from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingcodex_service.application.common import _safe_read, now_iso, read_json, sanitize_id, stable_hash, write_json


@dataclass(frozen=True)
class SkillSpec:
    id: str
    label: str
    owner_roles: tuple[str, ...]
    risk_tags: tuple[str, ...] = ()
    user_visible: bool = False
    scope: str = "mainagent"


@dataclass(frozen=True)
class AgentSpec:
    role: str
    label: str
    group: str
    builtin_skills: tuple[str, ...]
    permission_profile: str
    mcp_allowlist: tuple[str, ...] = ()
    forbidden_skill_tags: tuple[str, ...] = ()


RESEARCH_ROLES = (
    "fundamental-analyst",
    "technical-analyst",
    "news-analyst",
    "macro-analyst",
    "instrument-analyst",
    "valuation-analyst",
)

HEAD_MANAGER_SKILLS = (
    "orchestrate-workflow",
    "investment-workflow-map",
    "scenario-quality-gates",
    "manage-subagents",
    "manage-optional-skills",
    "head-manager-interview",
    "strategy-creator",
    "synthesize-decision",
    "postmortem",
)

AGENT_SPECS: dict[str, AgentSpec] = {
    "head-manager": AgentSpec(
        role="head-manager",
        label="Head Manager",
        group="coordination",
        builtin_skills=HEAD_MANAGER_SKILLS,
        permission_profile="tradingcodex",
        mcp_allowlist=(
            "get_tradingcodex_status",
            "simulate_policy",
            "get_order_status",
            "get_positions",
            "get_portfolio_snapshot",
            "list_workflow_artifacts",
            "create_research_artifact",
            "get_research_artifact",
            "list_research_artifacts",
            "search_research_artifacts",
            "append_research_artifact_version",
            "export_research_artifact_md",
            "record_source_snapshot",
            "record_audit_event",
        ),
    ),
    "fundamental-analyst": AgentSpec(
        role="fundamental-analyst",
        label="Fundamental Analyst",
        group="research",
        builtin_skills=("external-data-source-gate", "collect-evidence", "fundamental-analysis"),
        permission_profile="tradingcodex-fundamental",
        mcp_allowlist=(
            "list_workflow_artifacts",
            "create_research_artifact",
            "get_research_artifact",
            "list_research_artifacts",
            "search_research_artifacts",
            "append_research_artifact_version",
            "export_research_artifact_md",
            "record_source_snapshot",
            "record_audit_event",
        ),
        forbidden_skill_tags=("approval", "execution", "order", "secret"),
    ),
    "technical-analyst": AgentSpec(
        role="technical-analyst",
        label="Technical Analyst",
        group="research",
        builtin_skills=("external-data-source-gate", "collect-evidence", "technical-analysis"),
        permission_profile="tradingcodex-technical",
        mcp_allowlist=(
            "list_workflow_artifacts",
            "create_research_artifact",
            "get_research_artifact",
            "list_research_artifacts",
            "search_research_artifacts",
            "append_research_artifact_version",
            "export_research_artifact_md",
            "record_source_snapshot",
            "record_audit_event",
        ),
        forbidden_skill_tags=("approval", "execution", "order", "secret"),
    ),
    "news-analyst": AgentSpec(
        role="news-analyst",
        label="News Analyst",
        group="research",
        builtin_skills=("external-data-source-gate", "collect-evidence", "news-analysis"),
        permission_profile="tradingcodex-news",
        mcp_allowlist=(
            "list_workflow_artifacts",
            "create_research_artifact",
            "get_research_artifact",
            "list_research_artifacts",
            "search_research_artifacts",
            "append_research_artifact_version",
            "export_research_artifact_md",
            "record_source_snapshot",
            "record_audit_event",
        ),
        forbidden_skill_tags=("approval", "execution", "order", "secret"),
    ),
    "macro-analyst": AgentSpec(
        role="macro-analyst",
        label="Macro Analyst",
        group="research",
        builtin_skills=("external-data-source-gate", "collect-evidence", "macro-analysis"),
        permission_profile="tradingcodex-macro",
        mcp_allowlist=(
            "list_workflow_artifacts",
            "create_research_artifact",
            "get_research_artifact",
            "list_research_artifacts",
            "search_research_artifacts",
            "append_research_artifact_version",
            "export_research_artifact_md",
            "record_source_snapshot",
            "record_audit_event",
        ),
        forbidden_skill_tags=("approval", "execution", "order", "secret"),
    ),
    "instrument-analyst": AgentSpec(
        role="instrument-analyst",
        label="Instrument Analyst",
        group="research",
        builtin_skills=("external-data-source-gate", "collect-evidence", "instrument-analysis"),
        permission_profile="tradingcodex-instrument",
        mcp_allowlist=(
            "list_workflow_artifacts",
            "create_research_artifact",
            "get_research_artifact",
            "list_research_artifacts",
            "search_research_artifacts",
            "append_research_artifact_version",
            "export_research_artifact_md",
            "record_source_snapshot",
            "record_audit_event",
        ),
        forbidden_skill_tags=("approval", "execution", "order", "secret"),
    ),
    "valuation-analyst": AgentSpec(
        role="valuation-analyst",
        label="Valuation Analyst",
        group="research",
        builtin_skills=("external-data-source-gate", "valuation-review"),
        permission_profile="tradingcodex-valuation",
        mcp_allowlist=(
            "list_workflow_artifacts",
            "create_research_artifact",
            "get_research_artifact",
            "list_research_artifacts",
            "search_research_artifacts",
            "append_research_artifact_version",
            "export_research_artifact_md",
            "record_source_snapshot",
            "record_audit_event",
        ),
        forbidden_skill_tags=("approval", "execution", "order", "secret"),
    ),
    "portfolio-manager": AgentSpec(
        role="portfolio-manager",
        label="Portfolio Manager",
        group="portfolio",
        builtin_skills=("portfolio-review", "create-order-intent"),
        permission_profile="tradingcodex-portfolio",
        mcp_allowlist=("list_workflow_artifacts", "get_positions", "get_portfolio_snapshot", "record_audit_event"),
        forbidden_skill_tags=("execution", "secret"),
    ),
    "risk-manager": AgentSpec(
        role="risk-manager",
        label="Risk Manager",
        group="risk",
        builtin_skills=("review-risk", "policy-review", "approve-order"),
        permission_profile="tradingcodex-risk",
        mcp_allowlist=(
            "simulate_policy",
            "validate_order_intent",
            "validate_approval_receipt",
            "create_approval_receipt",
            "list_workflow_artifacts",
            "record_audit_event",
        ),
        forbidden_skill_tags=("execution", "secret"),
    ),
    "execution-operator": AgentSpec(
        role="execution-operator",
        label="Execution Operator",
        group="execution",
        builtin_skills=("execute-paper-order",),
        permission_profile="tradingcodex-execution",
        mcp_allowlist=(
            "simulate_policy",
            "validate_order_intent",
            "validate_approval_receipt",
            "submit_approved_order",
            "cancel_approved_order",
            "get_order_status",
            "get_positions",
            "get_portfolio_snapshot",
            "list_workflow_artifacts",
            "record_audit_event",
        ),
        forbidden_skill_tags=("approval", "secret"),
    ),
}


