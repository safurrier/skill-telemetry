# ruff: noqa
"""Live-source snapshot, digest, parser-budget, and descriptor-cap regression tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import skill_telemetry.ingest as ingest_module
from skill_telemetry.ingest import (
    IngestError,
    IngestLimits,
    _read_source,
    discover_inputs,
    ingest_pi,
)
from skill_telemetry.store import EventStore
from tests.test_ingest_limits import _pi_line


def test_jsonl_reads_discovered_snapshot_and_ignores_later_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "live.jsonl"
    source.write_text(_pi_line() + "\n")
    original_open = ingest_module._open_source

    def append_after_open(selected: object, limits: IngestLimits) -> int:
        fd = original_open(selected, limits)  # type: ignore[arg-type]
        with source.open("a") as stream:
            stream.write("not-a-snapshot\n")
        return fd

    monkeypatch.setattr(ingest_module, "_open_source", append_after_open)
    stats = ingest_pi((source,), EventStore(tmp_path / "state"))
    assert stats.imported == 1
    assert stats.records_scanned == 1


def test_same_inode_same_size_mutation_is_rejected_by_discovery_digest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text(_pi_line() + "\n")
    selected = discover_inputs((source,))
    before = source.read_bytes()
    replacement = b" " + before[1:]
    assert len(replacement) == len(before)
    source.write_bytes(replacement)
    with pytest.raises(IngestError, match="unsafe-or-changed-input"):
        _read_source(selected[0], IngestLimits(), tolerate_trailing_utf8=False)


def test_tolerated_malformed_jsonl_charges_parser_work_across_lines(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    expensive = '{"a":[1,2,3,4,5,6,7,8,9,10}'
    source.write_text(expensive + "\n" + expensive + "\n")
    stats = ingest_pi(
        (source,),
        EventStore(tmp_path / "state"),
        tolerate_invalid_jsonl=True,
        limits=IngestLimits(max_structured_records=20),
    )
    assert stats.limit_status == "max-structured-records"
    assert not (tmp_path / "state").exists()


def test_jsonl_line_cap_is_checked_before_unterminated_line_materialization(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_bytes(b"{" + b"x" * 4096)
    stats = ingest_pi(
        (source,),
        EventStore(tmp_path / "state"),
        tolerate_invalid_jsonl=True,
        limits=IngestLimits(max_jsonl_line_bytes=128),
    )
    assert stats.limit_status == "max-jsonl-line-bytes"


def test_directory_scan_reservation_observes_four_fd_peak_and_blocks_at_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "source.jsonl").write_text(_pi_line())
    original_limit = ingest_module._descriptor_limit
    requested: list[int] = []

    def observe_limit(limits: IngestLimits, needed: int) -> None:
        requested.append(needed)
        original_limit(limits, needed)

    monkeypatch.setattr(ingest_module, "_descriptor_limit", observe_limit)
    stats = ingest_pi(
        (root,),
        EventStore(tmp_path / "state"),
        limits=IngestLimits(max_live_descriptors=3),
    )
    assert stats.limit_status == "max-live-descriptors"
    # The scanner's directory and scandir descriptors are reserved while the
    # component-relative leaf walk requests two more; the operation is stopped
    # before a fourth descriptor is opened.
    assert max(requested) == 4
    assert not (tmp_path / "state").exists()


@pytest.mark.skipif(os.name == "nt", reason="RLIMIT_NOFILE is a Unix contract")
def test_low_rlimit_descriptor_exhaustion_is_content_free_in_a_subprocess(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text(_pi_line())
    script = """
import os
import resource
import sys
from pathlib import Path
from skill_telemetry.ingest import ingest_pi
from skill_telemetry.store import EventStore
source = Path(sys.argv[1])
state = Path(sys.argv[2])
open_fds = len(os.listdir('/dev/fd'))
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (min(soft, open_fds), hard))
stats = ingest_pi((source,), EventStore(state))
print(stats.limit_status)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(source), str(tmp_path / "state")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "max-live-descriptors"


def test_codex_directory_replacement_before_child_discovery_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "app.json"
    source.write_text(json.dumps({"method": "turn/start", "params": {}}))
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("original")
    original_checked = ingest_module._open_checked

    def replace_before_open(path: Path, **kwargs: object) -> object:
        if path == skill and kwargs.get("directory"):
            skill.rename(tmp_path / "old-skill")
            skill.mkdir()
            (skill / "SKILL.md").write_text("replacement")
        return original_checked(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest_module, "_open_checked", replace_before_open)
    with pytest.raises(IngestError, match="unsafe-or-changed-input"):
        ingest_module.ingest_codex(
            (source,), EventStore(tmp_path / "state"), skills=(("safe", skill),)
        )
