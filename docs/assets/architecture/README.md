---
id: skill-telemetry-architecture-assets
title: Architecture diagram assets
description: Editable source, static fallback, and animated exports for the skill-telemetry architecture map.
index:
  - id: files
    keywords: [excalidraw, svg, gif, mp4, html]
  - id: update
    keywords: [render, animation, source, regenerate]
---

# Architecture diagram assets

`skill-telemetry-architecture.excalidraw` is the editable source of truth. The
other files are generated views:

| File | Use |
| --- | --- |
| `skill-telemetry-architecture.svg` | Static, scene-embedded fallback for GitHub and reduced motion |
| `skill-telemetry-architecture-animation.gif` | Inline GitHub animation |
| `skill-telemetry-architecture-animation.mp4` | Sharper playback artifact with native controls when opened directly |
| `skill-telemetry-architecture-animated.html` | Self-contained interactive playback with replay, pause, and play controls |

The diagram uses `@swiftlysingh/excalidraw-cli` 1.2.0 for the editable scene and
static SVG, `excalidraw-animate` 0.7.2 for element-order playback, Playwright with
a Chromium browser for capture, and FFmpeg for MP4/GIF encoding.

## Update the diagram

1. Edit the `.excalidraw` scene. Keep the two swimlanes, color meanings, and
   evidence-domain separation aligned with `docs/explanation/architecture.md`.
2. Export the static SVG with embedded scene data:

   ```bash
   npx --yes @swiftlysingh/excalidraw-cli@1.2.0 convert \
     skill-telemetry-architecture.excalidraw \
     --format svg --embed-scene --export-background \
     --background-color '#fffaf4' --padding 24 \
     --output skill-telemetry-architecture.svg
   ```

3. Render animated HTML and diagram-only MP4 with the `explain-excalidraw`
   renderer scripts. Supply their installed paths explicitly:

   ```bash
   uvx --with playwright python "$RENDER_EXCALIDRAW" \
     skill-telemetry-architecture.excalidraw \
     skill-telemetry-architecture-animated.html \
     --title "skill-telemetry architecture" --animate \
     --browser-executable "$CHROME"

   uv run python ../../../scripts/postprocess_architecture_exports.py \
     --svg skill-telemetry-architecture.svg \
     --html skill-telemetry-architecture-animated.html

   PATH="$(dirname "$FFMPEG"):$PATH" uvx --with playwright python \
     "$RENDER_EXCALIDRAW_VIDEO" \
     skill-telemetry-architecture-animated.html \
     skill-telemetry-architecture-animation.mp4 \
     --browser-executable "$CHROME" --hold-seconds 2
   ```

4. Accelerate the MP4 and build the GitHub GIF with a completed poster frame:

   ```bash
   "$FFMPEG" -y -i skill-telemetry-architecture-animation.mp4 \
     -vf 'setpts=0.45*PTS' -an -c:v libx264 -pix_fmt yuv420p \
     -movflags +faststart architecture-fast.mp4
   mv architecture-fast.mp4 skill-telemetry-architecture-animation.mp4

   "$FFMPEG" -y -sseof -0.1 \
     -i skill-telemetry-architecture-animation.mp4 \
     -frames:v 1 architecture-complete.png

   "$FFMPEG" -y -loop 1 -t 1 -i architecture-complete.png \
     -i skill-telemetry-architecture-animation.mp4 \
     -filter_complex '[0:v]fps=12[poster];[1:v]fps=12[anim];[poster][anim]concat=n=2:v=1:a=0,scale=1200:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle' \
     -loop 0 skill-telemetry-architecture-animation.gif
   ```

   The result is an approximately 16.6-second MP4 and a GIF that starts with one
   second of the completed scene. Keep both files below 1 MiB.
5. Inspect the first and final frames, test HTML playback controls and status,
   open the editable scene, and check wide, narrow, reduced-motion, and dark-mode
   browser layouts.

`RENDER_EXCALIDRAW`, `RENDER_EXCALIDRAW_VIDEO`, `CHROME`, and `FFMPEG` are local
build-tool paths, not runtime dependencies. Generated assets must not contain
those paths or require a network request when viewed.
