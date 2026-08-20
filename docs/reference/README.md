---
id: skill-telemetry-reference
title: Reference
description: Stable command, state, privacy, support, and contributor review facts.
index:
  - id: cli
    keywords: [commands, options, output, exit-codes]
  - id: state
    keywords: [paths, permissions, retention, privacy]
  - id: support
    keywords: [runtime, version, platform, limitation]
  - id: review
    keywords: [rubric, contributor, quality]
---

# Reference

Use reference pages when you need an exact interface or boundary rather than a
step-by-step task.

## Product reference

- [CLI reference](cli.md)—commands, side effects, JSON/text output, ingest
  options, and exit codes.
- [State and privacy](state-and-privacy.md)—environment variables, default paths,
  permissions, retained fields, rotation, dedupe, and corruption behavior.
- [Runtime support](runtime-support.md)—tested versions, fixture scope,
  platforms, and unsupported surfaces.
- [`SPEC.md`](../../SPEC.md)—normative behavioral requirements.
- Packaged schemas under `src/skill_telemetry/schemas/`—machine-readable JSON
  response shapes.

## Contributor reference

- [Review rubrics](review-rubrics/README.md)—optional project-specific lenses
  for code, docs, performance, and command-line experience.
- [Development and release checks](../how-to/develop-and-release.md)—the mise
  task surface and public-history workflow.

The product has no general configuration file. Don't infer configuration or
service behavior from contributor tooling.
