# ruff: noqa
from __future__ import annotations

from pathlib import Path

import skill_telemetry.claude_hooks as hooks


def test_malformed_utf8_prefixes_consume_aggregate_budget(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "skills"
    for index in range(3):
        skill = root / f"sample-{index}" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(b"\xff" * 8)
    monkeypatch.setattr(hooks, "MAX_FRONTMATTER_BYTES", 8)
    monkeypatch.setattr(hooks, "MAX_INVENTORY_PREFIX_BYTES", 16)
    assert hooks._frontmatter_name_with_size(root / "sample-0" / "SKILL.md") == (
        None,
        8,
    )
    assert hooks.installed_skill_inventory((root.resolve(),)) == {}


def test_inventory_accepts_safe_frontmatter_after_malformed_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    bad = root / "bad" / "SKILL.md"
    good = root / "good" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    good.parent.mkdir(parents=True)
    bad.write_bytes(b"\xff")
    good.write_text("---\nname: sample-skill\n---\n")
    inventory = hooks.installed_skill_inventory((root.resolve(),))
    assert inventory["bad"] == "bad"
    assert inventory["sample-skill"] == "sample-skill"
