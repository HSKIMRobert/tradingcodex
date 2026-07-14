from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from apps.mcp.services import (
    approve_external_mcp_permission_request,
    check_external_mcp_connection,
    deny_external_mcp_permission_request,
    discover_external_mcp_connection,
    register_external_mcp_connection,
    review_external_mcp_tool,
)
from tradingcodex_cli.commands.mcp import mcp
from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application.brokers import (
    _create_external_mcp_broker_connection_from_service,
    create_external_mcp_broker_connection,
)
from tradingcodex_service.application.customization import (
    _import_codex_mcp_server_from_service,
    import_codex_mcp_server,
)
from tradingcodex_service.application.operator_authority import (
    EXTERNAL_MCP_BROKER_CONNECT,
    EXTERNAL_MCP_IMPORT_CODEX,
    EXTERNAL_MCP_PERMISSION_APPROVE,
    EXTERNAL_MCP_PERMISSION_DENY,
    _issue_operator_authority,
    consume_operator_authority,
    external_mcp_broker_connection_resource,
    external_mcp_codex_import_resource,
    external_mcp_operator_resource,
    external_mcp_permission_resource,
)
from tradingcodex_service.application.runtime import ensure_runtime_database
from tradingcodex_service.mcp_runtime import call_mcp_tool, handle_mcp_rpc


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / f"mcp-operator-{uuid.uuid4().hex[:10]}"
    bootstrap_workspace(root)
    ensure_runtime_database(root)
    return root


def issue_test_external_mcp_authority(
    workspace: Path,
    action: str,
    arguments: dict,
):
    """Test-only stand-in for a completed interactive CLI confirmation."""

    return _issue_operator_authority(
        workspace,
        action=action,
        resource=external_mcp_operator_resource(action, arguments),
    )


def issue_test_permission_authority(
    workspace: Path,
    action: str,
    request_id: object,
    reason: str = "",
):
    """Test-only stand-in for a completed interactive CLI confirmation."""

    return _issue_operator_authority(
        workspace,
        action=action,
        resource=external_mcp_permission_resource(action, request_id, reason),
    )


def issue_test_codex_import_authority(workspace: Path, name: str, source: str = "workspace"):
    """Test-only stand-in for a completed interactive CLI confirmation."""

    return _issue_operator_authority(
        workspace,
        action=EXTERNAL_MCP_IMPORT_CODEX,
        resource=external_mcp_codex_import_resource(name, source),
    )


def issue_test_broker_import_authority(workspace: Path, arguments: dict):
    """Test-only stand-in for a completed interactive CLI confirmation."""

    return _issue_operator_authority(
        workspace,
        action=EXTERNAL_MCP_BROKER_CONNECT,
        resource=external_mcp_broker_connection_resource(**arguments),
    )


def create_permission_request(workspace: Path, suffix: str):
    from apps.mcp.models import McpExternalPermissionRequest, McpExternalTool, McpRouter

    router = McpRouter.objects.create(name=f"operator-{suffix}")
    tool = McpExternalTool.objects.create(router=router, external_name="quotes")
    return McpExternalPermissionRequest.objects.create(
        external_tool=tool,
        router_name=router.name,
        external_name=tool.external_name,
        principal_id="head-manager",
        request_hash="a" * 64,
        expires_at=timezone.now() + timedelta(hours=1),
    )


def test_external_mcp_tools_require_one_exact_operator_authority(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tradingcodex_service import mcp_runtime

    action = "register_external_mcp_connection"
    arguments = {"name": "operator-bound", "enabled": False}
    raw_calls = 0

    def fake_raw_call(*_args, **_kwargs):
        nonlocal raw_calls
        raw_calls += 1
        return {"status": "registered"}

    monkeypatch.setattr(mcp_runtime, "raw_call_tool", fake_raw_call)

    with pytest.raises(PermissionError, match="interactive operator authority"):
        call_mcp_tool(
            workspace,
            action,
            arguments,
            transport_principal="head-manager",
        )
    assert raw_calls == 0

    response = handle_mcp_rpc(
        workspace,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": action, "arguments": arguments},
        },
        transport_principal="head-manager",
    )
    assert response is not None
    assert "interactive operator authority" in response["error"]["message"]
    assert raw_calls == 0

    authority = issue_test_external_mcp_authority(workspace, action, arguments)
    with pytest.raises(PermissionError, match="does not match"):
        call_mcp_tool(
            workspace,
            action,
            {**arguments, "label": "changed-after-confirmation"},
            transport_principal="head-manager",
            operator_authority=authority,
        )
    assert raw_calls == 0

    result = call_mcp_tool(
        workspace,
        action,
        arguments,
        transport_principal="head-manager",
        operator_authority=authority,
    )
    assert result["status"] == "registered"
    assert raw_calls == 1
    with pytest.raises(PermissionError, match="already used"):
        call_mcp_tool(
            workspace,
            action,
            arguments,
            transport_principal="head-manager",
            operator_authority=authority,
        )
    assert raw_calls == 1

    wrong_action = "discover_external_mcp_connection"
    wrong_action_authority = issue_test_external_mcp_authority(
        workspace,
        wrong_action,
        arguments,
    )
    with pytest.raises(PermissionError, match="does not match"):
        call_mcp_tool(
            workspace,
            action,
            arguments,
            transport_principal="head-manager",
            operator_authority=wrong_action_authority,
        )
    assert raw_calls == 1


