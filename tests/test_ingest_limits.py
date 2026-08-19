# ruff: noqa
"""Security boundaries for bounded explicit ingestion."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest
import skill_telemetry.ingest as ingest_module
from skill_telemetry.ingest import (
    IngestError,
    IngestLimits,
    _expanded_path,
    _open_checked,
    _read_source,
    discover_inputs,
    ingest_codex,
    ingest_pi,
)
from skill_telemetry.store import EventStore


def _event(index: int = 0) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_name": "agent.skill.activation",
        "agent_system": "pi",
        "session_id": f"sha256:{index:064x}",
        "turn_id": f"sha256:{index + 1:064x}",
        "activation_id": f"sha256:{index + 2:064x}",
        "skill_name": "limit-test",
        "skill_source": "pi-provenance",
        "trigger": "explicit-command",
        "evidence_type": "explicit-command",
        "evidence_confidence": "observed",
        "status": "loaded",
        "timestamp": "2026-08-01T00:00:00Z",
    }


def _pi_line(index: int = 0) -> str:
    return json.dumps(
        {"type": "custom", "customType": "skill-telemetry-v1", "data": _event(index)}
    )


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        (IngestLimits(max_files=1), "max-files"),
        (IngestLimits(max_file_bytes=8), "max-file-bytes"),
        (IngestLimits(max_total_bytes=80), "max-total-bytes"),
        (IngestLimits(max_top_level_records=1), "max-top-level-records"),
    ],
)
def test_pi_limits_are_content_free_and_all_or_nothing(
    tmp_path: Path, limits: IngestLimits, expected: str
) -> None:
    first = tmp_path / "one.jsonl"
    second = tmp_path / "two.jsonl"
    first.write_text(_pi_line() + "\n" + _pi_line(4) + "\n")
    second.write_text(_pi_line(8) + "\n")
    stats = ingest_pi((first, second), EventStore(tmp_path / "state"), limits=limits)
    assert stats.limit_status == expected
    assert stats.imported == 0
    assert not (tmp_path / "state").exists()
    assert str(tmp_path) not in json.dumps(stats.to_dict())
    assert "limit-test" not in json.dumps(stats.to_dict())


def test_repeated_direct_inputs_count_against_traversal_budget(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text(_pi_line())

    stats = ingest_pi(
        (source, source),
        EventStore(tmp_path / "state"),
        limits=IngestLimits(max_traversal_entries=1),
    )

    assert stats.limit_status == "max-traversal-entries"
    assert not (tmp_path / "state").exists()


def test_discovery_charges_duplicate_digest_work_before_full_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated explicit paths cannot cause unbounded full-file discovery hashes."""
    source = tmp_path / "source.jsonl"
    size = 8 * 1024 * 1024
    source.write_bytes(b"x" * size)
    original_digest = ingest_module._digest_fd
    digest_calls = 0

    def count_digest(fd: int, snapshot_size: int) -> str:
        nonlocal digest_calls
        digest_calls += 1
        return original_digest(fd, snapshot_size)

    monkeypatch.setattr(ingest_module, "_digest_fd", count_digest)
    stats = ingest_pi(
        (source,) * 1_000,
        EventStore(tmp_path / "state"),
        limits=IngestLimits(
            max_file_bytes=size,
            max_discovery_bytes=size,
            max_traversal_entries=2_000,
        ),
    )

    assert stats.limit_status == "max-discovery-bytes"
    assert digest_calls == 1
    assert not (tmp_path / "state").exists()


def test_traversal_depth_entries_and_irrelevant_breadth_are_bounded(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    for index in range(3):
        (root / f"irrelevant-{index}.txt").write_text("x")
    nested = root / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "session.jsonl").write_text(_pi_line())
    store = EventStore(tmp_path / "state")
    assert (
        ingest_pi(
            (root,), store, limits=IngestLimits(max_traversal_entries=2)
        ).limit_status
        == "max-traversal-entries"
    )
    assert (
        ingest_pi((root,), store, limits=IngestLimits(max_depth=1)).limit_status
        == "max-depth"
    )
    assert not (tmp_path / "state").exists()


def test_discovery_rejects_root_replacement_before_selecting_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "session.jsonl").write_text(_pi_line())
    original_discover = ingest_module._discover_file

    def swap_root_then_discover(
        path: Path,
        limits: IngestLimits,
        expected: tuple[tuple[int, int], ...] | None = None,
        **kwargs: object,
    ) -> object:
        root.rename(tmp_path / "old-sessions")
        root.mkdir()
        (root / "session.jsonl").write_text(_pi_line(4))
        return original_discover(path, limits, expected, **kwargs)

    monkeypatch.setattr(ingest_module, "_discover_file", swap_root_then_discover)

    with pytest.raises(IngestError, match="unsafe-or-changed-input"):
        discover_inputs((root,))


