# Slice Handoff Rubric

A handoff is trustworthy when it is concrete enough for a new agent or human to
continue without reconstructing the session.

## Required Signals

- `META.yaml` status and branch are truthful.
- `TODO.md` shows what is complete and what remains.
- `VALIDATION.md` records real commands or captured outputs.
- `REVIEW.md` records reviewer/backend, rubrics, findings, and disposition.
- `DECISIONS.md` says whether decisions stayed local or were promoted.
- `artifacts/manifest.yaml` points only to intentional evidence.

## Good Handoff

- Names the files changed and why.
- Separates verified facts from assumptions.
- Lists unresolved risks without softening them.
- Gives the next operator one obvious next command.

## Weak Handoff

- Says "tests pass" without commands.
- Keeps review in temp output only.
- Leaves `META.yaml` placeholders.
- Commits large scratch artifacts because they happened to be generated.
- Marks a slice complete while the PR or review state is still unresolved.
