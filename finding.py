"""Colleague report: oral, profile, finding, trail map."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .managed import ChainBroken
from .pack import (
    claim_focus,
    claim_kind,
    parse_parts,
)
from .paste import (
    _grid_brief,
    _mb_stats,
    _mop_value_tokens,
    _split_plsql_row,
)

# Require a separator so IMSI 20404336… is not read as year 2040.
MONTH_RE = re.compile(r"(20\d{2})\s*[-/年]\s*(0?[1-9]|1[0-2])")
YYYYMM_RE = re.compile(r"\b(20\d{2}(?:0[1-9]|1[0-2]))\b")
ACC_RE = re.compile(r"\b(\d{8})\b")
AMT_RE = re.compile(r"(?:MOP\s*\$?\s*)?(\d+\.\d{1,2})", re.I)
AMT_CONTEXT_RE = re.compile(
    r"(?:收费|收費|费用|費用|扣费|扣費|金额|金額|收取|被收|合计|合計)"
    r"\s*(?:为|為|是|了)?\s*(?:MOP|澳门元|澳門元|HKD|港币|港幣|元|\$)?"
    r"\s*(\d+(?:\.\d{1,2})?)",
    re.I,
)
AMT_SUFFIX_RE = re.compile(
    r"(\d+(?:\.\d{1,2})?)\s*(?:MOP|澳门元|澳門元|HKD|港币|港幣|元)",
    re.I,
)
VERDICT_BAN_RE = re.compile(r"计费无误|計費無誤")
# 在8月收费 / 9月產生 — 主张账期，不是回复期限。
CHARGE_MONTH_RE = re.compile(
    r"(?:在|於)?(?:(20\d{2})\s*[-/年]\s*)?(1[0-2]|0?[1-9])\s*月.{0,12}(?:收费|收費|產生|产生)"
)


def parse_months(text: str, explicit: str = "") -> list[str]:
    found: list[str] = []
    charge: list[str] = []
    explicit_yms: list[str] = []

    def add(bucket: list[str], ym: str) -> None:
        if ym and ym not in bucket:
            bucket.append(ym)

    for part in explicit.replace(";", ",").split(","):
        part = part.strip().replace("-", "")
        if re.fullmatch(r"20\d{2}(?:0[1-9]|1[0-2])", part):
            add(explicit_yms, part)
            add(found, part)
    blob = text or ""
    now = datetime.now(timezone.utc)
    for y, m in CHARGE_MONTH_RE.findall(blob):
        year = int(y) if y else now.year
        add(charge, f"{year}{int(m):02d}")
    if re.search(r"本月.{0,12}(?:收費|收费|產生|产生)|(?:收費|收费|產生|产生).{0,8}本月", blob):
        add(charge, f"{now:%Y%m}")
    for y, m in MONTH_RE.findall(blob):
        add(found, f"{y}{int(m):02d}")
    for token in YYYYMM_RE.findall(blob):
        add(found, token)
    for token in re.findall(r"(1[0-2]|0?[1-9])\s*月", blob):
        add(found, f"{now.year}{int(token):02d}")
    if re.search(r"本月|本帳期|本账期", blob):
        add(found, f"{now:%Y%m}")
    if re.search(r"上月|上個帳期|上个账期", blob):
        year, month = now.year, now.month - 1
        if month == 0:
            year, month = year - 1, 12
        add(found, f"{year}{month:02d}")
    if charge:
        out: list[str] = []
        for ym in explicit_yms:
            add(out, ym)
        for ym in charge:
            add(out, ym)
        return out
    return found


def parse_acc(text: str, explicit: str = "") -> str:
    if re.fullmatch(r"\d{8}", (explicit or "").strip()):
        return explicit.strip()
    nums = ACC_RE.findall(text or "")
    return nums[0] if nums else ""


def parse_amounts(text: str) -> list[str]:
    found: list[str] = []
    blob = text or ""
    for m in AMT_RE.finditer(blob):
        prefix = blob[max(0, m.start() - 16) : m.start()]
        if re.search(r"ARPU\s*值?\s*$", prefix, re.I):
            continue
        amt = m.group(1)
        if re.match(r"\s*(MB|GB|G)", blob[m.end() :], re.I):
            continue
        if amt not in found:
            found.append(amt)
    for m in re.finditer(r"MOP\s*\$?\s*(\d+)(?![\d.])", blob, re.I):
        prefix = blob[max(0, m.start() - 24) : m.start()]
        if re.search(r"計劃|计划|套餐", prefix):
            continue
        amt = m.group(1) + ".00"
        if amt not in found:
            found.append(amt)
    # Chinese tickets commonly write integer amounts such as “收费80元”.
    # Keep the context requirement so account numbers, months, and durations
    # are not mistaken for money.
    for pattern in (AMT_CONTEXT_RE, AMT_SUFFIX_RE):
        for m in pattern.finditer(blob):
            amt = m.group(1)
            if re.match(r"\s*(MB|GB|G)\b", blob[m.end() :], re.I):
                continue
            if amt not in found:
                found.append(amt)
    return found

def _offers_from_ingest(ingest_text: str) -> list[str]:
    """QO_NAME rows from the 在用套餐 grid. Not a tariff."""
    names: list[str] = []
    lines = [ln.rstrip() for ln in (ingest_text or "").splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        parts = _split_plsql_row(lines[i])
        low = [p.lower() for p in parts]
        if "qo_name" not in low:
            i += 1
            continue
        idx = low.index("qo_name")
        width = len(parts)
        i += 1
        while i < len(lines):
            cells = _split_plsql_row(lines[i])
            if not cells:
                i += 1
                continue
            cl = [c.lower() for c in cells]
            if any(
                x in cl
                for x in (
                    "qo_name",
                    "q0_acc",
                    "qc_mop",
                    "qv_mop",
                    "q1_mop",
                    "qc_ym",
                    "qv_ym",
                    "q1_ym",
                )
            ):
                break
            if cells[0].isdigit() and len(cells) == width + 1:
                cells = cells[1:]
            if idx < len(cells):
                name = cells[idx].strip()
                if name and name.lower() != "qo_name" and name not in names:
                    names.append(name)
            i += 1
    return names


def _deduct_brief(ingest_text: str) -> str:
    """How the offer billed: QN_ offer×event, QX_ std vs charge, QT_ sector."""
    bits: list[str] = []
    lines = [ln.rstrip() for ln in (ingest_text or "").splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        parts = _split_plsql_row(lines[i])
        low = [p.lower() for p in parts]
        if "qn_offer" in low and "qn_event" in low:
            io, ie = low.index("qn_offer"), low.index("qn_event")
            im = low.index("qn_mop") if "qn_mop" in low else -1
            imb = low.index("qn_mb") if "qn_mb" in low else -1
            i += 1
            while i < len(lines):
                cells = _split_plsql_row(lines[i])
                cl = [c.lower() for c in cells]
                if any(x in cl for x in ("qn_offer", "q1_ym", "qx_ym", "qt_ym", "qo_name")):
                    break
                if cells and cells[0].isdigit() and len(cells) > ie:
                    cells = cells[1:]
                if ie < len(cells) and io < len(cells):
                    offer, event = cells[io].strip(), cells[ie].strip()
                    mop = cells[im].strip() if im >= 0 and im < len(cells) else ""
                    mb = cells[imb].strip() if imb >= 0 and imb < len(cells) else ""
                    if event not in {"总计", "合計", "合计"}:
                        extra = []
                        if mb:
                            extra.append(f"{mb}MB")
                        if mop:
                            extra.append(f"{mop}澳门元")
                        bits.append(
                            f"批价挂在「{offer}」上的「{event}」"
                            + (("（" + "，".join(extra) + "）") if extra else "")
                        )
                i += 1
            continue
        if "qx_offer" in low and "qx_event" in low:
            io, ie = low.index("qx_offer"), low.index("qx_event")
            istd = low.index("qx_std") if "qx_std" in low else -1
            im = low.index("qx_mop") if "qx_mop" in low else -1
            i += 1
            while i < len(lines):
                cells = _split_plsql_row(lines[i])
                cl = [c.lower() for c in cells]
                if any(x in cl for x in ("qx_offer", "q1_ym", "qn_ym", "qt_ym")):
                    break
                if cells and cells[0].isdigit():
                    cells = cells[1:]
                if ie < len(cells) and io < len(cells):
                    std = cells[istd].strip() if istd >= 0 and istd < len(cells) else ""
                    mop = cells[im].strip() if im >= 0 and im < len(cells) else ""
                    bits.append(
                        f"扣费现场「{cells[ie]}」挂「{cells[io]}」实收{mop or '—'}标准费{std or '—'}"
                    )
                i += 1
            continue
        if "qt_event" in low or "qt_sector_id" in low:
            ie = low.index("qt_event") if "qt_event" in low else -1
            isc = low.index("qt_sector_id") if "qt_sector_id" in low else -1
            isp = low.index("qt_sponsor") if "qt_sponsor" in low else -1
            i += 1
            while i < len(lines):
                cells = _split_plsql_row(lines[i])
                cl = [c.lower() for c in cells]
                if any(x in cl for x in ("qt_event", "q1_ym", "qn_ym", "qx_ym")):
                    break
                if cells and cells[0].isdigit():
                    cells = cells[1:]
                ev = cells[ie].strip() if ie >= 0 and ie < len(cells) else ""
                sec = cells[isc].strip() if isc >= 0 and isc < len(cells) else ""
                sp = cells[isp].strip() if isp >= 0 and isp < len(cells) else ""
                if ev:
                    bits.append(f"资费扇区「{ev}」sector={sec or '—'} sponsor={sp or '—'}")
                i += 1
            continue
        i += 1
    # unique keep order
    out: list[str] = []
    for b in bits:
        if b not in out:
            out.append(b)
    return "；".join(out[:12])


def _formal_finding(
    case: dict[str, Any],
    *,
    covered: list[str],
    missing: list[str],
) -> dict[str, str]:
    ingest_text = str(case.get("ingest") or "")
    brief = _grid_brief(ingest_text)
    acc = str(case.get("acc_num") or "")
    months = ",".join(str(m) for m in (case.get("months") or []))
    ym = "、".join(brief.get("yms") or []) or months
    accs = "、".join(brief.get("accs") or []) or acc
    events = "、".join(brief.get("events") or []) or "有费科目"
    n = int(brief.get("n") or 0)
    mop = brief.get("mop")
    sec = int(brief.get("sec") or 0)
    mins = round(sec / 60.0, 1) if sec else None
    tmin = str(brief.get("tmin") or "")
    tmax = str(brief.get("tmax") or "")
    claim_amt = "、".join(covered or missing or [str(x) for x in (case.get("amounts") or [])])
    time_bit = f"通话时间自 {tmin} 至 {tmax}。" if tmin and tmax else ""
    dur_bit = f"通话时长合计 {sec} 秒（约 {mins} 分钟）。" if sec else ""
    offer_names = _offers_from_ingest(ingest_text)
    deduct = _deduct_brief(ingest_text)
    offer_bit = ""
    if deduct or offer_names:
        offer_bit = "三、套餐怎么扣\n"
        if deduct:
            offer_bit += deduct + "。"
        elif offer_names:
            offer_bit += "在用销售品：" + "、".join(offer_names) + "。尚未见到批价挂在哪条销售品上。"
        offer_bit += "\n\n"
    parts_now = parse_parts(case.get("parts") or [])
    if deduct:
        tariff_gap = "批价挂在哪个销售品、资费扇区已按贴回列出。单价公式仍可能不完整，不写「计费无误」。"
    elif any(p in parts_now for p in ("rated_offer", "roam_detail", "tariff_by_event")):
        tariff_gap = "贴回里没有批价/资费段，视为本包未产出，不要求补贴。"
    else:
        tariff_gap = "话单是批价结果；本单未贴资费段，不能复核单价。"
    kind = claim_kind(str(case.get("claim") or ""))
    data_claim = kind == "data"
    claim_blob = str(case.get("claim") or "")
    want = _customer_want(claim_blob)
    oral = _oral_label(claim_blob, data_claim=data_claim)
    unit = "笔" if data_claim else "通"
    kind_word = "流量" if data_claim else "通话"
    mb_total, _nmb = _mb_stats(ingest_text)
    prof = case.get("profile") if isinstance(case.get("profile"), dict) else ticket_profile(claim_blob)
    if str(prof.get("dispute") or "") == "usage" and mb_total is not None and (mop is None or mop == 0):
        gb = round(mb_total / 1024.0, 2)
        verdict = "用量已在科目汇总中找到（有费为0）"
        money = (
            f"账期 {ym}，号码 {accs}。科目「{events}」。"
            f"话单 Q1_MB 合计 **{mb_total}** MB（约 **{gb}** GB），费用 **0**。"
        )
        claimant = (
            f"客户要的是：{want.get('quote') or oral}。"
            "这些行费用为0，主张金额没对上。未核办理/通知类原因。"
        )
        gap = "套内 0 费。未判定计费对错。减免由相关人员评估。"
    elif covered and not missing and mop is not None:
        verdict = "证据已找到，口述不成立"
        money = (
            f"账期 {ym}，号码 {accs}。{kind_word}有费科目「{events}」，共 {n} {unit}。"
            f"{time_bit}{dur_bit}"
            f"话单合计 **{mop}** 澳门元，与主张 **{claim_amt}** 一致。"
        )
        claimant = (
            f"客户要的是：{want.get('quote') or oral}。"
            f"话单是 {n} {unit}、合计 {mop} 澳门元，与「{oral.replace('口述：', '')}」对不上。"
        )
        gap = f"未判定计费对错。{tariff_gap}减免由相关人员评估。"
    elif mop is not None:
        verdict = "话单合计与主张不一致"
        money = (
            f"账期 {ym}，号码 {accs}。{kind_word}有费科目「{events}」，共 {n} {unit}。"
            f"{time_bit}{dur_bit}"
            f"话单合计 **{mop}** 澳门元，客户主张 **{claim_amt}**，二者不一致。"
        )
        claimant = (
            f"客户要的是：{want.get('quote') or oral}。"
            "短信当时的累计可以小于整月话单合计，不能单凭短信金额结案。"
        )
        gap = f"差额还没用本表行解释完。未判定计费对错。{tariff_gap}减免由相关人员评估。"
    else:
        verdict = "本表未找到主张金额"
        money = (
            f"账期 {months or '—'}，号码 {acc or '—'}。"
            f"贴回结果里加总不出主张 **{claim_amt or '—'}** 澳门元。"
        )
        claimant = f"客户要的是：{want.get('quote') or oral}。须看科目汇总，不能把空表当没用过。"
        gap = f"未判定计费对错。{tariff_gap}减免由相关人员评估。"
    charts = _evidence_charts(
        brief,
        claim_amt=claim_amt,
        aligned=bool(covered and not missing),
        data_claim=data_claim,
        oral=oral,
    )
    want_md = want.get("quote") or oral
    deduct_md = ""
    if offer_bit:
        deduct_md = "\n### 套餐怎么扣\n" + offer_bit.replace("三、套餐怎么扣\n", "").strip() + "\n"
    report = (
        f"## 结论\n**{verdict}**\n\n"
        f"### 这张单客户要什么\n> {want_md}\n\n"
        f"### 话单对上了什么\n{money}\n\n"
        f"### 和口述差在哪\n{claimant}\n"
        f"{deduct_md}\n"
        f"### 还没核到 / 处理意见\n{gap}\n"
    )
    return {
        "verdict": verdict,
        "money": money,
        "claimant": claimant,
        "gap": gap,
        "offers": "、".join(offer_names),
        "charts": charts,
        "report": report,
    }


def _esc_mm(text: str) -> str:
    return (text or "").replace('"', "'").replace("\n", " ")


def _customer_want(claim: str) -> dict[str, str]:
    """This ticket's ask, from 投诉项目/详情 — not a canned oral."""
    blob = claim or ""
    item = ""
    for pat in (
        r"投訴具體項目[）)\]]*\s*[（(]([^）)]+)",
        r"投诉具体项目[）)\]]*\s*[（(]([^）)]+)",
    ):
        found = re.search(pat, blob)
        if found:
            item = found.group(1).strip()
            break
    detail = ""
    for pat in (r"【詳細情況】\s*(.+)", r"【详细情况】\s*(.+)"):
        found = re.search(pat, blob)
        if found:
            detail = re.sub(r"\s+", " ", found.group(1)).strip()
            break
    if not item and not detail:
        detail = claim_focus(blob) or blob
        detail = re.sub(r"\s+", " ", detail).strip()
    if len(detail) > 160:
        detail = detail[:160] + "…"
    quote = "；".join(x for x in (item, detail) if x)
    return {"item": item, "detail": detail, "quote": quote}


