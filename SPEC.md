---
id: skill-telemetry-spec
title: skill-telemetry specification
---

# skill-telemetry specification

This file defines the product contract. Packaged JSON schemas define exact data
shapes. The architecture docs explain how the code meets this contract.

## Product scope

`skill-telemetry` is a local tool for macOS and Linux. It records bounded skill
evidence and separate token counts.

The Python package needs Python 3.12 or newer. Release CI runs Python 3.12 on
Ubuntu. The Pi package uses Pi 0.84.2 for its exact test target.

| Public command | Purpose |
| --- | --- |
| `version` | Report the installed release |
| `serve` | Run the foreground receiver |
| `doctor` | Check receiver and state health |
| `readout` | Read skill evidence |
| `usage` | Read token histograms |
| `ingest pi` | Import selected Pi files |
| `ingest codex` | Import selected Codex files and inventory |
| `evaluate` | Score safe campaign data |
| `claude-hook` | Accept one bounded, fail-open hook payload |

The tool has no config writer, service manager, profile selector, auth flow, or
live probe. It doesn't support Windows, remote export, hosted storage, or claims
about missed activations.

## Skill evidence

- The skill store accepts only schema-v1 events with known fields and safe IDs.
- Evidence stages stay separate. A candidate, read, metric, or runtime event does
  not become an activation.
- The store never keeps raw prompts, arguments, request bodies, tool content,
  source paths, credentials, or raw session and turn IDs.
- Events may include namespaced SHA-256 pseudonyms for local matching. These
  hashes aren't raw IDs or proof of identity outside this contract.
- Files, locks, retention, and dedupe remain private and bounded.

## Token usage

- Token histograms have their own schema, files, lock, limits, and read command.
- Usage points keep only known counters and dimensions.
- They don't name a skill, session, model, price, or cost.
- Skill writes and usage writes happen in order, but not as one atomic commit.

## Receiver

- `serve` accepts only literal loopback addresses.
- HTTP framing and request bodies have fixed limits.
- `/v1/logs` accepts OTLP HTTP logs.
- `/v1/metrics` accepts OTLP HTTP metrics.
- `/healthz` reports health.
- The receiver has no exporter and stays in the foreground.

## Explicit ingest

- The caller must pass every input through a repeatable `--input` option.
- Ingest never searches agent or home folders.
- Limits cover directory walks, depth, files, bytes, records, JSON shape, open
  files, and Codex inventory.
- File and inventory reads use no-follow opens and identity checks.
- `--dry-run` finds and normalizes records without saving them.
- Dedupe lasts only while a fingerprint remains in retained files.
- A limit or rejected schema record returns a safe partial result with exit code
  5. Malformed JSON/JSONL or unsafe input returns 3. A storage failure returns 7
  and can leave a durable prefix.

## Storage and failure rules

- State folders use mode `0700`. Ledger and lock files use mode `0600`.
- The store normalizes the full batch before its first append.
- A failed write may leave a valid prefix. A retry skips that prefix while its
  fingerprints remain on disk.
- Rotation may remove the oldest file before a later append fails.
- A torn or bad retained line causes a visible failure.
- `readout` and `usage` read only the chosen store. They never import agent data.

## Output and exits

Finite commands support `--format text|json`. JSON mode writes one schema-v1
envelope to stdout. Text errors use stderr. JSON errors stay on stdout.

| Code | Meaning |
| ---: | --- |
| 0 | Success |
| 2 | Parse or command input error |
| 3 | Unsafe or invalid contract input |
| 4 | Unsupported operation or option |
| 5 | Partial ingest |
| 6 | Health or evaluation failure |
| 7 | Storage, listener, or other operating failure |

`claude-hook` is the one fail-open exception. It reads one bounded stdin document,
writes no stdout, and returns zero if telemetry fails. Telemetry must not block the
agent.

## Evaluation and packages

- `evaluate` uses safe campaign data that ships in the wheel by default.
- The default run uses Python adapters and stores. It needs no Node process,
  checkout search, network call, or mise task.
- Schema-v1 JSON is the source of truth. Optional Markdown is an owner-only,
  create-only report for people.
- Python artifacts include required schemas and campaign files but no Node or Pi
  development files.
- The Pi package stays Git-only and points to `pi/src/index.ts` at the same repo
  version.

## Project checks

Use `mise run check` for routine work. Use `mise run verify` when a release or
merge needs wheel and source archive proof. Every release ref must also pass
`mise run public-history`.
