from __future__ import annotations

import os
import tempfile
from pathlib import Path

import django


if not os.environ.get("TRADINGCODEX_DB_NAME"):
    db_path = Path(tempfile.gettempdir()) / f"tradingcodex-test-{os.getpid()}.sqlite3"
    try:
        db_path.unlink()
    except FileNotFoundError:
        pass
    os.environ["TRADINGCODEX_DB_NAME"] = str(db_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")
django.setup()