def test_codex_inventory_limits_and_symlinks_never_append(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"method": "turn/start", "params": {"input": []}}))
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("safe fixture")
    store = EventStore(tmp_path / "state")
    stats = ingest_codex(
        (source,),
        store,
        skills=(("limit-test", skill),),
        limits=IngestLimits(max_codex_skill_file_bytes=2),
    )
    assert stats.limit_status == "max-codex-skill-file-bytes"
    link = tmp_path / "link"
    link.symlink_to(skill, target_is_directory=True)
    with pytest.raises(IngestError):
        ingest_codex((source,), store, skills=(("limit-test", link),))
    assert not (tmp_path / "state").exists()


def test_codex_structured_limit_is_all_or_nothing(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps({"method": "turn/start", "params": {"input": [{"nested": {}}]}})
    )
    stats = ingest_codex(
        (source,),
        EventStore(tmp_path / "state"),
        limits=IngestLimits(max_structured_records=1),
    )
    assert stats.limit_status == "max-structured-records"
    assert not (tmp_path / "state").exists()


def test_tolerated_jsonl_records_count_against_top_level_budget(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text(_pi_line() + "\nnot-json\n")

    stats = ingest_pi(
        (source,),
        EventStore(tmp_path / "state"),
        tolerate_invalid_jsonl=True,
        limits=IngestLimits(max_top_level_records=1),
    )

    assert stats.limit_status == "max-top-level-records"
    assert not (tmp_path / "state").exists()


def test_jsonl_top_level_limit_stops_before_decoding_excess_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text("\n".join(_pi_line(index) for index in range(3)) + "\n")
    original_loads = ingest_module.json.loads
    calls = 0

    def count_loads(value: str, *args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(ingest_module.json, "loads", count_loads)

    stats = ingest_pi(
        (source,),
        EventStore(tmp_path / "state"),
        limits=IngestLimits(max_top_level_records=2),
    )

    assert stats.limit_status == "max-top-level-records"
    assert calls == 2
    assert not (tmp_path / "state").exists()


def test_json_top_level_array_limit_stops_before_excess_element(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps([{"method": "turn/start", "params": {}} for _ in range(3)])
    )

    stats = ingest_codex(
        (source,),
        EventStore(tmp_path / "state"),
        limits=IngestLimits(max_top_level_records=2),
    )

    assert stats.limit_status == "max-top-level-records"
    assert not (tmp_path / "state").exists()


def test_codex_structured_limit_is_aggregate_across_documents(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text(
        "\n".join(
            json.dumps({"method": "turn/start", "params": {"input": []}})
            for _ in range(2)
        )
        + "\n"
    )

    stats = ingest_codex(
        (source,),
        EventStore(tmp_path / "state"),
        limits=IngestLimits(max_structured_records=3),
    )

    assert stats.limit_status == "max-structured-records"
    assert not (tmp_path / "state").exists()


def test_discovery_keeps_no_selected_file_descriptors(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text(_pi_line())
    before = len(os.listdir("/dev/fd"))
    stats = ingest_pi((source,), EventStore(tmp_path / "state"))
    after = len(os.listdir("/dev/fd"))
    assert stats.imported == 1
    assert after <= before + 1


def test_leaf_and_root_replacement_after_discovery_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    leaf = root / "session.jsonl"
    leaf.write_text(_pi_line())
    selected = discover_inputs((root,))
    leaf.unlink()
    leaf.write_text(_pi_line(4))
    with pytest.raises(IngestError):
        _read_source(selected[0], IngestLimits(), tolerate_trailing_utf8=False)

    selected = discover_inputs((root,))
    old_root = tmp_path / "old-sessions"
    root.rename(old_root)
    root.mkdir()
    (root / "session.jsonl").write_text(_pi_line(8))
    with pytest.raises(IngestError):
        _read_source(selected[0], IngestLimits(), tolerate_trailing_utf8=False)


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("Darwin", "/private/tmp/example.jsonl"),
        ("Darwin", "/private/var/example.jsonl"),
        ("Linux", "/tmp/example.jsonl"),
        ("Linux", "/var/example.jsonl"),
    ],
)
def test_platform_temporary_root_policy_is_not_cross_platform(
    monkeypatch: pytest.MonkeyPatch, system: str, expected: str
) -> None:
    monkeypatch.setattr(ingest_module.platform, "system", lambda: system)
    source = "/var/example.jsonl" if "/var/" in expected else "/tmp/example.jsonl"
    assert _expanded_path(Path(source)) == Path(expected)


def test_fifo_and_nonregular_leaf_races_are_nonblocking_and_close_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "session.jsonl"
    source.write_text(_pi_line())
    original_open = ingest_module.os.open
    replaced = False

    def replace_leaf(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal replaced
        if path == source.name and not replaced:
            replaced = True
            source.unlink()
            os.mkfifo(source)
        return original_open(path, flags, *args, **kwargs)

    before = len(os.listdir("/dev/fd"))
    monkeypatch.setattr(ingest_module.os, "open", replace_leaf)
    with pytest.raises(IngestError, match="unsafe-or-changed-input"):
        _open_checked(source, directory=False, limits=IngestLimits())
    after = len(os.listdir("/dev/fd"))
    assert after <= before + 1
    source.unlink()
    source.mkdir()
    with pytest.raises(IngestError, match="unsafe-or-changed-input"):
        _open_checked(source, directory=False, limits=IngestLimits())


def test_device_leaf_replacement_is_rejected_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "session.jsonl"
    source.write_text(_pi_line())
    original_open = ingest_module.os.open

    def replace_leaf_with_device(
        path: object, flags: int, *args: object, **kwargs: object
    ) -> int:
        if path == source.name:
            return original_open("/dev/null", os.O_RDONLY | os.O_NONBLOCK)
        return original_open(path, flags, *args, **kwargs)

    before = len(os.listdir("/dev/fd"))
    monkeypatch.setattr(ingest_module.os, "open", replace_leaf_with_device)
    with pytest.raises(IngestError, match="unsafe-or-changed-input"):
        _open_checked(source, directory=False, limits=IngestLimits())
    after = len(os.listdir("/dev/fd"))
    assert after <= before + 1


def test_directory_discovery_closes_scan_descriptors_on_a_broad_tree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    for index in range(30):
        directory = root / f"nested-{index}"
        directory.mkdir()
        (directory / "session.jsonl").write_text(_pi_line(index))
    before = len(os.listdir("/dev/fd"))
    stats = ingest_pi(
        (root,), EventStore(tmp_path / "state"), limits=IngestLimits(max_files=64)
    )
    after = len(os.listdir("/dev/fd"))
    assert stats.imported == 30
    assert after <= before + 1


def test_intermediate_direct_and_inventory_parent_replacement_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    middle = root / "middle"
    middle.mkdir(parents=True)
    leaf = middle / "session.jsonl"
    leaf.write_text(_pi_line())
    selected = discover_inputs((root,))
    middle.rename(root / "old-middle")
    middle.mkdir()
    (middle / "session.jsonl").write_text(_pi_line(1))
    with pytest.raises(IngestError, match="unsafe-or-changed-input"):
        _read_source(selected[0], IngestLimits(), tolerate_trailing_utf8=False)

    direct = tmp_path / "direct"
    direct.mkdir()
    direct_leaf = direct / "session.jsonl"
    direct_leaf.write_text(_pi_line(2))
    selected = discover_inputs((direct_leaf,))
    direct.rename(tmp_path / "old-direct")
    direct.mkdir()
    (direct / "session.jsonl").write_text(_pi_line(3))
    with pytest.raises(IngestError, match="unsafe-or-changed-input"):
        _read_source(selected[0], IngestLimits(), tolerate_trailing_utf8=False)

    source = tmp_path / "app.json"
    source.write_text(json.dumps({"method": "turn/start", "params": {}}))
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("safe")
    original_discover = ingest_module._discover_file

    def replace_inventory(
        path: Path, limits: IngestLimits, expected: object = None, **kwargs: object
    ) -> object:
        found = original_discover(path, limits, expected, **kwargs)
        if path.name == "SKILL.md":
            skill.rename(tmp_path / "old-skill")
            skill.mkdir()
            (skill / "SKILL.md").write_text("replacement")
        return found

    monkeypatch.setattr(ingest_module, "_discover_file", replace_inventory)
    with pytest.raises(IngestError, match="unsafe-or-changed-input"):
        ingest_codex(
            (source,), EventStore(tmp_path / "state"), skills=(("safe", skill),)
        )


def test_json_preflight_bounds_nodes_depth_and_strings_before_materialization(
    tmp_path: Path,
) -> None:
    deep: object = {"value": "ok"}
    for _ in range(8):
        deep = {"nested": deep}
    source = tmp_path / "deep.json"
    source.write_text(json.dumps(deep))
    assert (
        ingest_codex(
            (source,),
            EventStore(tmp_path / "state"),
            limits=IngestLimits(max_json_depth=4),
        ).limit_status
        == "max-json-depth"
    )
    source.write_text(json.dumps({"method": "turn/start", "blob": "x" * 64}))
    assert (
        ingest_codex(
            (source,),
            EventStore(tmp_path / "state"),
            limits=IngestLimits(max_json_string_bytes=8),
        ).limit_status
        == "max-json-string-bytes"
    )


def test_emfile_is_mapped_to_a_content_free_descriptor_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text(_pi_line())

    def exhausted(*args: object, **kwargs: object) -> int:
        raise OSError(errno.EMFILE, "injected")

    monkeypatch.setattr(ingest_module.os, "open", exhausted)
    stats = ingest_pi((source,), EventStore(tmp_path / "state"))
    assert stats.limit_status == "max-live-descriptors"
    assert not (tmp_path / "state").exists()
