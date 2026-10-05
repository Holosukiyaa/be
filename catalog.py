"""SQLite is the store. Python only opens it. No card/history constants here."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import managed
from .managed import ChainBroken

DB_NAME = "knowledge.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy (
  lane TEXT NOT NULL,
  seq INTEGER NOT NULL,
  name TEXT NOT NULL,
  story TEXT NOT NULL,
  how TEXT NOT NULL,
  solves TEXT NOT NULL,
  not_that TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (lane, seq)
);
CREATE TABLE IF NOT EXISTS schema_card (
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  updated TEXT NOT NULL,
  PRIMARY KEY (kind, name)
);
CREATE TABLE IF NOT EXISTS case_history (
  ticket_id TEXT PRIMARY KEY,
  acc_num TEXT NOT NULL,
  months TEXT NOT NULL,
  claim TEXT NOT NULL,
  finding TEXT NOT NULL,
  amounts TEXT NOT NULL,
  gold INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  closed TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'archived',
  expect_accs TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sql_fragment (
  name TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  proven INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  updated TEXT NOT NULL,
  aliases TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS kb_table (
  owner TEXT NOT NULL DEFAULT 'billdetail',
  name TEXT NOT NULL,
  purpose TEXT NOT NULL,
  use_for TEXT NOT NULL DEFAULT '',
  fragment TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  link TEXT NOT NULL DEFAULT '',
  proven INTEGER NOT NULL DEFAULT 0,
  updated TEXT NOT NULL,
  PRIMARY KEY (owner, name)
);
"""

def factory_db() -> Path:
    return Path(__file__).with_name("knowledge.sqlite")


def db_path() -> Path:
    path = managed.be_home() / DB_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(*, write: bool = True) -> sqlite3.Connection:
    path = db_path()
    if write:
        conn = sqlite3.connect(path)
    else:
        if not path.is_file():
            raise FileNotFoundError(path)
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=1000")
    return conn


def init() -> Path:
    """Home db is the live archive. Missing → copy packaged sqlite dump."""
    import shutil

    path = db_path()
    factory = factory_db()
    if not path.is_file():
        if factory.is_file():
            shutil.copy2(factory, path)
        else:
            with sqlite3.connect(path) as conn:
                conn.executescript(SCHEMA)
                conn.commit()
    else:
        with connect(write=True) as conn:
            conn.executescript(SCHEMA)
            _migrate(conn)
            conn.commit()
    with connect(write=True) as conn:
        _migrate(conn)
        conn.commit()
    return path


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(case_history)")}
    if cols and "status" not in cols:
        conn.execute(
            "ALTER TABLE case_history ADD COLUMN status TEXT NOT NULL DEFAULT 'archived'"
        )
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(case_history)")}
    if cols and "expect_accs" not in cols:
        conn.execute(
            "ALTER TABLE case_history ADD COLUMN expect_accs TEXT NOT NULL DEFAULT ''"
        )
    for row in _factory_rows("case_history"):
        if int(row["gold"] or 0) != 1:
            continue
        keys = row.keys()
        if "expect_accs" not in keys:
            continue
        accs = str(row["expect_accs"] or "").strip()
        if not accs:
            continue
        conn.execute(
            "UPDATE case_history SET expect_accs = ? "
            "WHERE ticket_id = ? AND gold = 1 AND TRIM(IFNULL(expect_accs,'')) = ''",
            (accs, row["ticket_id"]),
        )
    fcols = {str(r[1]) for r in conn.execute("PRAGMA table_info(sql_fragment)")}
    if fcols and "aliases" not in fcols:
        conn.execute(
            "ALTER TABLE sql_fragment ADD COLUMN aliases TEXT NOT NULL DEFAULT ''"
        )
    for row in _factory_rows("sql_fragment"):
        keys = row.keys()
        if "aliases" not in keys:
            continue
        aliases = str(row["aliases"] or "").strip()
        if not aliases:
            continue
        conn.execute(
            "UPDATE sql_fragment SET aliases = ? "
            "WHERE name = ? AND TRIM(IFNULL(aliases,'')) = ''",
            (aliases, row["name"]),
        )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sql_fragment ("
        "name TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, "
        "proven INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', "
        "updated TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kb_table ("
        "owner TEXT NOT NULL DEFAULT 'billdetail', name TEXT NOT NULL, "
        "purpose TEXT NOT NULL, use_for TEXT NOT NULL DEFAULT '', "
        "fragment TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', "
        "link TEXT NOT NULL DEFAULT '', proven INTEGER NOT NULL DEFAULT 0, "
        "updated TEXT NOT NULL, PRIMARY KEY (owner, name))"
    )
    _import_factory(conn, "sql_fragment")
    _import_factory(conn, "kb_table")
    _import_factory(conn, "schema_card")