def test_generic_cli_cannot_supply_external_mcp_operator_authority(workspace: Path) -> None:
    with pytest.raises(PermissionError, match="interactive operator authority"):
        mcp(
            workspace,
            [
                "call",
                "register_external_mcp_connection",
                "--principal",
                "head-manager",
                json.dumps({"name": "generic-cli-denied"}),
            ],
        )


def test_external_mcp_canonical_service_requires_and_consumes_authority(workspace: Path) -> None:
    action = "register_external_mcp_connection"
    arguments = {"name": "service-bound", "label": "Reviewed service"}

    with pytest.raises(PermissionError, match="interactive operator authority"):
        register_external_mcp_connection(workspace, arguments)
    with pytest.raises(ValueError, match="do not accept caller principal_id"):
        register_external_mcp_connection(
            workspace,
            {**arguments, "principal_id": "forged-head-manager"},
        )

    authority = issue_test_external_mcp_authority(workspace, action, arguments)
    with pytest.raises(PermissionError, match="does not match"):
        register_external_mcp_connection(
            workspace,
            {**arguments, "label": "changed"},
            operator_authority=authority,
        )
    registered = register_external_mcp_connection(
        workspace,
        arguments,
        operator_authority=authority,
    )
    assert registered["status"] == "registered"
    with pytest.raises(PermissionError, match="already used"):
        register_external_mcp_connection(
            workspace,
            arguments,
            operator_authority=authority,
        )

    mcp_arguments = {"name": "mcp-two-stage", "enabled": False}
    mcp_authority = issue_test_external_mcp_authority(workspace, action, mcp_arguments)
    through_mcp = call_mcp_tool(
        workspace,
        action,
        mcp_arguments,
        transport_principal="head-manager",
        operator_authority=mcp_authority,
    )
    assert through_mcp["status"] == "registered"
    with pytest.raises(PermissionError, match="already used"):
        call_mcp_tool(
            workspace,
            action,
            mcp_arguments,
            transport_principal="head-manager",
            operator_authority=mcp_authority,
        )


@pytest.mark.parametrize(
    ("service", "arguments"),
    (
        (check_external_mcp_connection, {"name": "missing"}),
        (discover_external_mcp_connection, {"name": "missing"}),
        (review_external_mcp_tool, {"tool_id": 1}),
    ),
)
def test_each_external_mcp_mutation_service_rejects_plain_direct_calls(
    workspace: Path,
    service,
    arguments: dict,
) -> None:
    with pytest.raises(PermissionError, match="interactive operator authority"):
        service(workspace, arguments)


def test_permission_decisions_require_bound_authority_and_ignore_claimed_identity(
    workspace: Path,
) -> None:
    approval_request = create_permission_request(workspace, "approve")
    approval_args = {"request_id": str(approval_request.pk), "reason": "reviewed evidence"}

    with pytest.raises(PermissionError, match="interactive operator authority"):
        approve_external_mcp_permission_request(workspace, approval_args)
    with pytest.raises(ValueError, match="does not allow fields: principal_id"):
        approve_external_mcp_permission_request(
            workspace,
            {**approval_args, "principal_id": "forged-user"},
        )

    authority = issue_test_permission_authority(
        workspace,
        EXTERNAL_MCP_PERMISSION_APPROVE,
        approval_request.pk,
        approval_args["reason"],
    )
    with pytest.raises(PermissionError, match="does not match"):
        approve_external_mcp_permission_request(
            workspace,
            {**approval_args, "reason": "changed-after-confirmation"},
            operator_authority=authority,
        )
    approved = approve_external_mcp_permission_request(
        workspace,
        approval_args,
        operator_authority=authority,
    )
    assert approved["status"] == "approved"
    assert approved["request"]["decided_by"] == "local-operator"
    with pytest.raises(PermissionError, match="already used"):
        approve_external_mcp_permission_request(
            workspace,
            approval_args,
            operator_authority=authority,
        )

    denial_request = create_permission_request(workspace, "deny")
    denial_args = {"request_id": str(denial_request.pk), "reason": "outside scope"}
    wrong_action_authority = issue_test_permission_authority(
        workspace,
        EXTERNAL_MCP_PERMISSION_APPROVE,
        denial_request.pk,
        denial_args["reason"],
    )
    with pytest.raises(PermissionError, match="does not match"):
        deny_external_mcp_permission_request(
            workspace,
            denial_args,
            operator_authority=wrong_action_authority,
        )
    denied = deny_external_mcp_permission_request(
        workspace,
        denial_args,
        operator_authority=issue_test_permission_authority(
            workspace,
            EXTERNAL_MCP_PERMISSION_DENY,
            denial_request.pk,
            denial_args["reason"],
        ),
    )
    assert denied["status"] == "denied"
    assert denied["request"]["decided_by"] == "local-operator"


