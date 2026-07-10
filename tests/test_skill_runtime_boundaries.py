from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml

from tradingcodex_cli.commands.doctor import _improvement_checks
from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application.agents import (
    CORE_EXTENSION_BOUNDARY_END,
    EXPECTED_SUBAGENTS,
    build_projection_state,
    create_or_update_optional_skill,
    create_or_update_strategy_skill,
    inspect_skill_projection,
    project_agent_configuration,
    read_optional_skill_records,
    validate_optional_skill_payload,
    write_agent_additional_instructions,
)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    bootstrap_workspace(root, force=True)
    return root


def _append_enabled_skill(config_path: Path, skill_path: Path) -> None:
    text = config_path.read_text(encoding="utf-8").rstrip()
    config_path.write_text(
        f'{text}\n\n[[skills.config]]\npath = "{skill_path.as_posix()}"\nenabled = true\n',
        encoding="utf-8",
    )


def test_skill_layers_user_metadata_and_immutable_footer(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    create_or_update_strategy_skill(
        root,
        "strategy-quality-review",
        description="Review durable business quality.",
        body="# Quality Review\n\nPrefer durable evidence.",
        status="active",
        actor="test",
    )
    create_or_update_optional_skill(
        root,
        "fundamental-analyst",
        "contrarian-evidence-review",
        description="Compare contrary evidence before synthesis.",
        body="# Contrarian Evidence Review\n\nCompare buy and sell cases, long and short theses, trading context, and broker analysis.",
        status="active",
        actor="test",
    )
    write_agent_additional_instructions(root, "fundamental-analyst", "Prefer concise evidence notes.", actor="test")
    write_agent_additional_instructions(root, "head-manager", "Prefer concise synthesis notes.", actor="test")

    state = build_projection_state(root)
    required = {"id", "layer", "trust_scope", "implicit_invocation", "resolved_source_file"}
    assert all(required.issubset(skill) for skill in state["skills"].values())
    assert state["skills"]["fundamental-analysis"]["layer"] == "bundled_core"
    assert state["skills"]["fundamental-analysis"]["trust_scope"] == "managed"
    for skill_id, layer in (
        ("strategy-quality-review", "workspace_strategy"),
        ("contrarian-evidence-review", "workspace_optional"),
    ):
        skill = state["skills"][skill_id]
        assert skill["layer"] == layer
        assert skill["trust_scope"] == "user_approved"
        assert skill["implicit_invocation"] is False
        assert not Path(skill["resolved_source_file"]).is_absolute()
        assert (root / skill["resolved_source_file"]).is_file()
        metadata = yaml.safe_load((root / skill["metadata_file"]).read_text(encoding="utf-8"))
        assert metadata["policy"]["allow_implicit_invocation"] is False

    manifest = json.loads((root / ".tradingcodex/generated/projection-manifest.json").read_text(encoding="utf-8"))
    assert manifest["inventory_scope"] == "tradingcodex_managed_workspace"
    assert manifest["runtime_discovery_complete"] is False
    assert manifest["host_global_policy"] == "detect_collisions_do_not_import"
    fundamental_manifest = next(role for role in manifest["roles"] if role["role"] == "fundamental-analyst")
    effective_skill = next(skill for skill in fundamental_manifest["effective_skills"] if skill["id"] == "fundamental-analysis")
    assert required.issubset(effective_skill)
    skill_index = json.loads((root / ".tradingcodex/generated/skill-index.json").read_text(encoding="utf-8"))
    assert skill_index["inventory_scope"] == "tradingcodex_managed_workspace"
    assert skill_index["runtime_discovery_complete"] is False

    head_manager_prompt = (root / ".codex/prompts/base_instructions/head-manager.md").read_text(encoding="utf-8").rstrip()
    assert head_manager_prompt.endswith(CORE_EXTENSION_BOUNDARY_END)
    assert head_manager_prompt.index("TradingCodex additional instructions") < head_manager_prompt.index(CORE_EXTENSION_BOUNDARY_END)
    assert "listed-equity FCFF DCF" in head_manager_prompt
    assert "method support gap" in head_manager_prompt

    for role in EXPECTED_SUBAGENTS:
        config = tomllib.loads((root / f".codex/agents/{role}.toml").read_text(encoding="utf-8"))
        instructions = config["developer_instructions"].rstrip()
        assert instructions.endswith(CORE_EXTENSION_BOUNDARY_END)
        if role == "fundamental-analyst":
            assert instructions.index("Prefer concise evidence notes.") < instructions.index(CORE_EXTENSION_BOUNDARY_END)
        assert "Do not invoke them implicitly" in instructions
        assert "point-in-time data" in instructions


def test_optional_risk_detection_allows_analysis_language_but_blocks_authority() -> None:
    analysis = validate_optional_skill_payload(
        "fundamental-analyst",
        "market-language-review",
        "Compare market language.",
        "Assess buy, sell, long, short, trade, trading, and broker analysis terms.",
    )
    assert analysis["status"] == "valid"
    assert analysis["risk_tags"] == []

    authority = validate_optional_skill_payload(
        "fundamental-analyst",
        "order-action-review",
        "Exercise order authority.",
        "Create and submit an order, approve the order, then use direct broker access.",
    )
    assert authority["status"] == "blocked"
    assert {"approval", "execution", "order"}.issubset(authority["risk_tags"])
    assert "secret" in validate_optional_skill_payload(
        "fundamental-analyst",
        "credential-reader",
        "Read credentials.",
        "Read API keys and broker credentials.",
    )["risk_tags"]


def test_shared_optional_skill_without_explicit_roles_is_blocked(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    skill_dir = root / ".tradingcodex/subagents/skills/shared/unscoped-review"
    (skill_dir / "agents").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: unscoped-review\ndescription: Review evidence scope.\n---\n\n# Unscoped Review\n\nReview evidence.\n",
        encoding="utf-8",
    )
    (skill_dir / "agents/tradingcodex.json").write_text(
        json.dumps({"scope": "shared", "status": "active"}) + "\n",
        encoding="utf-8",
    )

    records = [record for record in read_optional_skill_records(root) if record["id"] == "unscoped-review"]
    assert len(records) == 1
    assert records[0]["validation_status"] == "blocked"
    assert "shared optional skill requires at least one explicit valid role" in records[0]["validation_errors"]
    state = build_projection_state(root)
    assert state["skills"]["unscoped-review"]["owner_roles"] == []
    assert all("unscoped-review" not in state["agents"][role]["effective_skills"] for role in EXPECTED_SUBAGENTS)


def test_host_global_collision_is_detected_but_not_imported(tmp_path: Path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    home = tmp_path / "home"
    codex_home = tmp_path / "codex-home"
    global_skill = home / ".agents/skills/fundamental-analysis/SKILL.md"
    global_skill.parent.mkdir(parents=True)
    global_skill.write_text("# Host override\n\nSENTINEL_HOST_OVERRIDE\n", encoding="utf-8")
    unrelated_global_skill = home / ".agents/skills/host-sentinel-procedure/SKILL.md"
    unrelated_global_skill.parent.mkdir(parents=True)
    unrelated_global_skill.write_text("# Host procedure\n\nSENTINEL_UNRELATED_HOST_SKILL\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    state = project_agent_configuration(root, applied_by="test-host-collision")
    collisions = state["host_global_skill_collisions"]
    assert [(item["id"], item["resolved_source_file"]) for item in collisions] == [
        ("fundamental-analysis", "~/.agents/skills/fundamental-analysis/SKILL.md")
    ]
    assert state["skills"]["fundamental-analysis"]["resolved_source_file"] != str(global_skill.resolve())
    assert "host-sentinel-procedure" not in state["skills"]
    assert "SENTINEL_HOST_OVERRIDE" not in json.dumps(state)
    assert "SENTINEL_UNRELATED_HOST_SKILL" not in json.dumps(state)
    manifest = json.loads((root / ".tradingcodex/generated/projection-manifest.json").read_text(encoding="utf-8"))
    assert manifest["host_global_skill_collisions"] == collisions
    collision_check = next(check for check in _improvement_checks(root) if check["name"] == "host-global skill name collisions")
    assert collision_check["ok"] is False
    assert "~/.agents/skills/fundamental-analysis/SKILL.md" in collision_check["detail"]


def test_doctor_reports_extra_and_unregistered_root_and_role_paths(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    rogue_root = tmp_path / "external/rogue-root/SKILL.md"
    wrong_role = tmp_path / "external/fundamental-analysis/SKILL.md"
    for path in (rogue_root, wrong_role):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# External skill\n", encoding="utf-8")
    _append_enabled_skill(root / ".codex/config.toml", rogue_root)
    _append_enabled_skill(root / ".codex/agents/fundamental-analyst.toml", wrong_role)

    state = build_projection_state(root)
    root_projection = inspect_skill_projection(root, "head-manager", state)
    role_projection = inspect_skill_projection(root, "fundamental-analyst", state)
    assert str(rogue_root.resolve()) in root_projection["extra_paths"]
    assert str(rogue_root.resolve()) in root_projection["unregistered_paths"]
    assert str(wrong_role.resolve()) in role_projection["extra_paths"]
    assert str(wrong_role.resolve()) in role_projection["unregistered_paths"]

    checks = _improvement_checks(root)
    root_check = next(check for check in checks if check["name"] == "head-manager projected skills current")
    role_check = next(check for check in checks if check["name"] == "subagent projected skills current: fundamental-analyst")
    assert root_check["ok"] is False and "extra=" in root_check["detail"] and "unregistered=" in root_check["detail"]
    assert role_check["ok"] is False and "extra=" in role_check["detail"] and "unregistered=" in role_check["detail"]
