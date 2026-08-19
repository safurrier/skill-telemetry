# skill-telemetry

Privacy-preserving local telemetry for agent skill activation evidence

## WHY

Agent runtimes expose different evidence for skill activation, loading, and usage.
This project normalizes only content-safe signals into bounded local stores without
turning candidates, file reads, or aggregate metrics into stronger attribution.

**Done means**: `mise run check` passes, `mise run sync-check` validates the
active or changed contribution plan, and intended behavior is covered by the
appropriate test layer.

Correctness invariants live in [`SPEC.md`](SPEC.md). Durable system design and
decision history live under [`docs/explanation/`](docs/explanation/README.md).

## WHAT

```
skill-telemetry/
├── src/skill_telemetry/    # Python source
├── pi/                     # Pi extension package
├── tests/                  # Python test suite
├── .mise.toml              # Task runner config
├── pyproject.toml          # Python project config
└── README.md
```

Key steering files:
- `AGENTS.md` — this file (steering index)
- `SPEC.md` — correctness envelope (requirements, contracts, invariants)
- `docs/AGENTS.md` — docs routing index
- `docs/explanation/architecture.md` — system description, principles, decisions
- `docs/explanation/decision-ledger.md` — append-only durable decision history
- `docs/reference/review-rubrics/` — reusable review standards
- `.agent/skills/slice-workflow/` — vendored sync-check implementation

## HOW

```bash
mise run setup      # install tools and dependencies (one-time)
mise run check      # fast quality gate: fmt + lint + typecheck + test  ← before committing
mise run sync-check # plan/spec/evidence/review handoff gate            ← before handing off or pushing
mise run verify     # CI gate plus Python artifact proof  ← before merging
```

CI calls `mise run ci` (= `check`, including reachable-history scanning) and
changed-plan `sync-check`. An initial public `main` with no plan passes the
changed-plan check; future pull requests with meaningful changes must include a
completed changed plan. `sync-check` is a handoff completion gate, not a
replacement for code/test validation.

## Stack: python

- Formatter: ruff format (line-length 88)
- Linter: ruff check (E, W, F, I, B, C4, UP, N, S, PTH, RUF)
- Type checker: ty (error-on-warning)
- Tests: pytest with coverage

## Starting Work

```bash
git checkout -b feat/demo-work
mise run plan -- demo-work    # creates .ai/plans/YYYY-MM-DD-HHmmSS-demo-work/
mise -q run slice-status -- --json # inspect active slice state as JSON
```

`mise run plan` refuses to run on the default branch. Slugs must be lowercase
kebab-case and unique within `.ai/plans/`.

The task scaffolds META.yaml, TODO.md, LEARNING_LOG.md, VALIDATION.md,
REVIEW.md, DECISIONS.md, and `artifacts/manifest.yaml`. Add SPEC.md or
IMPLEMENTATION.md if the work is complex.

See `.ai/plans/AGENTS.md` for the full plan structure and `_example/` for a reference.

## Before Handoff Or Push

1. `mise run check` — must pass
2. Update the active plan: TODO, LEARNING_LOG, DECISIONS, VALIDATION, REVIEW, artifacts
3. `mise run sync-check` — repo-enforced handoff gate
4. `mise run verify` — when the slice needs artifact proof before merge

## Public releases

- Publish only refs that pass `mise run public-history`; scan selected refs in a
  temporary single-branch clone so local archive refs are never candidates.
- Keep completed implementation plans, raw review evidence, and release notes
  in local workflow storage rather than the release tree.
- Install from a reviewed full Git commit SHA or release tag. Python and Pi are
  Git-only; do not claim a package-registry release.

The skills above are helpers. The hard contract is the `mise` task surface.

## Skills

The repository retains only the vendored `slice-workflow` implementation used
by the `mise` sync-check tasks. Canonical truth stays in `docs/` and the active
plan; personal authoring workflows are intentionally not part of this project.

## Further Reading

| Document | Purpose |
|---|---|
| `SPEC.md` | Correctness envelope — requirements, contracts, invariants |
| `.ai/plans/` | Plan directories for units of work (see `.ai/plans/AGENTS.md`) |
| `docs/explanation/architecture.md` | System description, principles, decisions |
| `docs/explanation/decision-ledger.md` | Append-only durable decision trail |
| `docs/reference/review-rubrics/` | Review standards for external review |
| `README.md` | Human-oriented quick start |
