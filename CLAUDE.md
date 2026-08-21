# skill-telemetry

Privacy-preserving local telemetry for agent skill activation evidence.

## WHY

Agent runtimes expose different evidence for skill activation, loading, and usage.
This project normalizes only content-safe signals into bounded local stores without
turning candidates, file reads, or aggregate metrics into stronger attribution.

**Done means:** the relevant focused checks pass, `mise run check` passes before
publication, and behavior changes include regression coverage. Use `mise run verify`
when a change affects packaging, release artifacts, or public installation.

Normative behavior lives in [`SPEC.md`](SPEC.md). Current design and decisions live
under [`docs/explanation/`](docs/explanation/README.md).

## WHAT

```text
skill-telemetry/
├── src/skill_telemetry/    # Python CLI, contracts, collector, stores, readouts
├── pi/                     # Pi extension package
├── tests/                  # Python behavior, privacy, docs, and artifact tests
├── docs/                   # Tutorials, how-to, explanation, and reference
├── scripts/                # Public-history, artifact, and diagram helpers
├── .mise.toml              # Stable task interface
├── pyproject.toml          # Python package metadata
└── package.json            # Pi package metadata
```

Key sources:

- `SPEC.md` — supported behavior and invariants
- `docs/AGENTS.md` — documentation routing rules
- `docs/explanation/architecture.md` — system mechanisms and failure model
- `docs/explanation/decision-ledger.md` — durable decision history
- `docs/reference/review-rubrics/` — optional project-specific review lenses

## HOW

```bash
mise run setup      # install locked development dependencies
mise run check      # history, format, lint, type, Python/Pi tests, version contract
mise run verify     # check plus wheel/sdist build and installed-command proof
```

### Working rules

1. Create a focused branch; keep canonical `main` clean.
2. Read the nearest guidance and the source that owns each claim before editing.
3. Run focused tests while working, then `mise run check` before pushing.
4. Update `SPEC.md`, architecture, reference docs, or the decision ledger when a
   durable contract or design choice changes.
5. Use fresh-context review for broad, security/privacy-sensitive, cross-language,
   or release-facing changes. Keep lightweight docs and maintenance changes
   proportional.
6. Run `mise run verify` for release, packaging, artifact, or installation changes.

### Public releases

- Publish only refs that pass `mise run public-history`.
- Inspect the Git graph separately when a release requires a parentless history;
  the scanner validates reachable content, not commit count.
- Install Python and Pi from a reviewed full commit SHA or release tag.
- Do not claim PyPI or npm publication.

Repository tasks and CI are the hard checks. Local planning, notes, screenshots, and
review transcripts belong in local workflow storage or the pull request, not in
this repository.
