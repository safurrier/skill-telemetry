---
id: example-learning-log
title: "Example: Add User Auth — Learning Log"
description: >
  Example dev diary showing timestamped entries during work.
---

# Learning Log

## 2026-01-15 10:00 — Scoping

JWT chosen over session cookies because the API is stateless and consumed by
both web and mobile clients. Session cookies would require sticky sessions
or a session store.

## 2026-01-15 14:30 — Middleware pattern decision

Initially tried a class-based middleware. Switched to a decorator pattern
(`@require_auth`) because it's more explicit about which routes are protected
and easier to test in isolation.

## 2026-01-16 09:00 — User feedback: password hashing

User pointed out bcrypt rounds should be configurable via env var, not
hardcoded. Updated to read `AUTH_BCRYPT_ROUNDS` with a default of 12.

## 2026-01-16 16:00 — Test database cleanup issue

Integration tests were leaking test users across runs. Added a
`truncate_users` fixture that runs after each test module. Lesson: always
scope database fixtures to avoid test pollution.

## 2026-01-17 — Completion retrospective

**What matched plan:** Middleware and user model went as expected. JWT
validation was straightforward with PyJWT.

**What diverged:** Didn't anticipate the configurable bcrypt rounds or the
test database cleanup. Both were quick fixes but weren't in the original TODO.

**One-shot next time:** Include "make config values env-configurable" and
"add database cleanup fixtures" as standard TODO items for any feature
touching auth or persistence.
