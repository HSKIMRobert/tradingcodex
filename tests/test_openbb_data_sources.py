from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tradingcodex_cli.commands.data_sources import data_sources
from tradingcodex_cli import generator
from tradingcodex_service.application import data_sources as service


@pytest.fixture
def openbb_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    monkeypatch.setenv("TRADINGCODEX_HOME", str(home))
    monkeypatch.delenv("TRADINGCODEX_HOME_SOURCE", raising=False)
    return root, home


def _configure_and_enable(
    root: Path,
    *,
    provider: str = "fmp",
    access: str = "free",
    credential_refs: list[str] | None = None,
) -> None:
    service.configure_openbb_provider(
        root,
        {
            "provider": provider,
            "access": access,
            "credential_refs": credential_refs or [],
        },
    )
    service.enable_openbb_provider(
        root,
        {"provider": provider, "data_kinds": ["equity_price"]},
    )


def _valid_compatibility_payload(
    *,
    route_map: list[dict[str, Any]] | None = None,
    refresh_session_sha256: str = "test-session",
    configuration_scope_digest: str = "",
) -> dict[str, Any]:
    routes = list(route_map or [])
    metadata = [
        {
            "name": "openbb",
            "version": "4.7.2",
            "license": "AGPL-3.0-only",
            "origin": "https://pypi.org/project/openbb/",
            "metadata_sha256": "1" * 64,
            "record_sha256": "2" * 64,
            "installed_files_sha256": "a" * 64,
        },
        {
            "name": "openbb-mcp-server",
            "version": "1.4.1",
            "license": "AGPL-3.0-only",
            "origin": "https://pypi.org/project/openbb-mcp-server/",
            "metadata_sha256": "3" * 64,
            "record_sha256": "4" * 64,
            "installed_files_sha256": "b" * 64,
        },
    ]
    return {
        "format": service.COMPATIBILITY_FORMAT,
        "schema_version": service.COMPATIBILITY_SCHEMA_VERSION,
        "status": "compatible",
        "checked_at": "2026-07-18T00:00:00Z",
        "refresh_session_sha256": refresh_session_sha256,
        "requested_packages": ["openbb-mcp-server@latest", "openbb@latest"],
        "resolved_versions": {"openbb": "4.7.2", "openbb-mcp-server": "1.4.1"},
        "package_metadata": metadata,
        "package_metadata_digest": service.stable_hash(metadata),
        "server_info": {
            "name": "OpenBB",
            "version": "1.4.1",
            "protocol_version": "2025-06-18",
        },
        "license_declaration": "AGPL-3.0-only",
        "license_verified": True,
        "tool_digest": "5" * 64,
        "schema_digest": "6" * 64,
        "route_digest": service.stable_hash(routes),
        "route_map": routes,
        "route_categories": sorted({str(route.get("category") or "") for route in routes}),
        "route_map_truncated": False,
        "configuration_scope_digest": configuration_scope_digest,
    }


