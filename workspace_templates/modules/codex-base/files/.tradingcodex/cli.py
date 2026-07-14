#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SPEC = {{TRADINGCODEX_MCP_PACKAGE_SPEC_PYTHON}}
PACKAGE_SOURCE_KIND = {{TRADINGCODEX_PACKAGE_SOURCE_KIND_PYTHON}}
GENERATED_HOME = {{TRADINGCODEX_HOME_PYTHON}}
GENERATED_HOME_SOURCE = {{TRADINGCODEX_HOME_SOURCE_PYTHON}}
GENERATED_DB_PATH = {{TRADINGCODEX_DB_PATH_PYTHON}}
GENERATED_DB_SOURCE = {{TRADINGCODEX_DB_SOURCE_PYTHON}}
GENERATED_SERVICE_ADDR = {{TRADINGCODEX_SERVICE_ADDR_PYTHON}}
GENERATED_PYTHONPATH = {{TRADINGCODEX_MCP_PYTHONPATH_PYTHON}}
GENERATED_PYTHON = {{TRADINGCODEX_PYTHON_PYTHON}}
PACKAGE_SPEC_ENV = "TRADINGCODEX_MCP_PACKAGE_SPEC"
PACKAGE_SOURCE_KIND_ENV = "_TRADINGCODEX_EXECUTABLE_SOURCE_KIND"
PRIOR_RUNTIME_PYTHON_ENV = "_TRADINGCODEX_PRIOR_RUNTIME_PYTHON"


def _configure_environment() -> None:
    if GENERATED_PYTHONPATH:
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        os.environ["PYTHONPATH"] = GENERATED_PYTHONPATH + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        if GENERATED_PYTHONPATH not in sys.path:
            sys.path.insert(0, GENERATED_PYTHONPATH)
    os.environ.setdefault("TRADINGCODEX_WORKSPACE_ROOT", str(ROOT))
    declared_source = _declared_package_source()
    if declared_source:
        os.environ[PACKAGE_SPEC_ENV] = declared_source
    elif PACKAGE_SPEC:
        os.environ.setdefault(PACKAGE_SPEC_ENV, PACKAGE_SPEC)
    os.environ.setdefault(PACKAGE_SOURCE_KIND_ENV, PACKAGE_SOURCE_KIND)
    if str(os.environ.get("TRADINGCODEX_HOME") or "").strip():
        os.environ.setdefault("TRADINGCODEX_HOME_SOURCE", "environment_override")
    else:
        os.environ["TRADINGCODEX_HOME"] = GENERATED_HOME
        os.environ["TRADINGCODEX_HOME_SOURCE"] = GENERATED_HOME_SOURCE
    if GENERATED_DB_SOURCE == "environment_override" and not str(os.environ.get("TRADINGCODEX_DB_NAME") or "").strip():
        os.environ["TRADINGCODEX_DB_NAME"] = GENERATED_DB_PATH
    os.environ.setdefault("TRADINGCODEX_SERVICE_ADDR", GENERATED_SERVICE_ADDR)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")
    os.chdir(ROOT)


def _reexec_package_runner() -> None:
    package_spec = _declared_package_source() or PACKAGE_SPEC
    if not package_spec:
        raise SystemExit(
            "tcx: local package source is not stored; rerun update with --from <package-spec>."
        )
    local_directory = (
        _package_source_is_local(package_spec)
        and "://" not in package_spec
        and Path(package_spec).expanduser().is_dir()
    )
    runner = shutil.which("uv" if local_directory else "uvx")
    if runner:
        package_prefix = (
            ["run", "--no-project", "--with-editable"]
            if local_directory
            else ["--refresh", "--from"]
        )
    elif local_directory and (runner := shutil.which("uvx")):
        package_prefix = ["--refresh", "--from"]
    elif not local_directory and (runner := shutil.which("uv")):
        package_prefix = ["tool", "run", "--refresh", "--from"]
    else:
        raise SystemExit(
            "tcx: package refresh requires uv or uvx; install uv, or use "
            "--skip-refresh only with the recorded durable runtime."
        )
    args = [runner, *package_prefix, package_spec, "python", str(Path(__file__).resolve()), *sys.argv[1:]]
    env = os.environ.copy()
    env["TRADINGCODEX_LAUNCHED_BY_PACKAGE_RUNNER"] = "1"
    if "TRADINGCODEX_PYTHON" not in env and _prior_runtime_is_usable(GENERATED_PYTHON):
        env[PRIOR_RUNTIME_PYTHON_ENV] = GENERATED_PYTHON
    os.execve(runner, args, env)


