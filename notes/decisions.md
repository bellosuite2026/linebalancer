# Decisions

## 2026-11-01: Keep workshop measurements as plan elements

Workshop plans may persist measurement elements with `kind: "dim"`. The API
schema allowlist must accept this kind so a saved plan is not rejected on create
or update. The workshop CRUD test verifies that the response retains the
measurement element.