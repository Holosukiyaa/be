from __future__ import annotations

import argparse
import json
import sys

from .managed import ChainBroken


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="be")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mcp", help="stdio MCP — only AI entry")
    sub.add_parser("status")
    start_p = sub.add_parser("start")
    start_p.add_argument("--ticket-id", default="")
    start_p.add_argument("--acc", default="")
    start_p.add_argument("--months", default="")
    start_p.add_argument("--claim", default="")
    start_p.add_argument("--ticket-text", default="")
    pack_p = sub.add_parser("pack")
    pack_p.add_argument("--parts", default="")
    frag_p = sub.add_parser("fragments")
    frag_p.add_argument("--body", action="store_true")
    adm = sub.add_parser("admit")
    adm.add_argument("name")
    ing = sub.add_parser("ingest")
    ing.add_argument("text")
    sub.add_parser("verify")
    sub.add_parser("finish")
    sub.add_parser("review")
    sub.add_parser("confirm")
    arch = sub.add_parser("archive")
    arch.add_argument("--finding", default="")
    abn = sub.add_parser("abandon")
    abn.add_argument("--reason", default="")
    sub.add_parser("init-db")
    sub.add_parser("gui", help="write HTML archive and open it")
    sub.add_parser("serve", help="local chat UI: smolagents left, SQL right")
    hist = sub.add_parser("history")
    hist.add_argument("query", nargs="?", default="")
    cards = sub.add_parser("cards")
    cards.add_argument("kind", nargs="?", default="")
    sub.add_parser("tables", help="kb_table: what each table is for")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "mcp":
            from .mcp import serve

            serve()
            return 0
        from . import catalog, loop

        if args.cmd == "init-db":
            print(str(catalog.init()))
            return 0
        if args.cmd == "gui":
            from .gui import write_archive

            print(str(write_archive(browse=True)))
            return 0
        if args.cmd == "serve":
            from .serve import serve as http_serve

            http_serve()
            return 0
        if args.cmd == "history":
            if not args.query:
                print("need query, e.g. be history 副卡", file=sys.stderr)
                return 1
            print(json.dumps(catalog.search_history(args.query), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "cards":
            if not args.kind:
                print("need kind, e.g. be cards event", file=sys.stderr)
                return 1
            print(json.dumps(catalog.list_cards(args.kind), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "tables":
            print(json.dumps(catalog.list_kb_tables(), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "status":
            print(json.dumps(loop.status(), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "start":
            print(
                json.dumps(
                    loop.start(
                        ticket_id=args.ticket_id,
                        acc_num=args.acc,
                        months=args.months,
                        claim=args.claim,
                        ticket_text=args.ticket_text,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.cmd == "pack":
            print(json.dumps(loop.pack(args.parts), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "fragments":
            print(
                json.dumps(
                    catalog.list_fragments(include_body=bool(args.body)),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.cmd == "admit":
            print(json.dumps(catalog.admit_fragment(args.name), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "ingest":
            print(json.dumps(loop.ingest(args.text), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "verify":
            print(json.dumps(loop.verify(), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "finish":
            print(json.dumps(loop.finish(), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "review":
            print(json.dumps(loop.review(), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "confirm":
            print(json.dumps(loop.confirm(), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "archive":
            print(json.dumps(loop.archive(args.finding), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "abandon":
            print(json.dumps(loop.abandon(args.reason), ensure_ascii=False, indent=2))
            return 0
    except ChainBroken as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
