---
id: skill-telemetry-adr-0001
title: ADR 0001—Python core with a TypeScript Pi package
description: Why the project uses Python for portable telemetry and TypeScript for Pi integration.
index:
  - id: context
    keywords: [python, typescript, pi, otlp]
  - id: decision
    keywords: [stack, packaging, task-api]
  - id: consequences
    keywords: [tradeoffs, distribution, testing]
---

# ADR 0001: Python core with a TypeScript Pi package

- **Status:** Accepted
- **Date:** 2026-08-19
- **Decision owners:** project maintainers

## Context

The portable product needs to parse bounded JSON and JSONL, validate closed
schemas, receive OTLP protobuf over HTTP, maintain private local ledgers, and ship
as a standalone command-line tool. It also needs an optional extension that runs
inside Pi's TypeScript extension API and writes Pi-owned custom session entries.

One implementation language can't remove the host-runtime boundary. Bundling the
Python collector into the Pi process would couple local storage and receiver
lifecycle to Pi. Reimplementing the full collector in TypeScript would duplicate
the contract and make Claude and Codex integration depend on Node.

## Decision

Use Python 3.12+ for the portable core:

- Cyclopts provides the non-interactive CLI.
- Dataclasses and explicit validators define sparse record contracts.
- The standard library owns HTTP serving, filesystem operations, hashing, and
  JSONL persistence.
- `opentelemetry-proto` supplies OTLP message types.
- JSON schemas ship as package data for machine-readable response contracts.

Use TypeScript only for the Pi package:

- `pi/src/index.ts` registers Pi lifecycle handlers.
- `pi/src/matching.ts` owns bounded Pi inventory and event matching.
- Pi writes custom session entries. The Python CLI imports them only from an
  explicit path.

Keep `mise` as the repository task API. Contributors use the same task names in
local work and CI even if the underlying Python, Node, or validation commands
change.

## Consequences

### Benefits

- The Python wheel works without Node, Pi, or a repository checkout.
- Claude, Codex, and OTLP support share one contract and persistence layer.
- Pi-specific lifecycle behavior stays close to Pi's API and type system.
- Users can install Python and Pi from the same reviewed Git commit.

### Costs

- The repository carries two lockfiles and two test toolchains.
- Cross-language fixtures must catch drift between Pi's producer and Python's
  consumer.
- The installed Python evaluator can't prove that the Pi extension loads. CI
  must run that check separately.
- No package registry publishes either surface, so users install from Git refs.

## Alternatives considered

| Alternative | Why it wasn't chosen |
| --- | --- |
| Python only, including Pi integration | Pi extensions run in TypeScript and need direct access to Pi lifecycle APIs. |
| TypeScript only | It would make the portable collector and Claude/Codex workflows depend on Node and duplicate mature Python validation/storage work. |
| One process for Pi and the collector | It would tie receiver and persistence lifecycle to Pi instead of keeping collection independently operable. |
| Separate repositories | It would make producer/consumer version alignment and release verification harder for the first public release. |