def _oral_label(claim: str, *, data_claim: bool) -> str:
    blob = claim or ""
    if re.search(r"幾分鐘|几分钟", blob):
        return "口述：才打了几分钟"
    if re.search(r"關閉.{0,12}漫遊|关闭.{0,12}漫游|流動網絡已經關閉|流动网络已经关闭", blob):
        return "口述：已关闭数据漫游"
    if re.search(r"用得[好太]快", blob):
        return "口述：流量用得太快"
    if re.search(r"沒出過國|没出过国|未出過國|身處內地.{0,12}未", blob):
        return "口述：未出国却收国际漫游"
    want = _customer_want(blob)
    if want.get("item"):
        return "口述：" + want["item"][:28]
    return "口述：客户主张" if data_claim else "口述：通话收费不合理"


def ticket_profile(claim: str) -> dict[str, Any]:
    """Route in code. The model must not pick the next layer."""
    blob = claim or ""
    kind = claim_kind(blob)
    has_mb = bool(re.search(r"\d+(?:\.\d+)?\s*(MB|GB|G)", blob, re.I))
    has_money = bool(re.search(r"(減免|收费|收費).{0,20}MOP", blob, re.I))
    date_span = bool(re.search(r"\d{1,2}\s*日.{0,12}\d{1,2}\s*日", blob))
    if kind == "voice":
        dispute = "voice"
    elif has_mb and not has_money:
        dispute = "usage"
    else:
        dispute = "money"
    return {
        "kind": kind,
        "dispute": dispute,
        "need_daily": bool(date_span or dispute == "usage"),
        "need_tariff": bool(kind == "data" and dispute == "money"),
        "oral": _oral_label(blob, data_claim=(kind == "data")),
    }


