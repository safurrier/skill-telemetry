---
id: skill-telemetry-docs
title: skill-telemetry documentation
description: Task-based guide to the public skill-telemetry documentation.
index:
  - id: start
    keywords: [install, tutorial, first-run, evaluate]
  - id: operate
    keywords: [collector, ingest, readout, state, privacy]
  - id: understand
    keywords: [architecture, evidence, decisions, specification]
  - id: contribute
    keywords: [development, review, release]
---

# skill-telemetry documentation

Start with the task you need to complete. The root [README](../README.md) gives
the shortest installation and product overview. This index points to the longer
operator and contributor material.

## Start locally

- [First local run](tutorials/first-local-run.md) walks from a Git install to a
  packaged evaluation, foreground receiver, and empty-state readout.
- [CLI reference](reference/cli.md) lists commands, side effects, output rules,
  and exit codes.
- [Runtime support](reference/runtime-support.md) records the exact tested
  versions and the claims those tests do—and don't—support.

## Operate the tool

- [Run the foreground collector](how-to/run-the-collector.md) starts the
  loopback receiver and checks readiness.
- [Import explicit evidence](how-to/import-evidence.md) shows how to dry-run
  bounded Pi or Codex inputs and retain them later.
- [Read local results](how-to/read-local-results.md) explains the independent
  skill and usage summaries.
- [State and privacy reference](reference/state-and-privacy.md) covers paths,
  permissions, retention, dedupe, corruption, and the local trust boundary.

## Understand the design

- [Specification](../SPEC.md) is the normative product and behavior contract.
- [Architecture](explanation/architecture.md) explains components, data flow,
  evidence stages, and failure behavior.
- [Decision ledger](explanation/decision-ledger.md) records chronological design
  decisions.
- [ADR 0001](explanation/decisions/0001-stack-choice.md) explains the Python core,
  TypeScript Pi package, and mise task boundary.

## Contribute

- [Development and release checks](how-to/develop-and-release.md) maps repository
  tasks to routine work, handoff, and release proof.
- [Review rubrics](reference/review-rubrics/README.md) provide optional,
  project-specific lenses for code, docs, performance, and CLI experience.
- `AGENTS.md` is contributor workflow guidance, not product documentation.

## Where truth lives

| Source | Authority |
| --- | --- |
| `SPEC.md` | Normative supported behavior and invariants |
| Packaged JSON schemas | Machine-readable record and response shapes |
| `docs/explanation/architecture.md` | Mechanisms, rationale, and failure model |
| `docs/reference/` | Stable operator-facing commands, state, and support facts |
| Root `README.md` | Concise onboarding and common paths |
| Decision ledger and ADRs | Historical decisions, not current command reference |