SKILL_SPECS: dict[str, SkillSpec] = {
    "orchestrate-workflow": SkillSpec("orchestrate-workflow", "Orchestrate Workflow", ("head-manager",), user_visible=True),
    "investment-workflow-map": SkillSpec("investment-workflow-map", "Investment Workflow Map", ("head-manager",)),
    "scenario-quality-gates": SkillSpec("scenario-quality-gates", "Scenario Quality Gates", ("head-manager",)),
    "external-data-source-gate": SkillSpec("external-data-source-gate", "External Data Source Gate", RESEARCH_ROLES, scope="subagent_shared"),
    "manage-subagents": SkillSpec("manage-subagents", "Manage Subagents", ("head-manager",)),
    "manage-optional-skills": SkillSpec("manage-optional-skills", "Manage Optional Skills", ("head-manager",)),
    "head-manager-interview": SkillSpec("head-manager-interview", "Head Manager Interview", ("head-manager",), user_visible=True),
    "strategy-creator": SkillSpec("strategy-creator", "Strategy Creator", ("head-manager",), user_visible=True),
    "synthesize-decision": SkillSpec("synthesize-decision", "Synthesize Decision", ("head-manager",)),
    "postmortem": SkillSpec("postmortem", "Postmortem", ("head-manager",), user_visible=True),
    "collect-evidence": SkillSpec("collect-evidence", "Collect Evidence", RESEARCH_ROLES, scope="subagent_shared"),
    "fundamental-analysis": SkillSpec("fundamental-analysis", "Fundamental Analysis", ("fundamental-analyst",), scope="subagent_role"),
    "technical-analysis": SkillSpec("technical-analysis", "Technical Analysis", ("technical-analyst",), scope="subagent_role"),
    "news-analysis": SkillSpec("news-analysis", "News Analysis", ("news-analyst",), scope="subagent_role"),
    "macro-analysis": SkillSpec("macro-analysis", "Macro Analysis", ("macro-analyst",), scope="subagent_role"),
    "instrument-analysis": SkillSpec("instrument-analysis", "Instrument Analysis", ("instrument-analyst",), scope="subagent_role"),
    "valuation-review": SkillSpec("valuation-review", "Valuation Review", ("valuation-analyst",), scope="subagent_role"),
    "portfolio-review": SkillSpec("portfolio-review", "Portfolio Review", ("portfolio-manager",), scope="subagent_role"),
    "create-order-intent": SkillSpec("create-order-intent", "Create Order Intent", ("portfolio-manager",), risk_tags=("order",), scope="subagent_role"),
    "review-risk": SkillSpec("review-risk", "Review Risk", ("risk-manager",), scope="subagent_role"),
    "policy-review": SkillSpec("policy-review", "Policy Review", ("risk-manager",), risk_tags=("approval",), scope="subagent_role"),
    "approve-order": SkillSpec("approve-order", "Approve Order", ("risk-manager",), risk_tags=("approval", "order"), scope="subagent_role"),
    "execute-paper-order": SkillSpec("execute-paper-order", "Execute Paper Order", ("execution-operator",), risk_tags=("execution", "order"), scope="subagent_role"),
}


ROLE_SKILL_MAP: dict[str, list[str]] = {role: list(spec.builtin_skills) for role, spec in AGENT_SPECS.items()}
USER_VISIBLE_SKILLS = [skill.id for skill in SKILL_SPECS.values() if skill.user_visible]
EXPECTED_SUBAGENTS = [role for role in AGENT_SPECS if role != "head-manager"]
EXPECTED_SKILLS = sorted(SKILL_SPECS)
ROLE_PERMISSION_PROFILES = {role: spec.permission_profile for role, spec in AGENT_SPECS.items() if role != "head-manager"}

PROPOSAL_DIR = Path(".tradingcodex/mainagent/skill-change-proposals")
LEGACY_OPTIONAL_SKILL_DIR = Path(".tradingcodex/mainagent/optional-skills")
MAINAGENT_SKILL_DIR = Path(".agents/skills")
STRATEGY_SKILL_DIR = Path(".tradingcodex/strategies")
SUBAGENT_SKILL_DIR = Path(".tradingcodex/subagents/skills")
SUBAGENT_SHARED_SKILL_DIR = SUBAGENT_SKILL_DIR / "shared"
OPTIONAL_SKILL_STATUS_FILE = Path("agents/tradingcodex.json")
GENERATED_DIR = Path(".tradingcodex/generated")
MANIFEST_PATH = GENERATED_DIR / "projection-manifest.json"
AGENT_INDEX_PATH = GENERATED_DIR / "agent-index.json"
SKILL_INDEX_PATH = GENERATED_DIR / "skill-index.json"
STRATEGY_SKILL_PREFIX = "strategy-"
STRATEGY_ROOT_CONFIG_START = "# BEGIN TradingCodex strategy skills"
STRATEGY_ROOT_CONFIG_END = "# END TradingCodex strategy skills"
STRATEGY_REQUIRED_FRONTMATTER = {
    "name",
    "description",
    "type",
    "status",
    "language",
    "managed_by",
    "owner",
    "last_reviewed",
}
STRATEGY_REQUIRED_SECTIONS = (
    "## Thesis",
    "## Eligible Universe",
    "## Preferred Setups",
    "## Entry Criteria",
    "## Exit Criteria",
    "## Evidence Requirements",
    "## Decision-Ready Standard",
    "## Sizing Guidance",
    "## Block Conditions",
    "## Portfolio And Risk Handoff",
    "## Change Log",
)
OPTIONAL_SKILL_STATUSES = {"draft", "active", "archived"}
OPTIONAL_SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
OPTIONAL_SKILL_RISK_PATTERNS = {
    "approval": re.compile(r"\b(approve|approval|approval receipt|receipt)\b", re.I),
    "execution": re.compile(r"\b(execute|execution|submit order|adapter submission|broker)\b", re.I),
    "order": re.compile(r"\b(order|order intent|buy|sell|short|long|trade|trading)\b", re.I),
    "secret": re.compile(r"\b(secret|credential|token|api key|password|\\.env)\b", re.I),
}
OPTIONAL_SKILL_LOCKED_SURFACE_PATTERN = re.compile(
    r"\b("
    r"mcp allowlist|permission profile|raw broker|live broker|direct broker|"
    r"bypass|ignore policy|disable guardrail|weaken guardrail|self-approve|"
    r"change policy|change capability|read secret|secret access"
    r")\b",
    re.I,
)


