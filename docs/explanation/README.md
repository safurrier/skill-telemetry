---
id: skill-telemetry-explanation
title: Design explanations
description: System mechanisms, tradeoffs, and durable decisions for skill-telemetry.
index:
  - id: architecture
    keywords: [components, data-flow, evidence, persistence, privacy]
  - id: decisions
    keywords: [ledger, adr, rationale, tradeoffs]
---

# Design explanations

Use these pages when you need to understand why the product behaves as it does.
For commands and stable facts, use the [reference index](../reference/README.md).
For a task, use the [how-to index](../how-to/README.md).

- [Architecture](architecture.md) explains component ownership, collection paths,
  evidence-stage separation, persistence, privacy, and failure behavior.
- [Decision ledger](decision-ledger.md) is the chronological record of durable
  product and repository decisions.
- [ADRs](decisions/) hold decisions that need a full context, alternatives, and
  consequences. Start with
  [ADR 0001: Python core with a TypeScript Pi package](decisions/0001-stack-choice.md).

The specification remains normative. Explanations can describe rationale and
mechanisms, but they don't widen the supported boundary in [`SPEC.md`](../../SPEC.md).
