---
name: tcx-dashboard
description: Summarize the current TradingCodex workspace, recent research, portfolio and order posture, forecasts, pending permissions, broker state, and viewer destinations from trusted read-only sources. Use when the user asks what changed, what needs attention, where work stands, or what to inspect next without starting investment analysis or changing state.
---

# TCX Dashboard

Use this skill as the read-only user overview for the current attached workspace. Report
recorded state and attention items; do not turn the overview into investment
judgment, workflow execution, or service recovery.

## Trusted Sources

- Start with the TradingCodex session context injected by the hook. Do not reread
  its backing files through the shell.
- Refresh only the requested or stale sections with Head Manager's read-only MCP
  tools, including `get_tradingcodex_status`, `list_research_artifacts`,
  `list_forecasts`, `get_forecast_calibration_report`, `get_portfolio_snapshot`,
  `get_positions`, `list_order_tickets`, `get_order_status`,
  `list_broker_connections`, `get_broker_connection_status`, and
  `list_external_mcp_permission_requests` when available and relevant.
- Treat missing, unavailable, or redacted data as unknown. Never convert it to a
  zero balance, empty portfolio, healthy status, or completed workflow.

## Procedure

1. Identify the current attached workspace and the user's requested scope. For an
   unqualified dashboard request, check the smallest useful set across recent
   research, portfolio/orders, forecasts, pending permissions, and system/broker
   posture.
2. Surface attention items first. Include only explicit states such as blocked,
   waiting, stale, failed, unhealthy, pending, uncertain, or incompatible, with
   their recorded timestamps or as-of posture when present.
3. Summarize the remaining available sections compactly. Preserve canonical
   status names and distinguish recorded facts from interpretation.
4. Describe something as changed only when a trusted comparison, version, event,
   or timestamp establishes the change. Otherwise label it recent or current.
5. Include the trusted viewer base URL when available and route the user to
   `#/library`, `#/skills`, or `#/system` for detail. Do not claim the viewer was
   opened.
6. If service status is missing, stale, or unhealthy, stop the overview at that
   boundary and route recovery to `$tcx-server`. If the user wants a new
   investment judgment, route that separate task to `$tcx-workflow`.

## Response Shape

Use only sections supported by returned data:

- **Needs attention**: blockers, stale state, pending permissions, uncertain
  orders, or unhealthy connections.
- **Recent work**: accepted research, reports, forecasts, and recorded workflow
  artifacts with source/as-of posture.
- **Portfolio and orders**: current recorded snapshot, positions, and ticket
  status without recommendations.
- **System**: workspace, service, broker, MCP, and update posture.
- **Inspect next**: one or two relevant viewer destinations or a separate exact
  skill entrypoint.

## Hard Stops

- Do not call `begin_analysis_run`, dispatch a role, create an artifact, or
  perform fresh investment analysis.
- Do not draft, approve, submit, cancel, retry, or reconcile an order.
- Do not mutate workspace, skill, policy, permission, broker, connector, or
  service state.
- Do not use shell, raw database access, raw broker APIs, or secrets.
- Do not expose raw reasoning, tool payloads, credential references, or
  unsanitized workspace content.