def registry_summary() -> dict[str, Any]:
    return {
        "source": "tradingcodex_service.application.agents",
        "agents": {role: _agent_spec_payload(spec) for role, spec in AGENT_SPECS.items()},
        "skills": {skill_id: asdict(spec) for skill_id, spec in SKILL_SPECS.items()},
        "expected_subagents": EXPECTED_SUBAGENTS,
        "expected_skills": EXPECTED_SKILLS,
    }


def inspect_agent_configuration(root: Path | str, role: str) -> dict[str, Any]:
    root = Path(root).resolve()
    if role not in AGENT_SPECS:
        raise ValueError(f"Unknown subagent or role: {role}")
    state = build_projection_state(root)
    return state["agents"][role]


def list_optional_role_skills(root: Path | str, role: str | None = None, include_archived: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    records = read_optional_skill_records(root, role=role, include_archived=include_archived)
    return {
        "status": "ok",
        "source": "file-native-optional-skills",
        "read_only": True,
        "optional_skills": records,
        "roles": sorted({record["role"] for record in records}),
    }


def list_user_visible_skills(root: Path | str) -> list[str]:
    root = Path(root).resolve()
    if not (root / MAINAGENT_SKILL_DIR).exists():
        return list(USER_VISIBLE_SKILLS)
    installed = _installed_skill_index(root)
    visible = [skill for skill in USER_VISIBLE_SKILLS if installed.get(skill, {}).get("installed")]
    visible.extend(skill["id"] for skill in read_strategy_skill_records(root, active_only=True) if not skill.get("legacy"))
    return list(dict.fromkeys(visible))


def read_strategy_skill_records(root: Path | str, *, active_only: bool = False) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    primary_root = root / STRATEGY_SKILL_DIR
    if primary_root.exists():
        for skill_path in sorted(primary_root.glob(f"{STRATEGY_SKILL_PREFIX}*/SKILL.md")):
            record = _strategy_record_payload(root, skill_path, legacy=False)
            seen.add(record["id"])
            if active_only and not record["active"]:
                continue
            records.append(record)
    legacy_root = root / MAINAGENT_SKILL_DIR
    if legacy_root.exists():
        for skill_path in sorted(legacy_root.glob(f"{STRATEGY_SKILL_PREFIX}*/SKILL.md")):
            if skill_path.parent.name in seen:
                continue
            record = _strategy_record_payload(root, skill_path, legacy=True)
            if active_only and not record["active"]:
                continue
            records.append(record)
    return records


def read_optional_skill_records(root: Path | str, role: str | None = None, include_archived: bool = True) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    base = root / SUBAGENT_SKILL_DIR
    if base.exists():
        for path in sorted(base.glob("*/*/SKILL.md")):
            scope_name = path.parent.parent.name
            skill_id = path.parent.name
            if skill_id in SKILL_SPECS:
                continue
            metadata_path = path.parent / OPTIONAL_SKILL_STATUS_FILE
            record = read_json(metadata_path, {}) or {}
            roles = _optional_record_roles(record, scope_name)
            for target_role in roles:
                if role and target_role != role:
                    continue
                candidate = {
                    **record,
                    "role": target_role,
                    "skill_id": skill_id,
                    "scope": "shared" if scope_name == "shared" else "role",
                    "source_file": _relative_path(root, path),
                    "metadata_file": _relative_path(root, path.parent / "agents" / "openai.yaml"),
                    "status_file": _relative_path(root, metadata_path),
                }
                payload = _optional_record_payload(root, candidate)
                if not include_archived and payload.get("status") == "archived":
                    continue
                seen.add((target_role, skill_id))
                records.append(payload)
    legacy_base = root / LEGACY_OPTIONAL_SKILL_DIR
    for path in sorted(legacy_base.glob("*/*.json")):
        record = read_json(path, {}) or {}
        record.setdefault("role", path.parent.name)
        record.setdefault("skill_id", path.stem)
        key = (str(record.get("role") or ""), normalize_optional_skill_id(str(record.get("skill_id") or "")))
        if key in seen:
            continue
        record.setdefault("source_file", _relative_path(root, root / MAINAGENT_SKILL_DIR / str(record.get("skill_id")) / "SKILL.md"))
        record.setdefault("metadata_file", _relative_path(root, root / MAINAGENT_SKILL_DIR / str(record.get("skill_id")) / "agents" / "openai.yaml"))
        record.setdefault("status_file", _relative_path(root, path))
        record.setdefault("legacy", True)
        if role and record.get("role") != role:
            continue
        if not include_archived and record.get("status") == "archived":
            continue
        records.append(_optional_record_payload(root, record))
    return records


def validate_optional_skill_payload(role: str, skill_id: str, title: str = "", description: str = "", body: str = "") -> dict[str, Any]:
    errors: list[str] = []
    if role not in EXPECTED_SUBAGENTS:
        errors.append(f"optional skills can target fixed subagents only: {role}")
    if skill_id in SKILL_SPECS:
        errors.append(f"core skill cannot be overwritten: {skill_id}")
    if skill_id.startswith(STRATEGY_SKILL_PREFIX):
        errors.append("optional skill id cannot use reserved strategy- prefix")
    if not OPTIONAL_SKILL_ID_PATTERN.match(skill_id):
        errors.append("optional skill id must be lowercase hyphen-case, 3-64 characters")
    combined = "\n".join([title, description, body])
    if OPTIONAL_SKILL_LOCKED_SURFACE_PATTERN.search(combined):
        errors.append("optional skills cannot change locked harness surfaces")
    risk_tags = infer_optional_skill_risk_tags(combined)
    agent = AGENT_SPECS.get(role)
    if agent:
        blocked_tags = sorted(set(agent.forbidden_skill_tags).intersection(risk_tags))
        if blocked_tags:
            errors.append(f"{role} cannot receive {skill_id}; blocked risk tags: {', '.join(blocked_tags)}")
    return {"status": "blocked" if errors else "valid", "errors": errors, "risk_tags": risk_tags}


def infer_optional_skill_risk_tags(text: str) -> list[str]:
    return sorted(tag for tag, pattern in OPTIONAL_SKILL_RISK_PATTERNS.items() if pattern.search(text))


def normalize_optional_skill_id(raw: str) -> str:
    return sanitize_id(raw).strip("-").lower()


def create_or_update_strategy_skill(
    root: Path | str,
    strategy_id: str,
    *,
    title: str = "",
    description: str = "",
    body: str = "",
    language: str = "unknown",
    status: str = "draft",
    actor: str = "local",
) -> dict[str, Any]:
    root = Path(root).resolve()
    strategy_id = normalize_strategy_skill_id(strategy_id)
    if status not in {"draft", "active", "archived"}:
        raise ValueError(f"unknown strategy status: {status}")
    if (root / MAINAGENT_SKILL_DIR / strategy_id).exists():
        raise ValueError(f"legacy strategy exists under .agents/skills: {strategy_id}; migrate it before writing")
    skill_dir = root / STRATEGY_SKILL_DIR / strategy_id
    skill_path = skill_dir / "SKILL.md"
    current_fields = _read_frontmatter_fields(skill_path)
    current_body = _read_markdown_body(skill_path)
    title = title or current_fields.get("name") or strategy_id
    description = description or current_fields.get("description") or f"Apply the {strategy_id} strategy."
    language = language or current_fields.get("language") or "unknown"
    body = body if body.strip() else current_body or _default_strategy_body(title)
    text = _render_strategy_skill_markdown(strategy_id, title, description, body, language, status)
    _atomic_write_text(skill_path, text)
    _atomic_write_text(skill_dir / "agents" / "openai.yaml", _render_openai_yaml(title, f"Apply {strategy_id} strategy", f"Use ${strategy_id} to apply this user-approved strategy."))
    record = _strategy_record_payload(root, skill_path, legacy=False)
    if status == "active" and record["validation_errors"]:
        raise ValueError("; ".join(record["validation_errors"]))
    project_agent_configuration(root, applied_by=actor)
    return _strategy_record_payload(root, skill_path, legacy=False)


def set_strategy_skill_status(root: Path | str, strategy_id: str, status: str, *, actor: str = "local") -> dict[str, Any]:
    root = Path(root).resolve()
    strategy_id = normalize_strategy_skill_id(strategy_id)
    record = get_strategy_skill_record(root, strategy_id)
    if record.get("legacy"):
        raise ValueError(f"legacy strategy is read-only: {strategy_id}")
    fields = dict(record.get("frontmatter") or {})
    body = _read_markdown_body(root / str(record["source_file"]))
    updated = create_or_update_strategy_skill(
        root,
        strategy_id,
        title=fields.get("name", strategy_id),
        description=fields.get("description", ""),
        body=body,
        language=fields.get("language", "unknown"),
        status=status,
        actor=actor,
    )
    return updated


def delete_strategy_skill(root: Path | str, strategy_id: str, *, force: bool = False, actor: str = "local") -> dict[str, Any]:
    root = Path(root).resolve()
    strategy_id = normalize_strategy_skill_id(strategy_id)
    record = get_strategy_skill_record(root, strategy_id)
    if record.get("legacy"):
        raise ValueError(f"legacy strategy is read-only: {strategy_id}")
    if record.get("status") == "active" and not force:
        return set_strategy_skill_status(root, strategy_id, "archived", actor=actor)
    shutil.rmtree(root / STRATEGY_SKILL_DIR / strategy_id, ignore_errors=True)
    project_agent_configuration(root, applied_by=actor)
    return {"id": strategy_id, "status": "deleted", "active": False}


def get_strategy_skill_record(root: Path | str, strategy_id: str) -> dict[str, Any]:
    strategy_id = normalize_strategy_skill_id(strategy_id)
    for record in read_strategy_skill_records(root, active_only=False):
        if record["id"] == strategy_id:
            return record
    raise ValueError(f"unknown strategy: {strategy_id}")


def normalize_strategy_skill_id(raw: str) -> str:
    skill_id = sanitize_id(raw).strip("-").lower()
    if not skill_id.startswith(STRATEGY_SKILL_PREFIX):
        skill_id = f"{STRATEGY_SKILL_PREFIX}{skill_id}"
    if not OPTIONAL_SKILL_ID_PATTERN.match(skill_id):
        raise ValueError("strategy id must be lowercase hyphen-case, 3-64 characters")
    return skill_id


def create_or_update_optional_skill(
    root: Path | str,
    role: str,
    skill_id: str,
    *,
    title: str = "",
    description: str = "",
    body: str = "",
    status: str = "draft",
    actor: str = "local",
) -> dict[str, Any]:
    root = Path(root).resolve()
    if role not in EXPECTED_SUBAGENTS:
        raise ValueError(f"optional skills can target fixed subagents only: {role}")
    skill_id = normalize_optional_skill_id(skill_id)
    if status not in OPTIONAL_SKILL_STATUSES:
        raise ValueError(f"unknown optional skill status: {status}")
    if skill_id in SKILL_SPECS or (root / MAINAGENT_SKILL_DIR / skill_id).exists():
        raise ValueError(f"core or project-scope skill cannot be overwritten: {skill_id}")
    skill_dir = root / SUBAGENT_SKILL_DIR / role / skill_id
    skill_path = skill_dir / "SKILL.md"
    current_fields = _read_frontmatter_fields(skill_path)
    current_body = _read_markdown_body(skill_path)
    title = title or current_fields.get("name") or skill_id.replace("-", " ").title()
    description = description or current_fields.get("description") or title
    body = body if body.strip() else current_body or f"# {title}\n\nDescribe the optional role-local procedure.\n"
    validation = validate_optional_skill_payload(role, skill_id, title, description, body)
    if status == "active" and validation["errors"]:
        raise ValueError("; ".join(validation["errors"]))
    _atomic_write_text(skill_path, _render_basic_skill_markdown(skill_id, description, body))
    _atomic_write_text(skill_dir / "agents" / "openai.yaml", _render_openai_yaml(title, description[:64] or title, f"Use ${skill_id} for the {role} optional procedure."))
    metadata = {
        "role": role,
        "skill_id": skill_id,
        "scope": "role",
        "title": title,
        "description": description,
        "status": status,
        "updated_by": actor,
        "updated_at": now_iso(),
    }
    status_path = skill_dir / OPTIONAL_SKILL_STATUS_FILE
    existing = read_json(status_path, {}) or {}
    if existing.get("created_at"):
        metadata["created_at"] = existing["created_at"]
        metadata["created_by"] = existing.get("created_by", actor)
    else:
        metadata["created_at"] = metadata["updated_at"]
        metadata["created_by"] = actor
    _atomic_write_json(status_path, metadata)
    project_agent_configuration(root, role=role, applied_by=actor)
    return next(record for record in read_optional_skill_records(root, role=role, include_archived=True) if record["skill_id"] == skill_id)


def set_optional_skill_status(root: Path | str, role: str, skill_id: str, status: str, *, actor: str = "local") -> dict[str, Any]:
    root = Path(root).resolve()
    skill_id = normalize_optional_skill_id(skill_id)
    record = get_optional_skill_record(root, role, skill_id)
    body = _read_markdown_body(root / str(record["source_file"]))
    return create_or_update_optional_skill(
        root,
        role,
        skill_id,
        title=str(record.get("title") or skill_id.replace("-", " ").title()),
        description=str(record.get("description") or ""),
        body=body,
        status=status,
        actor=actor,
    )


def delete_optional_skill(root: Path | str, role: str, skill_id: str, *, force: bool = False, actor: str = "local") -> dict[str, Any]:
    root = Path(root).resolve()
    skill_id = normalize_optional_skill_id(skill_id)
    record = get_optional_skill_record(root, role, skill_id)
    if record.get("status") == "active" and not force:
        return set_optional_skill_status(root, role, skill_id, "archived", actor=actor)
    source = root / str(record["source_file"])
    shutil.rmtree(source.parent, ignore_errors=True)
    project_agent_configuration(root, role=role, applied_by=actor)
    return {"role": role, "skill_id": skill_id, "status": "deleted"}


def get_optional_skill_record(root: Path | str, role: str, skill_id: str) -> dict[str, Any]:
    skill_id = normalize_optional_skill_id(skill_id)
    for record in read_optional_skill_records(root, role=role, include_archived=True):
        if record["skill_id"] == skill_id:
            return record
    raise ValueError(f"unknown optional skill for {role}: {skill_id}")


def _optional_records_by_role(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in AGENT_SPECS}
    for record in records:
        by_role.setdefault(str(record.get("role") or ""), []).append(record)
    return by_role


def diff_agent_configuration(root: Path | str, role: str) -> dict[str, Any]:
    root = Path(root).resolve()
    if role not in AGENT_SPECS:
        raise ValueError(f"Unknown subagent or role: {role}")
    state = build_projection_state(root)
    agent = state["agents"][role]
    builtin = set(agent["builtin_skills"])
    current = set(agent["projected_skills"])
    effective = set(agent["effective_skills"])
    return {
        "role": role,
        "builtin_skills": agent["builtin_skills"],
        "projected_skills": agent["projected_skills"],
        "effective_skills": agent["effective_skills"],
        "pending_proposals": agent["pending_proposals"],
        "applied_proposals": agent["applied_proposals"],
        "missing_from_projected": sorted(effective - current),
        "extra_projected": sorted(current - effective),
        "pending_additions": sorted(effective - builtin),
        "validation_errors": agent["validation_errors"],
        "codex_file": agent["codex_file"],
        "projection_manifest": state["projection_manifest"],
    }


def project_agent_configuration(
    root: Path | str,
    *,
    role: str | None = None,
    proposal_path: Path | str | None = None,
    applied_by: str = "local",
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    selected_role = role
    proposal_record: dict[str, Any] | None = None
    if proposal_path:
        proposal = Path(proposal_path)
        proposal = proposal if proposal.is_absolute() else root / proposal
        proposal_record = read_skill_proposal(proposal, root)
        selected_role = selected_role or proposal_record.get("target")
        validation_errors = validate_skill_assignment(str(proposal_record.get("target", "")), str(proposal_record.get("skill", "")))
        if validation_errors:
            _rewrite_skill_proposal(root, proposal_record, proposal, "blocked", applied_by, validation_errors)
            raise ValueError("; ".join(validation_errors))
        _rewrite_skill_proposal(root, proposal_record, proposal, "applied", applied_by, [])
        proposal_record = read_skill_proposal(proposal, root)

    if selected_role and selected_role not in AGENT_SPECS:
        raise ValueError(f"Unknown subagent or role: {selected_role}")

    state = build_projection_state(root)
    if selected_role:
        roles_to_project = [selected_role] if selected_role != "head-manager" else []
    else:
        roles_to_project = [role_id for role_id in EXPECTED_SUBAGENTS]
    for role_id in roles_to_project:
        _project_agent_toml(root, role_id, state["agents"][role_id]["effective_skills"])
    _project_root_strategy_skills(root)

    refreshed = build_projection_state(root)
    generated_at = generated_at or now_iso()
    _write_projection_indexes(root, refreshed, applied_by, generated_at, proposal_record)
    return build_projection_state(root)


def write_skill_proposal_file(root: Path | str, type_: str, target: str, skill: str) -> dict[str, Any]:
    root = Path(root).resolve()
    now = datetime.now(timezone.utc)
    proposal_id = f"skill-{type_}-{target}-{skill}-{now.strftime('%Y%m%dT%H%M%S%fZ')}"
    path = root / PROPOSAL_DIR / f"{sanitize_id(proposal_id)}.yaml"
    validation_errors = validate_skill_assignment(target, skill)
    status = "blocked" if validation_errors else "proposed"
    fields = {
        "id": proposal_id,
        "type": type_,
        "target": target,
        "skill": skill,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "requires_validation": "true",
        "status": status,
        "validation_status": "blocked" if validation_errors else "valid",
    }
    if validation_errors:
        fields["validation_error"] = "; ".join(validation_errors)
    _write_simple_yaml(path, fields)
    result = {"status": status, "id": proposal_id, "path": path.relative_to(root).as_posix(), "validation_errors": validation_errors}
    return result


def read_skill_proposals(root: Path | str) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    proposals: list[dict[str, Any]] = []
    for path in sorted((root / PROPOSAL_DIR).glob("*.yaml")):
        proposals.append(read_skill_proposal(path, root))
    return proposals


def read_skill_proposal(path: Path, root: Path | None = None) -> dict[str, Any]:
    root = root.resolve() if root else None
    data = _read_simple_yaml(path)
    data["path"] = path.relative_to(root).as_posix() if root and path.is_relative_to(root) else str(path)
    data["source_file_hash"] = _file_hash(path)
    return data


def validate_skill_assignment(role: str, skill: str) -> list[str]:
    errors: list[str] = []
    agent = AGENT_SPECS.get(role)
    skill_spec = SKILL_SPECS.get(skill)
    if not agent:
        errors.append(f"unknown role: {role}")
    if not skill_spec:
        errors.append(f"unknown skill: {skill}")
    if errors or not agent or not skill_spec:
        return errors
    if role != "head-manager" and skill_spec.scope == "mainagent":
        errors.append(f"{role} cannot receive project-scope mainagent skill: {skill}")
    blocked_tags = sorted(set(agent.forbidden_skill_tags).intersection(skill_spec.risk_tags))
    if blocked_tags:
        errors.append(f"{role} cannot receive {skill}; blocked risk tags: {', '.join(blocked_tags)}")
    if skill_spec.owner_roles and role not in skill_spec.owner_roles:
        errors.append(f"{role} is not an owner role for {skill}")
    return errors


def skills_for_role(root: Path | str, role: str) -> list[str]:
    return inspect_agent_configuration(root, role)["effective_skills"]


def build_projection_state(root: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    manifest = read_json(root / MANIFEST_PATH, {}) or {}
    applied_by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in AGENT_SPECS}
    pending_by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in AGENT_SPECS}
    blocked_by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in AGENT_SPECS}
    for proposal in read_skill_proposals(root):
        target = str(proposal.get("target", ""))
        if target not in AGENT_SPECS:
            continue
        status = str(proposal.get("status", "proposed"))
        if status == "applied":
            applied_by_role[target].append(proposal)
        elif status == "blocked":
            blocked_by_role[target].append(proposal)
        else:
            pending_by_role[target].append(proposal)

    agents: dict[str, dict[str, Any]] = {}
    skill_root_exists = (root / MAINAGENT_SKILL_DIR).exists()
    optional_records = read_optional_skill_records(root, include_archived=True)
    optional_by_role = _optional_records_by_role(optional_records)
    for role, spec in AGENT_SPECS.items():
        applied_skills = [str(item.get("skill")) for item in applied_by_role[role] if item.get("skill")]
        active_optional = [
            str(record.get("skill_id"))
            for record in optional_by_role.get(role, [])
            if record.get("status") == "active" and not record.get("validation_errors")
        ]
        effective = _unique_existing(root, [*spec.builtin_skills, *applied_skills, *active_optional], role=role)
        agent_file = _agent_config_path(root, role)
        projected_skills = _parse_toml_skill_paths(agent_file.read_text(encoding="utf-8")) if agent_file.exists() else []
        validation_errors: list[str] = []
        for skill in effective:
            if skill in SKILL_SPECS:
                validation_errors.extend(validate_skill_assignment(role, skill))
        for optional in optional_by_role.get(role, []):
            validation_errors.extend(optional.get("validation_errors") or [])
        agents[role] = {
            **_agent_spec_payload(spec),
            "codex_file": _relative_path(root, agent_file) if agent_file else "",
            "codex_file_hash": _file_hash(agent_file) if agent_file else None,
            "builtin_skills": list(spec.builtin_skills)
            if not skill_root_exists
            else [skill for skill in spec.builtin_skills if _skill_path(root, skill, role=role).exists()],
            "effective_skills": effective,
            "projected_skills": projected_skills,
            "pending_proposals": [_proposal_summary(proposal) for proposal in pending_by_role[role]],
            "applied_proposals": [_proposal_summary(proposal) for proposal in applied_by_role[role]],
            "blocked_proposals": [_proposal_summary(proposal) for proposal in blocked_by_role[role]],
            "optional_skills": optional_by_role.get(role, []),
            "optional_skill_count": len([record for record in optional_by_role.get(role, []) if record.get("status") == "active"]),
            "validation_errors": sorted(set(validation_errors)),
            "permission_profile": spec.permission_profile,
            "mcp_allowlist": list(spec.mcp_allowlist),
        }

    skills = _installed_skill_index(root, optional_records)
    projection_input = {
        "agents": {
            role: {
                "effective_skills": agent["effective_skills"],
                "codex_file_hash": agent["codex_file_hash"],
            }
            for role, agent in agents.items()
        },
        "skills": {skill_id: item["source_file_hash"] for skill_id, item in skills.items()},
        "applied_proposals": {
            role: [proposal["source_file_hash"] for proposal in agent["applied_proposals"]]
            for role, agent in agents.items()
        },
    }
    return {
        "root": str(root),
        "registry": "tradingcodex_service.application.agents",
        "agents": agents,
        "skills": skills,
        "projection_hash": stable_hash(projection_input),
        "projection_manifest": manifest,
    }


