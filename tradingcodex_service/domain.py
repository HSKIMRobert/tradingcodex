from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TRADINGCODEX_VERSION = "0.1.0a1"
DEFAULT_MAX_SINGLE_ORDER_KRW = 100_000_000
DEFAULT_ALLOWED_ADAPTERS = {"stub-execution", "paper-trading"}
DEFAULT_PAPER_CASH_KRW = 100_000_000
DEFAULT_PORTFOLIO_ID = "default-paper"
DEFAULT_ACCOUNT_ID = "local-paper"
DEFAULT_STRATEGY_ID = "default-strategy"
_RUNTIME_DB_READY = False
_RUNTIME_DB_NAME = ""
EXPLICIT_DENY_ACTIONS = {
    "api_key.read",
    "api_key.rotate",
    "secret.read",
    "broker.raw_api",
    "broker_api.direct_call",
    "approval.self_issue",
    "approval_receipt.self_issue",
    "execute_order",
    "order.execute",
    "trade.execute",
    "trading.execute",
    "cash.withdraw",
    "cash.transfer",
    "permissions.write",
    "policy.write",
    "mcp.tradingcodex.write_policy_and_execute",
}

ROLE_SKILL_MAP: dict[str, list[str]] = {
    "head-manager": [
        "orchestrate-workflow",
        "investment-workflow-map",
        "scenario-quality-gates",
        "external-data-source-gate",
        "manage-subagents",
        "head-manager-interview",
        "synthesize-decision",
        "postmortem",
    ],
    "fundamental-analyst": ["external-data-source-gate", "collect-evidence", "fundamental-analysis"],
    "technical-analyst": ["external-data-source-gate", "collect-evidence", "technical-analysis"],
    "news-analyst": ["external-data-source-gate", "collect-evidence", "news-analysis"],
    "macro-analyst": ["external-data-source-gate", "collect-evidence", "macro-analysis"],
    "instrument-analyst": ["external-data-source-gate", "collect-evidence", "instrument-analysis"],
    "valuation-analyst": ["external-data-source-gate", "valuation-review"],
    "portfolio-manager": ["portfolio-review", "create-order-intent"],
    "risk-manager": ["review-risk", "policy-review", "approve-order"],
    "execution-operator": ["execute-paper-order"],
}

USER_VISIBLE_SKILLS = [
    "orchestrate-workflow",
    "head-manager-interview",
    "postmortem",
]

EXPECTED_SUBAGENTS = [role for role in ROLE_SKILL_MAP if role != "head-manager"]
EXPECTED_SKILLS = sorted({skill for skills in ROLE_SKILL_MAP.values() for skill in skills})
ROLE_PERMISSION_PROFILES = {
    "fundamental-analyst": "tradingcodex-fundamental",
    "technical-analyst": "tradingcodex-technical",
    "news-analyst": "tradingcodex-news",
    "macro-analyst": "tradingcodex-macro",
    "instrument-analyst": "tradingcodex-instrument",
    "valuation-analyst": "tradingcodex-valuation",
    "portfolio-manager": "tradingcodex-portfolio",
    "risk-manager": "tradingcodex-risk",
    "execution-operator": "tradingcodex-execution",
}


@dataclass(frozen=True)
class RuntimePolicy:
    max_single_order_krw: int = DEFAULT_MAX_SINGLE_ORDER_KRW
    allowed_adapters: frozenset[str] = frozenset(DEFAULT_ALLOWED_ADAPTERS)
    source: tuple[str, ...] = ("default-runtime-policy",)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def sanitize_id(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-") or "unknown"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")


def tradingcodex_home() -> Path:
    return Path(os.environ.get("TRADINGCODEX_HOME", "~/.tradingcodex")).expanduser().resolve()


def tradingcodex_state_dir() -> Path:
    return tradingcodex_home() / "state"


def tradingcodex_db_path() -> Path:
    configured = os.environ.get("TRADINGCODEX_DB_NAME")
    if configured:
        return Path(configured).expanduser().resolve()
    return tradingcodex_state_dir() / "tradingcodex.sqlite3"


def configure_tradingcodex_database(workspace_root: Path | str | None = None) -> None:
    global _RUNTIME_DB_READY, _RUNTIME_DB_NAME
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")
    db_path = tradingcodex_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_name = str(db_path)
    if os.environ.get("TRADINGCODEX_DB_NAME") == db_name and _RUNTIME_DB_NAME == db_name:
        return
    os.environ["TRADINGCODEX_DB_NAME"] = db_name
    if _RUNTIME_DB_NAME and _RUNTIME_DB_NAME != db_name:
        _RUNTIME_DB_READY = False
    try:
        from django.conf import settings
        from django.db import connections

        if settings.configured:
            current_name = settings.DATABASES["default"].get("NAME")
            settings.DATABASES["default"]["NAME"] = db_name
            settings.DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = int(os.environ.get("TRADINGCODEX_SQLITE_TIMEOUT", "30"))
            connections["default"].settings_dict["NAME"] = db_name
            connections["default"].settings_dict.setdefault("OPTIONS", {})["timeout"] = int(os.environ.get("TRADINGCODEX_SQLITE_TIMEOUT", "30"))
            if current_name != db_name:
                connections.close_all()
                _RUNTIME_DB_READY = False
    except Exception:
        pass
    _RUNTIME_DB_NAME = db_name


def configure_workspace_database(workspace_root: Path | str | None = None) -> None:
    configure_tradingcodex_database(workspace_root)


def workspace_context_payload(workspace_root: Path | str | None = None) -> dict[str, Any]:
    raw_root = workspace_root or os.environ.get("TRADINGCODEX_WORKSPACE_ROOT") or os.getcwd()
    root = Path(raw_root).expanduser().resolve()
    return {
        "path_hash": hashlib.sha256(str(root).encode("utf-8")).hexdigest(),
        "project_name": root.name or "tradingcodex-workspace",
        "path": str(root),
        "git_remote": _git_remote(root),
        "git_branch": _git_branch(root),
        "db_path": str(tradingcodex_db_path()),
    }


def persist_workspace_context_if_available(workspace_root: Path | str | None = None) -> dict[str, Any]:
    context = workspace_context_payload(workspace_root)
    try:
        ensure_runtime_database(None)
        from apps.harness.models import WorkspaceContext

        WorkspaceContext.objects.update_or_create(
            path_hash=context["path_hash"],
            defaults={
                "project_name": context["project_name"],
                "path": context["path"],
                "git_remote": context["git_remote"],
                "git_branch": context["git_branch"],
                "metadata": {"db_path": context["db_path"]},
            },
        )
    except Exception:
        pass
    return context


def ensure_runtime_database(workspace_root: Path | str | None = None) -> None:
    global _RUNTIME_DB_READY
    configure_tradingcodex_database(workspace_root)
    import django
    from django.apps import apps
    from django.core.management import call_command

    if not apps.ready:
        django.setup()
    if _RUNTIME_DB_READY or os.environ.get("TRADINGCODEX_AUTO_MIGRATE", "1") == "0":
        return
    with tradingcodex_file_lock("migrate"):
        call_command("migrate", interactive=False, verbosity=0, fake_initial=True)
        _sync_missing_runtime_columns()
        _RUNTIME_DB_READY = True


@contextmanager
def workspace_file_lock(workspace_root: Path | str, name: str):
    with tradingcodex_file_lock(name):
        yield


@contextmanager
def tradingcodex_file_lock(name: str):
    lock_path = tradingcodex_state_dir() / f"tradingcodex.{sanitize_id(name)}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        try:
            import fcntl

            fcntl.flock(lock_file, fcntl.LOCK_EX)
        except Exception:
            pass
        try:
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(lock_file, fcntl.LOCK_UN)
            except Exception:
                pass


def _runtime_model_tables_present() -> bool:
    try:
        from django.apps import apps
        from django.db import connection

        existing = set(connection.introspection.table_names())
        required = {
            model._meta.db_table
            for model in apps.get_models()
            if model._meta.managed and not model._meta.proxy
        }
        if not bool(required) or not required.issubset(existing):
            return False
        for model in apps.get_models():
            if not model._meta.managed or model._meta.proxy:
                continue
            columns = {
                column.name
                for column in connection.introspection.get_table_description(connection.cursor(), model._meta.db_table)
            }
            expected = {field.column for field in model._meta.local_concrete_fields}
            if not expected.issubset(columns):
                return False
        return True
    except Exception:
        return False


def _sync_missing_runtime_columns() -> None:
    try:
        from django.apps import apps
        from django.db import connection

        with connection.schema_editor() as schema_editor:
            for model in apps.get_models():
                if not model._meta.managed or model._meta.proxy:
                    continue
                existing_tables = set(connection.introspection.table_names())
                if model._meta.db_table not in existing_tables:
                    continue
                columns = {
                    column.name
                    for column in connection.introspection.get_table_description(connection.cursor(), model._meta.db_table)
                }
                for field in model._meta.local_concrete_fields:
                    if field.column not in columns:
                        schema_editor.add_field(model, field)
    except Exception:
        return


