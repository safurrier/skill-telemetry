"""Content-safe Claude hook normalization and installed-skill qualification."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from skill_telemetry.contract import SkillEvent
from skill_telemetry.privacy import pseudonym, safe_name

MAX_HOOK_BYTES = 256 * 1024
MAX_INVENTORY_FILES = 20_000
MAX_INVENTORY_DIRECTORIES = 4_096
MAX_INVENTORY_DEPTH = 16
MAX_FRONTMATTER_BYTES = 4_096
MAX_INVENTORY_PREFIX_BYTES = 2 * 1024 * 1024
FRONTMATTER_NAME_RE = re.compile(r"(?m)^name:\s*['\"]?([^'\"\s]+)['\"]?\s*$")
COMMAND_NAME_RE = re.compile(
    r"^/?([A-Za-z0-9][A-Za-z0-9._+-]{0,127})(?::([A-Za-z0-9][A-Za-z0-9._+-]{0,127}))?$"
)
TRIGGER_MAP = {
    "user-slash": "explicit",
    "claude-proactive": "proactive",
    "nested-skill": "nested",
}


def default_skill_roots() -> tuple[Path, ...]:
    """Return only caller-declared inventory roots; never probe home directories."""
    configured = os.environ.get("SKILL_TELEMETRY_SKILL_ROOTS", "")
    return tuple(
        Path(value).expanduser() for value in configured.split(os.pathsep) if value
    )


def _same_opened_file(before: os.stat_result, after: os.stat_result) -> bool:
    """Compare only stable identity and bounded-read metadata."""
    return (
        before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and stat.S_IFMT(before.st_mode) == stat.S_IFMT(after.st_mode)
        and before.st_uid == after.st_uid
        and before.st_size == after.st_size
    )


def _frontmatter_name_with_size(
    path: Path, before: os.stat_result | None = None
) -> tuple[str | None, int]:
    """Read and hash one verified bounded regular file without retaining content."""
    try:
        snapshot = path.lstat() if before is None else before
        if (
            not stat.S_ISREG(snapshot.st_mode)
            or snapshot.st_size > MAX_FRONTMATTER_BYTES
        ):
            return None, 0
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None, 0
    try:
        opened = os.fstat(fd)
        if not _same_opened_file(snapshot, opened):
            return None, 0
        remaining = opened.st_size
        chunks: list[bytes] = []
        digest = hashlib.sha256()
        while remaining:
            chunk = os.read(fd, min(remaining, 64 * 1024))
            if not chunk:
                return None, 0
            digest.update(chunk)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            return None, 0
        after = os.fstat(fd)
        if (
            not _same_opened_file(opened, after)
            or opened.st_mtime_ns != after.st_mtime_ns
        ):
            return None, 0
        prefix = b"".join(chunks)
    except OSError:
        return None, 0
    finally:
        os.close(fd)
    try:
        text = prefix.decode("utf-8")
    except UnicodeDecodeError:
        return None, len(prefix)
    match = FRONTMATTER_NAME_RE.search(text)
    return (safe_name(match.group(1)) if match else None), len(prefix)


def _frontmatter_name(path: Path) -> str | None:
    """Read one bounded prefix for callers that do not need budget accounting."""
    return _frontmatter_name_with_size(path)[0]


def _path_aliases(path: Path, canonical: str) -> tuple[str, ...]:
    aliases = {canonical, path.parent.name}
    parts = path.parts
    try:
        skills_index = len(parts) - 1 - tuple(reversed(parts)).index("skills")
    except ValueError:
        skills_index = -1
    if skills_index > 0 and skills_index + 1 < len(parts):
        skill_directory = safe_name(parts[skills_index + 1])
        plugin_candidates = parts[max(0, skills_index - 2) : skills_index]
        for candidate in plugin_candidates:
            plugin = safe_name(candidate)
            if (
                plugin
                and skill_directory
                and plugin not in {".claude", ".agents", "plugins"}
            ):
                aliases.add(f"{plugin}:{skill_directory}")
    return tuple(alias for alias in aliases if COMMAND_NAME_RE.fullmatch(alias))


def installed_skill_inventory(roots: Iterable[Path] | None = None) -> dict[str, str]:
    """Scan only explicit roots incrementally, returning no inventory on any cap breach."""
    inventory: dict[str, str] = {}
    selected_roots = default_skill_roots() if roots is None else roots
    entries = directories = scanned_files = prefix_bytes = 0
    pending: list[tuple[Path, int]] = []
    for root in selected_roots:
        try:
            root.lstat()
        except OSError:
            continue
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            continue
        directories += 1
        if directories > MAX_INVENTORY_DIRECTORIES:
            return {}
        pending.append((root, 0))

    while pending:
        directory, depth = pending.pop()
        if depth > MAX_INVENTORY_DEPTH:
            return {}
        try:
            with os.scandir(directory) as children:
                for child in children:
                    entries += 1
                    if entries > MAX_INVENTORY_FILES + MAX_INVENTORY_DIRECTORIES:
                        return {}
                    try:
                        if child.is_symlink():
                            continue
                        if child.is_dir(follow_symlinks=False):
                            directories += 1
                            if directories > MAX_INVENTORY_DIRECTORIES:
                                return {}
                            if depth >= MAX_INVENTORY_DEPTH:
                                return {}
                            pending.append((Path(child.path), depth + 1))
                            continue
                        if not child.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    scanned_files += 1
                    if scanned_files > MAX_INVENTORY_FILES:
                        return {}
                    if child.name != "SKILL.md":
                        continue
                    skill_path = Path(child.path)
                    try:
                        snapshot = child.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    canonical, consumed = _frontmatter_name_with_size(
                        skill_path, snapshot
                    )
                    prefix_bytes += consumed
                    if prefix_bytes > MAX_INVENTORY_PREFIX_BYTES:
                        return {}
                    directory_name = safe_name(skill_path.parent.name)
                    canonical = canonical or directory_name
                    if canonical is None:
                        continue
                    for alias in _path_aliases(skill_path, canonical):
                        inventory.setdefault(alias.casefold(), canonical)
        except OSError:
            continue
    return inventory


def canonical_skill_name(value: object, inventory: dict[str, str]) -> str | None:
    """Resolve one direct or structured hook name against installed inventory."""
    if not isinstance(value, str):
        return None
    match = COMMAND_NAME_RE.fullmatch(value.strip())
    if match is None:
        return None
    alias = ":".join(segment for segment in match.groups() if segment)
    return inventory.get(alias.casefold())


def map_invocation_trigger(value: object, *, default: str) -> str:
    """Map Claude-native trigger labels into runtime-neutral bounded tokens."""
    if isinstance(value, str):
        mapped = TRIGGER_MAP.get(value)
        if mapped is not None:
            return mapped
    return default


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _hook_timestamp(payload: dict[str, object]) -> str:
    value = payload.get("timestamp")
    return value if isinstance(value, str) else datetime.now(UTC).isoformat()


def _hook_event(
    payload: dict[str, object],
    *,
    hook_event: str,
    skill_name: str,
    skill_source: str,
    trigger: str,
    evidence_type: str,
    occurrence: object,
) -> SkillEvent:
    session_id = pseudonym(payload.get("session_id"), namespace="claude-session")
    prompt_id = pseudonym(payload.get("prompt_id"), namespace="claude-prompt")
    occurrence_id = pseudonym(
        "|".join(
            (
                hook_event,
                session_id or "",
                prompt_id or "",
                skill_name,
                str(occurrence) if occurrence is not None else "",
            )
        ),
        namespace="claude-hook-occurrence",
    )
    return SkillEvent.from_mapping(
        {
            "schema_version": 1,
            "event_name": "agent.skill.activation",
            "agent_system": "claude",
            "session_id": session_id,
            "turn_id": prompt_id,
            "activation_id": occurrence_id,
            "skill_name": skill_name,
            "skill_source": skill_source,
            "trigger": trigger,
            "evidence_type": evidence_type,
            "evidence_confidence": "observed",
            "status": "loaded",
            "timestamp": _hook_timestamp(payload),
            "signal_name": f"claude_code.hook.{hook_event.lower()}",
        }
    )


def normalize_claude_hook(
    payload: dict[str, object], inventory: dict[str, str]
) -> SkillEvent | None:
    """Normalize only supported Claude hooks and discard every content-bearing field."""
    hook_event = payload.get("hook_event_name")
    if hook_event == "UserPromptExpansion":
        if not all(
            _nonempty_string(payload.get(name)) for name in ("session_id", "prompt_id")
        ):
            return None
        skill_name = canonical_skill_name(payload.get("command_name"), inventory)
        command_source = safe_name(payload.get("command_source"))
        if skill_name is None or command_source is None:
            return None
        return _hook_event(
            payload,
            hook_event=cast(str, hook_event),
            skill_name=skill_name,
            skill_source=command_source,
            trigger=map_invocation_trigger(
                payload.get("invocation_trigger"), default="explicit"
            ),
            evidence_type="explicit-command",
            occurrence=payload.get("prompt_id"),
        )
    if hook_event == "PreToolUse":
        if not all(
            _nonempty_string(payload.get(name))
            for name in ("session_id", "prompt_id", "tool_use_id")
        ):
            return None
        tool_name = payload.get("tool_name")
        tool_input_value = payload.get("tool_input")
        if tool_name != "Skill" or not isinstance(tool_input_value, dict):
            return None
        tool_input = cast(dict[str, object], tool_input_value)
        skill_name = canonical_skill_name(tool_input.get("skill"), inventory)
        if skill_name is None:
            return None
        return _hook_event(
            payload,
            hook_event=cast(str, hook_event),
            skill_name=skill_name,
            skill_source="claude-skill-tool",
            trigger=map_invocation_trigger(
                tool_input.get("invocation_trigger", payload.get("invocation_trigger")),
                default="proactive",
            ),
            evidence_type="structured-hook",
            occurrence=payload.get("tool_use_id"),
        )
    return None
