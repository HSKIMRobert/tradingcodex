from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client

from tradingcodex_cli.generator import (
    DEFAULT_MODULE_IDS,
    bootstrap_workspace,
    copy_template_tree,
    load_module_registry,
    resolve_module_graph,
    templates_dir,
)
from tradingcodex_service.domain import (
    build_subagent_starter_prompt,
    call_tool,
    count_harness_component_tags,
    ensure_runtime_database,
    get_harness_component,
    is_investment_workflow_request,
    is_secret_only_request,
    list_components_by_tag,
    list_harness_components,
    mcp_handle_rpc,
    validate_order_intent,
)
from tradingcodex_service.application.agents import (
    AGENT_SPECS,
    EXPECTED_SKILLS,
    EXPECTED_SUBAGENTS,
    SKILL_SPECS,
    project_agent_configuration,
    read_strategy_skill_records,
    validate_skill_assignment,
)
from tradingcodex_service.mcp_runtime import SAFE_HOME_TOOL_NAMES, static_mcp_tools
from tradingcodex_service.version import TRADINGCODEX_VERSION


ROOT = Path(__file__).resolve().parents[1]


def run(
    args: list[str],
    cwd: Path,
    input_text: str | None = None,
    expect_ok: bool = True,
    env_extra: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    for key, value in (env_extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    result = subprocess.run(args, cwd=cwd, input=input_text, text=True, capture_output=True, env=env, timeout=120)
    if expect_ok and result.returncode != 0:
        raise AssertionError(f"{args} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    if not expect_ok and result.returncode == 0:
        raise AssertionError(f"{args} unexpectedly succeeded\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    result = bootstrap_workspace(workspace, force=True)
    assert result["modules"]
    return workspace


def write_optional_skill_fixture(workspace: Path, role: str, skill_id: str) -> dict:
    title = "Filing Red Flag Review"
    description = "Review filings for accounting and disclosure red flags."
    skill_dir = workspace / ".tradingcodex" / "subagents" / "skills" / role / skill_id
    metadata_dir = skill_dir / "agents"
    skill_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {skill_id}",
                f'description: "{description}"',
                "---",
                "",
                f"# {title}",
                "",
                "Review filing excerpts for role-local red flags and cite source/as-of posture.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (metadata_dir / "openai.yaml").write_text(
        "\n".join(
            [
                "interface:",
                f'  display_name: "{title}"',
                '  short_description: "Review filings for red flags"',
                f'  default_prompt: "Use ${skill_id} to review filing excerpts for red flags."',
                "policy:",
                "  allow_implicit_invocation: false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    status = {
        "role": role,
        "skill_id": skill_id,
        "title": title,
        "description": description,
        "status": "active",
        "created_by": "test-head-manager",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_by": "test-head-manager",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    (metadata_dir / "tradingcodex.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return project_agent_configuration(workspace, role=role, applied_by="test-head-manager")


def write_strategy_skill_fixture(workspace: Path, skill_id: str = "strategy-quality-compounder") -> dict:
    skill_dir = workspace / ".tradingcodex" / "strategies" / skill_id
    metadata_dir = skill_dir / "agents"
    skill_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {skill_id}",
                'description: "Apply a quality compounder strategy with evidence discipline."',
                "type: strategy",
                "status: active",
                "language: ko-KR",
                "managed_by: strategy-creator",
                "owner: user",
                "last_reviewed: 2026-06-12",
                "---",
                "",
                "# Quality Compounder",
                "",
                "## Thesis",
                "Prefer durable business quality with valuation discipline.",
                "",
                "## Eligible Universe",
                "Public equities only.",
                "",
                "## Preferred Setups",
                "Quality companies with visible reinvestment runway.",
                "",
                "## Entry Criteria",
                "Evidence-backed quality and valuation support.",
                "",
                "## Exit Criteria",
                "Thesis break, valuation excess, or better opportunity cost.",
                "",
                "## Evidence Requirements",
                "Use source/as-of posture and mark missing evidence.",
                "",
                "## Decision-Ready Standard",
                "Research, valuation, portfolio, and risk support must be accepted.",
                "",
                "## Sizing Guidance",
                "Start small when uncertainty is high.",
                "",
                "## Block Conditions",
                "Block when evidence is stale, restricted, or policy denies action.",
                "",
                "## Portfolio And Risk Handoff",
                "Forward only accepted strategy-relevant constraints.",
                "",
                "## Change Log",
                "- 2026-06-12: Test fixture.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (metadata_dir / "openai.yaml").write_text(
        "\n".join(
            [
                "interface:",
                '  display_name: "Quality Compounder"',
                '  short_description: "Apply a quality strategy"',
                f'  default_prompt: "Use ${skill_id} to apply this user-approved strategy."',
                "policy:",
                "  allow_implicit_invocation: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return project_agent_configuration(workspace, applied_by="test-strategy")


def run_user_prompt_hook(workspace: Path, prompt: str, extra_payload: dict | None = None) -> dict | None:
    payload = {"prompt": prompt}
    if extra_payload:
        payload.update(extra_payload)
    result = run(
        [sys.executable, str(workspace / ".codex" / "hooks" / "tradingcodex_hook.py"), "user-prompt-submit"],
        workspace,
        input_text=json.dumps(payload),
    )
    if not result.stdout.strip():
        return None
    output = json.loads(result.stdout)
    return json.loads(output["hookSpecificOutput"]["additionalContext"])


def test_template_copy_skips_python_bytecode_cache(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    cache = source / "__pycache__"
    cache.mkdir(parents=True)
    (source / "script.py").write_text("print('{{PROJECT_NAME}}')\n", encoding="utf-8")
    (cache / "script.cpython-314.pyc").write_bytes(b"\x94\x00\x00\x00binary-bytecode")
    (source / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1\x00binary-finder-metadata")

    copy_template_tree(source, target, {"PROJECT_NAME": "demo"})

    assert (target / "script.py").read_text(encoding="utf-8") == "print('demo')\n"
    assert not (target / "__pycache__").exists()
    assert not (target / ".DS_Store").exists()
    assert not list(target.rglob("*.pyc"))


def test_workspace_template_module_contracts(tmp_path: Path) -> None:
    registry = load_module_registry(templates_dir())
    assert set(DEFAULT_MODULE_IDS).issubset(registry)
    for module_id, module in registry.items():
        assert module.id == module_id
        assert module.dir.name == module_id
        for dependency in module.manifest.get("requires", {}).get("modules", []):
            assert dependency in registry

    resolved = resolve_module_graph(registry, DEFAULT_MODULE_IDS)
    assert [module.id for module in resolved]

    workspace = make_workspace(tmp_path)
    for rel in [
        "AGENTS.md",
        ".codex/config.toml",
        ".codex/prompts/base_instructions/head-manager.md",
        ".codex/hooks/tradingcodex_hook.py",
        ".agents/skills/orchestrate-workflow/SKILL.md",
        ".tradingcodex/config.yaml",
        ".tradingcodex/workspace.json",
        "trading/research/.gitkeep",
        "tcx",
    ]:
        assert (workspace / rel).exists(), rel
    assert not (workspace / "package.json").exists()
    assert not list(workspace.rglob("__pycache__"))
    assert not list(workspace.rglob("*.pyc"))
    assert not (workspace / ".tradingcodex" / "state" / "tradingcodex.sqlite3").exists()


def test_investment_request_detection_avoids_repository_work() -> None:
    assert is_investment_workflow_request("Analyze NVDA")
    assert is_investment_workflow_request("Analyze Apple stock")
    assert is_investment_workflow_request("$orchestrate-workflow analyze Apple")
    assert not is_investment_workflow_request("Analyze AGENTS.md for stale guidance")
    assert not is_investment_workflow_request("Update the docs table")


def test_harness_component_registry_contract() -> None:
    components = list_harness_components()
    component_ids = [component["id"] for component in components]
    required = {
        "investment-request-routing",
        "fixed-role-dispatch",
        "research-memory",
        "workflow-quality-gates",
        "external-data-source-gate",
        "secret-wall",
        "policy-and-restricted-list",
        "approval-gate",
        "execution-boundary",
        "audit-ledger",
        "skill-improvement-loop",
        "postmortem-loop",
        "paper-execution",
    }

    assert len(component_ids) == len(set(component_ids))
    assert required.issubset(set(component_ids))
    for component in components:
        assert component["tags"], component["id"]
        assert component["surfaces"], component["id"]
        assert component["validation"], component["id"]
        for dependency in component["depends_on"]:
            assert dependency in component_ids

    assert get_harness_component("investment-request-routing")["label"] == "Investment Request Routing"
    assert get_harness_component("missing-component") is None
    guidance = list_components_by_tag("guardrail.guidance")
    assert "investment-request-routing" in {component["id"] for component in guidance}
    tag_counts = count_harness_component_tags()
    assert tag_counts["guardrail"] > 0
    assert tag_counts["improvement"] > 0


def test_file_native_agent_skill_registry_contract() -> None:
    assert "head-manager" in AGENT_SPECS
    assert len(EXPECTED_SUBAGENTS) == 9
    assert len(AGENT_SPECS) == 10
    assert len(EXPECTED_SKILLS) == 23
    assert "strategy-creator" in EXPECTED_SKILLS
    assert set(EXPECTED_SKILLS) == set(SKILL_SPECS)
    project_scope_errors = validate_skill_assignment("fundamental-analyst", "postmortem")
    assert project_scope_errors
    assert "project-scope mainagent skill" in project_scope_errors[0]
    errors = validate_skill_assignment("fundamental-analyst", "execute-paper-order")
    assert errors
    assert "blocked risk tags" in errors[0]
    assert "execution" in errors[0]
    assert "order" in errors[0]


def test_user_prompt_hook_auto_routes_plain_investment_requests(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    gate = run_user_prompt_hook(workspace, "Analyze Apple stock")
    assert gate
    assert gate["activation_source"] == "auto_routed_investment_request"
    assert gate["auto_dispatch_allowed"] is True
    assert gate["confirmation_required"] is False
    assert gate["requires_subagent_dispatch"] is True
    assert gate["workflow_lane"] == "research_only"
    assert gate["required_subagents"] == ["fundamental-analyst", "technical-analyst", "news-analyst"]
    assert "This selected team is binding for the current lane" in gate["starter_prompt"]
    assert "For `research_only`, do not add valuation, portfolio, risk, approval, or execution roles." in gate["starter_prompt"]

    negated_scope_gate = run_user_prompt_hook(
        workspace,
        "Routing smoke test for NVDA. No order, no trading, no valuation. Use selected subagents only.",
    )
    assert negated_scope_gate
    assert negated_scope_gate["workflow_lane"] == "research_only"
    assert negated_scope_gate["required_subagents"] == ["fundamental-analyst", "technical-analyst", "news-analyst"]
    negated_spawn_line = next(line for line in negated_scope_gate["starter_prompt"].splitlines() if line.startswith("Spawn these fixed role subagents"))
    assert "valuation-analyst" not in negated_spawn_line

    explicit_gate = run_user_prompt_hook(workspace, "$orchestrate-workflow analyze Apple stock")
    assert explicit_gate
    assert explicit_gate["activation_source"] == "explicit_subagent"
    assert explicit_gate["auto_dispatch_allowed"] is True

    secret_gate = run_user_prompt_hook(workspace, "Please inspect the .env file")
    assert secret_gate
    assert secret_gate["activation_source"] == "secret_warning_only"
    assert secret_gate["secret_warning"] is True
    assert secret_gate["requires_subagent_dispatch"] is False
    assert secret_gate["required_subagents"] == []

    broker_secret_gate = run_user_prompt_hook(workspace, "Here is my broker API key secret, save it to .env")
    assert broker_secret_gate
    assert broker_secret_gate["activation_source"] == "secret_warning_only"
    assert broker_secret_gate["workflow_lane"] == "secret_warning"
    assert broker_secret_gate["requires_subagent_dispatch"] is False
    assert broker_secret_gate["starter_prompt"] == ""
    assert is_secret_only_request("Here is my broker API key secret, save it to .env") is True
    assert is_investment_workflow_request("Here is my broker API key secret, save it to .env") is False
    assert is_secret_only_request("Use my broker API key to execute an AAPL order") is False
    assert is_investment_workflow_request("Use my broker API key to execute an AAPL order") is True

    subagent_brief_gate = run_user_prompt_hook(
        workspace,
        "Risk role brief: no order, no trading, no approval, no execution. Return a blocked-actions handoff.",
        {"agent_type": "risk-manager"},
    )
    assert subagent_brief_gate is None

    assert run_user_prompt_hook(workspace, "Update the docs table") is None


def test_repo_skill_templates_keep_instruction_boundary() -> None:
    skill_root = ROOT / "workspace_templates" / "modules" / "repo-skills" / "files" / ".agents" / "skills"
    subagent_skill_root = ROOT / "workspace_templates" / "modules" / "repo-skills" / "files" / ".tradingcodex" / "subagents" / "skills"
    skill_paths = sorted([*skill_root.glob("*/SKILL.md"), *subagent_skill_root.glob("*/*/SKILL.md")])
    skill_names = {path.parent.name for path in skill_paths}
    forbidden_phrases = [
        "Role ownership:",
        "This skill owns",
        "Use by ",
        "only inside",
        "must not use this skill",
        "should assign",
    ]
    role_ids = {
        "head-manager",
        "fundamental-analyst",
        "technical-analyst",
        "news-analyst",
        "macro-analyst",
        "instrument-analyst",
        "valuation-analyst",
        "portfolio-manager",
        "risk-manager",
        "execution-operator",
    }
    policy_principal_mentions = {
        "head-manager-interview": {"head-manager"},
        "create-order-intent": {"portfolio-manager"},
        "approve-order": {"risk-manager"},
        "execute-paper-order": {"risk-manager"},
    }

    for path in skill_paths:
        text = path.read_text(encoding="utf-8")
        skill_name = path.parent.name
        for phrase in forbidden_phrases:
            assert phrase not in text, f"{phrase!r} leaked into {path}"
        for other_skill in skill_names - {skill_name}:
            assert f"`{other_skill}`" not in text, f"{skill_name} directly references {other_skill}"
        allowed_roles = policy_principal_mentions.get(skill_name, set())
        for role_id in role_ids:
            if role_id in text and role_id not in allowed_roles:
                raise AssertionError(f"{skill_name} should not encode role-specific instruction for {role_id}")

    for metadata in sorted([*skill_root.glob("*/agents/openai.yaml"), *subagent_skill_root.glob("*/*/agents/openai.yaml")]):
        text = metadata.read_text(encoding="utf-8")
        assert "only inside" not in text
    metadata_paths = sorted([*skill_root.glob("*/agents/openai.yaml"), *subagent_skill_root.glob("*/*/agents/openai.yaml")])
    assert {path.parent.parent.name for path in metadata_paths} == skill_names
    import yaml

    for metadata in metadata_paths:
        skill_name = metadata.parent.parent.name
        data = yaml.safe_load(metadata.read_text(encoding="utf-8"))
        interface = data.get("interface", {})
        policy = data.get("policy", {})
        short_description = interface.get("short_description", "")
        default_prompt = interface.get("default_prompt", "")
        assert 25 <= len(short_description) <= 64, metadata
        assert f"${skill_name}" in default_prompt, metadata
        assert isinstance(policy.get("allow_implicit_invocation"), bool), metadata

    optional_skill_manager = (skill_root / "manage-optional-skills" / "SKILL.md").read_text(encoding="utf-8")
    assert "Use $skill-creator" in optional_skill_manager
    assert ".tradingcodex/subagents/skills/<role>/<skill-id>/SKILL.md" in optional_skill_manager
    head_manager_prompt = (
        ROOT / "workspace_templates/modules/codex-base/files/.codex/prompts/base_instructions/head-manager.md"
    ).read_text(encoding="utf-8")
    assert "`manage-optional-skills`" in head_manager_prompt
    assert "use `$skill-creator`" in head_manager_prompt


def test_install_docs_tell_agents_not_to_invent_workspace_paths() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "installation.md").read_text(encoding="utf-8")
    generated_workspaces = (ROOT / "docs" / "generated-workspaces.md").read_text(encoding="utf-8")

    for text in [readme, installation, generated_workspaces]:
        normalized = re.sub(r"\s+", " ", text)
        assert "do not invent" in normalized
        assert "ask" in normalized.lower()

    assert "tradingcodex-workspace" in installation
    assert "tradingcodex-workspace" in generated_workspaces


def test_python_generator_creates_workspace_contract(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    assert (workspace / "pyproject.toml").exists()
    assert f'version = "{TRADINGCODEX_VERSION}"' in (workspace / "pyproject.toml").read_text(encoding="utf-8")
    assert not (workspace / "package.json").exists()
    assert (workspace / "tcx").exists()
    assert not (workspace / "tradingcodex").exists()
    assert (workspace / ".tradingcodex" / "cli.py").exists()
    assert (workspace / ".tradingcodex" / "mcp" / "server.py").exists()
    assert (workspace / ".codex" / "hooks" / "tradingcodex_hook.py").exists()
    workspace_manifest = json.loads((workspace / ".tradingcodex" / "workspace.json").read_text(encoding="utf-8"))
    assert workspace_manifest["workspace_id"].startswith("tcxw_")
    assert workspace_manifest["active_profile"]["label"] == "shared central paper profile"
    assert workspace_manifest["mcp_scope"] == "project-scoped"
    assert workspace_manifest["execution_mode"] == "paper only"
    module_lock = json.loads((workspace / ".tradingcodex" / "generated" / "module-lock.json").read_text(encoding="utf-8"))
    capability_index = json.loads((workspace / ".tradingcodex" / "generated" / "capability-index.json").read_text(encoding="utf-8"))
    component_index = json.loads((workspace / ".tradingcodex" / "generated" / "component-index.json").read_text(encoding="utf-8"))
    agent_index = json.loads((workspace / ".tradingcodex" / "generated" / "agent-index.json").read_text(encoding="utf-8"))
    skill_index = json.loads((workspace / ".tradingcodex" / "generated" / "skill-index.json").read_text(encoding="utf-8"))
    projection_manifest = json.loads((workspace / ".tradingcodex" / "generated" / "projection-manifest.json").read_text(encoding="utf-8"))
    assert "modules" in module_lock
    assert "capabilities" in capability_index
    assert {component["id"] for component in component_index["components"]} == {component["id"] for component in list_harness_components()}
    assert component_index["source"] == "tradingcodex_service.application.components"
    assert agent_index["source"] == "tradingcodex_service.application.agents"
    assert skill_index["source"] == "workspace-files"
    assert projection_manifest["source"] == "file-native-agent-skill-projection"
    assert agent_index["projection_hash"] == skill_index["projection_hash"] == projection_manifest["projection_hash"]
    assert len(agent_index["agents"]) == 10
    assert len(skill_index["skills"]) == 23
    assert skill_index["skills"]["strategy-creator"]["source"] == "core"
    assert "external-data-source-gate" in agent_index["agents"]["fundamental-analyst"]["effective_skills"]
    assert "external-data-source-gate" in (workspace / ".codex" / "agents" / "fundamental-analyst.toml").read_text(encoding="utf-8")
    assert ".tradingcodex/subagents/skills/shared/external-data-source-gate/SKILL.md" in (workspace / ".codex" / "agents" / "fundamental-analyst.toml").read_text(encoding="utf-8")
    generated_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in workspace.rglob("*")
        if path.is_file() and path.suffix.lower() in {"", ".md", ".toml", ".yaml", ".yml", ".json", ".py"}
    )
    forbidden_disclosure_system_names = ["k-" + "da" + "rt", "".join(["D", "A", "R", "T"])]
    for forbidden in forbidden_disclosure_system_names:
        assert forbidden.lower() not in generated_text.lower()
    assert "official regulator or exchange disclosure sources" in generated_text
    assert "./tradingcodex" not in generated_text
    orchestrate_guidance = (workspace / ".agents" / "skills" / "orchestrate-workflow" / "SKILL.md").read_text(encoding="utf-8")
    manage_guidance = (workspace / ".agents" / "skills" / "manage-subagents" / "SKILL.md").read_text(encoding="utf-8")
    orchestration_guidance = orchestrate_guidance + "\n" + manage_guidance
    assert "fork_context=false" in orchestration_guidance
    assert "routing-unverified" in orchestration_guidance
    assert "This skill is the workflow entrypoint" in orchestration_guidance
    assert "This skill covers fixed-role subagent mechanics" in orchestration_guidance
    assert "Subagent briefs are assignment envelopes" in manage_guidance
    assert "Downstream roles consume accepted upstream artifacts" in manage_guidance
    assert "Treat the selected team from hook context or the starter prompt as binding" in orchestration_guidance
    assert "Do not combine a fixed `agent_type` with full-history forking" in manage_guidance
    assert "same compact message, fixed `agent_type`, no model/reasoning overrides, and no full-history fork" in manage_guidance
    assert "do not set `fork_context` to true" in orchestration_guidance
    assert "`accepted`, `revise`, `blocked`, or `waiting`" in orchestration_guidance
    assert "Workflow consent:" in manage_guidance
    assert "ROLE CARD:" not in manage_guidance
    assert "fork_turns" not in orchestration_guidance
    assert "task_name" not in orchestration_guidance
    hook_text = (workspace / ".codex" / "hooks" / "tradingcodex_hook.py").read_text(encoding="utf-8")
    assert 'payload.get("agent_type")' in hook_text
    assert not (workspace / ".tradingcodex" / "state" / "tradingcodex.sqlite3").exists()
    assert not (workspace / ".tradingcodex" / "state" / "paper-portfolio.json").exists()
    db_path = run(["./tcx", "db", "path"], workspace).stdout.strip()
    assert db_path != str((workspace / ".tradingcodex" / "state" / "tradingcodex.sqlite3").resolve())
    status = json.loads(run(["./tcx", "subagents", "status"], workspace).stdout)
    assert status["installed_count"] == 9
    assert status["fixed_roster_ok"] is True
    assert status["skills_installed"] == 23
    inspect = json.loads(run(["./tcx", "subagents", "inspect", "fundamental-analyst"], workspace).stdout)
    assert inspect["effective_skills"] == ["external-data-source-gate", "collect-evidence", "fundamental-analysis"]
    diff = json.loads(run(["./tcx", "subagents", "diff", "fundamental-analyst"], workspace).stdout)
    assert diff["missing_from_projected"] == []
    assert diff["extra_projected"] == []
    projected = json.loads(run(["./tcx", "subagents", "project", "--role", "fundamental-analyst"], workspace).stdout)
    assert projected["projection_hash"] == projection_manifest["projection_hash"]
    mainagent_metadata = list((workspace / ".agents" / "skills").glob("*/agents/openai.yaml"))
    subagent_metadata = list((workspace / ".tradingcodex" / "subagents" / "skills").glob("*/*/agents/openai.yaml"))
    assert len(mainagent_metadata) == 9
    assert len(mainagent_metadata) + len(subagent_metadata) == 23
    assert (workspace / ".tradingcodex" / "user" / "profile.md").exists()
    assert not (workspace / ".tradingcodex" / "mainagent" / "head-manager-interview.md").exists()
    assert not (workspace / ".agents" / "skills" / "head-manager-interview" / "references" / "investor-profile-reference.md").exists()
    workspace_status = json.loads(run(["./tcx", "workspace", "status"], workspace).stdout)
    assert workspace_status["workspace_id"] == workspace_manifest["workspace_id"]
    assert workspace_status["active_profile"]["portfolio_id"] == "default-paper"
    profile_status = json.loads(run(["./tcx", "profile", "status"], workspace).stdout)
    assert profile_status["active_profile"]["label"] == "shared central paper profile"
    doctor = run(["./tcx", "doctor"], workspace).stdout
    assert "TradingCodex doctor passed" in doctor
    assert "improvement" in doctor
    assert "TradingCodex MCP autostarts local service" in doctor
    assert "head-manager MCP execution submit excluded" in doctor
    assert "execution-operator MCP execution allowlist configured" in doctor
    assert "risk-manager MCP approval allowlist configured" in doctor
    improvement_doctor = run(["./tcx", "doctor", "--layer", "improvement"], workspace).stdout
    assert "TradingCodex doctor passed" in improvement_doctor
    assert "skill installed: orchestrate-workflow" in improvement_doctor
    assert "no-overlap handoff contract installed" in improvement_doctor
    legacy_doctor = run(["./tcx", "doctor", "--layer", "task-harness"], workspace).stdout
    assert "TradingCodex doctor passed" in legacy_doctor
    assert "improvement" in legacy_doctor
    hooks = json.loads((workspace / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    expected_hook_events = {
        "SessionStart",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "UserPromptSubmit",
        "SubagentStart",
        "SubagentStop",
        "Stop",
    }
    assert set(hooks) == expected_hook_events
    assert "matcher" not in hooks["UserPromptSubmit"][0]
    assert "matcher" not in hooks["Stop"][0]
    assert hooks["PreToolUse"][0]["matcher"] == "Bash|mcp__.*"
    assert hooks["SubagentStart"][0]["matcher"]
    service_usage = run(["./tcx", "service", "nope"], workspace, expect_ok=False)
    assert "Usage: tcx service runserver [addrport] [django runserver args]" in service_usage.stderr
    agent_files = sorted((workspace / ".codex" / "agents").glob("*.toml"))
    assert len(agent_files) == 9
    actual_mcp_tools = {tool["name"] for tool in static_mcp_tools()}
    stale_mcp_tool_names = {"evaluate_policy", "get_positions_snapshot", "write_audit_event"}
    root_config = tomllib.loads((workspace / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert root_config["default_permissions"] == "tradingcodex"
    assert root_config["model_instructions_file"] == "prompts/base_instructions/head-manager.md"
    assert "developer_instructions" not in root_config
    head_manager_instructions = (workspace / ".codex" / "prompts" / "base_instructions" / "head-manager.md").read_text(encoding="utf-8")
    assert "You are the `head-manager` agent" in head_manager_instructions
    assert "Codex-based local trading harness" in head_manager_instructions
    assert "asset-management workflow team" in head_manager_instructions
    assert "not an autonomous trading bot" not in head_manager_instructions
    assert "# How you work" in head_manager_instructions
    assert "# TradingCodex guardrails" in head_manager_instructions
    assert "# Tool guidelines" in head_manager_instructions
    assert not re.search(r"[\uac00-\ud7a3]", head_manager_instructions)
    assert "Use repo skills as dependency-light capability procedures" in head_manager_instructions
    assert "Skill files do not grant role eligibility" in head_manager_instructions
    assert "This base instruction owns" not in head_manager_instructions
    assert "## Operating style" in head_manager_instructions
    assert "Head-manager skill routing" in head_manager_instructions
    assert "## Handoff quality" in head_manager_instructions
    assert ".tradingcodex/user/profile.md" in head_manager_instructions
    assert "profile_context" in head_manager_instructions
    assert "strategy-creator" in head_manager_instructions
    assert "language precedence" in head_manager_instructions
    assert "Only accepted artifacts move downstream" in head_manager_instructions
    assert "apply_patch" in head_manager_instructions
    assert "investment dispatch gate" in head_manager_instructions
    workspace_agents = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "Codex agent working expectations" in workspace_agents
    assert "Follow every applicable `AGENTS.md`" in workspace_agents
    assert "Keep prompts lean" in workspace_agents
    assert root_config["permissions"]["tradingcodex"]["extends"] == ":workspace"
    assert root_config["permissions"]["tradingcodex"]["network"]["enabled"] is False
    assert "strategy-creator/SKILL.md" in (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert ".tradingcodex/subagents/skills/shared/collect-evidence/SKILL.md" not in (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
    for profile_name in [
        "tradingcodex-fundamental",
        "tradingcodex-technical",
        "tradingcodex-news",
        "tradingcodex-macro",
        "tradingcodex-instrument",
        "tradingcodex-valuation",
        "tradingcodex-portfolio",
        "tradingcodex-risk",
        "tradingcodex-execution",
    ]:
        filesystem_rules = root_config["permissions"][profile_name]["filesystem"][":workspace_roots"]
        assert filesystem_rules[".tradingcodex/user/**"] == "deny"
        assert filesystem_rules[".tradingcodex/strategies/**"] == "deny"
    expected_tcx_mcp_args = ["--refresh", "--python", "3.14", "--from", "tradingcodex", "python", "-m", "tradingcodex_cli", "mcp", "stdio"]
    root_mcp = root_config["mcp_servers"]["tradingcodex"]
    assert root_mcp["command"] == "uvx"
    assert root_mcp["args"] == expected_tcx_mcp_args
    assert root_mcp["enabled"] is True
    assert root_mcp["env"]["TRADINGCODEX_MCP_AUTOSTART_SERVICE"] == "1"
    assert root_mcp["env"]["TRADINGCODEX_SERVICE_ADDR"] == "127.0.0.1:8000"
    assert root_mcp["env"]["TRADINGCODEX_WORKSPACE_ROOT"] == str(workspace)
    assert set(root_mcp["enabled_tools"]).issubset(actual_mcp_tools)
    assert stale_mcp_tool_names.isdisjoint(root_mcp["enabled_tools"])
    assert "simulate_policy" in root_mcp["enabled_tools"]
    assert "get_tradingcodex_status" in root_mcp["enabled_tools"]
    assert "record_audit_event" in root_mcp["enabled_tools"]
    assert "get_portfolio_snapshot" in root_mcp["enabled_tools"]
    assert "submit_approved_order" not in root_mcp["enabled_tools"]
    assert "cancel_approved_order" not in root_mcp["enabled_tools"]
    for agent_file in agent_files:
        agent_config = agent_file.read_text(encoding="utf-8")
        agent_toml = tomllib.loads(agent_config)
        assert agent_toml["name"] == agent_file.stem
        assert agent_toml["description"]
        assert agent_toml["developer_instructions"]
        assert "request revision from the owning role" in agent_toml["developer_instructions"]
        assert 'model = "gpt-5.5"' in agent_config
        assert 'model_reasoning_effort = "high"' in agent_config
        agent_mcp = agent_toml["mcp_servers"]["tradingcodex"]
        assert agent_mcp["command"] == "uvx"
        assert agent_mcp["args"] == expected_tcx_mcp_args
        assert agent_mcp["env"]["TRADINGCODEX_MCP_AUTOSTART_SERVICE"] == "1"
        assert agent_mcp["env"]["TRADINGCODEX_WORKSPACE_ROOT"] == str(workspace)
        configured_tools = set(agent_mcp.get("enabled_tools", [])) | set(agent_mcp.get("disabled_tools", []))
        assert configured_tools.issubset(actual_mcp_tools), agent_file
        assert stale_mcp_tool_names.isdisjoint(configured_tools), agent_file
        if agent_file.stem == "risk-manager":
            assert "create_approval_receipt" in agent_mcp["enabled_tools"]
            assert "submit_approved_order" in agent_mcp["disabled_tools"]
        if agent_file.stem == "execution-operator":
            assert "submit_approved_order" in agent_mcp["enabled_tools"]
            assert "create_approval_receipt" not in agent_mcp["enabled_tools"]
    assert run(["./tcx", "skills", "list"], workspace).stdout.splitlines() == [
        "orchestrate-workflow",
        "head-manager-interview",
        "strategy-creator",
        "postmortem",
    ]
    assert len(run(["./tcx", "skills", "list", "--all"], workspace).stdout.splitlines()) == 23


def test_file_native_skill_proposal_and_projection_cli(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    proposed = json.loads(
        run(["./tcx", "skills", "propose-add", "--to", "fundamental-analyst", "--skill", "postmortem"], workspace).stdout
    )
    assert proposed["status"] == "blocked"
    assert "project-scope mainagent skill" in proposed["validation_errors"][0]
    blocked_project_scope = run(["./tcx", "skills", "apply-proposal", proposed["path"]], workspace, expect_ok=False)
    assert "project-scope mainagent skill" in blocked_project_scope.stderr
    assert not (workspace / ".tradingcodex" / "mainagent" / "applied-skill-changes.jsonl").exists()

    blocked = json.loads(
        run(["./tcx", "skills", "propose-add", "--to", "fundamental-analyst", "--skill", "execute-paper-order"], workspace).stdout
    )
    assert blocked["status"] == "blocked"
    assert "blocked risk tags" in blocked["validation_errors"][0]
    blocked_apply = run(["./tcx", "skills", "apply-proposal", blocked["path"]], workspace, expect_ok=False)
    assert "cannot receive execute-paper-order" in blocked_apply.stderr


def test_strategy_skills_are_root_visible_but_not_subagent_projected(tmp_path: Path, monkeypatch) -> None:
    workspace = make_workspace(tmp_path)
    strategy_id = "strategy-quality-compounder"
    state = write_strategy_skill_fixture(workspace, strategy_id)
    legacy_id = "strategy-legacy-reading"
    legacy_dir = workspace / ".agents" / "skills" / legacy_id
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "SKILL.md").write_text((workspace / ".tradingcodex" / "strategies" / strategy_id / "SKILL.md").read_text(encoding="utf-8").replace(strategy_id, legacy_id), encoding="utf-8")
    state = project_agent_configuration(workspace, applied_by="test-legacy-strategy")

    assert state["skills"][strategy_id]["source"] == "strategy"
    assert state["skills"][strategy_id]["active"] is True
    legacy_record = next(record for record in read_strategy_skill_records(workspace) if record["id"] == legacy_id)
    assert legacy_record["legacy"] is True
    root_config_text = (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "# BEGIN TradingCodex strategy skills" in root_config_text
    assert f".tradingcodex/strategies/{strategy_id}/SKILL.md" in root_config_text
    assert f".agents/skills/{legacy_id}/SKILL.md" not in root_config_text
    for agent_file in sorted((workspace / ".codex" / "agents").glob("*.toml")):
        assert f"{strategy_id}/SKILL.md" not in agent_file.read_text(encoding="utf-8")

    assert strategy_id in run(["./tcx", "skills", "list"], workspace).stdout.splitlines()
    assert legacy_id not in run(["./tcx", "skills", "list"], workspace).stdout.splitlines()
    assert strategy_id in run(["./tcx", "skills", "list", "--all"], workspace).stdout.splitlines()
    assert legacy_id in run(["./tcx", "skills", "list", "--all"], workspace).stdout.splitlines()

    monkeypatch.setenv("TRADINGCODEX_WORKSPACE_ROOT", str(workspace))
    client = Client(REMOTE_ADDR="127.0.0.1")
    assert strategy_id in client.get("/api/harness/skills").json()["skills"]
    assert strategy_id in client.get("/api/harness/skills?include_internal=true").json()["skills"]


def test_init_prepares_central_django_runtime(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "tc-home"
    result = run(
        [sys.executable, "-m", "tradingcodex_cli", "init", str(workspace)],
        ROOT,
        env_extra={"TRADINGCODEX_DB_NAME": None, "TRADINGCODEX_HOME": str(home)},
    )
    db_path = home / "state" / "tradingcodex.sqlite3"

    assert f"Central DB: {db_path}" in result.stdout
    assert "Workspace ID: tcxw_" in result.stdout
    assert "Active Profile: shared central paper profile" in result.stdout
    assert "MCP Scope: project-scoped" in result.stdout
    assert "Execution Mode: paper only" in result.stdout
    assert "./tcx doctor" in result.stdout
    assert db_path.exists()
    assert not (workspace / ".tradingcodex" / "state" / "tradingcodex.sqlite3").exists()
    assert 'DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-tradingcodex_service.settings}"' in (workspace / "tcx").read_text(encoding="utf-8")
    generated_cli = (workspace / ".tradingcodex" / "cli.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")' in generated_cli
    assert "from tradingcodex_cli.__main__ import main" in generated_cli
    generated_mcp_server = (workspace / ".tradingcodex" / "mcp" / "server.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")' in generated_mcp_server
    assert "maybe_autostart_service" in generated_mcp_server

    with sqlite3.connect(db_path) as connection:
        table_names = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
        assert "harness_workspacecontext" in table_names
        assert "harness_skillproposal" not in table_names
        assert "harness_roleskillassignment" not in table_names
        assert "mcp_mcptooldefinition" in table_names
        assert "research_researchartifact" not in table_names
        assert "research_researchartifactversion" not in table_names
        assert "research_sourcesnapshot" not in table_names
        assert "research_evidencepack" not in table_names
        assert connection.execute("select count(*) from django_migrations where app = 'orders' and name = '0001_initial'").fetchone()[0] == 1
        assert connection.execute("select count(*) from django_migrations where app = 'research' and name = '0002_remove_research_db_models'").fetchone()[0] == 1
        assert connection.execute("select count(*) from harness_workspacecontext where path = ?", (str(workspace.resolve()),)).fetchone()[0] == 1
        assert connection.execute("select workspace_id from harness_workspacecontext where path = ?", (str(workspace.resolve()),)).fetchone()[0].startswith("tcxw_")


def test_init_current_directory_and_overwrite_language(tmp_path: Path) -> None:
    workspace = tmp_path / "current-workspace"
    workspace.mkdir()
    home = tmp_path / "tc-home-current"
    env_extra = {"TRADINGCODEX_DB_NAME": None, "TRADINGCODEX_HOME": str(home)}

    result = run([sys.executable, "-m", "tradingcodex_cli", "init", "."], workspace, env_extra=env_extra)

    assert f"TradingCodex workspace created: {workspace.resolve()}" in result.stdout
    assert (workspace / "tcx").exists()
    assert json.loads((workspace / ".tradingcodex" / "generated" / "module-lock.json").read_text(encoding="utf-8"))["tradingcodex_version"] == TRADINGCODEX_VERSION

    repeated = run([sys.executable, "-m", "tradingcodex_cli", "init", "."], workspace, expect_ok=False, env_extra=env_extra)
    assert "--overwrite" in repeated.stderr
    assert "--force" not in repeated.stderr

    overwrite = run([sys.executable, "-m", "tradingcodex_cli", "init", ".", "--overwrite"], workspace, env_extra=env_extra)
    assert f"TradingCodex workspace created: {workspace.resolve()}" in overwrite.stdout

    help_text = run([sys.executable, "-m", "tradingcodex_cli", "init", "--help"], workspace, env_extra=env_extra).stdout
    assert "--overwrite" in help_text
    assert "--force" not in help_text


def test_attach_current_directory_preserves_workspace_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "attach-workspace"
    workspace.mkdir()
    home = tmp_path / "tc-home-attach"
    env_extra = {"TRADINGCODEX_DB_NAME": None, "TRADINGCODEX_HOME": str(home)}

    attached = run([sys.executable, "-m", "tradingcodex_cli", "attach", "."], workspace, env_extra=env_extra)
    manifest = json.loads((workspace / ".tradingcodex" / "workspace.json").read_text(encoding="utf-8"))
    workspace_id = manifest["workspace_id"]

    assert f"TradingCodex workspace attached: {workspace.resolve()}" in attached.stdout
    assert "MCP Scope: project-scoped" in attached.stdout
    assert workspace_id.startswith("tcxw_")

    refreshed = run([sys.executable, "-m", "tradingcodex_cli", "attach", "."], workspace, env_extra=env_extra)
    refreshed_manifest = json.loads((workspace / ".tradingcodex" / "workspace.json").read_text(encoding="utf-8"))
    assert refreshed_manifest["workspace_id"] == workspace_id
    assert f"TradingCodex workspace attached: {workspace.resolve()}" in refreshed.stdout


def test_init_allows_git_initialized_empty_current_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "git-workspace"
    (workspace / ".git").mkdir(parents=True)
    home = tmp_path / "tc-home-git-current"
    env_extra = {"TRADINGCODEX_DB_NAME": None, "TRADINGCODEX_HOME": str(home)}

    result = run([sys.executable, "-m", "tradingcodex_cli", "init", "."], workspace, env_extra=env_extra)

    assert f"TradingCodex workspace created: {workspace.resolve()}" in result.stdout
    assert (workspace / ".git").is_dir()
    assert (workspace / "AGENTS.md").exists()
    assert (workspace / ".codex" / "config.toml").exists()
    assert (workspace / "tcx").exists()


def test_generated_tcx_wrapper_uses_recorded_workspace_root_from_other_cwd(tmp_path: Path) -> None:
    workspace = tmp_path / "absolute-wrapper-workspace"
    home = tmp_path / "tc-home-absolute-wrapper"
    env_extra = {"TRADINGCODEX_DB_NAME": None, "TRADINGCODEX_HOME": str(home)}
    run([sys.executable, "-m", "tradingcodex_cli", "init", str(workspace)], ROOT, env_extra=env_extra)

    doctor = run([str(workspace / "tcx"), "doctor"], ROOT, env_extra=env_extra)

    assert "TradingCodex doctor passed" in doctor.stdout
    assert f"workspace={workspace.resolve()}" in doctor.stdout


def test_starter_prompt_keeps_negated_actions_out_of_execution() -> None:
    macro = build_subagent_starter_prompt("rates oil impact on NVDA position no order")
    assert "Workflow lane: portfolio_risk_review" in macro
    assert "macro-analyst" in macro
    assert "execution-operator" not in macro
    assert "Use handoff states: accepted, revise, blocked, waiting." in macro
    assert "Do not let downstream roles redo missing upstream work" in macro
    meta_macro = build_subagent_starter_prompt("rates oil impact on my NVDA position, no order. Verify routing and blocked order/approval/execution actions.")
    assert "Workflow lane: portfolio_risk_review" in meta_macro
    assert "macro-analyst" in meta_macro
    assert "execution-operator" not in meta_macro
    blocked_wording = build_subagent_starter_prompt("rates and oil impact on my NVDA position, no order. Do not place trades. Even with blocked action wording like execute, submit, approve, or order, verify portfolio_risk_review routing and no execution-operator.")
    assert "Workflow lane: portfolio_risk_review" in blocked_wording
    assert "macro-analyst" in blocked_wording
    blocked_spawn_line = next(line for line in blocked_wording.splitlines() if line.startswith("Spawn these fixed role subagents"))
    assert "execution-operator" not in blocked_spawn_line
    earnings = build_subagent_starter_prompt("NVDA earnings preview and catalyst review, no order and no trading")
    assert "Workflow lane: thesis_review" in earnings
    assert "fundamental-analyst" in earnings
    assert "news-analyst" in earnings
    assert "valuation-analyst" in earnings
    assert "execution-operator" not in earnings
    earnings_no_valuation = build_subagent_starter_prompt("NVDA earnings preview and catalyst review, no valuation, no order and no trading")
    assert "Workflow lane: thesis_review" in earnings_no_valuation
    earnings_no_valuation_spawn_line = next(line for line in earnings_no_valuation.splitlines() if line.startswith("Spawn these fixed role subagents"))
    assert "valuation-analyst" not in earnings_no_valuation_spawn_line
    crypto = build_subagent_starter_prompt("BTC trend review no trading")
    assert "Investment universe: public_crypto" in crypto
    assert "instrument-analyst" in crypto
    assert "fundamental-analyst" not in crypto
    assert "execution-operator" not in crypto
    broad = build_subagent_starter_prompt("Analyze NVDA for me. No order and no trading.")
    assert "Workflow lane: research_only" in broad
    assert "Spawn these fixed role subagents in parallel: fundamental-analyst, technical-analyst, news-analyst" in broad
    assert "This selected team is binding for the current lane" in broad
    assert "For `research_only`, do not add valuation, portfolio, risk, approval, or execution roles." in broad
    assert "do not set `fork_context` to true" in broad
    no_valuation = build_subagent_starter_prompt("Routing smoke test for NVDA. No order, no trading, no valuation. Use selected subagents only.")
    assert "Workflow lane: research_only" in no_valuation
    no_valuation_spawn_line = next(line for line in no_valuation.splitlines() if line.startswith("Spawn these fixed role subagents"))
    assert "valuation-analyst" not in no_valuation_spawn_line


def test_workspace_cli_order_policy_and_execution(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    order = {
        "id": "smoke-order-2",
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 1,
        "limit_price": 1000,
        "currency": "KRW",
        "broker": "paper-trading",
        "estimated_notional_krw": 1000,
        "created_by": "portfolio-manager",
        "created_at": "2026-01-01T00:00:00Z",
    }
    order_path = workspace / "trading" / "orders" / "draft" / "smoke-order-2.order_intent.json"
    order_path.write_text(json.dumps(order), encoding="utf-8")
    assert json.loads(run(["./tcx", "validate", "order", str(order_path.relative_to(workspace))], workspace).stdout)["valid"] is True
    approval = json.loads(run(["./tcx", "approve", str(order_path.relative_to(workspace)), "--approved-by", "risk-manager"], workspace).stdout)
    assert approval["status"] == "approved"
    execution = json.loads(run(["./tcx", "mcp", "call", "submit_approved_order", "--order-intent-id", order["id"]], workspace).stdout)
    assert execution["status"] == "accepted"
    assert execution["db_canonical"] is True
    assert execution["idempotency_key"].startswith("submit:")
    assert execution["result"]["portfolio_id"] == "default-paper"
    assert (workspace / "trading" / "orders" / "executed" / "smoke-order-2.execution_result.json").exists()
    duplicate = json.loads(run(["./tcx", "mcp", "call", "submit_approved_order", "--order-intent-id", order["id"]], workspace, expect_ok=False).stdout)
    assert duplicate["status"] == "rejected"
    assert "already has an execution result" in "\n".join(duplicate["reasons"])
    snapshot = json.loads(run(["./tcx", "mcp", "call", "get_portfolio_snapshot"], workspace).stdout)
    assert snapshot["positions"]["AAPL"]["quantity"] == 1.0

    created_profile = json.loads(run(["./tcx", "profile", "create", "strategy-lab"], workspace).stdout)
    assert created_profile["profile"]["portfolio_id"] == "strategy-lab"
    selected_profile = json.loads(run(["./tcx", "profile", "select", "strategy-lab"], workspace).stdout)
    assert selected_profile["active_profile"]["portfolio_id"] == "strategy-lab"
    isolated_snapshot = json.loads(run(["./tcx", "mcp", "call", "get_portfolio_snapshot"], workspace).stdout)
    assert isolated_snapshot["portfolio_id"] == "strategy-lab"
    assert isolated_snapshot["positions"] == {}


def test_restricted_and_live_orders_are_blocked(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    blocked = {
        "id": "blocked",
        "symbol": "BLOCKED",
        "side": "buy",
        "quantity": 1,
        "limit_price": 1000,
        "currency": "KRW",
        "broker": "paper-trading",
        "estimated_notional_krw": 1000,
        "created_by": "portfolio-manager",
        "created_at": "2026-01-01T00:00:00Z",
    }
    result = validate_order_intent(workspace, {"principal_id": "portfolio-manager", "order_intent": blocked})
    assert result["valid"] is False
    assert "symbol is restricted: BLOCKED" in "\n".join(result["reasons"])
    live = {**blocked, "id": "live", "symbol": "TSLA", "broker": "live"}
    live_result = validate_order_intent(workspace, {"principal_id": "portfolio-manager", "order_intent": live})
    assert live_result["valid"] is False
    assert "live broker adapter is not installed" in "\n".join(live_result["reasons"])
    self_approval = call_tool(workspace, "simulate_policy", {
        "principal_id": "head-manager",
        "action": "approval.self_issue",
        "resource": "*",
    })
    assert self_approval["decision"] == "deny"
    approval_create = call_tool(workspace, "simulate_policy", {
        "principal_id": "head-manager",
        "action": "approval_receipt.create",
        "resource": "*",
    })
    assert approval_create["decision"] == "deny"
    assert "only risk-manager can create approval receipts" in "\n".join(approval_create["reasons"])
    direct_broker = call_tool(workspace, "simulate_policy", {
        "principal_id": "head-manager",
        "action": "broker_api.call_direct",
        "resource": "live_broker_api",
    })
    assert direct_broker["decision"] == "deny"
    live_submit = call_tool(workspace, "simulate_policy", {
        "principal_id": "head-manager",
        "action": "execution.submit_live_order",
        "resource": "live_broker_adapter",
    })
    assert live_submit["decision"] == "deny"
    execute_order = call_tool(workspace, "simulate_policy", {
        "principal_id": "head-manager",
        "action": "execute_order",
        "resource": "TSLA",
    })
    assert execute_order["decision"] == "deny"


def test_capabilities_are_enforced_before_mcp_and_policy(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    ensure_runtime_database(workspace)
    from apps.policy.models import Capability, Principal
    from apps.policy.services import sync_builtin_principals_and_capabilities

    sync_builtin_principals_and_capabilities()
    capability = Capability.objects.get(principal__principal_id="fundamental-analyst", action="research_artifact.write")
    capability.effect = "deny"
    capability.save(update_fields=["effect"])
    forbidden = mcp_handle_rpc(workspace, {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "create_research_artifact",
            "arguments": {
                "principal_id": "fundamental-analyst",
                "artifact_id": "capability-denied-note",
                "title": "Denied",
                "markdown": "# Denied",
            },
        },
    })
    assert forbidden and "capability denied" in forbidden["error"]["message"]

    capability.effect = "allow"
    capability.save(update_fields=["effect"])
    Principal.objects.filter(principal_id="fundamental-analyst").update(active=False)
    inactive = mcp_handle_rpc(workspace, {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "create_research_artifact",
            "arguments": {
                "principal_id": "fundamental-analyst",
                "artifact_id": "inactive-principal-note",
                "title": "Inactive",
                "markdown": "# Inactive",
            },
        },
    })
    assert inactive and "not allowed" in inactive["error"]["message"]
    Principal.objects.filter(principal_id="fundamental-analyst").update(active=True)

    Capability.objects.filter(principal__principal_id="portfolio-manager", action="order_intent.validate").update(effect="deny")
    order = {
        "id": "capability-order",
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 1,
        "limit_price": 1000,
        "currency": "KRW",
        "broker": "paper-trading",
        "estimated_notional_krw": 1000,
        "created_by": "portfolio-manager",
        "created_at": "2026-01-01T00:00:00Z",
    }
    result = validate_order_intent(workspace, {"principal_id": "portfolio-manager", "order_intent": order})
    assert result["valid"] is False
    assert "capability denied" in "\n".join(result["reasons"])


def test_mcp_stdio_and_http_minimum_surface(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    initialized = mcp_handle_rpc(workspace, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert initialized and initialized["result"]["serverInfo"]["name"] == "tradingcodex"
    tools = mcp_handle_rpc(workspace, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert tools and any(tool["name"] == "submit_approved_order" for tool in tools["result"]["tools"])
    assert any(tool["name"] == "create_research_artifact" for tool in tools["result"]["tools"])
    for tool in tools["result"]["tools"]:
        annotations = tool["annotations"]
        assert isinstance(annotations["category"], str)
        assert isinstance(annotations["risk_level"], str)
        assert isinstance(annotations["allowed_roles"], list)
        assert isinstance(annotations["requires_approval"], bool)
        assert isinstance(annotations["audit_required"], bool)
    submit_tool = next(tool for tool in tools["result"]["tools"] if tool["name"] == "submit_approved_order")
    assert submit_tool["annotations"]["risk_level"] == "execution"
    assert submit_tool["annotations"]["allowed_roles"] == ["execution-operator"]
    assert submit_tool["annotations"]["audit_required"] is True
    assert submit_tool["annotations"]["experimental"] is True
    status_tool = next(tool for tool in tools["result"]["tools"] if tool["name"] == "get_tradingcodex_status")
    assert status_tool["annotations"]["audit_required"] is True
    tool_names = {tool["name"] for tool in tools["result"]["tools"]}
    assert "index_research_artifact_embedding" not in tool_names
    assert "semantic_search_research_artifacts" not in tool_names
    assert "ai_review_research_artifact" not in tool_names
    assert "evaluate_policy" not in tool_names
    assert "get_positions_snapshot" not in tool_names
    assert "write_audit_event" not in tool_names
    assert "simulate_policy" in tool_names
    assert "get_portfolio_snapshot" in tool_names
    assert "record_audit_event" in tool_names
    stdio_input = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    stdio = run(["./tcx", "mcp", "stdio"], workspace, input_text=stdio_input)
    assert "submit_approved_order" in stdio.stdout
    client = Client(REMOTE_ADDR="127.0.0.1")
    response = client.get("/mcp")
    assert response.status_code == 200
    assert response.json()["endpoint"] == "/mcp"
    batch = client.post(
        "/mcp",
        data=json.dumps([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
        ]),
        content_type="application/json",
    )
    assert batch.status_code == 200
    assert isinstance(batch.json(), list)


def test_global_home_mcp_safe_config_excludes_sensitive_tools(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    config_path = tmp_path / "codex-config.toml"

    installed = json.loads(run(["./tcx", "mcp", "install-global", "--safe", "--config", str(config_path)], workspace).stdout)
    config = config_path.read_text(encoding="utf-8")

    assert installed["server_name"] == "tradingcodex-home"
    assert "mcp_servers.tradingcodex-home" in config
    assert "TRADINGCODEX_MCP_SAFE_TOOLS" in config
    assert "submit_approved_order" not in installed["safe_tools"]
    assert "create_approval_receipt" not in installed["safe_tools"]
    assert "cancel_approved_order" not in installed["safe_tools"]
    assert set(installed["safe_tools"]) == set(SAFE_HOME_TOOL_NAMES)

    previous = os.environ.get("TRADINGCODEX_MCP_SAFE_TOOLS")
    os.environ["TRADINGCODEX_MCP_SAFE_TOOLS"] = "1"
    try:
        initialized = mcp_handle_rpc(workspace, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        tools = mcp_handle_rpc(workspace, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tool_names = {tool["name"] for tool in tools["result"]["tools"]}
        forbidden = mcp_handle_rpc(workspace, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "submit_approved_order", "arguments": {}},
        })
    finally:
        if previous is None:
            os.environ.pop("TRADINGCODEX_MCP_SAFE_TOOLS", None)
        else:
            os.environ["TRADINGCODEX_MCP_SAFE_TOOLS"] = previous

    assert initialized and initialized["result"]["serverInfo"]["name"] == "tradingcodex-home"
    assert tool_names == set(SAFE_HOME_TOOL_NAMES)
    assert forbidden and "safe scope" in forbidden["error"]["message"]


def test_django_ninja_control_api() -> None:
    client = Client(REMOTE_ADDR="127.0.0.1")
    assert client.get("/api/health").json()["status"] == "ok"
    status = client.get("/api/harness/status").json()
    assert status["expected_count"] == 9
    assert status["skills_installed"] == 23
    assert status["core_skills_installed"] == 23
    assert status["optional_skills_active"] >= 0
    assert status["user_visible_skills"] == ["orchestrate-workflow", "head-manager-interview", "strategy-creator", "postmortem"]
    assert status["components_total"] == len(list_harness_components())
    assert status["component_tag_counts"]["guardrail"] > 0
    assert client.get("/api/harness/skills").json()["skills"] == status["user_visible_skills"]
    assert len(client.get("/api/harness/skills?include_internal=true").json()["skills"]) == 23
    components = client.get("/api/harness/components").json()
    assert {component["id"] for component in components["components"]} == {component["id"] for component in list_harness_components()}
    component = client.get("/api/harness/components/investment-request-routing")
    assert component.status_code == 200
    assert component.json()["surfaces"]["hooks"] == ["UserPromptSubmit"]
    assert client.get("/api/harness/components/not-real").status_code == 404
    assert len(client.get("/api/subagents").json()) == 9
    assert "portfolio-review" in client.get("/api/subagents/portfolio-manager/skills").json()["skills"]
    response = client.post(
        "/api/policy/simulate",
        data=json.dumps({"principal_id": "execution-operator", "action": "mcp.tradingcodex.submit_approved_order"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["decision"] in {"allow", "deny"}


def test_default_django_admin() -> None:
    ensure_runtime_database(ROOT)
    User = get_user_model()
    user, _ = User.objects.get_or_create(username="admin-ui-test", defaults={"is_staff": True, "is_superuser": True})
    user.is_staff = True
    user.is_superuser = True
    user.set_password("admin")
    user.save()

    anonymous = Client(REMOTE_ADDR="127.0.0.1")
    login_response = anonymous.get("/admin/login/")
    assert login_response.status_code == 200
    login_body = login_response.content.decode()
    assert "Django administration" in login_body
    assert "tcx Control Plane" not in login_body
    assert "tradingcodex_admin/admin.css" not in login_body

    client = Client(REMOTE_ADDR="127.0.0.1")
    client.force_login(user)
    response = client.get("/admin/")
    body = response.content.decode()
    assert response.status_code == 200
    assert "Site administration" in body
    assert "Django administration" in body
    assert "What do you want to check?" not in body
    assert "Open research memory" not in body
    assert "research_researchartifact" not in body
    assert "Check current state" not in body
    assert "Review drafts and approvals" not in body
    assert "Review restrictions and blocks" not in body
    assert "Start with this flow" not in body
    assert "Advanced admin tables" not in body
    assert "Central investment ledger connected" not in body
    assert "tcx Home" not in body
    assert "Capabilities" in body
    assert "Capabilitys" not in body
    assert "MCP tool definitions" in body
    assert "Workspace contexts" in body
    assert "tradingcodex_admin/admin.css" not in body

    favicon_response = client.get("/favicon.ico")
    assert favicon_response.status_code == 302
    assert favicon_response["Location"].endswith("/static/tradingcodex_admin/favicon.svg")


def test_mcp_admin_service_actions_write_audit_events() -> None:
    ensure_runtime_database(ROOT)
    from apps.audit.models import AuditEvent
    from apps.mcp.models import McpToolDefinition
    from apps.mcp.services import set_mcp_tools_enabled, sync_builtin_mcp_registry
    from tradingcodex_service.mcp_runtime import prepare_mcp_runtime

    prepare_mcp_runtime(ROOT)
    before = AuditEvent.objects.count()
    queryset = McpToolDefinition.objects.filter(name="submit_approved_order")
    assert queryset.exists()
    set_mcp_tools_enabled(queryset, False, "admin-service-test")
    set_mcp_tools_enabled(queryset, True, "admin-service-test")
    sync_builtin_mcp_registry("admin-service-test")
    assert AuditEvent.objects.count() >= before + 3
    assert AuditEvent.objects.filter(action="mcp_tool.disabled", actor_principal="admin-service-test").exists()
    assert AuditEvent.objects.filter(action="mcp_tool.enabled", actor_principal="admin-service-test").exists()
    assert AuditEvent.objects.filter(action="mcp_tool_registry.synced", actor_principal="admin-service-test").exists()


def test_product_web_agents_first_routes_render_skill_preview() -> None:
    ensure_runtime_database(ROOT)
    client = Client(REMOTE_ADDR="127.0.0.1")

    dashboard = client.get("/")
    assert dashboard.status_code == 302
    assert dashboard["Location"].endswith("/harness/agents/")

    harness = client.get("/harness/")
    assert harness.status_code == 302
    assert harness["Location"].endswith("/harness/agents/")

    agents = client.get("/harness/agents/")
    assert agents.status_code == 200
    body = agents.content.decode()
    assert "Agents" in body
    assert "TradingCodex" in body
    assert "tcx tcx" not in body
    assert "Head Manager" in body
    assert "Required skills" in body
    assert "Optional skills" in body
    assert "Markdown preview" in body
    assert "head-manager" in body
    assert "fundamental-analyst" in body
    assert "execution-operator" in body
    assert "orchestrate-workflow" in body
    assert 'href="/policy/"' not in body
    assert 'href="/activity/"' not in body
    assert 'href="/portfolio/"' not in body
    assert 'href="/orders/"' not in body
    assert 'href="/harness/"' not in body
    assert 'href="/"' not in body
    assert "tc-workspace-card" in body
    assert 'aria-label="Open workspace folder"' in body
    assert "Open path" not in body
    assert "tc-sidebar-context" not in body
    assert "Remove ref" in body
    assert '<span class="tc-section-title">Boundary</span>' not in body
    assert "tc-sidebar-resizer" in body
    assert "static/tradingcodex_web/app.css" in body
    assert "tcx-shadcn-7" in body
    assert "static/vendor/htmx/htmx.min.js" in body
    assert "static/vendor/alpine/alpine.min.js" in body
    assert "TRADINGCODEX_API_KEY" not in body

    selected = client.get("/harness/agents/?role=fundamental-analyst&skill=fundamental-analysis")
    selected_body = selected.content.decode()
    assert selected.status_code == 200
    assert "fundamental-analysis" in selected_body
    assert "Fundamental Analysis" in selected_body
    assert "Frontmatter" in selected_body
    assert "Description" in selected_body

    for route in ["/harness/agents/", "/harness/agents/fundamental-analyst/skills/", "/harness/strategies/", "/research/", "/portfolio/", "/orders/", "/policy/", "/activity/", "/workflow/starter-prompt/"]:
        response = client.get(route)
        assert response.status_code == 200
        assert "tcx" in response.content.decode()
        assert "TRADINGCODEX_API_KEY" not in response.content.decode()

    admin_response = client.get("/admin/login/")
    assert admin_response.status_code == 200
    assert "Django administration" in admin_response.content.decode()
    assert "tcx Control Plane" not in admin_response.content.decode()


def test_product_web_agent_skill_and_strategy_mutation(tmp_path: Path, monkeypatch) -> None:
    workspace = make_workspace(tmp_path)
    monkeypatch.setenv("TRADINGCODEX_WORKSPACE_ROOT", str(workspace))
    projected = write_optional_skill_fixture(workspace, "fundamental-analyst", "filing-red-flag-review")
    assert "filing-red-flag-review" in projected["agents"]["fundamental-analyst"]["effective_skills"]
    client = Client(REMOTE_ADDR="127.0.0.1")

    index = client.get("/harness/agents/")
    assert index.status_code == 200
    index_body = index.content.decode()
    assert "Head Manager" in index_body
    assert "Required skills" in index_body
    assert "Optional skills" in index_body
    assert "Diagnostics" in index_body

    detail = client.get("/harness/agents/?role=fundamental-analyst&skill=filing-red-flag-review")
    detail_body = detail.content.decode()
    assert detail.status_code == 200
    assert "filing-red-flag-review" in detail_body
    assert "Filing Red Flag Review" in detail_body
    assert "Review filing excerpts" in detail_body
    assert "Diagnostics" in detail_body

    created = client.post(
        "/harness/agents/fundamental-analyst/optional-skills/create/",
        data={
            "skill_id": "source-quality-check",
            "title": "Source Quality Check",
            "description": "Check whether cited evidence is fresh and source-tagged.",
            "body": "# Source Quality Check\n\nReview assigned evidence for source quality.",
            "status": "active",
        },
    )
    assert created.status_code == 302
    optional_path = workspace / ".tradingcodex" / "subagents" / "skills" / "fundamental-analyst" / "source-quality-check" / "SKILL.md"
    assert optional_path.exists()
    agent_toml = (workspace / ".codex" / "agents" / "fundamental-analyst.toml").read_text(encoding="utf-8")
    assert ".tradingcodex/subagents/skills/fundamental-analyst/source-quality-check/SKILL.md" in agent_toml

    strategy_created = client.post(
        "/harness/strategies/create/",
        data={
            "strategy_id": "strategy-quality-income",
            "title": "Quality Income",
            "description": "Apply a quality income strategy.",
            "language": "ko-KR",
            "body": "# Quality Income\n\nFocus on durable income quality.",
            "status": "active",
        },
    )
    assert strategy_created.status_code == 302
    strategy_path = workspace / ".tradingcodex" / "strategies" / "strategy-quality-income" / "SKILL.md"
    assert strategy_path.exists()
    root_config = (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert ".tradingcodex/strategies/strategy-quality-income/SKILL.md" in root_config
    assert ".tradingcodex/strategies/strategy-quality-income/SKILL.md" not in agent_toml

    api_status = client.get("/api/harness/optional-skills?role=fundamental-analyst").json()
    assert {record["skill_id"] for record in api_status["optional_skills"]} >= {"filing-red-flag-review", "source-quality-check"}
    assert "strategy-quality-income" in {record["id"] for record in client.get("/api/harness/strategies").json()["strategies"]}
    api_optional = client.post(
        "/api/subagents/fundamental-analyst/optional-skills",
        data=json.dumps({
            "skill_id": "evidence-freshness-check",
            "title": "Evidence Freshness Check",
            "description": "Check source timestamps before handoff.",
            "body": "# Evidence Freshness Check\n\nCheck source timestamps.",
            "status": "active",
        }),
        content_type="application/json",
    )
    assert api_optional.status_code == 200
    assert "evidence-freshness-check" in (workspace / ".codex" / "agents" / "fundamental-analyst.toml").read_text(encoding="utf-8")
    api_strategy = client.post(
        "/api/harness/strategies",
        data=json.dumps({
            "strategy_id": "strategy-catalyst-watch",
            "title": "Catalyst Watch",
            "description": "Track catalyst-driven setups.",
            "body": "# Catalyst Watch\n\nTrack catalyst-driven setups.",
            "status": "active",
        }),
        content_type="application/json",
    )
    assert api_strategy.status_code == 200
    assert "strategy-catalyst-watch" in (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
    mcp_tool_names = {tool["name"] for tool in client.get("/api/integrations/mcp-tools").json()["tools"]}
    assert "create_optional_role_skill" not in mcp_tool_names
    assert "update_optional_role_skill" not in mcp_tool_names
    assert "delete_optional_role_skill" not in mcp_tool_names


def test_product_web_research_artifact_markdown_preview(tmp_path: Path, monkeypatch) -> None:
    workspace = make_workspace(tmp_path)
    monkeypatch.setenv("TRADINGCODEX_WORKSPACE_ROOT", str(workspace))
    from tradingcodex_service.application.markdown_preview import render_markdown_preview
    from tradingcodex_service.application.research import create_research_artifact, get_research_artifact

    stored = create_research_artifact(
        workspace,
        {
            "artifact_id": "web-preview-note",
            "artifact_type": "research_memo",
            "title": "Web Preview Note",
            "symbol": "NVDA",
            "markdown": "# Web Preview Note\n\n[factual] Preview body.\n\n<script>alert('x')</script>",
            "readiness_label": "research-grade",
            "export": False,
        },
    )
    assert stored["db_canonical"] is False
    assert stored["file_sot"] is True
    assert (workspace / stored["export_path"]).exists()
    source_with_frontmatter = workspace / "source-frontmatter.md"
    source_with_frontmatter.write_text(
        "---\nartifact_id: source-frontmatter-note\ntitle: Source Frontmatter Note\nsource_as_of: 2026-06-03\n---\n\n# Source Body\n",
        encoding="utf-8",
    )
    frontmatter_stored = create_research_artifact(
        workspace,
        {
            "markdown_path": "source-frontmatter.md",
            "artifact_type": "research_memo",
            "created_by": "fundamental-analyst",
        },
    )
    frontmatter_text = (workspace / frontmatter_stored["export_path"]).read_text(encoding="utf-8")
    assert frontmatter_text.count("---") == 2
    assert get_research_artifact(workspace, {"artifact_id": "source-frontmatter-note"})["markdown"] == "# Source Body\n"
    client = Client(REMOTE_ADDR="127.0.0.1")

    response = client.get("/research/?artifact=web-preview-note")
    body = response.content.decode()
    assert response.status_code == 200
    assert "Web Preview Note" in body
    assert "Frontmatter" in body
    assert "Artifact Id" in body
    assert "web-preview-note" in body
    assert "Readiness Label" in body
    assert "<h1>Web Preview Note</h1>" in body
    assert "Preview body" in body
    assert "<script>alert" not in body
    assert "<hr" not in body

    rendered = render_markdown_preview("# Safe\n\n<script>alert('x')</script>")
    assert "<script" not in rendered.html
    frontmatter_rendered = render_markdown_preview("---\ntitle: Frontmatter Title\n---\n\n# Body Only\n")
    assert frontmatter_rendered.frontmatter["title"] == "Frontmatter Title"
    assert "<h1>Body Only</h1>" in frontmatter_rendered.html
    assert "title:" not in frontmatter_rendered.html


def test_product_web_workspace_selector_uses_session(tmp_path: Path, monkeypatch) -> None:
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    bootstrap_workspace(workspace_a, force=True)
    bootstrap_workspace(workspace_b, force=True)
    monkeypatch.setenv("TRADINGCODEX_WORKSPACE_ROOT", str(workspace_a))

    from tradingcodex_service.application.runtime import persist_workspace_context_if_available
    from tradingcodex_service.web import WORKSPACE_SESSION_KEY

    context_a = persist_workspace_context_if_available(workspace_a)
    context_b = persist_workspace_context_if_available(workspace_b)
    client = Client(REMOTE_ADDR="127.0.0.1")

    landing = client.get("/harness/agents/")
    landing_body = landing.content.decode()
    assert landing.status_code == 200
    assert "tc-workspace-card" in landing_body
    assert 'aria-label="Open workspace folder"' in landing_body
    assert "Open path" not in landing_body
    assert "tc-sidebar-context" not in landing_body
    assert "Remove ref" in landing_body
    assert '<span class="tc-section-title">Boundary</span>' not in landing_body
    assert context_a["workspace_id"] in landing_body
    assert context_b["workspace_id"] in landing_body

    selected = client.get(f"/harness/agents/?workspace={context_b['workspace_id']}")
    selected_body = selected.content.decode()
    assert selected.status_code == 200
    assert client.session[WORKSPACE_SESSION_KEY] == context_b["workspace_id"]
    assert str(workspace_b.resolve()) in selected_body

    for route in ["/harness/agents/fundamental-analyst/skills/", "/research/"]:
        response = client.get(route)
        assert response.status_code == 200
        assert str(workspace_b.resolve()) in response.content.decode()

    fallback = client.get("/harness/agents/?workspace=missing-workspace")
    assert fallback.status_code == 200
    assert str(workspace_a.resolve()) in fallback.content.decode()
    assert WORKSPACE_SESSION_KEY not in client.session

    unbootstrapped = tmp_path / "unbootstrapped-repo"
    unbootstrapped.mkdir()
    (unbootstrapped / "README.md").write_text("# Existing repo\n", encoding="utf-8")
    from tradingcodex_service import web as web_module

    monkeypatch.setattr(web_module, "_choose_workspace_directory", lambda: unbootstrapped.resolve())
    opened = client.post("/workspaces/browse/", {"next": "/research/"})
    assert opened.status_code == 302
    assert (unbootstrapped / ".tradingcodex" / "workspace.json").exists()
    opened_body = client.get("/research/").content.decode()
    assert str(unbootstrapped.resolve()) in opened_body
    assert "Workspace bootstrapped and opened." in opened_body

    from apps.harness.models import WorkspaceContext

    opened_context = WorkspaceContext.objects.get(path=str(unbootstrapped.resolve()))
    removed = client.post(f"/workspaces/{opened_context.workspace_id}/remove/", {"next": "/research/"})
    assert removed.status_code == 302
    assert not WorkspaceContext.objects.filter(workspace_id=opened_context.workspace_id).exists()
    assert (unbootstrapped / ".tradingcodex" / "workspace.json").exists()


def test_product_web_role_inspector_and_topology_helpers() -> None:
    client = Client(REMOTE_ADDR="127.0.0.1")

    response = client.get("/harness/roles/portfolio-manager/")
    body = response.content.decode()
    assert response.status_code == 200
    assert "Portfolio Manager" in body
    assert "portfolio-review" in body
    assert "create-order-intent" in body
    assert "validate_order_intent" in body
    assert "No self-approval" in body
    assert "No-overlap" in body
    assert "Does not self-approve, execute, or repair missing research/valuation work." in body

    from tradingcodex_service.domain import get_harness_topology, get_role_detail

    topology = get_harness_topology(ROOT)
    roles = {node["role"] for node in topology["nodes"]}
    node_by_role = {node["role"]: node for node in topology["nodes"]}
    assert "head-manager" in roles
    assert len(roles - {"head-manager"}) == 9
    assert node_by_role["head-manager"]["y"] < node_by_role["fundamental-analyst"]["y"]
    assert node_by_role["fundamental-analyst"]["y"] < node_by_role["valuation-analyst"]["y"]
    assert node_by_role["valuation-analyst"]["y"] < node_by_role["portfolio-manager"]["y"]
    assert node_by_role["portfolio-manager"]["y"] < node_by_role["risk-manager"]["y"]
    assert node_by_role["risk-manager"]["y"] < node_by_role["execution-operator"]["y"]
    assert topology["boundary"]["x"] < node_by_role["execution-operator"]["x"]
    assert "capability" in topology["boundary"]["summary"]
    assert "idempotency" in topology["boundary"]["summary"]
    assert [layer["label"] for layer in topology["layers"]] == [
        "Coordinator",
        "Research roles",
        "Valuation",
        "Portfolio fit",
        "Risk approval",
        "MCP execution",
    ]
    assert {edge["group"] for edge in topology["edges"]} == {
        "dispatch",
        "research-handoff",
        "portfolio-risk-gate",
        "approval-gate",
        "execution-gate",
    }
    assert topology["handoff_states"] == ["accepted", "revise", "blocked", "waiting"]
    assert all(group["contract"] for group in topology["edge_groups"])
    detail = get_role_detail("execution-operator", ROOT)
    assert any(tool["name"] == "submit_approved_order" for tool in detail["allowed_tools"])
    assert "No raw broker API." in detail["forbidden_actions"]
    assert detail["handoff_contract"]["receives"] == "Approved order intent, approval receipt, and policy allow state."


def test_workflow_artifact_refs_store_handoff_state() -> None:
    ensure_runtime_database(ROOT)
    from apps.workflows.models import ArtifactRef, WorkflowRun

    run_obj = WorkflowRun.objects.create(
        run_id=f"handoff-state-{os.getpid()}",
        lane="research_only",
        universe="public_equity",
        readiness_label="factual-baseline",
    )
    ref = ArtifactRef.objects.create(
        workflow=run_obj,
        path="trading/reports/fundamental/NVDA.fundamental.md",
        artifact_type="fundamental_report",
        role="fundamental-analyst",
        handoff_state="accepted",
    )

    assert ref.handoff_state == "accepted"
    assert ArtifactRef.objects.get(pk=ref.pk).handoff_state == "accepted"


def test_product_web_does_not_create_approvals_or_executions(monkeypatch) -> None:
    ensure_runtime_database(ROOT)
    from apps.audit.models import AuditEvent
    from apps.mcp.models import McpToolCall
    from apps.orders.models import ApprovalReceipt, ExecutionResult, OrderIntent

    def forbidden_execution(*args, **kwargs):
        raise AssertionError("product web route attempted an execution-sensitive action")

    monkeypatch.setattr("tradingcodex_service.domain.submit_approved_order", forbidden_execution)
    monkeypatch.setattr("tradingcodex_service.domain.create_approval_receipt", forbidden_execution)

    before = (
        OrderIntent.objects.count(),
        ApprovalReceipt.objects.count(),
        ExecutionResult.objects.count(),
        McpToolCall.objects.count(),
        AuditEvent.objects.count(),
    )
    client = Client(REMOTE_ADDR="127.0.0.1")
    for route in [
        "/",
        "/harness/",
        "/research/",
        "/portfolio/",
        "/orders/",
        "/policy/",
        "/activity/",
        "/workflow/starter-prompt/",
        "/workflow/starter-prompt/preview/?q=NVDA%20earnings%20review%20no%20order",
    ]:
        response = client.get(route, follow=route in {"/", "/harness/"})
        assert response.status_code == 200
    after = (
        OrderIntent.objects.count(),
        ApprovalReceipt.objects.count(),
        ExecutionResult.objects.count(),
        McpToolCall.objects.count(),
        AuditEvent.objects.count(),
    )
    assert after == before

    preview = client.get("/workflow/starter-prompt/preview/?q=BTC%20trend%20review%20no%20trading")
    body = preview.content.decode()
    assert "Investment universe: public_crypto" in body
    assert "execution-operator" not in body


def test_central_db_env_overrides(tmp_path: Path) -> None:
    home = tmp_path / "tc-home"
    home_path = run(
        [sys.executable, "-m", "tradingcodex_cli", "db", "path"],
        ROOT,
        env_extra={"TRADINGCODEX_DB_NAME": None, "TRADINGCODEX_HOME": str(home)},
    ).stdout.strip()
    assert home_path == str(home / "state" / "tradingcodex.sqlite3")

    explicit = tmp_path / "explicit.sqlite3"
    explicit_path = run(
        [sys.executable, "-m", "tradingcodex_cli", "db", "path"],
        ROOT,
        env_extra={"TRADINGCODEX_DB_NAME": str(explicit), "TRADINGCODEX_HOME": str(home / "ignored")},
    ).stdout.strip()
    assert explicit_path == str(explicit)


def test_generated_mcp_server_uses_central_db_default(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    home = tmp_path / "tc-home"
    stdio_input = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"

    stdio = run(
        [sys.executable, str(workspace / ".tradingcodex" / "mcp" / "server.py")],
        workspace,
        input_text=stdio_input,
        env_extra={"TRADINGCODEX_DB_NAME": None, "TRADINGCODEX_HOME": str(home)},
    )

    assert "submit_approved_order" in stdio.stdout
    assert (home / "state" / "tradingcodex.sqlite3").exists()
    assert not (workspace / ".tradingcodex" / "state" / "tradingcodex.sqlite3").exists()


def test_file_native_research_artifacts_via_mcp_api_and_cli(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    stored = call_tool(workspace, "create_research_artifact", {
        "artifact_id": "nvda-evidence-1",
        "artifact_type": "evidence_pack",
        "universe": "public_equity",
        "workflow_type": "issuer_baseline",
        "symbol": "NVDA",
        "title": "NVDA Evidence Pack",
        "markdown": "# NVDA Evidence\n\n[factual] Gross margin expanded in the cited period.",
        "metadata": {"role": "fundamental"},
        "source_as_of": "2026-06-01",
        "readiness_label": "research-grade",
        "created_by": "fundamental-analyst",
    })
    assert stored["db_canonical"] is False
    assert stored["file_sot"] is True
    assert stored["workspace_native"] is True
    assert stored["export_path"] == "trading/research/nvda-evidence-1.evidence.md"
    assert (workspace / stored["export_path"]).exists()
    fetched = call_tool(workspace, "get_research_artifact", {"artifact_id": "nvda-evidence-1"})
    assert "Gross margin" in fetched["markdown"]
    assert fetched["source_as_of"] == "2026-06-01"
    assert fetched["role"] == "fundamental"
    assert 'source_as_of: "2026-06-01"' in (workspace / stored["export_path"]).read_text(encoding="utf-8")
    assert 'role: "fundamental"' in (workspace / stored["export_path"]).read_text(encoding="utf-8")
    searched = call_tool(workspace, "search_research_artifacts", {"query": "gross margin"})
    assert any(item["artifact_id"] == "nvda-evidence-1" for item in searched["artifacts"])
    from apps.mcp.models import McpToolCall, McpToolDefinition

    assert McpToolDefinition.objects.filter(name="create_research_artifact", category="research").exists()
    assert not McpToolCall.objects.filter(tool_name__in=["create_research_artifact", "get_research_artifact", "search_research_artifacts"]).exists()
    snapshot = call_tool(workspace, "record_source_snapshot", {
        "provider": "unit-test",
        "source_category": "filing",
        "as_of": "2026-06-01",
        "artifact_id": "nvda-evidence-1",
        "warnings": ["stale after 7 days"],
        "payload": {"url": "https://example.test/nvda"},
    })
    assert snapshot["db_canonical"] is False
    assert snapshot["file_sot"] is True
    assert snapshot["export_path"].startswith("trading/research/source-snapshots/")
    assert (workspace / snapshot["export_path"]).exists()
    forbidden = mcp_handle_rpc(workspace, {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "submit_approved_order", "arguments": {"principal_id": "head-manager"}},
    })
    assert forbidden and "not allowed" in forbidden["error"]["message"]

    previous_root = os.environ.get("TRADINGCODEX_WORKSPACE_ROOT")
    os.environ["TRADINGCODEX_WORKSPACE_ROOT"] = str(workspace)
    try:
        client = Client(REMOTE_ADDR="127.0.0.1")
        response = client.post(
            "/api/research/artifacts",
            data=json.dumps({
                "artifact_id": "btc-note-1",
                "artifact_type": "research_memo",
                "universe": "public_crypto",
                "title": "BTC Note",
                "markdown": "# BTC Note\n\n[inference] Trend work remains research-only.",
                "created_by": "instrument-analyst",
            }),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["artifact_id"] == "btc-note-1"
        assert response.json()["file_sot"] is True
        assert client.get("/api/research/artifacts/btc-note-1").json()["universe"] == "public_crypto"
        search_response = client.post(
            "/api/research/search",
            data=json.dumps({"query": "trend", "limit": 5}),
            content_type="application/json",
        )
        assert search_response.status_code == 200
        assert any(item["artifact_id"] == "btc-note-1" for item in search_response.json()["artifacts"])
    finally:
        if previous_root is None:
            os.environ.pop("TRADINGCODEX_WORKSPACE_ROOT", None)
        else:
            os.environ["TRADINGCODEX_WORKSPACE_ROOT"] = previous_root

    note_path = workspace / "note.md"
    note_path.write_text("# CLI Note\n\n[factual] Stored through generated workspace CLI.", encoding="utf-8")
    cli_stored = json.loads(run([
        "./tcx",
        "research",
        "create",
        "--id",
        "cli-note-1",
        "--title",
        "CLI Note",
        "--markdown-file",
        "note.md",
        "--symbol",
        "AAPL",
        "--source-as-of",
        "2026-06-02",
    ], workspace).stdout)
    assert cli_stored["db_canonical"] is False
    assert cli_stored["file_sot"] is True
    assert (workspace / cli_stored["export_path"]).exists()
    cli_export = (workspace / cli_stored["export_path"]).read_text(encoding="utf-8")
    assert 'source_as_of: "2026-06-02"' in cli_export
    cli_fetched = json.loads(run(["./tcx", "research", "get", "cli-note-1"], workspace).stdout)
    assert cli_fetched["artifact_id"] == "cli-note-1"
    assert cli_fetched["file_sot"] is True
    assert "updated_at" in cli_fetched
    frontmatter_cli_path = workspace / "frontmatter-cli-note.md"
    frontmatter_cli_path.write_text(
        "---\nartifact_id: frontmatter-cli-note\ntitle: Frontmatter CLI Note\n---\n\n# Frontmatter CLI Body\n",
        encoding="utf-8",
    )
    frontmatter_cli_stored = json.loads(run([
        "./tcx",
        "research",
        "create",
        "--markdown-file",
        "frontmatter-cli-note.md",
        "--created-by",
        "fundamental-analyst",
    ], workspace).stdout)
    assert frontmatter_cli_stored["artifact_id"] == "frontmatter-cli-note"
    assert json.loads(run(["./tcx", "research", "get", "frontmatter-cli-note"], workspace).stdout)["title"] == "Frontmatter CLI Note"

    mcp_cli_stored = json.loads(run([
        "./tcx",
        "mcp",
        "call",
        "create_research_artifact",
        "--principal",
        "fundamental-analyst",
        "--artifact-id",
        "mcp-cli-note-1",
        "--title",
        "MCP CLI Note",
        "--markdown",
        "# MCP CLI Note\n\n[factual] Stored through generated MCP CLI.",
        "--symbol",
        "MSFT",
    ], workspace).stdout)
    assert mcp_cli_stored["db_canonical"] is False
    assert mcp_cli_stored["file_sot"] is True
    assert not McpToolCall.objects.filter(tool_name="create_research_artifact", principal_id="fundamental-analyst", status="ok").exists()
    mcp_cli_snapshot = json.loads(run([
        "./tcx",
        "mcp",
        "call",
        "record_source_snapshot",
        "--principal",
        "fundamental-analyst",
        "--provider",
        "cli-test",
        "--source-category",
        "filing",
        "--as-of",
        "2026-06-12",
        "--artifact-id",
        "mcp-cli-note-1",
        "--payload",
        '{"url":"https://example.test/source"}',
        "--warnings",
        '["stale after 7 days"]',
    ], workspace).stdout)
    assert mcp_cli_snapshot["provider"] == "cli-test"
    assert mcp_cli_snapshot["source_category"] == "filing"
    assert mcp_cli_snapshot["db_canonical"] is False
    assert mcp_cli_snapshot["file_sot"] is True
    assert (workspace / mcp_cli_snapshot["export_path"]).exists()
    assert not McpToolCall.objects.filter(tool_name="record_source_snapshot", principal_id="fundamental-analyst", status="ok").exists()
    mcp_help = run(["./tcx", "mcp", "--help"], workspace).stdout
    assert "create_research_artifact" in mcp_help
    assert "mcp ledger" in mcp_help
    ledger = json.loads(run([
        "./tcx",
        "mcp",
        "ledger",
        "--tool",
        "create_research_artifact",
        "--principal",
        "fundamental-analyst",
        "--status",
        "ok",
    ], workspace).stdout)
    assert ledger["count"] == 0
    assert ledger["calls"] == []
    assert ledger["central_ledger"] is True


def test_central_db_is_shared_across_generated_workspaces(tmp_path: Path) -> None:
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    bootstrap_workspace(workspace_a, force=True)
    bootstrap_workspace(workspace_b, force=True)

    db_a = run(["./tcx", "db", "path"], workspace_a).stdout.strip()
    db_b = run(["./tcx", "db", "path"], workspace_b).stdout.strip()
    assert db_a == db_b
    assert db_a != str((workspace_a / ".tradingcodex" / "state" / "tradingcodex.sqlite3").resolve())
    assert db_b != str((workspace_b / ".tradingcodex" / "state" / "tradingcodex.sqlite3").resolve())
    manifest_a = json.loads((workspace_a / ".tradingcodex" / "workspace.json").read_text(encoding="utf-8"))
    manifest_b = json.loads((workspace_b / ".tradingcodex" / "workspace.json").read_text(encoding="utf-8"))
    assert manifest_a["workspace_id"] != manifest_b["workspace_id"]
    artifact_id = f"central-shared-note-{manifest_a['workspace_id'][-8:]}"
    order_id = f"central-cross-workspace-order-{manifest_a['workspace_id'][-8:]}"

    note = workspace_a / "shared-note.md"
    note.write_text("# Shared Note\n\n[factual] Workspace research is local to workspace A.", encoding="utf-8")
    created = json.loads(run([
        "./tcx",
        "research",
        "create",
        "--id",
        artifact_id,
        "--title",
        "Central Shared Note",
        "--markdown-file",
        "shared-note.md",
        "--symbol",
        "AAPL",
    ], workspace_a).stdout)
    assert created["db_canonical"] is False
    assert created["file_sot"] is True
    assert created["workspace_context"]["path"] == str(workspace_a)

    searched = json.loads(run(["./tcx", "research", "search", "Workspace research"], workspace_b).stdout)
    assert not any(item["artifact_id"] == artifact_id for item in searched["artifacts"])

    conflicting_note = workspace_b / "shared-note-conflict.md"
    conflicting_note.write_text("# Shared Note\n\n[factual] Same artifact id in workspace B is a separate file-native artifact.", encoding="utf-8")
    duplicate = json.loads(run([
        "./tcx",
        "research",
        "create",
        "--id",
        artifact_id,
        "--title",
        "Central Shared Note Conflict",
        "--markdown-file",
        "shared-note-conflict.md",
    ], workspace_b).stdout)
    assert duplicate["artifact_id"] == artifact_id
    assert duplicate["workspace_context"]["path"] == str(workspace_b)
    assert duplicate["file_sot"] is True

    appended_note = workspace_b / "shared-note-v2.md"
    appended_note.write_text("# Shared Note v2\n\n[factual] Explicit version append from workspace B.", encoding="utf-8")
    appended = json.loads(run(["./tcx", "research", "append", artifact_id, "--markdown-file", "shared-note-v2.md"], workspace_b).stdout)
    assert appended["version"] == 2
    assert appended["workspace_context"]["path"] == str(workspace_b)

    order = {
        "id": order_id,
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 1,
        "limit_price": 1000,
        "currency": "KRW",
        "broker": "paper-trading",
        "estimated_notional_krw": 1000,
        "created_by": "portfolio-manager",
        "created_at": "2026-01-01T00:00:00Z",
    }
    order_path = workspace_a / "trading" / "orders" / "draft" / f"{order_id}.order_intent.json"
    order_path.write_text(json.dumps(order), encoding="utf-8")
    assert json.loads(run(["./tcx", "approve", str(order_path.relative_to(workspace_a)), "--approved-by", "risk-manager"], workspace_a).stdout)["status"] == "approved"
    conflicting_order = {**order, "quantity": 2}
    conflicting_order_path = workspace_b / "trading" / "orders" / "draft" / "central-cross-workspace-order-conflict.order_intent.json"
    conflicting_order_path.write_text(json.dumps(conflicting_order), encoding="utf-8")
    order_conflict = json.loads(run(["./tcx", "validate", "order", str(conflicting_order_path.relative_to(workspace_b))], workspace_b, expect_ok=False).stdout)
    assert "order_intent.id already exists with a different payload" in "\n".join(order_conflict["reasons"])
    executed = json.loads(run(["./tcx", "mcp", "call", "submit_approved_order", "--order-intent-id", order["id"]], workspace_b).stdout)
    assert executed["status"] == "accepted"
    assert executed["workspace_context"]["path"] == str(workspace_b)

    portfolio_a = json.loads(run(["./tcx", "mcp", "call", "get_portfolio_snapshot"], workspace_a).stdout)
    portfolio_b = json.loads(run(["./tcx", "mcp", "call", "get_portfolio_snapshot"], workspace_b).stdout)
    assert portfolio_a["positions"]["AAPL"]["quantity"] >= 1
    assert portfolio_a["positions"] == portfolio_b["positions"]

    ledger_b = json.loads(run(["./tcx", "mcp", "ledger", "--tool", "submit_approved_order", "--status", "ok"], workspace_b).stdout)
    assert ledger_b["central_ledger"] is True
    assert any(call["workspace_context"]["path"] == str(workspace_b) for call in ledger_b["calls"])


def test_django_project_check() -> None:
    result = run([sys.executable, "manage.py", "check"], ROOT)
    assert "System check identified no issues" in result.stdout