PART_LABEL = {
    "data_survey": "科目汇总",
    "data_by_day": "按日",
    "offers": "在用套餐",
    "data_roam": "漫游小区",
    "rated_offer": "批价套餐",
    "members": "主副卡",
    "data_fee": "池内科目",
    "data_charged": "有费行",
    "voice_fee": "通话科目",
    "voice_charged": "通话有费行",
    "voice_detail": "通话扣费现场",
    "voice_tariff": "通话资费扇区",
    "lock": "锁定目标",
}


def _layer_title(parts: list[str]) -> str:
    names = set(parts)
    if "data_survey" in names or "data_by_day" in names:
        return "普查"
    if "data_roam" in names or "rated_offer" in names or "members" in names:
        return "下探"
    if "voice_fee" in names or "voice_charged" in names:
        return "通话取证"
    return "取证"


def _layer_why(parts: list[str], seen: str = "") -> str:
    title = _layer_title(parts)
    if title == "普查":
        return "先查本号通用账（科目+按日+订购），再决定下探。"
    if "data_roam" in parts:
        return "普查见国际漫游有费，下探小区与批价套餐。" + (f" 依据：{seen}" if seen else "")
    if "members" in parts and "data_survey" not in parts:
        return "主张可能在共享池/副卡，下探主副卡。" + (f" 依据：{seen}" if seen else "")
    if title == "通话取证":
        return "投诉是通话费，查通话科目与有费行。"
    if seen:
        return "按上一层贴回下探。依据：" + seen
    return "按投诉下探。"


