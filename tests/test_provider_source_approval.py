from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.db.utils import DatabaseError

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


def write_source_provenance(workspace: Path, provider_id: str, document: dict | None = None) -> Path:
    provider_dir = workspace / "trading" / "connectors" / provider_id
    provenance = document or {
        "schema_version": 1,
        "sources": [
            {
                "kind": "https",
                "url": "https://docs.example.org/broker/provider-api.html",
                "resolved_ref": "api-v1",
                "fetched_content_sha256": "a" * 64,
                "retrieved_at": "2026-07-16T01:02:03Z",
            },
            {
                "kind": "git",
                "url": "https://github.com/example/provider-sdk",
                "requested_ref": "v1.2.3",
                "resolved_commit": "b" * 40,
                "fetched_content_sha256": "c" * 64,
                "retrieved_at": "2026-07-16T10:02:03+09:00",
            },
        ],
    }
    path = provider_dir / "source-provenance.json"
    path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "ledger_error",
    [
        PermissionError("central ledger denied"),
        DatabaseError("unable to open database file"),
    ],
    ids=["filesystem-denied", "database-unavailable"],
)
def test_provider_inspection_falls_back_to_inert_bundle_when_ledger_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ledger_error: Exception,
) -> None:
    workspace = make_workspace(tmp_path)
    provider_path = write_provider(workspace, "build-static")

    def deny_ledger(_workspace: Path) -> None:
        raise ledger_error

    monkeypatch.setattr(
        "tradingcodex_service.application.brokers.ensure_runtime_database",
        deny_ledger,
    )

    inspected = inspect_workspace_broker_provider_source(workspace, "build-static")

    assert inspected["kind"] == "workspace"
    assert inspected["inspection_scope"] == "bundle_only"
    assert inspected["approval_status"] == "service_check_required"
    assert inspected["provider_py_sha256"] == hashlib.sha256(provider_path.read_bytes()).hexdigest()
    assert inspected["bundle_sha256"]


def test_provider_inspection_falls_back_when_ledger_query_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = make_workspace(tmp_path)
    write_provider(workspace, "query-denied")

    def deny_query(*_args, **_kwargs):
        raise DatabaseError("ledger query denied")

    monkeypatch.setattr(
        "tradingcodex_service.application.brokers._approved_workspace_provider_source",
        deny_query,
    )

    inspected = inspect_workspace_broker_provider_source(workspace, "query-denied")

    assert inspected["inspection_scope"] == "bundle_only"
    assert inspected["approval_status"] == "service_check_required"


def test_provider_status_requires_explicit_opt_in_for_ledger_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = make_workspace(tmp_path)
    write_provider(workspace, "strict-ledger")

    def deny_ledger(_workspace: Path) -> None:
        raise DatabaseError("ledger unavailable")

    monkeypatch.setattr(
        "tradingcodex_service.application.brokers.ensure_runtime_database",
        deny_ledger,
    )

    with pytest.raises(DatabaseError, match="ledger unavailable"):
        broker_provider_source_status("strict-ledger", workspace)


def test_provider_inspection_does_not_misclassify_non_ledger_os_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = make_workspace(tmp_path)
    write_provider(workspace, "context-failure")

    def deny_workspace_context(_workspace: Path) -> dict:
        raise OSError("workspace context unavailable")

    monkeypatch.setattr(
        "tradingcodex_service.application.brokers.workspace_context_payload",
        deny_workspace_context,
    )

    with pytest.raises(OSError, match="workspace context unavailable"):
        inspect_workspace_broker_provider_source(workspace, "context-failure")


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


