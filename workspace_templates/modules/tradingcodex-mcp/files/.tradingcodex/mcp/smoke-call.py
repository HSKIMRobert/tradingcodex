#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

SOURCE_ROOT = "{{SOURCE_ROOT}}"
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

os.environ.setdefault("TRADINGCODEX_WORKSPACE_ROOT", "{{PROJECT_DIR}}")

from tradingcodex_service.domain import call_tool


if __name__ == "__main__":
    root = Path("{{PROJECT_DIR}}")
    print(json.dumps(call_tool(root, "get_positions_snapshot", {}), indent=2))