def test_codex_mcp_import_requires_exact_authority_and_seals_internal_stage(
    workspace: Path,
) -> None:
    from apps.mcp.models import McpRouter

    name = f"codex-import-{uuid.uuid4().hex[:8]}"
    config_path = workspace / ".codex" / "config.toml"
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f'\n[mcp_servers.{name}]\ncommand = "uvx"\nargs = ["example-server"]\nenabled = false\n'
        )

    with pytest.raises(PermissionError, match="interactive operator authority"):
        import_codex_mcp_server(workspace, name=name, source="workspace")
    assert not McpRouter.objects.filter(name=name).exists()

    authority = issue_test_codex_import_authority(workspace, name)
    with pytest.raises(PermissionError, match="sealed operator service authority"):
        _import_codex_mcp_server_from_service(
            workspace,
            name=name,
            source="workspace",
            operator_service_authority=authority,  # type: ignore[arg-type]
        )
    with pytest.raises(PermissionError, match="does not match"):
        import_codex_mcp_server(
            workspace,
            name=name,
            source="global",
            operator_authority=authority,
        )

    result = import_codex_mcp_server(
        workspace,
        name=name,
        source="workspace",
        operator_authority=authority,
    )
    assert result["status"] == "imported"
    assert result["source"] == "workspace"
    router = McpRouter.objects.get(name=name)
    assert router.enabled is False
    assert router.command == "uvx"
    with pytest.raises(PermissionError, match="already used"):
        import_codex_mcp_server(
            workspace,
            name=name,
            source="workspace",
            operator_authority=authority,
        )


def test_external_mcp_import_cli_confirms_before_issuing_and_mutating(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tradingcodex_cli.commands import mcp as mcp_command

    authority = object()
    events: list[object] = []
    monkeypatch.setattr(
        mcp_command,
        "_require_operator_confirmation",
        lambda action, subject: events.append(("confirm", action, subject)),
    )
    monkeypatch.setattr(
        mcp_command,
        "_issue_operator_authority",
        lambda root, *, action, resource: events.append(("issue", action, resource)) or authority,
    )
    monkeypatch.setattr(
        mcp_command,
        "import_codex_mcp_server",
        lambda root, *, name, source, operator_authority: events.append(
            ("import", name, source, operator_authority)
        )
        or {"status": "imported", "name": name},
    )

    mcp_command.mcp_external(
        workspace,
        ["import-codex", "--source", "global", "--name", "operator-demo"],
    )

    assert json.loads(capsys.readouterr().out)["status"] == "imported"
    assert events == [
        ("confirm", "import-codex", "global:operator-demo"),
        (
            "issue",
            EXTERNAL_MCP_IMPORT_CODEX,
            external_mcp_codex_import_resource("operator-demo", "global"),
        ),
        ("import", "operator-demo", "global", authority),
    ]


def test_external_mcp_broker_import_uses_exact_authority_and_service_stage(
    workspace: Path,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    arguments = {
        "broker_id": f"operator-broker-{suffix}",
        "display_name": "Operator Broker",
        "router_name": f"operator-router-{suffix}",
        "discovery_payload": {
            "tools": [
                {
                    "name": "get_positions",
                    "description": "Read positions",
                    "inputSchema": {"type": "object"},
                }
            ]
        },
        "credential_ref": "",
    }
    with pytest.raises(PermissionError, match="interactive operator authority"):
        create_external_mcp_broker_connection(workspace, **arguments)

    authority = issue_test_broker_import_authority(workspace, arguments)
    with pytest.raises(PermissionError, match="does not match"):
        create_external_mcp_broker_connection(
            workspace,
            **{**arguments, "display_name": "Changed after confirmation"},
            operator_authority=authority,
        )
    result = create_external_mcp_broker_connection(
        workspace,
        **arguments,
        operator_authority=authority,
    )
    assert result["status"] == "read_only"
    assert result["imported"]["imported"] == 1
    with pytest.raises(PermissionError, match="already used"):
        create_external_mcp_broker_connection(
            workspace,
            **arguments,
            operator_authority=authority,
        )

    internal_arguments = {
        **arguments,
        "broker_id": f"service-broker-{suffix}",
        "router_name": f"service-router-{suffix}",
    }
    internal_authority = issue_test_broker_import_authority(workspace, internal_arguments)
    with pytest.raises(PermissionError, match="sealed operator service authority"):
        _create_external_mcp_broker_connection_from_service(
            workspace,
            **internal_arguments,
            operator_service_authority=internal_authority,  # type: ignore[arg-type]
        )
    service_authority = consume_operator_authority(
        internal_authority,
        workspace,
        action=EXTERNAL_MCP_BROKER_CONNECT,
        resource=external_mcp_broker_connection_resource(**internal_arguments),
    )
    internal_result = _create_external_mcp_broker_connection_from_service(
        workspace,
        **internal_arguments,
        operator_service_authority=service_authority,
    )
    assert internal_result["status"] == "read_only"
    with pytest.raises(PermissionError, match="already used"):
        _create_external_mcp_broker_connection_from_service(
            workspace,
            **internal_arguments,
            operator_service_authority=service_authority,
        )
