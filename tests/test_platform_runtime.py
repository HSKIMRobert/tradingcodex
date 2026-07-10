from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from apps.mcp.services import _child_process_kwargs, _router_argv, _stdio_mcp_rpc
from tradingcodex_cli.generator import (
    bootstrap_workspace,
    copy_template_tree,
    render_template,
    serialized_template_context,
    templates_dir,
)
from tradingcodex_cli.service_autostart import _detached_process_kwargs
from tradingcodex_service.application.common import (
    atomic_write_text,
    exclusive_file_lock,
    safe_workspace_path,
    workspace_launcher_command,
)
from tradingcodex_service.application.runtime import RuntimeHomeConflictError


ROOT = Path(__file__).resolve().parents[1]


def _native_platform_home(monkeypatch: pytest.MonkeyPatch, user_home: Path) -> Path:
    monkeypatch.setenv("HOME", str(user_home))
    if os.name == "nt":
        local_app_data = user_home / "Local App Data"
        monkeypatch.setenv("USERPROFILE", str(user_home))
        monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
        return local_app_data / "TradingCodex"
    if sys.platform == "darwin":
        return user_home / "Library" / "Application Support" / "TradingCodex"
    xdg_data = user_home / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
    return xdg_data / "tradingcodex"


def _make_pre_source_workspace(monkeypatch: pytest.MonkeyPatch, workspace: Path, setup_home: Path) -> Path:
    monkeypatch.setenv("TRADINGCODEX_HOME", str(setup_home))
    monkeypatch.delenv("TRADINGCODEX_HOME_SOURCE", raising=False)
    monkeypatch.delenv("TRADINGCODEX_DB_NAME", raising=False)
    bootstrap_workspace(workspace)
    lock_path = workspace / ".tradingcodex" / "generated" / "module-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["tradingcodex_home"] = "~/.tradingcodex"
    lock.pop("home_source", None)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    (workspace / "tcx.cmd").unlink()
    return lock_path


