from __future__ import annotations

import argparse
from pathlib import Path

from tradingcodex_cli.commands.utils import print_json
from tradingcodex_service.application import data_sources as openbb


def data_sources(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print_help()
        return
    if argv.pop(0) != "openbb":
        raise ValueError("Usage: tcx data-sources openbb enable|status|disable|env")
    _openbb(root, argv)


def _openbb(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print_help()
        return
    subcommand, values = argv[0], argv[1:]
    if subcommand == "enable":
        parser = argparse.ArgumentParser(prog="tcx data-sources openbb enable", allow_abbrev=False)
        parser.add_argument("--env-var", action="append", default=[])
        args = parser.parse_args(values)
        print_json(openbb.enable_openbb(root, args.env_var))
        return
    if subcommand == "status":
        parser = argparse.ArgumentParser(prog="tcx data-sources openbb status", allow_abbrev=False)
        parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
        parser.parse_args(values)
        print_json(openbb.get_openbb_status(root))
        return
    if subcommand == "disable":
        argparse.ArgumentParser(prog="tcx data-sources openbb disable", allow_abbrev=False).parse_args(values)
        print_json(openbb.disable_openbb(root))
        return
    if subcommand == "env" and values:
        action, remaining = values[0], values[1:]
        parser = argparse.ArgumentParser(prog=f"tcx data-sources openbb env {action}", allow_abbrev=False)
        if action == "list":
            parser.parse_args(remaining)
            print_json(openbb.get_openbb_status(root))
            return
        parser.add_argument("name")
        args = parser.parse_args(remaining)
        if action == "add":
            print_json(openbb.add_openbb_env_var(root, args.name))
            return
        if action == "remove":
            print_json(openbb.remove_openbb_env_var(root, args.name))
            return
    raise ValueError("Usage: tcx data-sources openbb enable|status|disable|env add|remove|list")


def print_help() -> None:
    print(
        """Usage:
  tcx data-sources openbb enable [--env-var <NAME>]...
  tcx data-sources openbb status
  tcx data-sources openbb disable
  tcx data-sources openbb env add|remove <NAME>
  tcx data-sources openbb env list

OpenBB is optional. These commands store only environment-variable names;
Codex inherits their values when it starts the official OpenBB MCP server.
Run `tcx update --skip-refresh --no-doctor` and restart Codex after a change.
"""
    )
