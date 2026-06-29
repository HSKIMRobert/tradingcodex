from __future__ import annotations

from pathlib import Path

from tradingcodex_cli.commands.utils import _option_value, print_json
from tradingcodex_service.application.decision_packages import (
    export_decision_package,
    get_decision_package,
    list_decision_packages,
)


def decision(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    if sub == "list":
        print_json(list_decision_packages(root, int(_option_value(args, "--limit") or 50)))
        return
    if sub == "show":
        decision_id = args[0] if args and not args[0].startswith("--") else _option_value(args, "--id")
        if not decision_id:
            raise ValueError("Usage: tcx decision show <decision-id>")
        print_json(get_decision_package(root, decision_id))
        return
    if sub == "export":
        decision_id = args[0] if args and not args[0].startswith("--") else _option_value(args, "--id")
        if not decision_id:
            raise ValueError("Usage: tcx decision export <decision-id> [--export-path trading/decisions/file.md]")
        print_json(export_decision_package(root, decision_id, _option_value(args, "--export-path")))
        return
    raise ValueError("Usage: tcx decision list|show|export")
