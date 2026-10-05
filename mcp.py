"""stdio MCP. Only entry for the AI loop."""
from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__, catalog, gui, loop
from .managed import ChainBroken

PROTOCOL = "2024-11-05"
INSTRUCTIONS = (
    "对用户只说中文。工具名只用于调用，不要写进回复。"
    "入口只有 be。先锁槽位。要核话单才点名已验证碎片出包；不要套固定普查 SQL。"
    "人跑 SQL 后 ingest → verify → finish → 先展示核验结果并等待用户确认 → confirm → archive。"
    "不要手写 Oracle。未验证碎片不要出包。不要写计费无误。人未贴回结果前不要核对、不要结案。"
)

_DUMMY = {"type": "string", "description": "Ignore. Some models send this by mistake."}

TOOLS = gui.TOOLS + [
    {
        "name": "be_status",
        "description": "Open case, process vs product, short strategy list. Not a green.",
        "inputSchema": {"type": "object", "properties": {"arguments": _DUMMY}},
    },
    {
        "name": "be_start",
        "description": "Lock slots: ticket_id, acc_num, months (202608 or 202607,202608), claim, optional ticket_text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "acc_num": {"type": "string"},
                "months": {"type": "string"},
                "claim": {"type": "string"},
                "ticket_text": {"type": "string"},
            },
        },
    },
    {
        "name": "be_pack",
        "description": "Assemble proven SQL fragments. parts is required (e.g. members,data_fee,data_charged). Unproven → stop.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parts": {"type": "string", "description": "Comma-separated fragment names in order."},
                "arguments": _DUMMY,
            },
        },
    },
    {
        "name": "be_fragments",
        "description": "List fragment names and proven flags. No SQL bodies.",
        "inputSchema": {"type": "object", "properties": {"arguments": _DUMMY}},
    },
    {
        "name": "be_fragment",
        "description": "Fetch one SQL fragment body. The only allowed RAG payload.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "be_ingest",
        "description": "Store the human-pasted query results as-is.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "be_verify",
        "description": "Check pack shape and whether claimed amounts appear in ingest. product failed is not MCP error.",
        "inputSchema": {"type": "object", "properties": {"arguments": _DUMMY}},
    },
    {
        "name": "be_finish",
        "description": "Write the three-sentence draft and run evidence review. Show the review and wait for explicit user confirmation before be_confirm; otherwise be_abandon.",
        "inputSchema": {"type": "object", "properties": {"arguments": _DUMMY}},
    },
    {
        "name": "be_review",
        "description": "Run deterministic evidence review for the current draft. Does not archive.",
        "inputSchema": {"type": "object", "properties": {"arguments": _DUMMY}},
    },
    {
        "name": "be_confirm",
        "description": "Record explicit human confirmation after a passing review.",
        "inputSchema": {"type": "object", "properties": {"arguments": _DUMMY}},
    },
    {
        "name": "be_archive",
        "description": "Archive after a passing review and explicit human confirmation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding": {"type": "string"},
                "arguments": _DUMMY,
            },
        },
    },
    {
        "name": "be_abandon",
        "description": "废弃当前单并记入历史 status=abandoned。不会假装结案。",
        "inputSchema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
        },
    },
    {
        "name": "be_catalog",
        "description": "Fetch a few schema cards. Require kind or query. Will not dump the catalog.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "what": {"type": "string", "enum": ["strategy", "card", "fact", "table"]},
                "kind": {"type": "string"},
                "query": {"type": "string"},
            },
        },
    },
    {
        "name": "be_history",
        "description": "Search closed tickets. query required (e.g. 副卡). Returns at most 3 short hits. Will not dump history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "be_learn",
        "description": "Upsert a schema fact (table/column/event/offer/ban). No MSISDN.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "name": {"type": "string"},
                "detail": {"type": "string"},
            },
            "required": ["kind", "name"],
        },
    },
]


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": message}}


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "be_status":
        return loop.status()
    if name == "be_start":
        return loop.start(
            ticket_id=str(args.get("ticket_id") or ""),
            acc_num=str(args.get("acc_num") or ""),
            months=str(args.get("months") or ""),
            claim=str(args.get("claim") or ""),
            ticket_text=str(args.get("ticket_text") or ""),
        )
    if name == "be_pack":
        return loop.pack(str(args.get("parts") or args.get("arguments") or ""))
    if name == "be_fragments":
        return {"items": catalog.list_fragments(include_body=False)}
    if name == "be_fragment":
        row = catalog.get_fragment(str(args.get("name") or ""))
        if not row:
            raise ChainBroken("fragment name required or unknown")
        return row
    if name == "be_ingest":
        return loop.ingest(str(args.get("text") or ""))
    if name == "be_verify":
        return loop.verify()
    if name == "be_finish":
        return loop.finish()
    if name == "be_review":
        return loop.review()
    if name == "be_confirm":
        return loop.confirm()
    if name == "be_archive":
        return loop.archive(str(args.get("finding") or ""))
    if name == "be_abandon":
        return loop.abandon(str(args.get("reason") or ""))
    if name == "be_catalog":
        what = str(args.get("what") or "strategy")
        if what == "table":
            q = str(args.get("query") or args.get("kind") or "")
            rows = catalog.tables_for_use(q) if q else catalog.list_kb_tables()
            return {
                "items": [
                    {"name": r["name"], "purpose": r["purpose"], "use_for": r["use_for"]}
                    for r in rows[:8]
                ]
            }
        if what in {"fact", "card"}:
            return {
                "items": catalog.list_cards(
                    args.get("kind") or None,
                    str(args.get("query") or ""),
                )
            }
        return {"items": [{"seq": s["seq"], "name": s["name"]} for s in catalog.list_strategy() if s["lane"] == "ship"]}
    if name == "be_history":
        return {"items": catalog.search_history(str(args.get("query") or ""), int(args.get("limit") or 3))}
    if name == "be_gui":
        return gui.call(name, args)
    if name == "be_learn":
        return catalog.put_fact(str(args.get("kind") or ""), str(args.get("name") or ""), str(args.get("detail") or ""))
    raise ChainBroken(f"unknown tool {name}")