def _write_projection_indexes(
    root: Path,
    state: dict[str, Any],
    applied_by: str,
    generated_at: str,
    proposal_record: dict[str, Any] | None,
) -> None:
    agent_index = {
        "generated_at": generated_at,
        "source": "tradingcodex_service.application.agents",
        "projection_hash": state["projection_hash"],
        "agents": state["agents"],
    }
    skill_index = {
        "generated_at": generated_at,
        "source": "workspace-files",
        "projection_hash": state["projection_hash"],
        "skills": state["skills"],
    }
    manifest_roles = []
    for role, agent in state["agents"].items():
        manifest_roles.append(
            {
                "role": role,
                "codex_file": agent["codex_file"],
                "source_file_hash": agent["codex_file_hash"],
                "effective_skills": [
                    {
                        "skill": skill,
                        "source_file": state["skills"].get(skill, {}).get("source_file", ""),
                        "source_file_hash": state["skills"].get(skill, {}).get("source_file_hash"),
                    }
                    for skill in agent["effective_skills"]
                ],
            }
        )
    manifest = {
        "generated_at": generated_at,
        "applied_by": applied_by,
        "projection_hash": state["projection_hash"],
        "source": "file-native-agent-skill-projection",
        "proposal": _proposal_summary(proposal_record) if proposal_record else None,
        "roles": manifest_roles,
    }
    write_json(root / AGENT_INDEX_PATH, agent_index)
    write_json(root / SKILL_INDEX_PATH, skill_index)
    write_json(root / MANIFEST_PATH, manifest)


