from __future__ import annotations

import io
import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from tradingcodex_cli.commands.connectors import connectors
from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application.brokers import (
    _WORKSPACE_PROVIDER_CACHE,
    _WORKSPACE_PROVIDER_SOURCES,
    _remove_workspace_provider_modules,
    approve_workspace_broker_provider_source,
    broker_provider_source_status,
    get_broker_adapter_provider,
    inspect_workspace_broker_provider_source,
    list_broker_adapter_providers,
    revoke_workspace_broker_provider_source,
    scaffold_broker_connector,
)
from tradingcodex_service.application.operator_authority import (
    PROVIDER_SOURCE_APPROVE,
    PROVIDER_SOURCE_REVOKE,
    _issue_operator_authority,
    provider_source_approval_resource,
    provider_source_revocation_resource,
)
from tradingcodex_service.application.runtime import tradingcodex_home, workspace_context_payload
from tradingcodex_service.mcp_runtime import TOOL_REGISTRY


@pytest.fixture(autouse=True)
def restore_workspace_provider_cache():
    previous_cache = dict(_WORKSPACE_PROVIDER_CACHE)
    previous_sources = dict(_WORKSPACE_PROVIDER_SOURCES)
    _WORKSPACE_PROVIDER_CACHE.clear()
    _WORKSPACE_PROVIDER_SOURCES.clear()
    yield
    for source in _WORKSPACE_PROVIDER_SOURCES.values():
        module_prefix = str(source.get("module_prefix") or "")
        if module_prefix:
            _remove_workspace_provider_modules(module_prefix)
    _WORKSPACE_PROVIDER_CACHE.clear()
    _WORKSPACE_PROVIDER_CACHE.update(previous_cache)
    _WORKSPACE_PROVIDER_SOURCES.clear()
    _WORKSPACE_PROVIDER_SOURCES.update(previous_sources)


def make_workspace(tmp_path: Path, name: str = "workspace") -> Path:
    workspace = tmp_path / name
    bootstrap_workspace(workspace)
    return workspace


