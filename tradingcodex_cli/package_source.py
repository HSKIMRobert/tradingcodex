from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlsplit

from packaging.requirements import InvalidRequirement, Requirement


DEFAULT_EXECUTABLE_SOURCE = "tradingcodex"
EXECUTABLE_SOURCE_ENV = "TRADINGCODEX_MCP_PACKAGE_SPEC"
PRIOR_RUNTIME_PYTHON_ENV = "_TRADINGCODEX_PRIOR_RUNTIME_PYTHON"
PACKAGE_SOURCE_KIND_ENV = "_TRADINGCODEX_EXECUTABLE_SOURCE_KIND"
LOCAL_EXECUTABLE_SOURCE_KIND = "local-explicit"
PERSISTENT_EXECUTABLE_SOURCE_KIND = "persistent"
LOCAL_EXECUTABLE_SOURCE_PROVENANCE = "local-explicit"
_REMOTE_SOURCE_SCHEMES = frozenset({"https", "git+https", "git+ssh", "ssh"})
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:access[_-]?key|api[_-]?key|credential|password|passwd|secret|signature|token)\s*="
)


def validate_executable_source(raw_value: str) -> str:
    """Validate a package source before it can become executable provenance."""

    if not isinstance(raw_value, str):
        raise ValueError("TradingCodex executable source must be a string")
    if not raw_value or raw_value != raw_value.strip():
        raise ValueError("TradingCodex executable source must be non-empty with no surrounding whitespace")
    if len(raw_value) > 4096:
        raise ValueError("TradingCodex executable source is too long")
    if raw_value.startswith("-"):
        raise ValueError("TradingCodex executable source must not begin with an option")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw_value):
        raise ValueError("TradingCodex executable source must not contain control characters")
    if _SECRET_ASSIGNMENT.search(raw_value):
        raise ValueError("TradingCodex executable source must not contain inline secrets")

    source_url = _source_url(raw_value)
    if source_url:
        _validate_source_url(source_url)
    elif "://" in raw_value:
        raise ValueError("TradingCodex executable source URL is invalid")
    elif re.match(r"^[^/\\\s@]+@[^/\\\s:]+:.+", raw_value):
        raise ValueError("TradingCodex executable source must not contain user information")
    return raw_value


def configured_executable_source(
    explicit_source: str | None,
    *,
    environ: Mapping[str, str] | None = None,
    require_explicit: bool = False,
) -> str:
    """Resolve only caller-declared source provenance; never infer a uvx --from value."""

    values = os.environ if environ is None else environ
    if explicit_source is not None:
        return validate_executable_source(explicit_source)
    environment_source = str(values.get(EXECUTABLE_SOURCE_ENV) or "")
    if environment_source:
        return validate_executable_source(environment_source)
    if require_explicit:
        raise ValueError(
            "package source provenance is required; pass --from <package-spec> "
            f"or set {EXECUTABLE_SOURCE_ENV}"
        )
    return DEFAULT_EXECUTABLE_SOURCE


def executable_source_is_local(source: str) -> bool:
    value = validate_executable_source(source)
    source_url = _source_url(value)
    if source_url:
        return urlsplit(source_url).scheme.casefold() == "file"
    path = Path(value).expanduser()
    return (
        path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or value.startswith(("./", "../", "~/", ".\\", "..\\", "~\\"))
        or "/" in value
        or "\\" in value
        or value.casefold().endswith((".whl", ".zip", ".tar.gz", ".tgz"))
    )


def canonical_executable_source(
    source: str,
    *,
    require_local_exists: bool = False,
    platform_name: str | None = None,
) -> str:
    value = validate_executable_source(source)
    if not executable_source_is_local(value):
        return value
    source_url = _source_url(value)
    if source_url:
        parsed = urlsplit(source_url)
        if parsed.netloc:
            raise ValueError("TradingCodex local executable source URL must not name a remote host")
        decoded_path = unquote(parsed.path)
        if (platform_name or os.name).casefold() in {"nt", "windows", "win32"}:
            if re.match(r"^/[A-Za-z]:/", decoded_path):
                decoded_path = decoded_path[1:]
            rendered = str(PureWindowsPath(decoded_path))
            if require_local_exists and platform_name is None and not Path(rendered).exists():
                raise ValueError("TradingCodex local executable source does not exist")
            return rendered
        local_path = Path(decoded_path).expanduser()
    else:
        local_path = Path(value).expanduser()
    resolved = local_path.resolve(strict=False)
    if require_local_exists and not resolved.exists():
        raise ValueError("TradingCodex local executable source does not exist")
    return str(resolved)


def runtime_has_direct_source() -> bool:
    """Return whether installed metadata declares a non-index source, without exposing it."""

    try:
        raw = distribution("tradingcodex").read_text("direct_url.json")
    except PackageNotFoundError:
        return False
    if not raw:
        return False
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return True
    return isinstance(payload, dict) and bool(str(payload.get("url") or ""))


def _source_url(value: str) -> str:
    try:
        requirement = Requirement(value)
    except InvalidRequirement:
        requirement = None
    if requirement is not None and requirement.url:
        return requirement.url
    return value if "://" in value else ""


def _validate_source_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("TradingCodex executable source URL is invalid") from exc
    scheme = parsed.scheme.casefold()
    if scheme == "file":
        if parsed.netloc:
            raise ValueError("TradingCodex executable source file URL must be local")
        if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
            raise ValueError("TradingCodex executable source URL must not contain credentials")
    elif scheme not in _REMOTE_SOURCE_SCHEMES or not parsed.hostname:
        raise ValueError("TradingCodex executable source URL must use HTTPS, SSH, or file")
    elif parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("TradingCodex executable source URL must not contain credentials")
    if parsed.query:
        raise ValueError("TradingCodex executable source URL must not contain a query or signed parameters")
    if parsed.fragment:
        raise ValueError("TradingCodex executable source URL must not contain a fragment")
