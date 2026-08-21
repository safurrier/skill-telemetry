---
id: skill-telemetry-how-to-read-results
title: Read local skill and usage results
description: Inspect retained evidence without importing runtime data or overstating attribution.
index:
  - id: skill
    keywords: [readout, activation, evidence, unknown]
  - id: usage
    keywords: [tokens, histogram, model, cost]
  - id: interpretation
    keywords: [attribution, stage, limitation]
---

# Read local skill and usage results

The two read commands are pure: they inspect their selected stores and don't scan
or import runtime data.

## Read skill evidence

```bash
skill-telemetry readout --format json
```

For an explicit store:

```bash
skill-telemetry readout \
  --state-dir /absolute/path/to/skill-state \
  --format json
```

The summary keeps strong and weak evidence separate. Counts can include explicit
commands, structured activations, canonical reads, aggregate metrics, candidates,
runtime telemetry, unsupported or redacted records, and unknown evidence.

Don't combine those counts into a single activation total unless the consuming
analysis defines and justifies that operation. A candidate or file read isn't an
activation.

## Read token histograms

```bash
skill-telemetry usage --format json
```

Or select the independent usage store:

```bash
skill-telemetry usage \
  --state-dir /absolute/path/to/usage-state \
  --format json
```

Usage points contain known Codex token histogram fields. They don't
identify a skill, session, model, price, or cost. The usage store has a different
lock, retention policy, and dedupe fingerprint from the skill store.

## Read an empty store

An empty directory is a valid input. The command returns an `ok` schema-v1 envelope
with zero counts. It doesn't create evidence to make the report non-empty.

## Handle corruption

If a retained JSONL line tears or becomes malformed, the command fails instead of
skipping it. Preserve the file before any manual repair. The package doesn't offer
a command that silently truncates or rewrites corrupt state.

For exact paths, permissions, and retention defaults, see
[State and privacy](../reference/state-and-privacy.md).
