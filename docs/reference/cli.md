---
id: skill-telemetry-reference-cli
title: CLI reference
description: Commands, options, side effects, output envelopes, and exit codes.
index:
  - id: commands
    keywords: [version, readout, usage, ingest, serve, doctor, evaluate, claude-hook]
  - id: output
    keywords: [json, text, stdout, stderr, envelope]
  - id: exits
    keywords: [exit-code, partial, health, operational]
---

# CLI reference

The installed entry point is `skill-telemetry`. Commands are non-interactive,
don't page output, and honor `NO_COLOR`.

## Commands

| Command | Important options | Effect |
| --- | --- | --- |
| `version` | `--format text|json` | Read-only installed-version response |
| `readout` | `--state-dir`, `--format` | Pure read of skill evidence |
| `usage` | `--state-dir`, `--format` | Pure read of token histograms |
| `doctor` | `--endpoint`, `--state-dir`, `--format` | Contacts a literal loopback receiver and checks private state |
| `serve` | `--host`, `--port`, `--state-dir`, `--usage-state-dir`, `--format` | Runs a foreground listener and writes accepted records |
| `ingest pi` | repeatable `--input`, `--dry-run`, limits, `--state-dir`, `--format` | Imports explicit Pi JSON/JSONL |
| `ingest codex` | Pi options plus repeatable `--skill NAME=PATH` | Imports explicit Codex JSON/JSONL with supplied inventory |
| `evaluate` | `--manifest`, `--observations`, `--markdown-output`, `--format` | Scores packaged or explicit sanitized campaign data |
| `claude-hook` | `--state-dir` | Reads bounded stdin, may append one event, and fails open |

Run `skill-telemetry COMMAND --help` for generated option details.

## Shared output contract

Finite commands accept `--format text|json`. JSON output is one schema-v1 document
with these top-level fields:

```json
{
  "schema_version": 1,
  "command": "readout",
  "tool_version": "0.1.0",
  "status": "ok",
  "data": {},
  "warnings": [],
  "unsupported": []
}
```

Exact `data` shapes come from the packaged schemas. Successful text output uses
stdout. Text diagnostics use stderr. In JSON mode, command errors return a JSON
envelope on stdout and leave stderr empty.

`claude-hook` doesn't use this envelope. It emits no stdout and returns zero on
telemetry failures.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success |
| 2 | Parse or command-input error |
| 3 | Unsafe, invalid, or contract input |
| 4 | Unsupported operation or option |
| 5 | Partial ingest |
| 6 | Health or evaluation failure |
| 7 | Operational, storage, or listener failure |

## Ingest limits

Public ingest options can override selected defaults:

| Option | Default |
| --- | ---: |
| `--max-files` | 256 |
| `--max-file-bytes` | 8 MiB |
| `--max-total-bytes` | 32 MiB |
| `--max-records` | 50,000 top-level records |
| `--max-depth` | 8 directory levels |

Additional fixed bounds cover traversal entries, directories, discovery bytes,
structured JSON nodes, JSON depth, string and line sizes, live descriptors, and
Codex inventory. See [State and privacy](state-and-privacy.md) for the full
operational boundary.

## Evaluation metrics and output files

The evaluation report uses two different unknown-rate denominators:

- top-level `metrics.unknown_rate` is the number of unobservable cases divided by
  all campaign cases.
- each `metrics.stages.*.unknown_rate` is the number of unknown events for that
  stage divided by observed events for that stage.

`--markdown-output` writes an optional human report. The path must be absolute and
must name a new file. The command uses a no-follow, owner-only create and doesn't
replace an existing path. The JSON result remains authoritative.
