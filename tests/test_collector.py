from __future__ import annotations

from pathlib import Path

from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord

from skill_telemetry.collector import normalize_record
from skill_telemetry.store import EventStore


def _claude_record(span: bytes) -> LogRecord:
    return LogRecord(
        event_name="claude_code.skill_activated",
        trace_id=b"t" * 16,
        span_id=span,
        time_unix_nano=1_700_000_000_000_000_000,
        attributes=[
            KeyValue(key="session.id", value=AnyValue(string_value="session")),
            KeyValue(key="prompt.id", value=AnyValue(string_value="turn")),
            KeyValue(key="skill_name", value=AnyValue(string_value="example-capture")),
        ],
    )


def test_native_claude_records_use_transport_occurrence_for_repeat_and_replay(
    tmp_path: Path,
) -> None:
    first = normalize_record(_claude_record(b"a" * 8), {"service.name": "claude-code"})
    second = normalize_record(_claude_record(b"b" * 8), {"service.name": "claude-code"})
    replay = normalize_record(_claude_record(b"a" * 8), {"service.name": "claude-code"})
    assert first.activation_id != second.activation_id
    store = EventStore(tmp_path / "state")
    assert store.append_many((first, second, replay)) == (True, True, False)
