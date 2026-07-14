from __future__ import annotations

import json
from pathlib import Path

from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application.build_gateway import BUILD_PROTECTED_MCP_TOOLS
from tradingcodex_service.application.components import get_harness_component
from tradingcodex_service.application.customization import discover_codex_mcp_servers


ROOT = Path(__file__).resolve().parents[1]


def test_build_turn_maintenance_map_covers_enforcement_and_protected_tools() -> None:
    component = get_harness_component("build-turn-authorization")

    assert component is not None
    assert {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PermissionRequest",
        "Stop",
    }.issubset(component["surfaces"]["hooks"])
    assert BUILD_PROTECTED_MCP_TOOLS.issubset(component["surfaces"]["mcp_tools"])
    assert "render_broker_connector_scaffold" in component["surfaces"]["mcp_tools"]
    assert "connect_broker_connector" not in component["surfaces"]["mcp_tools"]
    assert "scaffold_broker_connector" not in component["surfaces"]["mcp_tools"]
    assert "build-hook" in component["surfaces"]["tests"]


def test_repo_skills_module_declares_build_turn_authorization() -> None:
    manifest = json.loads(
        (ROOT / "workspace_templates/modules/repo-skills/module.json").read_text(encoding="utf-8")
    )

    assert "skill.build.turn_authorization" in manifest["provides"]["capabilities"]


def test_mcp_module_declares_render_and_db_only_connector_capabilities() -> None:
    manifest = json.loads(
        (ROOT / "workspace_templates/modules/tradingcodex-mcp/module.json").read_text(encoding="utf-8")
    )
    capabilities = set(manifest["provides"]["capabilities"])

    assert {
        "mcp.tradingcodex.render_broker_connector_scaffold",
        "mcp.tradingcodex.register_broker_connector",
        "mcp.tradingcodex.validate_broker_connector_build",
        "mcp.tradingcodex.record_broker_mapping_review",
    }.issubset(capabilities)


def test_generated_root_mcp_exposes_render_not_service_side_scaffold_writes() -> None:
    config = (
        ROOT / "workspace_templates/modules/codex-base/files/.codex/config.toml"
    ).read_text(encoding="utf-8")

    assert '"render_broker_connector_scaffold"' in config
    assert '"connect_broker_connector"' not in config
    assert '"scaffold_broker_connector"' not in config


def test_public_codex_mcp_discovery_omits_launch_values(tmp_path: Path) -> None:
    bootstrap_workspace(tmp_path)
    config = tmp_path / ".codex/config.toml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + "\n"
        """
[mcp_servers.private]
command = "/private/bin/server"
args = ["--token", "launch-secret"]
url = "https://user:password@example.invalid/mcp?token=secret"
env = { PRIVATE_TOKEN = "ignored" }
""".strip()
        + "\n",
        encoding="utf-8",
    )

    public = discover_codex_mcp_servers(tmp_path, include_global=False)
    record = public["servers"][0]
    serialized = json.dumps(record, sort_keys=True)
    assert record["has_command"] is True
    assert record["arg_count"] == 2
    assert record["has_url"] is True
    assert "command" not in record
    assert "args" not in record
    assert "url" not in record
    assert "/private/bin/server" not in serialized
    assert "launch-secret" not in serialized
    assert "password" not in serialized

    operator_view = discover_codex_mcp_servers(
        tmp_path,
        include_global=False,
        include_launch_details=True,
    )
    assert operator_view["servers"][0]["command"] == "/private/bin/server"
    assert operator_view["servers"][0]["args"] == ["--token", "launch-secret"]
