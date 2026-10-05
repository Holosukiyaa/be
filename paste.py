"""PL/SQL paste: split grids, sum money/MB, fuse columns."""
from __future__ import annotations

import re
from typing import Any

from .managed import ChainBroken

EMPTY_MARKS = frozenset(
    {
        "空",
        "空的",
        "结果是空的",
        "結果是空的",
        "(empty)",
        "empty",
        "无记录",
        "無記錄",
        "无行",
        "無行",
        "no rows",
        "no rows selected",
    }
)

def _split_plsql_row(line: str) -> list[str]:
    s = (line or "").strip()
    if not s:
        return []
    if "\t" in s:
        return [c.strip() for c in s.split("\t") if c.strip() != ""]
    if re.search(r"\s{2,}", s):
        return [c.strip() for c in re.split(r"\s{2,}", s) if c.strip()]
    return [c.strip() for c in s.split() if c.strip()]


def normalize_plsql_grid(text: str) -> str:
    """PL/SQL Developer copy: row numbers + multi-space columns + datetime with a space."""
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return text or ""
    head_i = None
    headers: list[str] = []
    for i, ln in enumerate(lines):
        parts = _split_plsql_row(ln)
        low = [p.lower() for p in parts]
        if any(
            n in low
            for n in (
                "qc_mop",
                "qv_mop",
                "q1_mop",
                "qd_mop",
                "qr_mop",
                "qn_mop",
                "qc_ym",
                "qv_ym",
                "q1_ym",
            )
        ):
            head_i = i
            headers = parts
            break
    if head_i is None or not headers:
        return text or ""
    out = ["\t".join(headers)]
    width = len(headers)
    for ln in lines[head_i + 1 :]:
        cells = _split_plsql_row(ln)
        if not cells:
            continue
        if cells[0].isdigit() and len(cells) == width + 1:
            cells = cells[1:]
        if len(cells) < width:
            continue
        if len(cells) > width:
            cells = cells[: width - 1] + [" ".join(cells[width - 1 :])]
        out.append("\t".join(cells[:width]))
    return "\n".join(out)


def _mop_stats(ingest_text: str) -> tuple[float | None, int]:
    """Sum Q1_MOP / QV_MOP / QC_MOP. Last money column only, never called-numbers."""
    grid = normalize_plsql_grid(ingest_text)
    lines = [ln.strip() for ln in grid.splitlines() if ln.strip()]
    idx = None
    start = 0
    for i, ln in enumerate(lines):
        parts = ln.split("\t") if "\t" in ln else _split_plsql_row(ln)
        low = [p.lower() for p in parts]
        for name in ("qc_mop", "qv_mop", "q1_mop", "qr_mop", "qn_mop", "qd_mop"):
            if name in low:
                idx = low.index(name)
                start = i + 1
                break
        if idx is not None:
            break
    if idx is None:
        return None, 0
    total = 0.0
    n = 0
    for ln in lines[start:]:
        parts = ln.split("\t") if "\t" in ln else _split_plsql_row(ln)
        if idx >= len(parts):
            continue
        low_row = [p.lower() for p in parts]
        if any(
            h in low_row
            for h in ("q1_ym", "qd_ym", "qr_ym", "qn_ym", "qc_ym", "qv_ym", "qo_name")
        ):
            break
        token = parts[idx].replace(",", "")
        if not re.fullmatch(r"\d+\.\d{1,2}", token):
            continue
        if any(c in {"总计", "合計", "合计"} for c in parts):
            continue
        total += float(token)
        n += 1
    return (round(total, 2), n) if n else (None, 0)


