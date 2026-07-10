from __future__ import annotations

import os
import tempfile
from typing import Any

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from tradingcodex_service import __version__
from tradingcodex_service.application.runtime import tradingcodex_db_path, tradingcodex_state_dir


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
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            return {
                "name": "migrations",
                "status": "failed",
                "code": "migrations_pending",
                "detail": f"{len(pending)} pending migration(s)",
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