def test_generated_workspace_serializes_spaces_and_package_metacharacters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "Workspace With Spaces"
    home = tmp_path / "Application Support" / "Trader's Home"
    package_spec = str(tmp_path / "Wheel Package & Cache" / "tradingcodex-1.0.0-py3-none-any.whl")
    monkeypatch.setenv("TRADINGCODEX_HOME", str(home))
    monkeypatch.delenv("TRADINGCODEX_HOME_SOURCE", raising=False)
    monkeypatch.delenv("TRADINGCODEX_DB_NAME", raising=False)
    monkeypatch.setenv("TRADINGCODEX_MCP_PACKAGE_SPEC", package_spec)

    bootstrap_workspace(workspace)
    configs = [workspace / ".codex" / "config.toml", *sorted((workspace / ".codex" / "agents").glob("*.toml"))]
    parsed = [tomllib.loads(path.read_text(encoding="utf-8")) for path in configs]
    assert len(parsed) == 11
    root_mcp = parsed[0]["mcp_servers"]["tradingcodex"]
    assert root_mcp["env"]["TRADINGCODEX_HOME"] == str(home.resolve())
    assert root_mcp["env"]["TRADINGCODEX_HOME_SOURCE"] == "environment_override"
    assert root_mcp["args"][2] == package_spec
    workspace_config = yaml.safe_load((workspace / ".tradingcodex" / "config.yaml").read_text(encoding="utf-8"))
    assert workspace_config["service"]["default_db"] == str(home.resolve() / "state" / "tradingcodex.sqlite3")
    hooks = json.loads((workspace / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    expected_hook = r".\tcx.cmd __hook session-start" if os.name == "nt" else "./tcx __hook session-start"
    assert hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"] == expected_hook
    module_lock = json.loads((workspace / ".tradingcodex" / "generated" / "module-lock.json").read_text(encoding="utf-8"))
    assert module_lock["tradingcodex_home"] == str(home.resolve())
    assert module_lock["home_source"] == "environment_override"
    assert (workspace / "tcx").is_file()
    assert (workspace / "tcx.cmd").is_file()
    assert b"\r\n" not in (workspace / "tcx").read_bytes()
    if os.name != "nt":
        assert os.access(workspace / "tcx", os.X_OK)


def test_windows_drive_paths_render_as_valid_toml_yaml_json(tmp_path: Path) -> None:
    raw = {
        "PROJECT_NAME": "portable-test",
        "WORKSPACE_ID": "tcxw_portable",
        "GENERATED_AT": "2026-01-01T00:00:00Z",
        "TRADINGCODEX_VERSION": "1.0.0",
        "TRADINGCODEX_MCP_PACKAGE_SPEC": r"C:\Wheel Package\tradingcodex-1.0.0-py3-none-any.whl",
        "TRADINGCODEX_HOME": r"C:\Users\Ada Lovelace\AppData\Local\TradingCodex",
        "TRADINGCODEX_HOME_SOURCE": "platform_default",
        "TRADINGCODEX_DB_PATH": r"C:\Users\Ada Lovelace\AppData\Local\TradingCodex\state\tradingcodex.sqlite3",
        "TRADINGCODEX_DB_SOURCE": "home_default",
        "TRADINGCODEX_SERVICE_ADDR": "127.0.0.1:48267",
        "TRADINGCODEX_HOOK_COMMAND": r".\tcx.cmd __hook",
        "TRADINGCODEX_WORKSPACE_LAUNCHER": r".\tcx.cmd",
    }
    context = serialized_template_context(raw)
    for module in ("codex-base", "fixed-subagents", "repo-skills"):
        copy_template_tree(templates_dir() / "modules" / module / "files", tmp_path, context)
    configs = [tmp_path / ".codex" / "config.toml", *sorted((tmp_path / ".codex" / "agents").glob("*.toml"))]
    parsed = [tomllib.loads(path.read_text(encoding="utf-8")) for path in configs]
    assert parsed[0]["mcp_servers"]["tradingcodex"]["env"]["TRADINGCODEX_HOME"] == raw["TRADINGCODEX_HOME"]
    assert yaml.safe_load((tmp_path / ".tradingcodex" / "config.yaml").read_text(encoding="utf-8"))["service"]["default_db"] == raw["TRADINGCODEX_DB_PATH"]
    assert json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"] == r".\tcx.cmd __hook stop"
    rendered_agent_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            tmp_path / ".codex" / "prompts" / "base_instructions" / "head-manager.md",
            *sorted((tmp_path / ".agents" / "skills").glob("*/SKILL.md")),
        ]
    )
    assert r".\tcx.cmd" in rendered_agent_text
    assert "./tcx" not in rendered_agent_text


def test_template_rendering_is_single_pass_and_cmd_values_are_quoted() -> None:
    assert render_template("value={{X}}", {"X": "{{Y}}", "Y": "rewritten"}) == "value={{Y}}"
    context = serialized_template_context({"X": "foo&bar|baz^qux%TEMP%"})
    assert context["X_CMD"].startswith('"') and context["X_CMD"].endswith('"')
    assert "foo&bar|baz^qux%%TEMP%%" in context["X_CMD_SET"]
    assert workspace_launcher_command("win32") == r".\tcx.cmd"


