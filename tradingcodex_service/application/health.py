from __future__ import annotations

import os
import tempfile
from typing import Any

from django.db import connection
from tradingcodex_service import __version__
from tradingcodex_service.application.runtime import runtime_migration_status, tradingcodex_db_path, tradingcodex_state_dir


def liveness_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "tradingcodex",
        "version": __version__,
        "pid": os.getpid(),
        "central_local_service": True,
        "process_scope": os.environ.get("TRADINGCODEX_MCP_SCOPE", "local-service"),
    }


def readiness_payload() -> dict[str, Any]:
    checks = [_database_check(), _migration_check(), _state_directory_check()]
    ready = all(check["status"] == "ok" for check in checks)
    return {
        **liveness_payload(),
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "db_path": str(tradingcodex_db_path()),
        "checks": checks,
        "reason_codes": [check["code"] for check in checks if check["status"] != "ok"],
    }


def _database_check() -> dict[str, str]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {"name": "database", "status": "ok", "code": "database_ok"}
    except Exception as exc:
        return {"name": "database", "status": "failed", "code": "database_unavailable", "detail": type(exc).__name__}


def _migration_check() -> dict[str, str]:
    try:
        migration_status = runtime_migration_status()
        if not migration_status["compatible"]:
            incompatible = [
                *migration_status["unknown_applied"],
                *migration_status["untracked_project_tables"],
            ]
            return {
                "name": "migrations",
                "status": "failed",
                "code": "schema_incompatible",
                "detail": ", ".join(incompatible),
            }
        if migration_status["pending"]:
            return {
                "name": "migrations",
                "status": "failed",
                "code": "migrations_pending",
                "detail": f"{len(migration_status['pending'])} pending migration(s)",
            }
        return {"name": "migrations", "status": "ok", "code": "migrations_current"}
    except Exception as exc:
        return {"name": "migrations", "status": "failed", "code": "migration_check_failed", "detail": type(exc).__name__}


def _state_directory_check() -> dict[str, str]:
    path = tradingcodex_state_dir() / "run"
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".readiness-", dir=path):
            pass
        return {"name": "state_directory", "status": "ok", "code": "state_directory_writable"}
    except Exception as exc:
        return {"name": "state_directory", "status": "failed", "code": "state_directory_unwritable", "detail": type(exc).__name__}
