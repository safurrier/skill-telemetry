# ruff: noqa
from __future__ import annotations

import http.client
import io
import json
import threading
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, ArrayValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord, ResourceLogs, ScopeLogs
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    AGGREGATION_TEMPORALITY_CUMULATIVE,
    AGGREGATION_TEMPORALITY_DELTA,
    Metric,
    NumberDataPoint,
    ResourceMetrics,
    ScopeMetrics,
    Sum,
)
from opentelemetry.proto.resource.v1.resource_pb2 import Resource

from skill_telemetry.cli import main
from skill_telemetry.collector import (
    CollectorServer,
    infer_agent,
    normalize_codex_metric,
    normalize_record,
)
from skill_telemetry.contract import SkillEvent
from skill_telemetry.readout import build_readout
from skill_telemetry.receiver import MAX_CHUNKS, read_request_body
from skill_telemetry.store import EventStore

FIXTURES = Path(__file__).parent / "fixtures"
PRIVACY_CORPUS = json.loads(
    (Path(__file__).parent / "fixtures/privacy-corpus.json").read_text()
)
REJECTED_IDENTIFIERS = tuple(PRIVACY_CORPUS["rejected_identifiers"])
SAFE_RUNTIME_IDENTIFIERS = tuple(
    value
    for value in PRIVACY_CORPUS["safe_identifiers"]
    if value.startswith(("claude_code.", "codex.", "gen_ai.", "pi."))
)
COLLECTOR_SIGNAL_SOURCES = (None, "event.name", "event_name", "gen_ai.event.name")


def body_handler(headers: list[tuple[str, str]], payload: bytes) -> SimpleNamespace:
    message = Message()
    for name, value in headers:
        message.add_header(name, value)
    return SimpleNamespace(headers=message, rfile=io.BytesIO(payload))


def otlp_request(*, include_prohibited: bool = False) -> bytes:
    attrs = [
        KeyValue(key="session.id", value=AnyValue(string_value="private-session")),
        KeyValue(key="turn.id", value=AnyValue(string_value="private-turn")),
        KeyValue(key="skill_name", value=AnyValue(string_value="example-capture")),
        KeyValue(key="trigger", value=AnyValue(string_value="explicit")),
    ]
    if include_prohibited:
        attrs.append(
            KeyValue(key="prompt", value=AnyValue(string_value="PROHIBITED RAW PROMPT"))
        )
    record = LogRecord(
        event_name="claude_code.skill_activated",
        attributes=attrs,
        body=AnyValue(string_value="PROHIBITED ASSISTANT OR TOOL BODY"),
    )
    request = ExportLogsServiceRequest(
        resource_logs=[
            ResourceLogs(
                resource=Resource(
                    attributes=[
                        KeyValue(
                            key="service.name",
                            value=AnyValue(string_value="claude-code"),
                        )
                    ]
                ),
                scope_logs=[ScopeLogs(log_records=[record])],
            )
        ]
    )
    return request.SerializeToString()


def metrics_request(
    *,
    name: str = "codex.skill.injected",
    skill: str = "example-capture",
    invoke_type: str | None = "explicit",
    status: str = "success",
    count: int = 1,
    temporality: int = AGGREGATION_TEMPORALITY_DELTA,
    time_unix_nano: int = 1_750_000_000_000_000_000,
    include_prohibited: bool = False,
) -> bytes:
    attributes = [
        KeyValue(key="skill", value=AnyValue(string_value=skill)),
        KeyValue(key="status", value=AnyValue(string_value=status)),
    ]
    if invoke_type is not None:
        attributes.append(
            KeyValue(key="invoke_type", value=AnyValue(string_value=invoke_type))
        )
    if include_prohibited:
        attributes.extend(
            [
                KeyValue(
                    key="prompt", value=AnyValue(string_value="PROHIBITED PROMPT")
                ),
                KeyValue(key="path", value=AnyValue(string_value="/private/SKILL.md")),
                KeyValue(
                    key="command", value=AnyValue(string_value="PROHIBITED COMMAND")
                ),
                KeyValue(
                    key="credential_name",
                    value=AnyValue(string_value="WORK_OPENAI_API_KEY"),
                ),
            ]
        )
    metric = Metric(
        name=name,
        sum=Sum(
            aggregation_temporality=temporality,
            is_monotonic=True,
            data_points=[
                NumberDataPoint(
                    attributes=attributes,
                    start_time_unix_nano=time_unix_nano - 1_000,
                    time_unix_nano=time_unix_nano,
                    as_int=count,
                )
            ],
        ),
    )
    return ExportMetricsServiceRequest(
        resource_metrics=[
            ResourceMetrics(scope_metrics=[ScopeMetrics(metrics=[metric])])
        ]
    ).SerializeToString()


