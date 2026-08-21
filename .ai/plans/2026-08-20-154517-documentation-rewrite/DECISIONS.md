---
id: plan-decisions
title: Decision Notes
description: Slice-local decisions and their durable destination.
---

# Decisions—documentation-rewrite

## What Changed

- The root README now owns orientation, first success, collection choices, and routing.
- `SPEC.md` remains the normative behavior contract.
- Architecture explains mechanisms and failure semantics without widening support.
- Tutorials and how-to pages own guided and task-oriented workflows.
- Reference pages own commands, state/privacy, support, and review lenses.
- Documentation tests now discover every authored page and validate local links.

## Why

- The initial public docs were accurate but template-shaped. They sent readers into
  contributor workflow before product tasks, repeated dense claims, and left three
  intent folders as placeholders.

## Where Reflected

- `README.md`
- `SPEC.md`
- `docs/`
- `tests/test_docs.py`
- `docs/explanation/decision-ledger.md`

## Promotion

Promoted to the decision ledger in the same change.
