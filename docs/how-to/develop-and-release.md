---
id: skill-telemetry-how-to-develop-release
title: Develop and verify a release
description: Use the repository task surface for routine checks, handoff evidence, artifacts, and public refs.
index:
  - id: setup
    keywords: [mise, dependencies, branch]
  - id: validate
    keywords: [check, sync-check, verify, ci]
  - id: release
    keywords: [public-history, artifacts, git, tag]
---

# Develop and verify a release

These commands operate in a source checkout. They install local development
dependencies, run tests, or create build output. They don't publish a release.

## Set up the checkout

Create a feature branch before planning meaningful work, then install locked
Python dependencies:

```bash
git switch -c <type>/<short-name>
mise run setup
```

For a contribution that changes behavior or durable documentation, create and
maintain the repository plan required by `AGENTS.md`:

```bash
mise run plan -- <lowercase-kebab-slug>
```

## Run the routine gate

```bash
mise run check
```

This task runs the reachable-history check for the selected local ref, Python
format/lint/type/tests, Pi install/test/type/package-load checks, and the
Python/Pi version contract.

Use focused tasks while editing:

```bash
mise run fmt-check
mise run lint
mise run typecheck
mise run test
mise run node-check
mise run version-contract
```

## Complete handoff evidence

Update the active plan's decisions, validation, review, and artifact manifest,
then run:

```bash
mise run sync-check
```

This gate checks the changed contribution plan and its evidence. It doesn't
replace source or test validation.

## Build release artifacts

```bash
mise run verify
```

`verify` runs the CI task and then builds and inspects one wheel and one source
distribution. Artifact verification installs each distribution in an isolated
virtual environment and exercises the public Python commands.

## Check publication refs

Before pushing a release ref, scan the exact intended refs:

```bash
uv run python -m scripts.verify_public_history --ref HEAD
```

The scanner inspects reachable blobs plus commit and annotated-tag text. It rejects
unsafe Git modes, generated paths, private path shapes, credential-shaped content,
and objects above its scan limit.

The scanner doesn't enforce a parentless history. The one-commit public shape is
release policy, so inspect the graph separately before publication:

```bash
git rev-list --count HEAD
git show -s --format='%H %P' HEAD
```

Publish Python and Pi only from a reviewed full commit or release tag. This project
doesn't publish to PyPI or npm.