def _factory_rows(table: str) -> list[sqlite3.Row]:
    factory = factory_db()
    if not factory.is_file():
        return []
    src = sqlite3.connect(f"file:{factory.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        return list(src.execute(f"SELECT * FROM {table}").fetchall())
    except sqlite3.OperationalError:
        return []
    finally:
        src.close()


def _import_factory(conn: sqlite3.Connection, table: str) -> None:
    """Fill empty tables from packaged sqlite. Never DROP. Never Python lists."""
    rows = _factory_rows(table)
    if not rows:
        return
    cols = list(rows[0].keys())
    marks = ",".join("?" * len(cols))
    names = ",".join(cols)
    if table == "sql_fragment":
        for row in rows:
            aliases = str(row["aliases"] or "").strip() if "aliases" in row.keys() else ""
            conn.execute(
                "INSERT INTO sql_fragment(name,kind,body,proven,note,updated,aliases) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                "kind=excluded.kind, note=excluded.note, "
                "updated=excluded.updated, "
                "aliases=CASE WHEN TRIM(IFNULL(sql_fragment.aliases,''))='' "
                "THEN excluded.aliases ELSE sql_fragment.aliases END",
                (
                    row["name"],
                    row["kind"],
                    row["body"],
                    row["proven"],
                    row["note"],
                    row["updated"],
                    aliases,
                ),
            )
        return
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    if n is not None and int(n[0]) > 0:
        return
    conn.executemany(
        f"INSERT OR IGNORE INTO {table}({names}) VALUES({marks})",
        [tuple(row[c] for c in cols) for row in rows],
    )


def ensure_fragments() -> None:
    """Copy missing fragments from packaged sqlite. Do not overwrite admitted bodies."""
    init()
    have = {str(r["name"]) for r in list_fragments(include_body=False, limit=64)}
    for row in _factory_rows("sql_fragment"):
        name = str(row["name"])
        if name in have:
            continue
        put_fragment(
            name,
            str(row["body"]),
            kind=str(row["kind"] or name),
            proven=bool(row["proven"]),
            note=str(row["note"] or ""),
            aliases=str(row["aliases"] or "") if "aliases" in row.keys() else "",
        )


def list_fragments(*, include_body: bool = False, limit: int = 32) -> list[dict[str, Any]]:
    init()
    limit = max(1, min(int(limit), 64))
    with connect(write=False) as conn:
        rows = conn.execute(
            "SELECT name, kind, proven, note, updated, body, aliases FROM sql_fragment ORDER BY name LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for row in rows:
        item = {
            "name": row["name"],
            "kind": row["kind"],
            "proven": int(row["proven"] or 0),
            "note": row["note"],
            "updated": row["updated"],
            "aliases": str(row["aliases"] or "") if "aliases" in row.keys() else "",
        }
        if include_body:
            item["body"] = row["body"]
        out.append(item)
    return out


def get_fragment(name: str) -> dict[str, Any] | None:
    """One SQL fragment. This is the allowed RAG payload."""
    name = (name or "").strip()
    if not name:
        raise ChainBroken("fragment name required")
    init()
    with connect(write=False) as conn:
        row = conn.execute(
            "SELECT name, kind, body, proven, note, updated, aliases FROM sql_fragment WHERE name = ?",
            (name,),
        ).fetchone()
    return dict(row) if row else None


def parse_alias_groups(raw: str) -> list[list[str]]:
    """Comma = AND in a group. Semicolon = OR across groups."""
    groups: list[list[str]] = []
    for chunk in str(raw or "").replace("，", ",").split(";"):
        cols = [c.strip().lower() for c in chunk.split(",") if c.strip()]
        if cols:
            groups.append(cols)
    return groups


def _aliases_seed(name: str) -> str:
    """Explore trial voice_fee/voice_charged are not factory rows; borrow QV/QC groups."""
    groups: list[list[str]] = []
    for fr in _factory_rows("sql_fragment"):
        if str(fr["name"]) != "voice_detail":
            continue
        if "aliases" in fr.keys():
            groups = parse_alias_groups(str(fr["aliases"] or ""))
        break
    if name == "voice_fee":
        for g in groups:
            if "qv_ym" in g:
                return ",".join(g)
    if name == "voice_charged":
        for g in groups:
            if "qc_ym" in g:
                return ",".join(g)
    return ""


def fragment_aliases(name: str) -> list[list[str]]:
    name = (name or "").strip()
    if not name:
        return []
    init()
    raw = ""
    with connect(write=False) as conn:
        row = conn.execute(
            "SELECT aliases FROM sql_fragment WHERE name = ?", (name,)
        ).fetchone()
    if row and "aliases" in row.keys():
        raw = str(row["aliases"] or "")
    groups = parse_alias_groups(raw)
    if groups:
        return groups
    for fr in _factory_rows("sql_fragment"):
        if str(fr["name"]) != name or "aliases" not in fr.keys():
            continue
        groups = parse_alias_groups(str(fr["aliases"] or ""))
        if groups:
            return groups
        break
    return parse_alias_groups(_aliases_seed(name))


def all_alias_names() -> set[str]:
    init()
    names: set[str] = set()
    with connect(write=False) as conn:
        rows = conn.execute("SELECT aliases FROM sql_fragment").fetchall()
    for row in rows:
        if "aliases" not in row.keys():
            continue
        for group in parse_alias_groups(str(row["aliases"] or "")):
            names.update(group)
    for fr in _factory_rows("sql_fragment"):
        if "aliases" not in fr.keys():
            continue
        for group in parse_alias_groups(str(fr["aliases"] or "")):
            names.update(group)
    return names


def put_fragment(
    name: str,
    body: str,
    *,
    kind: str = "",
    proven: bool = False,
    note: str = "",
    aliases: str = "",
) -> dict[str, Any]:
    name = (name or "").strip()
    body = (body or "").strip()
    kind = (kind or name).strip()
    if not name or not body:
        raise ChainBroken("fragment name and body required")
    if name.strip().isdigit() and len(name.strip()) >= 8:
        raise ChainBroken("do not store acc_num as a fragment name")
    low = body.lower()
    if "all_tab_columns" in low or "all_tables" in low:
        raise ChainBroken("fragment must not probe all_tables / all_tab_columns")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    aliases = (aliases or "").strip()
    if not aliases:
        aliases = _aliases_seed(name)
    init()
    with connect(write=True) as conn:
        conn.execute(
            "INSERT INTO sql_fragment(name,kind,body,proven,note,updated,aliases) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, body=excluded.body, "
            "proven=excluded.proven, note=excluded.note, updated=excluded.updated, "
            "aliases=CASE WHEN TRIM(excluded.aliases)='' THEN sql_fragment.aliases ELSE excluded.aliases END",
            (name, kind, body, 1 if proven else 0, note.strip(), now, aliases),
        )
        conn.commit()
    return {"name": name, "kind": kind, "proven": 1 if proven else 0, "note": note, "aliases": aliases}


def admit_fragment(name: str) -> dict[str, Any]:
    """Human marks a fragment proven after a real run. AI tools must not call this."""
    name = (name or "").strip()
    if not name:
        raise ChainBroken("fragment name required")
    init()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect(write=True) as conn:
        cur = conn.execute(
            "UPDATE sql_fragment SET proven = 1, updated = ? WHERE name = ?",
            (now, name),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise ChainBroken(f"no fragment named {name}")
        row = conn.execute("SELECT name, kind, proven, note FROM sql_fragment WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else {"name": name, "proven": 1}


def list_strategy() -> list[dict[str, Any]]:
    init()
    with connect(write=False) as conn:
        rows = conn.execute("SELECT * FROM strategy ORDER BY lane, seq").fetchall()
    return [dict(r) for r in rows]


def list_cards(kind: str | None = None, query: str = "", limit: int = 5) -> list[dict[str, Any]]:
    """Retrieve a few cards. kind or query required — no full dump."""
    init()
    kind = (kind or "").strip() or None
    q = (query or "").strip()
    if not kind and not q:
        raise ChainBroken("be_catalog needs kind (table/column/event/offer/ban) or query. will not dump all cards.")
    limit = max(1, min(int(limit), 8))
    with connect(write=False) as conn:
        if kind and q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM schema_card WHERE kind = ? AND (name LIKE ? OR body LIKE ?) ORDER BY name LIMIT ?",
                (kind, like, like, limit),
            ).fetchall()
        elif kind:
            rows = conn.execute(
                "SELECT * FROM schema_card WHERE kind = ? ORDER BY name LIMIT ?",
                (kind, limit),
            ).fetchall()
        else:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM schema_card WHERE name LIKE ? OR body LIKE ? ORDER BY kind, name LIMIT ?",
                (like, like, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def list_facts(kind: str | None = None) -> list[dict[str, Any]]:
    """Alias: cards are the schema facts."""
    rows = list_cards(kind)
    out = []
    for row in rows:
        out.append(
            {
                "kind": row["kind"],
                "name": row["name"],
                "detail": row.get("body") or row.get("detail") or "",
                "updated": row.get("updated") or "",
            }
        )
    return out


def list_kb_tables() -> list[dict[str, Any]]:
    init()
    with connect(write=False) as conn:
        rows = conn.execute(
            "SELECT name, purpose, use_for, fragment, source, owner, link, proven, updated "
            "FROM kb_table ORDER BY proven DESC, name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_kb_table(name: str) -> dict[str, Any] | None:
    name = (name or "").strip()
    if not name:
        return None
    init()
    with connect(write=False) as conn:
        row = conn.execute("SELECT * FROM kb_table WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def tables_for_use(use: str) -> list[dict[str, Any]]:
    """Tables whose use_for matches a complaint kind (通话/流量/短信). Not a dump."""
    key = (use or "").strip()
    if not key:
        return []
    out = []
    for row in list_kb_tables():
        blob = str(row.get("use_for") or "") + "," + str(row.get("purpose") or "")
        if key in blob:
            out.append(row)
    return out


def table_for_fragment(fragment: str) -> str:
    frag = (fragment or "").strip()
    if not frag:
        return ""
    for row in list_kb_tables():
        parts = [p.strip() for p in str(row.get("fragment") or "").split(",") if p.strip()]
        if frag in parts:
            return str(row["name"])
    return ""


def get_card(kind: str, name: str) -> dict[str, Any] | None:
    """Exact card. Not a search. Empty name is a miss, not a dump."""
    kind = (kind or "").strip()
    name = (name or "").strip()
    if not kind or not name:
        return None
    init()
    with connect(write=False) as conn:
        row = conn.execute(
            "SELECT * FROM schema_card WHERE kind = ? AND name = ?",
            (kind, name),
        ).fetchone()
    return dict(row) if row else None


def put_fact(kind: str, name: str, detail: str) -> dict[str, Any]:
    if not kind.strip() or not name.strip():
        raise ChainBroken("kind and name required")
    if name.strip().isdigit() and len(name.strip()) >= 8:
        raise ChainBroken("do not store acc_num on a schema card")
    if kind.strip() in {"sql", "fragment"}:
        return put_fragment(name, detail, kind=name.strip(), proven=False, note="be_learn unproven")
    if kind.strip() == "table":
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        init()
        with connect(write=True) as conn:
            conn.execute(
                "INSERT INTO kb_table(owner,name,purpose,use_for,fragment,source,link,proven,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(owner,name) DO UPDATE SET purpose=excluded.purpose, updated=excluded.updated",
                ("billdetail", name.strip(), detail.strip(), "", "", "be_learn", "", 0, now),
            )
            conn.commit()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    init()
    with connect(write=True) as conn:
        conn.execute(
            "INSERT INTO schema_card(kind,name,body,updated) VALUES(?,?,?,?) "
            "ON CONFLICT(kind,name) DO UPDATE SET body=excluded.body, updated=excluded.updated",
            (kind.strip(), name.strip(), detail.strip(), now),
        )
        conn.commit()
    return {"kind": kind, "name": name, "body": detail, "updated": now}


def gold_for(ticket_id: str | None, acc_num: str | None) -> dict[str, Any] | None:
    init()
    with connect(write=False) as conn:
        row = None
        if ticket_id:
            row = conn.execute(
                "SELECT ticket_id, acc_num, months, amounts AS expect_amounts, note, expect_accs "
                "FROM case_history WHERE gold = 1 AND ticket_id = ?",
                (ticket_id,),
            ).fetchone()
        if row is None and acc_num:
            row = conn.execute(
                "SELECT ticket_id, acc_num, months, amounts AS expect_amounts, note, expect_accs "
                "FROM case_history WHERE gold = 1 AND acc_num = ?",
                (acc_num,),
            ).fetchone()
    return dict(row) if row else None


def _short_row(row: sqlite3.Row) -> dict[str, Any]:
    finding = str(row["finding"] or "")
    if len(finding) > 80:
        finding = finding[:77] + "..."
    return {
        "ticket_id": row["ticket_id"],
        "acc_num": row["acc_num"],
        "months": row["months"],
        "amounts": row["amounts"],
        "gold": row["gold"],
        "finding": finding,
        "status": row["status"] if "status" in row.keys() else "archived",
    }


_STOP = {
    "客户", "投诉", "计费", "热线", "谢谢", "表示", "详细", "情况", "工单",
    "核查", "处理", "要求", "认为", "正确", "错误", "原因", "项目",
}

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{2,}|\d+\.\d+|\d{2,}")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text or "") if t not in _STOP}


def similar_cases(
    claim: str,
    *,
    exclude_ticket: str = "",
    exclude_acc: str = "",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Top similar closed tickets. Short rows only. For the working AI, not a dump."""
    init()
    needles = _tokens(claim)
    if not needles:
        return []
    limit = max(1, min(int(limit), 3))
    with connect(write=False) as conn:
        rows = conn.execute("SELECT * FROM case_history").fetchall()
    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        if exclude_ticket and str(row["ticket_id"]) == exclude_ticket:
            continue
        if exclude_acc and str(row["acc_num"]) == exclude_acc:
            continue
        hay = " ".join(
            str(row[k] or "") for k in ("claim", "finding", "note", "amounts", "ticket_id")
        )
        hits = _tokens(hay) & needles
        if not hits:
            continue
        score = float(len(hits)) + (0.5 if row["gold"] else 0.0)
        scored.append((score, row))
    scored.sort(key=lambda x: (-x[0], str(x[1]["closed"])))
    out = []
    for score, row in scored[:limit]:
        item = _short_row(row)
        item["score"] = score
        out.append(item)
    return out


def search_history(query: str = "", limit: int = 3) -> list[dict[str, Any]]:
    """Must pass a query. Never dump the whole history to the model."""
    init()
    q = (query or "").strip()
    if not q:
        raise ChainBroken("be_history needs a query (e.g. 副卡 / 香港 / 53.75). will not dump all cases.")
    limit = max(1, min(int(limit), 5))
    like = f"%{q}%"
    with connect(write=False) as conn:
        rows = conn.execute(
            "SELECT * FROM case_history WHERE ticket_id LIKE ? OR acc_num LIKE ? "
            "OR claim LIKE ? OR finding LIKE ? OR note LIKE ? OR amounts LIKE ? "
            "ORDER BY gold DESC, closed DESC LIMIT ?",
            (like, like, like, like, like, like, limit),
        ).fetchall()
    return [_short_row(r) for r in rows]


def remember_case(
    *,
    ticket_id: str,
    acc_num: str,
    months: str,
    claim: str,
    finding: str,
    amounts: str,
    note: str = "",
    gold: int = 0,
    status: str = "archived",
) -> dict[str, Any]:
    if not ticket_id.strip() and not acc_num.strip():
        raise ChainBroken("ticket_id or acc_num required")
    tid = ticket_id.strip() or acc_num.strip()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    init()
    with connect(write=True) as conn:
        conn.execute(
            "INSERT INTO case_history(ticket_id,acc_num,months,claim,finding,amounts,gold,note,closed,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(ticket_id) DO UPDATE SET "
            "acc_num=excluded.acc_num, months=excluded.months, claim=excluded.claim, "
            "finding=excluded.finding, amounts=excluded.amounts, note=excluded.note, "
            "closed=excluded.closed, status=excluded.status",
            (tid, acc_num, months, claim, finding, amounts, int(gold), note, now, status),
        )
        conn.commit()
    return {"ticket_id": tid, "closed": now}
