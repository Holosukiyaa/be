"""SQL fragments in sqlite. AI names the parts; this module stitches and gates."""
from __future__ import annotations

import re
from typing import Any

from .managed import ChainBroken

POOL_SQL = """
                 SELECT prod_inst_id
                   FROM usr_profile.prod_inst
                  WHERE acc_num = '{acc}'
                 UNION
                 SELECT d2.prod_inst_id
                   FROM usr_profile.offer_obj_inst_rel a
                   JOIN usr_profile.offer_inst b
                     ON a.offer_inst_id = b.offer_inst_id
                   JOIN usr_profile.prod_inst d2
                     ON a.obj_id = d2.prod_inst_id
                  WHERE b.offer_type = '11'
                    AND a.status_cd = '1000'
                    AND a.offer_inst_id IN (
                          SELECT a3.offer_inst_id
                            FROM usr_profile.offer_obj_inst_rel a3
                            JOIN usr_profile.offer_inst b3
                              ON a3.offer_inst_id = b3.offer_inst_id
                            JOIN usr_profile.prod_inst d3
                              ON a3.obj_id = d3.prod_inst_id
                           WHERE b3.offer_type = '11'
                             AND a3.status_cd = '1000'
                             AND d3.acc_num = '{acc}'
                        )
"""

VOICE_KEYS = ("通话", "通話", "致电", "致電", "语音", "語音", "拨打", "撥打")
DATA_KEYS = ("流量", "上网", "上網", "WAP", "数据", "數據")
ROAM_KEYS = ("漫游", "漫遊")
# 第一包一次复制：订购+按日+小区+批价+扣费现场+资费扇区+科目（科目放最后）。
# 第二包只在主副卡可疑时才出。
SURVEY_PARTS = (
    "offers",
    "data_by_day",
    "data_roam",
    "rated_offer",
    "roam_detail",
    "tariff_by_event",
    "data_survey",
)
DRILL_DATA_PARTS = ("members", "data_charged")
TARIFF_PARTS = ("roam_detail", "tariff_by_event")
DATA_PARTS = SURVEY_PARTS
VOICE_PARTS = (
    "members",
    "offers",
    "voice_fee",
    "voice_detail",
    "voice_charged",
)
POOL_PARTS = frozenset(
    {"members", "data_fee", "data_charged", "voice_fee", "voice_charged"}
)
SELF_SQL = "SELECT prod_inst_id FROM usr_profile.prod_inst WHERE acc_num = '{acc}'"

VOICE_FEE_BLUEPRINT = """SELECT '{ym}' AS qv_ym,
               d.acc_num AS qv_acc,
               e.name AS qv_event,
               COUNT(*) AS qv_cnt,
               SUM(NVL(t.duration, 0)) AS qv_sec,
               SUM(NVL(t.charge1, 0) + NVL(t.charge2, 0)
                   + NVL(t.charge3, 0) + NVL(t.charge4, 0)
                   + NVL(t.charge5, 0) + NVL(t.charge6, 0)) / 100 AS qv_mop
          FROM billdetail.{table}_{ym}@ocs_link t
          JOIN usr_profile.prod_inst d
            ON d.prod_inst_id = t.serv_id
          LEFT JOIN bill_conf.dest_event_type e
            ON e.event_type_id = t.event_type_id
         WHERE t.serv_id IN ({pool}
               )
         GROUP BY d.acc_num, e.name"""

VOICE_CHARGED_BLUEPRINT = """SELECT '{ym}' AS qc_ym,
               d.acc_num AS qc_acc,
               NVL(t.start_date, t.created_date) AS qc_tm,
               e.name AS qc_event,
               t.call_type AS qc_call_type,
               t.billing_nbr AS qc_billing,
               t.calling_nbr AS qc_calling,
               t.called_nbr AS qc_called,
               NVL(t.duration, 0) AS qc_sec,
               (NVL(t.charge1, 0) + NVL(t.charge2, 0)
                + NVL(t.charge3, 0) + NVL(t.charge4, 0)
                + NVL(t.charge5, 0) + NVL(t.charge6, 0)) / 100 AS qc_mop
          FROM billdetail.{table}_{ym}@ocs_link t
          JOIN usr_profile.prod_inst d
            ON d.prod_inst_id = t.serv_id
          LEFT JOIN bill_conf.dest_event_type e
            ON e.event_type_id = t.event_type_id
         WHERE t.serv_id IN ({pool}
               )
           AND (NVL(t.charge1, 0) + NVL(t.charge2, 0)
                + NVL(t.charge3, 0) + NVL(t.charge4, 0)
                + NVL(t.charge5, 0) + NVL(t.charge6, 0)) > 0"""

