---
id: skill-telemetry-review-core-quality
title: Core quality review rubric
description: Review lens for contracts, evidence semantics, privacy, persistence, and failures.
index:
  - id: contracts
    keywords: [schema, allowlist, evidence, attribution]
  - id: storage
    keywords: [rotation, dedupe, retry, corruption]
  - id: safety
    keywords: [privacy, bounds, fail-open, fail-closed]
---

# Core quality review rubric

Apply the items that match the change.

## Contracts and evidence

- Does the change preserve the closed schema and reject unknown or unsafe fields?
- Does it keep candidates, reads, activations, aggregate metrics, runtime events,
  and unsupported evidence distinct?
- Are pseudonyms and aggregate counts described without stronger identity or
  attribution claims?
- Does usage remain independent from skill, session, model, price, and cost?

## Privacy and input safety

- Can raw prompts, arguments, request bodies, tool content, paths, credentials, or
  raw runtime identifiers reach a retained field or error message?
- Are explicit paths, HTTP bodies, parser depth, records, bytes, descriptors, and
  inventory still bounded at the owning seam?
- Do no-follow and identity checks remain paired with the filesystem operation
  they protect?

## Persistence and retries

- Does normalization finish before the first append?
- Can a partial prefix, rotation, or cross-domain failure occur, and is that
  behavior represented honestly?
- Does retry dedupe only retained fingerprints?
- Do malformed or torn retained lines fail visibly?
- Are directories, files, and locks still owner-only?

## Failure boundaries

- Does the receiver fail closed on unsafe binds, framing, and state?
- Does `claude-hook` remain fail-open, silent on stdout, and content-safe?
- Do JSON errors preserve the one-envelope stdout contract and stable exit code?
- Does the code keep a new unsupported state explicit rather than normalize it
  into success?

## Evidence

Require focused regression coverage for the changed boundary. Add broad tests only
when the change crosses adapters, stores, packaging, or language boundaries. Check
claims against [`SPEC.md`](../../../SPEC.md) and the relevant packaged schema.
