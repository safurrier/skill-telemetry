from __future__ import annotations

import os
from pathlib import Path

from pytest import MonkeyPatch

import skill_telemetry.claude_hooks as hooks
from skill_telemetry.store import EventStore


def test_inventory_empty_root_is_empty(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    assert hooks.installed_skill_inventory((root.resolve(),)) == {}


def test_inventory_reads_only_a_bounded_byte_prefix(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = root / "example-capture" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    # A character-count reader would consume twice the cap and see this name.
    skill.write_bytes(
        b"\xc3\xa9" * hooks.MAX_FRONTMATTER_BYTES + b"\nname: example-capture\n"
    )
    assert hooks._frontmatter_name(skill) is None


def test_inventory_accepts_an_exact_file_cap_and_rejects_an_oversized_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = tmp_path / "skills"
    exact = root / "exact" / "SKILL.md"
    oversized = root / "oversized" / "SKILL.md"
    exact.parent.mkdir(parents=True)
    oversized.parent.mkdir(parents=True)
    monkeypatch.setattr(hooks, "MAX_FRONTMATTER_BYTES", 32)
    exact.write_bytes(b"---\nname: exact\n---\n" + b"#" * 12)
    oversized.write_bytes(b"---\nname: oversized\n---\n" + b"#" * 32)
    assert exact.stat().st_size == hooks.MAX_FRONTMATTER_BYTES
    assert hooks._frontmatter_name(exact) == "exact"
    assert hooks._frontmatter_name(oversized) is None


def test_inventory_never_blocks_on_a_fifo_or_reads_nonregular_file(
    tmp_path: Path,
) -> None:
    fifo = tmp_path / "SKILL.md"
    os.mkfifo(fifo)
    assert hooks._frontmatter_name(fifo) is None


def test_inventory_rejects_a_file_mutated_during_hashing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: changing\n---\n")
    original_read = hooks.os.read
    changed = False

    def mutate_after_read(fd: int, size: int) -> bytes:
        nonlocal changed
        chunk = original_read(fd, size)
        if chunk and not changed:
            changed = True
            metadata = skill.stat()
            os.utime(skill, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000))
        return chunk

    monkeypatch.setattr(hooks.os, "read", mutate_after_read)
    assert hooks._frontmatter_name(skill) is None


def test_inventory_rejects_a_file_replaced_between_snapshot_and_open(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    skill = tmp_path / "SKILL.md"
    replacement = tmp_path / "replacement"
    skill.write_text("---\nname: original\n---\n")
    replacement.write_text("---\nname: replacement\n---\n")
    snapshot = skill.lstat()
    original_open = hooks.os.open
    replaced = False

    def replace_before_open(
        path: object, flags: int, *args: object, **kwargs: object
    ) -> int:
        nonlocal replaced
        if not replaced and Path(path) == skill:
            replaced = True
            os.replace(replacement, skill)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(hooks.os, "open", replace_before_open)
    assert hooks._frontmatter_name_with_size(skill, snapshot) == (None, 0)


def test_inventory_reads_explicit_root_and_ignores_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = root / "example-capture" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: example-capture\n---\n")
    linked = root / "linked"
    linked.symlink_to(skill.parent, target_is_directory=True)
    inventory = hooks.installed_skill_inventory((root.resolve(),))
    assert inventory["example-capture"] == "example-capture"


def test_inventory_stops_content_free_on_deep_or_wide_roots(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = tmp_path / "skills"
    deep = root
    for index in range(3):
        deep = deep / f"level-{index}"
    deep.mkdir(parents=True)
    (deep / "SKILL.md").write_text("---\nname: example-capture\n---\n")
    monkeypatch.setattr(hooks, "MAX_INVENTORY_DEPTH", 1)
    assert hooks.installed_skill_inventory((root.resolve(),)) == {}

    monkeypatch.setattr(hooks, "MAX_INVENTORY_DEPTH", 16)
    monkeypatch.setattr(hooks, "MAX_INVENTORY_DIRECTORIES", 1)
    assert hooks.installed_skill_inventory((root.resolve(),)) == {}


def test_inventory_fails_closed_on_single_huge_directory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    for index in range(3):
        (root / f"file-{index}").write_text("x")
    monkeypatch.setattr(hooks, "MAX_INVENTORY_FILES", 2)
    assert hooks.installed_skill_inventory((root.resolve(),)) == {}


def test_inventory_ignores_malformed_or_unreadable_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    malformed = root / "malformed" / "SKILL.md"
    malformed.parent.mkdir(parents=True)
    malformed.write_bytes(b"\xff\xfe")
    inventory = hooks.installed_skill_inventory((root.resolve(),))
    assert inventory["malformed"] == "malformed"
    assert "\ufffd" not in str(inventory)


def test_hook_activation_replay_dedupes_by_prompt_or_tool_occurrence(
    tmp_path: Path,
) -> None:
    inventory = {"example-capture": "example-capture"}
    explicit = {
        "hook_event_name": "UserPromptExpansion",
        "session_id": "session",
        "prompt_id": "prompt-1",
        "command_name": "/example-capture",
        "command_source": "project",
    }
    tool = {
        "hook_event_name": "PreToolUse",
        "session_id": "session",
        "prompt_id": "prompt-1",
        "tool_use_id": "tool-1",
        "tool_name": "Skill",
        "tool_input": {"skill": "example-capture"},
    }
    events = [
        hooks.normalize_claude_hook(explicit, inventory),
        hooks.normalize_claude_hook(tool, inventory),
        hooks.normalize_claude_hook(tool, inventory),
    ]
    assert all(event is not None for event in events)
    store = EventStore(tmp_path / "state")
    assert store.append_many([event for event in events if event is not None]) == (
        True,
        True,
        False,
    )
