---
id: skill-telemetry-architecture
title: Architecture
description: Components, data flow, evidence semantics, storage, and failure boundaries.
index:
  - id: inputs
    keywords: [pi, claude, codex, otlp, ingest]
  - id: evidence
    keywords: [activation, candidate, read, metric, attribution]
  - id: persistence
    keywords: [jsonl, rotation, dedupe, retry, corruption]
  - id: boundaries
    keywords: [loopback, privacy, export, process]
---

# Architecture

The project has a Python core and a separate Pi extension. Python owns the public
commands, record rules, adapters, local files, OTLP receiver, reports, and packaged
evaluation. TypeScript owns Pi event matching and writes safe custom entries into
Pi sessions. Python can import those entries later from a path the caller names.

## Animated system map

<picture>
  <source media="(prefers-reduced-motion: reduce)" srcset="../assets/architecture/skill-telemetry-architecture.svg">
  <img src="../assets/architecture/skill-telemetry-architecture-animation.gif" alt="Animated two-lane architecture map. Packaged campaigns use only the Python evaluator. Pi lifecycle events pass through Pi extension matching into retained skill-telemetry-v1 custom entries and later explicit ingest. Selected Pi and Codex files also use explicit ingest; Claude hook input uses a privacy adapter. OTLP logs enter only the skill path. OTLP metrics split into independent skill-metric and token-usage adapters. Stage-preserving skill evidence and token usage stay in separate ledgers and readouts.">
</picture>

[Download the self-contained player](../assets/architecture/skill-telemetry-architecture-animated.html) ·
[Watch MP4](../assets/architecture/skill-telemetry-architecture-animation.mp4) ·
[View static SVG](../assets/architecture/skill-telemetry-architecture.svg) ·
[Edit the Excalidraw source](../assets/architecture/skill-telemetry-architecture.excalidraw)

The two swimlanes show a deliberate boundary. Live and explicitly imported evidence
can reach the local stores. Packaged campaign data reaches only the Python evaluator.
The color sequence follows input, normalization, retained state, and read surfaces.

## Text data flow

```text
Pi lifecycle -> Pi extension matching -> custom skill-telemetry-v1 entries
                                                    │ caller-selected Pi file
Pi files ──────────┐                                 v
Codex files ────────> bounded explicit ingest -> stage-preserving gate
Claude hook stdin ──> privacy adapter ─────────> stage-preserving gate
/v1/logs ───────────> skill logs adapter ──────> stage-preserving gate
/v1/metrics ─────────> skill metric adapter ───> stage-preserving gate
stage-preserving gate -> skill ledger -> readout

/v1/metrics -> token usage adapter -> usage ledger -> usage

packaged campaign records -> evaluator -> schema-v1 JSON
```

The receiver also serves `/healthz`. It stays in the foreground, accepts literal
loopback addresses, and has no exporter.

## Evidence keeps its source meaning

The project doesn't reduce all signals to “skill used.” It preserves these kinds
of evidence:

- native or structured activation.
- explicit skill command.
- prompt expansion.
- canonical skill-file read.
- candidate mention.
- aggregate native metric.
- generic runtime event.
- failed, unsupported, or redacted provenance.

Each adapter can strengthen a claim only through rules owned by that runtime. A
Codex file read, for example, needs a matching `NAME=PATH` inventory entry during
explicit ingest. A caller can't supply a bare name or hash and call it proven.
Pi reads must match Pi's bounded inventory. A redacted Claude event stays redacted.

Token counts aren't skill evidence. They have a separate schema and can't answer
which skill, session, model, price, or cost produced a point.

## Stores and retries

Skill events and usage points have separate folders, locks, file limits, and
dedupe keys. The skill store keeps up to four 5 MiB files. The usage store keeps up
to eight 20 MiB files. Rotation shifts the retained files and drops the oldest.

A ledger normalizes the whole batch before the first append. The write itself is
not transactional. A failure can leave a valid prefix. A retry skips that prefix
while its fingerprints remain in the retained set.

Rotation can remove old fingerprints before a later append fails. Dedupe therefore
covers the retained window, not the lifetime of the store.

Skill and usage writes are also not one atomic commit. A request can save skill
events before a later usage write fails. A retry follows each store's own dedupe
rule.

Readers treat a torn or malformed line as corrupt state. They stop and report the
problem rather than guessing where valid data ends.

## Bounded collection

Explicit ingest begins with repeatable `--input` paths. It never searches home or
agent folders. Limits cover directory entries, folders, depth, files, bytes,
records, JSON depth, string and line size, open file handles, and Codex inventory.

Input and inventory reads use no-follow opens and file identity checks. These rules
protect the seams that own those reads. They don't claim that every action by an
external runtime is free from filesystem races.

The Claude hook has its own stdin and inventory caps. It reads only absolute roots
from `SKILL_TELEMETRY_SKILL_ROOTS`. If telemetry fails, the hook writes no stdout
and returns zero. That fail-open rule keeps telemetry from blocking the agent.

## Privacy boundary

The skill schema allows only known fields. It keeps safe IDs and optional namespaced
SHA-256 pseudonyms for local matching. It rejects unknown fields and unsafe IDs.

The stores leave out raw prompts, arguments, request bodies, tool content, source
paths, credentials, model identity, pricing, and raw session and turn IDs. No
component exports records.

File modes protect data from other users. They don't form a sandbox. A process
that runs as the same user can read the same files.

## Evaluation boundary

`evaluate` reads safe campaign data from the Python package. It runs production
adapter and scoring paths without Node, a repo checkout, or a live runtime. The
schema-v1 JSON result is authoritative. Markdown is an optional human report.

Pi matching, type checks, and package loading run in repo CI against Pi 0.84.2.
Packaged records labeled Pi 0.80.10 cover a historical data contract. They don't
show that the installed evaluator ran that Pi version.

## Process and config boundary

The package doesn't install a service, credentials, profile, or agent config.
`serve` is the only collector process and stays attached to its caller. An
operator may use an outside process manager, but that manager isn't part of this
project.

Absolute CLI paths and environment variables select state. The product has no
config file and no config mutation API.