def _seen_from_ingest(text: str) -> str:
    brief = _grid_brief(text)
    events = [e for e in (brief.get("events") or []) if e and e not in {"总计", "合計", "合计"}]
    mop = brief.get("mop")
    bits: list[str] = []
    if events:
        bits.append("、".join(events[:6]))
    if mop is not None:
        bits.append(f"{mop} 澳门元")
    names = _offers_from_ingest(text)
    if names:
        bits.append("套餐 " + "、".join(names[:8]))
    return "；".join(bits)


def _trail_map(trail: list[dict[str, Any]]) -> str:
    if not trail:
        return ""
    lines = ["flowchart TB"]
    ids: list[str] = []
    for step in trail:
        n = int(step.get("n") or len(ids) + 1)
        sid = f"L{n}"
        labels = "、".join(step.get("labels") or step.get("parts") or []) or "—"
        seen = str(step.get("seen") or step.get("why") or "")
        title = f"第{n}层 {step.get('name') or ''}"
        lines.append(f'  {sid}["{_esc_mm(title)}<br/>{_esc_mm(labels)}<br/>{_esc_mm(seen[:90])}"]')
        ids.append(sid)
    for i in range(len(ids) - 1):
        why = _esc_mm(str((trail[i + 1].get("why") or "下探")[:40]))
        lines.append(f'  {ids[i]} -->|"{why}"| {ids[i + 1]}')
    lines += [
        "  classDef on fill:#fef3c7,stroke:#b45309,color:#1c1917",
        "  classDef done fill:#dcfce7,stroke:#166534,color:#14532d",
        "  classDef wait fill:#e7e5e4,stroke:#78716c,color:#44403c",
    ]
    for i, step in enumerate(trail):
        st = str(step.get("status") or "")
        cls = "on" if i == len(trail) - 1 else ("done" if st == "ingested" or st == "locked" else "wait")
        lines.append(f"  class {ids[i]} {cls}")
    return "\n".join(lines)


