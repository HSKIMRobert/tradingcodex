#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: summarize_connector_status.py <status.json>", file=sys.stderr)
        return 2
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(summarize(data))
    return 0


def summarize(data: dict[str, Any]) -> str:
    connection = data.get("connection") if isinstance(data.get("connection"), dict) else data
    profile = connection.get("capability_profile") or (connection.get("metadata") or {}).get("capability_profile") or {}
    lines = [
        f"broker: {connection.get('broker_id', '')}",
        f"status: {connection.get('status', '')}",
        f"health: {(data.get('health') or {}).get('status', connection.get('last_health_status', ''))}",
        f"template: {profile.get('template_id', '')}",
        f"assets: {', '.join(profile.get('asset_classes') or [])}",
        f"products: {', '.join(profile.get('products') or [])}",
        f"execution_posture: {profile.get('execution_posture', '')}",
        f"blocked_surfaces: {', '.join(profile.get('blocked_surfaces') or [])}",
    ]
    blockers = connection.get("blockers") or profile.get("blockers") or []
    if blockers:
        lines.append("blockers: " + "; ".join(str(item) for item in blockers))
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
