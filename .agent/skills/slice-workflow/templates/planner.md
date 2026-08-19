# Slice Planner Prompt

Phase: {{phase}}
Plan: `{{plan_path}}`
Branch: `{{plan_branch}}`
Task source: `{{task_path}}`

Use the `slice-workflow` skill. You are planning this slice before significant
implementation work.

## Task

{{task_text}}

## Current Plan Context

{{plan_summary}}

## Your Job

1. Read the active plan files under `{{plan_path}}`.
2. Make `META.yaml` truthful:
   - status
   - source
   - contract_change
   - decision_record
   - review_rubrics
   - evidence_required
3. Replace vague TODOs with concrete slice steps.
4. Update `SPEC.md` and `IMPLEMENTATION.md` if this is more than a trivial edit.
5. Seed `DECISIONS.md` with what changed, why, and where it should be reflected.
6. Do not implement code yet unless the user explicitly asks.

## Handoff

After planning, tell the user:

- the plan path
- what decisions remain open
- the next command, usually `mise run slice-implement`
