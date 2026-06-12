from __future__ import annotations

from pathlib import Path

from tradingcodex_cli.commands.utils import _option_value, print_json
from tradingcodex_service.application.agents import (
    create_or_update_strategy_skill,
    delete_strategy_skill,
    get_strategy_skill_record,
    read_strategy_skill_records,
    set_strategy_skill_status,
)


def strategies(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    if sub == "list":
        for record in read_strategy_skill_records(root, active_only="--active" in args):
            print(record["name"])
        return
    if sub == "inspect":
        name = args[0] if args else ""
        if not name:
            raise ValueError("Usage: tcx strategies inspect <name>")
        record = get_strategy_skill_record(root, name)
        print((root / str(record["source_file"])).read_text(encoding="utf-8"))
        return
    if sub in {"create", "update"}:
        name = args[0] if args and not args[0].startswith("--") else ""
        if not name:
            raise ValueError(f"Usage: tcx strategies {sub} <name> [--description <text>] [--body-file <path>]")
        status = "active" if "--active" in args else (_option_value(args, "--status") or "draft")
        print_json(
            create_or_update_strategy_skill(
                root,
                name,
                description=_option_value(args, "--description") or "",
                body=_body_arg(root, args),
                language=_option_value(args, "--language") or "unknown",
                status=status,
                actor="local-cli",
            )
        )
        return
    if sub in {"activate", "archive"}:
        name = args[0] if args else ""
        if not name:
            raise ValueError(f"Usage: tcx strategies {sub} <name>")
        print_json(set_strategy_skill_status(root, name, "active" if sub == "activate" else "archived", actor="local-cli"))
        return
    if sub == "delete":
        name = args[0] if args else ""
        if not name:
            raise ValueError("Usage: tcx strategies delete <name> [--force]")
        print_json(delete_strategy_skill(root, name, force="--force" in args, actor="local-cli"))
        return
    raise ValueError(f"Unknown strategies command: {sub}")


def _body_arg(root: Path, args: list[str]) -> str:
    body_file = _option_value(args, "--body-file")
    if body_file:
        path = Path(body_file)
        path = path if path.is_absolute() else root / path
        return path.read_text(encoding="utf-8")
    return _option_value(args, "--body") or ""
