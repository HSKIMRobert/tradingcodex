from __future__ import annotations

from pathlib import Path

from tradingcodex_cli.commands.utils import _option_value, _validate_options, print_json
from tradingcodex_service.application.investment_brains import (
    get_investment_brain_record,
    install_investment_brain,
    read_investment_brain_records,
    remove_investment_brain,
    rollback_investment_brain,
    set_investment_brain_status,
    update_investment_brain,
    validate_investment_brain_source,
)


def investment_brains(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    if sub == "list":
        _validate_command_args(args, value_options=set(), flag_options={"--active", "--json"}, positional_count=0)
        records = read_investment_brain_records(root, include_removed="--active" not in args)
        if "--active" in args:
            records = [record for record in records if record["status"] == "active"]
        if "--json" in args:
            print_json(records)
        else:
            for record in records:
                print(f"{record['brain_id']}\t{record['version']}\t{record['status']}")
        return
    if sub == "inspect":
        _validate_command_args(args, value_options=set(), flag_options=set(), positional_count=1)
        brain_id = _required_id(args, "inspect")
        print_json(get_investment_brain_record(root, brain_id))
        return
    if sub == "validate":
        _validate_command_args(
            args,
            value_options={"--git", "--local", "--ref"},
            flag_options=set(),
            positional_count=0,
        )
        print_json(
            validate_investment_brain_source(
                root,
                local_source=_option_value(args, "--local"),
                git_source=_option_value(args, "--git"),
                ref=_option_value(args, "--ref") or "",
            )
        )
        return
    if sub == "install":
        _validate_command_args(
            args,
            value_options={"--git", "--local", "--ref"},
            flag_options={"--active", "--inactive"},
            positional_count=0,
        )
        if "--active" in args and "--inactive" in args:
            raise ValueError("select at most one of --active or --inactive")
        print_json(
            install_investment_brain(
                root,
                local_source=_option_value(args, "--local"),
                git_source=_option_value(args, "--git"),
                ref=_option_value(args, "--ref") or "",
                active="--inactive" not in args,
                actor="local-cli",
            )
        )
        return
    if sub == "update":
        _validate_command_args(
            args,
            value_options={"--git", "--local", "--ref"},
            flag_options=set(),
            positional_count=1,
        )
        brain_id = _required_id(args, "update")
        print_json(
            update_investment_brain(
                root,
                brain_id,
                local_source=_option_value(args, "--local"),
                git_source=_option_value(args, "--git"),
                ref=_option_value(args, "--ref"),
                actor="local-cli",
            )
        )
        return
    if sub in {"activate", "deactivate"}:
        _validate_command_args(args, value_options=set(), flag_options=set(), positional_count=1)
        brain_id = _required_id(args, sub)
        print_json(
            set_investment_brain_status(
                root,
                brain_id,
                "active" if sub == "activate" else "inactive",
                actor="local-cli",
            )
        )
        return
    if sub == "rollback":
        _validate_command_args(
            args,
            value_options={"--version"},
            flag_options=set(),
            positional_count=1,
        )
        brain_id = _required_id(args, "rollback")
        print_json(
            rollback_investment_brain(
                root,
                brain_id,
                version=_option_value(args, "--version") or "",
                actor="local-cli",
            )
        )
        return
    if sub == "remove":
        _validate_command_args(args, value_options=set(), flag_options=set(), positional_count=1)
        brain_id = _required_id(args, "remove")
        print_json(remove_investment_brain(root, brain_id, actor="local-cli"))
        return
    raise ValueError(f"Unknown investment-brains command: {sub}")


def _required_id(args: list[str], sub: str) -> str:
    brain_id = args[0] if args and not args[0].startswith("--") else ""
    if not brain_id:
        raise ValueError(f"Usage: tcx investment-brains {sub} <investment-brain-id>")
    return brain_id


def _validate_command_args(
    args: list[str],
    *,
    value_options: set[str],
    flag_options: set[str],
    positional_count: int,
) -> None:
    _validate_options(args, value_options=value_options, flag_options=flag_options)
    positionals: list[str] = []
    seen_options: set[str] = set()
    index = 0
    while index < len(args):
        value = args[index]
        if value in value_options:
            if value in seen_options:
                raise ValueError(f"investment-brains option may be supplied only once: {value}")
            seen_options.add(value)
            index += 2
            continue
        if value in flag_options:
            if value in seen_options:
                raise ValueError(f"investment-brains option may be supplied only once: {value}")
            seen_options.add(value)
            index += 1
            continue
        if not value.startswith("--"):
            positionals.append(value)
        index += 1
    if len(positionals) != positional_count:
        raise ValueError("investment-brains command received unexpected positional arguments")
