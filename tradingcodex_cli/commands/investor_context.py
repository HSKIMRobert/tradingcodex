from __future__ import annotations

from pathlib import Path

from tradingcodex_cli.commands.utils import _option_value, print_json
from tradingcodex_service.application.investor_context import (
    INVESTOR_CONTEXT_FIELDS,
    clear_investor_context,
    read_investor_context,
    set_investor_context_enabled,
    update_investor_context,
)


OPTIONS = {
    "--objective": "investment_objective",
    "--horizon": "time_horizon",
    "--risk-tolerance": "risk_tolerance_and_loss_capacity",
    "--liquidity": "liquidity_needs",
    "--holdings": "current_holdings_and_concentrations",
    "--constraints": "constraints",
    "--notes": "notes",
}


def investor_context(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "status"
    args = argv[1:]
    if sub == "status":
        print_json(read_investor_context(root))
        return
    if sub == "update":
        updates = {
            field: value
            for option, field in OPTIONS.items()
            if (value := _option_value(args, option)) is not None
        }
        for field in INVESTOR_CONTEXT_FIELDS:
            clear_flag = f"--clear-{field.replace('_', '-')}"
            if clear_flag in args:
                updates[field] = None
        if not updates:
            raise ValueError(
                "Usage: tcx investor-context update --objective <text> --horizon <text> "
                "--risk-tolerance <text> --liquidity <text> --constraints <text> [--notes <text>]"
            )
        print_json(update_investor_context(root, updates, actor=_option_value(args, "--updated-by") or "user"))
        return
    if sub in {"enable", "disable"}:
        print_json(set_investor_context_enabled(root, sub == "enable", actor=_option_value(args, "--updated-by") or "user"))
        return
    if sub == "clear":
        print_json(clear_investor_context(root))
        return
    raise ValueError("Usage: tcx investor-context status|update|enable|disable|clear")
