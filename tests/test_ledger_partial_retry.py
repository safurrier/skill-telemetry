# ruff: noqa
"""Bounded at-least-once ledger behavior shared by both retained stores."""

from __future__ import annotations

import errno
import json
import os
import stat
import threading
from pathlib import Path

import pytest

import skill_telemetry.ledger as ledger_module
from skill_telemetry.ledger import MAX_FILE_INDEX, JsonlLedger, LedgerSpec
from skill_telemetry.store import EventStore
from skill_telemetry.usage_store import UsageStore
from skill_telemetry.contract import SkillEvent
from skill_telemetry.usage_contract import TokenUsagePoint


def _event(identifier: str) -> SkillEvent:
    return SkillEvent.from_mapping(
        {
            "schema_version": 1,
            "event_name": "agent.skill.activation",
            "agent_system": "pi",
            "activation_id": f"sha256:{identifier:0>64}",
            "skill_name": "sample-skill",
            "trigger": "explicit-command",
            "evidence_type": "explicit-command",
            "evidence_confidence": "observed",
            "status": "loaded",
            "timestamp": "2026-01-01T00:00:00Z",
            "signal_name": "pi.skill.activation",
        }
    )


def _point(identifier: int) -> TokenUsagePoint:
    return TokenUsagePoint(
        schema_version=1,
        metric_name="codex.turn.token_usage",
        metric_kind="histogram",
        aggregation_temporality="delta",
        unit="",
        token_type="total",
        start_time_unix_nano=identifier,
        time_unix_nano=identifier + 1,
        count=1,
        sum=1.0,
        bucket_counts=(1,),
        explicit_bounds=(),
    )


@pytest.mark.parametrize(
    ("store_type", "items", "reader"),
    [
        (EventStore, (_event("a"), _event("b")), "read_events"),
        (UsageStore, (_point(100), _point(101)), "read_points"),
    ],
)
def test_write_failure_leaves_a_visible_prefix_and_retry_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_type: type[EventStore] | type[UsageStore],
    items: tuple[object, object],
    reader: str,
) -> None:
    store = store_type(tmp_path / "state", max_bytes=2_000, max_files=2)
    original_write = ledger_module.os.write
    calls = 0

    def fail_second_record(fd: int, content: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            return original_write(fd, memoryview(content)[:1])  # type: ignore[arg-type]
        if calls == 3:
            raise OSError(errno.EIO, "injected")
        return original_write(fd, content)  # type: ignore[arg-type]

    monkeypatch.setattr(ledger_module.os, "write", fail_second_record)
    with pytest.raises(ValueError, match="retry may suppress a durable prefix"):
        store.append_many(items)  # type: ignore[arg-type]
    monkeypatch.setattr(ledger_module.os, "write", original_write)

    assert getattr(store, reader)() == (items[0],)
    assert store.append_many(items) == (False, True)  # type: ignore[arg-type]
    assert getattr(store, reader)() == items


def _unique_items(
    store_type: type[EventStore] | type[UsageStore],
) -> tuple[object, ...]:
    if store_type is EventStore:
        return tuple(_event(f"{index:x}") for index in range(16))
    return tuple(_point(200 + index) for index in range(16))


def _encoded_line_size(store: EventStore | UsageStore, item: object) -> int:
    payload = store._ledger.spec.encode(item)  # type: ignore[arg-type]
    return len(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _path_items(store: EventStore | UsageStore, path: Path) -> tuple[object, ...]:
    return tuple(
        store._ledger.spec.decode(json.loads(line))
        for line in path.read_text().splitlines()
    )


def _fail_replacement_open(original_open: object) -> object:
    def fail_replacement_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes], *args: object
    ) -> int:
        if (
            os.fspath(path).endswith(("events.jsonl", "usage.jsonl"))
            and args[0] & os.O_APPEND
        ):
            raise OSError(errno.EIO, "injected")
        return original_open(path, *args)  # type: ignore[operator,arg-type]

    return fail_replacement_open


@pytest.mark.parametrize(
    ("store_type", "reader"), [(EventStore, "read_events"), (UsageStore, "read_points")]
)
def test_max_files_one_rotation_failure_prunes_prior_record_and_retry_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_type: type[EventStore] | type[UsageStore],
    reader: str,
) -> None:
    store = store_type(tmp_path / "state", max_bytes=1_024, max_files=1)
    items = _unique_items(store_type)
    next_index = 0
    while not store.current_path.exists() or (
        store.current_path.stat().st_size + _encoded_line_size(store, items[next_index])
        <= store.max_bytes
    ):
        assert store.append(items[next_index])  # type: ignore[arg-type]
        next_index += 1
    replacement = items[next_index]
    original_open = ledger_module.os.open
    monkeypatch.setattr(ledger_module.os, "open", _fail_replacement_open(original_open))
    with pytest.raises(ValueError, match="retry may suppress a durable prefix"):
        store.append(replacement)  # type: ignore[arg-type]
    monkeypatch.setattr(ledger_module.os, "open", original_open)

    # Rotation starts by pruning the only segment. The failed replacement is absent.
    assert getattr(store, reader)() == ()
    assert store.append(replacement) is True  # type: ignore[arg-type]
    restarted = store_type(tmp_path / "state", max_bytes=1_024, max_files=1)
    assert getattr(restarted, reader)() == (replacement,)


