"""Markdown parsing helpers for plan-contract checks."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import CHECKLIST_PREFIX, PLACEHOLDER_VALUES
from .models import MarkdownSection


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + 5 :]


def parse_sections(path: Path) -> list[MarkdownSection]:
    text = strip_frontmatter(path.read_text()) if path.exists() else ""
    sections: list[MarkdownSection] = []
    matches = list(re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE))
    if not matches:
        return sections

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(
            MarkdownSection(
                heading=match.group(2).strip(),
                level=len(match.group(1)),
                content=text[start:end].strip(),
            )
        )
    return sections


def find_section(path: Path, heading: str, *, level: int = 2) -> MarkdownSection | None:
    target = heading.lower()
    for section in parse_sections(path):
        if section.level == level and section.heading.lower() == target:
            return section
    return None


def normalize_value(value: str) -> str:
    return value.strip().strip("`").strip()


def strip_checklist_prefix(value: str) -> str:
    return CHECKLIST_PREFIX.sub("", value, count=1).strip()


def is_placeholder_value(value: str) -> bool:
    normalized = normalize_value(value).lower()
    return normalized in PLACEHOLDER_VALUES


def checklist_has_meaningful_items(path: Path) -> bool:
    if not path.exists():
        return False

    for raw_line in strip_frontmatter(path.read_text()).splitlines():
        stripped = raw_line.strip()
        match = re.match(r"^- \[[ xX]\]\s+(.+)$", stripped)
        if not match:
            continue
        item = normalize_value(match.group(1))
        if not is_placeholder_value(item):
            return True
    return False


def file_has_meaningful_content(path: Path) -> bool:
    if not path.exists():
        return False

    for raw_line in strip_frontmatter(path.read_text()).splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        if stripped.startswith("- "):
            bullet = normalize_value(stripped[2:])
            if is_placeholder_value(bullet) or is_placeholder_value(
                strip_checklist_prefix(bullet)
            ):
                continue
            return True
        if not is_placeholder_value(stripped):
            return True
    return False


def section_bullets(path: Path, heading: str) -> list[str]:
    section = find_section(path, heading)
    if section is None:
        return []
    bullets: list[str] = []
    for line in section.content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(normalize_value(stripped[2:]))
    return bullets


def section_has_meaningful_bullets(path: Path, heading: str) -> bool:
    return any(
        not is_placeholder_value(value) for value in section_bullets(path, heading)
    )


def keyed_bullets(path: Path, heading: str) -> dict[str, str]:
    section = find_section(path, heading)
    if section is None:
        return {}
    values: dict[str, str] = {}
    for line in section.content.splitlines():
        stripped = line.strip()
        match = re.match(r"^-\s+([^:]+):\s*(.+)$", stripped)
        if match:
            values[match.group(1).strip().lower()] = normalize_value(match.group(2))
    return values


def extract_paths_from_bullets(path: Path, heading: str) -> list[str]:
    values = section_bullets(path, heading)
    extracted: list[str] = []
    for value in values:
        inline = re.findall(r"`([^`]+)`", value)
        if inline:
            extracted.extend(inline)
            continue
        candidate = re.split(r"\s+[—-]\s+", value, maxsplit=1)[0].strip()
        if candidate:
            extracted.append(candidate)
    return extracted
