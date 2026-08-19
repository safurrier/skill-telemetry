---
id: skill-telemetry-adr-0001
title: ADR 0001 — Initial Stack Choice
description: >
  Records the python stack selection decision for skill-telemetry.
index:
  - id: decision
    keywords: [stack, adr, bootstrap, architecture]
  - id: consequences
    keywords: [tradeoffs, tooling, ecosystem]
---

# ADR 0001: Initial Stack Choice

**Status**: Accepted
**Date**: 2026-01-01
**Deciders**: repo initialization
**Generated from**: init

---

## Context

skill-telemetry needs a default implementation stack, toolchain, and task
surface immediately after initialization.

## Decision

Adopt **python** as the initial stack for skill-telemetry and wire
the generated repo around the stable `mise` task contract.

## Consequences

**Positive:**

- Generated repos are runnable and testable from the first commit.
- The task contract stays consistent even as implementation details vary.

**Negative / Trade-offs:**

- The initial stack shapes tool choices and examples until future decisions revise them.

## Alternatives Considered

| Alternative | Reason not chosen |
|---|---|
| Delay stack selection | Generated repos would have no working golden path |