def _git_dir(root: Path) -> Path | None:
    dotgit = root / ".git"
    if dotgit.is_dir():
        return dotgit
    if dotgit.is_file():
        text = _safe_read(dotgit).strip()
        match = re.match(r"gitdir:\s*(.+)", text)
        if match:
            gitdir = Path(match.group(1))
            return gitdir if gitdir.is_absolute() else (root / gitdir).resolve()
    return None


def _git_branch(root: Path) -> str:
    gitdir = _git_dir(root)
    if not gitdir:
        return ""
    head = _safe_read(gitdir / "HEAD").strip()
    match = re.match(r"ref:\s+refs/heads/(.+)", head)
    return match.group(1) if match else head[:12]


def _git_remote(root: Path) -> str:
    gitdir = _git_dir(root)
    config = _safe_read(gitdir / "config") if gitdir else _safe_read(root / ".git" / "config")
    match = re.search(r'\[remote "origin"\][^\[]*?\n\s*url\s*=\s*(.+)', config)
    return match.group(1).strip() if match else ""


def read_runtime_policy(workspace_root: Path | str) -> RuntimePolicy:
    root = Path(workspace_root)
    max_single_order = DEFAULT_MAX_SINGLE_ORDER_KRW
    allowed_adapters = set(DEFAULT_ALLOWED_ADAPTERS)
    source = [".tradingcodex/policies/access-policies.yaml", ".tradingcodex/config.yaml"]

    access_text = _safe_read(root / ".tradingcodex" / "policies" / "access-policies.yaml")
    max_match = re.search(r"order\.estimated_notional_krw\s*<=\s*(\d+)", access_text)
    if max_match:
        max_single_order = int(max_match.group(1))
    brokers_match = re.search(r"order\.broker\s+in\s+\[([^\]]+)\]", access_text)
    if brokers_match:
        parsed = re.findall(r'"([^"]+)"', brokers_match.group(1))
        if parsed:
            allowed_adapters = set(parsed)

    config_text = _safe_read(root / ".tradingcodex" / "config.yaml")
    section = re.search(r"enabled_adapters:[ \t]*\n((?:[ \t]*-[ \t]*[A-Za-z0-9._-]+[ \t]*(?:\n|$))+)", config_text)
    if section:
        configured = set(re.findall(r"^[ \t]*-[ \t]*([A-Za-z0-9._-]+)[ \t]*$", section.group(1), flags=re.M))
        if configured:
            allowed_adapters &= configured

    return RuntimePolicy(max_single_order, frozenset(allowed_adapters), tuple(source))


def read_restricted_symbols(workspace_root: Path | str) -> set[str]:
    text = _safe_read(Path(workspace_root) / ".tradingcodex" / "policies" / "restricted-list.yaml")
    symbols: set[str] = set()
    try:
        ensure_runtime_database(workspace_root)
        from apps.policy.models import RestrictedSymbol

        symbols.update(symbol.upper() for symbol in RestrictedSymbol.objects.filter(active=True).values_list("symbol", flat=True))
    except Exception:
        pass
    inline = re.search(r"restricted_symbols\s*:\s*\[([^\]]*)\]", text)
    if inline:
        for raw in inline.group(1).split(","):
            symbol = raw.strip().strip("'\"")
            if symbol:
                symbols.add(symbol.upper())
    block = re.search(r"restricted_symbols\s*:\s*\n((?:[ \t]*-[ \t]*[A-Za-z0-9_.:-]+[ \t]*(?:\n|$))+)", text)
    if block:
        symbols.update(symbol.upper() for symbol in re.findall(r"^[ \t]*-[ \t]*([A-Za-z0-9_.:-]+)[ \t]*$", block.group(1), flags=re.M))
    symbols.update(symbol.upper() for symbol in re.findall(r"\bsymbol\s*:\s*['\"]?([A-Za-z0-9_.:-]+)['\"]?", text))
    return symbols


