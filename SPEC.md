---
id: skill-telemetry-spec
title: skill-telemetry specification
---

# skill-telemetry specification

## Product boundary

`skill-telemetry` is a local, POSIX-only (macOS/Linux) collector for bounded,
privacy-filtered skill evidence and an independent token-usage histogram domain.
Release CI covers Python 3.12 on Ubuntu; the package metadata permits newer
Python 3 releases, but they are not a release-CI support claim. The Pi extension
API is pinned for development at 0.84.2. Windows, service management, profiles, authentication, remote export,
configuration mutation, runtime probing, and semantic missed-activation claims
are unsupported.

The public command tree is `version`, foreground `serve`, `doctor`, pure
`readout`, `usage`, `ingest pi`, `ingest codex`, `evaluate`, and fail-open
`claude-hook`. There are no classify, normalize, config, service, profile,
authentication, or live-probe commands.

## Invariants

- Stores retain only schema-v1 allowlisted records in owner-only bounded JSONL.
  Skill and token usage have distinct contracts, locks, retention, and readouts.
- Raw prompts, arguments, request bodies, tool content, paths, credentials,
  model identity, cost, and session attribution are never retained or exported.
- The receiver accepts literal loopback addresses only and has no export path.
  Request framing and body size are bounded.
- Explicit ingestion accepts only bounded, no-follow inputs. `readout` and
  `usage` do not scan or import ambient runtime state. Ingest dedupe lasts only
  while its fingerprint remains in the retained window; pruning permits reimport.
- Finite commands provide `--format text|json`. JSON emits one schema-v1
  envelope on stdout; diagnostics are stderr. Exit codes are 0 success, 2 parse,
  3 unsafe/invalid input, 4 unsupported, 5 partial ingest, 6 health/evaluation
  failure, and 7 operational failure. `claude-hook` is intentionally different:
  bounded stdin, no stdout, exit 0 on telemetry failure.
- `evaluate` uses packaged sanitized data and Python only. Its JSON report is
  authoritative; optional Markdown is human-only.

## Acceptance

`mise run check`, `mise run verify`, and `mise run sync-check` pass. The wheel
and sdist contain required Python data but no Node package files. Installed
outside-checkout `version`, `readout`, and `evaluate` work without Node, mise,
or `PYTHONPATH`; Pi matcher/type/package-load checks remain repository CI.
