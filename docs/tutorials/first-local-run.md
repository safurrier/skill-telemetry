---
id: skill-telemetry-tutorial-first-local-run
title: First local run
description: Install a reviewed release, verify it, start the loopback receiver, and inspect empty local state.
index:
  - id: install
    keywords: [uv, git, version, evaluate]
  - id: receiver
    keywords: [serve, doctor, loopback]
  - id: readout
    keywords: [state, readout, usage]
---

# First local run

This walkthrough verifies the Python package and starts a local receiver without
configuring an agent runtime. You need macOS or Linux, Python 3.12 or newer, and
[`uv`](https://docs.astral.sh/uv/).

## Install the reviewed release

```bash
uv tool install \
  'skill-telemetry @ git+https://github.com/safurrier/skill-telemetry.git@v0.1.0'
```

The project is Git-only. This command installs from the `v0.1.0` tag. It doesn't
contact PyPI for `skill-telemetry` itself.

Check the installed version:

```bash
skill-telemetry version --format json
```

In the schema-v1 response, check that `status` is `ok` and `data.version` is
`0.1.0`.

## Run the packaged contract check

```bash
skill-telemetry evaluate --format json
```

A successful installation reports `status` as `ok` and `data.passed` as `true`. The
command uses sanitized campaign data shipped in the wheel. It checks production
Python adapters and scoring, but it doesn't inspect a live agent runtime.

## Use isolated state for the walkthrough

Create two private directories:

```bash
export SKILL_TELEMETRY_STATE_DIR="$PWD/.local-skill-state"
export SKILL_TELEMETRY_USAGE_STATE_DIR="$PWD/.local-usage-state"
```

Both values must be absolute. The stores create their directories with mode
`0700` on the first relevant write. `doctor` ensures and checks only the selected
skill-state directory. It doesn't create the usage directory.

## Start the receiver

In one terminal, run:

```bash
skill-telemetry serve --host 127.0.0.1 --port 14318
```

Leave that process running. It stays in the foreground and accepts local OTLP HTTP
requests only.

In another terminal, export the same state paths and check readiness:

```bash
export SKILL_TELEMETRY_STATE_DIR="$PWD/.local-skill-state"
export SKILL_TELEMETRY_USAGE_STATE_DIR="$PWD/.local-usage-state"
skill-telemetry doctor --endpoint http://127.0.0.1:14318 --format json
```

A healthy response has `status` set to `ok` and `data.loopback_only` set to
`true`.

Stop the receiver with `Ctrl-C` when you finish.

## Read the stores

No runtime has emitted data yet, so both reads should succeed with empty counts:

```bash
skill-telemetry readout --format json
skill-telemetry usage --format json
```

These commands don't discover or import evidence. They only inspect the two
stores selected by your environment.

## Clean up

Remove the tutorial state only if you no longer need it:

```bash
rm -rf "$SKILL_TELEMETRY_STATE_DIR" "$SKILL_TELEMETRY_USAGE_STATE_DIR"
```

The command is intentionally manual because uninstalling the package preserves
telemetry state. Next, choose a collection path from the
[documentation index](../README.md): explicit Pi/Codex ingest, the Claude hook,
the Pi extension, or OTLP receiver integration.
