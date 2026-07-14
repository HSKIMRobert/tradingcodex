from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from tradingcodex_cli.versioning import version_less_than
from tradingcodex_service.application.common import canonical_path_identity, paths_equivalent
from tradingcodex_service.application.runtime import (
    RuntimeHomeResolutionError,
    resolve_tradingcodex_home,
    tradingcodex_db_path,
)


def test_release_version_order_handles_pep_440_prereleases() -> None:
    from tradingcodex_cli import service_autostart, startup_status

    ordered = ["1.1.0.dev1", "1.1.0a1", "1.1.0a2", "1.1.0b1", "1.1.0rc1", "1.1.0", "1.1.0.post1"]
    assert all(version_less_than(left, right) for left, right in zip(ordered, ordered[1:]))
    assert not version_less_than("1.1.0", "1.1.0rc1")
    with pytest.raises(ValueError):
        version_less_than("not-a-version", "1.1.0")
    assert startup_status.version_less_than is version_less_than
    assert service_autostart._version_less_than is version_less_than


def test_platform_default_home_paths_are_pure_and_side_effect_free(tmp_path: Path) -> None:
    mac_home = tmp_path / "mac-user"
    mac = resolve_tradingcodex_home(
        environ={"HOME": str(mac_home)},
        platform_name="darwin",
    )
    assert mac.home == (mac_home / "Library" / "Application Support" / "TradingCodex").resolve()
    assert mac.home_source == "platform_default"
    assert not mac_home.exists()

    linux_home = tmp_path / "linux-user"
    linux = resolve_tradingcodex_home(
        environ={"HOME": str(linux_home)},
        platform_name="linux",
    )
    assert linux.home == (linux_home / ".local" / "share" / "tradingcodex").resolve()

    xdg = tmp_path / "XDG Data With Spaces"
    linux_xdg = resolve_tradingcodex_home(
        environ={"HOME": str(linux_home), "XDG_DATA_HOME": str(xdg)},
        platform_name="linux",
    )
    assert linux_xdg.home == (xdg / "tradingcodex").resolve()

    windows = resolve_tradingcodex_home(
        environ={
            "USERPROFILE": r"C:\Users\Ada Lovelace",
            "LOCALAPPDATA": r"C:\Users\Ada Lovelace\AppData\Local",
        },
        platform_name="win32",
    )
    assert windows.home == PureWindowsPath(r"C:\Users\Ada Lovelace\AppData\Local\TradingCodex")
    assert windows.home_source == "platform_default"


def test_windows_default_requires_localappdata() -> None:
    with pytest.raises(RuntimeHomeResolutionError, match="LOCALAPPDATA"):
        resolve_tradingcodex_home(
            environ={"USERPROFILE": r"C:\Users\Ada"},
            platform_name="win32",
        )
    override = resolve_tradingcodex_home(
        environ={"USERPROFILE": r"C:\Users\Ada", "TRADINGCODEX_HOME": r"D:\Trading State"},
        platform_name="win32",
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
    )
    assert resolution.home_source == "platform_default"


def test_mismatched_generated_source_hint_fails_closed() -> None:
    env = {
        "USERPROFILE": r"C:\Users\Ada",
        "LOCALAPPDATA": r"C:\Users\Ada\AppData\Local",
        "TRADINGCODEX_HOME": r"D:\Copied Workspace\TradingCodex",
        "TRADINGCODEX_HOME_SOURCE": "platform_default",
    }
    with pytest.raises(RuntimeHomeResolutionError, match="does not match"):
        resolve_tradingcodex_home(environ=env, platform_name="win32")


def test_explicit_home_override_is_authoritative(tmp_path: Path) -> None:
    selected = tmp_path / "explicit home"
    resolution = resolve_tradingcodex_home(
        environ={"HOME": str(tmp_path), "TRADINGCODEX_HOME": str(selected)},
        platform_name="darwin",
    )
    assert resolution.home == selected.resolve()
    assert resolution.home_source == "environment_override"


def test_runtime_home_inside_workspace_fails_closed_across_native_and_windows_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    with pytest.raises(RuntimeHomeResolutionError, match="must be outside"):
        resolve_tradingcodex_home(
            environ={
                "HOME": str(tmp_path),
                "TRADINGCODEX_HOME": str(workspace / ".tradingcodex-home"),
                "TRADINGCODEX_WORKSPACE_ROOT": str(workspace),
            },
            platform_name="darwin",
        )

    with pytest.raises(RuntimeHomeResolutionError, match="must be outside"):
        resolve_tradingcodex_home(
            environ={
                "USERPROFILE": r"C:\Users\Ada",
                "LOCALAPPDATA": r"C:\Users\Ada\AppData\Local",
                "TRADINGCODEX_HOME": r"c:\work\portfolio\.tradingcodex-home",
                "TRADINGCODEX_WORKSPACE_ROOT": r"C:\Work\Portfolio",
            },
            platform_name="win32",
        )


def test_pre_v1_home_is_ignored_without_an_explicit_override(tmp_path: Path) -> None:
    pre_v1_home = tmp_path / ".tradingcodex"
    pre_v1_home.mkdir()
    (pre_v1_home / "state.sqlite3").write_text("pre-v1", encoding="utf-8")
    platform_home = tmp_path / "Library" / "Application Support" / "TradingCodex"
    resolution = resolve_tradingcodex_home(environ={"HOME": str(tmp_path)}, platform_name="darwin")
    assert resolution.home == platform_home.resolve()
    assert resolution.home_source == "platform_default"
    assert pre_v1_home.exists()
    assert not platform_home.exists()


def test_pre_v1_home_source_hint_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuntimeHomeResolutionError, match="unsupported"):
        resolve_tradingcodex_home(
            environ={
                "HOME": str(tmp_path),
                "TRADINGCODEX_HOME": str(tmp_path / ".tradingcodex"),
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
