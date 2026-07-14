from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tradingcodex_cli import service_autostart
from tradingcodex_cli.commands.mode import mode
from tradingcodex_service.application.runtime_mode import get_runtime_mode_status, set_runtime_mode
from tradingcodex_service.runtime_profile import (
    assert_service_binding_allowed,
    is_loopback_host,
    remote_configuration_errors,
)


def remote_env() -> dict[str, str]:
    return {
        "TRADINGCODEX_SERVICE_PROFILE": "remote",
        "TRADINGCODEX_DEBUG": "0",
        "TRADINGCODEX_SECRET_KEY": "django-secret-key-that-is-long-and-random-123",
        "TRADINGCODEX_API_KEY": "api-key-that-is-distinct-and-long-enough-456",
        "TRADINGCODEX_API_PRINCIPAL": "remote-operator",
        "TRADINGCODEX_ALLOWED_HOSTS": "trading.example.com",
        "TRADINGCODEX_CSRF_TRUSTED_ORIGINS": "https://trading.example.com",
        "TRADINGCODEX_TRANSPORT_SECURITY": "reverse-proxy",
    }


@pytest.mark.parametrize("host", ["localhost", "localhost.", "127.0.0.1", "127.12.34.56", "::1", "[::1]"])
def test_loopback_host_detection(host: str) -> None:
    assert is_loopback_host(host) is True


def test_local_profile_is_allowed_only_on_loopback() -> None:
    assert_service_binding_allowed("127.0.0.1:48267", {})

    with pytest.raises(RuntimeError, match="Refusing non-loopback") as exc_info:
        assert_service_binding_allowed("0.0.0.0:48267", {})

    message = str(exc_info.value)
    assert "TRADINGCODEX_SERVICE_PROFILE=remote" in message
    assert "TRADINGCODEX_DEBUG=0" in message
    assert "authenticated mutations" in message
    assert "TRADINGCODEX_TRANSPORT_SECURITY=reverse-proxy" in message


def test_complete_remote_profile_allows_non_loopback_binding() -> None:
    env = remote_env()
    assert remote_configuration_errors(env) == []
    assert_service_binding_allowed("0.0.0.0:48267", env)


def test_incomplete_remote_profile_is_rejected_even_on_loopback() -> None:
    with pytest.raises(RuntimeError, match="Invalid TradingCodex remote profile"):
        assert_service_binding_allowed("127.0.0.1:48267", {"TRADINGCODEX_SERVICE_PROFILE": "remote"})


def test_remote_profile_rejects_wildcard_hosts_and_insecure_origins() -> None:
    env = remote_env()
    env["TRADINGCODEX_ALLOWED_HOSTS"] = "*"
    env["TRADINGCODEX_CSRF_TRUSTED_ORIGINS"] = "http://trading.example.com"

    errors = remote_configuration_errors(env)

    assert any("ALLOWED_HOSTS" in error for error in errors)
    assert any("HTTPS" in error for error in errors)


def test_service_entrypoint_refuses_insecure_non_loopback_before_socket_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in remote_env():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRADINGCODEX_SERVICE_PROFILE", "local")
    socket_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        service_autostart,
        "_tcp_open",
        lambda host, port: socket_calls.append((host, port)) or False,
    )

    with pytest.raises(RuntimeError, match="Refusing non-loopback"):
        service_autostart.ensure_service_up(tmp_path, addr="0.0.0.0:48267")

    assert socket_calls == []


def test_remote_settings_enable_django_transport_security(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(remote_env())
    env["TRADINGCODEX_HOME"] = str(tmp_path / "home")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from tradingcodex_service import settings as s; "
                "assert s.SERVICE_PROFILE == 'remote'; "
                "assert s.DEBUG is False; "
                "assert s.SECURE_SSL_REDIRECT is True; "
                "assert s.SESSION_COOKIE_SECURE is True; "
                "assert s.CSRF_COOKIE_SECURE is True; "
                "assert s.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https')"
            ),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_retired_persistent_mode_is_inert_and_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy = tmp_path / ".tradingcodex/runtime/mode.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{not valid json", encoding="utf-8")
    original = legacy.read_bytes()
    monkeypatch.setenv("TRADINGCODEX_CODEX_PERMISSION", "unrestricted")

    mode(tmp_path, ["status"])

    output = capsys.readouterr().out
    assert "TradingCodex persistent mode command: compatibility status only" in output
    assert "Build enabled" not in output
    assert "exact `$tcx-build`" in output
    assert "(ignored)" in output
    status = get_runtime_mode_status(tmp_path, full_access_detected=True)
    assert status["status"] == "retired"
    assert status["authority"] == "none"
    assert status["build_enabled"] is False
    assert status["full_access_required"] is False
    assert status["permission_is_advisory"] is True
    assert status["full_access_detected"] is True
    assert status["legacy_mode_file_present"] is True
    assert status["legacy_mode_file_ignored"] is True
    assert legacy.read_bytes() == original

    with pytest.raises(ValueError, match="Persistent TradingCodex build mode is retired"):
        mode(tmp_path, ["set", "build", "--reason", "test"])
    assert legacy.read_bytes() == original

    unused_root = tmp_path / "unused"
    with pytest.raises(ValueError, match="Persistent TradingCodex build mode is retired"):
        set_runtime_mode(unused_root, "build", reason="test")
    assert not (unused_root / ".tradingcodex/runtime/mode.json").exists()


def test_retired_persistent_mode_never_reads_or_follows_a_legacy_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    legacy = tmp_path / ".tradingcodex/runtime/mode.json"
    legacy.parent.mkdir(parents=True)
    outside = tmp_path / "outside-mode-target"
    outside.mkdir()
    marker = outside / "marker.txt"
    marker.write_text("must remain untouched", encoding="utf-8")
    try:
        legacy.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    real_readlink = os.readlink

    def guarded_readlink(path: os.PathLike[str] | str, *args: object, **kwargs: object) -> str:
        if Path(path) == legacy:
            raise AssertionError("retired mode status followed the legacy mode symlink")
        return real_readlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "readlink", guarded_readlink)

    status = get_runtime_mode_status(tmp_path, full_access_detected=True)

    assert status["status"] == "retired"
    assert status["build_enabled"] is False
    assert status["legacy_mode_file_present"] is True
    assert status["legacy_mode_file_ignored"] is True
    assert legacy.is_symlink()
    with pytest.raises(ValueError, match="Persistent TradingCodex build mode is retired"):
        set_runtime_mode(tmp_path, "build")
    assert marker.read_text(encoding="utf-8") == "must remain untouched"
