# Data Sources And OpenBB

This document owns TradingCodex's external-data acquisition order, supported
OpenBB integration, official-source fallback, credential-reference policy, and
data-source quality contract. Broker connectivity and execution remain separate
and are documented in [safety-policy-and-execution.md](./safety-policy-and-execution.md).

## Acquisition Order

TradingCodex treats source priority as an acquisition order, never as a trust
ranking:

1. Reuse an accepted current-run Dataset or Source Snapshot that exactly covers
   the requested identifiers, fields, period, cutoff, frequency, and adjustment
   posture. Dataset reuse requires an exact authenticated acquisition-receipt
   lookup; a title, provider label, or search card is not enough.
2. Use one relevant enabled user-added MCP or skill. An explicitly named source
   wins within this tier.
3. Use the opt-in TradingCodex-supported OpenBB integration.
4. Use TradingCodex's reviewed official-source registry and narrow public-web
   retrieval.

One producer owns each atomic data series. Other roles consume its Snapshot,
Dataset, acquisition receipt, or accepted artifact rather than fetching the
same series again. Independent series may still be acquired in parallel.

`strict` source policy may reuse only evidence already attested to the named
source, then calls only that source and returns the resulting gap. It may apply
one error-directed changed correction at the same source, but never falls
through. `preferred` means try the named source before continuing. `best_available`
uses the complete order above. A partial result freezes its valid rows and
routes only an authenticated missing field, identifier, or one exact
non-overlapping period to the next tier. A caller cannot mark a value missing
when it is present in every retained row merely to trigger another overlapping
fetch.

Fallback is a durable state machine, not an agent-memory convention. Each
attempt names the exact predecessor receipt chain. When a higher tier truly had
no relevant callable source, a bounded skipped-tier attestation records that
gap. The service rejects tier regression, a second distinct user capability,
strict-source fallback, missing ancestry, and residual rows that overlap a
preserved partial result. A same-tier TradingCodex provider change is allowed
only for the exact non-overlapping residual of a `partial_valid` predecessor.

An installed capability is not automatically trusted. Automatic use still
requires current-task callability, exact relevance, a read-only schema, public
input, allowed cost posture, and no account, secret, download, file mutation,
broker, order, or other side effect. Core evidence, safety, policy, approval,
and execution rules always remain authoritative.

## Result And Retry Contract

External attempts normalize to `complete_valid`, `partial_valid`,
`correctable_error`, `terminal_gap`, `unsafe`, `transient`,
`approval_required`, or `conflict`. The semantic attempt key combines the exact
tool, provider, identifier, fields, period or as-of, interval, and adjustment
policy.

A success or terminal outcome closes that key. Empty, authentication,
entitlement, rate-limit, timeout, truncation, permission, unsupported-coverage,
and deterministic failures are not submitted again unchanged in the same run.
One correction is allowed only when the returned error identifies an argument
and the correction changes that argument. Conflicting series are not averaged;
the producer first checks unit, currency, venue, calendar, vintage, and
adjustment comparability. A recorded provider/source conflict closes the
original semantic call and, under `preferred` or `best_available`, may advance
to the next source tier with exact receipt ancestry; `strict` still stops.

The transport does not determine evidence grade. An OpenBB response from an
unofficial aggregator can remain `screen-grade`; an exact official filing or
statistical release with complete identity and point-in-time metadata can
support `factual-baseline`. Conclusion-sensitive screening evidence still
requires official or primary corroboration when available.

## Supported OpenBB Integration

OpenBB is an optional recommended integration, not a TradingCodex dependency.
`tcx attach` and `tcx update` do not install it. A user explicitly provisions
the isolated runtime:

```bash
./tcx data-sources openbb provision
```

The supported integration runs the upstream OpenBB MCP server as a separate
stdio process below `TRADINGCODEX_HOME`. TradingCodex does not vendor, import,
modify, or place OpenBB code in the generated workspace or TradingCodex wheel.
The wrapper uses an isolated HOME and does not read the user's ambient OpenBB
settings, `.env`, or bundled OpenBB skills.

The version policy is floating latest. The first supported OpenBB start in a
Codex session performs one serialized refresh and writes a compatibility
receipt containing resolved package versions, origin and license metadata,
package and tool-schema digests, route inventory, and compatibility checks. An
offline refresh, incompatible release, unreviewed license change, or unsafe
tool surface quarantines the integration for that session. TradingCodex does
not silently use an older release; normal source fallback remains available.

Only evidence-producing roles receive the optional managed OpenBB MCP entry.
Head Manager, portfolio, risk, and judgment roles do not receive raw OpenBB
data tools. The managed policy rejects skill installation, broad category
activation, downloads, write-style HTTP methods, account and broker operations,
orders, file mutation, and tools with unknown side effects.

## Provider And Credential Setup

OpenBB has provider-specific credential slots rather than one universal API
key. Configure only an environment-variable reference:

