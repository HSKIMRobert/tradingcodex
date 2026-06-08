---
name: approve-order
description: "Approve or reject a draft order intent without executing it. Use by risk-manager after order validation, risk review, policy review, restricted-list checks, and creator-versus-approver separation."
---

# Approve Order

Role ownership: use by `risk-manager`. `head-manager` must not approve orders directly; it should assign `risk-manager`.

Use this skill when `risk-manager` needs to approve or reject a draft order intent after risk and policy review.

Required inputs:

- Draft `trading/orders/draft/*.order_intent.json`
- Risk review artifact or risk-check output
- Policy review result or `./tradingcodex policy simulate` output
- Universe/instrument support and adapter eligibility from policy review

Approval path:

1. Validate the order intent with `./tradingcodex validate order <path>`.
2. Confirm `approved_by` is not the same principal as `created_by`.
3. Confirm restricted list, enabled adapter, instrument support, notional limit, and approval readiness are all acceptable.
4. Create the approval receipt with `./tradingcodex approve <path> --approved-by risk-manager`.
5. Confirm the approved order and receipt paths were written.

Reject path:

- If validation, risk, or policy fails, write or reference the rejection reason.
- Do not create an approval receipt for a revise/reject decision.

Rules:

- Do not submit orders.
- Do not change policy in the same workflow.
- Do not approve an order created by `risk-manager`.
- Do not approve a live broker order unless a user-installed adapter and policy explicitly enable it.
- Do not approve unsupported universes or instruments merely because research or screen-grade analysis exists.
