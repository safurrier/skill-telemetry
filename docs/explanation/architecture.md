---
id: skill-telemetry-architecture
title: Architecture
---

# Architecture

## Local data flow

```text
explicit Pi/Codex files ──> bounded adapter ──> SkillEvent JSONL ──> readout
loopback OTLP logs/metrics ─> collector ──────> SkillEvent / usage JSONL
Claude hook stdin ──────────> fail-open adapter ─> SkillEvent JSONL
packaged acceptance data ───> deterministic evaluator ─> JSON report
```

The Python core owns contracts, validation, privacy filtering, JSONL ledgers,
receiver composition, explicit ingestion, readouts, and deterministic campaign
evaluation. The optional Pi extension owns Pi event matching and writes only
Pi-owned custom entries. It records no source paths or prompt text.

## Persistence and evidence

Each domain has an independent owner-only JSONL ledger, lock, byte cap, and
rotation policy. A batch is normalized before its first append. Append failure
is at-least-once: a readable durable prefix can remain, and retry deduplicates
that prefix while it is retained. Rotation may prune the oldest segment before
a failed append; dedupe is therefore retention-scoped rather than lifetime.
Abrupt termination can leave a torn final line, which is reported as corrupt
state instead of silently ignored.

Skill evidence stages remain separate: native/structured activation,
explicit command, prompt expansion, canonical read, candidate, aggregate
metric, runtime telemetry, and unsupported/redacted evidence are not promoted
into one another. Token histograms are a separate readout and never infer
skill, session, model, or cost attribution.

## Boundaries

The receiver uses literal loopback only and bounded HTTP framing. Input
collection is explicit: no command searches ambient agent roots. Inputs are
opened without following symlinks and discovery, descriptors, depth, files,
bytes, JSON nesting, strings, and records are bounded. `readout` and `usage`
only inspect their own supplied/default XDG stores.

The package neither installs configuration nor manages processes. Manual
runtime snippets are documentation, not a configuration API. Public operation
is foreground `serve`; users supervise it with their own tooling.

## Evaluation

`evaluate` loads sanitized campaign data packaged with the wheel and exercises
Python adapter/store seams. It contains no checkout discovery and no Node or
repository-task dependency. JSON is the stable machine report; Markdown is an
optional human artifact. Pi matcher/type/package-loading tests against 0.84.2
are release CI evidence rather than installed evaluator behavior. Records labeled
0.80.10 are packaged historical normalized-contract cases only, not runtime
execution evidence. The report's top-level `unknown_rate` is case-level; each
stage `unknown_rate` is event-level.
