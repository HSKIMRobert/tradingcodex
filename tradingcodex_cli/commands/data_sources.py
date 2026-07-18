from __future__ import annotations

import argparse
from pathlib import Path

from tradingcodex_cli.commands.utils import print_json
from tradingcodex_service.application import data_sources as service


def data_sources(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print_help()
        return
    integration = argv[0]
    if integration != "openbb":
        raise ValueError("Usage: tcx data-sources openbb provision|configure|enable|status|probe|disable|clear-credential-ref")
    _openbb(root, argv[1:])


def _openbb(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print_openbb_help()
        return
    subcommand = argv[0]
    values = argv[1:]
    if subcommand == "provision":
        parser = argparse.ArgumentParser(
            prog="tcx data-sources openbb provision",
            description="Explicitly download and compatibility-check the latest optional OpenBB MCP runtime.",
            allow_abbrev=False,
        )
        parser.parse_args(values)
        print_json(service.provision_openbb(root, {}))
        return
    if subcommand == "configure":
        parser = argparse.ArgumentParser(prog="tcx data-sources openbb configure", allow_abbrev=False)
        parser.add_argument("provider")
        parser.add_argument("--access", required=True, choices=sorted(service.DECLARED_ACCESS_VALUES))
        parser.add_argument(
            "--credential-ref",
            action="append",
            default=[],
            help="Repeatable <provider-slot>=env:<ENV_NAME>; raw values are rejected.",
        )
        args = parser.parse_args(values)
        print_json(
            service.configure_openbb_provider(
                root,
                {
                    "provider": args.provider,
                    "access": args.access,
                    "credential_refs": args.credential_ref,
                },
            )
        )
        return
    if subcommand == "enable":
        parser = argparse.ArgumentParser(prog="tcx data-sources openbb enable", allow_abbrev=False)
        parser.add_argument("provider")
        parser.add_argument("--data-kind", action="append", required=True)
        parser.add_argument("--auto-use", choices=sorted(service.AUTO_USE_VALUES))
        parser.add_argument("--secondary-consent", action="store_true")
        args = parser.parse_args(values)
        print_json(
            service.enable_openbb_provider(
                root,
                {
                    "provider": args.provider,
                    "data_kinds": args.data_kind,
                    "auto_use": args.auto_use,
                    "secondary_consent": args.secondary_consent,
                },
            )
        )
        return
    if subcommand == "status":
        parser = argparse.ArgumentParser(prog="tcx data-sources openbb status", allow_abbrev=False)
        parser.add_argument("provider", nargs="?")
        parser.add_argument("--data-kind", default="")
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args(values)
        status = service.get_data_source_status(
            root,
            {"provider": args.provider or "", "data_kind": args.data_kind},
        )
        if args.json:
            print_json(status)
        else:
            _print_status(status)
        return
    if subcommand == "probe":
        parser = argparse.ArgumentParser(prog="tcx data-sources openbb probe", allow_abbrev=False)
        parser.add_argument("provider")
        parser.add_argument("--data-kind", required=True)
        parser.add_argument("--symbol", default="")
        args = parser.parse_args(values)
        print_json(
            service.probe_openbb_provider(
                root,
                {"provider": args.provider, "data_kind": args.data_kind, "symbol": args.symbol},
            )
        )
        return
    if subcommand == "disable":
        parser = argparse.ArgumentParser(prog="tcx data-sources openbb disable", allow_abbrev=False)
        parser.add_argument("provider", nargs="?")
        parser.add_argument("--all", action="store_true")
        args = parser.parse_args(values)
        if bool(args.provider) == bool(args.all):
            parser.error("provide exactly one provider or --all")
        print_json(service.disable_openbb_provider(root, {"provider": args.provider or "", "all": args.all}))
        return
    if subcommand == "clear-credential-ref":
        parser = argparse.ArgumentParser(
            prog="tcx data-sources openbb clear-credential-ref",
            allow_abbrev=False,
        )
        parser.add_argument("provider")
        parser.add_argument("--slot", required=True)
        args = parser.parse_args(values)
        print_json(service.clear_openbb_credential_ref(root, {"provider": args.provider, "slot": args.slot}))
        return
    if subcommand == "serve":
        parser = argparse.ArgumentParser(prog="tcx data-sources openbb serve", allow_abbrev=False)
        parser.add_argument("--principal", required=True)
        args = parser.parse_args(values)
        raise SystemExit(service.serve_openbb(root, {"principal": args.principal}))
    raise ValueError("Usage: tcx data-sources openbb provision|configure|enable|status|probe|disable|clear-credential-ref")


def _print_status(status: dict[str, object]) -> None:
    print(f"OpenBB enabled: {str(bool(status.get('enabled'))).lower()}")
    print(f"Runtime: {status.get('runtime')}")
    print(f"Projection: {status.get('projection')}")
    providers = status.get("providers")
    if isinstance(providers, list) and providers:
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            print(
                f"- {provider.get('provider')}: enabled={str(bool(provider.get('enabled'))).lower()}, "
                f"access={provider.get('declared_access')}, credentials={provider.get('credentials')}, "
                f"observed={provider.get('observed_access')}, auto-use={provider.get('auto_use')}"
            )
            slot_hints = provider.get("credential_slot_hints")
            if isinstance(slot_hints, list) and slot_hints:
                print(
                    "  credential-slot-hints="
                    f"{','.join(str(item) for item in slot_hints)} "
                    f"source={provider.get('credential_slot_hint_source')}"
                )
    else:
        print("Providers: none configured")
    actions = status.get("recommended_actions")
    if isinstance(actions, list) and actions:
        print("Next:")
        for action in actions:
            print(f"  {action}")


def print_help() -> None:
    print("Usage: tcx data-sources openbb provision|configure|enable|status|probe|disable|clear-credential-ref")


def print_openbb_help() -> None:
    print(
        """TradingCodex optional OpenBB integration

Usage:
  tcx data-sources openbb provision
  tcx data-sources openbb configure <provider> --access keyless|free|paid|unknown [--credential-ref <slot>=env:<NAME>]...
  tcx data-sources openbb enable <provider> --data-kind <kind> [--data-kind <kind>]... [--auto-use allow|ask|deny] [--secondary-consent]
  tcx data-sources openbb status [provider] [--data-kind <kind>] [--json]
  tcx data-sources openbb probe <provider> --data-kind <kind> [--symbol <symbol>]
  tcx data-sources openbb disable <provider>|--all
  tcx data-sources openbb clear-credential-ref <provider> --slot <slot>

OpenBB is not installed during attach. Credential values stay in the environment;
TradingCodex stores only env:NAME references. Configuration changes require a
workspace update followed by a full Codex restart and a new task, not a Django
service restart.
"""
    )
