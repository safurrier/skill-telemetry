"""Allowlisted OTLP adapter and shape-faithful readout for Codex token usage."""

from __future__ import annotations

import math
from collections import defaultdict
from functools import partial
from pathlib import Path

from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
    ExportMetricsServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import KeyValue
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    AGGREGATION_TEMPORALITY_CUMULATIVE,
    AGGREGATION_TEMPORALITY_DELTA,
    AGGREGATION_TEMPORALITY_UNSPECIFIED,
    Metric,
)

from skill_telemetry.receiver import (
    AdapterInfrastructureError,
    AdapterPayloadError,
    PreparedAdapterResult,
)
from skill_telemetry.usage_contract import (
    CODEX_TOKEN_USAGE_METRIC,
    TOKEN_TYPES,
    TOKEN_UNITS,
    TokenUsagePoint,
    UsageContractError,
)
from skill_telemetry.usage_store import UsageStore, usage_state_directory

_TEMPORALITY_NAMES = {
    AGGREGATION_TEMPORALITY_UNSPECIFIED: "unspecified",
    AGGREGATION_TEMPORALITY_DELTA: "delta",
    AGGREGATION_TEMPORALITY_CUMULATIVE: "cumulative",
}


class UsageReadoutError(ValueError):
    """Raised when a retained finite histogram cannot be safely aggregated."""


def _finite_sum(values: list[float]) -> float:
    """Sum finite source values without allowing an operational overflow to escape."""
    try:
        total = math.fsum(values)
    except OverflowError as exc:
        raise UsageReadoutError("usage aggregate overflow") from exc
    if not math.isfinite(total):
        raise UsageReadoutError("usage aggregate is non-finite")
    return total


def _token_type(attributes: list[KeyValue]) -> str | None:
    """Return one scalar allowlisted token_type; ignore every other attribute."""
    matches = [attribute for attribute in attributes if attribute.key == "token_type"]
    if len(matches) != 1 or matches[0].value.WhichOneof("value") != "string_value":
        return None
    token_type = matches[0].value.string_value
    return token_type if token_type in TOKEN_TYPES else None


def normalize_token_usage_metric(metric: Metric) -> tuple[TokenUsagePoint, ...]:
    """Normalize only the official Codex histogram and its token_type dimension."""
    if (
        metric.name != CODEX_TOKEN_USAGE_METRIC
        or metric.WhichOneof("data") != "histogram"
    ):
        return ()
    if metric.unit not in TOKEN_UNITS:
        raise UsageContractError("unsupported usage unit")
    temporality = _TEMPORALITY_NAMES.get(metric.histogram.aggregation_temporality)
    if temporality is None:
        raise UsageContractError("unsupported aggregation temporality")
    points: list[TokenUsagePoint] = []
    for point in metric.histogram.data_points:
        token_type = _token_type(list(point.attributes))
        if token_type is None:
            continue
        if not point.HasField("sum"):
            raise UsageContractError("official usage histogram point requires sum")
        normalized = TokenUsagePoint(
            schema_version=1,
            metric_name=metric.name,
            metric_kind="histogram",
            aggregation_temporality=temporality,
            unit=metric.unit,
            token_type=token_type,
            start_time_unix_nano=point.start_time_unix_nano,
            time_unix_nano=point.time_unix_nano,
            count=point.count,
            sum=point.sum,
            bucket_counts=tuple(point.bucket_counts),
            explicit_bounds=tuple(point.explicit_bounds),
        )
        normalized.validate()
        points.append(normalized)
    return tuple(points)


def normalize_usage_metrics(
    request: ExportMetricsServiceRequest,
) -> tuple[TokenUsagePoint, ...]:
    """Extract allowlisted token usage points and ignore all unknown metrics."""
    points: list[TokenUsagePoint] = []
    for resource_metrics in request.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                points.extend(normalize_token_usage_metric(metric))
    return tuple(points)


def _commit_usage_points(
    store: UsageStore, points: tuple[TokenUsagePoint, ...]
) -> tuple[tuple[str, int], ...]:
    try:
        accepted = sum(store.append_many(points))
    except (OSError, ValueError) as exc:
        raise AdapterInfrastructureError("usage persistence failed") from exc
    return (("usage", accepted),)


class TokenUsageMetricsAdapter:
    """Binary OTLP metrics adapter for the independent usage domain."""

    def __init__(self, store: UsageStore) -> None:
        self.store = store

    def prepare(self, payload: bytes, content_type: str) -> PreparedAdapterResult:
        if "json" in content_type:
            raise AdapterPayloadError("OTLP metrics require binary protobuf")
        request = ExportMetricsServiceRequest()
        try:
            request.ParseFromString(payload)
            points = normalize_usage_metrics(request)
        except (DecodeError, TypeError, UsageContractError, ValueError) as exc:
            raise AdapterPayloadError("malformed OTLP usage histogram") from exc
        return PreparedAdapterResult(
            response_body=ExportMetricsServiceResponse().SerializeToString(),
            commit=partial(_commit_usage_points, self.store, points),
        )


