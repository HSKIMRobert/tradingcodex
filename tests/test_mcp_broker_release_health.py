from __future__ import annotations

import json
import logging
import sys
import tomllib
import uuid
from pathlib import Path

import pytest
from django.test import Client

from apps.mcp.services import check_external_mcp_connection, register_external_mcp_connection
from tradingcodex_cli import service_autostart
from tradingcodex_service.application import health as health_service
from tradingcodex_service.application.brokers import (
    BrokerAdapter,
    BrokerAdapterProvider,
    BrokerHealth,
    _BROKER_ADAPTER_PROVIDERS,
    get_broker_connection_status,
    register_broker_adapter_provider,
    register_broker_connector,
    validate_broker_connector_build,
)
from tradingcodex_service.application.runtime import ensure_runtime_database, tradingcodex_state_dir
from tradingcodex_service.mcp_runtime import call_mcp_tool
from tradingcodex_service.log_safety import RedactingFormatter


ROOT = Path(__file__).resolve().parents[1]


def test_package_metadata_uses_the_runtime_version_source() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["dynamic"] == ["version"]
    assert "version" not in project["project"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "tradingcodex_service.version.TRADINGCODEX_VERSION"
    }


def test_external_mcp_env_is_reference_only_and_secret_never_persists(monkeypatch, tmp_path: Path) -> None:
    ensure_runtime_database(tmp_path)
    from apps.audit.models import AuditEvent
    from apps.mcp.models import McpRouter, McpToolCall

    name = f"secret-wall-{uuid.uuid4().hex}"
    canary = f"tcx-secret-{uuid.uuid4().hex}"
    monkeypatch.setenv("TRADINGCODEX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MCP_TEST_SECRET", canary)
    server = tmp_path / "server.py"
    server.write_text(
        "import json, os, sys\n"
        "print(os.environ['TARGET_SECRET'], file=sys.stderr, flush=True)\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if 'id' in request:\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': {'serverInfo': {'name': 'test'}}}), flush=True)\n",
        encoding="utf-8",
    )

    registered = register_external_mcp_connection(
        tmp_path,
        {
            "name": name,
            "command": sys.executable,
            "args": [str(server)],
            "env": {"TARGET_SECRET": "env:MCP_TEST_SECRET"},
            "enabled": True,
        },
    )
    assert registered["connection"]["name"] == name
    assert canary not in json.dumps(registered)
    router = McpRouter.objects.get(name=name)
    assert router.env == {"TARGET_SECRET": "env:MCP_TEST_SECRET"}

    checked = check_external_mcp_connection(tmp_path, {"name": name, "timeout": 3})
    assert checked["status"] == "checked"
    log_path = tradingcodex_state_dir() / "run" / "external-mcp" / f"{name}.stderr.log"
    assert canary not in log_path.read_text(encoding="utf-8")
    assert "<redacted>" in log_path.read_text(encoding="utf-8")

    invalid_name = f"secret-wall-invalid-{uuid.uuid4().hex}"
    with pytest.raises(ValueError, match="raw values are not accepted"):
        call_mcp_tool(
            tmp_path,
            "register_external_mcp_connection",
            {"principal_id": "head-manager", "name": invalid_name, "env": {"TARGET_SECRET": canary}},
        )
    assert not McpRouter.objects.filter(name=invalid_name).exists()
    with pytest.raises(ValueError, match="inline credentials"):
        call_mcp_tool(
            tmp_path,
            "register_external_mcp_connection",
            {
                "principal_id": "head-manager",
                "name": f"secret-wall-args-{uuid.uuid4().hex}",
                "command": sys.executable,
                "args": ["--api-key", canary],
            },
        )
    ledger = McpToolCall.objects.filter(tool_name="register_external_mcp_connection").first()
    assert ledger is not None
    assert canary not in json.dumps({"request": ledger.request, "response": ledger.response, "error": ledger.error})
    assert canary not in json.dumps(list(AuditEvent.objects.values_list("payload", flat=True)))
    from django.db import connection

    database_path = Path(connection.settings_dict["NAME"])
    connection.close()
    for candidate in (database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
        if candidate.exists():
            assert canary.encode() not in candidate.read_bytes()


class _ValidationAdapter(BrokerAdapter):
    def health_check(self) -> BrokerHealth:
        return BrokerHealth("ok", "validation health ok")


def test_broker_status_is_read_only_and_explicit_validation_promotes(tmp_path: Path) -> None:
    ensure_runtime_database(tmp_path)
    provider_id = f"validation-{uuid.uuid4().hex}"
    register_broker_adapter_provider(
        BrokerAdapterProvider(
            provider_id=provider_id,
            display_name="Validation Test",
            execution_posture="broker_validation_only",
            adapter_type=provider_id,
            auth_model={"type": "credential_ref", "credential_ref_required": True},
            factory=lambda connection, workspace_root: _ValidationAdapter(),
        )
    )
    try:
        register_broker_connector(
            tmp_path,
            {"provider": provider_id, "broker_id": provider_id, "credential_ref": "env:VALIDATION_TEST"},
        )
        from apps.integrations.models import BrokerConnection

        connection = BrokerConnection.objects.get(broker_id=provider_id)
        before = {
            "status": connection.status,
            "trade_scopes": connection.enabled_trade_scopes,
            "health": connection.last_health_status,
            "metadata": connection.metadata,
            "updated_at": connection.updated_at,
        }
        observed = get_broker_connection_status(tmp_path, {"broker_id": provider_id, "promote_execution": True})
        connection.refresh_from_db()
        after = {
            "status": connection.status,
            "trade_scopes": connection.enabled_trade_scopes,
            "health": connection.last_health_status,
            "metadata": connection.metadata,
            "updated_at": connection.updated_at,
        }
        assert observed["health"]["status"] == "ok"
        assert observed["read_only"] is True
        assert after == before

        validated = validate_broker_connector_build(tmp_path, {"broker_id": provider_id})
        connection.refresh_from_db()
        assert validated["connection"]["read_only"] is False
        assert connection.status == "trading_enabled"
        assert connection.enabled_trade_scopes == ["order.submit.validation"]
    finally:
        _BROKER_ADAPTER_PROVIDERS.pop(provider_id, None)


def test_liveness_and_readiness_are_distinct(monkeypatch, tmp_path: Path) -> None:
    ensure_runtime_database(tmp_path)
    client = Client(REMOTE_ADDR="127.0.0.1")
    live = client.get("/api/health/live")
    ready = client.get("/api/health/ready")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert "checks" not in live.json()
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert {check["name"] for check in ready.json()["checks"]} == {"database", "migrations", "state_directory"}

    monkeypatch.setattr(
        health_service,
        "_state_directory_check",
        lambda: {"name": "state_directory", "status": "failed", "code": "state_directory_unwritable"},
    )
    not_ready = client.get("/api/health/ready")
    assert not_ready.status_code == 503
    assert not_ready.json()["ready"] is False
    assert not_ready.json()["reason_codes"] == ["state_directory_unwritable"]


def test_service_logging_uses_bounded_rotating_handler() -> None:
    from tradingcodex_service.settings import LOGGING

    handler = LOGGING["handlers"]["service_file"]
    assert handler["class"] == "logging.handlers.RotatingFileHandler"
    assert handler["maxBytes"] > 0
    assert handler["backupCount"] > 0
    assert handler["formatter"] == "redacted"


def test_service_log_formatter_redacts_environment_secrets(monkeypatch) -> None:
    canary = f"tcx-log-secret-{uuid.uuid4().hex}"
    monkeypatch.setenv("PROVIDER_API_KEY", canary)
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "provider failed: %s", (canary,), None)
    formatted = RedactingFormatter("{levelname} {message}", style="{").format(record)
    assert canary not in formatted
    assert "<redacted>" in formatted
