---
id: plan-validation
title: Validation Log
description: Render, browser, test, privacy, and repository evidence.
---

# Validation

## Commands

- `npx --yes @swiftlysingh/excalidraw-cli@1.2.0 create ...` — generated the
  editable 20-node, 18-edge scene before semantic styling and ordering.
- `excalidraw-cli convert ... --embed-scene` — generated the scene-embedded SVG.
- `render_excalidraw.py --animate` — generated self-contained HTML with pinned
  `excalidraw-animate` 0.7.2.
- `postprocess_architecture_exports.py --svg ... --html ...` — added static/player
  descriptions, narrow panning, playback status, and reduced-motion behavior.
- `render_excalidraw_video.py ... --hold-seconds 2` plus documented FFmpeg filters
  — generated a 16.6-second MP4 and 1200×439 GIF with completed poster frame.
- Playwright with system Chrome — Replay/Pause/Play status passed; near-end resume
  reached Completed; reduced motion showed the completed scene; wide, dark, and
  narrow left/right screenshots had no console errors or page overflow.
- `uv run pytest --no-cov tests/test_architecture_assets.py tests/test_docs.py -q`
  — 59 focused cases passed.
- `mise run check` — 493 Python tests at 85.30% coverage, 38 Pi tests, history,
  format, lint, type, package-load, and version checks passed.
- `find_forbidden()` over every architecture asset — passed; no private marker or
  credential-shaped material.
- Source-bound writing checks on README, architecture, and asset guide — normal
  samples remained above FRE 55 and below FK 10.

## Visual evidence

- `artifacts/reduced-motion-complete.png`
- `artifacts/narrow-complete-left.png`
- `artifacts/narrow-complete-right.png`
- `artifacts/dark-complete.png`
- `artifacts/video-final-frame.png`

## Evidence

- Independent semantic review approved endpoint, Pi, evidence-stage, ledger, and
  packaged/live boundaries after one correction round.
- Independent visual/accessibility review approved v3 after color, topology,
  descriptions, narrow panning, poster, status, and reproducibility corrections.