def _optional_record_payload(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    role = str(record.get("role") or "")
    skill_id = normalize_optional_skill_id(str(record.get("skill_id") or ""))
    source_file = str(record.get("source_file") or "")
    metadata_file = str(record.get("metadata_file") or "")
    status_file = str(record.get("status_file") or "")
    skill_path = root / source_file if source_file else _skill_path(root, skill_id, role=role)
    metadata_path = root / metadata_file if metadata_file else skill_path.parent / "agents" / "openai.yaml"
    status_path = root / status_file if status_file else skill_path.parent / OPTIONAL_SKILL_STATUS_FILE
    body = _safe_read(skill_path)
    validation = validate_optional_skill_payload(
        role,
        skill_id,
        str(record.get("title") or skill_id.replace("-", " ").title()),
        str(record.get("description") or ""),
        body,
    )
    status = str(record.get("status") or "active")
    if status not in OPTIONAL_SKILL_STATUSES:
        validation["errors"].append(f"unknown optional skill status: {status}")
    return {
        **record,
        "role": role,
        "skill_id": skill_id,
        "status": status,
        "source": "optional",
        "scope": str(record.get("scope") or "role"),
        "core": False,
        "installed": skill_path.exists(),
        "source_file": _relative_path(root, skill_path),
        "source_file_hash": _file_hash(skill_path),
        "metadata_file": _relative_path(root, metadata_path),
        "metadata_file_hash": _file_hash(metadata_path),
        "status_file": _relative_path(root, status_path),
        "status_file_hash": _file_hash(status_path),
        "validation_status": "blocked" if validation["errors"] else "valid",
        "validation_errors": validation["errors"],
        "risk_tags": validation["risk_tags"],
    }


def _strategy_record_payload(root: Path, skill_path: Path, *, legacy: bool) -> dict[str, Any]:
    skill_id = skill_path.parent.name
    metadata_path = skill_path.parent / "agents" / "openai.yaml"
    fields = _read_frontmatter_fields(skill_path)
    missing = sorted(STRATEGY_REQUIRED_FRONTMATTER - set(fields))
    validation_errors: list[str] = []
    if missing:
        validation_errors.append(f"missing strategy frontmatter: {', '.join(missing)}")
    if not skill_id.startswith(STRATEGY_SKILL_PREFIX):
        validation_errors.append("strategy skill id must start with strategy-")
    if fields.get("type") and fields.get("type") != "strategy":
        validation_errors.append("strategy skill frontmatter type must be strategy")
    if fields.get("managed_by") and fields.get("managed_by") != "strategy-creator":
        validation_errors.append("strategy skill frontmatter managed_by must be strategy-creator")
    body = _safe_read(skill_path)
    missing_sections = [section for section in STRATEGY_REQUIRED_SECTIONS if section not in body]
    if missing_sections:
        validation_errors.append(f"missing strategy sections: {', '.join(missing_sections)}")
    status = fields.get("status") or "unknown"
    active = status == "active" and not validation_errors
    label = fields.get("name") or skill_id.replace("-", " ").title()
    return {
        "id": skill_id,
        "label": label,
        "owner_roles": ["head-manager"],
        "risk_tags": ["strategy"],
        "user_visible": active,
        "source": "strategy",
        "scope": "strategy",
        "core": False,
        "legacy": legacy,
        "status": status,
        "active": active,
        "installed": skill_path.exists(),
        "source_file": _relative_path(root, skill_path),
        "source_file_hash": _file_hash(skill_path),
        "metadata_file": _relative_path(root, metadata_path),
        "metadata_file_hash": _file_hash(metadata_path),
        "validation_status": "blocked" if validation_errors else "valid",
        "validation_errors": validation_errors,
        "frontmatter": fields,
    }


def _project_agent_toml(root: Path, role: str, skills: list[str]) -> None:
    path = _agent_config_path(root, role)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    marker = "[[skills.config]]"
    body = text[: text.find(marker)].rstrip() if marker in text else text.rstrip()
    rendered = body + "\n\n" + _render_skill_config_blocks(root, skills, role=role)
    path.write_text(rendered.rstrip() + "\n", encoding="utf-8")


def _project_root_strategy_skills(root: Path) -> None:
    path = _agent_config_path(root, "head-manager")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    strategy_records = [record for record in read_strategy_skill_records(root, active_only=True) if not record.get("legacy")]
    rendered = "\n".join(
        f'[[skills.config]]\npath = "{(root / str(record["source_file"])).as_posix()}"\nenabled = true'
        for record in strategy_records
    )
    block = f"{STRATEGY_ROOT_CONFIG_START}\n{rendered}\n{STRATEGY_ROOT_CONFIG_END}".replace("\n\n", "\n")
    if STRATEGY_ROOT_CONFIG_START in text and STRATEGY_ROOT_CONFIG_END in text:
        pattern = re.compile(
            rf"{re.escape(STRATEGY_ROOT_CONFIG_START)}.*?{re.escape(STRATEGY_ROOT_CONFIG_END)}",
            re.S,
        )
        updated = pattern.sub(block, text)
    else:
        permissions_index = text.find("\n[permissions.")
        if permissions_index >= 0:
            updated = text[:permissions_index].rstrip() + "\n\n" + block + "\n" + text[permissions_index:]
        else:
            updated = text.rstrip() + "\n\n" + block + "\n"
    if updated != text:
        path.write_text(updated.rstrip() + "\n", encoding="utf-8")


def _render_skill_config_blocks(root: Path, skills: list[str], *, role: str | None = None) -> str:
    blocks = []
    for skill in skills:
        skill_path = _skill_path(root, skill, role=role)
        blocks.append(f'[[skills.config]]\npath = "{skill_path.as_posix()}"\nenabled = true')
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _rewrite_skill_proposal(root: Path, proposal: dict[str, Any], path: Path, status: str, applied_by: str, errors: list[str]) -> None:
    fields = {
        "id": proposal.get("id", path.stem),
        "type": proposal.get("type", "add"),
        "target": proposal.get("target", ""),
        "skill": proposal.get("skill", ""),
        "created_at": proposal.get("created_at", ""),
        "requires_validation": proposal.get("requires_validation", "true"),
        "status": status,
        "validation_status": "blocked" if errors else "valid",
        "applied_by": applied_by,
        "applied_at": now_iso(),
    }
    if errors:
        fields["validation_error"] = "; ".join(errors)
    _write_simple_yaml(path, fields)


def _installed_skill_index(root: Path, optional_records: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    skills: dict[str, dict[str, Any]] = {}
    for skill_id, spec in SKILL_SPECS.items():
        skill_path = _skill_path(root, skill_id)
        meta_path = skill_path.parent / "agents" / "openai.yaml"
        skills[skill_id] = {
            "id": skill_id,
            "label": spec.label,
            "owner_roles": list(spec.owner_roles),
            "risk_tags": list(spec.risk_tags),
            "user_visible": spec.user_visible,
            "source": "core",
            "scope": spec.scope,
            "core": True,
            "installed": skill_path.exists(),
            "source_file": _relative_path(root, skill_path),
            "source_file_hash": _file_hash(skill_path),
            "metadata_file": _relative_path(root, meta_path),
            "metadata_file_hash": _file_hash(meta_path),
        }
    for record in read_strategy_skill_records(root):
        skill_id = str(record.get("id") or "")
        if not skill_id or skill_id in skills:
            continue
        skills[skill_id] = record
    for record in optional_records or read_optional_skill_records(root, include_archived=True):
        skill_id = str(record.get("skill_id") or "")
        if not skill_id or skill_id in skills:
            continue
        skills[skill_id] = {
            "id": skill_id,
            "label": str(record.get("title") or skill_id.replace("-", " ").title()),
            "owner_roles": [record.get("role")],
            "risk_tags": list(record.get("risk_tags") or []),
            "user_visible": False,
            "source": "optional",
            "scope": record.get("scope", "role"),
            "core": False,
            "status": record.get("status"),
            "installed": bool(record.get("installed")),
            "source_file": record.get("source_file", ""),
            "source_file_hash": record.get("source_file_hash"),
            "metadata_file": record.get("metadata_file", ""),
            "metadata_file_hash": record.get("metadata_file_hash"),
            "status_file": record.get("status_file", ""),
            "status_file_hash": record.get("status_file_hash"),
            "validation_status": record.get("validation_status"),
            "validation_errors": record.get("validation_errors", []),
        }
    return skills


def _agent_spec_payload(spec: AgentSpec) -> dict[str, Any]:
    return {
        "role": spec.role,
        "label": spec.label,
        "group": spec.group,
        "permission_profile": spec.permission_profile,
        "builtin_skills": list(spec.builtin_skills),
        "forbidden_skill_tags": list(spec.forbidden_skill_tags),
        "mcp_allowlist": list(spec.mcp_allowlist),
    }


def _agent_config_path(root: Path, role: str) -> Path:
    if role == "head-manager":
        return root / ".codex" / "config.toml"
    return root / ".codex" / "agents" / f"{role}.toml"


def _skill_path(root: Path, skill: str, *, role: str | None = None) -> Path:
    spec = SKILL_SPECS.get(skill)
    if spec:
        if spec.scope == "subagent_shared":
            return root / SUBAGENT_SHARED_SKILL_DIR / skill / "SKILL.md"
        if spec.scope == "subagent_role":
            target_role = role or (spec.owner_roles[0] if spec.owner_roles else "")
            return root / SUBAGENT_SKILL_DIR / target_role / skill / "SKILL.md"
        return root / MAINAGENT_SKILL_DIR / skill / "SKILL.md"
    if role:
        role_path = root / SUBAGENT_SKILL_DIR / role / skill / "SKILL.md"
        if role_path.exists():
            return role_path
        shared_path = root / SUBAGENT_SHARED_SKILL_DIR / skill / "SKILL.md"
        if shared_path.exists():
            return shared_path
        return role_path
    for candidate in sorted((root / SUBAGENT_SKILL_DIR).glob(f"*/{skill}/SKILL.md")):
        return candidate
    return root / MAINAGENT_SKILL_DIR / skill / "SKILL.md"


def _parse_toml_skill_paths(text: str) -> list[str]:
    skills: list[str] = []
    patterns = [
        r'path\s*=\s*"[^"]+/\.agents/skills/([^"/]+)/SKILL\.md"',
        r'path\s*=\s*"[^"]+/\.tradingcodex/subagents/skills/(?:shared|[^"/]+)/([^"/]+)/SKILL\.md"',
        r'path\s*=\s*"[^"]+/\.tradingcodex/strategies/([^"/]+)/SKILL\.md"',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            skills.append(match.group(1))
    return list(dict.fromkeys(skills))


def _proposal_summary(proposal: dict[str, Any] | None) -> dict[str, Any] | None:
    if proposal is None:
        return None
    return {
        "id": proposal.get("id"),
        "type": proposal.get("type"),
        "target": proposal.get("target"),
        "skill": proposal.get("skill"),
        "status": proposal.get("status"),
        "path": proposal.get("path"),
        "source_file_hash": proposal.get("source_file_hash"),
    }


def _file_hash(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _optional_record_roles(record: dict[str, Any], scope_name: str) -> list[str]:
    if scope_name != "shared":
        return [scope_name]
    roles = record.get("roles")
    if isinstance(roles, list):
        return [str(role) for role in roles if str(role) in EXPECTED_SUBAGENTS]
    if isinstance(roles, str):
        parsed = [item.strip() for item in roles.split(",") if item.strip()]
        return [item for item in parsed if item in EXPECTED_SUBAGENTS]
    role = str(record.get("role") or "")
    if role in EXPECTED_SUBAGENTS:
        return [role]
    return list(EXPECTED_SUBAGENTS)


def _unique_existing(root: Path, skills: list[str], *, role: str | None = None) -> list[str]:
    unique = list(dict.fromkeys(skills))
    if not (root / MAINAGENT_SKILL_DIR).exists() and not (root / SUBAGENT_SKILL_DIR).exists():
        return unique
    return [skill for skill in unique if _skill_path(root, skill, role=role).exists()]


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _read_markdown_body(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end < 0:
        return text
    body_start = text.find("\n", end + 4)
    return text[body_start + 1 :] if body_start >= 0 else ""


def _render_basic_skill_markdown(skill_id: str, description: str, body: str) -> str:
    frontmatter = {
        "name": skill_id,
        "description": description or skill_id.replace("-", " ").title(),
    }
    return _render_frontmatter(frontmatter) + body.strip() + "\n"


def _render_strategy_skill_markdown(strategy_id: str, title: str, description: str, body: str, language: str, status: str) -> str:
    frontmatter = {
        "name": strategy_id,
        "description": description,
        "type": "strategy",
        "status": status,
        "language": language or "unknown",
        "managed_by": "strategy-creator",
        "owner": "user",
        "last_reviewed": now_iso()[:10],
    }
    return _render_frontmatter(frontmatter) + _ensure_strategy_sections(title, body).strip() + "\n"


def _render_frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _ensure_strategy_sections(title: str, body: str) -> str:
    text = body.strip() or _default_strategy_body(title)
    if not text.startswith("# "):
        text = f"# {title}\n\n{text}"
    for section in STRATEGY_REQUIRED_SECTIONS:
        if section not in text:
            text = text.rstrip() + f"\n\n{section}\nnot specified\n"
    return text


def _default_strategy_body(title: str) -> str:
    sections = "\n\n".join(f"{section}\nnot specified" for section in STRATEGY_REQUIRED_SECTIONS)
    return f"# {title}\n\n{sections}\n"


def _render_openai_yaml(display_name: str, short_description: str, default_prompt: str) -> str:
    short = re.sub(r"\s+", " ", short_description or display_name).strip()
    if len(short) < 25:
        short = (short + " for TradingCodex workflows").strip()
    if len(short) > 64:
        short = short[:64].rstrip()
    return "\n".join(
        [
            "interface:",
            f"  display_name: {_yaml_scalar(display_name)}",
            f"  short_description: {_yaml_scalar(short)}",
            f"  default_prompt: {_yaml_scalar(default_prompt)}",
            "policy:",
            "  allow_implicit_invocation: true",
            "",
        ]
    )


def _write_simple_yaml(path: Path, fields: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in fields.items():
        if value is None:
            continue
        lines.append(f"{key}: {_yaml_scalar(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_simple_yaml(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return data
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        data[key.strip()] = _unquote_yaml_scalar(raw_value.strip())
    return data


def _read_frontmatter_fields(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        fields[key.strip()] = _unquote_yaml_scalar(raw_value.strip())
    return fields


def _yaml_scalar(value: Any) -> str:
    text = str(value)
    if text in {"true", "false"}:
        return text
    if re.fullmatch(r"[A-Za-z0-9._/@:-]+", text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value
