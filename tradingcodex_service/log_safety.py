from __future__ import annotations

import logging
import os
import re


REDACTED = "<redacted>"


def redact_log_text(value: str) -> str:
    text = str(value or "")
    secret_values = sorted(
        {
            item
            for key, item in os.environ.items()
            if item and len(item) >= 4 and re.search(r"secret|password|api[_-]?key|token|credential", key, flags=re.I)
        },
        key=len,
        reverse=True,
    )
    for secret in secret_values:
        text = text.replace(secret, REDACTED)
    text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", rf"\1{REDACTED}", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password|credential|authorization)\s*[:=]\s*)([^\s,;&]+)",
        rf"\1{REDACTED}",
        text,
    )
    return re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+@", rf"\1{REDACTED}@", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))
