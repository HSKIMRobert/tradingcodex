from __future__ import annotations

from pathlib import Path

from tradingcodex_cli.commands.utils import _option_value, json_object_input, print_json
from tradingcodex_service.application.forecasting import (
    calibration_report,
    get_forecast,
    list_forecasts,
)
from tradingcodex_service.mcp_runtime import call_mcp_tool


def _required_principal(args: list[str], usage: str) -> str:
    principal = _option_value(args, "--principal")
    if not principal:
        raise ValueError(f"{usage} --principal <role>")
    return principal


def forecast(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    if sub in {"issue", "revise", "resolve"}:
        input_path = _option_value(args, "--json-file") or (args[0] if args and not args[0].startswith("--") else None)
        usage = f"Usage: tcx forecast {sub} <payload.json|->"
        payload = json_object_input(root, input_path, usage)
        principal = _required_principal(args, usage)
        tool = {"issue": "issue_forecast", "revise": "revise_forecast", "resolve": "resolve_forecast"}[sub]
        print_json(call_mcp_tool(root, tool, payload, transport_principal=principal))
        return
    if sub == "score":
        forecast_id = args[0] if args and not args[0].startswith("--") else None
        if not forecast_id:
            raise ValueError("Usage: tcx forecast score <forecast-id> [--idempotency-key <key>]")
        usage = "Usage: tcx forecast score <forecast-id> [--idempotency-key <key>]"
        principal = _required_principal(args, usage)
        payload = {"forecast_id": forecast_id}
        if idempotency_key := _option_value(args, "--idempotency-key"):
            payload["idempotency_key"] = idempotency_key
        print_json(call_mcp_tool(
            root,
            "score_forecast",
            payload,
            transport_principal=principal,
        ))
        return
    if sub == "get":
        forecast_id = args[0] if args and not args[0].startswith("--") else None
        if not forecast_id:
            raise ValueError("Usage: tcx forecast get <forecast-id>")
        print_json(get_forecast(root, {"forecast_id": forecast_id, "include_history": "--latest-only" not in args}))
        return
    if sub == "list":
        print_json(list_forecasts(root, {
            "status": _option_value(args, "--status"),
            "role": _option_value(args, "--role"),
            "evidence_lane": _option_value(args, "--evidence-lane"),
            "limit": _option_value(args, "--limit") or 100,
        }))
        return
    if sub == "calibration":
        print_json(calibration_report(root, {
            "minimum_sample": _option_value(args, "--minimum-sample") or 20,
            "evidence_lane": _option_value(args, "--evidence-lane") or "live_forward",
        }))
        return
    raise ValueError(f"Unknown forecast command: {sub}")