def _handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = str(msg.get("method") or "")
    req_id = msg.get("id")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if method == "initialize":
        return _ok(
            req_id,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "be", "version": __version__},
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _ok(req_id, {})
    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            text = json.dumps(_call(name, args), ensure_ascii=False, indent=2)
        except (ChainBroken, OSError, TypeError, ValueError) as exc:
            return _ok(
                req_id,
                {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            )
        return _ok(req_id, {"content": [{"type": "text", "text": text}]})
    if req_id is None:
        return None
    return _err(req_id, f"unknown method {method}")


def _reconfigure_utf8(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass


def _read_message(reader: Any) -> dict[str, Any] | None:
    first = reader.readline()
    if first == "":
        return None
    if first.lower().startswith("content-length:"):
        length = int(first.split(":", 1)[1].strip())
        while True:
            line = reader.readline()
            if line in ("", "\n", "\r\n"):
                break
        body = reader.read(length)
        payload = json.loads(body)
        return payload if isinstance(payload, dict) else None
    text = first.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_message(writer: Any, payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    raw = getattr(writer, "buffer", None)
    if raw is not None:
        raw.write(line.encode("utf-8"))
        raw.flush()
        return
    writer.write(line)
    writer.flush()


def serve(stdin: Any | None = None, stdout: Any | None = None) -> None:
    from . import __version__  # noqa: F401 — used in initialize via global

    reader = stdin or sys.stdin
    writer = stdout or sys.stdout
    if stdin is None:
        _reconfigure_utf8(sys.stdin)
    if stdout is None:
        _reconfigure_utf8(sys.stdout)
    while True:
        try:
            message = _read_message(reader)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return
        if message is None:
            return
        try:
            reply = _handle(message)
        except Exception as exc:
            req_id = message.get("id")
            if req_id is None:
                continue
            reply = _err(req_id, str(exc))
        if reply is None:
            continue
        _write_message(writer, reply)
