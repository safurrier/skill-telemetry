# skill-telemetry

`skill-telemetry` records local, content-safe evidence about agent skill use. It
helps people test Pi, Claude Code, and Codex integrations without treating every
mention or file read as an activation.

The repo contains a Python command-line tool and an optional Pi extension. Both
install from Git. The tool never exports data, installs a service, edits an agent's
config, or sends records to a hosted backend.

## Try it

You need macOS or Linux, Python 3.12 or newer, and
[`uv`](https://docs.astral.sh/uv/).

```bash
uv tool install \
  'skill-telemetry @ git+https://github.com/safurrier/skill-telemetry.git@v0.1.0'

skill-telemetry version --format json
skill-telemetry evaluate --format json
```

In the schema-v1 responses, check that `status` is `ok`, `data.version` is
`0.1.0`, and `data.passed` is `true`. `evaluate` checks safe records that ship
with the package. It proves that the installed Python adapters
and scorer work. It doesn't prove that you set up your agent or that the agent sends events.

For an immutable install, use the reviewed release commit instead of the tag:

```bash
uv tool install \
  'skill-telemetry @ git+https://github.com/safurrier/skill-telemetry.git@aeaf22850e361ee0959fa0747be87d5e4afc660d'
```

Never install from a moving branch.

## Architecture at a glance

<picture>
  <source media="(prefers-reduced-motion: reduce)" srcset="docs/assets/architecture/skill-telemetry-architecture.svg">
  <img src="docs/assets/architecture/skill-telemetry-architecture-animation.gif" alt="Animated two-lane architecture map. Packaged campaigns use only the Python evaluator. Pi lifecycle events pass through Pi extension matching into retained skill-telemetry-v1 custom entries and later explicit ingest. Selected Pi and Codex files also use explicit ingest; Claude hook input uses a privacy adapter. OTLP logs enter only the skill path. OTLP metrics split into independent skill-metric and token-usage adapters. Stage-preserving skill evidence and token usage stay in separate ledgers and readouts.">
</picture>

[Download the self-contained player](docs/assets/architecture/skill-telemetry-architecture-animated.html) ·
[Watch MP4](docs/assets/architecture/skill-telemetry-architecture-animation.mp4) ·
[View static SVG](docs/assets/architecture/skill-telemetry-architecture.svg) ·
[Edit the Excalidraw source](docs/assets/architecture/skill-telemetry-architecture.excalidraw)

The animation reveals inputs, normalization, storage, and readouts in order. Yellow
marks inputs, blue marks normalization, green marks retained state, and orange marks
read surfaces. The packaged evaluator stays in its own lane because it checks a
sanitized contract rather than a live runtime. See the
[architecture explanation](docs/explanation/architecture.md) for the failure and
privacy boundaries behind the map.

## Choose how to collect evidence

| Path | Input | Retained state write | Main limit |
| --- | --- | ---: | --- |
| Pi extension | Pi lifecycle events | Pi session entries | Tested with Pi 0.84.2 |
| Explicit ingest | Selected Pi or Codex JSON/JSONL paths | Only without `--dry-run`. Dry-run uses temporary state | Dedupe covers the retained window |
| Claude hook | One bounded hook payload | May append one event | Fails open and never configures Claude |
| Foreground receiver | OpenTelemetry (OTLP) HTTP logs and metrics | Skill and usage ledgers | No daemon or service manager |

Install the Git-only Pi package from the same ref:

```bash
pi install git:github.com/safurrier/skill-telemetry@v0.1.0
```

The package isn't published to npm.

## Understand the result

The tool keeps each evidence stage separate. An activation, explicit command,
prompt expansion, canonical read, candidate, aggregate metric, and generic runtime
event don't mean the same thing. Weaker evidence never becomes a stronger claim.

Token histograms live in a separate store. They don't identify a skill, session,
model, price, or cost.

## Read local state

`readout` and `usage` are pure reads. They don't scan agent folders or import new
data.

```bash
skill-telemetry readout --format json
skill-telemetry usage --format json
```

An empty store is valid and reports an `ok` status with zero counts. The
[state and privacy reference](docs/reference/state-and-privacy.md) lists default
paths, environment variables, permissions, and retention limits.

## Import selected files

Start with a dry run. You can repeat `--input`, and the command reads only the
paths you name.

```bash
skill-telemetry ingest pi \
  --input ./session.jsonl \
  --dry-run \
  --format json

skill-telemetry ingest codex \
  --input ./events.jsonl \
  --skill demo=./SKILL.md \
  --dry-run \
  --format json
```

Remove `--dry-run` only when you want to save valid records. Ingest limits folder
walks, files, bytes, records, JSON depth, and open file handles. Exit code 5 marks
a partial result and reports why it was partial.

A retry skips fingerprints that remain in the retained files. Rotation can remove
old fingerprints, so replay protection isn't permanent.

## Run the receiver

Start it in one terminal:

```bash
skill-telemetry serve --host 127.0.0.1 --port 14318
```

Check it from another terminal:

```bash
skill-telemetry doctor --endpoint http://127.0.0.1:14318 --format json
```

A healthy result has `status` set to `ok` and `data.loopback_only` set to `true`. The
receiver accepts OTLP HTTP at `/v1/logs` and `/v1/metrics` and serves `/healthz`.
It stays in the foreground, binds only to a literal loopback address, and has no
export path.

## Use the Claude hook

Pass absolute skill roots and one hook payload:

```bash
export SKILL_TELEMETRY_SKILL_ROOTS="/absolute/skills:/another/absolute/skills"
skill-telemetry claude-hook < hook-payload.json
```

The hook reads a bounded document, writes no stdout, and returns zero if telemetry
fails. That fail-open rule keeps telemetry from blocking the agent. The hook does
not search other roots or install Claude config.

## Know the privacy boundary

Skill records use a closed schema. They can store safe identifiers and namespaced
SHA-256 pseudonyms for local correlation. They don't store raw prompts, command
arguments, request bodies, tool content, source paths, credentials, or raw session
and turn IDs.

State is owner-only and size-bounded. A process that runs as the same user is still
inside the local trust boundary. Writes are at-least-once rather than transactional.
A failed batch can leave a valid prefix, and damaged retained lines fail visibly.

See [runtime support](docs/reference/runtime-support.md) for tested versions and
unsupported surfaces. The short version: this release targets macOS and Linux,
runs the Python release gate on Ubuntu, and doesn't support Windows, services,
profiles, auth, remote export, or live probing.

## Remove it

```bash
uv tool uninstall skill-telemetry
```

Remove the Pi package with Pi's package command. Uninstall keeps local state on
purpose. Delete the skill and usage state folders only when you mean to discard the
evidence.

## Develop and validate

```bash
mise run setup       # install locked development dependencies
mise run check       # routine repository checks
mise run verify      # CI plus wheel and source-archive proof
```

The [docs index](docs/README.md) links operator guides, reference pages, design
explanations, and contributor checks. [`SPEC.md`](SPEC.md) is the normative product
contract.