```bash
./tcx data-sources openbb configure fmp \
  --access free \
  --credential-ref fmp_api_key=env:FMP_API_KEY

./tcx data-sources openbb enable fmp \
  --data-kind equity_price \
  --data-kind equity_fundamentals \
  --auto-use allow
```

Repeat `--credential-ref` for a provider that declares several slots. The CLI
rejects raw-looking values, URLs, whitespace, slots that are not
provider-prefixed and credential-shaped, and references other than `env:NAME`;
it does not infer a provider's real credential schema from the slot name. The
actual value exists only in the environment of the process that starts Codex.
It never enters the workspace, central DB, Codex configuration, prompt, skill,
MCP/API response, audit, artifact, or log.

`$tcx-server` is the conversational setup guide. It reads sanitized status,
explains the configured provider slot and access declaration, and gives the
exact terminal command; it never asks the user to paste a key. When no slot is
configured, status may return a provider-name-convention hint, explicitly
marked unverified until the user confirms it against current provider
documentation. After any state-changing OpenBB command, regenerate the
workspace projection:

```bash
./tcx update --skip-refresh --no-doctor
```

Then fully quit and restart Codex and open a new task.
Restarting the Django viewer service does not reload an OpenBB MCP credential.

Status keeps independent facts separate:

| Field | Values and meaning |
| --- | --- |
| `declared_access` | `keyless`, user-declared `free` or `paid`, or `unknown`; never inferred from key presence |
| `credentials` | `not_required`, `ref_missing`, `env_missing`, or `available` |
| `credential_slot_hint_source` | `not_required`, `configured`, or `provider_name_convention_unverified`; only `configured` is an exact stored slot |
| `runtime` | `missing`, `ready`, `incompatible`, or `drifted` |
| `projection` | `absent`, `current`, or `restart_required` |
| `observed_access` | `unprobed`, `callable`, `auth_failed`, `entitlement_failed`, or `rate_limited` |

Paid and unknown access defaults to `auto-use=ask`. A keyless provider remains
`ask` until a bounded probe observes it as callable; changing an allowed
provider to paid or unknown revokes `allow`. User-declared free providers may
be enabled with `allow`, but that declaration does not prove entitlement or
cost. An unofficial, personal-use, or redistribution-limited provider also
requires explicit secondary-source consent and remains bounded by its source
card and evidence-grade ceiling.

Useful commands are:

```text
./tcx data-sources openbb status [provider] [--json]
./tcx data-sources openbb probe <provider> --data-kind <kind> [--symbol <symbol>]
./tcx data-sources openbb disable [provider|--all]
./tcx data-sources openbb clear-credential-ref <provider> --slot <slot>
```

`status` is local and secret-free. `probe` is explicit because it may consume a
provider quota. Its result proves only the CLI process's current environment;
an already running MCP process keeps the credential and configuration digest
loaded at its own startup. Disabling a provider therefore remains
`restart_required` while a recorded OpenBB proxy process is still alive; status
does not report the integration absent merely because the next projection is
disabled.

## `tcx-openbb` Role Skill

`tcx-openbb` is a bundled shared role skill, not a user setup entrypoint. It is
available to fundamental, technical, news, macro, instrument, and valuation
producers when the acquisition order reaches OpenBB.

The skill searches reusable Dataset cards first and uses a
compatibility-receipt route when possible. A mapped route skips
`available_tools`, but an inactive mapped route still requires exactly one
`activate_tools` call before the data call. When schema drift makes discovery
necessary, the skill performs at most one narrow discovery and one activation
of no more than three exact tools for each exact workflow, role session, and
category/subcategory scope. A distinct assigned subcategory has a distinct
scope; presentation-only argument changes do not. It always supplies the provider explicitly,
requests only needed public fields, disables charts, and limits row-returning
calls to 120 observations. It validates the requested and returned provider,
identifiers, dates, currency, timezone, frequency, adjustment,
corporate-action posture, warnings, and coverage before recording the result.
It also binds promotion to the currently validated compatibility receipt hash;
a stale, tampered, license-drifted, or route/schema-drifted receipt cannot be
reused in the same session.

The skill never provisions OpenBB, handles raw credentials, changes provider
configuration, restarts a process, assigns trust or license posture, activates
broad categories, or weakens fallback and evidence gates.

## Durable Data And Readback

Every material attempt records a content-addressed Data Acquisition Receipt
using the current v4 receipt contract.
The receipt binds the workflow `run_id`, service-derived data `family_id`, Data
Need, source tier, user capability or OpenBB
transport, separately attested requested/returned/actual upstream provider,
requested/returned adjustment policy, exact tool FQN and route, OpenBB
compatibility-receipt hash when applicable, schema and sanitized query hashes,
result class, warnings, fallback reason, evidence grade, and returned Snapshot
and Dataset ids, exact predecessor receipt ancestry, and inherited skipped-tier
attestations. One owner lease applies to the normalized family for the run;
changing fields, role, or source policy cannot create a second owner. The
authenticated caller's role must equal the DataNeed owner,
and successful data must meet the bounded `screen-grade` or
`factual-baseline` minimum.

