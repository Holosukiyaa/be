"""Ship loop: start → pack → ingest → verify → finish. Human runs SQL."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import catalog
from . import managed
from .managed import ChainBroken
from .pack import (
    assemble,
    choose_parts,
    claim_focus,
    decide_mode,
    pack_ok,
    parse_parts,
)
from .finding import (
    _ban_verdict,
    _formal_finding,
    _layer_title,
    _layer_why,
    _mark_trail_seen,
    _offers_from_ingest,
    _oral_label,
    _push_trail,
    _write_map,
    next_action as _next_action,
    parse_acc,
    parse_amounts,
    parse_months,
    ticket_profile,
)
from .paste import (
    _amounts_found,
    _column_fuse,
    _mb_stats,
    _mop_stats,
    _sum_mop_column,
    is_empty_ingest,
    is_ora_00942,
    normalize_plsql_grid,
)
from .review import build_review, evidence_fingerprint


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_path() -> Path:
    return managed.be_home() / "current.json"


def load_current() -> dict[str, Any] | None:
    path = _current_path()
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError:
        try:
            blob, _ = json.JSONDecoder().raw_decode(raw.lstrip())
        except json.JSONDecodeError:
            return None
    return blob if isinstance(blob, dict) else None


def save_current(case: dict[str, Any] | None) -> None:
    path = _current_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if case is None:
        if path.is_file():
            path.unlink()
        return
    path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cid = str(case.get("id") or "")
    if cid:
        dest = managed.cases_dir() / f"{cid}.json"
        dest.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_CHAT_LOCK = threading.Lock()


def chat_path() -> Path:
    return managed.be_home() / "chat.json"


def load_chat() -> list[dict[str, Any]]:
    path = chat_path()
    if not path.is_file():
        return []
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return blob if isinstance(blob, list) else []


def clear_chat() -> None:
    with _CHAT_LOCK:
        path = chat_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]\n", encoding="utf-8")


def new_chat() -> dict[str, Any]:
    """Drop open case and chat. Does not write abandoned history."""
    save_current(None)
    clear_chat()
    run = managed.be_home() / "run.sql"
    if run.is_file():
        run.write_text("", encoding="utf-8")
    try:
        from . import agent as agent_mod

        agent_mod.reset_agent()
    except Exception:
        pass
    _html()
    return {"schema": "be.new.v1", "ok": True}


def append_chat(role: str, text: str) -> None:
    with _CHAT_LOCK:
        items = load_chat()
        items.append({"t": _now(), "role": role, "text": text or ""})
        path = chat_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _turn(case: dict[str, Any], role: str, text: str) -> None:
    case.setdefault("thread", [])
    case["thread"].append({"t": _now(), "role": role, "text": text or ""})


def _html() -> None:
    try:
        from .gui import write_archive

        write_archive(browse=False)
    except OSError:
        pass


def _note(kind: str, seq: int, detail: str = "") -> None:
    path = managed.be_home() / "usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"t": _now(), "lane": "ship", "seq": seq, "kind": kind, "detail": detail}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _invalidate_delivery(case: dict[str, Any]) -> None:
    """Any evidence or draft change invalidates an earlier delivery decision."""
    case["review"] = None
    case["confirmed"] = False
    if str(case.get("process") or "") in {"reviewed", "confirmed"}:
        case["process"] = "active"


def _fragment_view(claim: str) -> dict[str, Any]:
    catalog.ensure_fragments()
    meta = catalog.list_fragments(include_body=False)
    return {"need": [], "fragments": meta, "missing_proven": []}


def _drop_unassembled_sql(case: dict[str, Any]) -> dict[str, Any]:
    """Old whole-pack SQL was hard-wired. Keep only fragment-assembled packs."""
    sql = str(case.get("sql") or "")
    if sql and "parts:" not in sql:
        case["sql"] = ""
        case["ingest"] = ""
        case["verify"] = None
        if str(case.get("process") or "") in {"packed", "ingested", "verified", "drafted"}:
            case["process"] = "active"
        run = managed.be_home() / "run.sql"
        if run.is_file():
            blob = run.read_text(encoding="utf-8")
            if "parts:" not in blob:
                run.write_text("", encoding="utf-8")
        save_current(case)
    return case


def status() -> dict[str, Any]:
    catalog.init()
    case = load_current()
    if case:
        case = _drop_unassembled_sql(case)
    process = "idle"
    product = "undeclared"
    view: dict[str, Any] = {}
    if case:
        process = str(case.get("process") or "active")
        product = str(case.get("product") or "pending")
        view = _fragment_view(str(case.get("claim") or ""))
        view.update(
            decide_mode(
                str(case.get("claim") or ""),
                list(case.get("uncovered") or view.get("missing_proven") or []),
                similar=True,
            )
        )
        if case.get("mode"):
            view["mode"] = case.get("mode")
            view["reminder"] = case.get("reminder") or view.get("reminder")
            view["uncovered"] = case.get("uncovered") or view.get("uncovered")
    return {
        "schema": "be.status.v1",
        "process": process,
        "product": product,
        "case": case,
        **view,
        "reminder": view.get("reminder")
        or "reuse=verified fragments; explore=remind user, never hard-wire.",
    }


def start(
    *,
    ticket_id: str = "",
    acc_num: str = "",
    months: str = "",
    claim: str = "",
    ticket_text: str = "",
) -> dict[str, Any]:
    catalog.init()
    blob = (ticket_text or "") or (claim or "")
    acc = parse_acc(blob, acc_num)
    from_ticket = parse_months(blob + " " + (claim or ""), "")
    from_ai = parse_months("", months)
    month_list = from_ticket or from_ai
    claim_text = claim_focus(blob) or (claim or "").strip() or (blob.strip()[:800] if blob.strip() else "")
    tid = (ticket_id or "").strip()
    if not tid:
        found = re.search(r"(?:工单|工單)\s*OID\s*[:：]?\s*(\d+)", blob, re.I)
        if found:
            tid = found.group(1)
    cur = load_current()
    if cur and (
        (acc and str(cur.get("acc_num") or "") == acc)
        or (tid and str(cur.get("ticket_id") or "") == tid)
    ):
        return {
            "schema": "be.start.v1",
            "case": cur,
            "hint": "本案已锁定，不要重开。请贴回 SQL 结果或点「结果为空」。",
            "next": "be_ingest" if cur.get("sql") else "be_pack",
        }
    if not acc:
        if cur and cur.get("acc_num"):
            return {
                "schema": "be.start.v1",
                "case": cur,
                "hint": "本案已锁定，不要重开。空结果请点「结果为空」。",
                "next": "be_ingest" if cur.get("sql") else "be_pack",
            }
        raise ChainBroken("acc_num required (8-digit)")
    if not month_list:
        raise ChainBroken("months required, e.g. 202608 or 202607,202608")
    if not claim_text:
        raise ChainBroken("claim required (主张)")
    case = {
        "id": str(uuid.uuid4())[:8],
        "ticket_id": tid,
        "acc_num": acc,
        "months": month_list,
        "claim": claim_text,
        "slots": {"acc_num": acc, "months": month_list, "claim": claim_text[:240]},
        "amounts": parse_amounts(claim_text or blob),
        "profile": ticket_profile(claim_text or blob),
        "sql": "",
        "ingest": "",
        "verify": None,
        "review": None,
        "confirmed": False,
        "process": "active",
        "product": "pending",
        "created": _now(),
    }
    gold = catalog.gold_for(ticket_id, acc)
    if gold:
        case["gold"] = gold
        extra = [x.strip() for x in str(gold.get("expect_amounts") or "").split(",") if x.strip()]
        for item in extra:
            if item not in case["amounts"]:
                case["amounts"].append(item)
    _turn(case, "user", "槽位 号码 {acc} 月份 {months} 主张 {claim}".format(
        acc=acc, months=",".join(month_list), claim=claim_text[:200]
    ))
    save_current(case)
    similar = catalog.similar_cases(
        str(case.get("claim") or blob),
        exclude_ticket=str(case.get("ticket_id") or ""),
        exclude_acc=acc,
        limit=3,
    )
    if similar:
        bits = []
        for item in similar:
            bits.append(f"{item.get('ticket_id')}: {item.get('finding')}")
        _turn(case, "sys", "相似旧单\n" + "\n".join(bits))
        save_current(case)
    view = _fragment_view(str(case.get("claim") or ""))
    info = decide_mode(str(case.get("claim") or ""), view["missing_proven"], similar)
    case["mode"] = info["mode"]
    case["reminder"] = info["reminder"]
    case["uncovered"] = info["uncovered"]
    case["confidence"] = info["confidence"]
    if info["mode"] == "explore":
        case["explore_n"] = int(case.get("explore_n") or 0) or 1
    else:
        case["explore_n"] = 0
    view.update(info)
    _turn(case, "sys", info["reminder"])
    save_current(case)
    _html()
    _note("help", 3, info["mode"])
    return {
        "schema": "be.start.v1",
        "case": case,
        "similar": similar,
        **view,
        "slots": case["slots"],
        "hint": info["reminder"] + " Then be_pack(parts=) with proven fragments only.",
        "next": "be_pack",
    }


def sql_fp(sql: str) -> str:
    return hashlib.sha1((sql or "").encode("utf-8")).hexdigest()[:12]


def stamp_sql_round(case: dict[str, Any], sql: str) -> bool:
    """New SQL body → new round, copied=false. Same body stays."""
    blob = (sql or "").strip()
    if not blob:
        case["sql_fp"] = ""
        case["sql_round"] = 0
        case["sql_copied"] = False
        case["sql_copied_n"] = 0
        return False
    fp = sql_fp(blob)
    if str(case.get("sql_fp") or "") == fp:
        return False
    case["sql_fp"] = fp
    case["sql_round"] = int(case.get("sql_round") or 0) + 1
    case["sql_copied"] = False
    case["sql_copied_n"] = 0
    return True


def mark_sql_copied() -> dict[str, Any]:
    case = load_current()
    if not case or not str(case.get("sql") or "").strip():
        raise ChainBroken("no sql to copy")
    stamp_sql_round(case, str(case.get("sql") or ""))
    n = int(case.get("sql_copied_n") or 0) + 1
    case["sql_copied"] = True
    case["sql_copied_n"] = n
    save_current(case)
    return {
        "sql_round": int(case.get("sql_round") or 1),
        "sql_copied": True,
        "sql_copied_n": n,
    }


def pack(parts: str = "") -> dict[str, Any]:
    case = load_current()
    if not case:
        raise ChainBroken("没有开单，请先贴工单锁定。")
    case = _drop_unassembled_sql(case)
    if not case.get("acc_num") or not case.get("months") or not str(case.get("claim") or "").strip():
        raise ChainBroken("slots first: acc_num, months, claim. be_start before be_pack")
    view = _fragment_view(str(case.get("claim") or ""))
    chosen = parse_parts(parts)
    if not chosen:
        _note("block", 2, "pack without parts")
        raise ChainBroken("点名碎片，例如 members,data_fee")
    chosen, extras = choose_parts(
        str(case.get("claim") or ""),
        chosen,
        ingest=str(case.get("ingest") or ""),
        mode=str(case.get("mode") or "reuse"),
        sql=str(case.get("sql") or ""),
        last_parts=parse_parts(case.get("parts") or []),
        tried_tables=list(case.get("tried_tables") or []),
        missing_proven=list(view.get("missing_proven") or []),
        need=list(view.get("need") or []),
    )
    if "tried_tables" in extras:
        case["tried_tables"] = extras["tried_tables"]
    if extras.get("trial_table"):
        case["trial_table"] = extras["trial_table"]
    try:
        sql = assemble(
            str(case["acc_num"]),
            list(case["months"]),
            chosen,
            ticket_id=str(case.get("ticket_id") or ""),
            claim=str(case.get("claim") or ""),
            mode=str(case.get("mode") or "reuse"),
            uncovered=list(case.get("uncovered") or []),
        )
    except ChainBroken as exc:
        _note("block", 2, str(exc)[:200])
        raise
    if str(sql or "").strip() == str(case.get("sql") or "").strip():
        raise ChainBroken("explore already emitted this SQL; do not repeat")
    fails = pack_ok(sql, str(case["acc_num"]), parts=chosen)
    if fails:
        _note("block", 2, ";".join(fails))
        raise ChainBroken("pack refused: " + "; ".join(fails))
    had_sql = bool(str(case.get("sql") or "").strip())
    if str(case.get("mode") or "") == "explore":
        n = int(case.get("explore_n") or 1)
        case["explore_n"] = n + 1 if had_sql else max(n, 1)
    case["sql"] = sql
    stamp_sql_round(case, sql)
    case["parts"] = chosen
    case["process"] = "packed"
    case["ingest"] = ""
    case["verify"] = None
    _invalidate_delivery(case)
    case["action"] = {
        "code": "be_ingest",
        "title": "请跑这一包",
        "detail": "复制右侧 SQL，整份执行，把结果贴回对话框。空点「结果为空」。ORA-00942 把报错原文贴回来。",
    }
    remind = str(case.get("reminder") or "")
    if case.get("mode") == "explore":
        tag = "【探索 第" + str(case.get("explore_n") or 1) + "次】" + remind + " "
    else:
        tag = "【复用】"
    prev_seen = ""
    if case.get("trail"):
        prev_seen = str((case["trail"][-1] or {}).get("seen") or "")
    layer = _layer_title(chosen)
    why = _layer_why(chosen, prev_seen)
    _push_trail(case, name=layer, parts=chosen, why=why, status="packed")
    _turn(
        case,
        "agent",
        tag
        + f"## 请跑第{len(case.get('trail') or [])}层（{layer}）\n\n"
        + why
        + "\n\n复制右侧 SQL **整份**执行。"
        + "整份跑完把结果贴回。贴回即这一包的全部权威结果，不会再要其他段。",
    )
    save_current(case)
    _note("help", 2, ",".join(chosen))
    out = managed.be_home() / "run.sql"
    out.write_text(sql, encoding="utf-8")
    _html()
    html_path = str(managed.be_home() / "archive.html")
    return {
        "schema": "be.pack.v1",
        "sql": sql,
        "parts": chosen,
        "path": str(out),
        "html": html_path,
        "instruction": "SQL 在右侧。整份复制到新窗口执行，不要改。无行点「结果为空」。",
        "next": "be_ingest",
    }


def ingest(text: str) -> dict[str, Any]:
    case = load_current()
    if not case or not case.get("sql"):
        raise ChainBroken("pack first")
    raw = (text or "").strip()
    empty = is_empty_ingest(raw)
    ora = is_ora_00942(raw)
    if not empty and not ora:
        raw = normalize_plsql_grid(raw)
    if empty:
        raw = "空"
    prev = str(case.get("ingest") or "").strip()
    if prev and prev != "空" and not empty and not ora:
        if raw.strip() in prev:
            raw = prev
        else:
            raw = prev.rstrip() + "\n" + raw
    case["ingest"] = raw
    case["process"] = "ingested"
    case["product"] = "pending"
    case["verify"] = None
    _invalidate_delivery(case)
    if empty:
        _turn(case, "user", "贴回结果：空（查询无行）")
    elif ora:
        _turn(case, "user", "贴回结果：ORA-00942 表不存在（OCS_LINK）")
    else:
        _turn(case, "user", "贴回结果\n" + raw)
    _mark_trail_seen(case, raw)
    trail = list(case.get("trail") or [])
    if trail:
        step = trail[-1]
        _turn(case, "sys", f"第{step.get('n')}层「{step.get('name')}」已贴回：**{step.get('seen') or '本层无加总行'}**")
    save_current(case)
    checked = verify()
    action = checked.get("action") or {}
    return {
        "schema": "be.ingest.v1",
        "chars": len(raw),
        "empty": empty,
        "display": "空（查询无行）" if empty else raw,
        "verify": {
            k: checked.get(k)
            for k in ("product", "process_ok", "note", "next", "amount_hits", "fuse_fail")
            if k in checked
        },
        "action": action,
        "next": checked.get("next") or "be_verify",
    }


def verify() -> dict[str, Any]:
    case = load_current()
    if not case:
        raise ChainBroken("no open case")
    sql = str(case.get("sql") or "")
    ingest_text = str(case.get("ingest") or "")
    if not ingest_text.strip():
        raise ChainBroken(
            "还没跑 SQL。请复制右侧整份执行，把结果贴回对话框（无行点「结果为空」）。未贴回不能核对、不能结案。"
        )
    view = _fragment_view(str(case.get("claim") or ""))
    case["uncovered"] = view["missing_proven"]
    compact_in = ingest_text.replace(" ", "").replace("\t", "").lower()
    if "qc_mop" in compact_in or "qv_mop" in compact_in:
        case["uncovered"] = [
            u for u in case["uncovered"] if not str(u).startswith("voice_")
        ]
    process_fails = (
        pack_ok(sql, str(case["acc_num"]), parts=list(case.get("parts") or []))
        if sql
        else ["no pack"]
    )
    result_fails: list[str] = []
    if not ingest_text:
        result_fails.append("no ingest")
    wanted = [str(x) for x in (case.get("amounts") or [])]
    hits = _amounts_found(ingest_text, wanted) if ingest_text else {}
    mop_sum = _sum_mop_column(ingest_text) if ingest_text else None
    if mop_sum is not None:
        for amt in wanted:
            try:
                if abs(float(amt) - mop_sum) < 0.06:
                    hits[amt] = True
            except ValueError:
                pass
    missing = [k for k, ok in hits.items() if not ok]
    gold = case.get("gold") if isinstance(case.get("gold"), dict) else None
    only_main = False
    expect_accs = [
        x.strip()
        for x in str((gold or {}).get("expect_accs") or "").split(",")
        if x.strip()
    ]
    if gold and expect_accs:
        if (
            ingest_text
            and not is_empty_ingest(ingest_text)
            and not is_ora_00942(ingest_text)
        ):
            seen = set(re.split(r"\D+", ingest_text))
            missing_accs = [acc for acc in expect_accs if acc not in seen]
            if missing_accs:
                for acc in missing_accs:
                    result_fails.append(f"金标准要求见到 {acc}")
                only_main = True
                _note("block", 1, "main-only")
    fuse = _column_fuse(ingest_text, list(case.get("parts") or []))
    fuse_fail = bool(fuse)
    if fuse:
        result_fails.extend(fuse)
        _note("block", 5, ";".join(fuse))
    note = "amounts missing in this table" if missing else "amounts traced"
    if missing:
        result_fails.append("amounts not in ingest: " + ",".join(missing) + " (say 本表未找到 if finishing without them)")
    if fuse_fail:
        note = fuse[0]
    ok_process = not process_fails
    product = "passed" if ok_process and ingest_text and not only_main and not fuse_fail else "failed"
    if missing and product == "passed":
        product = "passed_partial"
        note = "主张金额未能从行加总找到"
    if wanted and not missing and product == "passed":
        note = "证据已找到：主张金额可从话单行加总"
    elif not wanted and product == "passed" and not is_empty_ingest(ingest_text):
        product = "passed_partial"
        note = "无主张金额。用量类请核 Q1_MB，不要当通话费已找到。"
    if is_empty_ingest(ingest_text) and ok_process and not fuse_fail and not only_main:
        if str(case.get("mode") or "") == "explore":
            product = "explore"
            note = "空结果：本表未找到。探索不能结案。"
        else:
            product = "passed_partial"
            note = "空结果：本表未找到"
    ora = is_ora_00942(ingest_text)
    if ora:
        product = "explore" if str(case.get("mode") or "") == "explore" else "failed"
        note = "ORA-00942：OCS_LINK 上没有这张月表"
    if str(case.get("mode") or "") == "explore" and product == "passed_partial":
        product = "explore"
        note = str(case.get("reminder") or note)
    if str(case.get("mode") or "") == "explore" and product == "passed":
        note = "证据已找到：主张金额可从话单行加总"
    action = _next_action(
        case,
        empty=is_empty_ingest(ingest_text),
        product=product,
        fuse_fail=fuse_fail,
        only_main=only_main,
        ok_process=ok_process,
        ora=ora,
        fuse=fuse,
    )
    verify_blob = {
        "process_ok": ok_process,
        "process_fails": process_fails,
        "result_fails": result_fails,
        "amount_hits": hits,
        "mop_sum": mop_sum,
        "only_main_fail": only_main,
        "fuse_fail": fuse_fail,
        "product": product,
        "note": note,
        "action": action,
    }
    case["verify"] = verify_blob
    case["product"] = product
    case["action"] = action
    case["process"] = "verified" if ok_process and not fuse_fail else "active"
    _turn(case, "sys", "下一步：" + str(action.get("title") or "") + "\n\n" + str(action.get("detail") or ""))
    save_current(case)
    _html()
    if ok_process and not fuse_fail:
        _note("help", 5, product)
    elif process_fails:
        _note("block", 2, ";".join(process_fails))
    return {"schema": "be.verify.v1", **verify_blob, "next": action.get("code") or "be_pack", "action": action}


def finish() -> dict[str, Any]:
    case = load_current()
    if not case:
        raise ChainBroken("no open case")
    verify_blob = case.get("verify") if isinstance(case.get("verify"), dict) else None
    if not verify_blob:
        raise ChainBroken("be_verify first")
    if not verify_blob.get("process_ok"):
        _note("block", 1, "finish without process")
        raise ChainBroken("process not ok; cannot finish")
    if verify_blob.get("only_main_fail"):
        raise ChainBroken("主号-only ingest cannot finish this gold ticket")
    if verify_blob.get("fuse_fail"):
        raise ChainBroken("column fuse failed; paste this pack's Q1_* or QC_*/QV_* grid, not an old window")
    if str(case.get("mode") or "") == "explore" and list(case.get("uncovered") or []):
        raise ChainBroken(
            "explore: missing proven fragments; do not finish. admit voice_fee/voice_charged first."
        )
    ingest_text = str(case.get("ingest") or "")
    _ban_verdict(ingest_text)
    mop_sum, mop_n = _mop_stats(ingest_text)
    hits = verify_blob.get("amount_hits") if isinstance(verify_blob.get("amount_hits"), dict) else {}
    covered = [k for k, ok in hits.items() if ok]
    missing = [k for k, ok in hits.items() if not ok]
    formal = _formal_finding(case, covered=covered, missing=missing)
    lock_why = str(formal.get("verdict") or "锁定")
    _push_trail(
        case,
        name="锁定",
        parts=["lock"],
        why=lock_why,
        status="locked",
    )
    if case.get("trail"):
        case["trail"][-1]["labels"] = ["锁定目标"]
        case["trail"][-1]["seen"] = str(formal.get("money") or "")[:120]
        _write_map(case)
        formal = _formal_finding(case, covered=covered, missing=missing)
    draft = {
        "verdict": formal["verdict"],
        "money": formal["money"],
        "claimant": formal["claimant"],
        "gap": formal["gap"],
        "charts": formal.get("charts") or {},
        "report": formal.get("report") or "",
        "mop_sum": mop_sum,
        "mop_n": mop_n,
        "product": case.get("product"),
        "mode": case.get("mode"),
    }
    case["process"] = "drafted"
    case["draft"] = draft
    case["review"] = build_review(case, draft)
    case["confirmed"] = False
    if str(case["review"].get("status") or "") == "passed":
        case["process"] = "reviewed"
        case["action"] = {
            "code": "be_confirm",
            "title": "核验通过，等待人工确认",
            "detail": "请确认当前草稿与证据一致后再归档。",
        }
    else:
        case["process"] = "review_pending"
        case["action"] = {
            "code": "be_finish",
            "title": "核验发现缺口",
            "detail": str(case["review"].get("summary") or "请补证或收窄结论后重新出稿。"),
        }
    _turn(case, "agent", str(draft.get("report") or draft["verdict"]))
    save_current(case)
    _html()
    return {
        "schema": "be.finish.v1",
        "draft": draft,
        "case_id": case.get("id"),
        "review": case["review"],
        "next": "be_confirm" if case["process"] == "reviewed" else "be_finish",
        "hint": "核验通过后请先 be_confirm，再 be_archive。" if case["process"] == "reviewed" else "请根据核验缺口补证或收窄结论后重新出稿。",
    }


def review() -> dict[str, Any]:
    """Re-run the deterministic review for the current draft."""
    case = load_current()
    if not case:
        raise ChainBroken("no open case")
    draft = case.get("draft") if isinstance(case.get("draft"), dict) else None
    if not draft:
        raise ChainBroken("be_finish first")
    result = build_review(case, draft)
    case["review"] = result
    case["confirmed"] = False
    case["process"] = "reviewed" if result.get("status") == "passed" else "review_pending"
    case["action"] = {
        "code": "be_confirm" if case["process"] == "reviewed" else "be_finish",
        "title": "核验通过，等待人工确认" if case["process"] == "reviewed" else "核验发现缺口",
        "detail": str(result.get("summary") or ""),
    }
    _turn(case, "sys", str(result.get("summary") or ""))
    save_current(case)
    _html()
    return {"schema": "be.review.v1", "review": result, "next": case["action"]["code"]}


def confirm() -> dict[str, Any]:
    """Record an explicit human confirmation for the current reviewed version."""
    case = load_current()
    if not case:
        raise ChainBroken("no open case")
    review_blob = case.get("review") if isinstance(case.get("review"), dict) else {}
    if str(case.get("process") or "") != "reviewed" or review_blob.get("status") != "passed":
        raise ChainBroken("review must pass before human confirmation")
    if review_blob.get("fingerprint") != evidence_fingerprint(case, case.get("draft")):
        raise ChainBroken("review is stale; run be_review again")
    case["confirmed"] = True
    case["confirmed_fingerprint"] = str(review_blob.get("fingerprint") or "")
    case["process"] = "confirmed"
    case["action"] = {
        "code": "be_archive",
        "title": "已确认，可以归档",
        "detail": "当前证据与草稿已确认，归档会写入历史。",
    }
    _turn(case, "user", "人工确认当前证据与草稿")
    save_current(case)
    _html()
    return {"schema": "be.confirm.v1", "status": "confirmed", "next": "be_archive"}


def _persist(case: dict[str, Any], *, status: str, finding: str, note: str = "") -> None:
    catalog.remember_case(
        ticket_id=str(case.get("ticket_id") or case.get("acc_num") or ""),
        acc_num=str(case.get("acc_num") or ""),
        months=",".join(case.get("months") or []),
        claim=str(case.get("claim") or "")[:500],
        finding=finding[:12000],
        amounts=",".join(str(x) for x in (case.get("amounts") or [])),
        note=note or str((case.get("gold") or {}).get("note") or ""),
        gold=1 if case.get("gold") else 0,
        status=status,
    )


def archive(finding: str = "") -> dict[str, Any]:
    case = load_current()
    if not case:
        raise ChainBroken("no open case")
    if str(case.get("process") or "") != "confirmed":
        raise ChainBroken("be_confirm first, then be_archive to 结档")
    review_blob = case.get("review") if isinstance(case.get("review"), dict) else {}
    if review_blob.get("status") != "passed":
        raise ChainBroken("review must pass before archive")
    if review_blob.get("fingerprint") != evidence_fingerprint(case, case.get("draft")):
        raise ChainBroken("review is stale; run be_review again")
    if not case.get("confirmed") or case.get("confirmed_fingerprint") != review_blob.get("fingerprint"):
        raise ChainBroken("human confirmation is required before archive")
    _ban_verdict(finding)
    draft = case.get("draft") if isinstance(case.get("draft"), dict) else {}
    _ban_verdict(" ".join(str(draft.get(k) or "") for k in ("money", "claimant", "gap")))
    text = (finding or "").strip() or str(draft.get("report") or "") or (
        str(draft.get("verdict") or "")
        + "\n"
        + str(draft.get("money") or "")
        + "\n"
        + str(draft.get("claimant") or "")
        + "\n"
        + str(draft.get("gap") or "")
    )
    ingest_text = str(case.get("ingest") or "")
    if not text.strip():
        text = " | ".join(ln.strip() for ln in ingest_text.splitlines() if ln.strip())[:800]
    _ban_verdict(text)
    case["process"] = "archived"
    _turn(case, "sys", "已结档")
    _persist(case, status="archived", finding=text.strip())
    cid = case.get("id")
    save_current(None)
    run = managed.be_home() / "run.sql"
    if run.is_file():
        run.write_text("", encoding="utf-8")
    _html()
    return {"schema": "be.archive.v1", "case_id": cid, "status": "archived"}


def abandon(reason: str = "") -> dict[str, Any]:
    case = load_current()
    why = (reason or "").strip()
    if case and str(case.get("process") or "") in {"packed", "ingested", "verified", "drafted"}:
        raise ChainBroken("open evidence cannot abandon; use 新对话 or be_archive after finish")
    if case:
        why = (reason or "").strip() or "未写原因"
        _turn(case, "sys", "废弃：" + why)
        _persist(case, status="abandoned", finding="废弃：" + why, note=why)
    cid = (case or {}).get("id")
    save_current(None)
    _html()
    return {"schema": "be.abandon.v1", "case_id": cid, "status": "abandoned"}
