---
name: slice-workflow
description: >
  Skill-first workflow for planning, implementing, reviewing, and handing off a
  meaningful repo slice. Use when starting a slice, rendering planner/implementer/
  reviewer prompts with mise, deciding what evidence to keep, or evaluating prompt
  quality with holdout sample tasks.
allowed-tools: Read, Edit, Glob, Grep, Bash
---

# Slice Workflow

Use this skill to keep a slice legible from first plan through handoff.

The public interface is `mise`. This skill explains the workflow and judgment
standard behind those tasks.

The deterministic implementation lives in `cli/`, a tiny uv-backed Python
project that uses only the standard library at runtime. Repository-level `mise`
tasks call its module directly, so plan and handoff validation move with the repo.

## Command Flow

```bash
mise run plan -- <slug>
mise run plan-check
mise run spec-check
mise run evidence-check
mise run review-check
mise run sync-check
```

These tasks validate plan and handoff artifacts. They do not launch another
agent or mutate product source.

Use `mise -q run slice-status -- --json` when another agent or script needs the
active slice state.

## Responsibilities

### Planning

- Make `META.yaml` truthful before significant code changes.
- Turn vague work into concrete TODOs.
- Declare the evidence and review required for handoff.
- Record likely durable decisions in `DECISIONS.md`.

### Implementation

- Follow the active TODO order unless the work teaches you it is wrong.
- Update `LEARNING_LOG.md` when scope, assumptions, or approach change.
- Record validation commands and outcomes as they happen.
- Keep scratch evidence out of durable context unless it is summarized or
  intentionally declared.

### Review

- Treat review as adversarial verification, not a confidence ritual.
- Use the rubrics named in `META.yaml`.
- Write findings and final disposition into `REVIEW.md`.
- Update `META.yaml` `review_backend` to match the review artifact.

## References

- `references/artifact-policy.md` - what to keep, summarize, or ignore
- `references/handoff-rubric.md` - what makes a slice handoff trustworthy
- `references/holdout-sample-tasks.md` - sample tasks for prompt-quality checks

## Rules

- Skills own workflow policy and judgment.
- `mise` tasks own deterministic file creation, prompt rendering, status output,
  and validation exit codes.
- V1 is provider-neutral prompt rendering only.
- CI should block only deterministic contract failures. Fuzzy prompt quality
  belongs in holdout sample review until it becomes mechanically checkable.