def test_configuration_splits_nonsecret_workspace_state_from_home_refs(
    openbb_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home = openbb_workspace
    monkeypatch.setenv("MY_MARKET_KEY", "raw-value-must-not-persist")

    _configure_and_enable(root, credential_refs=["fmp_api_key=env:MY_MARKET_KEY"])

    workspace_text = (root / service.WORKSPACE_DATA_SOURCE_PATH).read_text(encoding="utf-8")
    credential_path = home / service.OPENBB_CREDENTIAL_PATH
    credential_text = credential_path.read_text(encoding="utf-8")
    status = service.get_data_source_status(root, {"provider": "fmp"})
    rendered_status = json.dumps(status)
    assert "MY_MARKET_KEY" not in workspace_text
    assert "env:MY_MARKET_KEY" in credential_text
    assert "raw-value-must-not-persist" not in workspace_text + credential_text + rendered_status
    assert status["providers"][0]["credentials"] == "available"
    assert status["providers"][0]["declared_access"] == "free"
    assert status["providers"][0]["observed_access"] == "unprobed"
    assert status["providers"][0]["credential_slot_hints"] == ["fmp_api_key"]
    assert status["providers"][0]["credential_slot_hint_source"] == "configured"
    assert credential_path.stat().st_mode & 0o777 == 0o600


def test_status_labels_unconfigured_credential_slot_as_unverified_hint(
    openbb_workspace: tuple[Path, Path],
) -> None:
    root, _ = openbb_workspace
    status = service.configure_openbb_provider(root, {"provider": "fmp", "access": "free"})
    provider = status["providers"][0]
    assert provider["credentials"] == "ref_missing"
    assert provider["credential_slot_hints"] == ["fmp_api_key"]
    assert provider["credential_slot_hint_source"] == "provider_name_convention_unverified"


@pytest.mark.parametrize(
    "assignment",
    [
        "fmp_api_key=raw-secret",
        "fmp_api_key=env:BAD-NAME",
        "fmp_api_key=env:sk_live_secret",
        "PATH=env:SAFE",
        "pythoninspect_api_key=env:SAFE",
        "ld_preload_token=env:SAFE",
        "ssl_cert_file_api_key=env:SAFE",
        "fmp_api_key=env:PATH",
        "fmp_api_key=env:PYTHONPATH",
        "fmp_api_key=env:DYLD_INSERT_LIBRARIES",
        "fmp_api_key=env:CODEX_HOME",
        "fmp_api_key=env:TRADINGCODEX_HOME",
        "fmp_api_key=env:UV_CONFIG_FILE",
        "fmp_api_key=env:SSL_CERT_FILE",
        "fmp_api_key=env:ONE=MORE",
    ],
)
def test_raw_or_unsafe_credential_assignments_are_rejected(
    openbb_workspace: tuple[Path, Path], assignment: str
) -> None:
    root, _ = openbb_workspace
    with pytest.raises(ValueError):
        service.configure_openbb_provider(
            root,
            {"provider": "fmp", "access": "free", "credential_refs": [assignment]},
        )


def test_credential_slot_must_match_provider_and_keyless_transition_is_explicit(
    openbb_workspace: tuple[Path, Path],
) -> None:
    root, _ = openbb_workspace
    with pytest.raises(ValueError, match="must start with fmp_"):
        service.configure_openbb_provider(
            root,
            {
                "provider": "fmp",
                "access": "free",
                "credential_refs": ["polygon_api_key=env:FMP_FROM_PARENT"],
            },
        )

    service.configure_openbb_provider(
        root,
        {
            "provider": "fmp",
            "access": "free",
            "credential_refs": ["fmp_api_key=env:FMP_FROM_PARENT"],
        },
    )
    with pytest.raises(ValueError, match="clear configured credential references"):
        service.configure_openbb_provider(root, {"provider": "fmp", "access": "keyless"})


def test_package_license_check_rejects_composite_or_changed_expression(
    openbb_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    del openbb_workspace
    payload = [
        {
            "name": name,
            "version": "1.0",
            "license": "MIT OR AGPL-3.0-only",
            "origin": f"https://pypi.org/project/{name}/",
            "metadata_sha256": "a" * 64,
            "record_sha256": "b" * 64,
        }
        for name in ("openbb-mcp-server", "openbb")
    ]
    monkeypatch.setattr(service.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
    )
    with pytest.raises(ValueError, match="license metadata is incompatible"):
        service._package_metadata()


def test_secondary_provider_requires_explicit_consent(openbb_workspace: tuple[Path, Path]) -> None:
    root, _ = openbb_workspace
    service.configure_openbb_provider(root, {"provider": "yfinance", "access": "unknown"})
    with pytest.raises(PermissionError, match="secondary-consent"):
        service.enable_openbb_provider(root, {"provider": "yfinance", "data_kinds": ["equity_price"]})
    status = service.enable_openbb_provider(
        root,
        {
            "provider": "yfinance",
            "data_kinds": ["equity_price"],
            "secondary_consent": True,
        },
    )
    assert status["providers"][0]["auto_use"] == "ask"


def test_projection_values_include_only_configured_env_names(
    openbb_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = openbb_workspace
    monkeypatch.setenv("UNRELATED_SECRET", "never-forward")
    monkeypatch.setenv("FMP_FROM_PARENT", "configured")
    _configure_and_enable(root, credential_refs=["fmp_api_key=env:FMP_FROM_PARENT"])
    values = service.openbb_projection_template_values(root)
    assert values["OPENBB_MCP_ENABLED_TOML"] == "true"
    assert json.loads(values["OPENBB_MCP_ENV_VARS_TOML"]) == ["FMP_FROM_PARENT"]
    child = service._openbb_runtime_environment(include_credentials=True, workspace_root=root)
    assert child["FMP_API_KEY"] == "configured"
    assert "FMP_FROM_PARENT" not in child
    assert "UNRELATED_SECRET" not in child


def test_generator_renders_enabled_role_mcp_with_exact_nonsecret_env_names(
    openbb_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _ = openbb_workspace
    monkeypatch.setenv("FMP_FROM_PARENT", "configured")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    _configure_and_enable(root, credential_refs=["fmp_api_key=env:FMP_FROM_PARENT"])
    generated_python = str(Path(generator.sys.executable).absolute())
    monkeypatch.setattr(generator, "resolve_generated_python", lambda **_kwargs: generated_python)
    monkeypatch.setattr(
        generator,
        "calculation_runtime_paths",
        lambda *_args, **_kwargs: (
            tmp_path / "calculation",
            tmp_path / "calculation" / "bin" / "python",
            tmp_path / "calculation" / "calculation_runner.py",
        ),
    )
    monkeypatch.setattr(
        generator,
        "_workspace_scratch_paths",
        lambda *_args, **_kwargs: (tmp_path / "scratch", tmp_path / "scratch"),
    )
    context = generator._generation_context(
        root,
        "tcxw_openbb_projection_test",
        provision_runtime=False,
        provision_scratch=False,
    )
    registry = generator.load_module_registry(generator.templates_dir())
    modules = generator.resolve_module_graph(registry, generator.DEFAULT_MODULE_IDS)
    rendered = generator.render_template_modules(modules, context)
    technical = tomllib.loads(rendered[".codex/agents/technical-analyst.toml"])
    openbb = technical["mcp_servers"]["openbb"]
    assert openbb["enabled"] is True
    assert openbb["required"] is False
    assert openbb["command"] == generated_python
    assert openbb["env_vars"] == ["FMP_FROM_PARENT"]
    assert openbb["args"][-2:] == ["--principal", "technical-analyst"]


def test_proxy_enforces_provider_admin_and_read_only_scope(openbb_workspace: tuple[Path, Path]) -> None:
    root, _ = openbb_workspace
    _configure_and_enable(root, access="free")
    proxy = service._OpenBBProxy(root, "technical-analyst")
    request_id = 0

    def error(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal request_id
        request_id += 1
        return proxy._request_error(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )

    assert error("available_categories", {}) is not None
    assert proxy._request_error({"method": "prompts/list"}) is not None
    assert proxy._request_error({"method": "resources/list"}) is not None
    assert error("deactivate_tools", {"tool_names": "equity_price_quote"}) is not None
    assert error("available_tools", {}) is not None
    assert error("available_tools", {"category": "equity", "subcategory": "price"}) is None
    assert error("available_tools", {"category": "equity", "subcategory": "price"}) is not None
    assert error("available_tools", {"category": "equity", "subcategory": "profile"}) is None
    assert proxy.available_tools_calls == 2
    assert error("activate_tools", {"tool_names": "one,two,three,four"}) is not None
    proxy.discovered_tools.update({"equity_price_quote", "equity_profile"})
    proxy.route_parameters["equity_price_quote"] = {"provider", "limit", "chart"}
    proxy.route_data_kinds["equity_price_quote"] = {"equity_price"}
    assert error("activate_tools", {"tool_names": "equity_price_quote"}) is None
    assert error("activate_tools", {"tool_names": "equity_profile"}) is None
    assert error("activate_tools", {"tool_names": "equity_price_quote"}) is not None
    assert proxy.activate_tools_calls == 2
    proxy.activated_tools.add("equity_price_quote")
    assert error("install_skill", {}) is not None
    assert error("equity_price_quote", {"provider": "polygon"}) is not None
    assert error("equity_price_quote", {"provider": "fmp", "limit": 121}) is not None
    assert error("equity_price_quote", {"provider": "fmp", "limit": 1, "chart": False}) is None

    service.configure_openbb_provider(root, {"provider": "paidfeed", "access": "paid"})
    service.enable_openbb_provider(root, {"provider": "paidfeed", "data_kinds": ["equity_price"]})
    ask_proxy = service._OpenBBProxy(root, "technical-analyst")
    ask_proxy.discovered_tools.add("equity_price_quote")
    ask_proxy.activated_tools.add("equity_price_quote")
    ask_proxy.route_parameters["equity_price_quote"] = {"provider", "limit", "chart"}
    ask_proxy.route_data_kinds["equity_price_quote"] = {"equity_price"}
    approval_error = ask_proxy._request_error(
        {
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "equity_price_quote",
                "arguments": {"provider": "paidfeed", "limit": 1, "chart": False},
            },
        }
    )
    assert approval_error is not None
    assert approval_error["code"] == -32003


def test_openbb_proxy_semantic_key_normalizes_aliases_and_preserves_identifiers() -> None:
    first = {
        "provider": "SEC",
        "series_id": "GDP",
        "fields": "VALUE",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "interval": "1d",
        "adjusted": False,
    }
    equivalent = {
        "provider_name": "sec",
        "series_id": ["gdp"],
        "columns": ["value"],
        "date_from": "2026-01-01T00:00:00Z",
        "date_to": "2026-01-31T00:00:00+00:00",
        "frequency": "DAILY",
        "adjustment": "raw",
    }
    assert service._openbb_semantic_call_key(
        "economy_series", first
    ) == service._openbb_semantic_call_key("economy_series", equivalent)

    for identifier_key in ("series_id", "contract"):
        baseline = {
            **{key: value for key, value in first.items() if key != "series_id"},
            identifier_key: "GDP",
        }
        distinct = {**baseline, identifier_key: "CPI"}
        assert service._openbb_semantic_call_key(
            "economy_series", baseline
        ) != service._openbb_semantic_call_key("economy_series", distinct)


def test_proxy_quarantines_runtime_version_drift_without_rewriting_resolved_version(
    openbb_workspace: tuple[Path, Path],
) -> None:
    root, _ = openbb_workspace
    _configure_and_enable(root, access="keyless")
    receipt = {
        "format": service.COMPATIBILITY_FORMAT,
        "schema_version": service.COMPATIBILITY_SCHEMA_VERSION,
        "status": "compatible",
        "resolved_versions": {"openbb": "4.7.2", "openbb-mcp-server": "1.4.1"},
        "server_info": {"protocol_version": "2025-06-18"},
    }
    service._write_compatibility_receipt(receipt)
    proxy = service._OpenBBProxy(root, "technical-analyst")
    proxy.pending["7"] = "initialize"
    filtered = proxy._filter_server_payload(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "OpenBB", "version": "9.9.9"},
            },
        }
    )
    assert filtered["error"]["code"] == -32004
    stored = service._read_receipt(service._compatibility_path())
    assert stored["status"] == "quarantined"
    assert stored["resolved_versions"]["openbb-mcp-server"] == "1.4.1"


def test_proxy_bounds_tool_catalog_and_strips_server_notification_payload(
    openbb_workspace: tuple[Path, Path],
) -> None:
    root, _ = openbb_workspace
    _configure_and_enable(root, access="keyless")
    proxy = service._OpenBBProxy(root, "technical-analyst")
    proxy.pending["9"] = "tools/list"
    bounded = proxy._filter_server_payload(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "result": {
                "tools": [
                    {
                        "name": "equity_price_historical",
                        "description": "x" * service.OPENBB_RESPONSE_CHAR_LIMIT,
                        "inputSchema": {"type": "object"},
                    }
                ]
            },
        }
    )
    assert bounded["error"]["code"] == -32005
    notification = proxy._filter_server_payload(
        {
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
            "params": {"untrusted": "x" * 1000},
        }
    )
    assert notification == {
        "jsonrpc": "2.0",
        "method": "notifications/tools/list_changed",
    }


