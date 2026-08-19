---
id: skill-telemetry-review-performance
title: Performance Review Rubric
description: >
  Review lens for slices that affect latency, throughput, or resource usage.
index:
  - id: performance
    keywords: [performance, latency, throughput, memory, benchmarks]
  - id: evidence
    keywords: [benchmarks, profiling, regressions, proof]
---

# Performance

Review for:

- whether the change introduces obvious hot-path regressions
- whether benchmark or profiling evidence is present when performance matters
- whether resource costs are proportional to the feature gain
