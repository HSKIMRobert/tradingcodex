from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingcodex_cli.commands.utils import print_json
from tradingcodex_cli.startup_status import detect_codex_permission_status
from tradingcodex_service.application.customization import (
    build_customization_status,
    discover_codex_mcp_servers,
    write_codex_mcp_server_config,
)
from tradingcodex_service.application.common import workspace_launcher_command


def build(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print_build_help()
        return
    section = argv[0]
    rest = argv[1:]
    if section == "status":
        _build_status(root, rest)
        return
    if section == "codex-mcp":
        _codex_mcp(root, rest)
        return
    if section == "permission":
        raise ValueError("External MCP consent moved to `tcx mcp permission`")
    raise ValueError("Usage: tcx build status|codex-mcp")


def _build_status(root: Path, argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="tcx build status", allow_abbrev=False)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    permission = detect_codex_permission_status(root)
    status = build_customization_status(root, full_access_detected=bool(permission.get("full_access_detected")))
    status["permission_status"] = permission
    if args.json:
        print_json(status)
        return
    contract = status["authorization_contract"]
    print("Build authorization: exact current root native Codex turn")
    print(f"Required first line: {contract['exact_first_line']}")
    display_permission = str(permission["codex_permission"]).replace("_", "-")
    print(f"Codex permission: {display_permission} (advisory)")
    print(f"Codex MCP servers: {status['codex_mcp']['count']}")
    if status["mode_status"].get("legacy_mode_file_present"):
        print(f"Legacy mode file: {status['mode_status']['path']} (ignored)")


def _codex_mcp(root: Path, argv: list[str]) -> None:
    if not argv:
        raise ValueError("Usage: tcx build codex-mcp discover|add")
    action = argv[0]
    rest = argv[1:]
    if action == "discover":
        parser = argparse.ArgumentParser(prog="tcx build codex-mcp discover", allow_abbrev=False)
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--workspace-only", action="store_true")
        args = parser.parse_args(rest)
        # Build is workspace-local. Global discovery remains a user-terminal
        # concern even when an older caller omits --workspace-only.
        result = discover_codex_mcp_servers(root, include_global=False, record=True)
        print_json(result)
        return
    if action == "import":
        parser = argparse.ArgumentParser(prog="tcx build codex-mcp import", allow_abbrev=False)
        parser.add_argument("--source", choices=["workspace", "global", "any"], default="workspace")
        parser.add_argument("--name", required=True)
        parser.parse_args(rest)
        launcher = workspace_launcher_command()
        raise ValueError(
            "External MCP import is an operator action, not a Build action. "
            f"Run `{launcher} mcp external import-codex --source "
            "workspace|global|any --name <server>` from an interactive user terminal."
        )
    if action == "add":
        parser = argparse.ArgumentParser(prog="tcx build codex-mcp add", allow_abbrev=False)
        parser.add_argument("--scope", choices=["workspace"], default="workspace")
        parser.add_argument("--name", required=True)
        parser.add_argument("--transport", default="stdio")
        parser.add_argument("--command", default="")
        parser.add_argument("--url", default="")
        parser.add_argument("--args-json", default="")
        parser.add_argument("--arg", action="append", default=[])
        parser.add_argument("--env-key", action="append", default=[])
        parser.add_argument("--credential-ref", default="")
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(rest)
        parsed_args = json.loads(args.args_json) if args.args_json else args.arg
        if not isinstance(parsed_args, list):
            raise ValueError("--args-json must be a JSON array")
        print_json(
            write_codex_mcp_server_config(
                root,
                name=args.name,
                scope=args.scope,
                transport=args.transport,
                command=args.command,
                args=[str(item) for item in parsed_args],
                url=args.url,
                env_keys=[str(item) for item in args.env_key],
                credential_ref=args.credential_ref,
                dry_run=args.dry_run,
            )
        )
        return
    raise ValueError("Usage: tcx build codex-mcp discover|add")


def print_build_help() -> None:
    launcher = workspace_launcher_command()
    print(f"""TradingCodex Build

Usage:
  {launcher} build status [--json]
  {launcher} build codex-mcp discover [--workspace-only] [--json]
  {launcher} build codex-mcp add --name <server> [--scope workspace] [--command <cmd>] [--arg <arg>] [--args-json <json>] [--env-key KEY] [--dry-run]

Agent-driven Codex mutation requires a root native turn whose exact first line
is `$tcx-build`, and this Build command writes workspace scope only. Importing
a Codex MCP entry into the External MCP Gate is an interactive operator action:
`{launcher} mcp external import-codex`. External MCP consent is managed with
`{launcher} mcp permission`.
""")