def test_explicit_db_override_is_projected_into_launchers_and_mcp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "db-override-workspace"
    home = tmp_path / "home"
    db_path = tmp_path / "Custom Database" / "ledger.sqlite3"
    monkeypatch.setenv("TRADINGCODEX_HOME", str(home))
    monkeypatch.setenv("TRADINGCODEX_DB_NAME", str(db_path))
    bootstrap_workspace(workspace)
    lock = json.loads((workspace / ".tradingcodex" / "generated" / "module-lock.json").read_text(encoding="utf-8"))
    assert lock["tradingcodex_db_path"] == str(db_path.resolve())
    assert lock["db_source"] == "environment_override"
    configs = [workspace / ".codex" / "config.toml", *sorted((workspace / ".codex" / "agents").glob("*.toml"))]
    for path in configs:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        assert config["mcp_servers"]["tradingcodex"]["env"]["TRADINGCODEX_DB_NAME"] == str(db_path.resolve())

    env = {**os.environ, "PYTHONPATH": str(ROOT), "TRADINGCODEX_PYTHON": sys.executable}
    env.pop("TRADINGCODEX_HOME", None)
    env.pop("TRADINGCODEX_HOME_SOURCE", None)
    env.pop("TRADINGCODEX_DB_NAME", None)
    status = subprocess.run(
        [str(workspace / "tcx"), "db", "status"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(status.stdout)
    assert payload["db_path"] == str(db_path.resolve())
    assert payload["db_source"] == "environment_override"
    assert db_path.exists()
    assert not (home / "state" / "tradingcodex.sqlite3").exists()


def test_doctor_does_not_open_a_mismatched_projected_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    generated_home = tmp_path / "generated-home"
    other_home = tmp_path / "other-home"
    monkeypatch.setenv("TRADINGCODEX_HOME", str(generated_home))
    monkeypatch.delenv("TRADINGCODEX_DB_NAME", raising=False)
    bootstrap_workspace(workspace)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "TRADINGCODEX_HOME": str(other_home)}
    env.pop("TRADINGCODEX_HOME_SOURCE", None)
    env.pop("TRADINGCODEX_DB_NAME", None)
    for layer in ("service", "guidance", "improvement"):
        result = subprocess.run(
            [sys.executable, "-m", "tradingcodex_cli", "doctor", "--layer", layer],
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 1
        assert "generated home/DB projection matches runtime" in result.stdout
    assert not (other_home / "state" / "tradingcodex.sqlite3").exists()


def test_bootstrap_fails_before_writing_when_global_homes_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_home = tmp_path / "user"
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.delenv("TRADINGCODEX_HOME", raising=False)
    monkeypatch.delenv("TRADINGCODEX_HOME_SOURCE", raising=False)
    monkeypatch.delenv("TRADINGCODEX_DB_NAME", raising=False)
    if sys.platform == "darwin":
        platform_home = user_home / "Library" / "Application Support" / "TradingCodex"
    elif os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(user_home))
        monkeypatch.setenv("LOCALAPPDATA", str(user_home / "Local App Data"))
        platform_home = user_home / "Local App Data" / "TradingCodex"
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(user_home / "xdg-data"))
        platform_home = user_home / "xdg-data" / "tradingcodex"
    legacy = user_home / ".tradingcodex"
    platform_home.mkdir(parents=True)
    legacy.mkdir(parents=True)
    (platform_home / "state").write_text("new", encoding="utf-8")
    (legacy / "state").write_text("old", encoding="utf-8")
    target = tmp_path / "must-not-exist"
    with pytest.raises(Exception, match="Both the platform-default and legacy"):
        bootstrap_workspace(target)
    assert not target.exists()