def _mb_stats(ingest_text: str) -> tuple[float | None, int]:
    grid = normalize_plsql_grid(ingest_text)
    lines = [ln.strip() for ln in grid.splitlines() if ln.strip()]
    idx = None
    start = 0
    for i, ln in enumerate(lines):
        parts = ln.split("\t") if "\t" in ln else _split_plsql_row(ln)
        low = [p.lower() for p in parts]
        if "q1_mb" in low:
            idx = low.index("q1_mb")
            start = i + 1
            break
    if idx is None:
        return None, 0
    total = 0.0
    n = 0
    for ln in lines[start:]:
        parts = ln.split("\t") if "\t" in ln else _split_plsql_row(ln)
        if any(c in {"总计", "合計", "合计"} for c in parts):
            continue
        if idx >= len(parts):
            continue
        token = parts[idx].replace(",", "")
        if not re.fullmatch(r"\d+(?:\.\d+)?", token):
            continue
        total += float(token)
        n += 1
    return (round(total, 2), n) if n else (None, 0)


def _sum_mop_column(ingest_text: str) -> float | None:
    total, _n = _mop_stats(ingest_text)
    return total


def _header_index(headers: list[str], *names: str) -> int | None:
    low = [h.lower() for h in headers]
    for name in names:
        if name in low:
            return low.index(name)
    return None


def _grid_brief(ingest_text: str) -> dict[str, Any]:
    grid = normalize_plsql_grid(ingest_text)
    lines = [ln.strip() for ln in grid.splitlines() if ln.strip()]
    if not lines:
        return {}
    headers = lines[0].split("\t") if "\t" in lines[0] else _split_plsql_row(lines[0])
    i_mop = _header_index(headers, "qc_mop", "qv_mop", "q1_mop", "qr_mop", "qn_mop", "qd_mop")
    i_sec = _header_index(headers, "qc_sec", "qv_sec")
    i_tm = _header_index(headers, "qc_tm", "q2_tm", "qd_day")
    i_ev = _header_index(headers, "qc_event", "qv_event", "q1_event", "qr_event", "qn_event", "qn_offer")
    i_acc = _header_index(headers, "qc_acc", "qv_acc", "q1_acc", "qr_acc", "qn_acc", "qd_acc")
    i_ym = _header_index(headers, "qc_ym", "qv_ym", "q1_ym", "qr_ym", "qn_ym", "qd_ym")
    mop_total = 0.0
    sec_total = 0
    n = 0
    events: list[str] = []
    times: list[str] = []
    accs: list[str] = []
    yms: list[str] = []
    rows_out: list[dict[str, Any]] = []
    for ln in lines[1:]:
        parts = ln.split("\t") if "\t" in ln else _split_plsql_row(ln)
        if any(
            h in [p.lower() for p in parts]
            for h in ("q1_ym", "qd_ym", "qr_ym", "qn_ym", "qc_ym", "qv_ym", "qo_name")
        ):
            break
        if i_mop is None or i_mop >= len(parts):
            continue
        token = parts[i_mop].replace(",", "")
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", token):
            continue
        if any(c in {"总计", "合計", "合计"} for c in parts):
            continue
        val = float(token)
        if val > 0.005:
            mop_total += val
            n += 1
        if i_sec is not None and i_sec < len(parts) and parts[i_sec].isdigit():
            sec_total += int(parts[i_sec])
        if i_tm is not None and i_tm < len(parts) and parts[i_tm]:
            times.append(parts[i_tm])
        if i_ev is not None and i_ev < len(parts) and parts[i_ev] and parts[i_ev] not in events:
            events.append(parts[i_ev])
        if i_acc is not None and i_acc < len(parts) and parts[i_acc] and parts[i_acc] not in accs:
            accs.append(parts[i_acc])
        if i_ym is not None and i_ym < len(parts) and parts[i_ym] and parts[i_ym] not in yms:
            yms.append(parts[i_ym])
        row = {
            "tm": parts[i_tm] if i_tm is not None and i_tm < len(parts) else "",
            "sec": int(parts[i_sec]) if i_sec is not None and i_sec < len(parts) and parts[i_sec].isdigit() else 0,
            "mop": float(token),
            "event": parts[i_ev] if i_ev is not None and i_ev < len(parts) else "",
        }
        rows_out.append(row)
    return {
        "n": n,
        "mop": round(mop_total, 2) if n else None,
        "sec": sec_total,
        "events": events,
        "tmin": times[0] if times else "",
        "tmax": times[-1] if times else "",
        "accs": accs,
        "yms": yms,
        "rows": rows_out,
    }


