from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def run(
    args: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    expect_ok: bool = True,
    env_extra: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    for key, value in (env_extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    result = subprocess.run(args, cwd=cwd, input=input_text, text=True, capture_output=True, env=env, timeout=120)
    if expect_ok and result.returncode != 0:
        raise AssertionError(f"{args} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    if not expect_ok and result.returncode == 0:
        raise AssertionError(f"{args} unexpectedly succeeded\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def init_workspace(tmp_path: Path) -> tuple[Path, dict[str, str | None]]:
    workspace = tmp_path / "codex-cli-e2e-workspace"
    home = tmp_path / "tradingcodex-home"
    env_extra = {"TRADINGCODEX_HOME": str(home), "TRADINGCODEX_DB_NAME": None}
    result = run([sys.executable, "-m", "tradingcodex_cli", "init", str(workspace)], ROOT, env_extra=env_extra)
    assert "TradingCodex workspace created" in result.stdout
    assert "Open the workspace in Codex" in result.stdout
    return workspace, env_extra


def hook_context(workspace: Path, prompt: str, env_extra: dict[str, str | None], *, via_hooks_json: bool = False) -> dict[str, Any] | None:
    payload = json.dumps({"prompt": prompt})
    if via_hooks_json:
        command = json.loads((workspace / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        result = run(shlex.split(command), workspace, input_text=payload, env_extra=env_extra)
    else:
        result = run([str(workspace / ".codex" / "hooks" / "tradingcodex_hook.py"), "user-prompt-submit"], workspace, input_text=payload, env_extra=env_extra)
    if not result.stdout.strip():
        return None
    output = json.loads(result.stdout)
    return json.loads(output["hookSpecificOutput"]["additionalContext"])


def tcx(workspace: Path, env_extra: dict[str, str | None], *args: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["./tcx", *args], workspace, env_extra=env_extra, expect_ok=expect_ok)


def test_generated_workspace_codex_cli_user_scenario_matrix(tmp_path: Path) -> None:
    workspace, env_extra = init_workspace(tmp_path)

    doctor = tcx(workspace, env_extra, "doctor").stdout
    assert "TradingCodex doctor passed" in doctor
    assert "TradingCodex MCP autostarts local service" in doctor

    prompt_cases = [
        (
            "Analyze Apple stock",
            "research_only",
            ["fundamental-analyst", "technical-analyst", "news-analyst"],
            False,
        ),
        (
            "$orchestrate-workflow NVDA earnings preview and catalyst review, no order and no trading",
            "thesis_review",
            ["fundamental-analyst", "technical-analyst", "news-analyst", "macro-analyst", "valuation-analyst"],
            False,
        ),
        (
            "BTC trend review no trading",
            "research_only",
            ["technical-analyst", "news-analyst", "instrument-analyst"],
            False,
        ),
        (
            "rates and oil impact on my NVDA position, no order. Do not place trades.",
            "portfolio_risk_review",
            ["macro-analyst", "portfolio-manager", "risk-manager"],
            False,
        ),
        (
            "Buy 1 AAPL with paper trading only after approval",
            "order_intent_or_approval_execution_gate",
            ["portfolio-manager", "risk-manager", "execution-operator"],
            False,
        ),
        (
            "Routing smoke test for NVDA. No order, no trading, no valuation. Use selected subagents only.",
            "research_only",
            ["fundamental-analyst", "technical-analyst", "news-analyst"],
            False,
        ),
        (
            "Compare EUR/USD and BTC technical setup, no trading",
            "research_only",
            ["technical-analyst", "news-analyst", "instrument-analyst"],
            False,
        ),
        (
            "TSLA fair value and whether it fits my portfolio, no order",
            "thesis_review_then_portfolio_risk_review",
            ["fundamental-analyst", "technical-analyst", "news-analyst", "valuation-analyst", "portfolio-manager", "risk-manager"],
            False,
        ),
        (
            "Please save my broker API key secret to .env",
            "secret_warning",
            [],
            True,
        ),
    ]
    for index, (prompt, lane, roles, secret_warning) in enumerate(prompt_cases):
        gate = hook_context(workspace, prompt, env_extra, via_hooks_json=index == 0)
        assert gate is not None, prompt
        assert gate["workflow_lane"] == lane
        assert gate["required_subagents"] == roles
        assert gate["secret_warning"] is secret_warning
        assert gate["confirmation_required"] is False
        if roles:
            starter = gate["starter_prompt"]
            assert "This selected team is binding for the current lane" in starter
            assert "Research artifact language:" in starter
            assert "Use handoff states: accepted, revise, blocked, waiting." in starter
            assert "source/as-of posture" in starter
            assert "Blocked actions before artifacts:" in starter

    assert hook_context(workspace, "Analyze AGENTS.md for stale guidance", env_extra) is None
    assert hook_context(workspace, "Create a quality income strategy for dividend stocks", env_extra) is None
    assert not (workspace / ".env").exists()

    status = json.loads(tcx(workspace, env_extra, "subagents", "status").stdout)
    assert status["installed_count"] == 9
    assert status["fixed_roster_ok"] is True
    assert status["skills_installed"] == 22
    plan = json.loads(tcx(workspace, env_extra, "subagents", "plan", "--all").stdout)
    assert plan["requested_count"] == 9
    assert plan["parallel_spawn_ok"] is True
    inspect = json.loads(tcx(workspace, env_extra, "subagents", "inspect", "fundamental-analyst").stdout)
    assert inspect["effective_skills"] == ["external-data-source-gate", "collect-evidence", "fundamental-analysis"]

    optional_body = workspace / "source-quality-body.md"
    optional_body.write_text("# Source Quality Check\n\nCheck source dates and cite stale evidence warnings.\n", encoding="utf-8")
    optional = json.loads(
        tcx(
            workspace,
            env_extra,
            "skills",
            "optional",
            "create",
            "source-quality-check",
            "--role",
            "fundamental-analyst",
            "--description",
            "Check whether cited evidence is fresh and source-tagged.",
            "--body-file",
            "source-quality-body.md",
            "--active",
        ).stdout
    )
    assert optional["status"] == "active"
    assert "source-quality-check" in tcx(workspace, env_extra, "subagents", "skills", "fundamental-analyst").stdout

    strategy_body = workspace / "quality-income-strategy.md"
    strategy_body.write_text("# Quality Income\n\nPrefer durable income quality with evidence discipline.\n", encoding="utf-8")
    strategy = json.loads(
        tcx(
            workspace,
            env_extra,
            "strategies",
            "create",
            "strategy-quality-income",
            "--description",
            "Apply a quality income strategy.",
            "--language",
            "ko-KR",
            "--body-file",
            "quality-income-strategy.md",
            "--active",
        ).stdout
    )
    assert strategy["name"] == "strategy-quality-income"
    assert strategy["active"] is True
    assert "strategy-quality-income" in tcx(workspace, env_extra, "skills", "list").stdout
    assert "strategy-quality-income" not in (workspace / ".codex" / "agents" / "fundamental-analyst.toml").read_text(encoding="utf-8")

    memo_path = workspace / "nvda-evidence.md"
    memo_path.write_text("# NVDA Evidence\n\n[factual] Test evidence uses source/as-of metadata.\n", encoding="utf-8")
    stored = json.loads(
        tcx(
            workspace,
            env_extra,
            "research",
            "create",
            "--markdown-file",
            "nvda-evidence.md",
            "--id",
            "e2e-nvda-evidence",
            "--type",
            "evidence_pack",
            "--symbol",
            "NVDA",
            "--title",
            "NVDA E2E Evidence",
            "--source-as-of",
            "2026-06-12",
            "--readiness",
            "research-grade",
            "--created-by",
            "fundamental-analyst",
        ).stdout
    )
    assert stored["file_sot"] is True
    assert stored["export_path"] == "trading/research/e2e-nvda-evidence.evidence.md"
    assert json.loads(tcx(workspace, env_extra, "research", "search", "source/as-of").stdout)["artifacts"][0]["artifact_id"] == "e2e-nvda-evidence"
    exported = json.loads(tcx(workspace, env_extra, "research", "export", "e2e-nvda-evidence", "--export-path", "trading/reports/fundamental/e2e-nvda.md").stdout)
    assert exported["export_path"] == "trading/reports/fundamental/e2e-nvda.md"
    quality = json.loads(tcx(workspace, env_extra, "quality-check", "trading/research/e2e-nvda-evidence.evidence.md").stdout)
    assert quality["status"] == "pass"
    bad_order_path = workspace / "trading" / "orders" / "draft" / "bad.order_intent.json"
    bad_order_path.write_text("{}", encoding="utf-8")
    bad_quality = json.loads(tcx(workspace, env_extra, "quality-check", "trading/orders/draft/bad.order_intent.json", expect_ok=False).stdout)
    assert bad_quality["status"] == "fail"
    assert "symbol" in bad_quality["required_fields_missing"]

    snapshot = json.loads(
        tcx(
            workspace,
            env_extra,
            "mcp",
            "call",
            "record_source_snapshot",
            "--principal",
            "fundamental-analyst",
            "--provider",
            "unit-test",
            "--source-category",
            "filing",
            "--as-of",
            "2026-06-12",
            "--artifact-id",
            "e2e-nvda-evidence",
            "--warnings",
            '["stale after 7 days"]',
            "--payload",
            '{"url":"https://example.test/nvda"}',
        ).stdout
    )
    assert snapshot["file_sot"] is True
    assert snapshot["export_path"].startswith("trading/research/source-snapshots/")

    stdio_input = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    stdio = run(["./tcx", "mcp", "stdio"], workspace, input_text=stdio_input, env_extra=env_extra)
    assert "submit_approved_order" in stdio.stdout
    assert "create_research_artifact" in stdio.stdout

    order = {
        "id": "e2e-order-1",
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 1,
        "limit_price": 1000,
        "currency": "KRW",
        "broker": "paper-trading",
        "estimated_notional_krw": 1000,
        "created_by": "portfolio-manager",
        "created_at": "2026-06-12T00:00:00Z",
    }
    order_path = workspace / "trading" / "orders" / "draft" / "e2e-order-1.order_intent.json"
    order_path.write_text(json.dumps(order), encoding="utf-8")
    assert json.loads(tcx(workspace, env_extra, "validate", "order", "trading/orders/draft/e2e-order-1.order_intent.json").stdout)["valid"] is True
    assert json.loads(tcx(workspace, env_extra, "risk-check", "trading/orders/draft/e2e-order-1.order_intent.json").stdout)["decision"] == "go"
    approval = json.loads(tcx(workspace, env_extra, "approve", "trading/orders/draft/e2e-order-1.order_intent.json", "--approved-by", "risk-manager").stdout)
    assert approval["status"] == "approved"
    execution = json.loads(tcx(workspace, env_extra, "mcp", "call", "submit_approved_order", "--order-intent-id", "e2e-order-1").stdout)
    assert execution["status"] == "accepted"
    duplicate = json.loads(tcx(workspace, env_extra, "mcp", "call", "submit_approved_order", "--order-intent-id", "e2e-order-1", expect_ok=False).stdout)
    assert duplicate["status"] == "rejected"
    snapshot_after_order = json.loads(tcx(workspace, env_extra, "mcp", "call", "get_portfolio_snapshot").stdout)
    assert snapshot_after_order["positions"]["AAPL"]["quantity"] == 1.0
    ledger = json.loads(tcx(workspace, env_extra, "mcp", "ledger", "--tool", "submit_approved_order", "--status", "ok").stdout)
    assert ledger["count"] >= 1

    blocked_order = {**order, "id": "e2e-blocked", "symbol": "BLOCKED"}
    blocked_path = workspace / "trading" / "orders" / "draft" / "e2e-blocked.order_intent.json"
    blocked_path.write_text(json.dumps(blocked_order), encoding="utf-8")
    blocked = json.loads(tcx(workspace, env_extra, "validate", "order", "trading/orders/draft/e2e-blocked.order_intent.json", expect_ok=False).stdout)
    assert blocked["valid"] is False
    assert "symbol is restricted: BLOCKED" in "\n".join(blocked["reasons"])

    created_profile = json.loads(tcx(workspace, env_extra, "profile", "create", "strategy-lab").stdout)
    assert created_profile["profile"]["portfolio_id"] == "strategy-lab"
    selected_profile = json.loads(tcx(workspace, env_extra, "profile", "select", "strategy-lab").stdout)
    assert selected_profile["active_profile"]["portfolio_id"] == "strategy-lab"
    isolated_snapshot = json.loads(tcx(workspace, env_extra, "mcp", "call", "get_portfolio_snapshot").stdout)
    assert isolated_snapshot["portfolio_id"] == "strategy-lab"
    assert isolated_snapshot["positions"] == {}
