# Licensing and Commercialization

TradingCodex uses an Apache-2.0 open-core licensing strategy.

## Baseline License

Unless a file, directory, or separately distributed artifact states otherwise,
the source code, generated workspace templates, and project documentation in
this repository are licensed under the Apache License, Version 2.0.

The project license is intentionally permissive so individual investors,
researchers, plugin authors, broker/data integration developers, and
commercial users can inspect, run, modify, and redistribute the open core.

The Apache-2.0 license grants copyright and patent permissions for covered
materials. It does not grant trademark rights.

## Open-Core Boundary

The open core includes:

- local Django service plane, CLI, and MCP gateway code
- generated workspace templates
- paper and validation-only execution paths
- role, policy, audit, research-memory, and harness primitives
- public project documentation

The following may be offered under separate commercial terms:

- hosted or managed TradingCodex services
- verified live broker adapters
- verified market-data adapters
- enterprise policy, compliance, audit, and supervision packs
- team administration, support, onboarding, and managed deployment services
- official certifications, compatibility badges, and marketplace placements

Commercial offerings must not bypass the product safety model. Executable
actions still flow through service-layer policy, approval, connection, and audit
checks.

## Generated Workspaces and User Content

Generated workspaces contain TradingCodex scaffold files copied from this
repository. Those scaffold files remain under Apache-2.0 unless marked
otherwise.

User-created research notes, portfolio data, order records, configuration
secrets, broker credentials, and other user-provided content are not licensed
to TradingCodex by merely existing in a generated workspace. They remain owned
by the user unless the user separately chooses to license or contribute them.

Generated workspaces do not own the canonical investment DB. They are clients
and provenance sources for the central local TradingCodex service.

## Contributions

TradingCodex uses an inbound-equals-outbound contribution model. Unless
explicitly agreed otherwise in writing, contributions intentionally submitted
for inclusion in this repository are submitted under Apache-2.0.

Contributors certify contribution rights using the Developer Certificate of
Origin 1.1 (DCO). The contribution workflow is documented in
`CONTRIBUTING.md`.

The project does not require a Contributor License Agreement by default. If a
future commercial or relicensing strategy requires a CLA, that change must be
made explicitly and documented in the source-of-truth docs.

## Trademarks

The TradingCodex name, future logos, and official product marks are reserved
for the project maintainer and authorized official offerings. Community forks,
plugins, adapters, and integrations may truthfully describe compatibility, but
must not imply official endorsement or verification without permission.

Trademark guidance is documented in `TRADEMARKS.md`.

## Legal Review

This document records project intent and repository policy. It is not legal,
tax, financial, investment, or regulatory advice. Before launching paid
services, verified adapters, marketplace terms, or enterprise offerings, the
project maintainer should obtain jurisdiction-specific legal review.
