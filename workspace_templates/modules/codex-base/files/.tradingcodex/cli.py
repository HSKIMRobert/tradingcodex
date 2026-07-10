#!/usr/bin/env python3
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("TRADINGCODEX_WORKSPACE_ROOT", str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")

from tradingcodex_cli.__main__ import main


if __name__ == "__main__":
    main()
