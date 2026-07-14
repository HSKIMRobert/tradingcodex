from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application import workbench
from tradingcodex_service.application.analysis_runs import begin_analysis_run
from tradingcodex_service.application.runtime import ensure_workspace_manifest


def test_workbench_analysis_guard_does_not_semantically_classify_korean() -> None:
    workbench._require_analysis_request("월요일 국장 예상해봐")


@pytest.mark.parametrize(
    "prompt",
    [
        "$investment-brain-quality-growth Analyze ACME.",
        "$investment-brain-quality-growth $investment-brain-deep-value Analyze ACME.",
    ],
)
def test_workbench_rejects_investment_brain_pseudo_invocation(prompt: str) -> None:
    with pytest.raises(ValueError, match="native Codex task"):
        workbench._validated_prompt(prompt)


def test_bound_prompt_declares_codex_native_orchestration() -> None:
    prompt = workbench._bound_workflow_prompt("월요일 국장 예상해봐", "analysis-korean")
    assert "already created lightweight analysis run" in prompt
    assert "orchestrate the fixed-role team dynamically" in prompt
    assert "record_workflow_plan" not in prompt


def test_workbench_agents_come_from_subagent_events(tmp_path: Path) -> None:
    state = tmp_path / ".tradingcodex/mainagent/subagent-session-state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"events": [
        {"event": "subagent-start", "run_id": "analysis-one", "role": "macro-analyst", "agent_session_id": "a", "ts": "2026-07-12T00:00:00Z"},
        {"event": "subagent-stop", "run_id": "analysis-one", "role": "macro-analyst", "agent_session_id": "a", "ts": "2026-07-12T00:01:00Z"},
    ]}), encoding="utf-8")
    assert workbench._run_agents_from_session(tmp_path, "analysis-one") == [{
        "role": "macro-analyst",
        "agent_session_id": "a",
        "status": "completed",
        "updated_at": "2026-07-12T00:01:00Z",
    }]


@pytest.mark.parametrize("payload", ["{not-json}", "[]", '{"type": 7}'])
def test_workbench_rejects_malformed_codex_event_output(payload: str) -> None:
    with pytest.raises(ValueError, match=r"Codex .*event"):
        workbench._normalize_codex_event(payload)


def test_workbench_run_directory_uses_lightweight_analysis_root(tmp_path: Path) -> None:
    ensure_workspace_manifest(tmp_path)
    begin_analysis_run(tmp_path, "Analyze ACME.", run_id="analysis-acme", apply_investor_context=False)
    assert workbench._run_dir(tmp_path, "analysis-acme") == tmp_path / ".tradingcodex/mainagent/runs/analysis-acme"


@pytest.mark.parametrize(
    "prompt",
    [
        "$tcx-order-allow --mode paper\nUse $tcx-workflow to prepare one paper order.",
        "$tcx-order-submit --ticket-id ticket-1 --approval-receipt-id receipt-1",
        "$tcx-order-cancel --ticket-id ticket-1 --broker-order-id broker-1 --approval-receipt-id receipt-1",
    ],
)
@pytest.mark.parametrize("surface", ["preview", "start", "follow-up"])
def test_workbench_rejects_native_execution_actions_on_every_run_surface(
    tmp_path: Path,
    prompt: str,
    surface: str,
) -> None:
    workspace = tmp_path / f"workbench-{surface}"
    bootstrap_workspace(workspace)

    with pytest.raises(ValueError, match="native execution actions are unavailable in Workbench"):
        if surface == "preview":
            workbench.preview_codex_run(workspace, prompt)
        elif surface == "start":
            workbench.start_codex_run(workspace, prompt)
        else:
            workbench.follow_up_codex_run(workspace, "analysis-missing", prompt)


def test_native_execution_skills_are_visible_but_not_workbench_startable(tmp_path: Path) -> None:
    workspace = tmp_path / "workbench-native-skills"
    bootstrap_workspace(workspace)

    skills = {item["id"]: item for item in workbench.skill_catalog(workspace)}

    assert skills["tcx-order-allow"]["user_visible"] is True
    assert skills["tcx-order-allow"]["startable"] is False
    assert skills["tcx-order-submit"]["user_visible"] is True
    assert skills["tcx-order-submit"]["startable"] is False
    assert skills["tcx-order-cancel"]["user_visible"] is True
    assert skills["tcx-order-cancel"]["startable"] is False


@pytest.mark.parametrize("surface", ["preview", "start", "follow-up"])
def test_workbench_rejects_native_build_turns_on_every_run_surface(
    tmp_path: Path,
    surface: str,
) -> None:
    workspace = tmp_path / f"workbench-build-{surface}"
    bootstrap_workspace(workspace)
    prompt = "$tcx-build\nUpdate the workspace-local connector scaffold."

    with pytest.raises(ValueError, match="native build turns are unavailable in Workbench"):
        if surface == "preview":
            workbench.preview_codex_run(workspace, prompt)
        elif surface == "start":
            workbench.start_codex_run(workspace, prompt)
        else:
            workbench.follow_up_codex_run(workspace, "analysis-missing", prompt)


def test_tcx_build_is_visible_but_not_workbench_startable(tmp_path: Path) -> None:
    workspace = tmp_path / "workbench-build-skill"
    bootstrap_workspace(workspace)

    skills = {item["id"]: item for item in workbench.skill_catalog(workspace)}

    assert skills["tcx-build"]["user_visible"] is True
    assert skills["tcx-build"]["startable"] is False
    assert {"build", "native-only"}.issubset(skills["tcx-build"]["risk_tags"])


def test_workbench_codex_launch_trusts_project_and_requires_its_mcp(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workbench-launch-contract"
    bootstrap_workspace(workspace)
    prompt = "Analyze ACME company facts only. No valuation, order, or execution."
    preview = workbench.preview_codex_run(workspace, prompt)
    captured: dict[str, object] = {}

    monkeypatch.setattr(workbench.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)

    def fake_launch(root, run_id, argv, metadata, runtime_prompt, *, followup):
        captured.update({
            "root": root,
            "run_id": run_id,
            "argv": argv,
            "metadata": metadata,
            "runtime_prompt": runtime_prompt,
            "followup": followup,
        })
        return {"workflow_run_id": run_id, "status": "starting"}

    monkeypatch.setattr(workbench, "_launch", fake_launch)
    result = workbench.start_codex_run(
        workspace,
        prompt,
        preview_signature=preview["preview_signature"],
    )

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert "--ignore-user-config" in argv
    assert workbench._trusted_project_config_arg(workspace.resolve()) in argv
    assert 'mcp_servers.tradingcodex.required=true' in argv
    assert result["status"] == "starting"