def _write_map(case: dict[str, Any]) -> None:
    trail = list(case.get("trail") or [])
    md = _trail_map(trail)
    case["map_md"] = ("```mermaid\n" + md + "\n```") if md else ""


def _push_trail(case: dict[str, Any], *, name: str, parts: list[str], why: str, status: str = "packed") -> None:
    trail = list(case.get("trail") or [])
    labels = [PART_LABEL.get(p, p) for p in parts] or [name]
    last = trail[-1] if trail else None
    if last and list(last.get("parts") or []) == list(parts) and last.get("name") == name:
        last["why"] = why or last.get("why")
        last["status"] = status
        last["labels"] = labels
    else:
        trail.append(
            {
                "n": len(trail) + 1,
                "name": name,
                "parts": list(parts),
                "labels": labels,
                "why": why,
                "seen": last.get("seen") if last and status == "locked" else "",
                "status": status,
            }
        )
    case["trail"] = trail
    _write_map(case)


def _mark_trail_seen(case: dict[str, Any], ingest_text: str) -> None:
    trail = list(case.get("trail") or [])
    if not trail:
        return
    seen = _seen_from_ingest(ingest_text)
    trail[-1]["seen"] = seen or trail[-1].get("seen") or ""
    trail[-1]["status"] = "ingested"
    case["trail"] = trail
    _write_map(case)