def test_proxy_redacts_external_errors_headers_urls_and_bounds_large_results(
    openbb_workspace: tuple[Path, Path]
) -> None:
    root, _ = openbb_workspace
    _configure_and_enable(root, access="keyless")
    proxy = service._OpenBBProxy(root, "technical-analyst")
    external_error = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "message": "401 https://provider.invalid/x?api_key=raw-secret",
            "headers": {"Authorization": "Bearer raw-secret", "Cookie": "session=raw-secret"},
        },
    }
    sanitized_error = proxy._sanitize_tool_response(external_error)
    error_text = json.dumps(sanitized_error)
    assert "raw-secret" not in error_text
    assert "auth_failed" in error_text

    success = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "url=https://user:pass@x.invalid/?token=raw-secret "
                        "Authorization: Basic dXNlcjpwYXNz Cookie: session=raw-secret "
                        "Set-Cookie: auth=raw-secret"
                    ),
                }
            ],
            "headers": {"X-API-Key": "raw-secret"},
        },
    }
    success_text = json.dumps(proxy._sanitize_tool_response(success))
    assert "raw-secret" not in success_text
    assert "user:pass" not in success_text
    assert "dXNlcjpwYXNz" not in success_text
    assert "[redacted]" in success_text

    oversized = {"jsonrpc": "2.0", "id": 3, "result": {"rows": ["x" * 21_000]}}
    bounded = proxy._sanitize_tool_response(oversized)
    bounded_text = json.dumps(bounded)
    assert len(bounded_text) < 2_000
    assert "external_result_exceeds_context_limit" in bounded_text


