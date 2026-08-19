# Plans

Each subdirectory is a unit of work with a standard structure. Create one with
`git checkout -b feat/<slug>` then `mise run plan -- <slug>`, or create it manually.
The goal is not just "there is a TODO list." Each plan should leave behind a
clear audit trail: what changed, why, how it was validated, and how it was
reviewed.

## Required Files

| File | Purpose | When to update |
|------|---------|----------------|
| `META.yaml` | Machine-readable metadata — branch, status, contract, review, evidence | At start; update status and review backend as work progresses |
| `TODO.md` | Checkable task list | At start; check off as you go |
| `LEARNING_LOG.md` | Dev diary — problems, adaptations, feedback, surprises | Append timestamped entries during work |
| `VALIDATION.md` | How changes were verified, including the commands run | After testing; append entries as you verify |
| `REVIEW.md` | External-enough review record with rubrics, findings, disposition | Before handoff or push |
| `DECISIONS.md` | Slice-local decision staging area before promotion to durable docs | During implementation; finalize before handoff |
| `artifacts/manifest.yaml` | Machine-readable list of artifacts produced for this slice | Whenever new evidence artifacts are produced |

## Optional Files

| File | Purpose | When to create |
|------|---------|----------------|
| `SPEC.md` | Requirements, constraints, scope for this task | Complex or scoped work with multiple requirements |
| `IMPLEMENTATION.md` | Step-by-step approach, design decisions | Non-obvious approach with multiple options |

## META.yaml Fields

```yaml
slug: feature-name           # matches directory suffix
branch: feat/feature-name    # git branch for this work
created: YYYY-MM-DD          # auto-filled by mise run plan
pr:                          # filled when PR opens (number or URL)
status: planned              # planned | in-progress | complete | abandoned
source: feature-request      # freeform — code-review, bug, spike, follow-on, etc.
contract_change: implementation_only | docs_only | contract_changed
decision_record: none | ledger | adr
review_mode: external_required
review_backend:              # set once review happens: subagent | skill:... | manual_external
review_rubrics:
  - core-quality
evidence_required:
  - commands
  - report
continues_from:              # optional plan lineage
supersedes:                  # optional plan lineage
```

## Lifecycle

```
git checkout -b feat/<slug>  → create a feature branch first
mise run plan -- <slug>      → creates directory with templates
status: planned              → fill TODO, META, and any scoped spec/implementation notes
status: in-progress          → append to LEARNING_LOG.md as you go
                             → update DECISIONS.md, VALIDATION.md, REVIEW.md, and artifacts
mise run sync-check          → validate plan/spec/evidence/review before handoff
status: complete             → before handoff or PR merge, after final proof
```

`mise run plan` rejects invalid slugs and existing slugs so plan paths stay stable.
`mise run sync-check` aggregates:

- `mise run plan-check`
- `mise run spec-check`
- `mise run evidence-check`
- `mise run review-check`

Local default mode validates the active planned/in-progress slice. PR CI must
use `mise run sync-check -- --changed-plans origin/main...HEAD` so changed plans
are marked `status: complete` and validated before handoff or merge. Each contract task
also accepts `--plan-dir .ai/plans/<plan-dir>` for explicit completed-plan
checks.

## Artifacts

Prefer small committed evidence artifacts when they help handoff:

- validation summaries
- review summaries
- concise command transcripts
- screenshots only when they carry review evidence

Keep raw scratch transcripts, huge diffs, and temporary captures out of git.
Every manifest entry must point at a real file under that plan directory.

## Example

See `_example/` for a complete reference plan showing the progression from
planned through completion with realistic entries.

<!-- generated-by: context-engineering@2.2.0 | last-updated: 2026-04-30 -->