def test_pre_source_workspace_update_recovers_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "old-workspace"
    lock_path = _make_pre_source_workspace(monkeypatch, workspace, tmp_path / "setup-home")
    user_home = tmp_path / "user"
    _native_platform_home(monkeypatch, user_home)
    legacy_home = user_home / ".tradingcodex"
    legacy_home.mkdir(parents=True)
    (legacy_home / "legacy-ledger.marker").write_text("legacy", encoding="utf-8")
    monkeypatch.setenv("TRADINGCODEX_HOME", str(legacy_home))
    monkeypatch.delenv("TRADINGCODEX_HOME_SOURCE", raising=False)

    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("TRADINGCODEX_HOME_SOURCE", None)
    env.pop("TRADINGCODEX_DB_NAME", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tradingcodex_cli",
            "update",
            str(workspace),
            "--no-doctor",
            "--skip-refresh",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr

    updated = json.loads(lock_path.read_text(encoding="utf-8"))
    assert updated["tradingcodex_home"] == str(legacy_home.resolve())
    assert updated["home_source"] == "legacy_fallback"
    assert (workspace / "tcx.cmd").is_file()


def test_pre_source_workspace_update_refuses_split_ledgers_before_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "old-workspace"
    lock_path = _make_pre_source_workspace(monkeypatch, workspace, tmp_path / "setup-home")
    user_home = tmp_path / "user"
    platform_home = _native_platform_home(monkeypatch, user_home)
    legacy_home = user_home / ".tradingcodex"
    for home, marker in ((platform_home, "platform"), (legacy_home, "legacy")):
        home.mkdir(parents=True)
        (home / f"{marker}.marker").write_text(marker, encoding="utf-8")
    monkeypatch.setenv("TRADINGCODEX_HOME", str(legacy_home))
    monkeypatch.delenv("TRADINGCODEX_HOME_SOURCE", raising=False)
    original_lock = lock_path.read_bytes()

    with pytest.raises(RuntimeHomeConflictError, match="Both the platform-default and legacy"):
        bootstrap_workspace(workspace, force=True)

    assert lock_path.read_bytes() == original_lock
    assert not (workspace / "tcx.cmd").exists()


def test_pre_source_workspace_with_nonlegacy_override_stays_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "old-workspace"
    lock_path = _make_pre_source_workspace(monkeypatch, workspace, tmp_path / "setup-home")
    _native_platform_home(monkeypatch, tmp_path / "user")
    selected = tmp_path / "explicit-home"
    monkeypatch.setenv("TRADINGCODEX_HOME", str(selected))
    monkeypatch.delenv("TRADINGCODEX_HOME_SOURCE", raising=False)

    bootstrap_workspace(workspace, force=True)

    updated = json.loads(lock_path.read_text(encoding="utf-8"))
    assert updated["tradingcodex_home"] == str(selected.resolve())
    assert updated["home_source"] == "environment_override"


def test_native_process_kwargs_and_external_mcp_pipe_reader() -> None:
    assert _detached_process_kwargs("posix") == {"start_new_session": True}
    assert "creationflags" in _detached_process_kwargs("nt")
    assert _child_process_kwargs("posix") == {"start_new_session": True}
    assert "creationflags" in _child_process_kwargs("nt")

    server = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request.get('method')
    result = {'protocolVersion':'2025-03-26','serverInfo':{'name':'fixture','version':'1'}} if method == 'initialize' else {'tools':[]}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}), flush=True)
"""
    router = SimpleNamespace(
        name="portable-fixture",
        command=sys.executable,
        args=["-u", "-c", server],
        env={},
        credential_ref="",
    )
    responses = _stdio_mcp_rpc(router, ["initialize", "tools/list"], timeout=5)
    assert responses["initialize"]["result"]["serverInfo"]["name"] == "fixture"
    assert responses["tools/list"]["result"]["tools"] == []

    exit_server = """
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'tools':[]}}), flush=True)
"""
    exit_router = SimpleNamespace(
        name="exiting-fixture",
        command=sys.executable,
        args=["-u", "-c", exit_server],
        env={},
        credential_ref="",
    )
    assert _stdio_mcp_rpc(exit_router, ["tools/list"], timeout=5)["tools/list"]["result"] == {"tools": []}


def test_windows_external_mcp_batch_files_fail_closed(tmp_path: Path) -> None:
    batch = tmp_path / "npx.cmd"
    batch.write_text("@echo off\r\n", encoding="utf-8")
    router = SimpleNamespace(command=str(batch), args=[], env={}, credential_ref="")
    with pytest.raises(ValueError, match="batch files"):
        _router_argv(router, platform_name="nt")
    args_router = SimpleNamespace(command="", args=[str(batch)], env={}, credential_ref="")
    with pytest.raises(ValueError, match="batch files"):
        _router_argv(args_router, platform_name="nt")


def test_native_lock_atomic_write_and_portable_workspace_paths(tmp_path: Path) -> None:
    lock_target = tmp_path / "state" / "ledger"
    entered = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with exclusive_file_lock(lock_target, timeout_seconds=2):
            entered.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=hold_lock)
    thread.start()
    assert entered.wait(timeout=2)
    with pytest.raises(TimeoutError):
        with exclusive_file_lock(lock_target, timeout_seconds=0.1):
            pass
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()

    text_path = tmp_path / "atomic" / "note.txt"
    atomic_write_text(text_path, "one\ntwo\n")
    assert text_path.read_bytes() == b"one\ntwo\n"
    for unsafe in ("trading/research/CON.md", "trading/research/note.md:stream", "trading/research/trailing. "):
        with pytest.raises(ValueError):
            safe_workspace_path(tmp_path, unsafe)
