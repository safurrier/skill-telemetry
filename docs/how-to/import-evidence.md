---
id: skill-telemetry-how-to-import-evidence
title: Import explicit Pi or Codex evidence
description: Discover, dry-run, and retain bounded evidence from caller-selected files and directories.
index:
  - id: pi
    keywords: [pi, session, jsonl, dry-run]
  - id: codex
    keywords: [codex, inventory, skill, provenance]
  - id: partial
    keywords: [limits, exit-5, dedupe, retry]
---

# Import explicit Pi or Codex evidence

Ingest reads only the paths you pass with `--input`. It never searches runtime
roots or home directories.

## Dry-run Pi input

```bash
skill-telemetry ingest pi \
  --input /absolute/path/to/session.jsonl \
  --dry-run \
  --format json
```

Repeat `--input` for more files or directories. A dry run performs bounded
discovery, parsing, and normalization against an isolated temporary store. It does
not append to your configured ledger.

Review the response counters before retaining anything. They distinguish scanned files and records, imported events, duplicates, rejected
data, and limit status.

## Dry-run Codex input

Codex canonical-read qualification needs an explicit inventory. Map each skill
name to a bounded regular file:

```bash
skill-telemetry ingest codex \
  --input /absolute/path/to/events.jsonl \
  --skill demo=/absolute/path/to/demo/SKILL.md \
  --dry-run \
  --format json
```

Repeat `--skill NAME=PATH` when the selected input can refer to more than one
skill. The mapping qualifies provenance. It doesn't cause the command to search
for other skills.

## Retain validated events

After a satisfactory dry run, repeat the same command without `--dry-run`. Choose
an explicit destination when you don't want the default XDG store:

```bash
skill-telemetry ingest pi \
  --input /absolute/path/to/session.jsonl \
  --state-dir /absolute/path/to/skill-state \
  --format json
```

Then inspect it:

```bash
skill-telemetry readout \
  --state-dir /absolute/path/to/skill-state \
  --format json
```

## Understand partial results

Exit code 5 means a preflight limit or rejected schema record made the result
partial. The JSON response identifies the limit and rejection counters. Preflight
limits stop the append. Rejection paths retain the other valid normalized events.

Malformed JSON/JSONL or unsafe input returns 3. A storage failure returns 7 and can
leave a valid durable prefix. Retrying is safe for fingerprints still present in
retained files. Rotation can prune old fingerprints, so replay protection isn't
permanent.

## Override limits carefully

`--max-files`, `--max-file-bytes`, `--max-total-bytes`, `--max-records`, and
`--max-depth` can lower or raise selected public limits. Other parser, descriptor,
and inventory caps remain implementation-owned safety bounds.

Don't raise limits merely to force an unknown input through. First narrow the
explicit input set and inspect the partial counters.
