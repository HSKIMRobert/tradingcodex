#!/usr/bin/env python3
"""TradingCodex Django-hosted MCP stdio bridge.

This server is an authenticated analysis, approval, and read/status gateway,
not a raw broker proxy or an execution-mutation surface. It delegates tool
calls to the shared Python service layer used by Django Admin, Django Ninja,
and the workspace CLI.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("TRADINGCODEX_WORKSPACE_ROOT", str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")

from tradingcodex_cli.mcp_stdio import run_stdio
from tradingcodex_cli.service_autostart import maybe_autostart_service


if __name__ == "__main__":
    maybe_autostart_service(ROOT)
    run_stdio(ROOT)