@pytest.mark.parametrize(
    ("store_type", "reader"), [(EventStore, "read_events"), (UsageStore, "read_points")]
)
def test_full_window_rotation_failure_prunes_only_oldest_and_retry_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_type: type[EventStore] | type[UsageStore],
    reader: str,
) -> None:
    store = store_type(tmp_path / "state", max_bytes=1_024, max_files=2)
    items = _unique_items(store_type)
    next_index = 0
    while len(store.retained_paths()) < 2:
        assert store.append(items[next_index])  # type: ignore[arg-type]
        next_index += 1
    while (
        store.current_path.stat().st_size + _encoded_line_size(store, items[next_index])
        <= store.max_bytes
    ):
        assert store.append(items[next_index])  # type: ignore[arg-type]
        next_index += 1
    replacement = items[next_index]
    newer_retained = _path_items(store, store.current_path)
    original_open = ledger_module.os.open
    monkeypatch.setattr(ledger_module.os, "open", _fail_replacement_open(original_open))
    with pytest.raises(ValueError, match="retry may suppress a durable prefix"):
        store.append(replacement)  # type: ignore[arg-type]
    monkeypatch.setattr(ledger_module.os, "open", original_open)

    # Rotation prunes the oldest segment first; the newer retained segment survives.
    assert getattr(store, reader)() == newer_retained
    assert store.append(replacement) is True  # type: ignore[arg-type]
    restarted = store_type(tmp_path / "state", max_bytes=1_024, max_files=2)
    assert getattr(restarted, reader)() == newer_retained + (replacement,)


def test_full_retention_window_reserves_directory_capacity_for_lock(
    tmp_path: Path,
) -> None:
    store = EventStore(tmp_path / "state", max_files=MAX_FILE_INDEX)
    store.ensure_private()
    lock = store.directory / ".store.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    for index in range(MAX_FILE_INDEX):
        suffix = "" if index == 0 else f".{index}"
        retained = store.directory / f"events{suffix}.jsonl"
        retained.write_bytes(b"")
        retained.chmod(0o600)

    assert len(store.retained_paths()) == MAX_FILE_INDEX


def test_private_nonblocking_lock_rejects_fifo_and_foreign_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = EventStore(tmp_path / "state")
    store.ensure_private()
    lock = store.directory / ".store.lock"
    os.mkfifo(lock, 0o600)
    with pytest.raises(ValueError, match="lock is not a regular file"):
        store.read_events()
    lock.unlink()
    lock.write_bytes(b"")
    lock.chmod(0o600)
    original_fstat = ledger_module.os.fstat

    def foreign_owner(fd: int) -> os.stat_result:
        metadata = original_fstat(fd)
        values = list(metadata)
        values[stat.ST_UID] = metadata.st_uid + 1
        return os.stat_result(values)

    monkeypatch.setattr(ledger_module.os, "fstat", foreign_owner)
    with pytest.raises(ValueError, match="lock is not owner-only"):
        store.read_events()


def test_bounded_preparation_stops_before_unbounded_consumption(tmp_path: Path) -> None:
    ledger = JsonlLedger(
        LedgerSpec[int, int](
            directory=tmp_path / "state",
            file_prefix="records",
            lock_name=".records.lock",
            max_bytes=1_000,
            max_files=1,
            max_batch_records=2,
            encode=lambda value: {"value": value},
            decode=lambda value: int(value["value"]),
            fingerprint=lambda value: value,
        )
    )
    consumed = 0

    def values() -> object:
        nonlocal consumed
        for value in range(10):
            consumed += 1
            yield value

    with pytest.raises(ValueError, match="max_records"):
        ledger.append_many(values())  # type: ignore[arg-type]
    assert consumed == 3
    assert not (tmp_path / "state").exists()


def test_deep_corrupt_owner_local_json_is_wrapped_as_ledger_error(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    corrupt = state / "events.jsonl"
    corrupt.write_text("[" * 2_000 + "]" * 2_000 + "\n")
    corrupt.chmod(0o600)

    with pytest.raises(ValueError, match="corrupt skill telemetry event store"):
        EventStore(state).read_events()


def test_concurrent_writers_dedupe_under_one_exclusive_lock(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "state")
    event = _event("e")
    results: list[bool] = []
    result_lock = threading.Lock()

    def append_once() -> None:
        result = store.append(event)
        with result_lock:
            results.append(result)

    workers = [threading.Thread(target=append_once) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert results.count(True) == 1
    assert results.count(False) == 3
    assert store.read_events() == (event,)
