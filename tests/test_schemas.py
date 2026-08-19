from __future__ import annotations

import copy
import json
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import pytest

from skill_telemetry.campaign import (
    EVIDENCE_OUTCOMES,
    EVIDENCE_STAGES,
    INVOCATION_TYPES,
    PRODUCER_CHECKS,
    RUNTIMES,
    add_producer_checks,
    load_manifest,
    load_observations,
    score_campaign,
)
from skill_telemetry.cli import ERROR_REASONS, JSON_STATUSES
from skill_telemetry.ingest import LIMIT_STATUSES
from skill_telemetry.schemas import COMMANDS, SchemaError, validate_json_document

SCHEMAS = Path(__file__).parents[1] / "src/skill_telemetry/schemas"


def test_producer_and_schema_vocabularies_stay_in_lockstep() -> None:
    envelope = json.loads((SCHEMAS / "envelope-v1.json").read_text())
    schema = json.loads((SCHEMAS / "command-data-v1.json").read_text())
    definitions = schema["$defs"]
    case = definitions["case"]
    properties = case["properties"]
    assert set(envelope["properties"]["command"]["enum"]) == COMMANDS
    assert set(envelope["properties"]["status"]["enum"]) == JSON_STATUSES
    assert set(definitions["error"]["properties"]["reason"]["enum"]) == ERROR_REASONS
    assert set(properties["runtime"]["enum"]) == RUNTIMES
    assert set(properties["invocation_type"]["enum"]) == INVOCATION_TYPES
    assert set(properties["evidence_stage"]["enum"]) == EVIDENCE_STAGES
    assert set(properties["missing_required"]["items"]["enum"]) == (
        EVIDENCE_OUTCOMES | {"unsupported-evidence-stage"}
    )
    assert (
        set(definitions["evaluate"]["properties"]["producer_checks"]["properties"])
        == PRODUCER_CHECKS
    )
    gate_names = set(definitions["evaluate"]["properties"]["gates"]["properties"])
    assert gate_names == {
        "supported_explicit_precision_100",
        "supported_explicit_recall_100",
        "zero_false_positives",
        "pi_candidate_to_load_100",
        "pi_correlation_quality_100",
        "duplicate_events_do_not_inflate",
        "resume_reimport_no_double_count",
        "no_unexplained_provenance_errors",
        "unobservable_evidence_explicit",
        "required_evidence_supported",
        *PRODUCER_CHECKS,
    }
    assert (
        set(definitions["ingest"]["properties"]["limit_status"]["enum"])
        == LIMIT_STATUSES
    )


def test_packaged_schemas_are_parseable_and_envelope_references_discriminated_data() -> (
    None
):
    envelope = json.loads((SCHEMAS / "envelope-v1.json").read_text())
    command_data = json.loads((SCHEMAS / "command-data-v1.json").read_text())
    assert len(envelope["oneOf"]) == 8
    assert "$defs" in command_data
    assert any(
        "command-data-v1.json" in json.dumps(branch) for branch in envelope["oneOf"]
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), True),
        (("tool_version",), ""),
        (("warnings",), [1]),
        (("data", "loopback_only"), False),
        (("data", "state_directory_mode"), "0755"),
    ],
)
def test_packaged_schema_rejects_constrained_field_mutations(
    path: tuple[str, ...], value: object
) -> None:
    document: dict[str, object] = {
        "schema_version": 1,
        "command": "doctor",
        "tool_version": "0.1.0",
        "status": "ok",
        "data": {
            "collector": "http://127.0.0.1:14318",
            "loopback_only": True,
            "state_directory_mode": "0o700",
        },
        "warnings": [],
        "unsupported": [],
    }
    target: dict[str, object] = document
    for segment in path[:-1]:
        target = target[segment]  # type: ignore[assignment,index]
    target[path[-1]] = value
    with pytest.raises(SchemaError):
        validate_json_document(document)


def _envelope(command: str, data: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command": command,
        "tool_version": "0.1.0",
        "status": "ok",
        "data": data,
        "warnings": [],
        "unsupported": [],
    }