def request(url: str, *, data: bytes | None = None) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/x-protobuf"} if data is not None else {}
    with urllib.request.urlopen(  # noqa: S310 - tests target server-selected loopback URL
        urllib.request.Request(url, data=data, headers=headers), timeout=2
    ) as response:
        return response.status, response.read()


@pytest.mark.parametrize("length", ["+10", "1_0", " 10", "10 ", "-1"])
def test_request_body_rejects_noncanonical_content_length(length: str) -> None:
    with pytest.raises(ValueError, match="invalid content length"):
        read_request_body(body_handler([("Content-Length", length)], b"x" * 10), 100)


def test_request_body_rejects_duplicate_or_ambiguous_framing() -> None:
    duplicate = body_handler(
        [("Content-Length", "1"), ("Content-Length", "1")],
        b"x",
    )
    with pytest.raises(ValueError, match="duplicate request framing headers"):
        read_request_body(duplicate, 100)

    ambiguous = body_handler(
        [("Content-Length", "1"), ("Transfer-Encoding", "chunked")],
        b"x",
    )
    with pytest.raises(ValueError, match="ambiguous request framing"):
        read_request_body(ambiguous, 100)


def test_request_body_rejects_noncanonical_or_excessive_chunks() -> None:
    invalid = body_handler([("Transfer-Encoding", "chunked")], b"+a\r\n0123456789\r\n")
    with pytest.raises(ValueError, match="invalid chunk size"):
        read_request_body(invalid, 100)

    excessive_payload = b"1\r\nx\r\n" * (MAX_CHUNKS + 1) + b"0\r\n\r\n"
    excessive = body_handler([("Transfer-Encoding", "chunked")], excessive_payload)
    with pytest.raises(OverflowError, match="too many chunks"):
        read_request_body(excessive, MAX_CHUNKS + 1)


@pytest.mark.parametrize(
    ("service_name", "signal_name", "expected"),
    [
        ("openai-api", "unknown", "local"),
        ("pip", "unknown", "local"),
        ("codex_cli_rs", "unknown", "codex"),
        ("runtime", "codex.api_request", "codex"),
        ("runtime", "pi.explicit_skill", "pi"),
        ("claude-code", "unknown", "claude"),
    ],
)
def test_agent_inference_uses_scoped_identity_not_substrings(
    service_name: str,
    signal_name: str,
    expected: str,
) -> None:
    assert infer_agent(service_name, signal_name) == expected


