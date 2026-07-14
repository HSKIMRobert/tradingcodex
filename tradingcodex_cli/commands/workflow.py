from __future__ import annotations

from pathlib import Path

from tradingcodex_cli.commands.utils import print_json
from tradingcodex_service.application.analysis_runs import begin_analysis_run, read_analysis_run
from tradingcodex_service.application.research import list_research_artifacts


def workflow(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] in {"help", "-h", "--help"}:
        print("Usage: tcx workflow begin <request>")
        print("       tcx workflow show <analysis-run-id>")
        return
    sub = argv[0]
    value = " ".join(argv[1:]).strip()
    if sub == "begin":
        if not value:
            raise ValueError("Usage: tcx workflow begin <request>")
        print_json(begin_analysis_run(root, value))
        return
    if sub == "show":
        if not value:
            raise ValueError("Usage: tcx workflow show <analysis-run-id>")
        run = read_analysis_run(root, value)
        if not run:
            raise ValueError(f"analysis run not found: {value}")
        print_json({
            "run": run,
            "artifacts": list_research_artifacts(root, {"workflow_run_id": value, "limit": 200})["artifacts"],
        })
        return
    raise ValueError("Usage: tcx workflow begin|show ...")
