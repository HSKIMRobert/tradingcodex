from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tradingcodex_cli.generator import bootstrap_workspace


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / f"hook-{uuid.uuid4().hex[:10]}"
    bootstrap_workspace(root)
    return root


def run_hook(workspace: Path, event: str, payload: dict[str, object]) -> dict[str, object] | None:
    result = subprocess.run(
        [sys.executable, str(workspace / ".codex/hooks/tradingcodex_hook.py"), event],
        cwd=workspace,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def tool_payload(tool_name: str, tool_input: dict[str, object]) -> dict[str, object]:
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": "hook-session",
        "turn_id": "hook-turn",
        "tool_use_id": "hook-tool-use",
    }


def test_native_workspace_work_does_not_need_build_grant(workspace: Path) -> None:
    assert run_hook(
        workspace,
        "pre-tool-use",
        tool_payload("apply_patch", {"patch": "*** Begin Patch\n*** End Patch"}),
    ) is None
    assert run_hook(
        workspace,
        "pre-tool-use",
        tool_payload("exec_command", {"cmd": "pytest -q tests/test_example.py"}),
    ) is None


def test_hook_blocks_raw_secrets_direct_broker_effects_and_service_ledgers(workspace: Path) -> None:
    cases = (
        ("exec_command", {"cmd": "cat .env"}, "raw credential"),
        ("exec_command", {"cmd": "broker api submit"}, "Direct broker"),
        ("apply_patch", {"path": "trading/orders/live.json"}, "service-owned"),
    )
    for tool_name, tool_input, expected in cases:
        result = run_hook(workspace, "pre-tool-use", tool_payload(tool_name, tool_input))
        assert result is not None
        assert result["decision"] == "block"
        assert expected in str(result["reason"])


def test_native_spawn_accepts_generic_fallback_and_records_only_redacted_metadata(workspace: Path) -> None:
    message = "Use a bounded research-only brief without order, broker, or secret access."
    assert run_hook(
        workspace,
        "pre-tool-use",
        tool_payload("spawn_agent", {"agent_type": "default", "task_name": "narrow_fact", "message": message}),
    ) is None
    records = [
        json.loads(line)
        for line in (workspace / "trading/audit/codex-hooks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    record = records[-1]
    assert record["decision"] == "native_codex"
    assert record["agent_type"] == "default"
    assert record["message_bytes"] == len(message.encode("utf-8"))
    assert "message" not in record


def test_external_mcp_policy_stays_with_its_service_boundary(workspace: Path) -> None:
    # OpenBB and user-owned MCP calls have their own service/native boundaries.
    # The hook no longer attempts duplicate routing, repeat-call, or tool-catalog policy.
    assert run_hook(
        workspace,
        "pre-tool-use",
        tool_payload("mcp__openbb__equity_price_historical", {"provider": "yfinance", "limit": 10}),
    ) is None
    assert run_hook(
        workspace,
        "pre-tool-use",
        tool_payload("mcp__user_server__search", {"query": "earnings date"}),
    ) is None


def test_session_context_is_small_and_preserves_direct_fast_path(workspace: Path) -> None:
    result = run_hook(workspace, "session-start", {})
    context = json.loads(str(result["hookSpecificOutput"]["additionalContext"]))
    assert context["marker"] == "tradingcodex-session-context"
    assert "build_authorization" not in context
    assert "managed_skill_authorization" not in context
    assert "Answer narrow trusted facts and status requests directly" in context["planning_instruction"]
