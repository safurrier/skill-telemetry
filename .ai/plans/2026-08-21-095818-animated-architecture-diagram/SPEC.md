---
id: plan-spec
title: Task Specification
description: Requirements and constraints for the animated architecture diagram.
---

# Specification—animated-architecture-diagram

## Problem

The architecture is documented in prose and text flow, but readers lack an editable
visual that reveals collection, evidence separation, persistence, and read surfaces.

## Requirements

### MUST

- Preserve the current architecture and evidence-domain boundaries.
- Keep packaged evaluation separate from live/local collection.
- Deliver editable source, static SVG, inline animation, controlled playback, and video.
- Embed the diagram in README and architecture docs with descriptive alt text.
- Show a static completed state when the viewer requests reduced motion.
- Keep generated playback self-contained and free of private build paths.
- Validate desktop and narrow layouts, controls, and completed output.

### SHOULD

- Use a restrained paper-and-ink palette and hand-drawn Excalidraw style.
- Keep generated binary assets below 1 MiB each.
- Record pinned generation tools and update guidance beside the assets.

## Constraints

- GitHub Markdown cannot embed controlled video, so use GIF for inline playback and
  retain MP4/HTML links plus SVG fallback.
- Do not add a runtime web dependency or alter product code.
- Do not imply that aggregate metrics or packaged evaluation are live activations.
