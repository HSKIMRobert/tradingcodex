from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

from tradingcodex_service.application.common import canonical_path_identity, paths_equivalent
from tradingcodex_service.application.runtime import (
    RuntimeHomeConflictError,
    RuntimeHomeResolutionError,
    resolve_tradingcodex_home,
    tradingcodex_db_path,
)


ROOT = Path(__file__).resolve().parents[1]


def test_platform_default_home_paths_are_pure_and_side_effect_free(tmp_path: Path) -> None:
    mac_home = tmp_path / "mac-user"
    mac = resolve_tradingcodex_home(
        environ={"HOME": str(mac_home)},
        platform_name="darwin",
        populated=lambda path: False,
    )
    assert mac.home == (mac_home / "Library" / "Application Support" / "TradingCodex").resolve()
    assert mac.home_source == "platform_default"
    assert not mac_home.exists()

    linux_home = tmp_path / "linux-user"
    linux = resolve_tradingcodex_home(
        environ={"HOME": str(linux_home)},
        platform_name="linux",
        populated=lambda path: False,
    )
    assert linux.home == (linux_home / ".local" / "share" / "tradingcodex").resolve()

    xdg = tmp_path / "XDG Data With Spaces"
    linux_xdg = resolve_tradingcodex_home(
        environ={"HOME": str(linux_home), "XDG_DATA_HOME": str(xdg)},
        platform_name="linux",
        populated=lambda path: False,
    )
    assert linux_xdg.home == (xdg / "tradingcodex").resolve()

    windows = resolve_tradingcodex_home(
        environ={
            "USERPROFILE": r"C:\Users\Ada Lovelace",
            "LOCALAPPDATA": r"C:\Users\Ada Lovelace\AppData\Local",
        },
        platform_name="win32",
        populated=lambda path: False,
    )
    assert windows.home == PureWindowsPath(r"C:\Users\Ada Lovelace\AppData\Local\TradingCodex")
    assert windows.home_source == "platform_default"


def test_windows_default_requires_localappdata() -> None:
    with pytest.raises(RuntimeHomeResolutionError, match="LOCALAPPDATA"):
        resolve_tradingcodex_home(
            environ={"USERPROFILE": r"C:\Users\Ada"},
            platform_name="win32",
            populated=lambda path: False,
        )
    override = resolve_tradingcodex_home(
        environ={"USERPROFILE": r"C:\Users\Ada", "TRADINGCODEX_HOME": r"D:\Trading State"},
        platform_name="win32",
        populated=lambda path: True,
    )
    assert override.home == PureWindowsPath(r"D:\Trading State")
    assert override.home_source == "environment_override"


def test_windows_source_hint_uses_windows_case_identity() -> None:
    resolution = resolve_tradingcodex_home(
        environ={
            "USERPROFILE": r"C:\Users\Ada",
            "LOCALAPPDATA": r"C:\Users\Ada\AppData\Local",
            "TRADINGCODEX_HOME": r"c:\users\ada\appdata\local\tradingcodex",
            "TRADINGCODEX_HOME_SOURCE": "platform_default",
        },
        platform_name="win32",
        populated=lambda path: False,
    )
    assert resolution.home_source == "platform_default"


def test_mismatched_generated_source_hint_fails_closed() -> None:
    env = {
        "USERPROFILE": r"C:\Users\Ada",
        "LOCALAPPDATA": r"C:\Users\Ada\AppData\Local",
        "TRADINGCODEX_HOME": r"D:\Copied Workspace\TradingCodex",
        "TRADINGCODEX_HOME_SOURCE": "platform_default",
    }
    with pytest.raises(RuntimeHomeConflictError, match="does not match"):
        resolve_tradingcodex_home(environ=env, platform_name="win32", populated=lambda path: False)
    status = resolve_tradingcodex_home(
        environ=env,
        platform_name="win32",
        populated=lambda path: False,
        strict=False,
    )
    assert status.conflict and status.home is None


def test_explicit_home_wins_even_when_both_candidates_are_populated(tmp_path: Path) -> None:
    selected = tmp_path / "explicit home"
    resolution = resolve_tradingcodex_home(
        environ={"HOME": str(tmp_path), "TRADINGCODEX_HOME": str(selected)},
        platform_name="darwin",
        populated=lambda path: True,
    )
    assert resolution.home == selected.resolve()
    assert resolution.home_source == "environment_override"
    assert not resolution.conflict