`record_external_data_result` uses a recoverable promotion transaction to store
a bounded Source Snapshot and, for tabular results, a canonical Dataset before
committing the receipt. Public Dataset/Snapshot reads and catalog refreshes
clean up an interrupted uncommitted promotion before returning data. Used rows
are preserved rather than reduced to a narrative summary.
`get_data_acquisition_receipt` resolves one exact receipt or Dataset id and
returns only authenticated source, evidence, coverage, Dataset/Snapshot
metadata, and lineage—never raw rows or provider queries.
`get_source_snapshot`, `get_dataset_rows`, and `export_dataset_csv` make the
evidence reproducible; export remains subject to the Dataset retention and
redistribution contract. The role-authenticated API exposes the same receipt
read at `/api/research/data-acquisition-receipts/{receipt_id}` and
`/api/research/datasets/{dataset_id}/acquisition-receipt`. Existing
`record_source_snapshot` and scratch-file `record_dataset_snapshot` calls remain
supported.

## Official Vanilla Sources

When higher acquisition tiers fail or require primary corroboration,
TradingCodex returns a deterministic official-source plan. The initial reviewed
registry includes:

| Posture | Sources |
| --- | --- |
| Keyless | SEC EDGAR, U.S. Treasury daily rates, BLS v1, ECB, World Bank, CFTC COT, and Bank of Canada reference series |
| Free-key opt-in | Korea FSC public market APIs, OpenDART, ECOS, KOSIS, BEA, EIA, and registered BLS v2 |

The registry distinguishes prices, reference rates, yields, filings,
fundamentals, macro series, energy statistics, and positioning. It does not
present CFTC positioning, central-bank FX, or Treasury reference curves as
executable market prices. Global exchange price, listed-option, and futures
coverage without a licensed or consented provider remains an explicit
`official_price_unavailable` gap.

`fetch_official_source_data` is the producer-only production last mile for the
seven keyless entries. It constructs requests only for reviewed HTTPS hosts,
never accepts caller-supplied URLs, headers, bodies, methods, or credentials,
and returns normalized rows plus a recorder-ready
`record_external_data_result_args` template rather than a raw HTTP body. The
supported identifiers are SEC `CIK` or `CIK/taxonomy/concept`; up to five BLS
series ids; Treasury `daily_treasury_yield_curve`,
`daily_treasury_real_yield_curve`, `daily_treasury_bill_rates`, or
`daily_treasury_long_term_rate`; ECB
`FLOW/SERIES_KEY`; World Bank `COUNTRY:INDICATOR`; the reviewed CFTC
`72hh-3qpy/CONTRACT_MARKET_CODE`; and an exact Bank of Canada series id.

The canonical official fallback executor is sequential: it calls each planned
source at most once, does not read credentials itself, caps normalized results
at 120 rows and 20,000 serialized characters, caps the HTTP body at 2 MiB, and
normalizes auth, entitlement, empty, stale, rate-limit, timeout, transient,
truncation, and unsafe/conflict outcomes without returning exception bodies or
response headers. It stops at the first complete or partial/reference result;
the producer records that result before any exact residual follow-up. Free-key
sources remain `approval_required` until a separate reviewed credential path is
implemented. Price planning requires an explicit region and reference-only
statistical series never close an executable-price gap.

## Licensing Boundary

OpenBB Core and the official MCP server currently use AGPL-3.0-only licensing,
while individual data providers impose separate terms. Process isolation and
non-vendoring reduce coupling but do not by themselves prove that hosted or
commercial use is permissible. Package-license drift is part of compatibility
validation, and a hosted or commercial OpenBB integration remains disabled
until a separate legal review accepts the distribution, operation, source
offer, and downstream-data obligations. See the upstream
[OpenBB license guidance](https://docs.openbb.co/odp/python/faqs/license).

## Design References

This contract deliberately borrows only narrow, reviewable patterns from other
projects. OpenBB's MCP exposes per-session discovery and exact-tool activation,
so TradingCodex keeps that surface bounded instead of loading a full financial
tool catalog. TradingAgents makes data-vendor selection explicit in
configuration rather than hiding it inside analyst prose. Qlib separates local
dataset/cache use from retrieval and ships data-health checks, which supports
TradingCodex's immutable Dataset, compact-ID handoff, and validation posture.

- [OpenBB MCP server interface](https://docs.openbb.co/odp/python/extensions/interface/openbb-mcp)
- [TradingAgents explicit data-vendor configuration](https://github.com/TauricResearch/TradingAgents/blob/main/main.py)
- [Qlib data preparation, cache, and health checks](https://github.com/microsoft/qlib/blob/main/README.md#data-preparation)

These are implementation references, not inherited guarantees. TradingCodex
still applies its own source, license, evidence, safety, and execution gates.