_ORDER = {
    "data_survey": "q1_ym, CASE WHEN q1_event = '总计' THEN 1 ELSE 0 END, q1_mop DESC",
    "data_by_day": "qd_ym, qd_day",
    "data_roam": "qr_ym, qr_mop DESC",
    "rated_offer": "qn_ym, qn_mop DESC",
    "roam_detail": "qx_ym, qx_tm",
    "tariff_by_event": "qt_ym, qt_event_id, qt_sector",
    "data_fee": "q1_ym, q1_mop DESC, q1_mb DESC",
    "data_charged": "q2_ym, q2_tm",
    "voice_fee": "qv_ym, qv_mop DESC",
    "voice_charged": "qc_ym, qc_tm",
    "voice_detail": "qx_ym, qx_tm",
    "voice_tariff": "qt_ym, qt_event_id, qt_sector",
}


def claim_focus(text: str) -> str:
    """Use 投诉项目/详情/产品名. Strip CRM chrome like 通话等级/无通话."""
    blob = text or ""
    bits: list[str] = []
    for pat in (
        r"投訴具體項目[）)\]]*\s*[（(]([^）)]+)",
        r"投诉具体项目[）)\]]*\s*[（(]([^）)]+)",
        r"【詳細情況】\s*(.+)",
        r"【详细情况】\s*(.+)",
        r"產品標識\s*([^\n]+)",
        r"产品标识\s*([^\n]+)",
        r"投訴類別\s*([^\n]+)",
        r"投诉类别\s*([^\n]+)",
    ):
        found = re.search(pat, blob)
        if found:
            bits.append(found.group(1).strip())
    if bits:
        return " ".join(bits)
    cleaned = re.sub(
        r"通話等級.{0,10}|通话等级.{0,10}|語音漫遊級別.{0,14}|语音漫游级别.{0,14}"
        r"|數據漫遊級別.{0,14}|数据漫游级别.{0,14}|無通話|无通话|本澳無漫遊|本澳无漫游",
        " ",
        blob,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def is_voice_claim(text: str) -> bool:
    return claim_kind(text) == "voice"


def claim_kind(claim: str) -> str:
    """voice | data | unclear — unclear is explore, not a silent default."""
    blob = claim or ""
    item = ""
    for pat in (
        r"投訴具體項目[）)\]]*\s*[（(]([^）)]+)",
        r"投诉具体项目[）)\]]*\s*[（(]([^）)]+)",
        r"投訴類別\s*([^\t\n]+)",
        r"投诉类别\s*([^\t\n]+)",
    ):
        found = re.search(pat, blob)
        if found:
            item = found.group(1)
            break
    if item:
        v = any(k in item for k in VOICE_KEYS)
        d = any(k in item for k in DATA_KEYS)
        if d and not v:
            return "data"
        if v and not d:
            return "voice"
    focused = claim_focus(claim) or blob
    focused = re.sub(
        r"(小姐|先生|客户|客戶)?致[电電]熱線|(小姐|先生|客户|客戶)致[电電][，,。]?",
        " ",
        focused,
    )
    voice = any(k in focused for k in VOICE_KEYS)
    data = any(k in focused for k in DATA_KEYS)
    roam = any(k in focused for k in ROAM_KEYS)
    if voice and not data:
        return "voice"
    if data and not voice:
        return "data"
    if voice and data:
        return "unclear"
    if roam:
        return "unclear"
    return "data"


def needed_parts(claim: str) -> list[str]:
    """Not a pack list. The model names parts; empty means no default pack."""
    return []


def drill_parts(claim: str) -> list[str]:
    kind = claim_kind(claim)
    if kind == "voice":
        return ["members", "voice_charged"]
    return list(DRILL_DATA_PARTS)


def tariff_parts(_claim: str = "") -> list[str]:
    return list(TARIFF_PARTS)


def decide_mode(claim: str, missing_proven: list[str], similar: list | None = None) -> dict:
    """reuse when kind is clear; explore only if unclear or caller passed uncovered."""
    missing = [m for m in (missing_proven or []) if m]
    kind = claim_kind(claim)
    if kind == "unclear" or missing:
        bits = []
        if missing:
            bits.append("缺已验证碎片 " + ",".join(missing))
        if kind == "unclear":
            bits.append("关键词分不清语音还是数据")
        if not similar:
            bits.append("没有相似旧单")
        return {
            "mode": "explore",
            "confidence": 0.0,
            "kind": kind,
            "uncovered": missing,
            "reminder": "探索，不是复用。" + "；".join(bits) + "。只能跑已跑通碎片，不能当结案。",
        }
    return {
        "mode": "reuse",
        # Reuse means the selected fragments have already been verified.
        # It is a workflow signal, not a statistical accuracy promise.
        "confidence": None,
        "kind": kind,
        "uncovered": [],
        "reminder": "复用已验证碎片；这表示流程可复用，不代表准确率承诺。",
    }


def parse_parts(parts: str | list[str] | None) -> list[str]:
    if isinstance(parts, list):
        raw = parts
    else:
        raw = (parts or "").replace(";", ",").split(",")
    out: list[str] = []
    for item in raw:
        name = str(item).strip()
        if name and name not in out:
            out.append(name)
    return out


def choose_parts(
    claim: str,
    requested: list[str],
    *,
    ingest: str = "",
    mode: str = "reuse",
    sql: str = "",
    last_parts: list[str] | None = None,
    tried_tables: list[str] | None = None,
    missing_proven: list[str] | None = None,
    need: list[str] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Keep the named fragments. Do not substitute a default survey/voice pack."""
    from .paste import is_ora_00942

    extras: dict[str, Any] = {}
    chosen = list(requested)
    if mode != "explore":
        return chosen, extras
    voice_named = any(n.startswith("voice_") for n in chosen)
    if voice_named:
        ensure_trial_voice()
    ingest_now = ingest or ""
    if voice_named and is_ora_00942(ingest_now):
        raise ChainBroken(
            "OCS_LINK 上没有这张月表。把真实表名发回来再拼。不要再出同一份 SQL。不要写计费无误。"
        )
    else:
        last = parse_parts(last_parts or [])
        if chosen and last and (sql or "").strip() and set(chosen) == set(last):
            raise ChainBroken(
                "explore already packed " + ",".join(last) + ". do not emit the same SQL."
            )
    return chosen, extras


def trial_voice_tables() -> tuple[str, ...]:
    from . import catalog

    catalog.init()
    names = []
    for row in catalog.list_kb_tables():
        parts = [p.strip() for p in str(row.get("fragment") or "").split(",") if p.strip()]
        if "voice_fee" in parts and str(row.get("name")) not in names:
            names.append(str(row["name"]))
    return tuple(names) or ("ocs_call_event",)


def trial_table_in_sql(sql: str) -> str:
    blob = (sql or "").lower()
    for name in trial_voice_tables():
        if name in blob:
            return name
    return ""


def next_trial_table(sql: str, tried: list[str] | None = None) -> str:
    seen = [t for t in (tried or []) if t]
    current = trial_table_in_sql(sql)
    if current and current not in seen:
        seen.append(current)
    for name in trial_voice_tables():
        if name not in seen:
            return name
    return ""


def ensure_trial_voice(table: str = "") -> None:
    """Unproven voice fragments for explore trial only. Does not overwrite admitted ones."""
    from . import catalog

    catalog.init()
    if not table:
        table = catalog.table_for_fragment("voice_fee") or "ocs_call_event"
    for kind in ("voice_fee", "voice_charged"):
        if catalog.get_fragment(kind):
            continue
        catalog.put_fragment(
            kind,
            voice_fragment_body(kind, table),
            kind=kind,
            proven=False,
            note=f"kb {table}",
        )


def rotate_trial_voice(table: str) -> None:
    """Rewrite unproven voice fragments to the next trial table."""
    from . import catalog

    catalog.init()
    for kind in ("voice_fee", "voice_charged"):
        row = catalog.get_fragment(kind)
        if row and int(row.get("proven") or 0):
            continue
        catalog.put_fragment(
            kind,
            voice_fragment_body(kind, table),
            kind=kind,
            proven=False,
            note=f"explore trial {table}",
        )


def voice_fragment_body(kind: str, table: str) -> str:
    table = (table or "").strip().lower()
    if not table.isidentifier() or table.startswith("_"):
        raise ChainBroken("voice table name not a safe identifier")
    if kind == "voice_fee":
        return VOICE_FEE_BLUEPRINT.replace("{table}", table)
    if kind == "voice_charged":
        return VOICE_CHARGED_BLUEPRINT.replace("{table}", table)
    raise ChainBroken("kind must be voice_fee or voice_charged")


def _fill(body: str, acc: str, ym: str) -> str:
    pool = POOL_SQL.format(acc=acc)
    self_sql = SELF_SQL.format(acc=acc)
    return (
        body.replace("{pool}", pool)
        .replace("{self}", self_sql)
        .replace("{ym}", ym)
        .replace("{acc}", acc)
    )


def _render_one(frag: dict[str, Any], acc: str, months: list[str]) -> str:
    kind = str(frag.get("kind") or frag.get("name") or "")
    body = str(frag.get("body") or "")
    name = str(frag.get("name") or kind)
    if kind in {"members", "offers"}:
        return f"-- {name}\n{_fill(body, acc, months[0])};\n"
    order = _ORDER.get(kind, "1")
    chunks: list[str] = []
    for ym in months:
        filled = _fill(body, acc, ym)
        chunks.append(
            f"-- {name} {ym}\nSELECT * FROM (\n{filled}\n) ORDER BY {order};\n"
        )
    return "\n".join(chunks)


def assemble(
    acc_num: str,
    months: list[str],
    parts: list[str],
    ticket_id: str = "",
    claim: str = "",
    mode: str = "reuse",
    uncovered: list[str] | None = None,
) -> str:
    acc = acc_num.strip()
    months = sorted({m.strip() for m in months if m.strip()})
    parts = parse_parts(parts)
    if not acc or not months:
        raise ChainBroken("acc_num and months required")
    if not parts:
        raise ChainBroken("点名碎片，例如 members,data_fee")
    from . import catalog

    catalog.init()
    catalog.ensure_fragments()
    by_name = {str(row["name"]): row for row in catalog.list_fragments(include_body=True)}
    pool_needed = any(p in POOL_PARTS for p in parts)
    if pool_needed and "members" not in parts:
        raise ChainBroken("members required (shared pool)")
    survey_pack = set(SURVEY_PARTS) <= set(parts)
    bits: list[str] = []
    trial: list[str] = []
    for name in parts:
        row = by_name.get(name)
        if not row:
            raise ChainBroken(
                f"unknown fragment {name}; stop. available: "
                + ",".join(sorted(by_name))
            )
        if not int(row.get("proven") or 0):
            if mode != "explore":
                raise ChainBroken(
                    f"fragment {name} is not proven (never run or not admitted); stop. do not hard-wire a guess."
                )
            trial.append(name)
        bits.append(_render_one(row, acc, months))
    months_s = ",".join(months)
    uncovered = [u for u in (uncovered or []) if u]
    if mode == "explore":
        extra = []
        if uncovered:
            extra.append("未覆盖 " + ",".join(uncovered))
        if trial:
            extra.append("试跑未验证 " + ",".join(trial))
        mode_line = "-- 模式 探索 " + (" ".join(extra) or "关键词不清") + " 不要当复用结案"
    else:
        mode_line = "-- 模式 复用已验证碎片（不代表准确率承诺）"
    offer_line = ""
    if survey_pack:
        offer_line = (
            "-- 本包含普查各段。整份复制当前结果网格（连表头）。\n"
            "-- event_type 从本号有费行带出，禁止手写国家码。\n"
        )
    if "voice_detail" in parts:
        offer_line += (
            "-- 通话扣费现场：拜访区、标准费、实收。同事文档里的 b_sector_tariff 是数据漫游资费，不是通话/IDD 费率，本包不查。\n"
        )
    if "tariff_by_event" in parts or "roam_detail" in parts:
        offer_line += (
            "-- 资费层：event_type 从本号有费行带出。禁止手写国家码和科目号。\n"
        )
    if "offers" in parts:
        offer_line += (
            "-- 套餐段只核对应订购名称，不是费率表，不能重批价、不能写计费无误。\n"
        )
    if "data_survey" in parts or "data_fee" in parts:
        offer_line += (
            "-- 单卡套餐没有主副卡是正常的。流量看 Q1_MB；ROLLUP 总计行不要加进金额。\n"
            "-- 月表每月一句。某月 ORA-00942 把报错贴回，其他月结果仍要贴。\n"
        )
    header = f"""-- ============================================================
-- 计费取证 SQL包（碎片拼装，整份复制一次跑完）
-- 工单 {ticket_id or '-'}   投诉号码 {acc}   月表 {months_s}
-- parts: {','.join(parts)}
{mode_line}
{offer_line}-- 不要改号码和月份。空结果也原样贴回。
-- ============================================================

"""
    sql = header + "\n".join(bits)
    fails = pack_ok(sql, acc, parts=parts)
    if fails:
        raise ChainBroken("assembly refused: " + "; ".join(fails))
    return sql


def pack_ok(sql: str, acc_num: str, parts: list[str] | None = None) -> list[str]:
    """Five AI bans + fill-in integrity. Empty list = ok."""
    fails: list[str] = []
    if acc_num not in sql:
        fails.append("acc_num not inlined")
    # 1 不下池（仅下探包）  2 EXISTS  3 desc/探表  4 科目 LIKE  （5 计费无误 在 finish/archive）
    chosen = list(parts or [])
    if any(p in POOL_PARTS for p in chosen):
        if "offer_type = '11'" not in sql and 'offer_type = "11"' not in sql:
            fails.append("shared-pool union missing")
    if "EXISTS" in sql.upper() and "ocs_data_event" in sql:
        fails.append("dblink EXISTS self-join banned")
    low = sql.lower()
    if "all_tab_columns" in low or "all_tables" in low:
        fails.append("schema probe banned (all_tables/all_tab_columns)")
    if "name like '%" in low:
        fails.append("event-name LIKE probe banned")
    if "data_fee" in chosen and "ocs_data_event_" not in low:
        fails.append("data_fee assembled without ocs_data_event")
    if "voice_fee" in chosen and "qv_mop" not in low:
        fails.append("voice_fee assembled without qv_mop")
    if "members" in chosen and "q0_acc" not in low:
        fails.append("members assembled without q0_acc")
    if "offers" in chosen and "qo_name" not in low:
        fails.append("offers assembled without qo_name")
    if "data_survey" in chosen and "q1_mop" not in low:
        fails.append("data_survey assembled without q1_mop")
    if "data_by_day" in chosen and "qd_mop" not in low:
        fails.append("data_by_day assembled without qd_mop")
    if "roam_detail" in chosen and "qx_mop" not in low:
        fails.append("roam_detail assembled without qx_mop")
    if "tariff_by_event" in chosen and "qt_event_id" not in low:
        fails.append("tariff_by_event assembled without qt_event_id")
    if "tariff_by_event" in chosen and ("prt" in low or "105766" in sql):
        fails.append("tariff fragment must not hard-code country or event id")
    if "voice_detail" in chosen and "qx_mop" not in low:
        fails.append("voice_detail assembled without qx_mop")
    if "voice_tariff" in chosen and "qt_event_id" not in low:
        fails.append("voice_tariff assembled without qt_event_id")
    if "voice_tariff" in chosen and ("prt" in low or "105766" in sql):
        fails.append("voice tariff must not hard-code country or event id")
    return fails


def render(acc_num: str, months: list[str], ticket_id: str = "", parts: list[str] | None = None) -> str:
    """Back-compat name: assemble. parts required."""
    return assemble(acc_num, months, parts or [], ticket_id=ticket_id)