def test_legacy_only_fallback_and_both_populated_conflict(tmp_path: Path) -> None:
    legacy = tmp_path / ".tradingcodex"
    legacy.mkdir()
    (legacy / "state.sqlite3").write_text("legacy", encoding="utf-8")
    resolution = resolve_tradingcodex_home(environ={"HOME": str(tmp_path)}, platform_name="darwin")
    assert resolution.home == legacy.resolve()
    assert resolution.home_source == "legacy_fallback"

    platform_home = tmp_path / "Library" / "Application Support" / "TradingCodex"
    platform_home.mkdir(parents=True)
    (platform_home / "preferences.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeHomeConflictError):
        resolve_tradingcodex_home(environ={"HOME": str(tmp_path)}, platform_name="darwin")
    diagnostic = resolve_tradingcodex_home(environ={"HOME": str(tmp_path)}, platform_name="darwin", strict=False)
    assert diagnostic.conflict
    assert diagnostic.home is None
    assert diagnostic.home_source is None


def test_empty_home_directories_are_not_treated_as_populated(tmp_path: Path) -> None:
    (tmp_path / ".tradingcodex" / "state").mkdir(parents=True)
    resolution = resolve_tradingcodex_home(environ={"HOME": str(tmp_path)}, platform_name="darwin")
    assert resolution.home_source == "platform_default"
    assert resolution.legacy_home_populated is False


def test_same_target_symlink_does_not_create_false_split_ledger(tmp_path: Path) -> None:
    legacy = tmp_path / ".tradingcodex"
    legacy.mkdir()
    (legacy / "state").write_text("state", encoding="utf-8")
    default_parent = tmp_path / "Library" / "Application Support"
    default_parent.mkdir(parents=True)
    (default_parent / "TradingCodex").symlink_to(legacy, target_is_directory=True)
    resolution = resolve_tradingcodex_home(environ={"HOME": str(tmp_path)}, platform_name="darwin")
    assert not resolution.conflict
    assert resolution.home_source == "platform_default"
    assert resolution.home == legacy.resolve()


def test_stale_generated_home_hint_fails_closed(tmp_path: Path) -> None:
    platform_home = tmp_path / "Library" / "Application Support" / "TradingCodex"
    platform_home.mkdir(parents=True)
    (platform_home / "state").write_text("new", encoding="utf-8")
    legacy = tmp_path / ".tradingcodex"
    with pytest.raises(RuntimeHomeConflictError, match="projection"):
        resolve_tradingcodex_home(
            environ={
                "HOME": str(tmp_path),
                "TRADINGCODEX_HOME": str(legacy),
                "TRADINGCODEX_HOME_SOURCE": "legacy_fallback",
            },
            platform_name="darwin",
        )


def test_db_override_remains_independent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    db = tmp_path / "Database With Spaces" / "ledger.sqlite3"
    monkeypatch.setenv("TRADINGCODEX_HOME", str(home))
    monkeypatch.setenv("TRADINGCODEX_DB_NAME", str(db))
    assert tradingcodex_db_path() == db.resolve()


def test_home_cli_reports_and_checks_split_ledger_without_creating_db(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "HOME": str(tmp_path)}
    env.pop("TRADINGCODEX_HOME", None)
    env.pop("TRADINGCODEX_HOME_SOURCE", None)
    env.pop("TRADINGCODEX_DB_NAME", None)
    setup_env = {**env, "TRADINGCODEX_HOME": str(tmp_path / "setup-home")}
    workspace = tmp_path / "workspace"
    subprocess.run(
        [sys.executable, "-m", "tradingcodex_cli", "attach", str(workspace)],
        cwd=ROOT,
        env=setup_env,
        text=True,
        capture_output=True,
        check=True,
    )
    if sys.platform == "darwin":
        platform_home = tmp_path / "Library" / "Application Support" / "TradingCodex"
    elif os.name == "nt":
        env["USERPROFILE"] = str(tmp_path)
        env["LOCALAPPDATA"] = str(tmp_path / "Local App Data")
        platform_home = Path(env["LOCALAPPDATA"]) / "TradingCodex"
    else:
        env["XDG_DATA_HOME"] = str(tmp_path / "xdg-data")
        platform_home = Path(env["XDG_DATA_HOME"]) / "tradingcodex"
    legacy = tmp_path / ".tradingcodex"
    platform_home.mkdir(parents=True)
    legacy.mkdir(parents=True)
    (platform_home / "state-marker").write_text("new", encoding="utf-8")
    (legacy / "state-marker").write_text("old", encoding="utf-8")

    status = subprocess.run(
        [sys.executable, "-m", "tradingcodex_cli", "home", "status", "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(status.stdout)
    assert payload["status"] == "conflict"
    assert payload["home"] is None
    assert payload["automatic_home_migration"] is False
    checked = subprocess.run(
        [sys.executable, "-m", "tradingcodex_cli", "home", "check", "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert checked.returncode == 1
    db_status = subprocess.run(
        [sys.executable, "-m", "tradingcodex_cli", "db", "status"],
        cwd=workspace,
        env=env,
        text=True,
        capture_output=True,
    )
    assert db_status.returncode == 1
    assert json.loads(db_status.stdout)["home_conflict"] is True
    for layer in ("service", "codex-native", "improvement"):
        doctor = subprocess.run(
            [sys.executable, "-m", "tradingcodex_cli", "doctor", "--layer", layer],
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
        )
        assert doctor.returncode == 1
        assert "global home selection" in doctor.stdout
        assert "platform=" in doctor.stdout and "legacy=" in doctor.stdout
    assert not (platform_home / "state" / "tradingcodex.sqlite3").exists()
    assert not (legacy / "state" / "tradingcodex.sqlite3").exists()


def test_path_identity_normalizes_symlinks_and_windows_case(tmp_path: Path) -> None:
    real = tmp_path / "private" / "state.sqlite3"
    real.parent.mkdir()
    real.write_text("db", encoding="utf-8")
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(real)
    assert paths_equivalent(real, alias)
    assert canonical_path_identity(alias) == canonical_path_identity(real)
    assert paths_equivalent(
        r"C:\Users\ADA\AppData\Local\TradingCodex\state\ledger.sqlite3",
        r"c:\users\ada\appdata\local\tradingcodex\state\ledger.sqlite3",
        platform_name="win32",
    )
