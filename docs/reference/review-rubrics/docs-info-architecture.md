---
id: skill-telemetry-review-docs-info-architecture
title: Documentation and information architecture review rubric
description: Review lens for public prose, navigation, authority, and durable decisions.
index:
  - id: audience
    keywords: [reader, task, journey, discoverability]
  - id: authority
    keywords: [readme, spec, schema, architecture, reference]
  - id: drift
    keywords: [links, versions, duplication, placeholders]
---

# Documentation and information architecture review rubric

## Reader and task

- Does the page identify its audience and the task or question it answers?
- Can a new user reach installation, collection, readout, privacy, and support
  information without entering contributor workflow docs?
- Does a tutorial teach a sequence, a how-to solve one task, an explanation give
  rationale, and a reference provide stable facts?

## Authority

- Does `SPEC.md` remain the normative behavior contract?
- Do packaged schemas remain the authority for machine-readable shapes?
- Does architecture explain mechanism without silently widening support?
- Does the README orient and route rather than duplicate every reference table?
- Does the decision ledger record history without replacing current reference?

## Accuracy and drift

- Do commands, options, exit codes, environment variables, paths, and version
  claims match source, help output, tests, or release metadata?
- Are links valid and relative to the page that contains them?
- Does the repo centralize repeated exact versions or limits where practical?
- Did template prompts, empty headings, stale migration language, or contributor
  jargon enter public docs?
- Does the page preserve privacy, security, authentication, and unsupported-state
  wording exactly enough to avoid overclaiming?

## Change evidence

For a broad rewrite, require an independent semantic-preservation review. Run the
repository documentation tests and the source-bound writing check on each changed
page. Treat writing findings as advisory observations, not proof of correctness or
readiness.
