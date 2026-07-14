# Gateway

TradingCodex MCP is an authenticated analysis, approval, and read/status
gateway, not a raw broker proxy or an execution-mutation surface.

Final submit and cancel requests enter through exact native action prompts and
the service-owned execution gateway. Provider logic must call policy evaluation
before adapter submission.

Paper and reviewed validation execution paths are local harness flows. They
exist for simulation, adapter validation, and audit/policy testing, not as a
claim of live-trading readiness.
