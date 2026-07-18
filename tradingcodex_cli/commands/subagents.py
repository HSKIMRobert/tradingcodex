from __future__ import annotations

from pathlib import Path

from tradingcodex_service.application.agents import (
    AGENT_SPECS,
    diff_agent_configuration,
    inspect_agent_configuration,
    project_agent_configuration,
    EXPECTED_SUBAGENTS,
)
from tradingcodex_cli.commands.utils import (
    list_skills,
    list_subagents,
    print_json,
    skills_for_role,
)

def subagents(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    if sub == "list":
        for agent in list_subagents(root):
            print(f"{agent['name']}\t{agent['description']}")
        return
    if sub == "prompt":
        json_output = "--json" in args
        explain = "--explain" in args
        request = " ".join(arg for arg in args if arg not in {"--json", "--explain"}).strip()
        if not request:
            raise ValueError("Usage: tcx subagents prompt [--json|--explain] <investment request>")
        prompt = (
            "Use $tcx-workflow. Interpret the request directly, begin a lightweight analysis run, "
            "and dynamically coordinate the smallest useful exact-role team.\n\n" + request
        )
        if json_output:
            print_json({"orchestration": "codex_native", "starter_prompt": prompt})
            return
        if explain:
            print("Codex-native orchestration: Head Manager chooses and revises roles at runtime.\n\n" + prompt)
            return
        print(prompt)
        return
    if sub == "status":
        agents = list_subagents(root)
        print_json({
            "expected_count": len(EXPECTED_SUBAGENTS),
            "installed_count": len(agents),
            "fixed_roster_ok": len(agents) == len(EXPECTED_SUBAGENTS),
            "skills_installed": len(list_skills(root)),
            "agents": agents,
        })
        return
    if sub == "inspect":
        role = args[0] if args else ""
        if not role:
            raise ValueError("Usage: tcx subagents inspect <role>")
        print_json(inspect_agent_configuration(root, role))
        return
    if sub == "diff":
        role = args[0] if args and not args[0].startswith("--") else _option_value(args, "--role")
        if not role:
            raise ValueError("Usage: tcx subagents diff <role>")
        print_json(diff_agent_configuration(root, role))
        return
    if sub == "project":
        role = _option_value(args, "--role")
        proposal = _option_value(args, "--proposal")
        applied_by = _option_value(args, "--applied-by") or "local-cli"
        result = project_agent_configuration(
            root,
            role=role,
            proposal_path=(Path(proposal) if proposal else None),
            applied_by=applied_by,
        )
        print_json({"status": "projected", "projection_hash": result["projection_hash"], "manifest": ".tradingcodex/generated/projection-manifest.json"})
        return
    if sub == "skills":
        role = args[0] if args else ""
        if role not in AGENT_SPECS:
            raise ValueError(f"Unknown subagent or role: {role}")
        print_json({"agent": role, "skills": skills_for_role(root, role)})
        return
    raise ValueError(f"Unknown subagents command: {sub}")
