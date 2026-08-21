"""Add accessibility and narrow-view behavior to generated architecture exports."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

TITLE = "skill-telemetry architecture"
DESCRIPTION = (
    "Two-lane architecture map. Packaged campaigns flow only through the Python "
    "evaluator to a JSON report. In the local lane, Pi lifecycle events pass through "
    "Pi matching into retained custom session entries, then explicit ingest. Selected "
    "Pi and Codex files also enter explicit ingest, while Claude hook input uses a "
    "privacy adapter. OTLP logs use the skill logs adapter. OTLP metrics split between "
    "a skill metric adapter and a token usage adapter. Skill evidence keeps stages "
    "separate before the skill ledger and readout. Token usage uses its own ledger and "
    "readout."
)


def accessible_svg(source: str, *, prefix: str) -> str:
    """Add one title and description to the first SVG root."""
    if f'id="{prefix}-title"' in source:
        return source
    match = re.search(r"<svg\b[^>]*>", source)
    if match is None:
        raise ValueError("generated export has no SVG root")
    root = match.group(0)[:-1]
    root += (
        f' role="img" aria-labelledby="{prefix}-title {prefix}-description">'
        f'<title id="{prefix}-title">{html.escape(TITLE)}</title>'
        f'<desc id="{prefix}-description">{html.escape(DESCRIPTION)}</desc>'
    )
    return source[: match.start()] + root + source[match.end() :]


def postprocess_svg(path: Path) -> None:
    path.write_text(accessible_svg(path.read_text(), prefix="architecture-svg"))


def postprocess_html(path: Path) -> None:
    source = path.read_text()
    if 'id="architecture-player-title"' in source:
        path.write_text("\n".join(line.rstrip() for line in source.splitlines()) + "\n")
        return
    source = source.replace(
        "    * { box-sizing: border-box; }",
        """    * { box-sizing: border-box; }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    .narrow-hint { display: none; color: var(--muted); font: 0.72rem/1.4 Menlo, Consolas, monospace; }""",
    )
    source = source.replace(
        ".diagram-wrap svg { width: 100%; height: auto; min-width: 480px; display: block; }",
        ".diagram-wrap svg { width: 100%; height: auto; min-width: 960px; display: block; }",
    )
    source = source.replace(
        "      .diagram-wrap { margin-inline: calc(-1 * clamp(20px, 4vw, 56px)); width: auto; }",
        """      .diagram-wrap { margin-inline: calc(-1 * clamp(20px, 4vw, 56px)); width: auto; }
      .diagram-wrap svg { min-width: 900px; }
      .narrow-hint { display: block; }""",
    )
    source = source.replace("<h1>", '<h1 id="architecture-heading">', 1)
    source = source.replace(
        '    <section class="diagram-wrap" aria-label="skill-telemetry architecture" data-excalidraw-diagram>',
        """    <p class="narrow-hint">Scroll horizontally to inspect the completed diagram at a readable size.</p>
    <section class="diagram-wrap" aria-label="Animated architecture player" data-excalidraw-diagram>""",
    )
    start = source.index("<svg", source.index("data-excalidraw-diagram"))
    end = source.index("</svg>", start) + len("</svg>")
    source = (
        source[:start]
        + accessible_svg(source[start:end], prefix="architecture-player")
        + source[end:]
    )
    source = re.sub(
        r"<span>([0-9.]+s sequence)</span>",
        r'<span role="status" aria-live="polite" data-playback-status>Ready · \1</span>',
        source,
        count=1,
    )
    source = source.replace(
        '    const controls = embed?.querySelector(".animation-controls");',
        """    const controls = embed?.querySelector(".animation-controls");
    const playbackStatus = embed?.querySelector("[data-playback-status]");
    let completionTimer;
    const scheduleCompletion = () => {
      clearTimeout(completionTimer);
      const remainingSeconds = Math.max(0, durationSeconds - svg.getCurrentTime());
      if (remainingSeconds === 0) {
        if (playbackStatus) playbackStatus.textContent = "Completed";
        return;
      }
      if (playbackStatus) playbackStatus.textContent = "Playing";
      completionTimer = setTimeout(() => {
        if (playbackStatus) playbackStatus.textContent = "Completed";
      }, remainingSeconds * 1000);
    };""",
    )
    source = source.replace(
        """      if (action === "replay") {
        svg.setCurrentTime(0);
        svg.unpauseAnimations();
      } else if (action === "pause") {
        svg.pauseAnimations();
      } else if (action === "play") {
        svg.unpauseAnimations();
      }""",
        """      if (action === "replay") {
        svg.setCurrentTime(0);
        svg.unpauseAnimations();
        scheduleCompletion();
      } else if (action === "pause") {
        svg.pauseAnimations();
        clearTimeout(completionTimer);
        if (playbackStatus) playbackStatus.textContent = "Paused";
      } else if (action === "play") {
        svg.unpauseAnimations();
        scheduleCompletion();
      }""",
    )
    source = source.replace(
        """    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches && svg) {
      svg.pauseAnimations();
      svg.setCurrentTime(durationSeconds);
    }""",
        """    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches && svg) {
      svg.pauseAnimations();
      svg.setCurrentTime(durationSeconds);
      if (playbackStatus) playbackStatus.textContent = "Completed · reduced motion";
    } else if (svg) {
      scheduleCompletion();
    }""",
    )
    path.write_text("\n".join(line.rstrip() for line in source.splitlines()) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    args = parser.parse_args()
    postprocess_svg(args.svg)
    postprocess_html(args.html)


if __name__ == "__main__":
    main()