def _usage_data() -> dict[str, object]:
    return {
        "schema_version": 1,
        "metric_name": "codex.turn.token_usage",
        "metric_kind": "histogram",
        "points": 2,
        "summarized_points": 2,
        "unspecified_temporality_points_excluded": 0,
        "histogram_groups": [
            {
                "token_type": "input",
                "unit": "",
                "aggregation_temporality": "delta",
                "count": 1,
                "sum": 1.0,
                "bucket_counts": [1],
                "explicit_bounds": [],
                "source_points": 1,
            },
            {
                "token_type": "total",
                "unit": "",
                "aggregation_temporality": "cumulative",
                "start_time_unix_nano": 1,
                "time_unix_nano": 2,
                "count": 1,
                "sum": 1.0,
                "bucket_counts": [1],
                "explicit_bounds": [],
                "source_points": 1,
            },
        ],
        "summary_total_semantics": "native-total-only; present only for one compatible token-unit total group",
        "aggregation_temporalities": ["delta", "cumulative"],
        "units": [""],
        "dimension_availability": {
            "token_type": "available",
            "model_identity": "unavailable-not-retained",
            "pricing": "unavailable-no-pricing-source",
            "session_attribution": "unavailable-not-emitted-or-retained",
            "cost": "unavailable-not-estimated",
            "other_metric_attributes": "unavailable-not-retained",
        },
        "summary_total_tokens": 1.0,
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("histogram_groups", 0, "token_type"), "unknown"),
        (("histogram_groups", 0, "unit"), "tokens"),
        (("histogram_groups", 0, "aggregation_temporality"), "cumulative"),
        (("histogram_groups", 0, "count"), -1),
        (("histogram_groups", 0, "sum"), -1),
        (("histogram_groups", 0, "bucket_counts"), ["one"]),
        (("histogram_groups", 0, "explicit_bounds"), ["one"]),
        (("histogram_groups", 0, "source_points"), 0),
        (("histogram_groups", 1, "start_time_unix_nano"), 0),
        (("histogram_groups", 1, "time_unix_nano"), "two"),
        (("aggregation_temporalities",), ["other"]),
        (("units",), ["tokens"]),
        (("dimension_availability", "cost"), "available"),
        (("summary_total_tokens",), -1),
    ],
)
def test_usage_schema_rejects_nested_field_type_range_and_enum_mutations(
    path: tuple[object, ...], value: object
) -> None:
    document = _envelope("usage", _usage_data())
    target: object = document["data"]
    for segment in path[:-1]:
        target = target[segment]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(SchemaError):
        validate_json_document(document)


def test_usage_schema_rejects_nested_missing_and_extra_properties() -> None:
    for mutate in (
        lambda data: data["histogram_groups"][0].pop("sum"),
        lambda data: data["histogram_groups"][0].update({"extra": True}),
        lambda data: data["dimension_availability"].pop("cost"),
        lambda data: data["dimension_availability"].update({"extra": "no"}),
    ):
        document = _envelope("usage", copy.deepcopy(_usage_data()))
        mutate(document["data"])
        with pytest.raises(SchemaError):
            validate_json_document(document)


def test_evaluate_schema_accepts_real_producer_output_and_rejects_nested_mutations() -> (
    None
):
    campaign_dir = files("skill_telemetry").joinpath("campaigns")
    manifest = load_manifest(Path(str(campaign_dir / "acceptance-v1.json")))
    observations = load_observations(
        Path(str(campaign_dir / "acceptance-observations-v1.json")), manifest
    )
    report = add_producer_checks(
        score_campaign(manifest, observations), {"pi-extension-tests": True}
    )
    document = _envelope("evaluate", report)
    validate_json_document(document)
    mutations = (
        lambda data: data["gates"].update({"pi-extension-tests": "true"}),
        lambda data: data["metrics"]["supported_explicit_precision"].update(
            {"value": 2}
        ),
        lambda data: data["metrics"]["deduplication"].update({"raw_events": -1}),
        lambda data: data["metrics"]["stages"]["explicit-command"].update(
            {"precision": []}
        ),
        lambda data: data["cases"][0].update({"runtime": "other"}),
        lambda data: data["cases"][0].update({"missing_required": [1]}),
        lambda data: data["cases"][0].update({"missing_required": ["unknown-outcome"]}),
        lambda data: data["cases"][0].update(
            {"missing_required": ["explicit-command"] * 65}
        ),
        lambda data: data["gates"].update({"unknown-gate": True}),
        lambda data: data["metrics"]["stages"].update({"unknown-stage": {}}),
        lambda data: data["producer_checks"].update(
            {"unknown-producer": {"status": "passed"}}
        ),
        lambda data: data.update({"cases": data["cases"] * 129}),
        lambda data: data["producer_checks"]["pi-extension-tests"].update(
            {"status": "unknown"}
        ),
        lambda data: data["producer_checks"]["pi-extension-tests"].update(
            {"extra": True}
        ),
    )
    for mutate in mutations:
        changed = copy.deepcopy(document)
        mutate(changed["data"])
        with pytest.raises(SchemaError):
            validate_json_document(changed)


