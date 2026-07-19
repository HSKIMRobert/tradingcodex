# Guidebook Rules

`guidebook/` is the static GitHub Pages user guide. Keep it task-first and
plain-language; durable product behavior belongs in `../docs/`.

## Navigation

- Every `*.html` page must use the same left sidebar and mobile menu, in the
  same order. Do not replace it with a category-only, abbreviated, or
  page-specific menu.
- The canonical order is: Quick start, Advanced usage, Dynamic workflow, The
  harness, Data sources & OpenBB, Decision Memory, Reusable context, Execution
  boundary, Provider to order, All user-facing skills, Research, Order,
  Improve, Customize, and Help & status.
- A page may show its current location through its title, breadcrumb, or an
  active state, but that must not add, remove, reorder, or rename sidebar
  links.
- When adding a guide page or changing a route, update the shared sidebar on
  every guide page and extend `tests/test_guidebook_contract.py` so drift is
  caught automatically.

## Validation

Run `uv run pytest -q tests/test_guidebook_contract.py` after changing
guidebook pages or navigation.
