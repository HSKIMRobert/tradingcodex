from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "workspace_templates/modules"
CANONICAL_TOOL_NAMES_QUERY = (
    'text(ALL_TOOLS.filter(x => x.name.includes("<provider-or-keyword>"))'
    ".slice(0, 12).map(x => x.name))"
)
CANONICAL_TOOL_SCHEMA_LOOKUP = (
    'const t = ALL_TOOLS.find(x => x.name === "<exact-tool-name>"); '
    'text(t ? t.description : "missing")'
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_head_manager_reads_artifacts_progressively_without_blind_repeats() -> None:
    head = _read(
        TEMPLATES
        / "codex-base/files/.codex/prompts/base_instructions/head-manager.md"
    )
    workflow = _read(
        TEMPLATES / "repo-skills/files/.agents/skills/tcx-workflow/SKILL.md"
    )
    head_flat = _flat(head)
    workflow_flat = _flat(workflow)

    for flat in (head_flat, workflow_flat):
        assert "detail_level=card" in flat or "compact cards" in flat
        assert "detail_level=review" in flat
        assert "one" in flat and "artifact" in flat
        assert "truncat" in flat
        assert "version" in flat and "content hash" in flat
    assert "Never repeat an unchanged tool call" in head
    assert "before the first spawn or optional planning reconnaissance" in head_flat
    assert "before synthesis" in head_flat
    assert "10000 <= timeout_ms <= 30000" in head_flat
    assert "Never call `wait_agent` a second time" in head_flat
    assert "Other tool calls do not reset this gate" in head_flat
    assert "accepted source types" in workflow
    assert "do not batch several full bodies" in workflow
    assert "do not expose private reasoning or unaccepted findings" in workflow_flat


def test_deferred_tool_resolution_uses_bounded_names_then_one_exact_schema() -> None:
    prompts = {
        "head-manager": _read(
            TEMPLATES
            / "codex-base/files/.codex/prompts/base_instructions/head-manager.md"
        ),
        "fixed-role": _read(
            TEMPLATES
            / "codex-base/files/.codex/prompts/base_instructions/fixed-role.md"
        ),
    }

    for label, prompt in prompts.items():
        flat = _flat(prompt)
        assert prompt.count(CANONICAL_TOOL_NAMES_QUERY) == 1, label
        assert prompt.count(CANONICAL_TOOL_SCHEMA_LOOKUP) == 1, label
        assert "the result contains at most twelve names" in flat.lower(), label
        assert (
            "Only if the exact selected name appeared in that prior names result, "
            "run at most one schema lookup"
        ) in flat, label
        assert "Each step emits exactly one standard data envelope" in flat, label
        assert "transport-owned status prelude" in flat, label
        assert "not a second data envelope" in flat, label
        assert "map, search, filter, or regex descriptions" in flat, label
        assert "full `ALL_TOOLS` records or catalogs" in flat, label
        assert "inspect an unselected tool" in flat, label
        assert "repeat a schema lookup" in flat, label
        assert "at most four literal `x.name.includes(...)` predicates" in flat, label
        assert "one `const` local passed to `text`" in flat, label
        assert ".map(x => x.description)" not in prompt, label
        assert ".filter(x => x.description" not in prompt, label
        assert "one JSON name array and no other block" not in prompt, label


def test_head_manager_delegates_one_exact_external_data_call_to_one_owner() -> None:
    head = _read(
        TEMPLATES
        / "codex-base/files/.codex/prompts/base_instructions/head-manager.md"
    )
    head_flat = _flat(head)

    assert "Do not make the external data call yourself" in head
    assert "exact namespace/FQN, provider, and DataNeed" in head
    assert "one acquisition owner's brief" in head_flat
    assert "`run_id` copied from the current `workflow_run_id`" in head
    assert "service derives it from the run and stable data-family coordinates" in head_flat
    assert "assign exactly one of the six evidence-producing roles as acquisition owner" in head_flat
    assert "the same family may not" in head_flat
    assert "Snapshot/Dataset/Data Acquisition Receipt/Artifact IDs" in head_flat
    assert "attested to that exact source" in head


def test_fixed_role_preserves_frequency_and_returns_oversized_need_for_split() -> None:
    fixed_role = _read(
        TEMPLATES
        / "codex-base/files/.codex/prompts/base_instructions/fixed-role.md"
    )
    fixed_flat = _flat(fixed_role)

    assert "Preserve the DataNeed frequency" in fixed_role
    assert "require its `run_id` to match the current workflow run" in fixed_role
    assert "service-derived `family_id` unchanged" in fixed_role
    assert "never turn required daily data into weekly data" in fixed_role
    assert "return to Head Manager for preassigned non-overlapping" in fixed_flat
    assert "instrument- or period-scoped atomic DataNeeds" in fixed_flat
    assert "not a cue for another overlapping fetch" in fixed_flat


def test_fixed_role_reads_each_skill_completely_without_concatenated_output() -> None:
    fixed_role = _read(
        TEMPLATES
        / "codex-base/files/.codex/prompts/base_instructions/fixed-role.md"
    )
    fixed_flat = _flat(fixed_role)

    assert "read every needed `SKILL.md` completely" in fixed_flat
    assert "one exact file per separate shell call" in fixed_flat
    assert "never concatenate paths" in fixed_flat
    assert "Keep each result under 20,000 characters" in fixed_flat
    assert "one bounded shell call" not in fixed_role

    role_skill_root = (
        TEMPLATES / "repo-skills/files/.tradingcodex/subagents/skills"
    )
    projected_skill_paths = sorted(role_skill_root.glob("**/SKILL.md"))
    assert projected_skill_paths
    assert all(len(_read(path)) < 20_000 for path in projected_skill_paths)


def test_role_web_and_row_provider_context_is_hard_bounded() -> None:
    prompts = (
        _read(
            TEMPLATES
            / "codex-base/files/.codex/prompts/base_instructions/head-manager.md"
        ),
        _read(
            TEMPLATES
            / "codex-base/files/.codex/prompts/base_instructions/fixed-role.md"
        ),
    )
    fixed_role = prompts[1]

    for prompt in prompts:
        assert 'response_length="short"' in prompt
        assert 'response_length="medium"' not in prompt
        assert "Never use `medium` or `long`" in prompt or "Never request `medium` or `long`" in prompt
    assert "at most 120 observations" in fixed_role
    assert "over-20,000-character result" in fixed_role

    contract_docs = (
        ROOT / "docs/roles-skills-and-workflows.md",
        ROOT / "docs/generated-workspaces.md",
        ROOT / "docs/validation-and-test-plan.md",
        ROOT / "openwiki/development-and-validation.md",
    )
    for path in contract_docs:
        text = _read(path)
        flat = _flat(text)
        assert CANONICAL_TOOL_NAMES_QUERY in text, path
        assert CANONICAL_TOOL_SCHEMA_LOOKUP in text, path
        assert "standard data envelope" in flat, path
        assert "status prelude" in flat, path


def test_role_skills_define_bounded_retry_and_supported_contract_values() -> None:
    role_skills = (
        TEMPLATES
        / "repo-skills/files/.tradingcodex/subagents/skills"
    )
    artifact = _read(role_skills / "shared/tcx-artifact/SKILL.md")
    runtime = _read(
        role_skills / "shared/tcx-calculation/references/data-runtime.md"
    )
    valuation = _read(
        role_skills / "valuation-analyst/tcx-valuation/SKILL.md"
    )

    assert "Stop unchanged tool loops" in artifact
    assert "Never submit the unchanged arguments again" in artifact
    assert "ARTIFACT <artifact_id> <path> <handoff_state>" in artifact
    assert "valuation sensitivity is an improvement type" in _flat(artifact).lower()
    for value in ("string", "bool", "int64", "float64", "date32", "timestamp"):
        assert f"`{value}`" in runtime
    assert "`decimal128(p,s)`" in runtime
    assert "timezone-aware RFC 3339" in runtime
    assert "`dataset_slice`" in runtime
    assert "`dataset_materialization`" in runtime
    assert "prefer a reverse DCF" in valuation
    assert "Do not publish a precise intrinsic-value target" in _flat(valuation)


def test_public_guide_explains_compact_role_context_and_evidence_reads() -> None:
    workflow = _read(ROOT / "guidebook/dynamic-workflow.html")
    harness = _read(ROOT / "guidebook/harness.html")

    assert "hard-bounded artifact cards first" in workflow
    assert "entire review response is capped" in workflow
    assert "exact next offset returned by the service" in workflow
    assert "A broad list or recovery-only child is never valid" in workflow
    assert "before the first spawn or optional planning reconnaissance" in workflow
    assert "Each child wait lasts 10–30 seconds" in workflow
    assert "visible progress update before waiting again" in workflow
    assert "Search snippets remain source leads" in workflow
    assert "private model reasoning remains hidden" in workflow
    assert "a compact fixed-role base" in harness
    assert "without copying the root coordination manual" in harness
