---
id: skill-telemetry-reference-state-privacy
title: State and privacy reference
description: State paths, file modes, retention, dedupe, corruption, and retained fields.
index:
  - id: paths
    keywords: [xdg, environment, state-dir]
  - id: retention
    keywords: [jsonl, rotation, size, files, dedupe]
  - id: privacy
    keywords: [allowlist, pseudonym, credentials, trust]
---

# State and privacy reference

## Choose state paths

| Variable or option | Domain | Rule |
| --- | --- | --- |
| `--state-dir` on skill commands | Skill | Select an absolute skill-state path |
| `--state-dir` on `usage` | Usage | Select an absolute usage-state path |
| `--usage-state-dir` on `serve` | Usage | Select an absolute usage-state path |
| `SKILL_TELEMETRY_STATE_DIR` | Skill | Absolute folder override |
| `SKILL_TELEMETRY_USAGE_STATE_DIR` | Usage | Absolute folder override |
| `XDG_STATE_HOME` | Both | Absolute base when no domain override exists |

The default paths are:

```text
~/.local/state/skill-telemetry
~/.local/state/skill-telemetry-usage
```

The product has no config file. `SKILL_TELEMETRY_SKILL_ROOTS` serves a different
purpose: it lists absolute Claude inventory roots for `claude-hook`.

## File layout and limits

| Domain | Current file | Rotated files | Lock | Default cap |
| --- | --- | --- | --- | --- |
| Skill | `events.jsonl` | `events.1.jsonl` and later | `.store.lock` | 5 MiB × 4 files |
| Usage | `usage.jsonl` | `usage.1.jsonl` and later | `.usage-store.lock` | 20 MiB × 8 files |

State folders use mode `0700`. Ledger and lock files use mode `0600`. The store rejects a directly
symlinked state folder. Ledger and lock leaf files use no-follow opens,
and the store validates their type, owner, and mode. Intermediate path components
follow normal filesystem resolution.

These modes protect data from other users. They don't isolate it from another
process that runs as the same user.

## Skill records

A skill event can keep a small set of safe fields:

- agent system and event name.
- skill name and content hash when the source qualifies them.
- evidence type, confidence, trigger, and status.
- timestamp and bounded count.
- namespaced SHA-256 pseudonyms for local session, turn, or activation matching.

The store leaves out raw prompts, command arguments, request and tool bodies,
source paths, credentials, model identity, pricing, and raw session and turn IDs.
Unknown fields and unsafe IDs fail validation.

A pseudonym can match records inside this local contract. It isn't a raw ID or a
claim about identity in another dataset.

## Usage records

Usage points contain known Codex token histogram fields. They use their own schema
and store. They don't name a skill, session, model, price, or cost.

## Rotation and retry

The ledger normalizes a whole batch and computes fingerprints before it appends.
If the current file lacks space, rotation shifts the retained files and removes
the oldest one.

A failed append can leave a valid prefix. A retry skips that prefix while its
fingerprints remain on disk. If rotation removed an old fingerprint, a later
replay can write it again. Dedupe covers retained data, not all past data.

Skill events dedupe by activation ID when one exists. Usage points dedupe with a
hash of the exact canonical point.

## Corrupt state

A torn or malformed retained line causes a visible read or append failure. The
tool doesn't skip, trim, or repair it. Preserve the files before manual work.

Uninstall leaves both state folders in place. Delete them only when you mean to
discard the evidence.
