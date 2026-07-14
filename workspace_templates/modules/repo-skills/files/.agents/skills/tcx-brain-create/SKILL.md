---
name: tcx-brain-create
description: "Create or revise a user-owned local Investment Brain plugin from user-selected Decision Memory evidence, counterexamples, validated lessons, or an explicitly stated investment philosophy. Use when the user asks to curate general inquiry and interpretation heuristics into an `investment-brain-*` bundle, while keeping authoring separate from installation, activation, and publication."
---

# Brain Creator

Create a user-owned local Investment Brain source bundle. A Brain shapes Head
Manager's inquiry and interpretation; it is not a Strategy, role roster,
workflow, memory store, policy package, or execution extension.

Read [bundle-contract.md](references/bundle-contract.md) before writing or
validating a bundle.

## Authoring Gate

1. Require an explicit user request to create or revise a Brain. Metadata may
   allow implicit skill discovery, but discovery is not write authorization.
2. Require the original root prompt to begin with the exact physical first line
   `$tcx-build`. The marker does not elevate Codex's actual filesystem
   permission; if writing is unavailable, report the platform blocker and stop.
   Workbench, subagents, and later turns cannot inherit the Build grant.
3. For a new Brain, use `investment-brains/<investment-brain-id>` unless the
   user selects another workspace-local source directory. Use a new lowercase
   hyphen-case `investment-brain-*` id and version `1.0.0` unless the user chose
   another valid initial version.
4. Revise only a user-owned source directory that the user identifies. Never
   edit `.tradingcodex/investment-brains/packages`, the registry, projected
   `.agents/skills/investment-brain-*`, a third-party managed package, or an
   upstream repository. Adaptation of third-party ideas requires a new
   user-owned id, compatible license, and original wording.

## Curation Procedure

1. Ask the user to select the exact Decision Memory episodes, forecasts,
   postmortems, validated lessons, and contrary cases that may inform the draft.
   Do not sweep all memory or infer consent from relevance.
2. Require counterexamples and scope limits. Separate repeatable process lessons
   from one profitable outcome, one regime, hindsight, or current narrative.
3. Perform a privacy review before drafting. Identify private Investor Context,
   account or holding details, personal constraints, confidential sources,
   issuer-specific cases, and verbatim private prose that must stay out.
4. Abstract the selected evidence into general hypotheses, inquiry priorities,
   interpretation principles, causal frames, scenarios, falsifiers,
   applicability limits, and abstention heuristics. Do not copy private cases,
   names, tickers, account facts, or memory text into the bundle.
5. Show the proposed abstraction, counterexamples, limitations, excluded private
   material, id, version, publisher, license, and destination. Obtain user
   confirmation before the first write or before revising existing content.
6. Write only the strict source bundle described in the reference. Keep the
   Brain body platform-neutral and high freedom. It must not name roles, tools,
   models, sandboxes, workflow order, artifact paths, memory operations, policy,
   approval, broker, order, or execution authority.
7. Review every generated file against the bundle checklist, then run the
   non-mutating `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains validate
   --local <source-directory>`. Fix every validation error without installing
   the bundle. For a revision already represented by an installed immutable
   version, require a version higher than every installed version; never
   republish changed bytes under the same version.
8. Return the local source path, file list, privacy exclusions, abstraction
   summary, counterexamples considered, version posture, and remaining review
   questions.

## Stop Boundary

Authoring ends with the reviewed local source bundle. Do not install, update,
activate, deactivate, remove, or project it. Do not stage, commit, configure a
remote, push, publish, or open a pull request. Each is a separate explicit user
action after authoring and privacy review.

Do not mutate Decision Memory, delete source cases, rewrite an installed
version, or present the draft as validated investment truth. Evidence remains
able to falsify the Brain, and the user remains the owner and final curator.