def _prior_runtime_is_usable(raw_path: str) -> bool:
    path = Path(raw_path).expanduser()
    if not path.is_absolute() or not path.is_file():
        return False
    parts = {part.casefold() for part in path.parts}
    if "archive-v0" in parts or "builds-v0" in parts:
        return False
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    try:
        probe = subprocess.run(
            [
                str(path),
                "-c",
                (
                    "import sys; "
                    "sys.exit(2) if not ((3, 11) <= sys.version_info < (3, 15)) else None; "
                    "import tradingcodex_cli.commands.mcp, tradingcodex_service.mcp_runtime"
                ),
            ],
            cwd=path.parent,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _declared_package_source() -> str:
    values: list[str] = []
    args = sys.argv[1:]
    for index, argument in enumerate(args):
        if argument == "--from":
            if index + 1 >= len(args):
                raise SystemExit("tcx: --from requires a package spec")
            values.append(args[index + 1])
        elif argument.startswith("--from="):
            values.append(argument.split("=", 1)[1])
    if len(values) > 1:
        raise SystemExit("tcx: --from may be supplied only once")
    value = values[0] if values else str(os.environ.get(PACKAGE_SPEC_ENV) or "")
    if not value:
        return ""
    if value != value.strip() or len(value) > 4096:
        raise SystemExit("tcx: package source is invalid")
    if value.startswith("-"):
        raise SystemExit("tcx: package source must not begin with an option")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SystemExit("tcx: package source is invalid")
    if re.search(
        r"(?i)(?:access[_-]?key|api[_-]?key|credential|password|passwd|secret|signature|token)\s*=",
        value,
    ):
        raise SystemExit("tcx: package source must not contain inline secrets")
    if "://" in value:
        url = value[value.rfind(" ", 0, value.index("://")) + 1 :]
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except ValueError as exc:
            raise SystemExit("tcx: package source URL is invalid") from exc
        scheme = parsed.scheme.casefold()
        if scheme == "file" and parsed.netloc:
            raise SystemExit("tcx: package source file URL must be local")
        if scheme not in {"file", "https", "git+https", "git+ssh", "ssh"}:
            raise SystemExit("tcx: package source URL scheme is unsupported")
        if scheme != "file" and not parsed.hostname:
            raise SystemExit("tcx: package source URL is invalid")
        if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
            raise SystemExit("tcx: package source URL must not contain credentials")
        if parsed.query or parsed.fragment:
            raise SystemExit("tcx: package source URL must not contain a query or fragment")
    elif re.match(r"^[^/\\\s@]+@[^/\\\s:]+:.+", value):
        raise SystemExit("tcx: package source must not use SCP-style remote syntax")
    return value


def _package_source_is_local(value: str) -> bool:
    if "://" in value:
        url = value[value.rfind(" ", 0, value.index("://")) + 1 :]
        return urlsplit(url).scheme.casefold() == "file"
    path = Path(value).expanduser()
    return (
        path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or value.startswith(("./", "../", "~/", ".\\", "..\\", "~\\"))
        or "/" in value
        or "\\" in value
        or value.casefold().endswith((".whl", ".zip", ".tar.gz", ".tgz"))
    )


def _update_requires_refresh() -> bool:
    if not sys.argv[1:] or sys.argv[1] != "update":
        return False
    update_args = sys.argv[2:]
    if any(argument in {"-h", "--help"} for argument in update_args):
        return False
    return not update_args or update_args[0] not in {"status", "help"}


def _run() -> None:
    _configure_environment()
    update_requested = bool(sys.argv[1:]) and sys.argv[1] == "update"
    refresh_requested = _update_requires_refresh()
    skip_refresh = "--skip-refresh" in sys.argv[2:] or os.environ.get("TRADINGCODEX_UPDATE_SKIP_REFRESH") == "1"
    if update_requested and "--skip-refresh" in sys.argv[2:]:
        sys.argv.remove("--skip-refresh")
        os.environ["TRADINGCODEX_UPDATE_SKIP_REFRESH"] = "1"
    if refresh_requested and not skip_refresh and os.environ.get("TRADINGCODEX_LAUNCHED_BY_PACKAGE_RUNNER") != "1":
        _reexec_package_runner()
    try:
        from tradingcodex_cli.__main__ import main
    except ModuleNotFoundError as exc:
        if exc.name != "tradingcodex_cli":
            raise
    else:
        main()
        return

    external = shutil.which("tcx.exe" if os.name == "nt" else "tcx")
    local_launchers = {str((ROOT / "tcx").resolve(strict=False)), str((ROOT / "tcx.cmd").resolve(strict=False))}
    if external and str(Path(external).resolve(strict=False)) not in local_launchers:
        raise SystemExit(subprocess.call([external, *sys.argv[1:]], env=os.environ.copy()))
    if os.environ.get("TRADINGCODEX_LAUNCHED_BY_PACKAGE_RUNNER") != "1":
        _reexec_package_runner()
    raise SystemExit("tcx: TradingCodex is unavailable; install the package or its generated package runner.")


if __name__ == "__main__":
    _run()