def test_safe_legacy_provider_bundle_keeps_the_v1_0_2_digest_and_approval(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    provider_path = write_provider(workspace, "legacy-safe", relative_helper=True)
    provider_dir = provider_path.parent

    digest = hashlib.sha256()
    digest.update(b"TradingCodexProviderBundle\x00v1\x00")
    for member in ("helper.py", "provider.py"):
        data = (provider_dir / member).read_bytes()
        encoded_path = member.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    inspected = inspect_workspace_broker_provider_source(workspace, "legacy-safe")
    assert inspected["bundle_sha256"] == digest.hexdigest()
    assert inspected["source_provenance"]["status"] == "not_provided"

    approved = approve_exact(workspace, "legacy-safe")
    assert approved["bundle_sha256"] == digest.hexdigest()
    assert broker_provider_source_status("legacy-safe", workspace)["approval_status"] == "approved"


@pytest.mark.parametrize(
    ("provider_id", "source"),
    [
        (
            "syntax-invalid",
            "from pathlib import Path\n"
            "Path({sentinel!r}).write_text('executed', encoding='utf-8')\n"
            "PROVIDER = (\n",
        ),
        (
            "contract-invalid",
            "from pathlib import Path\n"
            "Path({sentinel!r}).write_text('executed', encoding='utf-8')\n"
            "VALUE = 1\n",
        ),
    ],
    ids=["invalid-syntax", "missing-loader-entrypoint"],
)
def test_invalid_provider_source_is_rejected_before_approval_or_execution(
    tmp_path: Path,
    provider_id: str,
    source: str,
) -> None:
    workspace = make_workspace(tmp_path)
    provider_dir = workspace / "trading" / "connectors" / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)
    sentinel = tmp_path / f"{provider_id}-executed.txt"
    (provider_dir / "provider.py").write_text(
        source.format(sentinel=str(sentinel)),
        encoding="utf-8",
    )

    inspected = inspect_workspace_broker_provider_source(workspace, provider_id)

    assert inspected["approval_status"] == "blocked"
    assert inspected["drift_status"] == "unsafe_or_invalid_source"
    assert not sentinel.exists()

    expected_hash = "0" * 64
    with pytest.raises(ValueError, match="valid Python syntax|module-level PROVIDER or get_provider"):
        approve_workspace_broker_provider_source(
            workspace,
            provider_id,
            expected_bundle_sha256=expected_hash,
            operator_authority=issue_test_operator_authority(
                workspace,
                action=PROVIDER_SOURCE_APPROVE,
                resource=provider_source_approval_resource(provider_id, expected_hash),
            ),
        )
    assert not sentinel.exists()


def test_deep_provider_ast_is_rejected_without_leaking_recursion_errors(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    provider_id = "deep-ast"
    provider_dir = workspace / "trading" / "connectors" / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)
    (provider_dir / "provider.py").write_text(
        "PROVIDER = " + "+".join(["1"] * 2_000) + "\n",
        encoding="utf-8",
    )

    inspected = inspect_workspace_broker_provider_source(workspace, provider_id)

    assert inspected["approval_status"] == "blocked"
    assert inspected["drift_status"] == "unsafe_or_invalid_source"
    expected_hash = "0" * 64
    with pytest.raises(ValueError, match="valid Python syntax|complexity"):
        approve_workspace_broker_provider_source(
            workspace,
            provider_id,
            expected_bundle_sha256=expected_hash,
            operator_authority=issue_test_operator_authority(
                workspace,
                action=PROVIDER_SOURCE_APPROVE,
                resource=provider_source_approval_resource(provider_id, expected_hash),
            ),
        )


def test_synchronous_get_provider_entrypoint_remains_inspectable_without_execution(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    provider_id = "factory-provider"
    provider_dir = workspace / "trading" / "connectors" / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)
    sentinel = tmp_path / "factory-provider-executed.txt"
    (provider_dir / "provider.py").write_text(
        (
            "from pathlib import Path\n"
            "from tradingcodex_service.application.brokers import BrokerAdapterProvider\n"
            f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
            "\n"
            "def get_provider():\n"
            "    return BrokerAdapterProvider(\n"
            f"        provider_id={provider_id!r},\n"
            "        display_name='Factory provider',\n"
            "        execution_posture='broker_validation_only',\n"
            "    )\n"
        ),
        encoding="utf-8",
    )

    inspected = inspect_workspace_broker_provider_source(workspace, provider_id)

    assert inspected["approval_status"] == "approval_required"
    assert inspected["bundle_sha256"]
    assert not sentinel.exists()


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


