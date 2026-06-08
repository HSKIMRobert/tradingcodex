from __future__ import annotations

import json
import sys
from pathlib import Path

from tradingcodex_service.domain import mcp_handle_rpc


def run_stdio(workspace_root: Path) -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except Exception as exc:
            _write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}})
            continue
        response = mcp_handle_rpc(workspace_root, message)
        if response is not None:
            _write(response)


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()
