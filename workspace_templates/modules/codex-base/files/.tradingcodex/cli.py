#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SPEC = {{TRADINGCODEX_MCP_PACKAGE_SPEC_PYTHON}}
GENERATED_HOME = {{TRADINGCODEX_HOME_PYTHON}}
GENERATED_HOME_SOURCE = {{TRADINGCODEX_HOME_SOURCE_PYTHON}}
GENERATED_DB_PATH = {{TRADINGCODEX_DB_PATH_PYTHON}}
GENERATED_DB_SOURCE = {{TRADINGCODEX_DB_SOURCE_PYTHON}}
GENERATED_SERVICE_ADDR = {{TRADINGCODEX_SERVICE_ADDR_PYTHON}}


def _configure_environment() -> None:
    os.environ.setdefault("TRADINGCODEX_WORKSPACE_ROOT", str(ROOT))
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


def _reexec_uvx(*, refresh: bool) -> None:
    uvx = shutil.which("uvx")
    if not uvx:
        return
    args = [uvx]
    if refresh:
        args.append("--refresh")
    args.extend(["--from", PACKAGE_SPEC, "python", str(Path(__file__).resolve()), *sys.argv[1:]])
    env = os.environ.copy()
    env["TRADINGCODEX_LAUNCHED_BY_UVX"] = "1"
    os.execve(uvx, args, env)


def _run() -> None:
    _configure_environment()
    update_requested = bool(sys.argv[1:]) and sys.argv[1] == "update"
    skip_refresh = "--skip-refresh" in sys.argv[2:] or os.environ.get("TRADINGCODEX_UPDATE_SKIP_REFRESH") == "1"
    if update_requested and "--skip-refresh" in sys.argv[2:]:
        sys.argv.remove("--skip-refresh")
    if update_requested and not skip_refresh and os.environ.get("TRADINGCODEX_LAUNCHED_BY_UVX") != "1":
        _reexec_uvx(refresh=True)
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
    if os.environ.get("TRADINGCODEX_LAUNCHED_BY_UVX") != "1":
        _reexec_uvx(refresh=False)
    raise SystemExit("tcx: TradingCodex is unavailable; install the package or install uvx.")


if __name__ == "__main__":
    _run()
