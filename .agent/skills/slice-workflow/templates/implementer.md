# Slice Implementer Prompt

Phase: {{phase}}
Plan: `{{plan_path}}`
Branch: `{{plan_branch}}`

Use the `slice-workflow` skill. You are implementing the active slice in this
repo. Keep the plan, validation, and evidence current while you work.

## Current Plan Context

{{plan_summary}}

## Your Job

1. Follow the plan TODOs in order unless the implementation shows the plan is
   wrong.
2. Update `LEARNING_LOG.md` when assumptions, scope, or approach changes.
3. Update `DECISIONS.md` if the design changes or a durable decision is made.
4. Record every meaningful validation command and outcome in `VALIDATION.md`.
5. Keep durable evidence small and intentional. Do not commit raw scratch output
   unless it is summarized and declared in `artifacts/manifest.yaml`.
6. Run the repo's fast quality gate before handoff.

## Stop Condition

When implementation is ready for review, render the review prompt:

```bash
mise run slice-review
```
