---
id: example-decisions
title: "Example: Add User Auth — Decisions"
description: >
  Example slice-local decision notes showing how a plan promotes durable changes
  into repo docs.
---

# Decisions — add-user-auth

## What Changed

- Added JWT-based auth middleware, protected-route decorator, and login/register flows.

## Why

- Stateless auth fits both web and mobile clients without adding a session store.
- Durable auth behavior and config expectations needed to be captured outside the plan.

## Where Reflected

- `SPEC.md`
- `docs/explanation/architecture.md`
- `docs/explanation/decisions/0003-jwt-over-sessions.md`

## Promotion

- Promoted to ADR `docs/explanation/decisions/0003-jwt-over-sessions.md`.