def evaluate_policy(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    ensure_runtime_database(workspace_root)
    from apps.policy.services import capability_check, sync_builtin_principals_and_capabilities

    sync_builtin_principals_and_capabilities()
    policy = read_runtime_policy(workspace_root)
    order = resolve_order_intent(Path(workspace_root), args)
    receipt = resolve_approval_receipt(Path(workspace_root), args, order)
    principal_id = args.get("principal_id") or "unknown"
    action = args.get("action") or "unknown"
    reasons: list[str] = []
    capability_allowed, capability_reasons = capability_check(principal_id, action, args.get("resource"))
    if not capability_allowed:
        reasons.extend(capability_reasons)

    if action in EXPLICIT_DENY_ACTIONS:
        reasons.append(f"explicit deny action: {action}")
    if action.startswith(("broker_api.", "broker.")):
        reasons.append("direct broker API actions are explicitly denied")
    if "live" in action.lower() and re.search(r"order|execution|submit|broker", action.lower()):
        reasons.append("live execution actions are disabled in the initial core")
    if "live" in str(args.get("resource") or "").lower() and re.search(r"order|execution|submit|broker", action.lower()):
        reasons.append("live execution resources are disabled in the initial core")
    if action in {"approval.create", "approval_receipt.create"} and principal_id != "risk-manager":
        reasons.append("only risk-manager can create approval receipts")
    if action == "mcp.tradingcodex.submit_approved_order" and principal_id != "execution-operator":
        reasons.append("only execution-operator can submit approved orders")
    if order.get("broker") == "live" and not (Path(workspace_root) / ".tradingcodex" / "mcp" / "adapters" / "live.py").exists():
        reasons.append("live broker adapter is not installed in this workspace")
    if order.get("broker") and order["broker"] not in policy.allowed_adapters:
        reasons.append(f"adapter not enabled: {order['broker']}")

    notional = _number(order.get("estimated_notional_krw"))
    if order.get("estimated_notional_krw") not in (None, "") and (notional is None or notional <= 0):
        reasons.append("estimated_notional_krw must be a positive number")
    elif notional is not None and notional > policy.max_single_order_krw:
        reasons.append(f"estimated_notional_krw exceeds {policy.max_single_order_krw}")

    if order.get("symbol") and str(order["symbol"]).upper() in read_restricted_symbols(workspace_root):
        reasons.append(f"symbol is restricted: {order['symbol']}")
    if args.get("require_approval_check") and receipt.get("valid") is not True:
        reasons.append("approval_receipt.valid == false")

    decision = "allow" if not reasons else "deny"
    result = {
        "decision": decision,
        "reasons": reasons,
        "enforced_by": ["TradingCodex MCP"],
        "policy_source": list(policy.source),
        "principal_id": principal_id,
        "action": action,
        "resource": args.get("resource"),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }
    write_policy_decision_if_available(workspace_root, result)
    return result


def simulate_policy(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    return evaluate_policy(workspace_root, args)


def validate_order_intent(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    order = resolve_order_intent(Path(workspace_root), args)
    reasons: list[str] = []
    for field in ["id", "symbol", "side", "quantity", "limit_price", "currency", "broker", "estimated_notional_krw", "created_by", "created_at"]:
        if order.get(field) in (None, ""):
            reasons.append(f"missing {field}")
    if order.get("side") not in ("buy", "sell"):
        reasons.append("side must be buy or sell")
    _validate_positive(order.get("quantity"), "quantity", reasons)
    _validate_positive(order.get("limit_price"), "limit_price", reasons)
    _validate_positive(order.get("estimated_notional_krw"), "estimated_notional_krw", reasons)
    policy = evaluate_policy(workspace_root, {**args, "action": args.get("action") or "order_intent.validate", "order_intent": order})
    all_reasons = list(dict.fromkeys(reasons + policy["reasons"]))
    result = {"valid": not all_reasons and policy["decision"] == "allow", "reasons": all_reasons, "policy": policy, "db_canonical": True, "workspace_context": workspace_context_payload(workspace_root)}
    persist_order_intent_if_available(Path(workspace_root), order, result)
    return result


def validate_approval_receipt(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    order = resolve_order_intent(root, args)
    receipt = resolve_approval_receipt(root, args, order)
    reasons: list[str] = []
    for field in ["id", "order_intent_id", "approved_by", "valid", "expires_at"]:
        if receipt.get(field) in (None, ""):
            reasons.append(f"missing {field}")
    if receipt.get("valid") is not True:
        reasons.append("approval_receipt.valid must be true")
    if order.get("id") and receipt.get("order_intent_id") != order["id"]:
        reasons.append("approval_receipt.order_intent_id does not match order_intent.id")
    if order.get("created_by") and receipt.get("approved_by") == order["created_by"]:
        reasons.append("order creator cannot approve the same order")
    expires_at = _parse_datetime(receipt.get("expires_at"))
    if receipt.get("expires_at") and expires_at is None:
        reasons.append("approval_receipt.expires_at is not a valid date")
    if expires_at and expires_at <= datetime.now(timezone.utc):
        reasons.append("approval receipt is expired")
    return {"valid": not reasons, "reasons": reasons, "db_canonical": True, "workspace_context": workspace_context_payload(workspace_root)}


def create_approval_receipt(workspace_root: Path | str, order: dict[str, Any], approved_by: str = "risk-manager", expires_hours: int = 24) -> dict[str, Any]:
    root = Path(workspace_root)
    validation = validate_order_intent(root, {"principal_id": approved_by, "order_intent": order})
    if not validation["valid"]:
        rejected = {"status": "rejected", "order_intent_id": order.get("id"), "reasons": validation["reasons"], "db_canonical": True, "workspace_context": workspace_context_payload(root)}
        write_rejected_order(root, order, validation["reasons"])
        write_audit_event(root, {"type": "approval.rejected", "payload": rejected}, principal_id=approved_by, source="service")
        return rejected
    approval_policy = evaluate_policy(root, {"principal_id": approved_by, "action": "approval_receipt.create", "order_intent": order})
    if approval_policy["decision"] != "allow":
        rejected = {"status": "rejected", "order_intent_id": order.get("id"), "reasons": approval_policy["reasons"], "db_canonical": True, "workspace_context": workspace_context_payload(root)}
        write_rejected_order(root, order, approval_policy["reasons"])
        write_audit_event(root, {"type": "approval.rejected", "payload": rejected}, principal_id=approved_by, source="service")
        return rejected
    if approved_by == order.get("created_by"):
        raise ValueError("order creator cannot approve the same order")
    created = datetime.now(timezone.utc)
    receipt = {
        "id": f"approval-{sanitize_id(order['id'])}-{created.strftime('%Y%m%dT%H%M%S%fZ')}",
        "order_intent_id": order["id"],
        "approved_by": approved_by,
        "valid": True,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "expires_at": (created + timedelta(hours=expires_hours)).isoformat().replace("+00:00", "Z"),
        "policy_decision": validation["policy"],
    }
    receipt_validation = validate_approval_receipt(root, {"order_intent": order, "approval_receipt": receipt})
    if not receipt_validation["valid"]:
        return {"status": "rejected", "order_intent_id": order.get("id"), "reasons": receipt_validation["reasons"], "db_canonical": True, "workspace_context": workspace_context_payload(root)}
    persist_order_intent_if_available(root, order, validation)
    persist_approval_receipt_if_available(root, receipt)
    write_json(root / "trading" / "orders" / "approved" / f"{sanitize_id(order['id'])}.order_intent.json", order)
    write_json(root / "trading" / "approvals" / f"{sanitize_id(order['id'])}.approval_receipt.json", receipt)
    result = {
        "status": "approved",
        "order_intent_id": order["id"],
        "approved_order_path": f"trading/orders/approved/{sanitize_id(order['id'])}.order_intent.json",
        "approval_receipt_path": f"trading/approvals/{sanitize_id(order['id'])}.approval_receipt.json",
        "db_canonical": True,
        "workspace_context": workspace_context_payload(root),
    }
    write_audit_event(root, {"type": "approval.accepted", "payload": result}, principal_id=approved_by, source="service")
    return result


def submit_approved_order(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    order = resolve_order_intent(root, args)
    receipt = resolve_approval_receipt(root, args, order)
    principal_id = args.get("principal_id") or "execution-operator"
    order_validation = validate_order_intent(root, {"principal_id": principal_id, "order_intent": order})
    receipt_validation = validate_approval_receipt(root, {"order_intent": order, "approval_receipt": receipt})
    policy = evaluate_policy(root, {
        "principal_id": principal_id,
        "action": "mcp.tradingcodex.submit_approved_order",
        "order_intent": order,
        "approval_receipt": receipt,
        "require_approval_check": True,
    })
    if not order_validation["valid"] or not receipt_validation["valid"] or policy["decision"] != "allow":
        rejected = {
            "status": "rejected",
            "order_intent_id": order.get("id"),
            "reasons": order_validation["reasons"] + receipt_validation["reasons"] + policy["reasons"],
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(root, {"type": "submit_approved_order.rejected", "payload": rejected}, principal_id=principal_id, source="mcp")
        return rejected
    ensure_runtime_database(root)
    from apps.orders.services import finalize_execution_reservation, reserve_execution

    portfolio_id, account_id, strategy_id = portfolio_keys(order)
    reservation = reserve_execution(
        order=order,
        receipt=receipt,
        adapter=order.get("broker", ""),
        portfolio_id=portfolio_id,
        account_id=account_id,
        strategy_id=strategy_id,
        workspace_context=workspace_context_payload(root),
        principal_id=principal_id,
    )
    if not reservation.created:
        rejected = {
            "status": "rejected",
            "order_intent_id": order.get("id"),
            "idempotency_key": reservation.idempotency_key,
            "reasons": [f"order already has an execution result: {reservation.execution.status}"],
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(root, {"type": "submit_approved_order.duplicate", "payload": rejected}, principal_id=principal_id, source="mcp")
        return rejected
    try:
        adapter_result = submit_with_adapter(root, order)
    except Exception as exc:
        rejected = {
            "status": "rejected",
            "order_intent_id": order.get("id"),
            "adapter": order.get("broker"),
            "reasons": [f"adapter error: {exc}"],
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        finalize_execution_reservation(reservation.execution, rejected)
        write_audit_event(root, {"type": "submit_approved_order.adapter_error", "payload": rejected}, principal_id=principal_id, source="mcp")
        return rejected
    accepted = {"status": "accepted", "order_intent_id": order["id"], "adapter": order["broker"], "idempotency_key": reservation.idempotency_key, "result": adapter_result, "db_canonical": True, "workspace_context": workspace_context_payload(root)}
    persist_order_intent_if_available(root, order)
    persist_approval_receipt_if_available(root, receipt)
    finalize_execution_reservation(reservation.execution, accepted)
    write_json(root / "trading" / "orders" / "executed" / f"{sanitize_id(order['id'])}.execution_result.json", {
        "order_intent_id": order["id"],
        "approval_receipt_id": receipt.get("id"),
        "idempotency_key": reservation.idempotency_key,
        "result": accepted,
    })
    write_audit_event(root, {"type": "submit_approved_order.accepted", "payload": accepted}, principal_id=principal_id, source="mcp")
    return accepted


def submit_with_adapter(root: Path, order: dict[str, Any]) -> dict[str, Any]:
    broker = order.get("broker")
    if broker == "stub-execution":
        return {
            "adapter": "stub-execution",
            "broker_order_id": f"stub-{order['id']}",
            "status": "stubbed",
            "submitted_at": now_iso(),
            "order": order,
        }
    if broker == "paper-trading":
        return submit_paper_order(root, order)
    raise ValueError(f"Adapter is not enabled: {broker}")


def submit_paper_order(root: Path, order: dict[str, Any]) -> dict[str, Any]:
    portfolio_id, account_id, strategy_id = portfolio_keys(order)
    state = load_paper_portfolio_state(root, portfolio_id, account_id, strategy_id)
    symbol = str(order["symbol"]).upper()
    quantity = float(order["quantity"])
    price = float(order["limit_price"])
    notional = quantity * price
    current = state.setdefault("positions", {}).get(symbol, {"quantity": 0, "average_price": 0, "currency": order.get("currency", "KRW")})
    if order["side"] == "buy":
        if float(state.get("cash_krw", 0)) < notional:
            raise ValueError(f"insufficient paper cash: required {notional}, available {state.get('cash_krw', 0)}")
        next_quantity = float(current.get("quantity", 0)) + quantity
        current["average_price"] = 0 if next_quantity == 0 else ((float(current.get("quantity", 0)) * float(current.get("average_price", 0))) + notional) / next_quantity
        current["quantity"] = next_quantity
        state["cash_krw"] = float(state.get("cash_krw", 0)) - notional
    else:
        if float(current.get("quantity", 0)) < quantity:
            raise ValueError(f"insufficient paper position: required {quantity}, available {current.get('quantity', 0)}")
        current["quantity"] = float(current.get("quantity", 0)) - quantity
        state["cash_krw"] = float(state.get("cash_krw", 0)) + notional
        if current["quantity"] == 0:
            current["average_price"] = 0
    state["positions"][symbol] = current
    state["updated_at"] = now_iso()
    persist_paper_portfolio_state(root, state, portfolio_id, account_id, strategy_id, source="paper-trading")
    return {
        "adapter": "paper-trading",
        "broker_order_id": f"paper-{order['id']}",
        "status": "filled",
        "filled_quantity": quantity,
        "average_price": price,
        "submitted_at": state["updated_at"],
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "strategy_id": strategy_id,
    }


def portfolio_keys(args: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(args.get("portfolio_id") or DEFAULT_PORTFOLIO_ID),
        str(args.get("account_id") or DEFAULT_ACCOUNT_ID),
        str(args.get("strategy_id") or DEFAULT_STRATEGY_ID),
    )


def default_paper_portfolio_state(portfolio_id: str = DEFAULT_PORTFOLIO_ID, account_id: str = DEFAULT_ACCOUNT_ID, strategy_id: str = DEFAULT_STRATEGY_ID) -> dict[str, Any]:
    return {
        "cash_krw": DEFAULT_PAPER_CASH_KRW,
        "positions": {},
        "updated_at": now_iso(),
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "strategy_id": strategy_id,
        "source": "central-db",
        "db_canonical": True,
    }


def load_paper_portfolio_state(
    workspace_root: Path | str | None = None,
    portfolio_id: str = DEFAULT_PORTFOLIO_ID,
    account_id: str = DEFAULT_ACCOUNT_ID,
    strategy_id: str = DEFAULT_STRATEGY_ID,
) -> dict[str, Any]:
    ensure_runtime_database(workspace_root)
    from apps.portfolio.models import PortfolioSnapshot

    snapshot = (
        PortfolioSnapshot.objects.filter(
            portfolio_id=portfolio_id,
            account_id=account_id,
            strategy_id=strategy_id,
            source="paper-trading",
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if snapshot is None:
        state = default_paper_portfolio_state(portfolio_id, account_id, strategy_id)
        state["workspace_context"] = workspace_context_payload(workspace_root)
        persist_paper_portfolio_state(workspace_root, state, portfolio_id, account_id, strategy_id, source="paper-trading")
        return state
    state = dict(snapshot.payload or {})
    state.setdefault("cash_krw", 0)
    state.setdefault("positions", {})
    state.setdefault("updated_at", snapshot.created_at.isoformat())
    state.update({
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "strategy_id": strategy_id,
        "source": "central-db",
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    })
    return state


def persist_paper_portfolio_state(
    workspace_root: Path | str | None,
    state: dict[str, Any],
    portfolio_id: str,
    account_id: str,
    strategy_id: str,
    source: str = "paper-trading",
) -> None:
    ensure_runtime_database(workspace_root)
    from apps.portfolio.models import CashBalance, PortfolioSnapshot, Position

    state = dict(state)
    state.update({
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "strategy_id": strategy_id,
        "source": "central-db",
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    })
    snapshot = PortfolioSnapshot.objects.create(
        source=source,
        portfolio_id=portfolio_id,
        account_id=account_id,
        strategy_id=strategy_id,
        workspace_context=workspace_context_payload(workspace_root),
        payload=state,
    )
    CashBalance.objects.create(
        snapshot=snapshot,
        currency="KRW",
        amount=state.get("cash_krw", 0),
        portfolio_id=portfolio_id,
        account_id=account_id,
        strategy_id=strategy_id,
    )
    for symbol, position in sorted((state.get("positions") or {}).items()):
        if float(position.get("quantity", 0)) == 0:
            continue
        Position.objects.create(
            snapshot=snapshot,
            symbol=str(symbol).upper(),
            quantity=position.get("quantity", 0),
            average_price=position.get("average_price", 0),
            currency=position.get("currency") or "KRW",
            portfolio_id=portfolio_id,
            account_id=account_id,
            strategy_id=strategy_id,
        )


def list_positions(workspace_root: Path | str) -> dict[str, Any]:
    portfolio_id, account_id, strategy_id = portfolio_keys({})
    return load_paper_portfolio_state(Path(workspace_root), portfolio_id, account_id, strategy_id)


def list_workflow_artifacts(workspace_root: Path | str) -> dict[str, Any]:
    root = Path(workspace_root)
    files = []
    for prefix in ["trading/research", "trading/reports", "trading/orders", "trading/approvals"]:
        base = root / prefix
        if base.exists():
            files.extend(str(path.relative_to(root)) for path in base.rglob("*") if path.is_file() and path.name != ".gitkeep")
    return {"artifacts": sorted(files), "db_artifacts": list_research_artifacts(root, {"include_markdown": False}).get("artifacts", []), "db_canonical": True, "workspace_context": workspace_context_payload(root)}


def create_research_artifact(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    markdown = args.get("markdown")
    markdown_path = args.get("markdown_path") or args.get("markdown_file")
    if not markdown and markdown_path:
        markdown = _resolve_path(root, markdown_path).read_text(encoding="utf-8")
    if not markdown:
        raise ValueError("research artifact markdown is required")

    artifact_type = args.get("artifact_type") or args.get("type") or "research_memo"
    title = args.get("title") or args.get("artifact_id") or "Untitled research artifact"
    symbol = str(args.get("symbol") or "").upper()
    content_hash = hashlib.sha256(str(markdown).encode("utf-8")).hexdigest()
    artifact_id = args.get("artifact_id") or f"{sanitize_id(artifact_type)}-{sanitize_id(symbol or title)}-{content_hash[:12]}"
    metadata = args.get("metadata") if isinstance(args.get("metadata"), dict) else {}
    created_by = args.get("created_by") or args.get("principal_id") or "system"

    ensure_runtime_database(root)
    workspace_context = persist_workspace_context_if_available(root)
    from django.db import transaction
    from apps.research.models import ResearchArtifact, ResearchArtifactVersion

    with transaction.atomic():
        existing = ResearchArtifact.objects.filter(artifact_id=artifact_id).first()
        version = (existing.version + 1) if existing else 1
        artifact, created = ResearchArtifact.objects.update_or_create(
            artifact_id=artifact_id,
            defaults={
                "artifact_type": artifact_type,
                "universe": args.get("universe") or "public_equity",
                "workflow_type": args.get("workflow_type") or "",
                "symbol": symbol,
                "title": title,
                "markdown": markdown,
                "metadata": metadata,
                "workspace_context": workspace_context,
                "source_as_of": args.get("source_as_of") or "",
                "readiness_label": args.get("readiness_label") or "",
                "created_by": created_by,
                "content_hash": content_hash,
                "version": version,
                "parent_artifact_id": args.get("parent_artifact_id") or "",
            },
        )
        ResearchArtifactVersion.objects.create(
            artifact=artifact,
            version=version,
            markdown=markdown,
            metadata=metadata,
            workspace_context=workspace_context,
            content_hash=content_hash,
            created_by=created_by,
        )

    export_path = ""
    if args.get("export", True) is not False:
        export = export_research_artifact_md(root, {"artifact_id": artifact_id, "export_path": args.get("export_path")})
        export_path = export.get("export_path", "")
    result = {
        "status": "stored" if created else "updated",
        "db_canonical": True,
        "artifact_id": artifact_id,
        "version": version,
        "content_hash": content_hash,
        "export_path": export_path,
        "workspace_context": workspace_context,
    }
    write_audit_event(root, {"type": "research_artifact.saved", "payload": result}, principal_id=created_by, source="service")
    return result


def append_research_artifact_version(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("artifact_id"):
        raise ValueError("artifact_id is required")
    current = get_research_artifact(workspace_root, {"artifact_id": args["artifact_id"]})
    return create_research_artifact(workspace_root, {
        **current,
        **args,
        "markdown": args.get("markdown") or current.get("markdown"),
        "metadata": args.get("metadata") or current.get("metadata") or {},
    })


def get_research_artifact(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    artifact_id = args.get("artifact_id") or args.get("id")
    if not artifact_id:
        raise ValueError("artifact_id is required")
    ensure_runtime_database(workspace_root)
    from apps.research.models import ResearchArtifact

    artifact = ResearchArtifact.objects.get(artifact_id=artifact_id)
    return research_artifact_to_dict(artifact, include_markdown=args.get("include_markdown", True) is not False)


def list_research_artifacts(workspace_root: Path | str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    try:
        ensure_runtime_database(workspace_root)
        from apps.research.models import ResearchArtifact

        queryset = ResearchArtifact.objects.all()
        for field in ["artifact_type", "universe", "workflow_type", "symbol", "readiness_label", "created_by"]:
            value = args.get(field)
            if value:
                queryset = queryset.filter(**{field: str(value).upper() if field == "symbol" else value})
        limit = max(1, min(int(args.get("limit") or 50), 200))
        return {"db_canonical": True, "workspace_context": workspace_context_payload(workspace_root), "artifacts": [research_artifact_to_dict(artifact, include_markdown=args.get("include_markdown") is True) for artifact in queryset[:limit]]}
    except Exception as exc:
        return {"db_canonical": False, "artifacts": [], "error": str(exc)}


def search_research_artifacts(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        raise ValueError("query is required")
    ensure_runtime_database(workspace_root)
    from django.db.models import Q
    from apps.research.models import ResearchArtifact

    queryset = ResearchArtifact.objects.filter(Q(title__icontains=query) | Q(markdown__icontains=query) | Q(symbol__icontains=query))
    if args.get("universe"):
        queryset = queryset.filter(universe=args["universe"])
    if args.get("artifact_type"):
        queryset = queryset.filter(artifact_type=args["artifact_type"])
    limit = max(1, min(int(args.get("limit") or 20), 100))
    return {"query": query, "db_canonical": True, "workspace_context": workspace_context_payload(workspace_root), "artifacts": [research_artifact_to_dict(artifact, include_markdown=False) for artifact in queryset[:limit]]}


def export_research_artifact_md(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    artifact_id = args.get("artifact_id") or args.get("id")
    if not artifact_id:
        raise ValueError("artifact_id is required")
    ensure_runtime_database(root)
    from apps.research.models import ResearchArtifact

    artifact = ResearchArtifact.objects.get(artifact_id=artifact_id)
    rel = args.get("export_path") or artifact.export_path or default_research_export_path(artifact)
    path = _resolve_path(root, rel)
    frontmatter = {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "universe": artifact.universe,
        "workflow_type": artifact.workflow_type,
        "symbol": artifact.symbol,
        "readiness_label": artifact.readiness_label,
        "version": artifact.version,
        "content_hash": artifact.content_hash,
        "db_canonical": True,
    }
    body = "---\n" + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items()) + "\n---\n\n" + artifact.markdown.rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    if artifact.export_path != path.relative_to(root).as_posix():
        artifact.export_path = path.relative_to(root).as_posix()
        artifact.save(update_fields=["export_path", "updated_at"])
    return {"status": "exported", "artifact_id": artifact.artifact_id, "export_path": path.relative_to(root).as_posix(), "db_canonical": True, "workspace_context": workspace_context_payload(root)}


def record_source_snapshot(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    ensure_runtime_database(workspace_root)
    from apps.research.models import SourceSnapshot

    snapshot = SourceSnapshot.objects.create(
        provider=args.get("provider") or "unknown",
        source_category=args.get("source_category") or args.get("category") or "unknown",
        as_of=args.get("as_of") or "",
        artifact_id=args.get("artifact_id") or "",
        warnings=args.get("warnings") if isinstance(args.get("warnings"), list) else [],
        payload=args.get("payload") if isinstance(args.get("payload"), dict) else {},
        workspace_context=workspace_context_payload(workspace_root),
    )
    result = {"status": "recorded", "snapshot_id": snapshot.id, "artifact_id": snapshot.artifact_id, "provider": snapshot.provider, "source_category": snapshot.source_category, "db_canonical": True, "workspace_context": workspace_context_payload(workspace_root)}
    write_audit_event(workspace_root, {"type": "source_snapshot.recorded", "payload": result}, principal_id=args.get("principal_id", "system"), source="service")
    return result


def research_artifact_to_dict(artifact: Any, include_markdown: bool = True) -> dict[str, Any]:
    result = {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "universe": artifact.universe,
        "workflow_type": artifact.workflow_type,
        "symbol": artifact.symbol,
        "title": artifact.title,
        "metadata": artifact.metadata,
        "workspace_context": artifact.workspace_context,
        "source_as_of": artifact.source_as_of,
        "readiness_label": artifact.readiness_label,
        "created_by": artifact.created_by,
        "content_hash": artifact.content_hash,
        "version": artifact.version,
        "export_path": artifact.export_path,
        "parent_artifact_id": artifact.parent_artifact_id,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
        "db_canonical": True,
    }
    if include_markdown:
        result["markdown"] = artifact.markdown
    return result


def default_research_export_path(artifact: Any) -> str:
    stem = sanitize_id(artifact.artifact_id)
    if artifact.artifact_type == "evidence_pack":
        return f"trading/research/{stem}.evidence.md"
    role = artifact.metadata.get("role") if isinstance(artifact.metadata, dict) else ""
    if role in {"fundamental", "technical", "news", "macro", "instrument", "valuation", "portfolio", "risk", "policy"}:
        return f"trading/reports/{role}/{stem}.md"
    return f"trading/research/{stem}.md"


def write_audit_event(workspace_root: Path | str, event: dict[str, Any], principal_id: str = "system", source: str = "service") -> dict[str, Any]:
    root = Path(workspace_root)
    record = {"ts": now_iso(), "event": event}
    append_jsonl(root / "trading" / "audit" / "tradingcodex-mcp.jsonl", record)
    write_audit_event_if_available(root, principal_id, source, event)
    return {"written": True, "db_canonical": True, "export_path": "trading/audit/tradingcodex-mcp.jsonl", "workspace_context": workspace_context_payload(root)}


def call_tool(workspace_root: Path | str, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    from tradingcodex_service.mcp_runtime import call_mcp_tool

    return call_mcp_tool(workspace_root, name, args)


from tradingcodex_service.mcp_runtime import static_mcp_tools as _static_mcp_tools

MCP_TOOLS = _static_mcp_tools()


def mcp_handle_rpc(workspace_root: Path | str, message: dict[str, Any]) -> dict[str, Any] | None:
    from tradingcodex_service.mcp_runtime import handle_mcp_rpc

    return handle_mcp_rpc(workspace_root, message)


def classify_starter_request(request: str) -> dict[str, Any]:
    text = request.lower()
    universe = classify_investment_universe(text)
    action_text = strip_guardrail_verification_phrases(strip_negated_action_phrases(text))
    wants_approval_execution = bool(re.search(r"submit|already approved|approved paper|execute|execution|approve|approval|broker|live", action_text))
    wants_order_draft = bool(re.search(r"draft|order intent|buy order|sell order|paper buy order|paper sell order", action_text))
    wants_decision = bool(re.search(r"should i buy|should i sell|recommend|fair value|target price|buy|sell", action_text))
    wants_thesis_review = bool(re.search(r"earnings|filing|catalyst|preview|thesis|valuation|disclosure|narrative", text))
    wants_portfolio_risk = bool(re.search(r"portfolio|position|holding|own|exposure|concentration|correlation|drawdown|hedge|sizing|size|risk", text))
    wants_macro = bool(re.search(r"macro|rates|rate|fx|currency|commodity|commodities|inflation|fed|boj|ecb|central bank|yield|oil|gold", text))
    wants_instrument = bool(re.search(r"etf|index|indices|option|options|derivative|futures|borrow|short interest|crypto|bitcoin|btc|ethereum|eth|cds|bond|credit|convertible|preferred|instrument|market structure", text))
    wants_technical = bool(re.search(r"trend|technical|price|volatility|liquidity|drawdown|down|setup|chart", text))
    wants_news = bool(re.search(r"news|event|earnings|filing|headline|catalyst|disclosure", text))
    research = base_research_team(universe, wants_technical, wants_news)
    if wants_macro:
        research.append("macro-analyst")
    if wants_instrument:
        research.append("instrument-analyst")
    if wants_approval_execution:
        return {"universe": universe, "lane": "order_intent_or_approval_execution_gate", "subagents": _unique((["macro-analyst"] if wants_macro else []) + (["instrument-analyst"] if wants_instrument else []) + ["portfolio-manager", "risk-manager", "execution-operator"]), "blockedActions": ["natural-language order", "direct broker API", "secret read", "execution without approved artifacts"]}
    if wants_order_draft:
        return {"universe": universe, "lane": "order_intent_draft_gate", "subagents": _unique(research + ["portfolio-manager", "risk-manager"]), "blockedActions": ["approval", "execution", "direct broker API", "secret read"]}
    if wants_portfolio_risk:
        return {"universe": universe, "lane": "portfolio_risk_review", "subagents": _unique((["macro-analyst"] if wants_macro else []) + (["instrument-analyst"] if wants_instrument else []) + (["technical-analyst"] if wants_technical else []) + (["news-analyst"] if wants_news else []) + ["portfolio-manager", "risk-manager"]), "blockedActions": ["order intent", "approval", "execution", "direct broker API", "secret read"]}
    if wants_decision:
        return {"universe": universe, "lane": "thesis_review_then_portfolio_risk_review", "subagents": _unique(research + ["valuation-analyst", "portfolio-manager", "risk-manager"]), "blockedActions": ["order intent", "approval", "execution", "direct broker API", "secret read"]}
    if wants_thesis_review and universe == "public_equity":
        return {"universe": universe, "lane": "thesis_review", "subagents": _unique(research + ["valuation-analyst"]), "blockedActions": ["order intent", "approval", "execution", "direct broker API", "secret read"]}
    return {"universe": universe, "lane": "research_only", "subagents": _unique(research), "blockedActions": ["valuation unless requested", "order intent", "approval", "execution", "direct broker API", "secret read"]}


def classify_investment_universe(text: str) -> str:
    if re.search(r"\b(btc|bitcoin|eth|ethereum|crypto|token|stablecoin|on-chain|defi)\b", text):
        return "public_crypto"
    if re.search(r"\b(option|options|derivative|futures|swap|volatility surface)\b", text):
        return "options_derivatives"
    if re.search(r"\b(etf|index|indices|benchmark|constituent)\b", text):
        return "etf_index"
    if re.search(r"\b(cds|bond|credit|spread|covenant|restructuring|distressed|loan)\b", text):
        return "credit_signal"
    if re.search(r"\b(macro|rates|fx|currency|commodity|commodities|inflation|fed|boj|ecb|central bank|yield|oil|gold)\b", text):
        return "macro_rates_fx_commodities"
    return "public_equity"


def base_research_team(universe: str, wants_technical: bool, wants_news: bool) -> list[str]:
    if universe == "public_crypto":
        return ["technical-analyst", "news-analyst", "instrument-analyst"]
    if universe == "macro_rates_fx_commodities":
        team = ["macro-analyst"]
        if wants_technical:
            team.append("technical-analyst")
        if wants_news:
            team.append("news-analyst")
        return team
    if universe in {"options_derivatives", "credit_signal"}:
        team = ["instrument-analyst"]
        if wants_technical:
            team.append("technical-analyst")
        if wants_news:
            team.append("news-analyst")
        return team
    if universe == "etf_index":
        return ["instrument-analyst", "technical-analyst", "news-analyst"]
    return ["fundamental-analyst", "technical-analyst", "news-analyst"]


def build_subagent_starter_prompt(request: str) -> str:
    plan = classify_starter_request(request)
    return "\n".join([
        "Use this workspace's fixed-role subagent workflow.",
        "Explicitly use Codex subagents.",
        f'Original user request (verbatim): "{request}"',
        f"Investment universe: {plan['universe']}",
        f"Workflow lane: {plan['lane']}",
        f"Spawn these fixed role subagents in parallel: {', '.join(plan['subagents'])}",
        "Use each role's exact `.codex/agents/*.toml` name as the runtime label.",
        "Preserve the original user request and explicit constraints in every subagent brief.",
        "Do not let head-manager perform substantive investment analysis before subagent outputs exist.",
        "Wait for all selected subagents, then synthesize their outputs with artifact paths, disagreements, missing evidence, and next allowed action.",
        f"Blocked actions before artifacts: {', '.join(plan['blockedActions'])}",
    ])


def strip_negated_action_phrases(text: str) -> str:
    text = re.sub(r"\b(no|do not|don't|dont|without)\s+(account access|order draft|trade execution|trading|trade|trades|orders|order|draft|execution|execute|approval|approve)\b", " ", text)
    text = re.sub(r"\b(no|do not|don't|dont|without)\s+(live trading|live execution|broker access|account|broker|trade execution)\b", " ", text)
    return text


def strip_guardrail_verification_phrases(text: str) -> str:
    text = re.sub(r"\beven with\b[^.]{0,180}\b(?:blocked|denied|rejected|unavailable)[-\s]+action\s+wording\b[^.]*", " ", text)
    text = re.sub(r"\b(?:blocked|denied|rejected|unavailable)[-\s]+action\s+wording\s+like\b[^.]*", " ", text)
    text = re.sub(r"\bwhether\s+(?:order|approval|execution|direct|broker|secret|access|/|\s|was|were|is|are|blocked|denied|rejected)+", " ", text)
    text = re.sub(r"\b(?:blocked|denied|rejected|unavailable)\s+(?:order|approval|execution|direct|broker|secret|access|/|\s|actions|paths)+", " ", text)
    text = re.sub(r"\bverify\s+(?:routing\s+and\s+)?(?:blocked|denied|rejected|unavailable)\s+(?:actions|paths|access)?", " ", text)
    text = re.sub(r"\bverify\b.{0,120}\b(?:blocked|denied|rejected|unavailable|no trading|no order|no execution)\b", " ", text)
    text = re.sub(r"\bconfirm\b.{0,120}\b(?:blocked|denied|rejected|unavailable|no trading|no order|no execution)\b", " ", text)
    return text


def resolve_order_intent(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    if isinstance(args.get("order_intent"), dict):
        return args["order_intent"]
    if isinstance(args.get("order"), dict):
        return args["order"]
    if args.get("order_intent_path"):
        return read_json(_resolve_path(root, args["order_intent_path"]), {})
    if args.get("order_intent_id"):
        return find_order_intent_by_id(root, args["order_intent_id"]) or {}
    return {}


def resolve_approval_receipt(root: Path, args: dict[str, Any], order: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(args.get("approval_receipt"), dict):
        return args["approval_receipt"]
    if args.get("approval_receipt_path"):
        return read_json(_resolve_path(root, args["approval_receipt_path"]), {})
    if args.get("approval_receipt_id"):
        return find_approval_receipt_by_id(root, args["approval_receipt_id"]) or {}
    if order and order.get("id"):
        return find_approval_receipt_by_order_id(root, order["id"]) or {}
    return {}


def find_order_intent_by_id(root: Path, order_id: str) -> dict[str, Any] | None:
    try:
        ensure_runtime_database(root)
        from apps.orders.models import OrderIntent

        stored = OrderIntent.objects.filter(intent_id=order_id).first()
        if stored:
            payload = stored.payload or {}
            if isinstance(payload.get("order_intent"), dict):
                return payload["order_intent"]
            return {
                "id": stored.intent_id,
                "symbol": stored.symbol,
                "side": stored.side,
                "quantity": float(stored.quantity),
                "limit_price": float(stored.limit_price),
                "currency": stored.currency,
                "broker": stored.broker,
                "estimated_notional_krw": float(stored.estimated_notional_krw),
                "created_by": stored.created_by,
                "created_at": stored.created_at.isoformat(),
                "portfolio_id": stored.portfolio_id,
                "account_id": stored.account_id,
                "strategy_id": stored.strategy_id,
            }
    except Exception:
        pass
    for folder in ["approved", "draft", "rejected", "executed"]:
        for path in (root / "trading" / "orders" / folder).glob("*.json"):
            data = read_json(path, {})
            if data.get("id") == order_id or data.get("order_intent", {}).get("id") == order_id or data.get("order_intent_id") == order_id:
                return data.get("order_intent") or data
    return None


def find_approval_receipt_by_id(root: Path, receipt_id: str) -> dict[str, Any] | None:
    try:
        ensure_runtime_database(root)
        from apps.orders.models import ApprovalReceipt

        stored = ApprovalReceipt.objects.filter(receipt_id=receipt_id).first()
        if stored:
            return stored.payload or {}
    except Exception:
        pass
    for path in (root / "trading" / "approvals").glob("*.json"):
        data = read_json(path, {})
        if data.get("id") == receipt_id:
            return data
    return None


def find_approval_receipt_by_order_id(root: Path, order_id: str) -> dict[str, Any] | None:
    try:
        ensure_runtime_database(root)
        from apps.orders.models import ApprovalReceipt

        stored = ApprovalReceipt.objects.filter(order_intent_id=order_id, valid=True).order_by("-created_at", "-id").first()
        if stored:
            return stored.payload or {}
    except Exception:
        pass
    for path in (root / "trading" / "approvals").glob("*.json"):
        data = read_json(path, {})
        if data.get("order_intent_id") == order_id:
            return data
    return None


def write_rejected_order(root: Path, order: dict[str, Any], reasons: list[str]) -> None:
    write_json(root / "trading" / "orders" / "rejected" / f"{sanitize_id(order.get('id', 'unknown'))}.rejected.json", {
        "order_intent": order,
        "rejected_at": now_iso(),
        "reasons": reasons,
    })


def persist_order_intent_if_available(root: Path, order: dict[str, Any], validation: dict[str, Any] | None = None) -> None:
    required = ["id", "symbol", "side", "quantity", "limit_price", "currency", "broker", "estimated_notional_krw", "created_by", "created_at"]
    if any(order.get(field) in (None, "") for field in required):
        return
    try:
        ensure_runtime_database(root)
        from apps.orders.models import OrderIntent

        portfolio_id, account_id, strategy_id = portfolio_keys(order)
        OrderIntent.objects.update_or_create(
            intent_id=order["id"],
            defaults={
                "symbol": str(order["symbol"]).upper(),
                "side": order["side"],
                "quantity": order["quantity"],
                "limit_price": order["limit_price"],
                "currency": order["currency"],
                "broker": order["broker"],
                "estimated_notional_krw": order["estimated_notional_krw"],
                "created_by": order["created_by"],
                "created_at": _parse_datetime(order["created_at"]) or datetime.now(timezone.utc),
                "portfolio_id": portfolio_id,
                "account_id": account_id,
                "strategy_id": strategy_id,
                "workspace_context": workspace_context_payload(root),
                "payload": {"order_intent": order, "validation": validation or {}},
            },
        )
    except Exception:
        return


def persist_approval_receipt_if_available(root: Path, receipt: dict[str, Any]) -> None:
    required = ["id", "order_intent_id", "approved_by", "valid", "expires_at"]
    if any(receipt.get(field) in (None, "") for field in required):
        return
    try:
        ensure_runtime_database(root)
        from apps.orders.models import ApprovalReceipt

        ApprovalReceipt.objects.update_or_create(
            receipt_id=receipt["id"],
            defaults={
                "order_intent_id": receipt["order_intent_id"],
                "approved_by": receipt["approved_by"],
                "valid": bool(receipt["valid"]),
                "expires_at": _parse_datetime(receipt["expires_at"]) or datetime.now(timezone.utc),
                "workspace_context": workspace_context_payload(root),
                "payload": receipt,
            },
        )
    except Exception:
        return


def persist_execution_result_if_available(root: Path, order: dict[str, Any], receipt: dict[str, Any], result: dict[str, Any]) -> None:
    if not order.get("id"):
        return
    try:
        ensure_runtime_database(root)
        from apps.orders.services import execution_idempotency_key
        from apps.orders.models import ExecutionResult

        portfolio_id, account_id, strategy_id = portfolio_keys(order)
        key = str(result.get("idempotency_key") or execution_idempotency_key(order, receipt))
        ExecutionResult.objects.update_or_create(
            idempotency_key=key,
            defaults={
                "order_intent_id": order["id"],
                "approval_receipt_id": receipt.get("id", ""),
                "adapter": result.get("adapter") or order.get("broker", ""),
                "status": result.get("status", "recorded"),
                "portfolio_id": portfolio_id,
                "account_id": account_id,
                "strategy_id": strategy_id,
                "workspace_context": workspace_context_payload(root),
                "payload": result,
            },
        )
    except Exception:
        return

def write_audit_event_if_available(
    workspace_root_or_principal: Path | str | None,
    principal_id_or_source: str,
    source_or_event: str | dict[str, Any],
    event: dict[str, Any] | None = None,
) -> None:
    if event is None:
        workspace_root = None
        principal_id = str(workspace_root_or_principal)
        source = str(principal_id_or_source)
        event = source_or_event if isinstance(source_or_event, dict) else {}
    else:
        workspace_root = workspace_root_or_principal
        principal_id = str(principal_id_or_source)
        source = str(source_or_event)
    try:
        if workspace_root is not None:
            ensure_runtime_database(workspace_root)
        from apps.audit.models import AuditEvent

        AuditEvent.objects.create(
            actor_principal=principal_id,
            source=source,
            action=str(event.get("type") or event.get("action") or "event"),
            resource=str(event.get("resource") or event.get("payload", {}).get("order_intent_id") or ""),
            decision=str(event.get("decision") or event.get("payload", {}).get("status") or "recorded"),
            request_hash=stable_hash(event),
            result_hash=stable_hash(event.get("payload", event)),
            workspace_context=workspace_context_payload(workspace_root),
            payload=event,
        )
    except Exception:
        return


def write_policy_decision_if_available(workspace_root_or_result: Path | str | dict[str, Any] | None, result: dict[str, Any] | None = None) -> None:
    workspace_root = None
    if result is None:
        result = workspace_root_or_result if isinstance(workspace_root_or_result, dict) else {}
    else:
        workspace_root = workspace_root_or_result
    try:
        if workspace_root is not None:
            ensure_runtime_database(workspace_root)
        from apps.policy.models import PolicyDecision

        PolicyDecision.objects.create(
            principal_id=result["principal_id"],
            action=result["action"],
            resource=result.get("resource") or "",
            decision=result["decision"],
            reasons=result["reasons"],
            workspace_context=workspace_context_payload(workspace_root),
        )
    except Exception:
        return


ROLE_UI_PROFILES: dict[str, dict[str, Any]] = {
    "head-manager": {
        "label": "Head Manager",
        "group": "main",
        "purpose": "Routes the request, coordinates fixed subagents, waits for artifacts, and synthesizes the workflow state.",
        "forbidden_actions": [
            "Do not replace specialist analysis with direct analysis.",
            "Do not call broker APIs directly.",
            "Do not bypass policy, approval, adapter, or audit checks.",
        ],
    },
    "fundamental-analyst": {
        "label": "Fundamental Analyst",
        "group": "research",
        "purpose": "Reviews business quality, financial statements, official disclosures, and competitive position.",
        "forbidden_actions": ["No order intent.", "No approval.", "No execution.", "No secret access."],
    },
    "technical-analyst": {
        "label": "Technical Analyst",
        "group": "research",
        "purpose": "Reviews price action, trend, volatility, liquidity, volume, and market setup.",
        "forbidden_actions": ["No order intent.", "No execution.", "No standalone investment conclusion."],
    },
    "news-analyst": {
        "label": "News Analyst",
        "group": "research",
        "purpose": "Reviews news, official disclosures, event risk, catalysts, and narrative change.",
        "forbidden_actions": ["No unverified rumor claims.", "No execution.", "No secret access."],
    },
    "macro-analyst": {
        "label": "Macro Analyst",
        "group": "research",
        "purpose": "Reviews rates, FX, commodities, liquidity, policy, and cross-asset transmission.",
        "forbidden_actions": ["No order intent.", "No execution.", "No unsupported implementation claims."],
    },
    "instrument-analyst": {
        "label": "Instrument Analyst",
        "group": "research",
        "purpose": "Reviews ETF/index, options, derivatives, crypto public markets, credit signals, and instrument mechanics.",
        "forbidden_actions": ["No order intent.", "No execution.", "No unsupported instrument execution claims."],
    },
    "valuation-analyst": {
        "label": "Valuation Analyst",
        "group": "analysis",
        "purpose": "Builds valuation, scenario, multiple, DCF, reverse DCF, and expected-return views.",
        "forbidden_actions": ["No approval.", "No execution.", "No broker API calls."],
    },
    "portfolio-manager": {
        "label": "Portfolio Manager",
        "group": "portfolio",
        "purpose": "Reviews portfolio fit, sizing, cash, concentration, and draft order intent readiness.",
        "forbidden_actions": ["No self-approval.", "No execution.", "No arbitrary policy changes."],
    },
    "risk-manager": {
        "label": "Risk Manager",
        "group": "risk",
        "purpose": "Reviews risk, restricted list, downside, policy readiness, and approval receipt eligibility.",
        "forbidden_actions": ["No order drafting.", "No execution.", "No arbitrary policy changes."],
    },
    "execution-operator": {
        "label": "Execution Operator",
        "group": "execution",
        "purpose": "Submits approved order intents through TradingCodex MCP using paper or stub adapters only.",
        "forbidden_actions": ["No raw broker API.", "No secret read.", "No policy change.", "No live broker path in core."],
    },
}


ROLE_NODE_POSITIONS: dict[str, tuple[int, int]] = {
    "head-manager": (50, 10),
    "fundamental-analyst": (12, 29),
    "technical-analyst": (31, 29),
    "news-analyst": (50, 29),
    "macro-analyst": (69, 29),
    "instrument-analyst": (88, 29),
    "valuation-analyst": (31, 53),
    "portfolio-manager": (50, 66),
    "risk-manager": (69, 78),
    "execution-operator": (88, 91),
}


TOPOLOGY_EDGES: tuple[dict[str, str], ...] = (
    {"source": "head-manager", "target": "fundamental-analyst", "group": "dispatch"},
    {"source": "head-manager", "target": "technical-analyst", "group": "dispatch"},
    {"source": "head-manager", "target": "news-analyst", "group": "dispatch"},
    {"source": "head-manager", "target": "macro-analyst", "group": "dispatch"},
    {"source": "head-manager", "target": "instrument-analyst", "group": "dispatch"},
    {"source": "fundamental-analyst", "target": "valuation-analyst", "group": "research-handoff"},
    {"source": "technical-analyst", "target": "valuation-analyst", "group": "research-handoff"},
    {"source": "news-analyst", "target": "valuation-analyst", "group": "research-handoff"},
    {"source": "macro-analyst", "target": "portfolio-manager", "group": "portfolio-risk-gate"},
    {"source": "instrument-analyst", "target": "portfolio-manager", "group": "portfolio-risk-gate"},
    {"source": "valuation-analyst", "target": "portfolio-manager", "group": "portfolio-risk-gate"},
    {"source": "portfolio-manager", "target": "risk-manager", "group": "approval-gate"},
    {"source": "risk-manager", "target": "execution-operator", "group": "execution-gate"},
)


EDGE_GROUP_LABELS: dict[str, str] = {
    "dispatch": "Dispatch",
    "research-handoff": "Research handoff",
    "portfolio-risk-gate": "Portfolio/risk gate",
    "approval-gate": "Approval gate",
    "execution-gate": "Execution gate",
}


def get_harness_topology(workspace_root: Path | str | None = None) -> dict[str, Any]:
    tools = _static_mcp_tools()
    nodes = []
    for role, skills in ROLE_SKILL_MAP.items():
        x, y = ROLE_NODE_POSITIONS[role]
        profile = ROLE_UI_PROFILES[role]
        allowed_tools = _allowed_tools_for_role(role, tools)
        nodes.append({
            "role": role,
            "label": profile["label"],
            "group": profile["group"],
            "purpose": profile["purpose"],
            "skills_count": len(skills),
            "tools_count": len(allowed_tools),
            "x": x,
            "y": y,
        })
    edges = []
    for edge in TOPOLOGY_EDGES:
        source_x, source_y = ROLE_NODE_POSITIONS[edge["source"]]
        target_x, target_y = ROLE_NODE_POSITIONS[edge["target"]]
        mid_y = round((source_y + target_y) / 2, 2)
        edges.append({
            **edge,
            "label": EDGE_GROUP_LABELS[edge["group"]],
            "source_x": source_x,
            "source_y": source_y,
            "target_x": target_x,
            "target_y": target_y,
            "mid_y": mid_y,
        })
    return {
        "nodes": nodes,
        "edges": edges,
        "edge_groups": [{"key": key, "label": label} for key, label in EDGE_GROUP_LABELS.items()],
        "layers": [
            {"label": "Coordinator", "y": 10},
            {"label": "Research roles", "y": 29},
            {"label": "Valuation", "y": 53},
            {"label": "Portfolio fit", "y": 66},
            {"label": "Risk approval", "y": 78},
            {"label": "MCP execution", "y": 91},
        ],
        "boundary": {
            "label": "MCP execution boundary",
            "summary": "Execution-sensitive actions must pass principal, policy, schema, approval, adapter, and audit checks.",
            "x": 78,
            "y1": 72,
            "y2": 96,
        },
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def get_role_detail(role: str, workspace_root: Path | str | None = None) -> dict[str, Any]:
    if role not in ROLE_SKILL_MAP:
        role = "head-manager"
    tools = _static_mcp_tools()
    profile = ROLE_UI_PROFILES[role]
    return {
        "role": role,
        "label": profile["label"],
        "group": profile["group"],
        "purpose": profile["purpose"],
        "skills": ROLE_SKILL_MAP[role],
        "allowed_tools": _allowed_tools_for_role(role, tools),
        "forbidden_actions": profile["forbidden_actions"],
        "latest_artifacts": _latest_role_artifacts(role, workspace_root),
        "latest_activity": _latest_role_activity(role),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def get_harness_health(workspace_root: Path | str | None = None) -> dict[str, Any]:
    try:
        ensure_runtime_database(workspace_root)
    except Exception:
        pass

    from tradingcodex_service.mcp_runtime import static_mcp_tools

    tools = static_mcp_tools()
    counts = {
        "roster": len(EXPECTED_SUBAGENTS),
        "roles_total": len(ROLE_SKILL_MAP),
        "skills": len(EXPECTED_SKILLS),
        "mcp_tools": len(tools),
        "mcp_execution_tools": sum(1 for tool in tools if tool.get("annotations", {}).get("risk_level") == "execution"),
        "policy_blocks": _model_count("apps.policy.models", "PolicyDecision", decision="deny"),
        "restricted_symbols": _model_count("apps.policy.models", "RestrictedSymbol", active=True),
        "workspace_contexts": _model_count("apps.harness.models", "WorkspaceContext"),
        "research_artifacts": _model_count("apps.research.models", "ResearchArtifact"),
        "order_intents": _model_count("apps.orders.models", "OrderIntent"),
        "approval_receipts": _model_count("apps.orders.models", "ApprovalReceipt"),
        "execution_results": _model_count("apps.orders.models", "ExecutionResult"),
        "mcp_calls": _model_count("apps.mcp.models", "McpToolCall"),
    }
    checks = [
        {"label": "Fixed subagent roster", "value": f"{counts['roster']} of 9", "status": "good"},
        {"label": "Repo skills installed", "value": str(counts["skills"]), "status": "good"},
        {"label": "MCP tools visible", "value": str(counts["mcp_tools"]), "status": "good"},
        {"label": "Execution tools", "value": str(counts["mcp_execution_tools"]), "status": "warn"},
        {"label": "Policy blocks", "value": str(counts["policy_blocks"]), "status": "neutral"},
        {"label": "Workspace contexts", "value": str(counts["workspace_contexts"]), "status": "neutral"},
    ]
    return {
        "counts": counts,
        "checks": checks,
        "db_path": str(tradingcodex_db_path()),
        "central_local_service": True,
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def list_recent_activity(workspace_root: Path | str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    try:
        ensure_runtime_database(workspace_root)
    except Exception:
        pass
    items: list[dict[str, Any]] = []
    try:
        from apps.mcp.models import McpToolCall

        for call in McpToolCall.objects.order_by("-created_at", "-id")[:limit]:
            items.append({
                "kind": "MCP",
                "title": call.tool_name,
                "subtitle": call.principal_id,
                "status": call.status,
                "status_class": _status_class(call.status),
                "created_at": call.created_at,
            })
    except Exception:
        pass
    try:
        from apps.audit.models import AuditEvent

        for event in AuditEvent.objects.order_by("-created_at", "-id")[:limit]:
            items.append({
                "kind": "Audit",
                "title": event.action,
                "subtitle": event.actor_principal,
                "status": event.decision,
                "status_class": _status_class(event.decision),
                "created_at": event.created_at,
            })
    except Exception:
        pass
    try:
        from apps.workflows.models import WorkflowRun

        for run in WorkflowRun.objects.order_by("-created_at", "-id")[:limit]:
            items.append({
                "kind": "Workflow",
                "title": run.lane,
                "subtitle": run.universe,
                "status": run.status,
                "status_class": _status_class(run.status),
                "created_at": run.created_at,
            })
    except Exception:
        pass
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items[:limit]


def list_policy_overview(workspace_root: Path | str | None = None) -> dict[str, Any]:
    try:
        ensure_runtime_database(workspace_root)
    except Exception:
        pass
    restricted_symbols: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    principals: list[dict[str, Any]] = []
    try:
        from apps.policy.models import PolicyDecision, Principal, RestrictedSymbol

        restricted_symbols = [
            {"symbol": item.symbol, "reason": item.reason, "active": item.active, "status_class": "bad" if item.active else "neutral"}
            for item in RestrictedSymbol.objects.order_by("symbol")[:50]
        ]
        decisions = [
            {
                "principal_id": item.principal_id,
                "action": item.action,
                "resource": item.resource,
                "decision": item.decision,
                "reasons": item.reasons,
                "created_at": item.created_at,
                "status_class": _status_class(item.decision),
            }
            for item in PolicyDecision.objects.order_by("-created_at", "-id")[:20]
        ]
        principals = [
            {"principal_id": item.principal_id, "role": item.role, "active": item.active}
            for item in Principal.objects.order_by("role", "principal_id")[:50]
        ]
    except Exception:
        pass
    return {
        "restricted_symbols": restricted_symbols,
        "recent_decisions": decisions,
        "principals": principals,
        "explicit_denies": sorted(EXPLICIT_DENY_ACTIONS),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def _allowed_tools_for_role(role: str, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = []
    for tool in tools:
        annotations = tool.get("annotations") or {}
        if role in annotations.get("allowed_roles", []):
            allowed.append({
                "name": tool["name"],
                "category": annotations.get("category", ""),
                "risk_level": annotations.get("risk_level", "read"),
                "requires_approval": bool(annotations.get("requires_approval")),
                "status_class": _status_class(annotations.get("risk_level", "read")),
            })
    return allowed


def _latest_role_artifacts(role: str, workspace_root: Path | str | None) -> list[dict[str, Any]]:
    try:
        ensure_runtime_database(workspace_root)
        from apps.research.models import ResearchArtifact

        role_alias = role.replace("-analyst", "").replace("-manager", "").replace("-operator", "")
        queryset = ResearchArtifact.objects.filter(created_by=role).order_by("-updated_at", "-id")
        if not queryset.exists():
            queryset = ResearchArtifact.objects.filter(metadata__role=role_alias).order_by("-updated_at", "-id")
        return [
            {
                "artifact_id": artifact.artifact_id,
                "title": artifact.title,
                "artifact_type": artifact.artifact_type,
                "universe": artifact.universe,
                "readiness_label": artifact.readiness_label or "unlabeled",
                "updated_at": artifact.updated_at,
            }
            for artifact in queryset[:5]
        ]
    except Exception:
        return []


def _latest_role_activity(role: str) -> list[dict[str, Any]]:
    try:
        from apps.mcp.models import McpToolCall

        return [
            {
                "title": call.tool_name,
                "status": call.status,
                "status_class": _status_class(call.status),
                "created_at": call.created_at,
            }
            for call in McpToolCall.objects.filter(principal_id=role).order_by("-created_at", "-id")[:5]
        ]
    except Exception:
        return []


def _model_count(module_name: str, class_name: str, **filters: Any) -> int:
    try:
        module = __import__(module_name, fromlist=[class_name])
        model = getattr(module, class_name)
        queryset = model.objects.filter(**filters) if filters else model.objects
        return int(queryset.count())
    except Exception:
        return 0


def _status_class(value: Any) -> str:
    text = str(value).lower()
    if text in {"ok", "allow", "accepted", "approved", "enabled", "filled", "valid", "read", "true", "open"}:
        return "good"
    if text in {"deny", "denied", "rejected", "error", "blocked", "disabled", "false", "execution"}:
        return "bad"
    if text in {"proposed", "pending", "recorded", "stubbed", "write", "approval", "research-only"}:
        return "warn"
    return "neutral"


def _resolve_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else root / path


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _validate_positive(value: Any, field: str, reasons: list[str]) -> None:
    if value in (None, ""):
        return
    number = _number(value)
    if number is None or number <= 0:
        reasons.append(f"{field} must be a positive number")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