def test_provider_source_provenance_is_optional_validated_hashed_and_sanitized(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    write_provider(workspace, "provenance")

    legacy_status = inspect_workspace_broker_provider_source(workspace, "provenance")
    assert legacy_status["source_provenance"] == {
        "status": "not_provided",
        "schema_version": None,
        "source_count": 0,
        "sources": [],
    }
    legacy_bundle_sha256 = legacy_status["bundle_sha256"]

    write_source_provenance(workspace, "provenance")
    inspected = inspect_workspace_broker_provider_source(workspace, "provenance")
    assert inspected["bundle_sha256"] != legacy_bundle_sha256
    assert inspected["source_provenance"] == {
        "status": "validated",
        "schema_version": 1,
        "source_count": 2,
        "sources": [
            {
                "kind": "https",
                "url": "https://docs.example.org/broker/provider-api.html",
                "resolved_ref": "api-v1",
                "fetched_content_sha256": "a" * 64,
                "retrieved_at": "2026-07-16T01:02:03Z",
            },
            {
                "kind": "git",
                "url": "https://github.com/example/provider-sdk",
                "fetched_content_sha256": "c" * 64,
                "retrieved_at": "2026-07-16T01:02:03Z",
                "requested_ref": "v1.2.3",
                "resolved_commit": "b" * 40,
            },
        ],
    }

    approved = approve_exact(workspace, "provenance")
    snapshot_provenance = tradingcodex_home() / approved["snapshot_relative_path"] / "source-provenance.json"
    assert snapshot_provenance.read_bytes() == (
        workspace / "trading" / "connectors" / "provenance" / "source-provenance.json"
    ).read_bytes()

    provenance_path = workspace / "trading" / "connectors" / "provenance" / "source-provenance.json"
    document = json.loads(provenance_path.read_text(encoding="utf-8"))
    document["sources"][0]["fetched_content_sha256"] = "d" * 64
    provenance_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    drifted = inspect_workspace_broker_provider_source(workspace, "provenance")
    assert drifted["bundle_sha256"] != approved["bundle_sha256"]
    assert drifted["approval_status"] == "stale"
    assert drifted["drift_status"] == "approval_stale"


@pytest.mark.parametrize(
    ("document", "error"),
    [
        (
            {"schema_version": 2, "sources": []},
            "schema_version must be 1",
        ),
        (
            {
                "schema_version": 1,
                "sources": [
                    {
                        "kind": "https",
                        "url": "https://user:password@docs.example.org/provider",
                        "resolved_ref": "api-v1",
                        "fetched_content_sha256": "a" * 64,
                        "retrieved_at": "2026-07-16T01:02:03Z",
                    }
                ],
            },
            "must not contain credentials",
        ),
        (
            {
                "schema_version": 1,
                "sources": [
                    {
                        "kind": "https",
                        "url": "https://docs.example.org/provider?api_key=secret",
                        "resolved_ref": "api-v1",
                        "fetched_content_sha256": "a" * 64,
                        "retrieved_at": "2026-07-16T01:02:03Z",
                    }
                ],
            },
            "must not contain credentials, query, or fragment",
        ),
        (
            {
                "schema_version": 1,
                "sources": [
                    {
                        "kind": "https",
                        "url": "https://127.0.0.1/provider",
                        "resolved_ref": "api-v1",
                        "fetched_content_sha256": "a" * 64,
                        "retrieved_at": "2026-07-16T01:02:03Z",
                    }
                ],
            },
            "must use a public host",
        ),
        (
            {
                "schema_version": 1,
                "sources": [
                    {
                        "kind": "https",
                        "url": "https://docs.example.org/provider",
                        "resolved_ref": "api-v1",
                        "fetched_content_sha256": "A" * 64,
                        "retrieved_at": "2026-07-16T01:02:03Z",
                    }
                ],
            },
            "lowercase SHA-256",
        ),
        (
            {
                "schema_version": 1,
                "sources": [
                    {
                        "kind": "https",
                        "url": "https://docs.example.org/provider",
                        "resolved_ref": "api-v1",
                        "fetched_content_sha256": "a" * 64,
                        "retrieved_at": "2026-07-16 01:02:03",
                    }
                ],
            },
            "RFC 3339",
        ),
        (
            {
                "schema_version": 1,
                "sources": [
                    {
                        "kind": "git",
                        "url": "https://github.com/example/provider-sdk",
                        "requested_ref": "main",
                        "fetched_content_sha256": "a" * 64,
                        "retrieved_at": "2026-07-16T01:02:03Z",
                    }
                ],
            },
            "requires exactly one of resolved_ref or resolved_commit",
        ),
        (
            {
                "schema_version": 1,
                "sources": [
                    {
                        "kind": "git",
                        "url": "https://github.com/example/provider-sdk",
                        "resolved_ref": "refs/heads/main",
                        "resolved_commit": "b" * 40,
                        "fetched_content_sha256": "a" * 64,
                        "retrieved_at": "2026-07-16T01:02:03Z",
                    }
                ],
            },
            "requires exactly one of resolved_ref or resolved_commit",
        ),
        (
            {
                "schema_version": 1,
                "sources": [
                    {
                        "kind": "https",
                        "url": "https://docs.example.org/provider",
                        "resolved_commit": "b" * 40,
                        "fetched_content_sha256": "a" * 64,
                        "retrieved_at": "2026-07-16T01:02:03Z",
                    }
                ],
            },
            "HTTPS sources must use resolved_ref",
        ),
    ],
)
def test_provider_source_provenance_rejects_unsafe_or_noncanonical_entries(
    tmp_path: Path,
    document: dict,
    error: str,
) -> None:
    workspace = make_workspace(tmp_path)
    write_provider(workspace, "invalid-provenance")
    write_source_provenance(workspace, "invalid-provenance", document)

    status = inspect_workspace_broker_provider_source(workspace, "invalid-provenance")
    assert status["approval_status"] == "blocked"
    assert status["source_provenance"]["status"] == "unavailable"
    with pytest.raises(ValueError, match=error):
        approve_workspace_broker_provider_source(
            workspace,
            "invalid-provenance",
            expected_bundle_sha256="0" * 64,
            operator_authority=issue_test_operator_authority(
                workspace,
                action=PROVIDER_SOURCE_APPROVE,
                resource=provider_source_approval_resource("invalid-provenance", "0" * 64),
            ),
        )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        ".git/config",
        ".hg/store/data",
        ".svn/entries",
        ".env",
        ".env.production",
        "settings.env",
        "broker-credentials.json",
        "prod_api_key.json",
        "my-private-key.yaml",
        "client-secret.toml",
        "credentials.json",
        "key.json",
        "private.key",
    ],
)
def test_provider_bundle_rejects_vcs_metadata_and_secret_like_files(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    workspace = make_workspace(tmp_path)
    write_provider(workspace, "unsafe-bundle")
    path = workspace / "trading" / "connectors" / "unsafe-bundle" / unsafe_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("must-not-enter-provider-snapshot\n", encoding="utf-8")

    status = inspect_workspace_broker_provider_source(workspace, "unsafe-bundle")
    assert status["approval_status"] == "blocked"
    assert status["drift_status"] == "unsafe_or_invalid_source"
    expected_error = "VCS metadata" if any(part in {".git", ".hg", ".svn"} for part in path.parts) else "secret-like"
    with pytest.raises(ValueError, match=expected_error):
        approve_workspace_broker_provider_source(
            workspace,
            "unsafe-bundle",
            expected_bundle_sha256="0" * 64,
            operator_authority=issue_test_operator_authority(
                workspace,
                action=PROVIDER_SOURCE_APPROVE,
                resource=provider_source_approval_resource("unsafe-bundle", "0" * 64),
            ),
        )


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


@pytest.mark.parametrize(
    "ignored_name",
    ["connector-profile.json", "cached-provider.pyc"],
    ids=["connector-runtime-file", "bytecode-file"],
)
def test_provider_bundle_rejects_symlinks_even_when_the_filename_is_ignored(
    tmp_path: Path,
    ignored_name: str,
) -> None:
    workspace = make_workspace(tmp_path)
    provider_path = write_provider(workspace, "ignored-symlink")
    outside_file = tmp_path / f"outside-{ignored_name}"
    outside_file.write_text("must-not-enter-provider-bundle\n", encoding="utf-8")
    try:
        (provider_path.parent / ignored_name).symlink_to(outside_file)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")

    status = inspect_workspace_broker_provider_source(workspace, "ignored-symlink")

    assert status["approval_status"] == "blocked"
    assert status["drift_status"] == "unsafe_or_invalid_source"
    expected_hash = "0" * 64
    with pytest.raises(ValueError, match="symlink"):
        approve_workspace_broker_provider_source(
            workspace,
            "ignored-symlink",
            expected_bundle_sha256=expected_hash,
            operator_authority=issue_test_operator_authority(
                workspace,
                action=PROVIDER_SOURCE_APPROVE,
                resource=provider_source_approval_resource("ignored-symlink", expected_hash),
            ),
        )


def test_provider_directory_rejects_mocked_windows_reparse_attribute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = make_workspace(tmp_path)
    provider_path = write_provider(workspace, "reparse-provider")
    provider_dir = provider_path.parent
    original_lstat = Path.lstat

    def mocked_lstat(path: Path):
        metadata = original_lstat(path)
        if path == provider_dir:
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_file_attributes=0x400,
            )
        return metadata

    monkeypatch.setattr(Path, "lstat", mocked_lstat)

    status = inspect_workspace_broker_provider_source(workspace, "reparse-provider")

    assert status["approval_status"] == "blocked"
    assert status["drift_status"] == "unsafe_or_invalid_source"
    expected_hash = "0" * 64
    with pytest.raises(ValueError, match="symlink"):
        approve_workspace_broker_provider_source(
            workspace,
            "reparse-provider",
            expected_bundle_sha256=expected_hash,
            operator_authority=issue_test_operator_authority(
                workspace,
                action=PROVIDER_SOURCE_APPROVE,
                resource=provider_source_approval_resource("reparse-provider", expected_hash),
            ),
        )


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


