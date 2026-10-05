"""Deterministic evidence review for a BE case.

This module deliberately keeps the review rules small and inspectable. It does
not call a model and it never changes the submitted evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .paste import _grid_brief


NOTICE_TERMS = ("提醒", "通知", "短信", "短讯", "sms", "notice", "notify")
OVERCLAIM_TERMS = ("口述不成立", "投诉不成立", "计费合理", "收费合理")


def _blob(*parts: Any) -> str:
    return "\n".join(str(part or "") for part in parts)


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(term.lower() in low for term in terms)


def evidence_fingerprint(case: dict[str, Any], draft: dict[str, Any] | None = None) -> str:
    """Fingerprint the inputs that can change a review decision."""
    payload = {
        "claim": case.get("claim") or "",
        "acc_num": case.get("acc_num") or "",
        "months": case.get("months") or [],
        "parts": case.get("parts") or [],
        "sql": case.get("sql") or "",
        "ingest": case.get("ingest") or "",
        "verify": case.get("verify") or {},
        "draft": draft or case.get("draft") or {},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _check(name: str, passed: bool, detail: str, evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if passed else "needs_review",
        "detail": detail,
        "evidence": evidence or [],
    }


def build_review(case: dict[str, Any], draft: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a review package without mutating the case."""
    draft = draft if isinstance(draft, dict) else {}
    verify = case.get("verify") if isinstance(case.get("verify"), dict) else {}
    ingest = str(case.get("ingest") or "")
    claim = str(case.get("claim") or "")
    brief = _grid_brief(ingest) if ingest else {}
    raw_low = ingest.lower()
    checks: list[dict[str, Any]] = []

    acc = str(case.get("acc_num") or "")
    seen_accs = [str(x) for x in (brief.get("accs") or [])]
    scope_ok = bool(ingest.strip()) and (not acc or acc in ingest or acc in seen_accs)
    scope_evidence = ["acc_num"] if acc and (acc in ingest or acc in seen_accs) else []
    months = [str(x) for x in (case.get("months") or []) if x]
    seen_months = [str(x) for x in (brief.get("yms") or [])]
    if months and seen_months:
        scope_ok = scope_ok and any(month in seen_months for month in months)
        scope_evidence.append("ym")
    checks.append(
        _check(
            "scope",
            scope_ok,
            "账号和账期能在回贴结果中定位" if scope_ok else "回贴结果缺少可核对的账号或账期",
            scope_evidence,
        )
    )

    hits = verify.get("amount_hits") if isinstance(verify.get("amount_hits"), dict) else {}
    amounts_ok = bool(verify.get("process_ok")) and not bool(verify.get("fuse_fail"))
    if hits:
        amounts_ok = amounts_ok and all(bool(value) for value in hits.values())
    checks.append(
        _check(
            "numbers",
            amounts_ok,
            "SQL 结构、列名和主张金额检查通过" if amounts_ok else "SQL、列名或主张金额仍有未通过项",
            ["verify.process_ok", "verify.amount_hits"],
        )
    )

    required: list[str] = []
    if case.get("amounts"):
        required.append("charge")
    if _has_any(claim, NOTICE_TERMS):
        required.append("notice")
    if str((case.get("profile") or {}).get("dispute") or "") == "usage":
        required.append("usage")

    coverage: dict[str, dict[str, Any]] = {}
    for item in required:
        if item == "charge":
            ok = bool(hits) and all(bool(value) for value in hits.values())
            detail = "主张金额已在核对结果中找到" if ok else "主张金额没有全部在本次结果中找到"
            evidence = ["verify.amount_hits"]
        elif item == "usage":
            ok = bool(re.search(r"\bq1_mb\b", raw_low))
            detail = "结果含用量字段" if ok else "缺少用量字段 Q1_MB"
            evidence = ["Q1_MB"] if ok else []
        else:
            notice_headers = ("sms", "notice", "notify", "message", "msg")
            ok = _has_any(raw_low, notice_headers)
            detail = "结果含提醒或通知证据字段" if ok else "客户提出提醒/通知争议，但结果没有相应证据字段"
            evidence = [term for term in notice_headers if term in raw_low]
        coverage[item] = _check(item, ok, detail, evidence)
    coverage_ok = all(item.get("status") == "passed" for item in coverage.values())
    checks.append(
        _check(
            "coverage",
            coverage_ok,
            "客户诉求均有对应证据" if coverage_ok else "至少一项客户诉求还没有对应证据",
            list(coverage),
        )
    )

    verdict = str(draft.get("verdict") or "")
    overclaim = _has_any(verdict, OVERCLAIM_TERMS)
    conclusion_ok = not (overclaim and not coverage_ok)
    checks.append(
        _check(
            "conclusion",
            conclusion_ok,
            "结论范围没有超过证据" if conclusion_ok else "结论过于绝对，超过当前证据能支持的范围",
            ["draft.verdict"],
        )
    )

    missing = [item["name"] for item in checks if item["status"] != "passed"]
    status = "passed" if not missing else "needs_review"
    return {
        "schema": "be.review.v1",
        "status": status,
        "fingerprint": evidence_fingerprint(case, draft),
        "checks": checks,
        "coverage": coverage,
        "missing": missing,
        "summary": "证据包可以交付" if status == "passed" else "证据不足或结论需要收窄",
    }