def test_latest_refresh_is_single_flight_per_codex_session(
    openbb_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = openbb_workspace
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            "--transport --allowed-categories --default-categories --no-tool-discovery",
            "",
        )

    monkeypatch.setattr(service, "_uvx_path", lambda: "/usr/bin/uvx")
    monkeypatch.setattr(service, "_refresh_session_hash", lambda: "same-session")
    monkeypatch.setattr(service.subprocess, "run", fake_run)
    monkeypatch.setattr(
        service,
        "_package_metadata",
        lambda: [
            {
                "name": "openbb",
                "version": "4.7.2",
                "license": "AGPL-3.0-only",
                "origin": "https://pypi.org/project/openbb/",
                "metadata_sha256": "a" * 64,
                "record_sha256": "1" * 64,
                "installed_files_sha256": "e" * 64,
            },
            {
                "name": "openbb-mcp-server",
                "version": "1.4.1",
                "license": "AGPL-3.0-only",
                "origin": "https://pypi.org/project/openbb-mcp-server/",
                "metadata_sha256": "b" * 64,
                "record_sha256": "2" * 64,
                "installed_files_sha256": "f" * 64,
            },
        ],
    )
    monkeypatch.setattr(
        service,
        "_inspect_openbb_protocol",
        lambda _root, _versions: {
            "server_info": {"name": "OpenBB", "version": "1.4.1", "protocol_version": "2025-06-18"},
            "tool_digest": "c" * 64,
            "schema_digest": "d" * 64,
            "route_digest": service.stable_hash([]),
            "route_categories": [],
            "route_map": [],
            "route_map_truncated": False,
        },
    )
    first = service._ensure_openbb_compatibility(root, force_refresh=False)
    second = service._ensure_openbb_compatibility(root, force_refresh=False)
    assert len(calls) == 1
    assert first == second
    assert first["resolved_versions"] == {"openbb": "4.7.2", "openbb-mcp-server": "1.4.1"}
    assert first["license_verified"] is True
    assert first["tool_digest"] == "c" * 64
    assert service._runtime_status()[0] == "ready"