ShapeKey = tuple[str, str, tuple[float, ...]]
EpochKey = tuple[str, str, tuple[float, ...], int]


def _point_order(
    point: TokenUsagePoint,
) -> tuple[int, int, float, tuple[int, ...], tuple[float, ...]]:
    return (
        point.time_unix_nano,
        point.count,
        point.sum,
        point.bucket_counts,
        point.explicit_bounds,
    )


def _histogram_groups(
    points: tuple[TokenUsagePoint, ...],
) -> tuple[tuple[dict[str, object], ...], int]:
    """Group only compatible deltas and retain one cumulative point per stream epoch."""
    deltas: dict[ShapeKey, list[TokenUsagePoint]] = defaultdict(list)
    cumulative: dict[EpochKey, TokenUsagePoint] = {}
    for point in points:
        shape = (point.token_type, point.unit, point.explicit_bounds)
        if point.aggregation_temporality == "delta":
            deltas[shape].append(point)
        elif point.aggregation_temporality == "cumulative":
            epoch = (*shape, point.start_time_unix_nano)
            previous = cumulative.get(epoch)
            if previous is None or _point_order(point) > _point_order(previous):
                cumulative[epoch] = point

    group_entries: list[
        tuple[tuple[str, str, str, tuple[float, ...], int], dict[str, object]]
    ] = []
    summarized_points = 0
    for (token_type, unit, bounds), compatible in sorted(deltas.items()):
        summarized_points += len(compatible)
        group_entries.append(
            (
                (token_type, unit, "delta", bounds, 0),
                {
                    "token_type": token_type,
                    "unit": unit,
                    "aggregation_temporality": "delta",
                    "count": sum(point.count for point in compatible),
                    "sum": _finite_sum([point.sum for point in compatible]),
                    "bucket_counts": [
                        sum(point.bucket_counts[index] for point in compatible)
                        for index in range(len(bounds) + 1)
                    ],
                    "explicit_bounds": list(bounds),
                    "source_points": len(compatible),
                },
            )
        )
    for (token_type, unit, bounds, start_time), point in sorted(cumulative.items()):
        summarized_points += 1
        group_entries.append(
            (
                (token_type, unit, "cumulative", bounds, start_time),
                {
                    "token_type": token_type,
                    "unit": unit,
                    "aggregation_temporality": "cumulative",
                    "start_time_unix_nano": start_time,
                    "time_unix_nano": point.time_unix_nano,
                    "count": point.count,
                    "sum": point.sum,
                    "bucket_counts": list(point.bucket_counts),
                    "explicit_bounds": list(bounds),
                    "source_points": 1,
                },
            )
        )
    return tuple(group for _, group in sorted(group_entries)), summarized_points


def build_usage_readout(directory: Path | None = None) -> dict[str, object]:
    """Report compatible histogram groups without mixing metric shapes."""
    root = directory or usage_state_directory()
    points = UsageStore(root).read_points() if root.exists() else ()
    groups, summarized_points = _histogram_groups(points)
    temporalities = sorted({point.aggregation_temporality for point in points})
    units = sorted({point.unit for point in points})
    readout: dict[str, object] = {
        "schema_version": 1,
        "metric_name": CODEX_TOKEN_USAGE_METRIC,
        "metric_kind": "histogram",
        "points": len(points),
        "summarized_points": summarized_points,
        "unspecified_temporality_points_excluded": sum(
            point.aggregation_temporality == "unspecified" for point in points
        ),
        "histogram_groups": list(groups),
        "summary_total_semantics": (
            "native-total-only; present only for one compatible token-unit total group"
        ),
        "aggregation_temporalities": temporalities,
        "units": units,
        "dimension_availability": {
            "token_type": "available",
            "model_identity": "unavailable-not-retained",
            "pricing": "unavailable-no-pricing-source",
            "session_attribution": "unavailable-not-emitted-or-retained",
            "cost": "unavailable-not-estimated",
            "other_metric_attributes": "unavailable-not-retained",
        },
    }
    native_totals = [
        group
        for group in groups
        if group["token_type"] == "total" and group["unit"] in TOKEN_UNITS
    ]
    if len(native_totals) == 1:
        readout["summary_total_tokens"] = native_totals[0]["sum"]
    return readout