def write_provider(
    workspace: Path,
    provider_id: str,
    *,
    sentinel: Path | None = None,
    relative_helper: bool = False,
) -> Path:
    provider_dir = workspace / "trading" / "connectors" / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)
    if relative_helper:
        (provider_dir / "helper.py").write_text('DISPLAY_NAME = "Approved snapshot provider"\n', encoding="utf-8")
        display_import = "from .helper import DISPLAY_NAME\n"
        display_name = "DISPLAY_NAME"
    else:
        display_import = ""
        display_name = repr("Approved snapshot provider")
    sentinel_write = ""
    if sentinel is not None:
        sentinel_write = f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
    provider_path = provider_dir / "provider.py"
    provider_path.write_text(
        (
            "from pathlib import Path\n"
            "from tradingcodex_service.application.brokers import BrokerAdapterProvider\n"
            f"{display_import}"
            f"{sentinel_write}"
            "\n"
            "PROVIDER = BrokerAdapterProvider(\n"
            f"    provider_id={provider_id!r},\n"
            f"    display_name={display_name},\n"
            "    execution_posture='broker_validation_only',\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    return provider_path


def issue_test_operator_authority(
    workspace: Path,
    *,
    action: str,
    resource: str,
):
    """Test-only stand-in for the CLI's completed interactive confirmation."""

    return _issue_operator_authority(workspace, action=action, resource=resource)


def approve_exact(workspace: Path, provider_id: str) -> dict:
    inspected = inspect_workspace_broker_provider_source(workspace, provider_id)
    bundle_sha256 = inspected["bundle_sha256"]
    return approve_workspace_broker_provider_source(
        workspace,
        provider_id,
        expected_bundle_sha256=bundle_sha256,
        operator_authority=issue_test_operator_authority(
            workspace,
            action=PROVIDER_SOURCE_APPROVE,
            resource=provider_source_approval_resource(provider_id, bundle_sha256),
        ),
    )


def simulate_service_restart(monkeypatch) -> None:
    from django.utils import timezone as django_timezone

    monkeypatch.setattr(
        "tradingcodex_service.application.brokers._PROVIDER_RUNTIME_STARTED_AT",
        django_timezone.now() + timedelta(days=1),
    )


def test_provider_source_is_inert_until_exact_approval_and_restart(tmp_path: Path, monkeypatch) -> None:
    workspace = make_workspace(tmp_path)
    sentinel = tmp_path / "provider-imported.txt"
    write_provider(workspace, "reviewed", sentinel=sentinel, relative_helper=True)

    listed = list_broker_adapter_providers(workspace)
    assert "reviewed" not in {provider["provider_id"] for provider in listed["providers"]}
    inspected = inspect_workspace_broker_provider_source(workspace, "reviewed")
    assert inspected["approval_status"] == "approval_required"
    assert not sentinel.exists()

    approved = approve_workspace_broker_provider_source(
        workspace,
        "reviewed",
        expected_bundle_sha256=inspected["bundle_sha256"],
        operator_authority=issue_test_operator_authority(
            workspace,
            action=PROVIDER_SOURCE_APPROVE,
            resource=provider_source_approval_resource("reviewed", inspected["bundle_sha256"]),
        ),
    )
    assert approved["service_restart_required"] is True
    assert not sentinel.exists()
    with pytest.raises(PermissionError, match="approved after this process started"):
        get_broker_adapter_provider("reviewed", workspace)
    assert not sentinel.exists()

    simulate_service_restart(monkeypatch)
    provider = get_broker_adapter_provider("reviewed", workspace)
    assert provider is not None
    assert provider.display_name == "Approved snapshot provider"
    assert sentinel.read_text(encoding="utf-8") == "executed"


def test_provider_source_mutations_require_service_operator_authority(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    write_provider(workspace, "guarded")
    inspected = inspect_workspace_broker_provider_source(workspace, "guarded")

    with pytest.raises(PermissionError, match="interactive operator authority"):
        approve_workspace_broker_provider_source(
            workspace,
            "guarded",
            expected_bundle_sha256=inspected["bundle_sha256"],
        )
    with pytest.raises(PermissionError, match="interactive operator authority"):
        revoke_workspace_broker_provider_source(workspace, "guarded")


def test_operator_authority_is_one_shot_and_bound_to_action_workspace_and_resource(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, "workspace-a")
    other_workspace = make_workspace(tmp_path, "workspace-b")
    write_provider(workspace, "bound-authority")
    write_provider(other_workspace, "bound-authority")
    inspected = inspect_workspace_broker_provider_source(workspace, "bound-authority")
    other_inspected = inspect_workspace_broker_provider_source(other_workspace, "bound-authority")

    approval_authority = issue_test_operator_authority(
        workspace,
        action=PROVIDER_SOURCE_APPROVE,
        resource=provider_source_approval_resource("bound-authority", inspected["bundle_sha256"]),
    )
    with pytest.raises(PermissionError, match="does not match"):
        revoke_workspace_broker_provider_source(
            workspace,
            "bound-authority",
            operator_authority=approval_authority,
        )
    with pytest.raises(PermissionError, match="does not match"):
        approve_workspace_broker_provider_source(
            other_workspace,
            "bound-authority",
            expected_bundle_sha256=other_inspected["bundle_sha256"],
            operator_authority=approval_authority,
        )

    approved = approve_workspace_broker_provider_source(
        workspace,
        "bound-authority",
        expected_bundle_sha256=inspected["bundle_sha256"],
        operator_authority=approval_authority,
    )
    assert approved["status"] == "approved"
    with pytest.raises(PermissionError, match="already used"):
        approve_workspace_broker_provider_source(
            workspace,
            "bound-authority",
            expected_bundle_sha256=inspected["bundle_sha256"],
            operator_authority=approval_authority,
        )

    wrong_resource_authority = issue_test_operator_authority(
        workspace,
        action=PROVIDER_SOURCE_APPROVE,
        resource=provider_source_approval_resource("another-provider", inspected["bundle_sha256"]),
    )
    with pytest.raises(PermissionError, match="does not match"):
        approve_workspace_broker_provider_source(
            workspace,
            "bound-authority",
            expected_bundle_sha256=inspected["bundle_sha256"],
            operator_authority=wrong_resource_authority,
        )


def test_approval_rejects_wrong_digest_and_audits_only_review_metadata(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    marker = "source-secret-that-must-not-enter-audit"
    provider_path = write_provider(workspace, "audited")
    provider_path.write_text(provider_path.read_text(encoding="utf-8") + f"# {marker}\n", encoding="utf-8")
    context = workspace_context_payload(workspace)

    from apps.audit.models import AuditEvent
    from apps.integrations.models import BrokerProviderSourceApproval

    with pytest.raises(PermissionError, match="changed after operator review"):
        authority = issue_test_operator_authority(
            workspace,
            action=PROVIDER_SOURCE_APPROVE,
            resource=provider_source_approval_resource("audited", "0" * 64),
        )
        approve_workspace_broker_provider_source(
            workspace,
            "audited",
            expected_bundle_sha256="0" * 64,
            operator_authority=authority,
        )
    assert not BrokerProviderSourceApproval.objects.filter(
        workspace_id=context["workspace_id"],
        workspace_path_hash=context["path_hash"],
        provider_id="audited",
    ).exists()

    approved = approve_exact(workspace, "audited")
    event = AuditEvent.objects.filter(
        action="broker_provider_source.approved",
        resource="audited",
    ).latest("id")
    serialized = json.dumps(event.payload, sort_keys=True)
    assert marker not in serialized
    assert approved["bundle_sha256"] in serialized
    assert approved["source_sha256"] in serialized


def test_approval_and_cache_are_bound_to_workspace_identity_and_path(tmp_path: Path, monkeypatch) -> None:
    workspace_a = make_workspace(tmp_path, "workspace-a")
    write_provider(workspace_a, "bound")
    approve_exact(workspace_a, "bound")
    simulate_service_restart(monkeypatch)
    assert get_broker_adapter_provider("bound", workspace_a) is not None

    workspace_b = tmp_path / "workspace-b"
    shutil.copytree(workspace_a, workspace_b)
    context_a = workspace_context_payload(workspace_a)
    context_b = workspace_context_payload(workspace_b)
    assert context_a["workspace_id"] == context_b["workspace_id"]
    assert context_a["path_hash"] != context_b["path_hash"]

    status_b = broker_provider_source_status("bound", workspace_b)
    assert status_b["approval_status"] == "approval_required"
    with pytest.raises(PermissionError, match="requires explicit operator approval"):
        get_broker_adapter_provider("bound", workspace_b)
    assert len(_WORKSPACE_PROVIDER_CACHE) == 1


def test_snapshot_tamper_is_detected_before_provider_import(tmp_path: Path, monkeypatch) -> None:
    workspace = make_workspace(tmp_path)
    sentinel = tmp_path / "tampered-provider-imported.txt"
    write_provider(workspace, "tamper", sentinel=sentinel)
    approved = approve_exact(workspace, "tamper")
    snapshot_provider = tradingcodex_home() / approved["snapshot_relative_path"] / "provider.py"
    snapshot_provider.chmod(0o644)
    snapshot_provider.write_text(snapshot_provider.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")

    status = broker_provider_source_status("tamper", workspace)
    assert status["approval_status"] == "blocked"
    assert status["drift_status"] == "approved_snapshot_invalid"
    simulate_service_restart(monkeypatch)
    with pytest.raises(PermissionError, match="digest verification failed"):
        get_broker_adapter_provider("tamper", workspace)
    assert not sentinel.exists()


def test_provider_and_scaffold_paths_reject_symlinks(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    provider_dir = workspace / "trading" / "connectors" / "linked"
    provider_dir.mkdir(parents=True, exist_ok=True)
    outside_provider = tmp_path / "outside-provider.py"
    outside_provider.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    try:
        (provider_dir / "provider.py").symlink_to(outside_provider)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")

    status = inspect_workspace_broker_provider_source(workspace, "linked")
    assert status["approval_status"] == "blocked"
    with pytest.raises(ValueError, match="symlink"):
        approve_workspace_broker_provider_source(
            workspace,
            "linked",
            expected_bundle_sha256="0" * 64,
            operator_authority=issue_test_operator_authority(
                workspace,
                action=PROVIDER_SOURCE_APPROVE,
                resource=provider_source_approval_resource("linked", "0" * 64),
            ),
        )

    outside_scaffold = tmp_path / "outside-scaffold"
    outside_scaffold.mkdir()
    (workspace / "trading" / "connectors" / "escape").symlink_to(outside_scaffold, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        scaffold_broker_connector(
            workspace,
            {
                "provider_id": "paper",
                "broker_id": "escape",
                "credential_ref": "env:ESCAPE",
                "principal_id": "local-operator",
            },
        )
    assert list(outside_scaffold.iterdir()) == []


def test_provider_approval_commands_require_tty_and_are_not_mcp_tools(tmp_path: Path, monkeypatch) -> None:
    workspace = make_workspace(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("automated confirmation\n"))

    with pytest.raises(PermissionError, match="interactive operator terminal"):
        connectors(workspace, ["approve-provider", "demo"])
    with pytest.raises(PermissionError, match="interactive operator terminal"):
        connectors(workspace, ["revoke-provider", "demo"])

    assert "approve_workspace_broker_provider_source" not in TOOL_REGISTRY
    assert "revoke_workspace_broker_provider_source" not in TOOL_REGISTRY
    assert "approve_broker_provider_source" not in TOOL_REGISTRY
    assert "revoke_broker_provider_source" not in TOOL_REGISTRY


def test_provider_approval_cli_accepts_exact_interactive_confirmation(tmp_path: Path, monkeypatch, capsys) -> None:
    class OperatorInput(io.StringIO):
        def isatty(self) -> bool:
            return True

    workspace = make_workspace(tmp_path)
    write_provider(workspace, "interactive")
    inspected = inspect_workspace_broker_provider_source(workspace, "interactive")
    monkeypatch.setattr(
        sys,
        "stdin",
        OperatorInput(f"interactive {inspected['bundle_sha256']}\n"),
    )
    connectors(workspace, ["approve-provider", "interactive"])
    assert "\"status\": \"approved\"" in capsys.readouterr().out

    monkeypatch.setattr(sys, "stdin", OperatorInput("REVOKE interactive\n"))
    connectors(workspace, ["revoke-provider", "interactive"])
    assert "\"status\": \"revoked\"" in capsys.readouterr().out


def test_revoke_invalidates_loaded_provider_immediately(tmp_path: Path, monkeypatch) -> None:
    workspace = make_workspace(tmp_path)
    write_provider(workspace, "revoked")
    approve_exact(workspace, "revoked")
    simulate_service_restart(monkeypatch)
    assert get_broker_adapter_provider("revoked", workspace) is not None
    assert _WORKSPACE_PROVIDER_CACHE

    revoked = revoke_workspace_broker_provider_source(
        workspace,
        "revoked",
        operator_authority=issue_test_operator_authority(
            workspace,
            action=PROVIDER_SOURCE_REVOKE,
            resource=provider_source_revocation_resource("revoked"),
        ),
    )
    assert revoked["status"] == "revoked"
    assert not _WORKSPACE_PROVIDER_CACHE
    with pytest.raises(PermissionError, match="requires explicit operator approval"):
        get_broker_adapter_provider("revoked", workspace)