def test_receipt_route_map_is_bounded_filterable_and_seeds_fast_path(
    openbb_workspace: tuple[Path, Path]
) -> None:
    root, _ = openbb_workspace
    _configure_and_enable(root, access="keyless")
    state = service._read_state(root)
    discovery_result = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    [
                        {
                            "name": "equity_price_historical",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "provider": {"type": "string"},
                                    "symbol": {"type": "string"},
                                    "limit": {"type": "integer"},
                                },
                                "required": ["provider", "symbol"],
                            },
                        },
                        {
                            "name": "equity_account_write",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                    ]
                ),
            }
        ]
    }
    routes, truncated = service._build_route_map(
        [{"category": "equity", "result": discovery_result}],
        state,
    )
    assert truncated is False
    assert [route["tool_name"] for route in routes] == ["equity_price_historical"]
    receipt = _valid_compatibility_payload(
        route_map=routes,
        configuration_scope_digest=service._compatibility_scope_digest(state),
    )
    service._write_compatibility_receipt(receipt)
    status = service.get_data_source_status(root, {"data_kind": "equity_price"})
    assert status["compatibility_receipt"]["route_map"][0]["tool_name"] == "equity_price_historical"
    proxy = service._OpenBBProxy(root, "technical-analyst")
    assert proxy.available_tools_calls == 0
    assert proxy._request_error(
        {
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "activate_tools",
                "arguments": {"tool_names": "equity_price_historical"},
            },
        }
    ) is None
    assert "equity_price_historical" not in proxy.activated_tools
    proxy.pending["1"] = "tools/call:activate_tools"
    proxy._filter_server_payload(
        {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ok"}]}}
    )
    assert "equity_price_historical" in proxy.activated_tools


def test_runtime_status_detects_compatibility_receipt_tampering(
    openbb_workspace: tuple[Path, Path],
) -> None:
    del openbb_workspace
    metadata = [
        {
            "name": "openbb",
            "version": "4.7.2",
            "license": "AGPL-3.0-only",
            "origin": "https://pypi.org/project/openbb/",
            "metadata_sha256": "1" * 64,
            "record_sha256": "2" * 64,
            "installed_files_sha256": "7" * 64,
        },
        {
            "name": "openbb-mcp-server",
            "version": "1.4.1",
            "license": "AGPL-3.0-only",
            "origin": "https://pypi.org/project/openbb-mcp-server/",
            "metadata_sha256": "3" * 64,
            "record_sha256": "4" * 64,
            "installed_files_sha256": "8" * 64,
        },
    ]
    route_map: list[dict[str, Any]] = []
    service._write_compatibility_receipt(
        {
            "format": service.COMPATIBILITY_FORMAT,
            "schema_version": service.COMPATIBILITY_SCHEMA_VERSION,
            "status": "compatible",
            "license_verified": True,
            "package_metadata": metadata,
            "package_metadata_digest": service.stable_hash(metadata),
            "resolved_versions": {"openbb": "4.7.2", "openbb-mcp-server": "1.4.1"},
            "server_info": {"version": "1.4.1"},
            "tool_digest": "5" * 64,
            "schema_digest": "6" * 64,
            "route_map": route_map,
            "route_digest": service.stable_hash(route_map),
        }
    )
    assert service._runtime_status()[0] == "ready"
    path = service._compatibility_path()
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["package_metadata"][0]["license"] = "MIT"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert service._runtime_status()[0] == "drifted"


def test_cli_status_and_help_do_not_provision(openbb_workspace: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    root, _ = openbb_workspace
    data_sources(root, ["openbb", "status", "--json"])
    status = json.loads(capsys.readouterr().out)
    assert status["runtime"] == "missing"
    data_sources(root, ["openbb", "help"])
    assert "not installed during attach" in capsys.readouterr().out


def test_same_session_receipt_tampering_and_quarantine_never_retry_refresh(
    openbb_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = openbb_workspace
    service._write_compatibility_receipt(
        _valid_compatibility_payload(refresh_session_sha256="same-session")
    )
    path = service._compatibility_path()
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["package_metadata"][0]["license"] = "MIT"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    monkeypatch.setattr(service, "_refresh_session_hash", lambda: "same-session")

    def unexpected_refresh(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("a drifted or quarantined same-session receipt must not refresh")

    monkeypatch.setattr(service.subprocess, "run", unexpected_refresh)
    with pytest.raises(ValueError, match="receipt drifted"):
        service._ensure_openbb_compatibility(root, force_refresh=False)
    assert service._read_receipt(path)["status"] == "quarantined"
    with pytest.raises(ValueError, match="explicit provision"):
        service._ensure_openbb_compatibility(root, force_refresh=False)


def test_status_exposes_only_validated_receipt_hash_and_public_validator_is_exact(
    openbb_workspace: tuple[Path, Path],
) -> None:
    root, _ = openbb_workspace
    service._write_compatibility_receipt(_valid_compatibility_payload())
    stored = service._read_receipt(service._compatibility_path())
    receipt_hash = stored["receipt_hash"]
    status = service.get_data_source_status(root, {})
    assert status["runtime"] == "ready"
    assert status["compatibility_receipt"]["receipt_hash"] == receipt_hash
    assert service.validate_openbb_compatibility_receipt_hash(root, receipt_hash)[
        "receipt_hash"
    ] == receipt_hash
    with pytest.raises(ValueError, match="does not match"):
        service.validate_openbb_compatibility_receipt_hash(root, "0" * 64)


def test_keyless_requires_probe_and_access_reclassification_revokes_auto_use(
    openbb_workspace: tuple[Path, Path],
) -> None:
    root, _ = openbb_workspace
    service.configure_openbb_provider(root, {"provider": "sec", "access": "keyless"})
    status = service.enable_openbb_provider(root, {"provider": "sec", "data_kinds": ["filing"]})
    provider = status["providers"][0]
    assert provider["auto_use"] == "ask"
    assert provider["observed_access"] == "unprobed"
    with pytest.raises(PermissionError, match="successful probe"):
        service.enable_openbb_provider(
            root,
            {"provider": "sec", "data_kinds": ["filing"], "auto_use": "allow"},
        )

    state = service._read_state(root)
    state["openbb"]["providers"]["sec"]["observed_access"] = "callable"
    service._write_state(root, state)
    verified = service.enable_openbb_provider(
        root,
        {"provider": "sec", "data_kinds": ["filing"], "auto_use": "allow"},
    )
    assert verified["providers"][0]["auto_use"] == "allow"

    service.configure_openbb_provider(root, {"provider": "fmp", "access": "free"})
    service.enable_openbb_provider(root, {"provider": "fmp", "data_kinds": ["equity_price"]})
    reclassified = service.configure_openbb_provider(root, {"provider": "fmp", "access": "paid"})
    fmp = next(item for item in reclassified["providers"] if item["provider"] == "fmp")
    assert fmp["auto_use"] == "ask"
    assert fmp["observed_access"] == "unprobed"


def test_proxy_enforces_provider_specific_data_kind_scope(
    openbb_workspace: tuple[Path, Path],
) -> None:
    root, _ = openbb_workspace
    service.configure_openbb_provider(root, {"provider": "fred", "access": "free"})
    service.enable_openbb_provider(root, {"provider": "fred", "data_kinds": ["macro"]})
    service.configure_openbb_provider(root, {"provider": "fmp", "access": "free"})
    service.enable_openbb_provider(root, {"provider": "fmp", "data_kinds": ["equity_price"]})
    proxy = service._OpenBBProxy(root, "macro-analyst")
    tool_name = "equity_price_historical"
    proxy.discovered_tools.add(tool_name)
    proxy.activated_tools.add(tool_name)
    proxy.route_parameters[tool_name] = {"provider", "limit", "chart"}
    proxy.route_data_kinds[tool_name] = {"equity_price"}

    def request(provider: str, request_id: int) -> dict[str, Any] | None:
        return proxy._request_error(
            {
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"provider": provider, "limit": 1, "chart": False},
                },
            }
        )

    assert request("fred", 1) is not None
    assert request("fmp", 2) is None


def test_proxy_and_probe_fail_closed_on_unknown_unbounded_or_oversized_routes(
    openbb_workspace: tuple[Path, Path],
) -> None:
    root, _ = openbb_workspace
    _configure_and_enable(root, access="free")
    proxy = service._OpenBBProxy(root, "technical-analyst")
    unknown = proxy._request_error(
        {
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "equity_modify_alert",
                "arguments": {"provider": "fmp", "limit": 1, "chart": False},
            },
        }
    )
    assert unknown is not None

    tool_name = "equity_price_historical"
    proxy.discovered_tools.add(tool_name)
    proxy.activated_tools.add(tool_name)
    proxy.route_parameters[tool_name] = {"provider", "limit", "max_rows", "chart"}
    proxy.route_data_kinds[tool_name] = {"equity_price"}

    def request(arguments: dict[str, Any], request_id: int) -> dict[str, Any] | None:
        return proxy._request_error(
            {
                "id": request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
        )

    assert request({"provider": "fmp", "chart": False}, 2) is not None
    assert request({"provider": "fmp", "max_rows": 999, "chart": False}, 3) is not None
    assert request({"provider": "fmp", "limit": 1}, 4) is not None
    assert request({"provider": "fmp", "limit": 1, "chart": False}, 5) is None
    repeated = request({"provider": "fmp", "limit": 2, "chart": False}, 6)
    assert repeated is not None
    assert repeated["code"] == -32006

    oversized = proxy._sanitize_tool_response(
        {"jsonrpc": "2.0", "id": 7, "result": {"rows": [{"x": index} for index in range(121)]}}
    )
    assert "external_result_exceeds_row_limit" in json.dumps(oversized)

    unbounded_record = {
        "name": tool_name,
        "inputSchema": {
            "type": "object",
            "properties": {"provider": {"type": "string"}, "symbol": {"type": "string"}},
            "required": ["provider", "symbol"],
        },
    }
    assert service._probe_route(
        [unbounded_record],
        data_kind="equity_price",
        provider="fmp",
        symbol="AAPL",
        category="equity",
    ) is None


def test_disable_remains_restart_required_while_loaded_proxy_is_alive(
    openbb_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = openbb_workspace
    _configure_and_enable(root, access="free")
    service.write_openbb_projection_receipt(root, generated_at="one", command="python")
    service._write_loaded_receipt(root, "technical-analyst")
    assert service.get_data_source_status(root, {})["projection"] == "current"

    service.disable_openbb_provider(root, {"provider": "fmp"})
    service.write_openbb_projection_receipt(root, generated_at="two", command="python")
    disabled = service.get_data_source_status(root, {})
    assert disabled["projection"] == "restart_required"
    assert any("Fully quit and restart Codex" in action for action in disabled["recommended_actions"])

    monkeypatch.setattr(service, "_process_is_alive", lambda _process_id: False)
    restarted = service.get_data_source_status(root, {})
    assert restarted["projection"] == "absent"
    assert restarted["recommended_actions"] == []


def test_fresh_disabled_revision_zero_projection_is_absent_without_restart_action(
    openbb_workspace: tuple[Path, Path],
) -> None:
    root, _ = openbb_workspace
    receipt = service.write_openbb_projection_receipt(
        root,
        generated_at="fresh-attach",
        command="python",
    )

    assert receipt["configuration_revision"] == 0
    status = service.get_data_source_status(root, {})
    assert status["enabled"] is False
    assert status["projection"] == "absent"
    assert status["recommended_actions"] == []


def test_same_version_schema_drift_is_quarantined_after_one_refresh(
    openbb_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = openbb_workspace
    _configure_and_enable(root, access="free")
    scope_digest = service._compatibility_scope_digest(service._read_state(root))
    prior = _valid_compatibility_payload(
        refresh_session_sha256="prior-session",
        configuration_scope_digest=scope_digest,
    )
    service._write_compatibility_receipt(prior)
    calls = 0

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            argv,
            0,
            "--transport --allowed-categories --default-categories --no-tool-discovery",
            "",
        )

    monkeypatch.setattr(service, "_refresh_session_hash", lambda: "new-session")
    monkeypatch.setattr(service.subprocess, "run", fake_run)
    monkeypatch.setattr(service, "_package_metadata", lambda: prior["package_metadata"])
    monkeypatch.setattr(
        service,
        "_inspect_openbb_protocol",
        lambda _root, _versions: {
            "server_info": prior["server_info"],
            "tool_digest": prior["tool_digest"],
            "schema_digest": "9" * 64,
            "route_digest": prior["route_digest"],
            "route_categories": prior["route_categories"],
            "route_map": prior["route_map"],
            "route_map_truncated": False,
        },
    )
    with pytest.raises(ValueError, match="schema drifted"):
        service._ensure_openbb_compatibility(root, force_refresh=False)
    assert calls == 1
    quarantined = service._read_receipt(service._compatibility_path())
    assert quarantined["status"] == "quarantined"
    assert quarantined["failure_code"] == "same_version_compatibility_drift"
