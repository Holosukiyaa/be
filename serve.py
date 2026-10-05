"""Local HTTP UI: Vue 3 SPA (vendored) + JSON APIs. Bind 127.0.0.1 only."""
from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import catalog, gui, loop
from .managed import ChainBroken

HOST = "127.0.0.1"
PORT = 8765
WEB_ROOT = Path(__file__).resolve().parent / "web"
_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def _state() -> dict[str, Any]:
    from .managed import be_home

    cur = loop.load_current() or {}
    if cur:
        cur = loop._drop_unassembled_sql(cur)
        if cur.get("claim") and not cur.get("mode"):
            from .pack import decide_mode

            view = loop._fragment_view(str(cur.get("claim") or ""))
            info = decide_mode(
                str(cur.get("claim") or ""),
                view.get("missing_proven") or [],
                similar=True,
            )
            cur["mode"] = info["mode"]
            cur["reminder"] = info["reminder"]
            cur["uncovered"] = info["uncovered"]
            loop.save_current(cur)
    sql = str(cur.get("sql") or "")
    if cur and sql and loop.stamp_sql_round(cur, sql):
        loop.save_current(cur)
    if cur and not sql:
        run = be_home() / "run.sql"
        if run.is_file():
            blob = run.read_text(encoding="utf-8")
            if "parts:" in blob:
                sql = blob
    return {
        "process": cur.get("process") or "idle",
        "ticket_id": cur.get("ticket_id") or cur.get("id") or "",
        "acc_num": cur.get("acc_num") or "",
        "months": cur.get("months") or [],
        "claim": (cur.get("claim") or "")[:300],
        "mode": cur.get("mode") or "",
        "explore_n": int(cur.get("explore_n") or 0),
        "reminder": cur.get("reminder") or "",
        "uncovered": cur.get("uncovered") or [],
        "slots": cur.get("slots") or {
            "acc_num": cur.get("acc_num") or "",
            "months": cur.get("months") or [],
            "claim": (cur.get("claim") or "")[:200],
        },
        "sql": sql,
        "sql_round": int(cur.get("sql_round") or 0),
        "sql_copied": bool(cur.get("sql_copied")),
        "sql_copied_n": int(cur.get("sql_copied_n") or 0),
        "ingest": cur.get("ingest") or "",
        "action": cur.get("action") or (cur.get("verify") or {}).get("action") or {},
        "review": cur.get("review") or {},
        "confirmed": bool(cur.get("confirmed")),
        "charts": ((cur.get("draft") or {}) if isinstance(cur.get("draft"), dict) else {}).get("charts") or {},
        "trail": cur.get("trail") or [],
        "map_md": cur.get("map_md") or "",
        "thread": loop.load_chat() or cur.get("thread") or [],
        "ready": True,
    }


def _archive() -> dict[str, Any]:
    return {
        "cases": gui._all_history(),
        "cards": gui._all_cards(),
        "strategies": gui._all_strategy(),
    }


_PAGES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/history": "history.html",
    "/history.html": "history.html",
    "/cards": "cards.html",
    "/cards.html": "cards.html",
    "/gates": "gates.html",
    "/gates.html": "gates.html",
}


def _static(rel: str) -> tuple[bytes, str] | None:
    name = _PAGES.get(rel if rel.startswith("/") else "/" + (rel or ""), "")
    if not name:
        name = (rel or "").lstrip("/")
    if not name or name == "index.html":
        name = "index.html"
    root = WEB_ROOT.resolve()
    target = (root / name).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target.read_bytes(), _TYPES.get(target.suffix.lower(), "application/octet-stream")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        raw = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self._send(code, raw, "application/json; charset=utf-8")

    def _read_json(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/state":
            self._json(200, _state())
            return
        if path == "/api/archive":
            catalog.init()
            self._json(200, _archive())
            return
        hit = _static(path)
        if hit:
            self._send(200, hit[0], hit[1])
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        data = self._read_json()
        try:
            if path == "/api/chat":
                from .agent import chat

                text = str(data.get("message") or data.get("text") or "").strip()
                if not text:
                    self._json(400, {"error": "empty message"})
                    return
                reply = chat(text)
                self._json(200, {"reply": reply, "state": _state()})
                return
            if path == "/api/new":
                out = loop.new_chat()
                self._json(200, {"ok": True, "result": out, "state": _state()})
                return
            if path == "/api/ingest":
                text = str(data.get("text") or "").strip()
                out = loop.ingest(text)
                self._json(200, {"ok": True, "result": out, "state": _state()})
                return
            if path == "/api/copied":
                out = loop.mark_sql_copied()
                self._json(200, {"ok": True, "result": out, "state": _state()})
                return
            if path == "/api/review":
                out = loop.review()
                self._json(200, {"ok": True, "result": out, "state": _state()})
                return
            if path == "/api/confirm":
                out = loop.confirm()
                self._json(200, {"ok": True, "result": out, "state": _state()})
                return
            if path == "/api/archive-current":
                out = loop.archive()
                self._json(200, {"ok": True, "result": out, "state": _state()})
                return
        except ChainBroken as exc:
            self._json(400, {"error": str(exc), "state": _state()})
            return
        except Exception as exc:
            self._json(500, {"error": str(exc), "state": _state()})
            return
        self._send(404, b"not found", "text/plain")


def serve(host: str = HOST, port: int = PORT, *, browse: bool = True) -> None:
    import sys

    from .agent import _load_env
    from .managed import be_home

    _load_env()
    catalog.init()
    log = be_home() / "serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "a", encoding="utf-8")
    sys.stdout = handle
    sys.stderr = handle
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"be serve {url}", flush=True)
    if browse:
        import threading

        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    httpd.serve_forever()
