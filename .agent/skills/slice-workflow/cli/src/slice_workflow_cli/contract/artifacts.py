"""Artifact and validation evidence helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import COMMAND_PATTERN
from .markdown import strip_frontmatter
from .models import ArtifactEntry


def parse_artifact_manifest(path: Path) -> list[ArtifactEntry]:
    if not path.exists():
        return []

    entries: list[ArtifactEntry] = []
    current: dict[str, str] | None = None
    in_artifacts = False

    for raw_line in path.read_text().splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        if raw_line.strip() == "artifacts:":
            in_artifacts = True
            continue
        if not in_artifacts:
            continue

        if raw_line.startswith("  - "):
            if current is not None:
                entries.append(
                    ArtifactEntry(
                        type=current.get("type", ""),
                        path=current.get("path", ""),
                        note=current.get("note", ""),
                    )
                )
            current = {}
            key_value = raw_line[4:].strip()
            if ":" in key_value:
                key, value = key_value.split(":", 1)
                current[key.strip()] = value.strip()
            continue

        if current is not None and raw_line.startswith("    ") and ":" in raw_line:
            key, value = raw_line.strip().split(":", 1)
            current[key.strip()] = value.strip()

    if current is not None:
        entries.append(
            ArtifactEntry(
                type=current.get("type", ""),
                path=current.get("path", ""),
                note=current.get("note", ""),
            )
        )

    return entries


def validation_has_commands(path: Path) -> bool:
    if not path.exists():
        return False
    text = strip_frontmatter(path.read_text())

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        inline = re.findall(r"`([^`]+)`", stripped)
        if any(COMMAND_PATTERN.search(candidate) for candidate in inline):
            return True

    for block in re.findall(r"```[a-zA-Z0-9_-]*\n(.*?)```", text, flags=re.DOTALL):
        for raw_line in block.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("$ "):
                stripped = stripped[2:].strip()
            if COMMAND_PATTERN.search(stripped):
                return True
    return False


def resolve_plan_artifact_path(plan_dir: Path, artifact_path: str) -> Path | None:
    candidate = (plan_dir / artifact_path).resolve()
    plan_root = plan_dir.resolve()
    if candidate == plan_root or plan_root in candidate.parents:
        return candidate
    return None
