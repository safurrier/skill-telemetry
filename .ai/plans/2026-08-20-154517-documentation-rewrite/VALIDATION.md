---
id: plan-validation
title: Validation Log
description: Commands and evidence for the documentation rewrite.
---

# Validation

## Commands

- `uv run skill-telemetry --help` and each public subcommand `--help` — passed;
  command names, options, defaults, and side effects inspected.
- `uv run skill-telemetry version --format json` — passed; version `0.1.0`.
- `uv run skill-telemetry evaluate --format json` — passed; packaged evaluation
  reported `data.passed == true`.
- `uv run skill-telemetry readout --state-dir <empty-temp> --format json` — passed;
  empty store reported zero events.
- Source-bound `writing_check.py` on README, SPEC, and every authored `docs/**/*.md`
  except `docs/AGENTS.md` — completed before and after edits.
- `uv run pytest tests/test_docs.py --no-cov -q` — 50 documentation cases passed.
- `mise run check` — passed: 484 Python tests at 85.30% coverage, 38 Pi tests,
  public-history, format, lint, type, package-load, and version contract.
- `mise run verify` — passed, including isolated wheel and source-archive builds and
  installed-command smoke checks.
- `git diff --check` — passed.

## Writing evidence

Normal-sample final readability:

| Page | FRE | FK |
| --- | ---: | ---: |
| `README.md` | 63.5 | 7.3 |
| `SPEC.md` | 67.7 | 5.8 |
| `docs/explanation/architecture.md` | 62.5 | 7.2 |
| `docs/reference/state-and-privacy.md` | 65.1 | 6.7 |

All normal samples meet the advisory FRE 55 minimum and FK 10 maximum. Remaining
checker observations are exact product names, runtime/protocol/data acronyms,
proper names, or searchable contract terms and are dispositioned in the writing
summary artifact.

## Evidence

- `artifacts/writing-check-summary.md`
- Independent semantic-preservation review: no remaining blockers or substantive
  findings after two correction rounds.
- Independent README/IA review: final README grade A, 26/27; no blockers.
