from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from tradingcodex_cli.generator import DEFAULT_MODULE_IDS, bootstrap_workspace, load_module_registry, resolve_module_graph, templates_dir


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print_help()
        return
    command = argv.pop(0)
    try:
        if command == "init":
            init(argv)
        elif command == "doctor":
            from tradingcodex_cli.workspace import doctor

            root = configure_workspace_env(Path.cwd())
            doctor(root, _option_value(argv, "--layer") or "all")
        elif command == "service":
            service(argv)
        elif command in {"subagents", "skills", "policy", "mcp", "db", "validate", "risk-check", "approve", "quality-check", "audit", "postmortem", "research", "explain-policy"}:
            configure_workspace_env(Path.cwd())
            from tradingcodex_cli.workspace import main as workspace_main

            workspace_main([command, *argv])
        else:
            raise ValueError(f"Unknown command: {command}")
    except Exception as exc:
        print(f"{program_name()}: {exc}", file=sys.stderr)
        sys.exit(1)


def init(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog=f"{program_name()} init")
    parser.add_argument("project_dir", nargs="?")
    parser.add_argument("--overwrite", action="store_true", help="overwrite files at matching generated workspace paths")
    parser.add_argument("--force", "-f", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-modules", action="store_true")
    args = parser.parse_args(argv)
    if args.list_modules:
        registry = load_module_registry(templates_dir())
        for module in resolve_module_graph(registry, DEFAULT_MODULE_IDS):
            print(f"{module.id}: {module.description}")
        return
    if not args.project_dir:
        parser.print_help()
        raise SystemExit(1)
    result = bootstrap_workspace(args.project_dir, force=args.overwrite or args.force, dry_run=args.dry_run)
    if args.dry_run:
        print(f"TradingCodex dry run: {result['targetDir']}")
        print(f"Modules: {', '.join(result['modules'])}")
        print(f"Capabilities: {', '.join(result['capabilities'])}")
        return
    configure_workspace_env(Path(result["targetDir"]))
    from tradingcodex_service.domain import ensure_runtime_database, persist_workspace_context_if_available, tradingcodex_db_path

    ensure_runtime_database(Path(result["targetDir"]))
    persist_workspace_context_if_available(Path(result["targetDir"]))
    print(f"TradingCodex workspace created: {result['targetDir']}")
    print(f"Modules: {', '.join(result['modules'])}")
    print(f"Django DB: {tradingcodex_db_path()}")
    print("\nNext:")
    print(f"  cd {result['targetDir']}")
    print("  ./tcx doctor")
    print("  Open the workspace in Codex and trust it; TradingCodex MCP will start the experimental local dashboard service at http://127.0.0.1:8000/")
    print("  Fully quit and restart Codex, then start from a new thread in this generated workspace so project MCP config is reloaded.")


def service(argv: list[str]) -> None:
    sub = argv[0] if argv else "runserver"
    if sub != "runserver":
        raise ValueError(f"Usage: {program_name()} service runserver [addrport] [django runserver args]")
    from django.core.management import execute_from_command_line

    configure_workspace_env(Path.cwd())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")
    execute_from_command_line(["manage.py", "runserver", *(argv[1:] or ["127.0.0.1:8000"])])


def configure_workspace_env(root: Path) -> Path:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")
    if not os.environ.get("TRADINGCODEX_WORKSPACE_ROOT"):
        os.environ["TRADINGCODEX_WORKSPACE_ROOT"] = str(root.resolve())
    return Path(os.environ["TRADINGCODEX_WORKSPACE_ROOT"]).resolve()


def _option_value(args: list[str], name: str) -> str | None:
    try:
        return args[args.index(name) + 1]
    except Exception:
        return None


def program_name() -> str:
    name = Path(sys.argv[0]).name
    return name if name == "tcx" else "tcx"


def print_help() -> None:
    print("""TradingCodex Python/Django

Usage:
  tcx init <workspace> [--overwrite]
  tcx init --list-modules
  tcx doctor [--layer <layer>]
  tcx subagents status
  tcx skills list [--all]
  tcx db path|status|migrate
  tcx research list
  tcx mcp stdio
  tcx service runserver [addrport] [django runserver args]
""")


if __name__ == "__main__":
    main()
