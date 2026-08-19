from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_telemetry.usage import UsageReadoutError, build_usage_readout
from skill_telemetry.usage_contract import TokenUsagePoint, UsageContractError
from skill_telemetry.usage_store import UsageStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_serialized_usage_fixture_persists_dedupes_and_reads(tmp_path: Path) -> None:
    point = TokenUsagePoint.from_mapping(
        json.loads((FIXTURES / "serialized/token-usage-v0.2.jsonl").read_text())
    )
    store = UsageStore(tmp_path / "usage")
    assert store.append_many((point, point)) == (True, False)
    readout = build_usage_readout(store.directory)
    assert readout["points"] == 1
    assert readout["summary_total_tokens"] == 12.0


def test_finite_usage_points_that_overflow_an_aggregate_raise_stable_error(
    tmp_path: Path,
) -> None:
    store = UsageStore(tmp_path / "usage")
    first = TokenUsagePoint.from_mapping(
        {
            **json.loads((FIXTURES / "serialized/token-usage-v0.2.jsonl").read_text()),
            "aggregation_temporality": "delta",
            "sum": 1e308,
            "time_unix_nano": 101,
        }
    )
    second = TokenUsagePoint.from_mapping({**first.to_dict(), "time_unix_nano": 102})
    assert store.append_many((first, second)) == (True, True)
    with pytest.raises(UsageReadoutError, match="usage aggregate overflow"):
        build_usage_readout(store.directory)


def test_invalid_usage_fixture_is_rejected() -> None:
    base = json.loads((FIXTURES / "serialized/token-usage-v0.2.jsonl").read_text())
    for invalid in json.loads((FIXTURES / "token-usage-invalid-v1.json").read_text()):
        candidate = {**base, **invalid["patch"]}
        with pytest.raises(UsageContractError):
            TokenUsagePoint.from_mapping(candidate)
