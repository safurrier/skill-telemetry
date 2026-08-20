---
id: skill-telemetry-review-performance
title: Performance and resource-bounds review rubric
description: Review lens for parsing, traversal, receiver, memory, and ledger costs.
index:
  - id: bounds
    keywords: [bytes, files, depth, records, descriptors]
  - id: hot-paths
    keywords: [http, protobuf, json, hashing, ledger]
  - id: evidence
    keywords: [benchmark, profile, regression, tests]
---

# Performance and resource-bounds review rubric

Performance work in this project starts with bounded behavior. A faster path that
removes a safety cap is usually a regression.

## Inputs and memory

- Do HTTP content length and chunked bodies stay within the request cap?
- Do JSON and JSONL parsing retain depth, node, string, line, and total-byte
  bounds before building large in-memory structures?
- Do directory traversal and inventory keep file, directory, depth, descriptor,
  per-file, and aggregate limits?
- Does protobuf normalization drop raw payload content after it builds the
  allowlisted record?

## Storage hot paths

- Does dedupe scanning remain proportional to the bounded retained window?
- Does a new index or fingerprint avoid unbounded memory growth?
- Are rotation, fsync, lock duration, and batch normalization costs understood?
- Can a larger default make owner-local storage or startup reads unexpectedly
  expensive?

## Pi extension

- Does inventory hashing keep per-skill, aggregate-byte, and record caps?
- Are descriptors closed on success, replacement, non-regular input, and errors?
- Does lifecycle work avoid blocking the agent on telemetry failure?

## Evidence level

Existing boundary tests are usually enough for changes that preserve algorithms
and only rearrange code. Require timing, allocation, or profiling evidence when a
change modifies parsing strategy, repeated ledger scans, hashing volume, lock
scope, request handling, or default limits. Report the input size, platform, and
command so another reviewer can reproduce the result.
