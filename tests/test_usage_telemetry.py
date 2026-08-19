# ruff: noqa
from __future__ import annotations

import errno
import json
import stat
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from email.message import Message
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, ArrayValue, KeyValue
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    AGGREGATION_TEMPORALITY_CUMULATIVE,
    AGGREGATION_TEMPORALITY_DELTA,
    Histogram,
    HistogramDataPoint,
    Metric,
    NumberDataPoint,
    ResourceMetrics,
    ScopeMetrics,
    Sum,
)
from opentelemetry.proto.resource.v1.resource_pb2 import Resource

import skill_telemetry.ledger as ledger_module
from skill_telemetry.collector import CollectorServer
from skill_telemetry.store import EventStore
from skill_telemetry.usage import build_usage_readout, normalize_token_usage_metric
from skill_telemetry.usage_contract import (
    CODEX_TOKEN_USAGE_METRIC,
    TOKEN_UNITS,
    TokenUsagePoint,
    UsageContractError,
)
from skill_telemetry.usage_store import (
    DEFAULT_USAGE_MAX_BYTES,
    DEFAULT_USAGE_MAX_FILES,
    UsageStore,
    UsageStoreError,
)

INVALID_USAGE_CASES = json.loads(
    (Path(__file__).parent / "fixtures/token-usage-invalid-v1.json").read_text()
)


class FailingEventStore(EventStore):
    def append_many(self, events: object) -> tuple[bool, ...]:
        _ = events
        raise OSError("synthetic skill store failure")


class FailingUsageStore(UsageStore):
    def append_many(self, points: object) -> tuple[bool, ...]:
        _ = points
        raise OSError("synthetic usage store failure")


def usage_metric(
    *,
    token_type: str = "total",
    name: str = CODEX_TOKEN_USAGE_METRIC,
    unit: str = "",
    temporality: int = AGGREGATION_TEMPORALITY_CUMULATIVE,
    time_unix_nano: int = 1_750_000_000_000_000_000,
    count: int = 3,
    total: float = 42.5,
    bucket_counts: tuple[int, ...] = (1, 2, 0),
    explicit_bounds: tuple[float, ...] = (10.0, 100.0),
    extra_attributes: list[KeyValue] | None = None,
) -> Metric:
    return Metric(
        name=name,
        unit=unit,
        histogram=Histogram(
            aggregation_temporality=temporality,
            data_points=[
                HistogramDataPoint(
                    attributes=[
                        KeyValue(
                            key="token_type", value=AnyValue(string_value=token_type)
                        ),
                        *(extra_attributes or []),
                    ],
                    start_time_unix_nano=time_unix_nano - 10_000,
                    time_unix_nano=time_unix_nano,
                    count=count,
                    sum=total,
                    bucket_counts=bucket_counts,
                    explicit_bounds=explicit_bounds,
                )
            ],
        ),
    )


def skill_metric(
    *, skill: str = "session" + "-capture", timestamp: int = 1_750_000_000_000_000_000
) -> Metric:
    return Metric(
        name="codex.skill.injected",
        sum=Sum(
            aggregation_temporality=AGGREGATION_TEMPORALITY_DELTA,
            is_monotonic=True,
            data_points=[
                NumberDataPoint(
                    attributes=[
                        KeyValue(key="skill", value=AnyValue(string_value=skill)),
                        KeyValue(key="status", value=AnyValue(string_value="success")),
                        KeyValue(
                            key="invoke_type", value=AnyValue(string_value="explicit")
                        ),
                    ],
                    start_time_unix_nano=timestamp - 1_000,
                    time_unix_nano=timestamp,
                    as_int=1,
                )
            ],
        ),
    )


