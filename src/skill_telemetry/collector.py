"""Skill-domain OTLP adapters and public receiver composition."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from functools import partial

from google.protobuf.json_format import ParseDict, ParseError
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
    ExportMetricsServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    AGGREGATION_TEMPORALITY_DELTA,
    Metric,
    NumberDataPoint,
)

from skill_telemetry.adapters import normalize_claude
from skill_telemetry.contract import MAX_EVENT_COUNT, SkillEvent
from skill_telemetry.privacy import pseudonym, safe_name, safe_signal_name
from skill_telemetry.receiver import (
    DEFAULT_HOST,
    DEFAULT_MAX_REQUEST_BYTES,
    DEFAULT_PORT,
    AdapterInfrastructureError,
    AdapterPayloadError,
    AdapterResult,
    CompositeEndpointAdapter,
    PreparedAdapterResult,
    ReceiverServer,
)
from skill_telemetry.store import EventStore
from skill_telemetry.usage import TokenUsageMetricsAdapter
from skill_telemetry.usage_store import UsageStore

CODEX_SKILL_METRIC = "codex.skill.injected"
CODEX_INVOKE_TYPES = frozenset({"explicit", "implicit"})
CODEX_METRIC_STATUS_MAP = {"ok": "success", "success": "success", "error": "error"}


def any_value(value: AnyValue) -> object | None:
    """Extract scalar OTLP values only; arrays/maps/bytes are intentionally discarded."""
    selected = value.WhichOneof("value")
    if selected == "string_value":
        return value.string_value
    if selected == "bool_value":
        return value.bool_value
    if selected == "int_value":
        return value.int_value
    if selected == "double_value":
        return value.double_value
    return None


def key_values(values: list[KeyValue]) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in values:
        scalar = any_value(item.value)
        if scalar is not None:
            result[item.key] = scalar
    return result


def single_scalar_attribute(
    values: list[KeyValue], key: str
) -> tuple[bool, object | None]:
    """Return exact presence plus one scalar value, rejecting duplicates as non-scalar."""
    matches = [item for item in values if item.key == key]
    if not matches:
        return False, None
    if len(matches) != 1:
        return True, None
    return True, any_value(matches[0].value)


def record_timestamp(record: LogRecord) -> str:
    nanos = record.time_unix_nano or record.observed_time_unix_nano
    if nanos:
        return datetime.fromtimestamp(nanos / 1_000_000_000, tz=UTC).isoformat()
    return datetime.now(UTC).isoformat()


def infer_agent(service_name: object, signal_name: str | None) -> str:
    """Infer only from exact resource identities or scoped signal prefixes."""
    signal = (signal_name or "").lower()
    if signal.startswith("claude_code."):
        return "claude"
    if signal.startswith("codex."):
        return "codex"
    if signal.startswith("pi."):
        return "pi"
    service = service_name.lower() if isinstance(service_name, str) else ""
    if service in {"claude-code", "claude_code"}:
        return "claude"
    if service == "codex" or service.startswith(("codex-", "codex_")):
        return "codex"
    if service in {"pi", "pi-coding-agent"}:
        return "pi"
    return "local"


def signal_from_record(
    record: LogRecord,
    attrs: dict[str, object],
    service_name: object,
) -> str | None:
    """Read scoped signal metadata without consulting the prohibited OTLP body."""
    event_name = safe_signal_name(record.event_name)
    if event_name:
        return event_name
    for key in ("event.name", "event_name", "gen_ai.event.name"):
        raw_name = attrs.get(key)
        event_name = safe_signal_name(raw_name)
        if event_name:
            return event_name
        # Claude Code 2.1.191-2.1.211 sends an unscoped event.name attribute
        # while its OTLP body contains the scoped duplicate. Scope the attribute
        # only when the trusted resource identity is exact; never read the body.
        if key == "event.name" and service_name == "claude-code":
            segment = safe_name(raw_name)
            if segment:
                event_name = safe_signal_name(f"claude_code.{segment}")
                if event_name:
                    return event_name
    return None


def normalize_record(
    record: LogRecord, resource_attrs: dict[str, object]
) -> SkillEvent:
    """Normalize only approved identifiers; never serialize the log body or arbitrary attrs."""
    attrs = key_values(list(record.attributes))
    signal_name = (
        signal_from_record(record, attrs, resource_attrs.get("service.name"))
        or "unknown"
    )
    agent_system = infer_agent(resource_attrs.get("service.name"), signal_name)
    if signal_name == "claude_code.skill_activated":
        # Trace/span/time are transport metadata, so this distinguishes repeated
        # activations without retaining body, prompt, path, or tool content.
        native = normalize_claude(
            {
                "event_name": signal_name,
                "timestamp": record_timestamp(record),
                "attributes": attrs,
                "occurrence_id": "|".join(
                    (
                        record.trace_id.hex(),
                        record.span_id.hex(),
                        str(record.time_unix_nano or record.observed_time_unix_nano),
                    )
                ),
            }
        )
        if native is not None:
            return native

    session_raw = next(
        (
            attrs[name]
            for name in ("session.id", "session_id", "conversation.id", "thread.id")
            if name in attrs
        ),
        None,
    )
    turn_raw = next(
        (attrs[name] for name in ("turn.id", "turn_id", "prompt.id") if name in attrs),
        None,
    )
    session_id = pseudonym(session_raw, namespace=f"{agent_system}-session")
    turn_id = pseudonym(turn_raw, namespace=f"{agent_system}-turn")
    record_identity = "|".join(
        (
            agent_system,
            session_id or "",
            turn_id or "",
            signal_name,
            record.trace_id.hex(),
            record.span_id.hex(),
            str(record.time_unix_nano or record.observed_time_unix_nano),
        )
    )
    activation_id = pseudonym(record_identity, namespace="runtime-log")
    return SkillEvent.from_mapping(
        {
            "schema_version": 1,
            "event_name": "agent.runtime.telemetry",
            "agent_system": agent_system,
            "session_id": session_id,
            "turn_id": turn_id,
            "activation_id": activation_id,
            "trigger": "runtime-telemetry",
            "evidence_type": "otlp-log",
            "evidence_confidence": "observed",
            "status": "received",
            "timestamp": record_timestamp(record),
            "signal_name": signal_name,
        }
    )


def parse_otlp_logs(payload: bytes, content_type: str) -> ExportLogsServiceRequest:
    request = ExportLogsServiceRequest()
    if "json" in content_type:
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise ValueError("OTLP JSON root must be an object")
        ParseDict(decoded, request, ignore_unknown_fields=False)
    else:
        request.ParseFromString(payload)
    return request


def parse_otlp_metrics(
    payload: bytes, content_type: str
) -> ExportMetricsServiceRequest:
    """Parse only the binary OTLP/HTTP encoding configured for Codex metrics."""
    if "json" in content_type:
        raise ValueError("OTLP metrics require binary protobuf")
    request = ExportMetricsServiceRequest()
    request.ParseFromString(payload)
    return request


def _metric_count(point: NumberDataPoint) -> int | None:
    selected = point.WhichOneof("value")
    if selected == "as_int":
        count = point.as_int
    elif (
        selected == "as_double"
        and math.isfinite(point.as_double)
        and point.as_double.is_integer()
    ):
        count = int(point.as_double)
    else:
        return None
    return count if 1 <= count <= MAX_EVENT_COUNT else None


def normalize_codex_metric(metric: Metric) -> tuple[SkillEvent, ...]:
    """Normalize allowlisted delta points without creating session attribution."""
    if (
        metric.name != CODEX_SKILL_METRIC
        or metric.WhichOneof("data") != "sum"
        or metric.sum.aggregation_temporality != AGGREGATION_TEMPORALITY_DELTA
        or not metric.sum.is_monotonic
    ):
        return ()
    events: list[SkillEvent] = []
    for point in metric.sum.data_points:
        point_attributes = list(point.attributes)
        skill_present, skill_value = single_scalar_attribute(point_attributes, "skill")
        invoke_type_present, invoke_type_value = single_scalar_attribute(
            point_attributes, "invoke_type"
        )
        status_present, status_value = single_scalar_attribute(
            point_attributes, "status"
        )
        skill_name = safe_name(skill_value)
        raw_invoke_type = safe_name(invoke_type_value)
        invoke_type = raw_invoke_type if invoke_type_present else "unknown"
        raw_status = safe_name(status_value)
        status = CODEX_METRIC_STATUS_MAP.get(raw_status or "")
        count = _metric_count(point)
        if (
            not skill_present
            or not status_present
            or skill_name is None
            or (invoke_type_present and invoke_type not in CODEX_INVOKE_TYPES)
            or status is None
            or count is None
            or not point.time_unix_nano
        ):
            continue
        assert skill_name is not None
        assert invoke_type is not None
        assert status is not None
        timestamp = datetime.fromtimestamp(
            point.time_unix_nano / 1_000_000_000, tz=UTC
        ).isoformat()
        identity_parts: list[str] = [
            CODEX_SKILL_METRIC,
            skill_name,
            invoke_type,
            status,
            str(point.start_time_unix_nano),
            str(point.time_unix_nano),
        ]
        identity = "|".join(identity_parts)
        events.append(
            SkillEvent.from_mapping(
                {
                    "schema_version": 1,
                    "event_name": "agent.skill.aggregate",
                    "agent_system": "codex",
                    "activation_id": pseudonym(
                        identity, namespace="codex-metric-point"
                    ),
                    "skill_name": skill_name,
                    "skill_source": "codex-native",
                    "trigger": invoke_type,
                    "evidence_type": "native-metric",
                    "evidence_confidence": "observed",
                    "status": status,
                    "timestamp": timestamp,
                    "signal_name": CODEX_SKILL_METRIC,
                    "count": count,
                }
            )
        )
    return tuple(events)


def normalize_metrics(request: ExportMetricsServiceRequest) -> tuple[SkillEvent, ...]:
    """Extract only Codex skill delta points and ignore all other metric traffic."""
    events: list[SkillEvent] = []
    for resource_metrics in request.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                events.extend(normalize_codex_metric(metric))
    return tuple(events)


def _commit_skill_events(
    store: EventStore, events: tuple[SkillEvent, ...]
) -> tuple[tuple[str, int], ...]:
    try:
        accepted = sum(store.append_many(events))
    except (OSError, ValueError) as exc:
        raise AdapterInfrastructureError("skill event persistence failed") from exc
    return (("skill", accepted),)


class SkillLogsAdapter:
    """Existing skill/runtime log normalization behind the neutral adapter seam."""

    def __init__(self, store: EventStore) -> None:
        self.store = store

    def prepare(self, payload: bytes, content_type: str) -> PreparedAdapterResult:
        try:
            logs = parse_otlp_logs(payload, content_type)
            events: list[SkillEvent] = []
            for resource_logs in logs.resource_logs:
                resource_attrs = key_values(list(resource_logs.resource.attributes))
                for scope_logs in resource_logs.scope_logs:
                    for record in scope_logs.log_records:
                        events.append(normalize_record(record, resource_attrs))
        except (
            DecodeError,
            ParseError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise AdapterPayloadError("malformed OTLP logs") from exc
        return PreparedAdapterResult(
            response_body=ExportLogsServiceResponse().SerializeToString(),
            commit=partial(_commit_skill_events, self.store, tuple(events)),
        )

    def ingest(self, payload: bytes, content_type: str) -> AdapterResult:
        prepared = self.prepare(payload, content_type)
        return AdapterResult(
            response_body=prepared.response_body,
            accepted_counts=prepared.commit(),
            content_type=prepared.content_type,
        )


class SkillMetricsAdapter:
    """Existing Codex skill metric normalization behind the adapter seam."""

    def __init__(self, store: EventStore) -> None:
        self.store = store

    def prepare(self, payload: bytes, content_type: str) -> PreparedAdapterResult:
        try:
            metrics = parse_otlp_metrics(payload, content_type)
            events = normalize_metrics(metrics)
        except (DecodeError, TypeError, ValueError) as exc:
            raise AdapterPayloadError("malformed OTLP metrics") from exc
        return PreparedAdapterResult(
            response_body=ExportMetricsServiceResponse().SerializeToString(),
            commit=partial(_commit_skill_events, self.store, events),
        )


class CollectorServer(ReceiverServer):
    """Public HTTP service wiring the two retained domains to one receiver."""

    def __init__(
        self,
        server_address: tuple[str, int],
        store: EventStore,
        *,
        usage_store: UsageStore | None = None,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    ) -> None:
        self.store = store
        self.usage_store = usage_store if usage_store is not None else UsageStore()
        super().__init__(
            server_address,
            {
                "/v1/logs": SkillLogsAdapter(store),
                "/v1/metrics": CompositeEndpointAdapter(
                    SkillMetricsAdapter(store),
                    TokenUsageMetricsAdapter(self.usage_store),
                ),
            },
            max_request_bytes=max_request_bytes,
        )


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    store: EventStore | None = None,
    usage_store: UsageStore | None = None,
) -> None:
    """Serve both local domains until interrupted, with no export path."""
    server = CollectorServer(
        (host, port),
        store if store is not None else EventStore(),
        usage_store=usage_store,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
