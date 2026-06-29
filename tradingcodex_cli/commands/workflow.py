from __future__ import annotations

from pathlib import Path

from tradingcodex_cli.commands.utils import print_json
from tradingcodex_service.application.decision_packages import build_workflow_plan, create_decision_package


def workflow(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "plan"
    args = argv[1:]
    prompt = " ".join(args).strip()
    if sub == "plan":
        if not prompt:
            raise ValueError("Usage: tcx workflow plan <investment request>")
        print_json(build_workflow_plan(root, prompt))
        return
    if sub == "run":
        if not prompt:
            raise ValueError("Usage: tcx workflow run <investment request>")
        print_json(create_decision_package(root, prompt))
        return
    raise ValueError("Usage: tcx workflow plan|run <investment request>")
