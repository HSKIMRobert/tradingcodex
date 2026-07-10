from __future__ import annotations

import os
import tempfile
from pathlib import Path

import django


TEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="tradingcodex-pytest-")).resolve()
os.environ.setdefault("TRADINGCODEX_HOME", str(TEST_RUNTIME_ROOT / "home"))

if not os.environ.get("TRADINGCODEX_DB_NAME"):
    db_path = TEST_RUNTIME_ROOT / f"tradingcodex-test-{os.getpid()}.sqlite3"
    try:
        db_path.unlink()
    except FileNotFoundError:
        pass
    os.environ["TRADINGCODEX_DB_NAME"] = str(db_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")
django.setup()
