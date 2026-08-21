---
id: skill-telemetry-review-cli-experience
title: CLI and operator experience review rubric
description: Review lens for help, output, exits, errors, readiness, and empty states.
index:
  - id: discovery
    keywords: [help, examples, options, command]
  - id: automation
    keywords: [json, stdout, stderr, exit-code]
  - id: operation
    keywords: [serve, doctor, error, empty-state]
---

# CLI and operator experience review rubric

The product has no graphical interface. Review interaction through commands,
machine output, and local operating states.

## Discovery

- Does top-level help make the command and its side effects clear?
- Do option names, defaults, repeatability, and required values appear in generated
  help?
- Does documentation start with read-only or dry-run commands before persistence
  or listener examples?
- Are Git-only installation and unsupported registry paths explicit?

## Automation contract

- Does every finite JSON command emit exactly one schema-valid document on stdout?
- Do text and JSON errors use the documented stdout/stderr split?
- Are exit codes stable and specific enough for an automated caller?
- Are warnings and unsupported states structured without raw or secret content?
- Does output avoid paging, prompts, progress noise, and ANSI formatting where the
  machine contract forbids them?

## Operating states

- Does `serve` provide a clear startup signal and remain in the foreground?
- Can `doctor` distinguish healthy, unavailable, unsafe, and unsupported states?
- Do empty `readout` and `usage` results remain successful and understandable?
- Do ingest responses distinguish limits and rejections from malformed-input
  errors, and report retained counts without overstating completion?
- Do corrupt state and path-safety failures tell the operator what boundary failed
  without echoing unsafe input?

## Friction

Prefer one explicit command over hidden discovery. Avoid options that silently
scan home directories, mutate third-party configuration, choose credentials, or
change evidence semantics. If an operation writes state, binds a socket, or creates
a report, its help and documentation should say so.
