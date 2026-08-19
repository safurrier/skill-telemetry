# Holdout Sample Tasks

Use these fixed tasks to manually evaluate whether slice prompts are improving.
They are prompt-quality fixtures, not normal CI blockers.

Run the planner/reviewer prompts against one or more samples and inspect whether
the output is specific, scoped, and evidence-oriented.

## Sample 1: Add A CLI Flag

Task: Add a `--dry-run` flag to an existing command that would otherwise mutate
files. The implementation must print what would change and exit successfully
without writing.

Good planner output:

- identifies mutation boundaries
- adds tests for no-write behavior
- names docs/help text updates
- requires validation with the real command

## Sample 2: Fix A Generated Test Failure

Task: A freshly initialized project fails `mise run check` because one generated
test imports the wrong module name.

Good planner output:

- traces generation from template to output
- updates template and golden/generated-output tests
- avoids patching only the generated fixture

## Sample 3: Update A Stack Template

Task: The Rust stack needs a new lint flag in `cargo clippy`.

Good planner output:

- touches stack task dispatch, docs, and generated repo tests
- verifies Rust single/app generated projects
- records whether the stable task contract changed

## Sample 4: Review An Incomplete Plan

Task: Review a slice with `META.yaml` complete but no real validation commands
and a vague `REVIEW.md`.

Good reviewer output:

- fails the handoff
- cites missing deterministic evidence
- separates fix-required findings from optional cleanup

## Scoring

Score each prompt output from 1 to 5:

- 1: generic checklist, no repo-specific evidence
- 3: mostly useful but misses one major artifact or validation boundary
- 5: scoped, concrete, evidence-oriented, and easy to hand off