def _evidence_charts(
    brief: dict[str, Any],
    *,
    claim_amt: str,
    aligned: bool,
    data_claim: bool = False,
    oral: str = "",
) -> dict[str, Any]:
    n = int(brief.get("n") or 0)
    mop = brief.get("mop")
    sec = int(brief.get("sec") or 0)
    mins = round(sec / 60.0, 1) if sec else None
    events = "、".join(brief.get("events") or []) or "有费科目"
    fact_amt = f"话单费用合计 {mop} 澳门元" if mop is not None else "话单费用未能加总"
    oral = oral or ("口述：客户主张" if data_claim else "口述：通话收费不合理")
    if data_claim:
        fact_dur = f"{n} 笔流量行" if n else "未见流量汇总行"
        oral_edge = "对照话单行"
        subj = "流量证据"
    else:
        fact_dur = f"{n} 通，合计 {sec} 秒（约 {mins} 分钟）" if sec else f"{n} 通"
        oral_edge = "对照通话行"
        subj = "话单证据"
    ok_side = [
        {"label": f"主张金额 {claim_amt or '—'} 澳门元", "fact": fact_amt, "ok": aligned},
        {"label": "计费科目 / 主叫" if not data_claim else "计费科目 / 流量", "fact": events, "ok": True},
    ]
    bad_side = [
        {"label": oral, "fact": fact_dur, "ok": False},
    ]
    flow = [
        "flowchart TB",
        "  subgraph 客户口径",
        f'    A1["主张金额 { _esc_mm(claim_amt) } 澳门元"]',
        f'    A2["{_esc_mm(oral)}"]',
        "  end",
        f"  subgraph {subj}",
        f'    B1["{_esc_mm(events)} 共 {n} {"笔" if data_claim else "通"}"]',
        f'    B2["{_esc_mm(fact_dur)}"]',
        f'    B3["{_esc_mm(fact_amt)}"]',
        "  end",
    ]
    if aligned:
        flow.append('  A1 -->|"对上：金额已在话单中找到"| B3')
    else:
        flow.append('  A1 -->|"错位：金额未对上"| B3')
    flow.append(f'  A2 -->|"{oral_edge}"| B2')
    flow += [
        "  classDef ok fill:#dcfce7,stroke:#166534,color:#14532d",
        "  classDef bad fill:#fee2e2,stroke:#991b1b,color:#7f1d1d",
        "  class A1,B1,B3 ok" if aligned else "  class B1 ok",
        "  class A2,B2 bad",
    ]
    if not aligned:
        flow.append("  class A1,B3 bad")
    days: dict[str, list[str]] = {}
    for row in list(brief.get("rows") or []):
        tm = str(row.get("tm") or "")
        day = tm.split(" ")[0] if tm else ("流量" if data_claim else "通话")
        clock = tm.split(" ")[-1] if " " in tm else tm
        clock = clock.replace(":", "时", 1).replace(":", "分", 1)
        bit = f"{clock} {row.get('sec') or 0}秒 {row.get('mop')}元"
        days.setdefault(day, []).append(bit)
    time_lines = ["timeline", "    title " + ("流量有费行时间" if data_claim else "通话有费行时间")]
    for day, bits in days.items():
        if not bits:
            continue
        time_lines.append(f"    {day} : {bits[0]}")
        for extra in bits[1:]:
            time_lines.append(f"           : {extra}")
    mermaid_md = "```mermaid\n" + "\n".join(flow) + "\n```"
    if days:
        mermaid_md += "\n\n```mermaid\n" + "\n".join(time_lines) + "\n```"
    return {
        "ok": ok_side,
        "bad": bad_side,
        "rows": list(brief.get("rows") or []),
        "mermaid_flow": "\n".join(flow),
        "mermaid_time": "\n".join(time_lines),
        "mermaid_md": mermaid_md,
    }


