---
id: skill-telemetry-how-to-run-collector
title: Run the foreground collector
description: Start the loopback OTLP receiver, verify ownership and health, and choose explicit state paths.
index:
  - id: start
    keywords: [serve, host, port, state]
  - id: verify
    keywords: [doctor, healthz, loopback]
  - id: troubleshoot
    keywords: [bind, listener, permissions]
---

# Run the foreground collector

The public package runs one foreground receiver. It doesn't install or manage a
background service.

## Start with explicit state

```bash
skill-telemetry serve \
  --host 127.0.0.1 \
  --port 14318 \
  --state-dir /absolute/path/to/skill-state \
  --usage-state-dir /absolute/path/to/usage-state
```

Both state paths must be absolute. Omit them to use the XDG defaults. The process
prints startup information and remains attached to the terminal.

The receiver exposes:

| Route | Purpose |
| --- | --- |
| `/healthz` | Health and loopback policy |
| `/v1/logs` | OTLP HTTP log ingestion |
| `/v1/metrics` | OTLP HTTP metric ingestion |

The receiver accepts only literal loopback hosts. Use `127.0.0.1` for the
supported bind example. Names such as `localhost`, wildcard addresses, and
non-loopback IP addresses fail before the server starts.

## Verify readiness

From another terminal:

```bash
skill-telemetry doctor \
  --endpoint http://127.0.0.1:14318 \
  --state-dir /absolute/path/to/skill-state \
  --format json
```

Success reports an `ok` status, a loopback-only collector, and private state
policy. `doctor` contacts only a literal loopback HTTP endpoint.

## Stop the collector

Press `Ctrl-C` in the server terminal. The package doesn't daemonize or register a
service. If you supervise it with another process manager, that lifecycle and its
configuration remain outside this project.

## Diagnose common failures

- **Address already in use:** another process owns the selected port. Stop that
  process or choose another loopback port.
- **Host rejected:** pass the supported literal loopback address `127.0.0.1`.
- **State path rejected:** use an absolute path whose components aren't unsafe
  links or non-directories.
- **Health check fails:** confirm that `doctor` uses the same port as `serve` and
  that the receiver process is still running.
- **Corrupt state:** readout and append operations fail visibly on malformed
  retained lines. Preserve the files for diagnosis. Don't assume the tool has
  silently repaired them.
