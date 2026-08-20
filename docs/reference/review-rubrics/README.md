---
id: skill-telemetry-review-rubrics
title: Review rubrics
description: Optional project-specific lenses for reviewing changes to skill-telemetry.
index:
  - id: core
    keywords: [correctness, privacy, evidence, persistence]
  - id: docs
    keywords: [documentation, authority, links, drift]
  - id: performance
    keywords: [bounds, memory, parsing, ledger]
  - id: cli
    keywords: [output, exits, errors, operator]
---

# Review rubrics

These rubrics are optional review lenses, not additional product requirements.
Use the smallest set that matches a change. The specification and tests remain the
sources of behavioral truth.

| Rubric | Use when a change affects |
| --- | --- |
| [Core quality](core-quality.md) | Contracts, adapters, privacy, persistence, receiver, or failure behavior |
| [Docs and information architecture](docs-info-architecture.md) | Public prose, navigation, authority, or decisions |
| [Performance and resource bounds](performance.md) | Parsing, traversal, HTTP bodies, memory, locks, or rotation |
| [CLI and operator experience](ui-ux.md) | Commands, help, output envelopes, errors, exits, or empty states |

A review should cite the changed invariant and the evidence used. It shouldn't
turn these prompts into a generic checklist detached from the patch.
