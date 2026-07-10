from __future__ import annotations

import argparse

from tradingcodex_cli.commands.utils import print_json
from tradingcodex_service.application.runtime import runtime_home_status


def home(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="tcx home")
    parser.add_argument("subcommand", nargs="?", choices=("status", "check"), default="status")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status = runtime_home_status()
    if args.json or args.subcommand == "status":
        print_json(status)
    else:
        print(f"TradingCodex home: {status['home']}")
        print(f"Source: {status['home_source']}")
        print(f"Database: {status['db_path']} ({status['db_source']})")
        print(status["diagnostic"])
    if args.subcommand == "check" and status["home_conflict"]:
        raise SystemExit(1)