def _ban_verdict(text: str) -> None:
    cleaned = re.sub(
        r"不写\s*计费无误|不寫\s*計費無誤|未判定[「\"“]计费无误[」\"”]",
        "",
        text or "",
    )
    if VERDICT_BAN_RE.search(cleaned):
        raise ChainBroken("ban: do not write 计费无误")

def next_action(
    case: dict[str, Any],
    *,
    empty: bool,
    product: str,
    fuse_fail: bool,
    only_main: bool,
    ok_process: bool,
    ora: bool = False,
    fuse: list[str] | None = None,
) -> dict[str, str]:
    uncovered = [str(x) for x in (case.get("uncovered") or []) if x]
    mode = str(case.get("mode") or "")
    if fuse_fail:
        raw = ""
        for item in fuse or []:
            if str(item).strip():
                raw = str(item).strip()
                break
        if not raw:
            prev = case.get("verify") if isinstance(case.get("verify"), dict) else {}
            note = str((prev or {}).get("note") or "")
            if note.startswith("column fuse:"):
                raw = note
        return {
            "code": "be_ingest",
            "title": "贴回的不是本包列名",
            "detail": raw or "列之间没有分隔，不要粘成 Q1_YMQ1_ACC；请从结果网格连表头复制（Tab 或两空格）。",
        }
    if only_main:
        gold = case.get("gold") if isinstance(case.get("gold"), dict) else {}
        accs = [
            x.strip()
            for x in str((gold or {}).get("expect_accs") or "").split(",")
            if x.strip()
        ]
        listed = "、".join(accs) if accs else "期望号码"
        return {
            "code": "be_ingest",
            "title": "只见主号，负例未过",
            "detail": f"必须见到金标准期望号码（{listed}）。不要写主号没有这笔。",
        }
    if not ok_process:
        return {
            "code": "be_pack",
            "title": "出包未过闸",
            "detail": "先按碎片重拼，不要改 SQL。",
        }
    ingest_now = str(case.get("ingest") or "")
    has_q1 = bool(re.search(r"\bq1_mop\b|\bq1_mb\b", ingest_now, re.I))
    fee_on = False
    for tok in _mop_value_tokens(ingest_now):
        try:
            if float(tok) > 0.005:
                fee_on = True
                break
        except ValueError:
            pass
    prof = case.get("profile") if isinstance(case.get("profile"), dict) else ticket_profile(str(case.get("claim") or ""))
    dispute = str(prof.get("dispute") or "")
    if dispute == "usage" and has_q1 and not fee_on:
        mb_total, _nmb = _mb_stats(ingest_now)
        amts = "、".join(str(x) for x in (case.get("amounts") or []) if x)
        return {
            "code": "be_pack",
            "title": "用量见到了，费用是0，先判断",
            "detail": (
                f"贴回有科目用量{(' '+str(mb_total)+' MB') if mb_total is not None else ''}，有费为0。"
                f"主张金额 {amts or '—'} 没在这些行里。"
                "不要套别的工单口径、不要直接结案。"
                "自己判断：金额是不是在别的月、是不是账单科目不是话单行、办理/通知是不是这张表回答不了。"
                "要再查就点名不同碎片或月份。禁止同一份 SQL。不要写计费无误。"
            ),
        }
    ingest_ym = [str(y) for y in (_grid_brief(ingest_now).get("yms") or [])]
    claim_ym = [str(m) for m in (case.get("months") or []) if m]
    miss_ym = [m for m in claim_ym if m not in ingest_ym]
    if dispute == "money" and not fee_on and miss_ym and ingest_ym:
        return {
            "code": "be_finish",
            "title": "贴回不是主张账期",
            "detail": (
                "主张账期 "
                + "、".join(claim_ym)
                + "，贴回见到 "
                + "、".join(ingest_ym)
                + "。本张表加不出主张金额。不要用别的月零费当这笔不存在。不要写计费无误。"
            ),
        }
    if ora:
        return {
            "code": "stop",
            "title": "表不存在",
            "detail": "OCS_LINK 上没有这张月表。把真实表名发回来再拼。不要再出同一份 SQL。不要写计费无误。",
        }
    if product == "passed":
        return {
            "code": "be_finish",
            "title": "证据已找到",
            "detail": "主张金额可从话单行加总对上。下一步写结论：钱在这些行里；口述哪句不成立；减免得人定。不要写未覆盖，不要写计费无误。",
        }
    if empty and mode == "explore":
        tried = parse_parts(case.get("parts") or [])
        if "voice_fee" not in tried and any(x.startswith("voice_") for x in uncovered):
            return {
                "code": "be_pack",
                "title": "数据表无行，下一包试跑语音",
                "detail": "本包无行。下一步 be_pack parts=members,voice_fee,voice_charged（探索试跑，未承认）。不要再出同一份数据 SQL。",
                "suggested_parts": "members,voice_fee,voice_charged",
            }
        miss = "、".join(uncovered) or "未覆盖碎片"
        return {
            "code": "stop",
            "title": "探索试跑仍空，不能结案",
            "detail": (
                "本包无行，记为「本表未找到」。"
                f"缺已验证碎片：{miss}。"
                "不要再出同一份 SQL。人承认正确语音表名后再拼。"
            ),
        }
    if empty:
        parts = parse_parts(case.get("parts") or [])
        last = parts[-1] if parts else ""
        months = "、".join(str(m) for m in (case.get("months") or []) if m)
        return {
            "code": "be_pack",
            "title": "空了，先判断为什么空",
            "detail": (
                "空不等于没用过，也不等于主张不成立。不要套「本表未找到」三句话。"
                f"本包 {','.join(parts) or '—'}，账期 {months or '—'}，最后一段 {last or '—'}。"
                "自己判断：是不是只看见有费行（套餐内0费会空）、当月月表是不是还没出账、"
                "主张是不是办理/通知根本不在话单表。要再查就点名不同碎片或补上期。禁止同一份 SQL。"
            ),
        }
    if mode == "explore" and uncovered:
        return {
            "code": "stop",
            "title": "探索未覆盖，不能结案",
            "detail": f"缺已验证碎片：{'、'.join(uncovered)}。贴回只证明已跑通部分。下一步：承认缺失碎片后再拼。",
        }
    return {
        "code": "be_finish",
        "title": "可以出三句话草稿",
        "detail": "核对已完成。金额须能从行加总。不写计费无误。减免给人。",
    }


