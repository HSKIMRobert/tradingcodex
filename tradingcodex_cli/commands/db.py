from __future__ import annotations

from pathlib import Path

from tradingcodex_service.application.runtime import (
    ensure_runtime_database,
    migrate_runtime_database,
    persist_workspace_context_if_available,
    runtime_home_status,
    tradingcodex_db_path,
)
from tradingcodex_cli.commands.utils import print_json

def db(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "status"
    if sub == "path":
        print(str(tradingcodex_db_path()))
        return
    if sub == "migrate":
        migration = migrate_runtime_database(root)
        print_json({
            "status": "migrated",
            "db_path": str(tradingcodex_db_path()),
            "db_canonical": True,
            "backup_path": migration["backup_path"],
            "workspace_context": persist_workspace_context_if_available(root),
        })
        return
    if sub == "status":
        home_status = runtime_home_status()
        ensure_runtime_database(root)
        db_path = tradingcodex_db_path()
        print_json({
            **home_status,
            "status": "ok",
            "db_path": str(db_path),
            "db_exists": db_path.exists(),
            "workspace_root": str(root),
            "workspace_is_provenance_only": True,
            "db_canonical": True,
            "workspace_context": persist_workspace_context_if_available(root),
        })
        return
    raise ValueError("Usage: tcx db status|path|migrate")
