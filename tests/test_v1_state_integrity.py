from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradingcodex_cli.commands.utils import read_thread_policy
from tradingcodex_service.application import workbench
from tradingcodex_service.application import runtime
from tradingcodex_service.application.agents import read_agent_additional_instructions
from tradingcodex_service.application.context_budget import audit_context_budget


def test_context_budget_has_no_workflow_plan_or_loop_projection(tmp_path: Path) -> None:
    result = audit_context_budget(tmp_path)
    assert result["status"] == "pass"
    assert "loop_state" not in result
    assert "latest_workflow_intake" not in result


def test_agent_instruction_reader_does_not_hide_invalid_utf8(tmp_path: Path) -> None:
    instruction = tmp_path / ".tradingcodex/agent-instructions/fundamental-analyst.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"\xff\xfe")

    with pytest.raises(ValueError, match="invalid UTF-8"):
        read_agent_additional_instructions(tmp_path, "fundamental-analyst")


@pytest.mark.parametrize("payload", ["{not-json}", "[]", '{"type": 7}'])
def test_workbench_rejects_malformed_codex_event_output(payload: str) -> None:
    with pytest.raises(ValueError, match=r"Codex .*event"):
        workbench._normalize_codex_event(payload)


def test_workbench_validates_the_entire_stored_event_log(tmp_path: Path) -> None:
    path = tmp_path / "web-run-events.jsonl"
    valid = json.dumps({
        "type": "turn.completed",
        "ts": "2026-01-01T00:00:00Z",
    })
    path.write_text("{not-json}\n" + "\n".join([valid] * 500) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 1"):
        workbench._read_normalized_events(path)


def test_workbench_stored_event_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unsupported workbench event fields"):
        workbench._validated_stored_event({
            "type": "item.completed",
            "item_type": "agent_message",
            "ts": "2026-01-01T00:00:00Z",
            "message": "must not be retained",
        })


def test_workbench_thread_authority_is_versioned_and_run_bound(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "workbench-locks"
    monkeypatch.setattr(workbench, "_run_state_dir", lambda: state_dir)
    root = tmp_path / "workspace"
    run_id = "workflow-current"
    workbench._store_thread_authority(root, run_id, "thread-current")
    path = workbench._thread_authority_path(root, run_id)
    value = json.loads(path.read_text(encoding="utf-8"))
    assert workbench._service_thread_id(root, run_id) == "thread-current"
    value["workflow_run_id"] = "workflow-other"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="identity"):
        workbench._service_thread_id(root, run_id)


def test_thread_policy_requires_canonical_toml_and_yaml_types(tmp_path: Path) -> None:
    codex_path = tmp_path / ".codex/config.toml"
    tradingcodex_path = tmp_path / ".tradingcodex/config.yaml"
    codex_path.parent.mkdir(parents=True)
    tradingcodex_path.parent.mkdir(parents=True)
    codex_path.write_text("[agents]\nmax_threads = 6\nmax_depth = 1\n", encoding="utf-8")
    tradingcodex_path.write_text("subagents:\n  reserved_threads: 1\n  overflow_strategy: batch_queue\n", encoding="utf-8")

    assert read_thread_policy(tmp_path) == {
        "max_threads": 6,
        "max_depth": 1,
        "reserved_threads": 1,
        "max_parallel_subagents": 5,
        "overflow_strategy": "batch_queue",
    }

    codex_path.write_text('[agents]\nmax_threads = "6"\nmax_depth = 1\n', encoding="utf-8")
    with pytest.raises(ValueError, match="max_threads"):
        read_thread_policy(tmp_path)


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