def test_collector_accepts_otlp_on_loopback_and_drops_raw_content(
    private_state: Path,
) -> None:
    store = EventStore()
    server = CollectorServer(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        assert host == "127.0.0.1"
        assert request(f"http://{host}:{port}/healthz")[0] == 200
        status, _ = request(
            f"http://{host}:{port}/v1/logs",
            data=otlp_request(include_prohibited=True),
        )
        assert status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    stored = "\n".join(path.read_text() for path in private_state.glob("*.jsonl"))
    assert "example-capture" in stored
    assert "PROHIBITED" not in stored
    assert "private-session" not in stored
    assert "/" + "Users/" not in stored


def test_collector_retains_only_codex_skill_delta_metric_and_aggregate_count(
    private_state: Path,
) -> None:
    store = EventStore()
    server = CollectorServer(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        status, _ = request(
            f"http://{host}:{port}/v1/metrics",
            data=metrics_request(count=4, include_prohibited=True),
        )
        assert status == 200
        request(
            f"http://{host}:{port}/v1/metrics",
            data=metrics_request(name="codex.unrelated", count=99),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    events = store.read_events()
    assert len(events) == 1
    payload = events[0].to_dict()
    assert payload["skill_name"] == "example-capture"
    assert payload["trigger"] == "explicit"
    assert payload["status"] == "success"
    assert payload["count"] == 4
    assert "session_id" not in payload
    assert "turn_id" not in payload
    retained = json.dumps(payload)
    assert "PROHIBITED" not in retained
    assert "/private/" not in retained
    readout = build_readout(private_state)
    assert readout["native_metric_events"] == 1
    assert readout["aggregate_skill_invocations"] == 4


def test_duplicate_metric_delivery_does_not_inflate_and_restart_accepts_later_delta(
    private_state: Path,
) -> None:
    payload = metrics_request(count=3)
    for delivery in range(2):
        server = CollectorServer(("127.0.0.1", 0), EventStore())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        try:
            request(f"http://{host}:{port}/v1/metrics", data=payload)
            if delivery == 1:
                request(
                    f"http://{host}:{port}/v1/metrics",
                    data=metrics_request(
                        count=2, time_unix_nano=1_750_000_000_000_001_000
                    ),
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    events = EventStore(private_state).read_events()
    assert [event.count for event in events] == [3, 2]
    assert sum(event.count or 0 for event in events) == 5


def test_codex_metric_rejects_non_monotonic_delta_sum() -> None:
    message = ExportMetricsServiceRequest.FromString(metrics_request())
    metric = message.resource_metrics[0].scope_metrics[0].metrics[0]
    metric.sum.is_monotonic = False

    assert normalize_codex_metric(metric) == ()


def test_codex_metric_normalizes_observed_0144_success_without_invoke_type() -> None:
    message = ExportMetricsServiceRequest.FromString(
        metrics_request(invoke_type=None, status="ok")
    )
    metric = message.resource_metrics[0].scope_metrics[0].metrics[0]

    events = normalize_codex_metric(metric)

    assert len(events) == 1
    assert events[0].trigger == "unknown"
    assert events[0].status == "success"
    assert events[0].count == 1


def test_codex_metric_rejects_present_non_scalar_invoke_type() -> None:
    message = ExportMetricsServiceRequest.FromString(
        metrics_request(invoke_type=None, status="ok")
    )
    metric = message.resource_metrics[0].scope_metrics[0].metrics[0]
    metric.sum.data_points[0].attributes.append(
        KeyValue(
            key="invoke_type",
            value=AnyValue(
                array_value=ArrayValue(values=[AnyValue(string_value="explicit")])
            ),
        )
    )

    assert normalize_codex_metric(metric) == ()


def test_codex_metric_accepts_implicit_error_count_as_aggregate_evidence() -> None:
    message = ExportMetricsServiceRequest.FromString(
        metrics_request(invoke_type="implicit", status="error", count=2)
    )
    metric = message.resource_metrics[0].scope_metrics[0].metrics[0]

    events = normalize_codex_metric(metric)

    assert len(events) == 1
    assert events[0].trigger == "implicit"
    assert events[0].status == "error"
    assert events[0].count == 2
    assert events[0].session_id is None


@pytest.mark.parametrize(
    "payload",
    [
        metrics_request(temporality=AGGREGATION_TEMPORALITY_CUMULATIVE),
        metrics_request(skill="unknown/unsafe"),
        metrics_request(invoke_type="other"),
        metrics_request(invoke_type="unknown"),
        metrics_request(status="unknown"),
        metrics_request(count=0),
        metrics_request(count=1_000_001),
    ],
)
def test_codex_metric_rejects_non_delta_or_invalid_points(payload: bytes) -> None:
    request_message = ExportMetricsServiceRequest.FromString(payload)
    metric = request_message.resource_metrics[0].scope_metrics[0].metrics[0]
    assert normalize_codex_metric(metric) == ()


def test_collector_accepts_bounded_chunked_otlp_from_claude_code(
    private_state: Path,
) -> None:
    store = EventStore()
    server = CollectorServer(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=2)
    payload = otlp_request(include_prohibited=True)
    try:
        connection.request(
            "POST",
            "/v1/logs",
            body=(payload[:13], payload[13:]),
            headers={"Content-Type": "application/x-protobuf"},
            encode_chunked=True,
        )
        response = connection.getresponse()
        assert response.status == 200
        response.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    stored = "\n".join(path.read_text() for path in private_state.glob("*.jsonl"))
    assert "example-capture" in stored
    assert "PROHIBITED" not in stored
    assert "private-session" not in stored


def test_collector_rejects_oversize_and_malformed_payloads(private_state: Path) -> None:
    server = CollectorServer(("127.0.0.1", 0), EventStore(), max_request_bytes=32)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as too_large:
            request(f"http://{host}:{port}/v1/logs", data=b"x" * 33)
        assert too_large.value.code == 413

        connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            connection.request(
                "POST",
                "/v1/logs",
                body=(b"x" * 16, b"x" * 17),
                headers={"Content-Type": "application/x-protobuf"},
                encode_chunked=True,
            )
            response = connection.getresponse()
            assert response.status == 413
            response.read()
        finally:
            connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not list(private_state.glob("*.jsonl"))


@pytest.mark.parametrize(
    "raw_body",
    [
        pytest.param("sk-proj-SECRET123", id="secret-like-token"),
        pytest.param(
            "identifier-shaped-private-response", id="identifier-shaped-response"
        ),
    ],
)
def test_raw_otlp_body_never_becomes_a_normalized_identifier(raw_body: str) -> None:
    event = normalize_record(
        LogRecord(body=AnyValue(string_value=raw_body)),
        {"service.name": "codex_cli_rs"},
    )

    payload = event.to_dict()
    assert payload["signal_name"] == "unknown"
    assert raw_body not in json.dumps(payload)


def test_claude_2_1_211_sanitized_fixture_preserves_redacted_truth() -> None:
    fixture = json.loads((FIXTURES / "claude-2.1.211-skill-activated.json").read_text())
    record = fixture["record"]
    event = normalize_record(
        LogRecord(
            attributes=[
                KeyValue(key=key, value=AnyValue(string_value=value))
                for key, value in record["attributes"].items()
            ]
        ),
        fixture["resource_attributes"],
    )

    assert event.signal_name == fixture["expected"]["signal_name"]
    assert event.status == fixture["expected"]["status"]
    assert event.skill_name is None


def test_claude_unscoped_event_attribute_uses_exact_resource_identity() -> None:
    event = normalize_record(
        LogRecord(
            attributes=[
                KeyValue(
                    key="event.name", value=AnyValue(string_value="skill_activated")
                ),
                KeyValue(key="skill_name", value=AnyValue(string_value="writing-core")),
            ],
            body=AnyValue(string_value="PROHIBITED claude_code.skill_activated body"),
        ),
        {"service.name": "claude-code"},
    )

    assert event.event_name == "agent.skill.activation"
    assert event.signal_name == "claude_code.skill_activated"
    assert event.skill_name == "writing-core"
    assert "PROHIBITED" not in json.dumps(event.to_dict())


@pytest.mark.parametrize(
    ("attribute_name", "untrusted_signal"),
    [
        pytest.param(None, "sk-proj-SECRET123", id="secret-like-event-name"),
        pytest.param(
            None, "identifier-shaped-private-response", id="unscoped-event-name"
        ),
        pytest.param(None, "codex.sk-proj-SECRET123", id="prefixed-event-name"),
        pytest.param(
            "event.name",
            "claude_code.github_pat_PRIVATE123",
            id="secret-event-dot-name-attribute",
        ),
        pytest.param(
            "event_name",
            "gen_ai.xoxb-PRIVATE123",
            id="secret-event-underscore-name-attribute",
        ),
        pytest.param(
            "gen_ai.event.name",
            "gen_ai.xoxb-PRIVATE123",
            id="secret-gen-ai-event-name-attribute",
        ),
    ],
)
def test_untrusted_event_names_do_not_pass_identifier_validation(
    attribute_name: str | None,
    untrusted_signal: str,
) -> None:
    attributes = (
        []
        if attribute_name is None
        else [
            KeyValue(key=attribute_name, value=AnyValue(string_value=untrusted_signal))
        ]
    )
    event = normalize_record(
        LogRecord(
            event_name=untrusted_signal if attribute_name is None else "",
            attributes=attributes,
        ),
        {"service.name": "codex_cli_rs"},
    )

    payload = json.dumps(event.to_dict())
    assert event.signal_name == "unknown"
    assert untrusted_signal not in payload


@pytest.mark.parametrize("attribute_name", COLLECTOR_SIGNAL_SOURCES)
@pytest.mark.parametrize("untrusted_signal", REJECTED_IDENTIFIERS)
def test_shared_privacy_corpus_reaches_every_collector_signal_source(
    attribute_name: str | None,
    untrusted_signal: str,
) -> None:
    attributes = (
        []
        if attribute_name is None
        else [
            KeyValue(key=attribute_name, value=AnyValue(string_value=untrusted_signal))
        ]
    )
    event = normalize_record(
        LogRecord(
            event_name=untrusted_signal if attribute_name is None else "",
            attributes=attributes,
        ),
        {"service.name": "runtime"},
    )

    payload = json.dumps(event.to_dict())
    assert event.signal_name == "unknown"
    assert untrusted_signal not in payload


@pytest.mark.parametrize("attribute_name", COLLECTOR_SIGNAL_SOURCES)
@pytest.mark.parametrize("signal_name", SAFE_RUNTIME_IDENTIFIERS)
def test_shared_safe_runtime_corpus_reaches_every_collector_signal_source(
    attribute_name: str | None,
    signal_name: str,
) -> None:
    attributes = (
        []
        if attribute_name is None
        else [KeyValue(key=attribute_name, value=AnyValue(string_value=signal_name))]
    )
    event = normalize_record(
        LogRecord(
            event_name=signal_name if attribute_name is None else "",
            attributes=attributes,
        ),
        {"service.name": "runtime"},
    )

    assert event.signal_name == signal_name


def test_codex_lifecycle_events_in_same_turn_keep_distinct_correlation_records() -> (
    None
):
    attrs = [KeyValue(key="turn.id", value=AnyValue(string_value="same-private-turn"))]
    conversation = normalize_record(
        LogRecord(
            event_name="codex.conversation_starts", attributes=attrs, time_unix_nano=1
        ),
        {"service.name": "codex"},
    )
    tool = normalize_record(
        LogRecord(event_name="codex.tool_result", attributes=attrs, time_unix_nano=2),
        {"service.name": "codex"},
    )
    assert conversation.turn_id == tool.turn_id
    assert conversation.activation_id != tool.activation_id
    assert conversation.signal_name == "codex.conversation_starts"
    assert tool.signal_name == "codex.tool_result"


def test_codex_event_name_attribute_is_allowlisted_but_prompt_is_discarded() -> None:
    event = normalize_record(
        LogRecord(
            attributes=[
                KeyValue(
                    key="event.name",
                    value=AnyValue(string_value="codex.conversation_starts"),
                ),
                KeyValue(
                    key="conversation.id",
                    value=AnyValue(string_value="private-conversation"),
                ),
                KeyValue(
                    key="prompt", value=AnyValue(string_value="PROHIBITED RAW PROMPT")
                ),
            ]
        ),
        {"service.name": "codex_cli_rs"},
    )
    payload = event.to_dict()
    assert payload["signal_name"] == "codex.conversation_starts"
    assert payload["agent_system"] == "codex"
    assert payload["session_id"].startswith("sha256:")
    assert "PROHIBITED" not in str(payload)
    assert "private-conversation" not in str(payload)


def test_non_loopback_bind_is_rejected() -> None:
    with pytest.raises(ValueError, match="loopback"):
        CollectorServer(("0.0.0.0", 4318), EventStore())


def test_readout_keeps_evidence_stages_independent(private_state: Path) -> None:
    records = [
        {"evidence_type": "native-event", "event_name": "agent.skill.activation"},
        {"evidence_type": "explicit-command", "event_name": "agent.skill.activation"},
        {"evidence_type": "prompt-expansion", "event_name": "agent.skill.activation"},
        {"evidence_type": "canonical-file-read", "event_name": "agent.skill.execution"},
        {
            "evidence_type": "natural-language-candidate",
            "event_name": "agent.skill.candidate",
        },
        {
            "evidence_type": "unavailable-evidence",
            "event_name": "agent.skill.unknown",
            "session_id": f"sha256:{'a' * 64}",
        },
        {
            "evidence_type": "unavailable-evidence",
            "event_name": "agent.skill.unknown",
            "session_id": f"sha256:{'a' * 64}",
            "status": "not-observed",
        },
        {"evidence_type": "unobservable", "event_name": "agent.skill.unknown"},
        {
            "evidence_type": "provenance-error",
            "event_name": "agent.skill.failure",
            "status": "provenance-missing",
        },
        {
            "evidence_type": "otlp-log",
            "event_name": "agent.runtime.telemetry",
            "signal_name": "unknown",
        },
        {
            "evidence_type": "native-event",
            "event_name": "agent.runtime.alternate",
            "signal_name": "codex.future_lifecycle",
        },
    ]
    events = []
    for index, record in enumerate(records):
        events.append(
            SkillEvent.from_mapping(
                {
                    "schema_version": 1,
                    "agent_system": "local",
                    "trigger": "runtime-telemetry",
                    "evidence_confidence": "unknown",
                    "status": "unknown",
                    "timestamp": "2026-07-18T20:00:00Z",
                    "activation_id": f"sha256:{index:064x}",
                    **record,
                }
            )
        )
    EventStore(private_state).append_many(events)
    result = build_readout(private_state)
    assert result == {
        "native_or_structured_activations": 1,
        "explicit_command_activations": 1,
        "prompt_expansions": 1,
        "structured_hook_activations": 0,
        "native_metric_events": 0,
        "aggregate_skill_invocations": 0,
        "file_read_evidence": 1,
        "natural_language_candidates": 1,
        "unsupported_or_redacted_events": 2,
        "unknown_runtime_telemetry_events": 1,
        "unknown_or_unobservable": 3,
        "skill_evidence_events": 9,
        "runtime_telemetry_events": 2,
        "total_events": 11,
    }
