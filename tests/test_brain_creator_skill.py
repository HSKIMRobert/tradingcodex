from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml

from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application.agents import EXPECTED_SUBAGENTS, build_projection_state
from tradingcodex_service.application.workbench import skill_catalog


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = (
    ROOT
    / "workspace_templates/modules/repo-skills/files/.agents/skills/tcx-brain-create"
)
HEAD_MANAGER_PROMPT = (
    ROOT
    / "workspace_templates/modules/codex-base/files/.codex/prompts/base_instructions/head-manager.md"
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_brain_creator_content_keeps_authoring_private_and_separate() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL_ROOT / "references/bundle-contract.md").read_text(encoding="utf-8")
    metadata = yaml.safe_load((SKILL_ROOT / "agents/openai.yaml").read_text(encoding="utf-8"))
    head_manager = HEAD_MANAGER_PROMPT.read_text(encoding="utf-8")
    flat_skill = _flat(skill)

    assert "[bundle-contract.md](references/bundle-contract.md)" in skill
    assert "explicit user request" in flat_skill
    assert "exact physical first line `$tcx-build`" in flat_skill
    assert "does not elevate Codex's actual filesystem permission" in flat_skill
    assert "select the exact Decision Memory episodes" in flat_skill
    assert "Require counterexamples and scope limits" in flat_skill
    assert "Do not copy private cases" in flat_skill
    assert "investment-brains/<investment-brain-id>" in skill
    assert ".tradingcodex/investment-brains/packages" in skill
    assert "Never edit" in flat_skill and "third-party managed package" in flat_skill
    assert "Do not install, update, activate" in flat_skill
    assert "Do not stage, commit, configure a remote, push, publish, or open a pull request" in flat_skill
    assert "investment-brains validate" in flat_skill and "--local <source-directory>" in flat_skill

    assert '"format": "tradingcodex.investment-brain"' in reference
    assert "allow_implicit_invocation: false" in reference
    assert "No install, activation, Git, or publication action occurred" in reference
    assert metadata["policy"]["allow_implicit_invocation"] is True
    assert metadata["interface"]["default_prompt"].startswith("$tcx-build\n")
    assert "$tcx-brain-create" in metadata["interface"]["default_prompt"]
    assert "$tcx-brain-create" in head_manager
    assert "exact current\n`$tcx-build` root turn" in head_manager


def test_brain_creator_projects_only_to_head_manager(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_workspace(workspace)

    state = build_projection_state(workspace)
    skill = state["skills"]["tcx-brain-create"]
    assert skill["owner_roles"] == ["head-manager"]
    assert skill["scope"] == "mainagent"
    assert skill["user_visible"] is True
    assert skill["implicit_invocation"] is True
    assert "tcx-brain-create" in state["agents"]["head-manager"]["effective_skills"]
    assert "tcx-brain-create" in state["agents"]["head-manager"]["projected_skills"]

    root_config = tomllib.loads((workspace / ".codex/config.toml").read_text(encoding="utf-8"))
    root_paths = {item["path"] for item in root_config["skills"]["config"]}
    assert "../.agents/skills/tcx-brain-create/SKILL.md" in root_paths
    for role in EXPECTED_SUBAGENTS:
        assert "tcx-brain-create" not in state["agents"][role]["effective_skills"]
        assert "tcx-brain-create" not in (
            workspace / f".codex/agents/{role}.toml"
        ).read_text(encoding="utf-8")

    generated_skill = workspace / ".agents/skills/tcx-brain-create"
    assert (generated_skill / "SKILL.md").is_file()
    assert (generated_skill / "agents/openai.yaml").is_file()
    assert (generated_skill / "references/bundle-contract.md").is_file()

    catalog = {item["id"]: item for item in skill_catalog(workspace)}
    assert catalog["tcx-brain-create"]["startable"] is False
    module = json.loads((ROOT / "workspace_templates/modules/repo-skills/module.json").read_text())
    assert "skill.brain_creator" in module["provides"]["capabilities"]
