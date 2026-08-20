---
id: skill-telemetry-reference-runtime-support
title: Runtime support and evidence claims
description: Tested runtime versions, fixture scope, evidence semantics, and unsupported surfaces.
index:
  - id: platforms
    keywords: [python, ubuntu, macos, linux, windows]
  - id: runtimes
    keywords: [pi, claude, codex, fixture, version]
  - id: limitations
    keywords: [unsupported, attribution, probing, export]
---

# Runtime support and evidence claims

This page distinguishes product support, fixture compatibility, and historical
labels. A passing normalized fixture doesn't certify a future runtime release.

## Platform boundary

| Surface | Claim |
| --- | --- |
| Python package | Requires Python 3.12+ on macOS and Linux product boundary |
| Release CI | Python 3.12 on Ubuntu |
| Windows | Unsupported |
| Receiver | Foreground process on literal loopback only |
| Distribution | Git tag or reviewed full commit. No PyPI or npm release |

## Agent runtime evidence

| Runtime | Evidence in this release | Limit |
| --- | --- | --- |
| Pi | Extension test, type check, and package-load smoke against Pi 0.84.2 | No forward-compatibility promise |
| Pi historical campaign | Sanitized records labeled Pi 0.80.10 | Normalized-contract label only, not runtime execution evidence |
| Claude Code | Adapter and hook fixtures for Claude 2.1.211 | Fixture contract only |
| Codex | Adapter and usage fixtures for Codex 0.144.5 | Fixture contract only |

The Pi extension listens to selected lifecycle events, writes content-safe custom
session entries, and restores dedupe state on session start. It catches ordinary
JavaScript `Error` failures from append, reports a content-safe warning, and lets
the agent continue. Other thrown values or a failing notification path can still
propagate. Fixed caps bound inventory and hashing.

Claude can report native activation evidence with an identity or mark it as
identity-redacted. The hook reads only caller-declared inventory roots and never
configures Claude.

Codex supports structured events, qualified explicit commands, canonical reads
backed by supplied inventory, aggregate native metrics, and independent usage
histograms. Aggregate metrics don't establish per-session or named-skill
attribution unless their own contract carries that dimension.

## Unsupported or absent

The public project doesn't provide:

- Windows support.
- service or daemon installation.
- runtime profile or credential selection.
- authentication.
- automatic third-party configuration mutation.
- live authenticated probing.
- remote export or hosted storage.
- semantic claims about missed activations.
- model, price, or cost attribution from token histograms.
- a support promise for runtime versions not named above.

Operators can build those integrations around the local CLI, but they remain
outside this release's support claim.
