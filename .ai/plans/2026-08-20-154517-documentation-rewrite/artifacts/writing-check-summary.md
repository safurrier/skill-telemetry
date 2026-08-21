# Writing-check summary

## Corpus

Checked separately with schema-v2 source-bound records:

- `README.md` — `readme`
- `SPEC.md` — `technical-doc-reference`
- all authored `docs/**/*.md` except `docs/AGENTS.md`
- explanation pages, ADRs, and the tutorial — `technical-doc-explanatory`
- indexes, how-to pages, reference pages, and rubrics — `technical-doc-reference`

Excluded on purpose:

- `AGENTS.md` and `CLAUDE.md` — agent steering, owned by the context workflow
- `.ai/plans/**` — contribution evidence, not public product prose
- `.agent/**` — vendored workflow implementation
- fixtures, generated output, dependencies, and `.pytest_cache/**`

## Readability passes

The initial long-form pages were below the advisory normal-sample target. Focused
structure and readability rewrites produced these final results:

| Page | Initial FRE / FK | Final FRE / FK | Disposition |
| --- | ---: | ---: | --- |
| `README.md` | 41.7 / 10.5 | 63.5 / 7.3 | fixed through reader-journey rewrite and reference links |
| `SPEC.md` | 35.5 / 11.3 | 67.7 / 5.8 | fixed through shorter normative rules and tables |
| `docs/explanation/architecture.md` | 31.6 / 12.3 | 62.5 / 7.2 | fixed through shorter mechanism-focused sections |
| `docs/reference/state-and-privacy.md` | new page, 48.7 / 9.4 | 65.1 / 6.7 | fixed in a second focused pass |

No normal sample remains below FRE 55 or above FK 10. Small, insufficient, and
composition-limited pages did not enter the readability loop.

## Finding dispositions

- **fix:** sentence length, contractions, semicolon-heavy lists, numbered-heading
  punctuation, passive constructions, placeholder prose, unclear authority, stale
  release wording, missing config names, and absent task routes.
- **keep_exact_term:** `skill-telemetry`, Pi, Codex, Claude, OTLP, JSONL, XDG,
  SHA-256, ADR, and ANSI where they are product names, protocol/data terms, paths,
  or searchable interfaces. First-use pages define the less familiar terms where
  useful.
- **keep_required_text:** exact commands, options, environment variables, paths,
  modes, versions, limits, exit codes, evidence stages, privacy warnings, and
  unsupported surfaces.
- **keep_voice:** direct maintainer warnings such as never installing from a moving
  branch and preserving corrupt state before manual work.
- **defer:** none.

Findings remain advisory and bound to each candidate's exact source digest. The
final independent review owns semantic preservation, not the checker.
