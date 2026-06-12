from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingcodex_service.application.common import now_iso, read_json, sanitize_id, stable_hash, write_json


@dataclass(frozen=True)
class SkillSpec:
    id: str
    label: str
    owner_roles: tuple[str, ...]
    risk_tags: tuple[str, ...] = ()
    user_visible: bool = False


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
    "external-data-source-gate",
    "manage-subagents",
    "head-manager-interview",
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
    "external-data-source-gate": SkillSpec("external-data-source-gate", "External Data Source Gate", ("head-manager",) + RESEARCH_ROLES),
    "manage-subagents": SkillSpec("manage-subagents", "Manage Subagents", ("head-manager",)),
    "head-manager-interview": SkillSpec("head-manager-interview", "Head Manager Interview", ("head-manager",), user_visible=True),
    "synthesize-decision": SkillSpec("synthesize-decision", "Synthesize Decision", ("head-manager",)),
    "postmortem": SkillSpec("postmortem", "Postmortem", ("head-manager",), user_visible=True),
    "collect-evidence": SkillSpec("collect-evidence", "Collect Evidence", RESEARCH_ROLES),
    "fundamental-analysis": SkillSpec("fundamental-analysis", "Fundamental Analysis", ("fundamental-analyst",)),
    "technical-analysis": SkillSpec("technical-analysis", "Technical Analysis", ("technical-analyst",)),
    "news-analysis": SkillSpec("news-analysis", "News Analysis", ("news-analyst",)),
    "macro-analysis": SkillSpec("macro-analysis", "Macro Analysis", ("macro-analyst",)),
    "instrument-analysis": SkillSpec("instrument-analysis", "Instrument Analysis", ("instrument-analyst",)),
    "valuation-review": SkillSpec("valuation-review", "Valuation Review", ("valuation-analyst",)),
    "portfolio-review": SkillSpec("portfolio-review", "Portfolio Review", ("portfolio-manager",)),
    "create-order-intent": SkillSpec("create-order-intent", "Create Order Intent", ("portfolio-manager",), risk_tags=("order",)),
    "review-risk": SkillSpec("review-risk", "Review Risk", ("risk-manager",)),
    "policy-review": SkillSpec("policy-review", "Policy Review", ("risk-manager",), risk_tags=("approval",)),
    "approve-order": SkillSpec("approve-order", "Approve Order", ("risk-manager",), risk_tags=("approval", "order")),
    "execute-paper-order": SkillSpec("execute-paper-order", "Execute Paper Order", ("execution-operator",), risk_tags=("execution", "order")),
}


ROLE_SKILL_MAP: dict[str, list[str]] = {role: list(spec.builtin_skills) for role, spec in AGENT_SPECS.items()}
USER_VISIBLE_SKILLS = [skill.id for skill in SKILL_SPECS.values() if skill.user_visible]
EXPECTED_SUBAGENTS = [role for role in AGENT_SPECS if role != "head-manager"]
EXPECTED_SKILLS = sorted(SKILL_SPECS)
ROLE_PERMISSION_PROFILES = {role: spec.permission_profile for role, spec in AGENT_SPECS.items() if role != "head-manager"}

PROPOSAL_DIR = Path(".tradingcodex/mainagent/skill-change-proposals")
GENERATED_DIR = Path(".tradingcodex/generated")
MANIFEST_PATH = GENERATED_DIR / "projection-manifest.json"
AGENT_INDEX_PATH = GENERATED_DIR / "agent-index.json"
SKILL_INDEX_PATH = GENERATED_DIR / "skill-index.json"


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
    blocked_tags = sorted(set(agent.forbidden_skill_tags).intersection(skill_spec.risk_tags))
    if blocked_tags:
        errors.append(f"{role} cannot receive {skill}; blocked risk tags: {', '.join(blocked_tags)}")
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
    skill_root_exists = (root / ".agents" / "skills").exists()
    for role, spec in AGENT_SPECS.items():
        applied_skills = [str(item.get("skill")) for item in applied_by_role[role] if item.get("skill")]
        effective = _unique_existing(root, [*spec.builtin_skills, *applied_skills])
        agent_file = _agent_config_path(root, role)
        projected_skills = _parse_toml_skill_paths(agent_file.read_text(encoding="utf-8")) if agent_file.exists() else []
        validation_errors: list[str] = []
        for skill in effective:
            validation_errors.extend(validate_skill_assignment(role, skill))
        agents[role] = {
            **_agent_spec_payload(spec),
            "codex_file": _relative_path(root, agent_file) if agent_file else "",
            "codex_file_hash": _file_hash(agent_file) if agent_file else None,
            "builtin_skills": list(spec.builtin_skills)
            if not skill_root_exists
            else [skill for skill in spec.builtin_skills if _skill_path(root, skill).exists()],
            "effective_skills": effective,
            "projected_skills": projected_skills,
            "pending_proposals": [_proposal_summary(proposal) for proposal in pending_by_role[role]],
            "applied_proposals": [_proposal_summary(proposal) for proposal in applied_by_role[role]],
            "blocked_proposals": [_proposal_summary(proposal) for proposal in blocked_by_role[role]],
            "validation_errors": sorted(set(validation_errors)),
            "permission_profile": spec.permission_profile,
            "mcp_allowlist": list(spec.mcp_allowlist),
        }

    skills = _installed_skill_index(root)
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


def _project_agent_toml(root: Path, role: str, skills: list[str]) -> None:
    path = _agent_config_path(root, role)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    marker = "[[skills.config]]"
    body = text[: text.find(marker)].rstrip() if marker in text else text.rstrip()
    rendered = body + "\n\n" + _render_skill_config_blocks(root, skills)
    path.write_text(rendered.rstrip() + "\n", encoding="utf-8")


def _render_skill_config_blocks(root: Path, skills: list[str]) -> str:
    blocks = []
    for skill in skills:
        skill_path = _skill_path(root, skill)
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


def _installed_skill_index(root: Path) -> dict[str, dict[str, Any]]:
    skills: dict[str, dict[str, Any]] = {}
    skill_root = root / ".agents" / "skills"
    for skill_id, spec in SKILL_SPECS.items():
        skill_path = skill_root / skill_id / "SKILL.md"
        meta_path = skill_root / skill_id / "agents" / "openai.yaml"
        skills[skill_id] = {
            "id": skill_id,
            "label": spec.label,
            "owner_roles": list(spec.owner_roles),
            "risk_tags": list(spec.risk_tags),
            "user_visible": spec.user_visible,
            "installed": skill_path.exists(),
            "source_file": _relative_path(root, skill_path),
            "source_file_hash": _file_hash(skill_path),
            "metadata_file": _relative_path(root, meta_path),
            "metadata_file_hash": _file_hash(meta_path),
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


def _skill_path(root: Path, skill: str) -> Path:
    return root / ".agents" / "skills" / skill / "SKILL.md"


def _parse_toml_skill_paths(text: str) -> list[str]:
    skills: list[str] = []
    for match in re.finditer(r'path\s*=\s*"([^"]+/\.agents/skills/([^"/]+)/SKILL\.md)"', text):
        skills.append(match.group(2))
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


def _unique_existing(root: Path, skills: list[str]) -> list[str]:
    unique = list(dict.fromkeys(skills))
    if not (root / ".agents" / "skills").exists():
        return unique
    return [skill for skill in unique if _skill_path(root, skill).exists()]


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
