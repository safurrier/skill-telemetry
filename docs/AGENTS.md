# Docs Routing

This directory holds durable project knowledge. Prefer it over historical plan
logs when you need the current repo truth.

## Reading Order

| Path | Type | Use when |
|---|---|---|
| `docs/README.md` | human index | you want the main reading order |
| `docs/explanation/architecture.md` | explanation | you need system boundaries, invariants, and workflows |
| `docs/explanation/decision-ledger.md` | explanation | you need the durable timeline of non-trivial changes |
| `docs/explanation/decisions/` | explanation | a change needs a full ADR instead of a short ledger entry |
| `docs/reference/review-rubrics/` | reference | you are reviewing a slice and need explicit standards |
| `docs/how-to/` | how-to | you need task-oriented recipes |
| `docs/tutorials/` | tutorial | you need a guided learning flow |

## Rules

- Durable truths live here, not in `.ai/plans/`.
- Review rubrics are part of repo knowledge. Update them when standards improve.
- Append to the decision ledger; do not rewrite history unless a human is
  correcting a mistake.