@pytest.mark.parametrize(
    "unavailable_status",
    [
        {"inspection_scope": "bundle_only", "approval_status": "approval_required"},
        {"inspection_scope": "service_and_bundle", "approval_status": "service_check_required"},
    ],
    ids=["bundle-only", "service-check-required"],
)
def test_provider_approval_cli_rejects_unavailable_ledger_before_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    unavailable_status: dict[str, str],
) -> None:
    class OperatorInput(io.StringIO):
        def isatty(self) -> bool:
            return True

    workspace = make_workspace(tmp_path)
    status = {
        "kind": "workspace",
        "path": "trading/connectors/demo/provider.py",
        "provider_py_sha256": "a" * 64,
        "bundle_sha256": "b" * 64,
        **unavailable_status,
    }
    monkeypatch.setattr(sys, "stdin", OperatorInput("demo " + "b" * 64 + "\n"))
    monkeypatch.setattr(
        "tradingcodex_cli.commands.connectors.brokers.inspect_workspace_broker_provider_source",
        lambda *_args, **_kwargs: status,
    )

    def unexpected_confirmation(_prompt: str) -> str:
        pytest.fail("approval confirmation must not be requested without canonical ledger inspection")

    monkeypatch.setattr("builtins.input", unexpected_confirmation)

    with pytest.raises(PermissionError, match="canonical ledger inspection"):
        connectors(workspace, ["approve-provider", "demo"])

    assert capsys.readouterr().out == ""


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
