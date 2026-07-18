from __future__ import annotations

import tomllib
from pathlib import Path

from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application.agents import AGENT_SPECS, RESEARCH_ROLES, SKILL_SPECS
from tradingcodex_service.application.data_sources import enable_openbb
from tradingcodex_service.mcp_runtime import TOOL_REGISTRY


def test_openbb_is_a_direct_optional_evidence_role_projection(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    bootstrap_workspace(root)

    assert "tcx-openbb" not in SKILL_SPECS
    assert "record_external_data_result" not in TOOL_REGISTRY
    assert "fetch_official_source_data" not in TOOL_REGISTRY
    for role in RESEARCH_ROLES:
        assert "tcx-openbb" not in AGENT_SPECS[role].builtin_skills
        config = tomllib.loads((root / f".codex/agents/{role}.toml").read_text(encoding="utf-8"))
        openbb = config["mcp_servers"]["openbb"]
        assert openbb["command"] == "uvx"
        assert openbb["args"] == [
            "--from", "openbb-mcp-server", "--with", "openbb", "openbb-mcp",
            "--transport", "stdio", "--default-categories", "admin",
        ]
        assert openbb["enabled"] is False
        assert openbb["required"] is False
        assert openbb["env_vars"] == []

    for path in (root / ".codex/agents").glob("*.toml"):
        if path.stem in RESEARCH_ROLES:
            continue
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        assert "openbb" not in config.get("mcp_servers", {})


def test_openbb_enable_projects_env_names_only(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    bootstrap_workspace(root)
    enable_openbb(root, ["FMP_API_KEY"])
    bootstrap_workspace(root, update=True)

    config = tomllib.loads((root / ".codex/agents/fundamental-analyst.toml").read_text(encoding="utf-8"))
    assert config["mcp_servers"]["openbb"]["enabled"] is True
    assert config["mcp_servers"]["openbb"]["env_vars"] == ["FMP_API_KEY"]
