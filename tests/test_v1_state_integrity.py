from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tradingcodex_service.application import runtime
from tradingcodex_service.application.agents import read_agent_additional_instructions
def test_agent_instruction_reader_does_not_hide_invalid_utf8(tmp_path: Path) -> None:
    instruction = tmp_path / ".tradingcodex/agent-instructions/fundamental-analyst.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"\xff\xfe")

    with pytest.raises(ValueError, match="invalid UTF-8"):
        read_agent_additional_instructions(tmp_path, "fundamental-analyst")


@pytest.mark.parametrize(
    ("status_field", "details", "reason"),
    [
        (
            "unknown_applied",
            ["orders.0004_prerelease"],
            "migrations outside the clean v1 graph",
        ),
        (
            "untracked_project_tables",
            ["orders_orderticket"],
            "project tables without clean v1 migration history",
        ),
    ],
)
def test_incompatible_prerelease_state_reports_safe_manual_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status_field: str,
    details: list[str],
    reason: str,
) -> None:
    selected_home = tmp_path / "External TradingCodex Home"
    selected_db = tmp_path / "Old Runtime" / "prerelease.sqlite3"
    selected_home.mkdir()
    selected_db.parent.mkdir()
    home_sentinel = selected_home / "keep-me.txt"
    home_sentinel.write_text("unchanged", encoding="utf-8")
    selected_db.write_bytes(b"prerelease-state")
    monkeypatch.setenv("TRADINGCODEX_HOME", str(selected_home))
    monkeypatch.setenv("TRADINGCODEX_DB_NAME", str(selected_db))
    status = {
        "compatible": False,
        "unknown_applied": [],
        "untracked_project_tables": [],
        "pending": [],
        "applied_project": [],
    }
    status[status_field] = details
    monkeypatch.setattr(runtime, "runtime_migration_status", lambda workspace_root=None: status)

    with pytest.raises(runtime.RuntimeMigrationError) as exc_info:
        runtime.assert_runtime_database_compatible(tmp_path / "workspace")

    message = str(exc_info.value)
    assert reason in message
    assert details[0] in message
    assert f"Selected TRADINGCODEX_HOME: {selected_home.resolve()}" in message
    assert f"Selected database: {selected_db.resolve()}" in message
    assert "will not migrate, delete, archive, or back up" in message
    assert "new empty directory outside the workspace" in message
    assert "unset it or point it to a new empty database" in message
    assert "explicitly archive or remove" in message
    assert home_sentinel.read_text(encoding="utf-8") == "unchanged"
    assert selected_db.read_bytes() == b"prerelease-state"
    assert not list(tmp_path.rglob("*.backup-*"))


@pytest.mark.parametrize(
    "retired_table",
    ["workflows_workflowrun", "workflows_artifactref", "orders_orderintent"],
)
def test_retired_project_table_without_migration_history_is_incompatible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    retired_table: str,
) -> None:
    home = tmp_path / "external-home"
    database = home / "state" / "retired.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute(f'CREATE TABLE "{retired_table}" (id INTEGER PRIMARY KEY)')

    monkeypatch.setenv("TRADINGCODEX_HOME", str(home))
    monkeypatch.setenv("TRADINGCODEX_DB_NAME", str(database))
    status = runtime.runtime_migration_status(tmp_path / "workspace")

    assert status["compatible"] is False
    assert retired_table in status["untracked_project_tables"]
    with pytest.raises(runtime.RuntimeMigrationError, match=retired_table):
        runtime.assert_runtime_database_compatible(tmp_path / "workspace")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (retired_table,),
        ).fetchone() == (retired_table,)
