# Contributing to TradingCodex

TradingCodex is an Apache-2.0 open-core project. The core repository is meant
to be easy to study, fork, extend, and use commercially, while official
commercial offerings, hosted services, verified adapters, enterprise packs,
and TradingCodex marks may be governed by separate terms.

## License of Contributions

Unless explicitly agreed otherwise in writing, every contribution intentionally
submitted for inclusion in this repository is submitted under the Apache
License, Version 2.0.

TradingCodex uses an inbound-equals-outbound contribution model: by
contributing, you agree that your contribution can be distributed under the
same Apache-2.0 license used by the project.

## Developer Certificate of Origin

Contributors must certify that they have the right to submit their work by
using the Developer Certificate of Origin 1.1 (DCO):

https://developercertificate.org/

Add a sign-off line to every commit:

```text
Signed-off-by: Your Name <you@example.com>
```

Git can add it automatically:

```bash
git commit -s
```

## Product and Safety Rules

Before changing product rules, generated workspace behavior, subagent roles,
guardrails, MCP tools, policy behavior, Admin operations, or execution flows,
read the docs in `docs/` and update the relevant docs in the same change.

Important boundaries:

- Live broker adapters are not part of the open core unless explicitly added
  by a future product decision.
- Do not commit broker API keys, credentials, tokens, private account data, or
  other secrets.
- Executable trading actions must continue to flow through TradingCodex
  service-layer policy, approval, adapter, and audit checks.
- Public equity is the deepest first investing sleeve, but changes should
  preserve the broader multi-asset direction.

## Trademarks and Commercial Use

The Apache-2.0 license grants copyright and patent permissions for the code.
It does not grant rights to use TradingCodex names, logos, or official product
branding. See `TRADEMARKS.md`.

Forks and integrations are welcome, but they should avoid implying that they
are official TradingCodex distributions, hosted services, or verified adapters
unless the project maintainer has granted written permission.
