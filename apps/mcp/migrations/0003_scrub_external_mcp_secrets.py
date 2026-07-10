import hashlib
import json
import re

from django.db import migrations


ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_REFERENCE = re.compile(r"^env:[A-Za-z_][A-Za-z0-9_]*$")
INLINE_SECRET = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|password|credential|authorization)\s*[:=]\s*)([^\s,;&]+)"
)
REDACTED = "<redacted>"


def _redact(value):
    if isinstance(value, dict):
        result = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key.lower() == "env":
                result[key] = REDACTED
            elif key.lower() == "credential_ref" and isinstance(item, str) and (
                ENV_REFERENCE.fullmatch(item) or re.fullmatch(r"(?:os-keychain|keyring|secret)://[A-Za-z0-9._~:/@+-]+", item)
            ):
                result[key] = item
            elif _is_sensitive_field(key):
                result[key] = REDACTED
            else:
                result[key] = _redact(item)
        return result
    if isinstance(value, list):
        result = []
        redact_next = False
        for item in value:
            if redact_next:
                result.append(REDACTED)
                redact_next = False
                continue
            result.append(_redact(item))
            redact_next = isinstance(item, str) and bool(
                re.fullmatch(r"--?(?:api[_-]?key|token|secret|password|credential|authorization)", item, flags=re.I)
            )
        return result
    if isinstance(value, str):
        value = re.sub(r"(?i)(bearer\s+)[^\s,;]+", rf"\1{REDACTED}", value)
        value = INLINE_SECRET.sub(rf"\1{REDACTED}", value)
        return re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+:[^/@\s]+@", rf"\1{REDACTED}@", value)
    return value


def _is_sensitive_field(key):
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return normalized.endswith(
        ("secret", "secrets", "password", "passphrase", "credential", "credentials", "apikey", "accesstoken", "refreshtoken", "token", "authorization", "cookie")
    )


def _stable_hash(value):
    encoded = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scrub_external_mcp_secrets(apps, schema_editor):
    McpRouter = apps.get_model("mcp", "McpRouter")
    McpExternalTool = apps.get_model("mcp", "McpExternalTool")
    McpToolCall = apps.get_model("mcp", "McpToolCall")
    McpExternalToolCall = apps.get_model("mcp", "McpExternalToolCall")
    McpExternalPermissionRequest = apps.get_model("mcp", "McpExternalPermissionRequest")
    AuditEvent = apps.get_model("audit", "AuditEvent")

    for router in McpRouter.objects.all().iterator():
        stored = router.env if isinstance(router.env, dict) else {}
        safe = {
            str(key): str(reference)
            for key, reference in stored.items()
            if ENV_NAME.fullmatch(str(key)) and ENV_REFERENCE.fullmatch(str(reference))
        }
        changed = safe != stored
        router.env = safe
        credential_ref = str(router.credential_ref or "")
        if credential_ref and not (
            ENV_REFERENCE.fullmatch(credential_ref)
            or re.fullmatch(r"(?:os-keychain|keyring|secret)://[A-Za-z0-9._~:/@+-]+", credential_ref)
        ):
            router.credential_ref = ""
            changed = True
        router.last_error = _redact(router.last_error)
        launch_text = " ".join([router.command, *(router.args or []), router.url])
        if (
            INLINE_SECRET.search(launch_text)
            or re.search(r"(?i)bearer\s+", launch_text)
            or re.search(r"(?i)--?(?:api[_-]?key|token|secret|password|credential|authorization)(?:\s|=)", launch_text)
            or re.search(r"(?i)^[a-z][a-z0-9+.-]*://[^/@\s]+:[^/@\s]+@", router.url or "")
        ):
            router.command = ""
            router.args = []
            router.url = ""
            changed = True
        if changed:
            router.enabled = False
            router.last_status = "disabled"
            router.last_error = "Stored inline environment values were removed; rotate affected credentials and register env references again."
        router.save(update_fields=["env", "credential_ref", "command", "args", "url", "enabled", "last_status", "last_error"])

    for tool in McpExternalTool.objects.all().iterator():
        before = (tool.description, tool.input_schema, tool.output_schema, tool.conditions)
        tool.description = _redact(tool.description)
        tool.input_schema = _redact(tool.input_schema)
        tool.output_schema = _redact(tool.output_schema)
        tool.conditions = _redact(tool.conditions)
        after = (tool.description, tool.input_schema, tool.output_schema, tool.conditions)
        if after != before:
            tool.enabled = False
            tool.drift_detected = True
            tool.review_status = "schema_changed"
            tool.schema_hash = _stable_hash(
                {
                    "primitive": tool.primitive,
                    "name": tool.external_name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "output_schema": tool.output_schema,
                }
            )
            tool.save(
                update_fields=[
                    "description",
                    "input_schema",
                    "output_schema",
                    "conditions",
                    "enabled",
                    "drift_detected",
                    "review_status",
                    "schema_hash",
                ]
            )

    for record in McpToolCall.objects.all().iterator():
        record.request = _redact(record.request)
        record.response = _redact(record.response)
        record.error = _redact(record.error)
        record.request_hash = _stable_hash(record.request)
        record.result_hash = _stable_hash(record.response)
        record.save(update_fields=["request", "response", "error", "request_hash", "result_hash"])
    for record in McpExternalToolCall.objects.all().iterator():
        record.request = _redact(record.request)
        record.response = _redact(record.response)
        record.reasons = _redact(record.reasons)
        record.request_hash = _stable_hash(record.request)
        record.result_hash = _stable_hash(record.response)
        record.save(update_fields=["request", "response", "reasons", "request_hash", "result_hash"])
    for record in McpExternalPermissionRequest.objects.all().iterator():
        record.arguments_summary = _redact(record.arguments_summary)
        record.reasons = _redact(record.reasons)
        record.decision_reason = _redact(record.decision_reason)
        record.save(update_fields=["arguments_summary", "reasons", "decision_reason"])
    for record in AuditEvent.objects.all().iterator():
        record.payload = _redact(record.payload)
        record.request_hash = _stable_hash(record.payload)
        record.result_hash = _stable_hash(record.payload.get("payload", record.payload) if isinstance(record.payload, dict) else record.payload)
        record.save(update_fields=["payload", "request_hash", "result_hash"])


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
        ("mcp", "0002_mcpexternalpermissionrequest"),
    ]

    operations = [migrations.RunPython(scrub_external_mcp_secrets, migrations.RunPython.noop)]
