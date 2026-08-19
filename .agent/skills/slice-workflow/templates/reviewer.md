# Slice Reviewer Prompt

Phase: {{phase}}
Plan: `{{plan_path}}`
Branch: `{{plan_branch}}`

Use the `slice-workflow` skill. You are reviewing this slice before handoff.
Treat the review as verification, not self-assurance.

## Current Plan Context

{{plan_summary}}

## Your Job

1. Read `META.yaml`, `TODO.md`, `VALIDATION.md`, `DECISIONS.md`, and the changed
   files.
2. Load the rubrics named in `META.yaml` from `docs/reference/review-rubrics/`
   when present.
3. Check whether the implementation, docs, generated templates, tests, and
   validation evidence agree.
4. Write findings into `REVIEW.md` with:
   - mode
   - backend
   - reviewer
   - rubrics
   - findings
   - disposition
5. Update `META.yaml` `review_backend` to match the review artifact.

## Review Standard

Fail the handoff if required evidence is missing, generated docs drift from the
source contract, or the plan is marked complete before the actual PR/review state
supports it.
