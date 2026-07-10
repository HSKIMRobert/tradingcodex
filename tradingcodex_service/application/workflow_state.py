from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from tradingcodex_service.application.common import append_jsonl, exclusive_file_lock, now_iso, safe_workspace_path, sanitize_id, stable_hash, write_json


WORKFLOW_RUNS_ROOT = Path(".tradingcodex/mainagent/workflows")
LATEST_LOOP_STATE = Path(".tradingcodex/mainagent/workflow-loop-state.json")
StateReducer = Callable[[dict[str, Any]], dict[str, Any] | None]
StateProjection = Callable[[dict[str, Any]], dict[str, Any]]


def workflow_state_path(root: Path | str, workflow_run_id: str) -> Path:
    return _workflow_state_file(root, workflow_run_id, "loop-state.json")


def read_workflow_state(root: Path | str, workflow_run_id: str) -> dict[str, Any]:
    return _read_state_strict(workflow_state_path(root, workflow_run_id))


def replay_workflow_state(root: Path | str, workflow_run_id: str) -> dict[str, Any]:
    events_path = _workflow_state_file(root, workflow_run_id, "events.jsonl")
    if not events_path.exists():
        return {}
    replayed: dict[str, Any] = {}
    expected_revision = 1
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        state = event.get("state")
        if event.get("state_revision") != expected_revision or not isinstance(state, dict):
            raise ValueError("workflow event log is not replayable")
        if event.get("workflow_run_id") != workflow_run_id or state.get("workflow_run_id") != workflow_run_id:
            raise ValueError("workflow event log run id mismatch")
        if stable_hash(state) != event.get("state_hash"):
            raise ValueError("workflow event state hash mismatch")
        replayed = state
        expected_revision += 1
    return replayed


def initialize_workflow_state(
    root: Path | str,
    state: dict[str, Any],
    *,
    latest_projection: StateProjection,
) -> dict[str, Any]:
    run_id = str(state.get("workflow_run_id") or "")
    if not run_id:
        raise ValueError("workflow_run_id is required")

    def initialize(current: dict[str, Any]) -> dict[str, Any]:
        if current:
            raise ValueError(f"workflow state already exists: {run_id}")
        return dict(state)

    return transition_workflow_state(
        root,
        run_id,
        event_type="workflow-plan-recorded",
        reason="validated plan initialized canonical workflow state",
        event_id=f"plan:{state.get('plan_hash')}",
        reducer=initialize,
        latest_projection=latest_projection,
        update_latest=True,
    )


def transition_workflow_state(
    root: Path | str,
    workflow_run_id: str,
    *,
    event_type: str,
    reason: str,
    event_id: str,
    reducer: StateReducer,
    latest_projection: StateProjection,
    update_latest: bool | None = None,
    event_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    path = workflow_state_path(root, workflow_run_id)
    with exclusive_file_lock(path):
        current = _read_state_strict(path)
        replayed = replay_workflow_state(root, workflow_run_id)
        if replayed:
            if replayed.get("workflow_run_id") != workflow_run_id:
                raise ValueError("workflow event log run id mismatch")
            file_revision = int(current.get("state_revision") or 0)
            replay_revision = int(replayed.get("state_revision") or 0)
            if file_revision > replay_revision:
                raise ValueError("canonical workflow state is ahead of its durable event log")
            if file_revision == replay_revision and current and stable_hash(current) != stable_hash(replayed):
                raise ValueError("canonical workflow state disagrees with its durable event log")
            if replay_revision > file_revision:
                current = replayed
                write_json(path, current)
        if current and current.get("workflow_run_id") != workflow_run_id:
            raise ValueError("workflow state run id mismatch")
        if event_id and event_id in (current.get("applied_event_ids") or []):
            return current
        updated = reducer(copy.deepcopy(current))
        next_state = dict(updated if isinstance(updated, dict) else current)
        _enforce_immutable_contract(current, next_state, workflow_run_id)
        revision = int(current.get("state_revision") or 0) + 1
        canonical_event_id = event_id or stable_hash({"run": workflow_run_id, "revision": revision, "event": event_type})
        next_state.update({
            "workflow_run_id": workflow_run_id,
            "state_revision": revision,
            "last_event_id": canonical_event_id,
            "last_transition": event_type,
            "transition_reason": reason,
            "updated_at": now_iso(),
            "applied_event_ids": [*(current.get("applied_event_ids") or []), canonical_event_id],
        })
        event = {
            "event_id": canonical_event_id,
            "event_type": event_type,
            "reason": reason,
            "workflow_run_id": workflow_run_id,
            "state_revision": revision,
            "plan_hash": next_state.get("plan_hash", ""),
            "routing_envelope_hash": next_state.get("routing_envelope_hash", ""),
            "supervisor_round": next_state.get("supervisor_round", 0),
            "ts": next_state["updated_at"],
            "payload": event_payload or {},
            "state_hash": stable_hash(next_state),
            "state": next_state,
        }
        # The append-only event is canonical. If a process stops before the
        # projection write, the next transition replays and repairs the file.
        append_jsonl(_workflow_state_file(root, workflow_run_id, "events.jsonl"), event)
        write_json(path, next_state)
        latest_path = safe_workspace_path(root, LATEST_LOOP_STATE.as_posix(), allowed_roots=(Path(".tradingcodex/mainagent"),))
        latest = _read_json_or_empty(latest_path)
        should_update_latest = update_latest if update_latest is not None else not latest or latest.get("workflow_run_id") == workflow_run_id
        if should_update_latest:
            write_json(latest_path, latest_projection(next_state))
        return next_state


def _workflow_state_file(root: Path | str, workflow_run_id: str, name: str) -> Path:
    return safe_workspace_path(
        Path(root).expanduser().resolve(),
        (WORKFLOW_RUNS_ROOT / sanitize_id(workflow_run_id) / name).as_posix(),
        allowed_roots=(Path(".tradingcodex/mainagent"),),
    )


def _enforce_immutable_contract(current: dict[str, Any], updated: dict[str, Any], run_id: str) -> None:
    if updated.get("workflow_run_id") not in (None, "", run_id):
        raise ValueError("workflow transition cannot change workflow_run_id")
    for field in ("lane", "plan_version", "plan_hash", "routing_envelope_hash", "intake_hash"):
        if current.get(field) not in (None, "") and updated.get(field) != current.get(field):
            raise ValueError(f"workflow transition cannot change immutable {field}")
    old_blocks = {str(item).lower() for item in current.get("blocked_actions") or []}
    new_blocks = {str(item).lower() for item in updated.get("blocked_actions") or []}
    if not old_blocks.issubset(new_blocks):
        raise ValueError("workflow transition cannot remove blocked actions")


def _read_state_strict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"canonical workflow state is unavailable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"canonical workflow state must be an object: {path}")
    return value


def _read_json_or_empty(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}
