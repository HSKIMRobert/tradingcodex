from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingcodex_service.application import brokers


def connectors(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "status"
    if sub == "status":
        result = brokers.get_connector_build_status(root, {})
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    if sub == "providers":
        result = brokers.list_broker_adapter_providers(root, {})
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    if sub == "scaffold":
        parser = argparse.ArgumentParser(prog="tcx connectors scaffold")
        parser.add_argument("broker_id")
        parser.add_argument("--provider", "--provider-id", dest="provider_id", default="")
        parser.add_argument("--broker-id", required=True)
        parser.add_argument("--credential-ref", default="")
        parser.add_argument("--environment", default="")
        raw_args = argv[1:]
        if raw_args and "--broker-id" not in raw_args:
            raw_args = [raw_args[0], "--broker-id", raw_args[0], *raw_args[1:]]
        args = parser.parse_args(raw_args)
        result = brokers.scaffold_broker_connector(
            root,
            {
                "provider": args.provider_id,
                "broker_id": args.broker_id,
                "credential_ref": args.credential_ref,
                "environment": args.environment,
                "principal_id": "head-manager",
            },
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    if sub == "register":
        parser = argparse.ArgumentParser(prog="tcx connectors register")
        parser.add_argument("provider_arg", nargs="?")
        parser.add_argument("--provider", "--provider-id", dest="provider_id", default="")
        parser.add_argument("--broker-id", required=True)
        parser.add_argument("--credential-ref", required=True)
        parser.add_argument("--environment", default="")
        args = parser.parse_args(argv[1:])
        provider_id = args.provider_id or args.provider_arg or ""
        result = brokers.register_broker_connector(
            root,
            {
                "provider": provider_id,
                "broker_id": args.broker_id,
                "credential_ref": args.credential_ref,
                "environment": args.environment,
                "principal_id": "head-manager",
            },
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    if sub == "validate":
        parser = argparse.ArgumentParser(prog="tcx connectors validate")
        parser.add_argument("broker_id")
        args = parser.parse_args(argv[1:])
        result = brokers.validate_broker_connector_build(root, {"broker_id": args.broker_id, "principal_id": "head-manager"})
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    raise ValueError(
        "Usage: tcx connectors status|providers\n"
        "       tcx connectors scaffold <broker-id> [--provider <provider-id>] [--credential-ref <ref>] [--environment <env>]\n"
        "       tcx connectors register --provider <provider-id> --broker-id <id> --credential-ref <ref> [--environment <env>]\n"
        "       tcx connectors validate <broker-id>"
    )
