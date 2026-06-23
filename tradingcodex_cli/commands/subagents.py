from __future__ import annotations

import sys
from pathlib import Path

from tradingcodex_service.application.agents import (
    AGENT_SPECS,
    diff_agent_configuration,
    inspect_agent_configuration,
    project_agent_configuration,
    EXPECTED_SUBAGENTS,
)
from tradingcodex_service.application.context_budget import audit_context_budget
from tradingcodex_service.application.harness import build_subagent_starter_prompt, build_workflow_intake_summary
from tradingcodex_cli.commands.utils import (
    _option_value,
    _parse_agent_list,
    list_skills,
    list_subagents,
    print_json,
    read_subagent_state,
    read_thread_policy,
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
        prompt = build_subagent_starter_prompt(request, root)
        summary = build_workflow_intake_summary(request, root)
        if json_output:
            print_json({"intake_summary": summary, "starter_prompt": prompt})
            return
        if explain:
            print(_format_prompt_explanation(summary, prompt))
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
            "thread_policy": read_thread_policy(root),
            "agents": agents,
        })
        return
    if sub == "state":
        print_json(read_subagent_state(root, _option_value(args, "--run")))
        return
    if sub == "context-audit":
        result = audit_context_budget(root, strict="--strict" in args)
        print_json(result)
        if result["status"] != "pass":
            sys.exit(1)
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
    if sub == "plan":
        installed = list_subagents(root)
        requested = [agent["name"] for agent in installed] if "--all" in args else _parse_agent_list(args)
        if not requested:
            raise ValueError("Usage: tcx subagents plan <agent...>|--all")
        installed_names = {agent["name"] for agent in installed}
        unknown = [agent for agent in requested if agent not in installed_names]
        thread_policy = read_thread_policy(root)
        size = max(1, int(thread_policy["max_parallel_subagents"]))
        batches = [{"batch": i + 1, "agents": requested[i:i + size]} for i in range(0, len(requested), size)]
        print_json({
            "requested_count": len(requested),
            "requested_agents": requested,
            "all_fixed_roster": "--all" in args,
            "unknown_agents": unknown,
            "thread_policy": thread_policy,
            "parallel_spawn_ok": not unknown and len(batches) == 1,
            "required_batches": len(batches),
            "batches": batches,
            "recommendation": "spawn requested subagents in one batch" if len(batches) == 1 else "spawn each batch sequentially and hand off artifacts before starting the next batch",
        })
        if unknown:
            sys.exit(1)
        return
    if sub == "skills":
        role = args[0] if args else ""
        if role not in AGENT_SPECS:
            raise ValueError(f"Unknown subagent or role: {role}")
        print_json({"agent": role, "skills": skills_for_role(root, role)})
        return
    raise ValueError(f"Unknown subagents command: {sub}")


def _format_prompt_explanation(summary: dict, prompt: str) -> str:
    lines = [
        f"Workflow: {summary.get('label') or 'Unknown'}",
        f"Question: {summary.get('primary_question') or 'Review the request before dispatch.'}",
        f"Universe: {summary.get('investment_universe_label') or summary.get('investment_universe') or 'unknown'}",
    ]
    idea_translation = summary.get("idea_translation") or {}
    if idea_translation:
        lines.append(f"Idea translated: {idea_translation.get('plain_english')}")
        lines.append(f"  Working hypothesis: {idea_translation.get('working_hypothesis')}")
        lines.append(f"  Safety boundary: {idea_translation.get('safety_boundary')}")
    subagents = summary.get("subagents") or []
    if subagents:
        lines.append("Selected roles: " + ", ".join(agent.get("label") or agent.get("role") for agent in subagents))
        lines.append("Why these roles:")
        for agent in subagents:
            lines.append(f"  - {agent.get('label') or agent.get('role')}: {agent.get('why_selected')}")
    else:
        lines.append("Selected roles: head-manager only")
    blocked = summary.get("blocked_actions") or []
    if blocked:
        lines.append("Still blocked: " + ", ".join(blocked))
    blocked_details = summary.get("blocked_action_details") or []
    if blocked_details:
        lines.append("Why blocked:")
        for item in blocked_details:
            lines.append(f"  - {item.get('label')}: {item.get('reason')}")
    review_highlights = summary.get("review_highlights") or []
    if review_highlights:
        lines.append("Decision checks:")
        for item in review_highlights:
            lines.append(f"  - {item.get('label')}: {item.get('detail')}")
    next_actions = summary.get("next_allowed_actions") or []
    if next_actions:
        lines.append("Next allowed actions:")
        for item in next_actions:
            lines.append(f"  - {item.get('label')}: {item.get('detail')}")
    method_lenses = summary.get("method_lenses") or []
    if method_lenses:
        lines.append("Method lenses:")
        for item in method_lenses:
            plain = item.get("plain")
            lines.append(f"  - {item.get('label')}: {item.get('detail')}")
            if plain:
                lines.append(f"     Plain meaning: {plain}")
            if item.get("reference"):
                lines.append(f"     Reference: {item.get('reference')}")
    loop_controls = summary.get("loop_controls") or []
    if loop_controls:
        lines.append("Iteration controls:")
        for item in loop_controls:
            lines.append(f"  - {item.get('label')}: {item.get('detail')}")
    judgment_controls = summary.get("judgment_controls") or []
    if judgment_controls:
        lines.append("Judgment controls:")
        for item in judgment_controls:
            lines.append(f"  - {item.get('label')}: {item.get('detail')}")
    strategy_baseline = summary.get("strategy_baseline") or {}
    if strategy_baseline:
        lines.append(f"Strategy baseline: {strategy_baseline.get('summary')}")
    profile_inputs = summary.get("investor_profile_inputs") or []
    if profile_inputs:
        lines.append("Profile needed before advice: " + ", ".join(profile_inputs))
    questions = summary.get("questions_to_answer") or []
    if questions:
        lines.append("Questions to answer:")
        for item in questions:
            lines.append(f"  - {item.get('question')} ({item.get('why_required')})")
    stages = summary.get("workflow_stages") or []
    if stages:
        lines.append("Workflow steps:")
        for index, stage in enumerate(stages, start=1):
            lines.append(f"  {index}. {stage.get('label')}: {stage.get('summary')}")
            exit_criteria = stage.get("exit_criteria") or []
            if exit_criteria:
                lines.append("     Needs: " + "; ".join(exit_criteria))
    lines.extend(["", "Codex prompt:", prompt])
    return "\n".join(lines)
