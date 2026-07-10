from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from urllib.parse import urlsplit


LOCAL_PROFILE = "local"
REMOTE_PROFILE = "remote"
DEFAULT_LOCAL_SECRET_KEY = "tradingcodex-local-dev-key"
SUPPORTED_TRANSPORT_SECURITY = "reverse-proxy"


def service_profile(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    profile = str(env.get("TRADINGCODEX_SERVICE_PROFILE", LOCAL_PROFILE)).strip().lower()
    if profile not in {LOCAL_PROFILE, REMOTE_PROFILE}:
        raise RuntimeError("TRADINGCODEX_SERVICE_PROFILE must be 'local' or 'remote'")
    return profile


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]").rstrip(".")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def assert_service_binding_allowed(addr: str, environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    host = _address_host(addr)
    profile = service_profile(env)
    if is_loopback_host(host) and profile == LOCAL_PROFILE:
        return
    errors = remote_configuration_errors(env)
    if errors:
        context = (
            f"Refusing non-loopback TradingCodex binding on {host}"
            if not is_loopback_host(host)
            else "Invalid TradingCodex remote profile"
        )
        raise RuntimeError(
            context + ": " + "; ".join(errors)
        )


def assert_runtime_profile_configured(environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    if service_profile(env) != REMOTE_PROFILE:
        return
    errors = remote_configuration_errors(env)
    if errors:
        raise RuntimeError("Invalid TradingCodex remote profile: " + "; ".join(errors))


def remote_configuration_errors(environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    errors: list[str] = []
    try:
        profile = service_profile(env)
    except RuntimeError as exc:
        return [str(exc)]
    if profile != REMOTE_PROFILE:
        errors.append("set TRADINGCODEX_SERVICE_PROFILE=remote")

    if _env_bool(env, "TRADINGCODEX_DEBUG", default=True):
        errors.append("set TRADINGCODEX_DEBUG=0")

    secret = str(env.get("TRADINGCODEX_SECRET_KEY", ""))
    if len(secret) < 32 or secret == DEFAULT_LOCAL_SECRET_KEY:
        errors.append("set a non-default TRADINGCODEX_SECRET_KEY with at least 32 characters")

    api_key = str(env.get("TRADINGCODEX_API_KEY", ""))
    principal = str(env.get("TRADINGCODEX_API_PRINCIPAL", "")).strip()
    if len(api_key) < 32 or not principal:
        errors.append(
            "configure authenticated mutations with TRADINGCODEX_API_KEY (at least 32 characters) and TRADINGCODEX_API_PRINCIPAL"
        )
    elif api_key == secret:
        errors.append("TRADINGCODEX_API_KEY must differ from TRADINGCODEX_SECRET_KEY")

    allowed_hosts = _csv(env.get("TRADINGCODEX_ALLOWED_HOSTS", ""))
    if not allowed_hosts or "*" in allowed_hosts or not any(
        not is_loopback_host(host.lstrip(".")) and host != "testserver" for host in allowed_hosts
    ):
        errors.append("configure explicit non-loopback TRADINGCODEX_ALLOWED_HOSTS without '*'")

    origins = _csv(env.get("TRADINGCODEX_CSRF_TRUSTED_ORIGINS", ""))
    if not origins or any(not _secure_origin(origin, allowed_hosts) for origin in origins):
        errors.append(
            "configure HTTPS TRADINGCODEX_CSRF_TRUSTED_ORIGINS matching TRADINGCODEX_ALLOWED_HOSTS"
        )

    if str(env.get("TRADINGCODEX_TRANSPORT_SECURITY", "")).strip().lower() != SUPPORTED_TRANSPORT_SECURITY:
        errors.append("set TRADINGCODEX_TRANSPORT_SECURITY=reverse-proxy")
    return errors


def _address_host(addr: str) -> str:
    value = str(addr).strip()
    if value.startswith("["):
        closing = value.find("]")
        if closing < 0:
            raise RuntimeError(f"invalid service address: {addr}")
        return value[1:closing]
    if ":" in value:
        return value.rsplit(":", 1)[0] or "127.0.0.1"
    return "127.0.0.1"


def _env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _secure_origin(origin: str, allowed_hosts: list[str]) -> bool:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return False
    hostname = parsed.hostname.lower()
    return any(
        hostname == allowed.lower().lstrip(".")
        or (allowed.startswith(".") and hostname.endswith(allowed.lower()))
        for allowed in allowed_hosts
        if allowed != "*"
    )
