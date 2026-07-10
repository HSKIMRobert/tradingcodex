from __future__ import annotations

from pathlib import Path

from tradingcodex_cli.commands.utils import _option_value, json_object_input, print_json
from tradingcodex_service.mcp_runtime import call_mcp_tool


def evaluation(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else ""
    args = argv[1:]
    operations = {
        "corpus": "create_evaluation_corpus",
        "run": "record_evaluation_run",
        "assign-review": "create_blind_review_assignment",
        "review-packet": "get_blind_review_packet",
        "blind-review": "record_blind_human_review",
        "compare": "compare_evaluation_runs",
    }
    tool = operations.get(sub)
    if tool is None:
        raise ValueError("Usage: tcx evaluation corpus|run|assign-review|review-packet|blind-review|compare <payload.json|-> --principal <id>")
    principal = _option_value(args, "--principal")
    if not principal:
        raise ValueError("--principal is required for every evaluation operation")
    input_path = _option_value(args, "--json-file") or _positional_input(args)
    payload = json_object_input(root, input_path, f"Usage: tcx evaluation {sub} <payload.json|-> --principal <id>")
    spoofable_fields = {"principal_id", "created_by", "reviewer", "assigned_by"} & set(payload)
    if spoofable_fields:
        raise ValueError(f"evaluation identity comes from --principal, not payload fields: {', '.join(sorted(spoofable_fields))}")
    print_json(call_mcp_tool(root, tool, payload, transport_principal=principal))


def _positional_input(args: list[str]) -> str | None:
    skip = False
    for item in args:
        if skip:
            skip = False
            continue
        if item in {"--principal", "--json-file"}:
            skip = True
            continue
        if not item.startswith("--"):
            return item
    return None
