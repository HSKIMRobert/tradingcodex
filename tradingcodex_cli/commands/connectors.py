from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tradingcodex_cli.commands.utils import print_json
from tradingcodex_service.application import brokers
from tradingcodex_service.application.operator_authority import (
    PROVIDER_SOURCE_APPROVE,
    PROVIDER_SOURCE_REVOKE,
    _issue_operator_authority,
    provider_source_approval_resource,
    provider_source_revocation_resource,
)


def _require_interactive_operator_terminal(action: str) -> None:
    if not sys.stdin.isatty():
        raise PermissionError(
            f"provider source {action} requires an interactive operator terminal; piped or automated input is not accepted"
        )


def connectors(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "status"
    if sub == "status":
        result = brokers.get_connector_build_status(root, {})
        print_json(result)
        return
    if sub == "providers":
        result = brokers.list_broker_adapter_providers(root, {})
        print_json(result)
        return
    if sub == "inspect-provider":
        parser = argparse.ArgumentParser(prog="tcx connectors inspect-provider")
        parser.add_argument("provider_id")
        args = parser.parse_args(argv[1:])
        print_json(brokers.inspect_workspace_broker_provider_source(root, args.provider_id))
        return
    if sub == "approve-provider":
        parser = argparse.ArgumentParser(
            prog="tcx connectors approve-provider",
            description="Approve one exact workspace provider bundle from an interactive operator terminal.",
        )
        parser.add_argument("provider_id")
        args = parser.parse_args(argv[1:])
        _require_interactive_operator_terminal("approval")
        status = brokers.inspect_workspace_broker_provider_source(root, args.provider_id)
        source_sha256 = str(status.get("provider_py_sha256") or "")
        bundle_sha256 = str(status.get("bundle_sha256") or "")
        relative_path = str(status.get("path") or "")
        if status.get("kind") != "workspace" or not source_sha256 or not bundle_sha256 or not relative_path:
            raise ValueError(f"workspace provider source is unavailable: {args.provider_id}")
        print(f"Provider: {args.provider_id}")
        print(f"Source: {relative_path}")
        print(f"provider.py SHA-256: {source_sha256}")
        print(f"Bundle SHA-256: {bundle_sha256}")
        print("Approved provider Python executes with TradingCodex service authority after restart.")
        expected_confirmation = f"{args.provider_id} {bundle_sha256}"
        confirmation = input(f'Type "{expected_confirmation}" to approve this exact source: ').strip()
        if confirmation != expected_confirmation:
            raise PermissionError("provider source approval was not confirmed")
        operator_authority = _issue_operator_authority(
            root,
            action=PROVIDER_SOURCE_APPROVE,
            resource=provider_source_approval_resource(args.provider_id, bundle_sha256),
        )
        print_json(
            brokers.approve_workspace_broker_provider_source(
                root,
                args.provider_id,
                expected_bundle_sha256=bundle_sha256,
                operator_authority=operator_authority,
            )
        )
        return
    if sub == "revoke-provider":
        parser = argparse.ArgumentParser(
            prog="tcx connectors revoke-provider",
            description="Revoke a workspace provider source from an interactive operator terminal.",
        )
        parser.add_argument("provider_id")
        args = parser.parse_args(argv[1:])
        _require_interactive_operator_terminal("revocation")
        expected_confirmation = f"REVOKE {args.provider_id}"
        confirmation = input(f'Type "{expected_confirmation}" to revoke this provider source: ').strip()
        if confirmation != expected_confirmation:
            raise PermissionError("provider source revocation was not confirmed")
        operator_authority = _issue_operator_authority(
            root,
            action=PROVIDER_SOURCE_REVOKE,
            resource=provider_source_revocation_resource(args.provider_id),
        )
        print_json(
            brokers.revoke_workspace_broker_provider_source(
                root,
                args.provider_id,
                operator_authority=operator_authority,
            )
        )
        return
    if sub == "connect":
        parser = argparse.ArgumentParser(prog="tcx connectors connect")
        parser.add_argument("broker_id")
        parser.add_argument("--provider-id", required=True)
        parser.add_argument("--display-name", default="")
        parser.add_argument("--credential-ref", default="")
        parser.add_argument("--environment", default="")
        parser.add_argument("--mode", choices=["read-only", "validation", "live-request"], default="read-only")
        args = parser.parse_args(argv[1:])
        result = brokers.connect_broker_connector(
            root,
            {
                "provider_id": args.provider_id,
                "broker_id": args.broker_id,
                "display_name": args.display_name,
                "credential_ref": args.credential_ref,
                "environment": args.environment,
                "mode": args.mode,
                "principal_id": "head-manager",
            },
        )
        print_json(result)
        return
    if sub == "scaffold":
        parser = argparse.ArgumentParser(prog="tcx connectors scaffold")
        parser.add_argument("broker_id")
        parser.add_argument("--provider-id", required=True)
        parser.add_argument("--display-name", default="")
        parser.add_argument("--credential-ref", default="")
        parser.add_argument("--environment", default="")
        args = parser.parse_args(argv[1:])
        result = brokers.scaffold_broker_connector(
            root,
            {
                "provider_id": args.provider_id,
                "broker_id": args.broker_id,
                "display_name": args.display_name,
                "credential_ref": args.credential_ref,
                "environment": args.environment,
                "principal_id": "head-manager",
            },
        )
        print_json(result)
        return
    if sub == "register":
        parser = argparse.ArgumentParser(prog="tcx connectors register")
        parser.add_argument("--provider-id", required=True)
        parser.add_argument("--broker-id", required=True)
        parser.add_argument("--display-name", default="")
        parser.add_argument("--credential-ref", required=True)
        parser.add_argument("--environment", default="")
        args = parser.parse_args(argv[1:])
        result = brokers.register_broker_connector(
            root,
            {
                "provider_id": args.provider_id,
                "broker_id": args.broker_id,
                "display_name": args.display_name,
                "credential_ref": args.credential_ref,
                "environment": args.environment,
                "principal_id": "head-manager",
            },
        )
        print_json(result)
        return
    if sub == "validate":
        parser = argparse.ArgumentParser(prog="tcx connectors validate")
        parser.add_argument("broker_id")
        args = parser.parse_args(argv[1:])
        result = brokers.validate_broker_connector_build(root, {"broker_id": args.broker_id, "principal_id": "head-manager"})
        print_json(result)
        return
    raise ValueError(
        "Usage: tcx connectors status|providers|inspect-provider|approve-provider|revoke-provider\n"
        "       tcx connectors inspect-provider <provider-id>\n"
        "       tcx connectors approve-provider <provider-id>\n"
        "       tcx connectors revoke-provider <provider-id>\n"
        "         (approval and revocation require interactive operator-terminal input)\n"
        "       tcx connectors connect <broker-id> --provider-id <provider-id> [--display-name <name>] [--credential-ref <ref>] [--environment <env>] [--mode read-only|validation|live-request]\n"
        "       tcx connectors scaffold <broker-id> --provider-id <provider-id> [--display-name <name>] [--credential-ref <ref>] [--environment <env>]\n"
        "       tcx connectors register --provider-id <provider-id> --broker-id <id> [--display-name <name>] --credential-ref <ref> [--environment <env>]\n"
        "       tcx connectors validate <broker-id>"
    )