def usage_envelope(*metrics: Metric, prohibited_resource: bool = False) -> bytes:
    resource_attributes = []
    if prohibited_resource:
        resource_attributes = [
            KeyValue(
                key="repository.path",
                value=AnyValue(string_value="/private/repository"),
            ),
            KeyValue(
                key="prompt", value=AnyValue(string_value="PROHIBITED RAW PROMPT")
            ),
            KeyValue(key="credential", value=AnyValue(string_value="sk-proj-PRIVATE")),
        ]
    return ExportMetricsServiceRequest(
        resource_metrics=[
            ResourceMetrics(
                resource=Resource(attributes=resource_attributes),
                scope_metrics=[ScopeMetrics(metrics=list(metrics))],
            )
        ]
    ).SerializeToString()


def post(url: str, payload: bytes) -> tuple[int, Message]:
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-protobuf"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
        response.read()
        return response.status, response.headers


def point(
    *,
    token_type: str = "total",
    timestamp: int = 100,
    total: float = 12,
    unit: str = "",
    temporality: str = "cumulative",
    start_time: int | None = None,
    bucket_counts: tuple[int, ...] = (1, 1),
    explicit_bounds: tuple[float, ...] = (10.0,),
) -> TokenUsagePoint:
    return TokenUsagePoint(
        schema_version=1,
        metric_name=CODEX_TOKEN_USAGE_METRIC,
        metric_kind="histogram",
        aggregation_temporality=temporality,
        unit=unit,
        token_type=token_type,
        start_time_unix_nano=timestamp - 1 if start_time is None else start_time,
        time_unix_nano=timestamp,
        count=sum(bucket_counts),
        sum=total,
        bucket_counts=bucket_counts,
        explicit_bounds=explicit_bounds,
    )


def run_server(
    event_store: EventStore, usage_store: UsageStore
) -> tuple[CollectorServer, threading.Thread, str]:
    server = CollectorServer(("127.0.0.1", 0), event_store, usage_store=usage_store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}/v1/metrics"


