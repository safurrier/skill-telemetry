# skill-telemetry

Privacy-preserving, local telemetry for skill evidence. It is a Git-installable
Python tool with an optional Pi package in the same repository.

## Install and first use

Python 3.12+ is required. Once the public remote exists, install from a reviewed
Git commit or release tag, not a branch:

```bash
uv tool install 'skill-telemetry @ git+https://github.com/safurrier/skill-telemetry.git@<full-commit-sha>'
# Or, after the release tag exists:
uv tool install 'skill-telemetry @ git+https://github.com/safurrier/skill-telemetry.git@v0.1.0'
skill-telemetry version --format json
skill-telemetry evaluate --format json
```

The Pi package is Git-only. Its `package.json` declares `pi/src/index.ts`; use
the Pi package workflow with the same full commit SHA or release tag. The
extension is tested against Pi 0.84.2. Registry publication is not provided.

## Commands

All commands are non-interactive, never page output, and honor `NO_COLOR`.
Finite commands accept `--format text|json`; JSON is one schema-v1 envelope.

```bash
skill-telemetry --help
skill-telemetry version --format json
skill-telemetry readout --state-dir /absolute/state --format json
skill-telemetry usage --state-dir /absolute/usage-state --format json
skill-telemetry ingest pi --input ./session.jsonl --dry-run --format json
skill-telemetry ingest codex --input ./events.jsonl --skill demo=./SKILL.md --format json
skill-telemetry evaluate --format json
skill-telemetry serve --host 127.0.0.1 --port 14318
skill-telemetry doctor --format json
```

`serve` remains in the foreground and binds only a literal loopback address.
`readout` and `usage` are pure reads: they never discover or import runtime
roots. `ingest` requires explicit repeated `--input` paths and applies file,
directory, depth, record, and byte limits. `--dry-run` executes normalization
without retaining results. Ingest retries are duplicate-safe only for the
retained ledger window; old fingerprints disappear as rotation prunes files.

`claude-hook` is a deliberately fail-open integration:

```bash
skill-telemetry claude-hook < hook-payload.json
```

It reads one bounded stdin document, emits no stdout, and exits zero if
telemetry fails. It is not a general configuration installer. Set only explicit
absolute inventory roots before invoking it; it never discovers ambient roots:

```bash
export SKILL_TELEMETRY_SKILL_ROOTS="/absolute/skills:/another/absolute/skills"
skill-telemetry claude-hook < hook-payload.json
```

## Data, privacy, and state

Default state roots follow XDG: `$XDG_STATE_HOME/skill-telemetry` and
`$XDG_STATE_HOME/skill-telemetry-usage` (or `~/.local/state/...`). Override
with absolute `--state-dir` values or the documented state environment
variables. Files are owner-only JSONL and bounded by rotation. Torn final lines
or damaged state fail visibly; a retry can complete a durable partial prefix
while it remains readable.

The skill domain records only validated identifiers and pseudonymous IDs. The
separate usage domain stores allowlisted Codex token histogram points. Usage is
not skill attribution, session attribution, model identity, pricing, or cost.
No data is exported by this tool. Same-user access to local state remains the
local trust boundary.

## Support and limitations

Pi 0.80.10 appears only as a label on packaged campaign records for the historical
normalized contract; it is not runtime execution evidence. Pi 0.84.2 remains the
exact extension test target. `metrics.unknown_rate` is case-level (unobservable
cases divided by all cases); each `metrics.stages.*.unknown_rate` is event-level
(unknown events for that stage divided by observed events for that stage).

| Surface | Supported claim |
| --- | --- |
| Python CLI/store/receiver | Python 3.12 on Ubuntu release CI |
| Pi extension | Exact development API 0.84.2 release test; packaged campaign records labeled 0.80.10 cover only the historical normalized contract, not runtime execution evidence |
| Claude adapter/hook | Normalized Claude 2.1.211 fixture contract; no forward compatibility claim |
| Codex adapters/usage | Normalized Codex 0.144.5 fixture contract; no forward compatibility claim |
| Foreground receiver | `serve` only |
| Windows, services, profiles, auth, probing | Unsupported or absent |

To uninstall, remove the Python and Pi packages with their package managers.
State is intentionally retained; remove its XDG directories manually only when
you choose to discard local telemetry.

## Development

```bash
mise run setup
mise run check
mise run verify
mise run sync-check
```

See [SPEC.md](SPEC.md) and [architecture](docs/explanation/architecture.md) for
contracts, evidence semantics, and troubleshooting boundaries.
