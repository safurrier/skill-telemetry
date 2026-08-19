"""Versioned contract for allowlisted Codex token-usage histograms."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from typing import Self, cast

USAGE_SCHEMA_VERSION = 1
CODEX_TOKEN_USAGE_METRIC = "codex.turn.token_usage"
TOKEN_TYPES = frozenset(
    {"input", "cached_input", "output", "reasoning_output", "total"}
)
TEMPORALITIES = frozenset({"unspecified", "delta", "cumulative"})
TOKEN_UNITS = frozenset({""})
MAX_HISTOGRAM_COUNT = 1_000_000_000_000
MAX_BUCKETS = 512


class UsageContractError(ValueError):
    """Raised when a normalized usage point violates contract v1."""


@dataclass(frozen=True, slots=True)
class TokenUsagePoint:
    """One content-free OTLP histogram point with exact numeric fidelity."""

    schema_version: int
    metric_name: str
    metric_kind: str
    aggregation_temporality: str
    unit: str
    token_type: str
    start_time_unix_nano: int
    time_unix_nano: int
    count: int
    sum: float
    bucket_counts: tuple[int, ...]
    explicit_bounds: tuple[float, ...]

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> Self:
        """Validate and construct a point, rejecting silent schema widening."""
        allowed = {field.name for field in fields(cls)}
        if set(value) - allowed:
            raise UsageContractError("usage point contains unknown fields")
        missing = sorted(allowed - set(value))
        if missing:
            raise UsageContractError(
                f"missing usage point fields: {', '.join(missing)}"
            )
        prepared = dict(value)
        for name in ("bucket_counts", "explicit_bounds"):
            item = prepared[name]
            if not isinstance(item, (list, tuple)):
                raise UsageContractError(f"{name} must be an array")
            prepared[name] = tuple(item)
        try:
            point = cls(
                schema_version=cast(int, prepared["schema_version"]),
                metric_name=cast(str, prepared["metric_name"]),
                metric_kind=cast(str, prepared["metric_kind"]),
                aggregation_temporality=cast(str, prepared["aggregation_temporality"]),
                unit=cast(str, prepared["unit"]),
                token_type=cast(str, prepared["token_type"]),
                start_time_unix_nano=cast(int, prepared["start_time_unix_nano"]),
                time_unix_nano=cast(int, prepared["time_unix_nano"]),
                count=cast(int, prepared["count"]),
                sum=cast(float, prepared["sum"]),
                bucket_counts=cast(tuple[int, ...], prepared["bucket_counts"]),
                explicit_bounds=cast(tuple[float, ...], prepared["explicit_bounds"]),
            )
            point.validate()
        except TypeError as exc:
            raise UsageContractError("usage point has invalid field types") from exc
        return point

    def validate(self) -> None:
        """Validate the closed, low-cardinality token usage contract."""
        if self.schema_version != USAGE_SCHEMA_VERSION:
            raise UsageContractError("unsupported usage schema_version")
        if self.metric_name != CODEX_TOKEN_USAGE_METRIC:
            raise UsageContractError("unsupported usage metric")
        if self.metric_kind != "histogram":
            raise UsageContractError("usage metric must be a histogram")
        if (
            not isinstance(self.aggregation_temporality, str)
            or self.aggregation_temporality not in TEMPORALITIES
        ):
            raise UsageContractError("unsupported aggregation temporality")
        if not isinstance(self.unit, str) or self.unit not in TOKEN_UNITS:
            raise UsageContractError("unsupported usage unit")
        if not isinstance(self.token_type, str) or self.token_type not in TOKEN_TYPES:
            raise UsageContractError("unsupported token_type")
        for label, value in (
            ("start_time_unix_nano", self.start_time_unix_nano),
            ("time_unix_nano", self.time_unix_nano),
            ("count", self.count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise UsageContractError(f"{label} must be a non-negative integer")
        if self.time_unix_nano == 0:
            raise UsageContractError("time_unix_nano is required")
        if (
            self.aggregation_temporality == "cumulative"
            and self.start_time_unix_nano == 0
        ):
            raise UsageContractError("cumulative usage requires start_time_unix_nano")
        if self.start_time_unix_nano > self.time_unix_nano:
            raise UsageContractError("usage point timestamps are out of order")
        if self.count > MAX_HISTOGRAM_COUNT:
            raise UsageContractError("histogram count exceeds the contract bound")
        if not isinstance(self.sum, (int, float)) or isinstance(self.sum, bool):
            raise UsageContractError("histogram sum must be numeric")
        if not math.isfinite(self.sum) or self.sum < 0:
            raise UsageContractError("histogram sum must be finite and non-negative")
        if not isinstance(self.bucket_counts, tuple) or not isinstance(
            self.explicit_bounds, tuple
        ):
            raise UsageContractError("histogram buckets and bounds must be tuples")
        if len(self.explicit_bounds) > MAX_BUCKETS:
            raise UsageContractError("histogram has too many buckets")
        if len(self.bucket_counts) != len(self.explicit_bounds) + 1:
            raise UsageContractError(
                "bucket_counts must have one more item than explicit_bounds"
            )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.bucket_counts
        ):
            raise UsageContractError("bucket_counts must be non-negative integers")
        if sum(self.bucket_counts) != self.count:
            raise UsageContractError("bucket_counts must sum to histogram count")
        previous = -math.inf
        for bound in self.explicit_bounds:
            if not isinstance(bound, (int, float)) or isinstance(bound, bool):
                raise UsageContractError("explicit_bounds must be numeric")
            if not math.isfinite(bound) or bound <= previous:
                raise UsageContractError(
                    "explicit_bounds must be finite and increasing"
                )
            previous = float(bound)

    def to_dict(self) -> dict[str, object]:
        """Return the canonical JSON representation."""
        self.validate()
        value = asdict(self)
        value["bucket_counts"] = list(self.bucket_counts)
        value["explicit_bounds"] = list(self.explicit_bounds)
        return value
