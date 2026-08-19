---
id: example-review
title: "Example: Add User Auth — Review"
description: >
  Example external review record showing rubric coverage, findings, and
  disposition before handoff.
---

# Review — add-user-auth

## Review Context

- Mode: external
- Backend: subagent
- Reviewer: review-agent-2

## Rubrics

- core-quality
- docs-info-architecture

## Findings

- Password hashing rounds should be configurable instead of hardcoded.
- The test database cleanup fixture needs to run after each module.

## Disposition

- Addressed both findings before merge.
- Updated SPEC.md and docs/reference/auth.md to reflect the configuration knob.
