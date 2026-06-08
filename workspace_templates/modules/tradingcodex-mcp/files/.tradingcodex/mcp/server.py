#!/usr/bin/env python3
"""TradingCodex Django-hosted MCP stdio bridge.

This server is an approved action gateway, not a raw broker proxy. It delegates
tool calls to the shared Python service layer used by Django Admin, Django Ninja,
and the workspace CLI.
"""
import os
import sys

SOURCE_ROOT = "{{SOURCE_ROOT}}"
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

os.environ.setdefault("TRADINGCODEX_WORKSPACE_ROOT", "{{PROJECT_DIR}}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")

from pathlib import Path

from tradingcodex_cli.mcp_stdio import run_stdio
from tradingcodex_cli.service_autostart import maybe_autostart_service


if __name__ == "__main__":
    workspace_root = Path("{{PROJECT_DIR}}")
    maybe_autostart_service(workspace_root, source_root=Path(SOURCE_ROOT))
    run_stdio(workspace_root)
