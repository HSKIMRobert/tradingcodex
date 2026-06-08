#!/usr/bin/env python3
import os
import sys

SOURCE_ROOT = "{{SOURCE_ROOT}}"
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

os.environ.setdefault("TRADINGCODEX_WORKSPACE_ROOT", "{{PROJECT_DIR}}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")

from tradingcodex_cli.__main__ import main


if __name__ == "__main__":
    main()