def _alias_header_line(line: str) -> bool:
    from . import catalog

    low = [c.lower() for c in _split_plsql_row(line)]
    names = catalog.all_alias_names()
    return any(n in low for n in names)


def is_empty_ingest(ingest_text: str) -> bool:
    raw = (ingest_text or "").strip()
    if not raw:
        return False
    if raw.lower() in EMPTY_MARKS or raw in EMPTY_MARKS:
        return True
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if lines and all(_alias_header_line(ln) for ln in lines):
        _total, n = _mop_stats(raw)
        if n == 0:
            return True
    return False


def is_ora_00942(text: str) -> bool:
    blob = (text or "").upper()
    return "ORA-00942" in blob or "ORA-02063" in blob


def _column_fuse(ingest_text: str, parts: list[str]) -> list[str]:
    """治人：贴回必须带本包碎片 aliases（独立单元格）。VISIT_AREA = 旧窗口。空结果不算列。"""
    raw = (ingest_text or "").strip()
    if is_empty_ingest(raw) or is_ora_00942(raw):
        return []
    from . import catalog

    headers: list[list[str]] = []
    saw_visit = False
    for ln in raw.splitlines():
        low = [c.lower() for c in _split_plsql_row(ln)]
        if not low:
            continue
        if "visit_area" in low:
            saw_visit = True
        headers.append(low)
    matched = False
    for name in parts:
        groups = catalog.fragment_aliases(str(name))
        if not groups:
            continue
        for low in headers:
            if any(all(col in low for col in group) for group in groups):
                matched = True
                break
        if matched:
            break
    if matched:
        return []
    if saw_visit:
        return ["column fuse: VISIT_AREA is an old window; re-run the SQL on the right"]
    return [
        "column fuse: 列之间没有分隔，不要粘成 Q1_YMQ1_ACC；请从结果网格连表头复制（Tab 或两空格）"
    ]


def _mop_value_tokens(ingest_text: str) -> set[str]:
    """Only money-column cells, never MB/秒/被叫."""
    tokens: set[str] = set()
    grid = normalize_plsql_grid(ingest_text)
    lines = [ln.strip() for ln in grid.splitlines() if ln.strip()]
    idx = None
    start = 0
    for i, ln in enumerate(lines):
        parts = ln.split("\t") if "\t" in ln else _split_plsql_row(ln)
        low = [p.lower() for p in parts]
        for name in ("qc_mop", "qv_mop", "q1_mop", "qr_mop", "qn_mop", "qd_mop", "qx_mop"):
            if name in low:
                idx = low.index(name)
                start = i + 1
                break
        if idx is not None:
            break
    if idx is None:
        return tokens
    for ln in lines[start:]:
        parts = ln.split("\t") if "\t" in ln else _split_plsql_row(ln)
        low_row = [p.lower() for p in parts]
        if any(h in low_row for h in ("q1_ym", "qd_ym", "qr_ym", "qn_ym", "qc_ym", "qv_ym", "qo_name")):
            break
        if idx >= len(parts):
            continue
        token = parts[idx].replace(",", "")
        if re.fullmatch(r"\d+(?:\.\d{1,2})?", token):
            tokens.add(token)
            if "." not in token:
                tokens.add(token + ".00")
            tokens.add(token.replace(".00", ""))
    return tokens


def _amounts_found(ingest_text: str, wanted: list[str]) -> dict[str, bool]:
    mop_tokens = _mop_value_tokens(ingest_text)
    mop_norm: set[str] = set()
    for cell in mop_tokens:
        try:
            mop_norm.add(f"{float(cell):.2f}")
        except ValueError:
            pass
    found = {}
    for amt in wanted:
        token = amt.replace(" ", "")
        hit = token in mop_tokens or token.replace(".00", "") in mop_tokens
        try:
            hit = hit or f"{float(token):.2f}" in mop_norm
        except ValueError:
            pass
        found[amt] = hit
    return found


