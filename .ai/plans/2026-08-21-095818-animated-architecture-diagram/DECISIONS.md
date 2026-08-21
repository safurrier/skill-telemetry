---
id: plan-decisions
title: Decision Notes
description: Visual and delivery decisions for the architecture diagram.
---

# Decisions—animated-architecture-diagram

## What Changed

- Added an editable Excalidraw system map and static/animated exports.
- Embedded the animation in README and architecture docs with reduced-motion fallback.
- Added tests for scene content, embedded source, playback controls, offline use, binary shape, and doc embeds.

## Why

- A two-lane paper-and-ink map shows the live local evidence flow without merging it
  with the separate packaged evaluator. Color communicates input, normalization,
  retained state, and read surfaces.

## Where Reflected

- `README.md`
- `docs/explanation/architecture.md`
- `docs/assets/architecture/`
- `tests/test_architecture_assets.py`

## Promotion

- No new product or architecture decision. The visual restates current documented design.