def stop_server(server: CollectorServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.mark.parametrize("unit", sorted(TOKEN_UNITS))
def test_usage_unit_allowlist_preserves_source(unit: str) -> None:
    normalized = normalize_token_usage_metric(usage_metric(unit=unit))

    assert len(normalized) == 1
    assert normalized[0].unit == unit


@pytest.mark.parametrize("case", INVALID_USAGE_CASES, ids=lambda case: str(case["id"]))
def test_invalid_case_corpus_is_rejected_by_runtime(case: dict[str, object]) -> None:
    payload = point().to_dict()
    payload.update(case["patch"])

    with pytest.raises(UsageContractError):
        TokenUsagePoint.from_mapping(payload)


def test_histogram_contract_preserves_official_metric_fidelity() -> None:
    points = normalize_token_usage_metric(usage_metric(token_type="reasoning_output"))

    assert len(points) == 1
    assert points[0].to_dict() == {
        "schema_version": 1,
        "metric_name": "codex.turn.token_usage",
        "metric_kind": "histogram",
        "aggregation_temporality": "cumulative",
        "unit": "",
        "token_type": "reasoning_output",
        "start_time_unix_nano": 1_749_999_999_999_990_000,
        "time_unix_nano": 1_750_000_000_000_000_000,
        "count": 3,
        "sum": 42.5,
        "bucket_counts": [1, 2, 0],
        "explicit_bounds": [10.0, 100.0],
    }


@pytest.mark.parametrize(
    "token_type", ["input", "cached_input", "output", "reasoning_output", "total"]
)
def test_token_type_allowlist_accepts_documented_values(token_type: str) -> None:
    assert len(normalize_token_usage_metric(usage_metric(token_type=token_type))) == 1


def test_unknown_string_token_type_is_excluded_directly() -> None:
    assert (
        normalize_token_usage_metric(usage_metric(token_type="private-model-name"))
        == ()
    )


def test_unknown_unit_is_malformed_before_token_type_filtering() -> None:
    with pytest.raises(UsageContractError, match="unsupported usage unit"):
        normalize_token_usage_metric(
            usage_metric(unit="sk-proj-PRIVATE123", token_type="private-model-name")
        )


@pytest.mark.parametrize(
    "metric",
    [
        usage_metric(name="codex.turn.other"),
        usage_metric(
            extra_attributes=[
                KeyValue(key="token_type", value=AnyValue(string_value="total"))
            ]
        ),
        usage_metric(token_type="total"),
    ],
)
def test_unknown_metrics_and_non_scalar_or_duplicate_token_type_are_ignored(
    metric: Metric,
) -> None:
    if metric.name == CODEX_TOKEN_USAGE_METRIC:
        attributes = metric.histogram.data_points[0].attributes
        if len([item for item in attributes if item.key == "token_type"]) == 1:
            attributes[0].value.CopyFrom(
                AnyValue(
                    array_value=ArrayValue(values=[AnyValue(string_value="total")])
                )
            )
    assert normalize_token_usage_metric(metric) == ()


def test_synthetic_otlp_receiver_path_drops_all_non_allowlisted_content(
    private_state: Path, tmp_path: Path
) -> None:
    usage_directory = tmp_path / "usage-state"
    server, thread, url = run_server(EventStore(), UsageStore(usage_directory))
    try:
        metric = usage_metric(
            extra_attributes=[
                KeyValue(
                    key="model", value=AnyValue(string_value="PRIVATE-MODEL-SENTINEL")
                ),
                KeyValue(
                    key="session.id", value=AnyValue(string_value="PRIVATE-SESSION")
                ),
                KeyValue(
                    key="command", value=AnyValue(string_value="PROHIBITED COMMAND")
                ),
                KeyValue(
                    key="tool.output", value=AnyValue(string_value="PROHIBITED TOOL IO")
                ),
            ]
        )
        assert post(url, usage_envelope(metric, prohibited_resource=True))[0] == 200
    finally:
        stop_server(server, thread)

    retained = "\n".join(path.read_text() for path in usage_directory.glob("*.jsonl"))
    assert "codex.turn.token_usage" in retained
    for sentinel in (
        "PRIVATE",
        "PROHIBITED",
        "/private/",
        "command",
        "tool.output",
        "repository.path",
        "model",
        "session.id",
    ):
        assert sentinel not in retained
    assert not list(private_state.glob("usage*.jsonl"))


def test_malformed_histogram_is_400_and_preflight_prevents_both_writes(
    private_state: Path, tmp_path: Path
) -> None:
    usage_directory = tmp_path / "usage"
    malformed = usage_metric()
    malformed.histogram.data_points[0].bucket_counts[:] = [3]
    server, thread, url = run_server(EventStore(), UsageStore(usage_directory))
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            post(url, usage_envelope(skill_metric(), malformed))
        assert error.value.code == 400
    finally:
        stop_server(server, thread)
    assert not private_state.exists()
    assert not usage_directory.exists()


def test_first_store_failure_returns_retryable_503_then_retry_commits_once(
    private_state: Path, tmp_path: Path
) -> None:
    usage_directory = tmp_path / "usage"
    payload = usage_envelope(skill_metric(), usage_metric())
    server, thread, url = run_server(
        FailingEventStore(private_state), UsageStore(usage_directory)
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            post(url, payload)
        assert error.value.code == 503
    finally:
        stop_server(server, thread)
    assert not usage_directory.exists()

    server, thread, url = run_server(
        EventStore(private_state), UsageStore(usage_directory)
    )
    try:
        status, headers = post(url, payload)
    finally:
        stop_server(server, thread)
    assert status == 200
    assert headers["X-Skill-Telemetry-Accepted"] == "1"
    assert headers["X-Usage-Telemetry-Accepted"] == "1"
    assert len(EventStore(private_state).read_events()) == 1
    assert len(UsageStore(usage_directory).read_points()) == 1


def test_real_first_domain_prefix_failure_returns_503_and_retry_completes_both_domains(
    private_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage_directory = tmp_path / "usage"
    payload = usage_envelope(
        skill_metric(skill="session" + "-capture"),
        skill_metric(skill="skill-creator", timestamp=1_750_000_000_000_000_001),
        usage_metric(),
    )
    original_write = ledger_module.os.write
    calls = 0

    def fail_second_skill_record(fd: int, content: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            return original_write(fd, memoryview(content)[:1])  # type: ignore[arg-type]
        if calls == 3:
            raise OSError(errno.EIO, "injected")
        return original_write(fd, content)  # type: ignore[arg-type]

    monkeypatch.setattr(ledger_module.os, "write", fail_second_skill_record)
    server, thread, url = run_server(
        EventStore(private_state), UsageStore(usage_directory)
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            post(url, payload)
        assert error.value.code == 503
    finally:
        stop_server(server, thread)
    monkeypatch.setattr(ledger_module.os, "write", original_write)

    # The first domain has a visible prefix; usage did not start after its failure.
    assert len(EventStore(private_state).read_events()) == 1
    assert not usage_directory.exists()

    server, thread, url = run_server(
        EventStore(private_state), UsageStore(usage_directory)
    )
    try:
        status, headers = post(url, payload)
    finally:
        stop_server(server, thread)
    assert status == 200
    assert headers["X-Skill-Telemetry-Accepted"] == "1"
    assert headers["X-Usage-Telemetry-Accepted"] == "1"
    assert len(EventStore(private_state).read_events()) == 2
    assert len(UsageStore(usage_directory).read_points()) == 1


def test_second_store_failure_is_partial_but_retry_dedupes_first_commit(
    private_state: Path, tmp_path: Path
) -> None:
    usage_directory = tmp_path / "usage"
    payload = usage_envelope(skill_metric(), usage_metric())
    server, thread, url = run_server(
        EventStore(private_state), FailingUsageStore(usage_directory)
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            post(url, payload)
        assert error.value.code == 503
    finally:
        stop_server(server, thread)
    assert len(EventStore(private_state).read_events()) == 1
    assert not usage_directory.exists()

    server, thread, url = run_server(
        EventStore(private_state), UsageStore(usage_directory)
    )
    try:
        status, headers = post(url, payload)
    finally:
        stop_server(server, thread)
    assert status == 200
    assert headers["X-Skill-Telemetry-Accepted"] == "0"
    assert headers["X-Usage-Telemetry-Accepted"] == "1"
    assert len(EventStore(private_state).read_events()) == 1
    assert len(UsageStore(usage_directory).read_points()) == 1


def test_usage_store_permissions_are_owner_only(tmp_path: Path) -> None:
    store = UsageStore(tmp_path / "usage")
    assert store.append(point())

    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.current_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((store.directory / ".usage-store.lock").stat().st_mode) == 0o600


def test_delta_duplicate_delivery_after_restart_and_rotation_is_not_added_twice(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "usage"
    event_directory = tmp_path / "events"
    store = UsageStore(directory, max_bytes=512, max_files=3)
    payloads = [
        usage_envelope(
            usage_metric(
                temporality=AGGREGATION_TEMPORALITY_DELTA,
                time_unix_nano=100_000 + index,
                total=float(index + 1),
            )
        )
        for index in range(3)
    ]
    server, thread, url = run_server(EventStore(event_directory), store)
    try:
        for payload in payloads:
            assert post(url, payload)[0] == 200
    finally:
        stop_server(server, thread)
    assert len(store.retained_paths()) > 1

    restarted = UsageStore(directory, max_bytes=512, max_files=3)
    server, thread, url = run_server(EventStore(event_directory), restarted)
    try:
        status, headers = post(url, payloads[0])
    finally:
        stop_server(server, thread)
    assert status == 200
    assert headers["X-Usage-Telemetry-Accepted"] == "0"
    assert len(restarted.read_points()) == 3
    groups = build_usage_readout(directory)["histogram_groups"]
    assert groups[0]["sum"] == 6.0
    assert groups[0]["source_points"] == 3


def test_usage_store_wraps_invalid_retained_field_types(tmp_path: Path) -> None:
    store = UsageStore(tmp_path / "usage")
    store.ensure_private()
    invalid = point().to_dict()
    invalid["start_time_unix_nano"] = "not-a-timestamp"
    store.current_path.write_text(json.dumps(invalid) + "\n")
    store.current_path.chmod(0o600)

    with pytest.raises(UsageStoreError, match="corrupt usage store"):
        store.read_points()


def test_usage_retention_is_independent_of_skill_store(
    private_state: Path, tmp_path: Path
) -> None:
    usage_directory = tmp_path / "usage-state"
    usage_store = UsageStore(usage_directory, max_bytes=512, max_files=2)
    for index in range(4):
        assert usage_store.append(point(timestamp=100 + index, total=10 + index))

    EventStore(private_state).ensure_private()
    corrupt = private_state / "events.jsonl"
    corrupt.write_text("PROHIBITED CORRUPT OTHER DOMAIN\n")
    corrupt.chmod(0o600)

    assert len(usage_store.read_points()) == 2
    assert DEFAULT_USAGE_MAX_BYTES > 5 * 1024 * 1024
    assert DEFAULT_USAGE_MAX_FILES > 4
    assert usage_directory != private_state


def test_readout_keeps_latest_cumulative_snapshot_per_stream_epoch(
    tmp_path: Path,
) -> None:
    store = UsageStore(tmp_path / "usage")
    first = point(timestamp=100, total=12, start_time=90)
    later = replace(first, time_unix_nano=101, sum=20)
    other_epoch = point(timestamp=200, total=7, start_time=190)
    store.append_many((first, later, other_epoch))

    readout = build_usage_readout(store.directory)

    assert readout["points"] == 3
    assert readout["summarized_points"] == 2
    assert [group["sum"] for group in readout["histogram_groups"]] == [20.0, 7.0]
    assert "summary_total_tokens" not in readout


def test_readout_adds_only_compatible_delta_shapes(tmp_path: Path) -> None:
    store = UsageStore(tmp_path / "usage")
    store.append_many(
        (
            point(temporality="delta", timestamp=100, total=2),
            point(temporality="delta", timestamp=101, total=3),
            point(
                temporality="delta",
                timestamp=102,
                total=5,
                bucket_counts=(1, 0, 1),
                explicit_bounds=(5.0, 10.0),
            ),
        )
    )

    groups = build_usage_readout(store.directory)["histogram_groups"]

    assert [
        (group["unit"], group["explicit_bounds"], group["sum"]) for group in groups
    ] == [
        ("", [5.0, 10.0], 5.0),
        ("", [10.0], 5.0),
    ]
    assert all(group["aggregation_temporality"] == "delta" for group in groups)


def test_readout_does_not_mix_delta_cumulative_or_unspecified(tmp_path: Path) -> None:
    store = UsageStore(tmp_path / "usage")
    store.append_many(
        (
            point(temporality="delta", timestamp=100, total=2),
            point(temporality="cumulative", timestamp=101, total=3, start_time=90),
            point(temporality="unspecified", timestamp=102, total=100, start_time=0),
        )
    )

    readout = build_usage_readout(store.directory)

    assert len(readout["histogram_groups"]) == 2
    assert {
        group["aggregation_temporality"] for group in readout["histogram_groups"]
    } == {
        "delta",
        "cumulative",
    }
    assert readout["unspecified_temporality_points_excluded"] == 1
    assert "summary_total_tokens" not in readout


def test_safe_native_total_is_present_without_adding_components(
    private_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage_directory = tmp_path / "usage-state"
    monkeypatch.setenv("SKILL_TELEMETRY_USAGE_STATE_DIR", str(usage_directory))
    UsageStore().append_many(
        (
            point(token_type="input", timestamp=101, total=60),
            point(token_type="output", timestamp=102, total=40),
            point(token_type="total", timestamp=103, total=100),
        )
    )

    first = build_usage_readout()
    second = build_usage_readout()
    assert first == second
    assert first["summary_total_tokens"] == 100.0
    assert [group["sum"] for group in first["histogram_groups"]] == [60.0, 40.0, 100.0]
    assert first["dimension_availability"]["cost"] == "unavailable-not-estimated"
    assert not private_state.exists()
