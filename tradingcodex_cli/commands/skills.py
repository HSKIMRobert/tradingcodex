from __future__ import annotations

from pathlib import Path

from tradingcodex_cli.commands.utils import _option_value, _validate_options, apply_skill_proposal, list_skills, print_json, write_skill_proposal
from tradingcodex_service.application.agents import (
    create_or_update_optional_skill,
    delete_optional_skill,
    get_optional_skill_record,
    read_optional_skill_records,
    set_optional_skill_status,
)

def skills(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    if sub == "optional":
        optional_skills(root, args)
        return
    if sub == "list":
        for skill in list_skills(root, include_internal="--all" in args):
            print(skill)
        return
    if sub == "inspect":
        name = args[0] if args else ""
        from tradingcodex_service.application.agents import build_projection_state

        skill = build_projection_state(root)["skills"].get(name)
        if not skill or not skill.get("source_file"):
            raise ValueError(f"Unknown skill: {name}")
        print((root / str(skill["source_file"])).read_text(encoding="utf-8"))
        return
    if sub in {"propose-add", "propose-update"}:
        target = _option_value(args, "--to")
        skill = _option_value(args, "--skill")
        if not target or not skill:
            raise ValueError(f"Usage: tcx skills {sub} --to <agent> --skill <skill>")
        print_json(write_skill_proposal(root, sub.replace("propose-", ""), target, skill))
        return
    if sub == "apply-proposal":
        proposal_path = Path(args[0]) if args else None
        if not proposal_path:
            raise ValueError("Usage: tcx skills apply-proposal <proposal.yaml> [--approved-by <principal>]")
        apply_skill_proposal(root, proposal_path if proposal_path.is_absolute() else root / proposal_path, _option_value(args, "--approved-by"))
        return
    raise ValueError(f"Unknown skills command: {sub}")


def optional_skills(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    _validate_options(
        args,
        value_options={"--body", "--body-file", "--description", "--role", "--status"},
        flag_options={"--active", "--force"},
    )
    role = _option_value(args, "--role")
    if sub == "list":
        for record in read_optional_skill_records(root, role=role, include_archived="--active" not in args):
            print(f"{record['role']}:{record['name']}")
        return
    if sub == "inspect":
        name = args[0] if args and not args[0].startswith("--") else ""
        if not role or not name:
            raise ValueError("Usage: tcx skills optional inspect <name> --role <agent>")
        record = get_optional_skill_record(root, role, name)
        print((root / str(record["source_file"])).read_text(encoding="utf-8"))
        return
    if sub in {"create", "update"}:
        name = args[0] if args and not args[0].startswith("--") else ""
        if not role or not name:
            raise ValueError(f"Usage: tcx skills optional {sub} <name> --role <agent> [--description <text>] [--body-file <path>]")
        body = _body_arg(root, args)
        status = "active" if "--active" in args else (_option_value(args, "--status") or "draft")
        print_json(create_or_update_optional_skill(root, role, name, description=_option_value(args, "--description") or "", body=body, status=status, actor="local-cli"))
        return
    if sub in {"activate", "archive"}:
        name = args[0] if args else ""
        if not role or not name:
            raise ValueError(f"Usage: tcx skills optional {sub} <name> --role <agent>")
        print_json(set_optional_skill_status(root, role, name, "active" if sub == "activate" else "archived", actor="local-cli"))
        return
    if sub == "delete":
        name = args[0] if args else ""
        if not role or not name:
            raise ValueError("Usage: tcx skills optional delete <name> --role <agent> [--force]")
        print_json(delete_optional_skill(root, role, name, force="--force" in args, actor="local-cli"))
        return
    raise ValueError(f"Unknown optional skills command: {sub}")


def _body_arg(root: Path, args: list[str]) -> str:
    body_file = _option_value(args, "--body-file")
    if body_file:
        path = Path(body_file)
        path = path if path.is_absolute() else root / path
        return path.read_text(encoding="utf-8")
    return _option_value(args, "--body") or ""
