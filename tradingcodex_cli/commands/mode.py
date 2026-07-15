from __future__ import annotations

import argparse
from pathlib import Path

from tradingcodex_cli.commands.utils import print_json
from tradingcodex_cli.startup_status import detect_codex_permission_status
from tradingcodex_service.application.runtime_mode import RETIRED_MODE_REASON, get_runtime_mode_status


def mode(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "status"
    if sub == "status":
        parser = argparse.ArgumentParser(prog="tcx mode status")
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args(argv[1:])
        permission = detect_codex_permission_status(root)
        status = get_runtime_mode_status(
            root,
            full_access_detected=bool(permission.get("full_access_detected")),
        )
        if args.json:
            print_json(status)
            return
        print("TradingCodex persistent mode command: compatibility status only")
        print("Build authorization: exact `$tcx-build` invocation on the first meaningful line of a root native Codex turn")
        if status.get("legacy_mode_file_present"):
            print(f"Legacy mode file: {status['path']} (ignored)")
        print(f"Notice: {status['build_blocked_reason']}")
        return
    if sub == "set":
        raise ValueError(RETIRED_MODE_REASON)
    raise ValueError("Persistent `tcx mode` is retired; use `tcx mode status [--json]` only for compatibility")
