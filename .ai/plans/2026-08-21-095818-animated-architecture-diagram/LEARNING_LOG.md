---
id: plan-learning-log
title: Learning Log
description: Observations from diagram generation and validation.
---

# Learning log—animated-architecture-diagram

- The topology reads best as two swimlanes: packaged contract evaluation and local
  evidence flow. Combining them suggests that evaluation probes a live runtime.
- Functional color works better than per-runtime color because Pi, Claude, Codex,
  and OTLP converge through shared normalization and storage seams.
- Excalidraw element count makes default playback about 28 seconds. A 2× video/GIF
  encode keeps inline playback under 15 seconds while HTML retains user controls.
- GitHub Markdown needs GIF for inline motion. A `<picture>` source gives reduced-
  motion readers the completed static SVG.
- Scene-embedded SVG keeps the editable Excalidraw payload beside a smaller static
  rendering, while the standalone `.excalidraw` remains the clear source of truth.
