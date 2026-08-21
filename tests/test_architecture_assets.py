"""Validate editable, static, and animated architecture artifacts."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "docs/assets/architecture"
BASENAME = "skill-telemetry-architecture"


def _scene() -> dict[str, object]:
    return json.loads((ASSETS / f"{BASENAME}.excalidraw").read_text())


def _labeled_shapes(scene: dict[str, object]) -> dict[str, dict[str, object]]:
    elements = scene["elements"]
    assert isinstance(elements, list)
    result: dict[str, dict[str, object]] = {}
    for index, element in enumerate(elements):
        if (
            isinstance(element, dict)
            and element.get("type") == "text"
            and index
            and isinstance(elements[index - 1], dict)
            and elements[index - 1].get("type") in {"rectangle", "ellipse"}
        ):
            result[str(element["text"])] = elements[index - 1]
    return result


def _edges(scene: dict[str, object]) -> set[tuple[str, str]]:
    elements = scene["elements"]
    assert isinstance(elements, list)
    labels_by_shape = {
        str(shape["id"]): label for label, shape in _labeled_shapes(scene).items()
    }
    edges: set[tuple[str, str]] = set()
    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "arrow":
            continue
        start = element.get("startBinding")
        end = element.get("endBinding")
        assert isinstance(start, dict) and isinstance(end, dict)
        edges.add(
            (
                labels_by_shape[str(start["elementId"])],
                labels_by_shape[str(end["elementId"])],
            )
        )
    return edges


def test_architecture_scene_is_editable_and_complete() -> None:
    scene = _scene()

    assert scene["type"] == "excalidraw"
    assert scene["version"] == 2
    assert scene["source"] == "https://github.com/safurrier/skill-telemetry"
    labels = {element.get("text") for element in scene["elements"]}
    assert {
        "Pi lifecycle",
        "Pi extension matching",
        "Pi custom entries",
        "Pi/Codex files",
        "Claude hook stdin",
        "/v1/logs",
        "/v1/metrics",
        "Skill logs adapter",
        "Skill metric adapter",
        "Token usage adapter",
        "Stage-preserving gate",
        "Skill ledger",
        "Usage ledger",
        "readout",
        "usage",
        "Packaged campaigns",
        "Python evaluator",
        "customType: skill-telemetry-v1",
    } <= labels


def test_architecture_edges_preserve_runtime_and_domain_boundaries() -> None:
    edges = _edges(_scene())

    assert {
        ("Pi lifecycle", "Pi extension matching"),
        ("Pi extension matching", "Pi custom entries"),
        ("Pi custom entries", "Explicit ingest"),
        ("/v1/logs", "Skill logs adapter"),
        ("Skill logs adapter", "Stage-preserving gate"),
        ("/v1/metrics", "Skill metric adapter"),
        ("Skill metric adapter", "Stage-preserving gate"),
        ("/v1/metrics", "Token usage adapter"),
        ("Token usage adapter", "Usage ledger"),
        ("Stage-preserving gate", "Skill ledger"),
        ("Packaged campaigns", "Python evaluator"),
        ("Python evaluator", "JSON report"),
    } <= edges
    assert ("/v1/logs", "Token usage adapter") not in edges
    assert not any(
        source == "Packaged campaigns" and target != "Python evaluator"
        for source, target in edges
    )


def test_architecture_colors_match_functional_legend() -> None:
    shapes = _labeled_shapes(_scene())

    for label in (
        "Pi extension matching",
        "Explicit ingest",
        "Privacy adapter",
        "Skill logs adapter",
        "Skill metric adapter",
        "Token usage adapter",
        "Stage-preserving gate",
    ):
        assert shapes[label]["backgroundColor"] == "#d0ebff"
    for label in ("Pi custom entries", "Skill ledger", "Usage ledger"):
        assert shapes[label]["backgroundColor"] == "#d8f5a2"
    for label in ("JSON report", "readout", "usage"):
        assert shapes[label]["backgroundColor"] == "#ffd8a8"


def test_static_svg_embeds_scene_and_accessible_description() -> None:
    svg = (ASSETS / f"{BASENAME}.svg").read_text()

    assert svg.startswith("<svg")
    assert "svg-source:excalidraw" in svg
    assert "application/vnd.excalidraw+json" in svg
    assert 'viewBox="0 0 2098 784"' in svg
    assert 'role="img"' in svg
    assert "architecture-svg-title" in svg
    assert "architecture-svg-description" in svg


def test_animated_html_is_self_contained_responsive_and_accessible() -> None:
    html = (ASSETS / f"{BASENAME}-animated.html").read_text()

    assert 'data-action="replay"' in html
    assert 'data-action="pause"' in html
    assert 'data-action="play"' in html
    assert "data-playback-status" in html
    assert "prefers-reduced-motion: reduce" in html
    assert 'aria-label="Animated architecture player"' in html
    assert 'role="img"' in html
    assert "architecture-player-description" in html
    assert "min-width: 900px" in html
    assert "durationSeconds - svg.getCurrentTime()" in html
    external_urls = set(re.findall(r"https?://[^\"'\s<]+", html))
    assert external_urls <= {"http://www.w3.org/2000/svg"}
    assert not any(marker in html.lower() for marker in ("/users/", "file://"))


def test_inline_animation_and_video_have_expected_shapes() -> None:
    gif = (ASSETS / f"{BASENAME}-animation.gif").read_bytes()
    mp4 = (ASSETS / f"{BASENAME}-animation.mp4").read_bytes()

    assert gif.startswith(b"GIF89a")
    width, height = struct.unpack("<HH", gif[6:10])
    assert (width, height) == (1200, 439)
    assert mp4[4:8] == b"ftyp"
    assert b"mvhd" in mp4[:256]
    assert len(gif) < 1_000_000
    assert len(mp4) < 1_000_000


def test_readme_and_architecture_embed_animation_with_static_fallback() -> None:
    for path in (ROOT / "README.md", ROOT / "docs/explanation/architecture.md"):
        content = path.read_text()
        assert f"{BASENAME}-animation.gif" in content
        assert f"{BASENAME}.svg" in content
        assert f"{BASENAME}.excalidraw" in content
        assert "prefers-reduced-motion: reduce" in content
        assert "/v1/logs" in content
        assert "/v1/metrics" in content
        assert "skill-telemetry-v1" in content
