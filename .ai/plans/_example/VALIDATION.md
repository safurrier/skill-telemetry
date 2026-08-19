---
id: example-validation
title: "Example: Add User Auth — Validation"
description: >
  Example validation log showing how changes were verified.
---

# Validation

## Commands

- `mise run check` — 45 passed (12 new)
- `mise run sync-check` — plan/spec/evidence/review contract passed
- `mise run verify` — 52 passed (7 new integration tests)

## Evidence

Artifacts listed in `artifacts/manifest.yaml`:
- `artifacts/release-review.md`
- `artifacts/integration.log`

## Notes

New tests:
- `test_jwt_middleware.py` — token validation, expiry, malformed tokens
- `test_auth_decorator.py` — protected/unprotected route behavior
- `test_user_model.py` — create, authenticate, password hashing