def test_readout_and_ingest_schemas_reject_every_field_type_and_shape_mutation() -> (
    None
):
    readout = {
        "native_or_structured_activations": 0,
        "explicit_command_activations": 0,
        "prompt_expansions": 0,
        "structured_hook_activations": 0,
        "native_metric_events": 0,
        "aggregate_skill_invocations": 0,
        "file_read_evidence": 0,
        "natural_language_candidates": 0,
        "unsupported_or_redacted_events": 0,
        "unknown_runtime_telemetry_events": 0,
        "unknown_or_unobservable": 0,
        "skill_evidence_events": 0,
        "runtime_telemetry_events": 0,
        "total_events": 0,
    }
    ingest = {
        "agent_system": "pi",
        "files_scanned": 0,
        "records_scanned": 0,
        "telemetry_records": 0,
        "imported": 0,
        "duplicates": 0,
        "rejected": 0,
        "malformed_records_skipped": 0,
        "limit_status": "max-files",
        "dry_run": False,
    }
    for command, data in (("readout", readout), ("ingest.pi", ingest)):
        for field in data:
            changed = _envelope(command, copy.deepcopy(data))
            changed["data"][field] = "wrong"  # type: ignore[index]
            with pytest.raises(SchemaError):
                validate_json_document(changed)
        missing = _envelope(command, copy.deepcopy(data))
        missing["data"].pop(next(iter(data)))  # type: ignore[index]
        with pytest.raises(SchemaError):
            validate_json_document(missing)
        extra = _envelope(command, copy.deepcopy(data))
        extra["data"]["unexpected"] = 0  # type: ignore[index]
        with pytest.raises(SchemaError):
            validate_json_document(extra)


def test_evaluate_ignores_unknown_event_stage_keys_in_closed_v1_output() -> None:
    campaign_dir = files("skill_telemetry").joinpath("campaigns")
    manifest = load_manifest(Path(str(campaign_dir / "acceptance-v1.json")))
    observations = load_observations(
        Path(str(campaign_dir / "acceptance-observations-v1.json")), manifest
    )
    case_id = next(key for key, value in observations.items() if value.events)
    original = observations[case_id]
    observations[case_id] = replace(
        original, events=(replace(original.events[0], evidence_type="future-stage"),)
    )
    document = _envelope("evaluate", score_campaign(manifest, observations))
    validate_json_document(document)
    assert "future-stage" not in document["data"]["metrics"]["stages"]


def test_evaluate_schema_requires_a_complete_gate_set_and_nonempty_cases() -> None:
    campaign_dir = files("skill_telemetry").joinpath("campaigns")
    manifest = load_manifest(Path(str(campaign_dir / "acceptance-v1.json")))
    observations = load_observations(
        Path(str(campaign_dir / "acceptance-observations-v1.json")), manifest
    )
    document = _envelope("evaluate", score_campaign(manifest, observations))
    for mutate in (
        lambda data: data.update({"gates": {}}),
        lambda data: data.update({"cases": []}),
    ):
        changed = copy.deepcopy(document)
        mutate(changed["data"])
        with pytest.raises(SchemaError):
            validate_json_document(changed)


def test_runtime_validator_rejects_data_from_another_command() -> None:
    document = {
        "schema_version": 1,
        "command": "version",
        "tool_version": "0.1.0",
        "status": "ok",
        "data": {
            "collector": "http://127.0.0.1",
            "loopback_only": True,
            "state_directory_mode": "0o700",
        },
        "warnings": [],
        "unsupported": [],
    }
    with pytest.raises(SchemaError):
        validate_json_document(document)
