"""Versioned skill-evaluation campaign loading and common scoring."""

from __future__ import annotations

import json
import os
import platform
import re
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    AGGREGATION_TEMPORALITY_DELTA,
    Metric,
    NumberDataPoint,
    Sum,
)

from skill_telemetry.adapters import normalize_claude, normalize_codex
from skill_telemetry.claude_hooks import normalize_claude_hook
from skill_telemetry.collector import normalize_codex_metric
from skill_telemetry.contract import ContractError, SkillEvent
from skill_telemetry.ingest import ingest_codex, ingest_pi
from skill_telemetry.privacy import safe_name
from skill_telemetry.store import EventStore

CAMPAIGN_SCHEMA_VERSION = 1
ACTIVATION_STAGES = frozenset(
    {
        "explicit-command",
        "structured-input",
        "structured-hook",
        "native-event",
        "native-metric",
    }
)
UNKNOWN_STATUSES = frozenset({"identity-redacted", "unsupported", "unknown"})
CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
OBSERVATION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$")
MAX_CAMPAIGN_BYTES = 2 * 1024 * 1024
MAX_CAMPAIGN_CASES = 128
MAX_CASE_OUTCOMES = 64
RUNTIMES = frozenset({"pi", "codex", "claude"})
INVOCATION_TYPES = frozenset(
    {
        "explicit",
        "implicit",
        "natural-language",
        "negative-control",
        "resume-reimport",
        "model-selected",
    }
)
EVIDENCE_STAGES = frozenset(
    {
        "activation",
        "candidate-to-load",
        "aggregate-activation",
        "named-hook",
        "native-event",
    }
)
EVIDENCE_OUTCOMES = frozenset(
    {
        "explicit-command",
        "structured-input",
        "structured-hook",
        "native-event",
        "native-metric",
        "natural-language-candidate",
        "canonical-file-read",
        "provenance-error",
        "native-skill-identity",
    }
)
UNSUPPORTED_EVIDENCE_STAGE = "unsupported-evidence-stage"
OUTCOMES = EVIDENCE_OUTCOMES | frozenset({UNSUPPORTED_EVIDENCE_STAGE})
PRODUCER_CHECKS = frozenset(
    {"pi-extension-tests", "pi-extension-build", "pi-extension-load"}
)


class CampaignError(ValueError):
    """Raised when campaign inputs do not satisfy the versioned contract."""


@dataclass(frozen=True, slots=True)
class CampaignCase:
    """One runtime/version expectation with explicit evidence support semantics."""

    case_id: str
    runtime: str
    runtime_version: str
    expected_skill: str | None
    invocation_type: str
    evidence_stage: str
    required_outcomes: tuple[str, ...]
    forbidden_outcomes: tuple[str, ...]
    unobservable_outcomes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CampaignManifest:
    """A versioned, deterministic campaign definition."""

    schema_version: int
    campaign_id: str
    observations: str
    cases: tuple[CampaignCase, ...]
    source_directory: Path


@dataclass(frozen=True, slots=True)
class CaseObservation:
    """Store-validated evidence plus explicit delivery and support accounting."""

    events: tuple[SkillEvent, ...]
    unsupported_outcomes: tuple[str, ...]
    duplicate_deliveries: int = 0


@dataclass(frozen=True, slots=True)
class Ratio:
    numerator: int
    denominator: int
    value: float | None

    @classmethod
    def make(cls, numerator: int, denominator: int) -> Ratio:
        return cls(
            numerator,
            denominator,
            None if denominator == 0 else numerator / denominator,
        )


def add_producer_checks(
    report: dict[str, object], checks: dict[str, bool]
) -> dict[str, object]:
    """Compose only declared producer results into the report's pass decision."""
    if set(checks) - PRODUCER_CHECKS or not all(
        isinstance(passed, bool) for passed in checks.values()
    ):
        raise CampaignError("producer checks do not match schema version 1")
    gates = cast(dict[str, bool], report["gates"])
    for name, passed in checks.items():
        gates[name] = passed
    report["producer_checks"] = {
        name: {
            "status": "passed" if passed else "failed",
            **(
                {"remediation": "Repair the reported producer check in repository CI."}
                if not passed
                else {}
            ),
        }
        for name, passed in checks.items()
    }
    report["passed"] = bool(report["passed"]) and all(checks.values())
    return report


def _mapping(value: object, location: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CampaignError(f"{location} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CampaignError(f"{location} must be a non-empty string")
    return value


def _enum(value: object, location: str, allowed: frozenset[str]) -> str:
    candidate = _string(value, location)
    if candidate not in allowed:
        raise CampaignError(f"{location} has unsupported schema version 1 value")
    return candidate


def _case_id(value: object, location: str) -> str:
    candidate = _string(value, location)
    if not CASE_ID.fullmatch(candidate) or safe_name(candidate) is None:
        raise CampaignError(f"{location} must be a bounded safe filename segment")
    return candidate


def _outcomes(value: object, location: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) > MAX_CASE_OUTCOMES
        or not all(isinstance(item, str) and item in OUTCOMES for item in value)
    ):
        raise CampaignError(f"{location} must be a bounded outcome array")
    result = tuple(cast(list[str], value))
    if len(set(result)) != len(result):
        raise CampaignError(f"{location} must not contain duplicates")
    return result


def _absolute_campaign_path(path: Path) -> Path:
    """Normalize Darwin's documented /tmp and /var aliases without resolving links."""
    absolute = path.absolute()
    if platform.system() == "Darwin" and absolute.parts[:2] in {
        ("/", "tmp"),
        ("/", "var"),
    }:
        return Path("/private") / absolute.relative_to("/")
    return absolute


def _open_directory_nofollow(path: Path) -> int:
    """Open every absolute directory component without following a symlink."""
    if not path.is_absolute():
        raise CampaignError("campaign path must be absolute")
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    except AttributeError as exc:
        raise CampaignError("safe campaign file access is unsupported") from exc
    fd = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            if component in {"", ".", ".."}:
                raise CampaignError("unsafe campaign path")
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise CampaignError("unsafe campaign directory")
        return fd
    except OSError as exc:
        os.close(fd)
        raise CampaignError("unsafe campaign directory") from exc
    except CampaignError:
        os.close(fd)
        raise


def _read_campaign_file(path: Path, label: str) -> str:
    """Read one bounded regular file through a no-follow parent descriptor."""
    absolute = _absolute_campaign_path(path)
    parent_fd = _open_directory_nofollow(absolute.parent)
    fd = -1
    try:
        fd = os.open(
            absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd
        )
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_CAMPAIGN_BYTES:
            raise CampaignError(f"unsafe or oversized {label}")
        remaining = metadata.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(fd, min(remaining, 64 * 1024))
            if not chunk:
                raise CampaignError(f"truncated {label}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise CampaignError(f"changed {label}")
        return b"".join(chunks).decode("utf-8")
    except CampaignError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise CampaignError(f"unsafe or unreadable {label}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(parent_fd)


def _observation_name(value: object, location: str) -> str:
    candidate = _string(value, location)
    if not OBSERVATION_NAME.fullmatch(candidate):
        raise CampaignError(f"{location} must be a safe JSON filename")
    return candidate


def load_manifest(path: Path) -> CampaignManifest:
    """Load a campaign while rejecting silent schema widening."""
    try:
        root = _mapping(json.loads(_read_campaign_file(path, "campaign")), "campaign")
    except json.JSONDecodeError as exc:
        raise CampaignError("campaign must contain valid JSON") from exc
    expected_keys = {"schema_version", "campaign_id", "observations", "cases"}
    if set(root) != expected_keys:
        raise CampaignError("campaign fields do not match schema version 1")
    if root["schema_version"] != CAMPAIGN_SCHEMA_VERSION:
        raise CampaignError("unsupported campaign schema_version")
    raw_cases = root["cases"]
    if (
        not isinstance(raw_cases, list)
        or not raw_cases
        or len(raw_cases) > MAX_CAMPAIGN_CASES
    ):
        raise CampaignError("campaign.cases must be a bounded non-empty array")
    cases: list[CampaignCase] = []
    case_keys = {
        "case_id",
        "runtime",
        "runtime_version",
        "expected_skill",
        "invocation_type",
        "evidence_stage",
        "required_outcomes",
        "forbidden_outcomes",
        "unobservable_outcomes",
    }
    for index, raw_case in enumerate(raw_cases):
        location = f"campaign.cases[{index}]"
        item = _mapping(raw_case, location)
        if set(item) != case_keys:
            raise CampaignError(f"{location} fields do not match schema version 1")
        expected_skill_value = item["expected_skill"]
        if expected_skill_value is not None and not isinstance(
            expected_skill_value, str
        ):
            raise CampaignError(f"{location}.expected_skill must be a string or null")
        cases.append(
            CampaignCase(
                case_id=_case_id(item["case_id"], f"{location}.case_id"),
                runtime=_enum(item["runtime"], f"{location}.runtime", RUNTIMES),
                runtime_version=_string(
                    item["runtime_version"], f"{location}.runtime_version"
                ),
                expected_skill=expected_skill_value,
                invocation_type=_enum(
                    item["invocation_type"],
                    f"{location}.invocation_type",
                    INVOCATION_TYPES,
                ),
                evidence_stage=_enum(
                    item["evidence_stage"],
                    f"{location}.evidence_stage",
                    EVIDENCE_STAGES,
                ),
                required_outcomes=_outcomes(
                    item["required_outcomes"], f"{location}.required_outcomes"
                ),
                forbidden_outcomes=_outcomes(
                    item["forbidden_outcomes"], f"{location}.forbidden_outcomes"
                ),
                unobservable_outcomes=_outcomes(
                    item["unobservable_outcomes"], f"{location}.unobservable_outcomes"
                ),
            )
        )
    identifiers = [item.case_id for item in cases]
    if len(set(identifiers)) != len(identifiers):
        raise CampaignError("campaign case_id values must be unique")
    return CampaignManifest(
        schema_version=CAMPAIGN_SCHEMA_VERSION,
        campaign_id=_string(root["campaign_id"], "campaign.campaign_id"),
        observations=_observation_name(root["observations"], "campaign.observations"),
        cases=tuple(cases),
        source_directory=_absolute_campaign_path(path).parent,
    )


def _codex_metric_fixture(record: dict[str, object]) -> Metric:
    attributes = [
        KeyValue(key=key, value=AnyValue(string_value=value))
        for key in ("skill", "invoke_type", "status")
        if isinstance((value := record.get(key)), str)
    ]
    count = record.get("count")
    time_unix_nano = record.get("time_unix_nano")
    return Metric(
        name=str(record.get("name") or "codex.skill.injected"),
        sum=Sum(
            aggregation_temporality=AGGREGATION_TEMPORALITY_DELTA,
            is_monotonic=True,
            data_points=[
                NumberDataPoint(
                    attributes=attributes,
                    start_time_unix_nano=(
                        time_unix_nano - 1_000 if isinstance(time_unix_nano, int) else 0
                    ),
                    time_unix_nano=time_unix_nano
                    if isinstance(time_unix_nano, int)
                    else 0,
                    as_int=count if isinstance(count, int) else 0,
                )
            ],
        ),
    )


def _write_private_new(path: Path, content: bytes) -> None:
    """Write only a new owner-only regular file; never follow an output symlink."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise CampaignError("unsafe campaign temporary output")
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written <= 0:
                raise OSError("short campaign output write")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)


def _materialize_case(
    producer: str,
    records: list[object],
    case: CampaignCase,
    temporary_root: Path,
    case_number: int,
) -> tuple[tuple[SkillEvent, ...], int]:
    """Cross production seams using internal paths, never manifest identifiers."""
    case_root = temporary_root / f"case-{case_number}"
    case_root.mkdir(mode=0o700)
    store = EventStore(case_root)
    duplicate_deliveries = 0
    try:
        if producer == "pi-session":
            session = temporary_root / f"records-{case_number}.jsonl"
            _write_private_new(
                session,
                "".join(f"{json.dumps(record)}\n" for record in records).encode(),
            )
            stats = ingest_pi((session,), store)
            if stats.rejected:
                raise CampaignError(
                    f"campaign case {case.case_id} contains rejected Pi telemetry"
                )
            duplicate_deliveries = stats.duplicates
        elif producer == "codex-adapter":
            pending: list[SkillEvent] = []
            for raw_record in records:
                pending.extend(normalize_codex(_mapping(raw_record, "codex record")))
            retained = store.append_many(pending)
            duplicate_deliveries = len(retained) - sum(retained)
        elif producer == "codex-ingest":
            source = temporary_root / f"codex-{case_number}.json"
            _write_private_new(source, json.dumps(records).encode())
            stats = ingest_codex((source,), store)
            if stats.rejected or stats.malformed_records_skipped:
                raise CampaignError(
                    f"campaign case {case.case_id} contains rejected Codex telemetry"
                )
            duplicate_deliveries = stats.duplicates
        elif producer == "claude-adapter":
            pending = []
            for raw_record in records:
                event = normalize_claude(_mapping(raw_record, "claude record"))
                if event is not None:
                    pending.append(event)
            retained = store.append_many(pending)
            duplicate_deliveries = len(retained) - sum(retained)
        elif producer == "claude-hook":
            pending = []
            inventory = {case.expected_skill or "": case.expected_skill or ""}
            for raw_record in records:
                record = _mapping(raw_record, "claude hook record")
                alias = record.get("command_name")
                tool_input = record.get("tool_input")
                if isinstance(alias, str) and case.expected_skill:
                    inventory[alias.casefold().lstrip("/")] = case.expected_skill
                if isinstance(tool_input, dict):
                    skill = tool_input.get("skill")
                    if isinstance(skill, str) and case.expected_skill:
                        inventory[skill.casefold().lstrip("/")] = case.expected_skill
                event = normalize_claude_hook(record, inventory)
                if event is not None:
                    pending.append(event)
            retained = store.append_many(pending)
            duplicate_deliveries = len(retained) - sum(retained)
        elif producer == "codex-metric":
            pending = []
            for raw_record in records:
                pending.extend(
                    normalize_codex_metric(
                        _codex_metric_fixture(
                            _mapping(raw_record, "codex metric record")
                        )
                    )
                )
            retained = store.append_many(pending)
            duplicate_deliveries = len(retained) - sum(retained)
        else:
            raise CampaignError(
                f"campaign case {case.case_id} has an unsupported producer"
            )
        events = store.read_events()
    except CampaignError:
        raise
    except (ContractError, OSError, ValueError) as exc:
        raise CampaignError(
            f"campaign case {case.case_id} failed normalization"
        ) from exc
    if any(event.agent_system != case.runtime for event in events):
        raise CampaignError("case observation runtime does not match manifest")
    return events, duplicate_deliveries


def load_observations(
    path: Path, manifest: CampaignManifest
) -> dict[str, CaseObservation]:
    """Materialize packaged sanitized runtime records through production seams."""
    try:
        root = _mapping(
            json.loads(_read_campaign_file(path, "observations")), "observations"
        )
    except json.JSONDecodeError as exc:
        raise CampaignError("observations must contain valid JSON") from exc
    if set(root) != {"schema_version", "campaign_id", "cases"}:
        raise CampaignError("observation fields do not match schema version 1")
    if root["schema_version"] != CAMPAIGN_SCHEMA_VERSION:
        raise CampaignError("unsupported observation schema_version")
    if root["campaign_id"] != manifest.campaign_id:
        raise CampaignError("observation campaign_id does not match manifest")
    raw_cases = _mapping(root["cases"], "observations.cases")
    declared = {item.case_id for item in manifest.cases}
    if set(raw_cases) != declared:
        raise CampaignError("observation cases must exactly match manifest cases")
    observations: dict[str, CaseObservation] = {}
    cases_by_id = {item.case_id: item for item in manifest.cases}
    with tempfile.TemporaryDirectory(prefix="skill-telemetry-campaign-") as temporary:
        temporary_root = Path(temporary)
        for case_number, (case_id, raw_observation) in enumerate(raw_cases.items()):
            item = _mapping(raw_observation, f"observations.cases.{case_id}")
            if set(item) != {"producer", "records", "unsupported_outcomes"}:
                raise CampaignError(
                    "case observation fields do not match schema version 1"
                )
            producer = _string(
                item["producer"], f"observations.cases.{case_id}.producer"
            )
            records = item["records"]
            if not isinstance(records, list):
                raise CampaignError("case observation records must be an array")
            events, duplicate_deliveries = _materialize_case(
                producer, records, cases_by_id[case_id], temporary_root, case_number
            )
            observations[case_id] = CaseObservation(
                events=events,
                unsupported_outcomes=_outcomes(
                    item["unsupported_outcomes"],
                    f"observations.cases.{case_id}.unsupported_outcomes",
                ),
                duplicate_deliveries=duplicate_deliveries,
            )
    return observations


def _event_key(event: SkillEvent) -> str:
    if event.activation_id:
        return event.activation_id
    return json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))


def _matching_event(
    event: SkillEvent, outcome: str, expected_skill: str | None
) -> bool:
    if event.evidence_type != outcome:
        return False
    return expected_skill is None or event.skill_name == expected_skill


def _ratio_dict(ratio: Ratio) -> dict[str, object]:
    return asdict(ratio)


def score_campaign(
    manifest: CampaignManifest,
    observations: dict[str, CaseObservation],
    *,
    gate_set: Literal["acceptance", "delivery"] = "acceptance",
) -> dict[str, object]:
    """Score evidence with one support model and an explicit campaign gate set."""
    case_results: list[dict[str, object]] = []
    unique_by_case: dict[str, tuple[SkillEvent, ...]] = {}
    raw_event_count = 0
    duplicate_count = 0
    stage_names: set[str] = set()
    false_positives = 0
    provenance_errors = 0

    for case in manifest.cases:
        observation = observations[case.case_id]
        raw_event_count += len(observation.events) + observation.duplicate_deliveries
        duplicate_count += observation.duplicate_deliveries
        unique: dict[str, SkillEvent] = {}
        for event in observation.events:
            key = _event_key(event)
            if key in unique:
                duplicate_count += 1
            else:
                unique[key] = event
        events = tuple(unique.values())
        unique_by_case[case.case_id] = events
        # SkillEvent permits future safe evidence tokens, but the public v1
        # report has a deliberately closed stage vocabulary. An unrecognized
        # token is a failed case unless the manifest explicitly declares the
        # v1 unsupported-stage accounting outcome.
        unrecognized_stages = sorted(
            {
                event.evidence_type
                for event in events
                if event.evidence_type not in EVIDENCE_OUTCOMES
            }
        )
        stage_names.update(
            event.evidence_type
            for event in events
            if event.evidence_type in EVIDENCE_OUTCOMES
        )
        stage_names.update(case.required_outcomes)
        stage_names.update(case.forbidden_outcomes)
        provenance_errors += sum(
            event.evidence_type == "provenance-error" for event in events
        )

        missing = [
            outcome
            for outcome in case.required_outcomes
            if not any(
                _matching_event(event, outcome, case.expected_skill) for event in events
            )
        ]
        forbidden = [
            outcome
            for outcome in case.forbidden_outcomes
            if any(event.evidence_type == outcome for event in events)
        ]
        wrong_skill = [
            event.evidence_type
            for event in events
            if event.evidence_type in ACTIVATION_STAGES
            and case.expected_skill is not None
            and event.skill_name != case.expected_skill
            and event.status not in UNKNOWN_STATUSES
        ]
        false_positives += len(forbidden) + len(wrong_skill)
        unobservable_acknowledged = set(observation.unsupported_outcomes) == set(
            case.unobservable_outcomes
        )
        unknown_stages_accounted = not unrecognized_stages or (
            UNSUPPORTED_EVIDENCE_STAGE in case.unobservable_outcomes
            and UNSUPPORTED_EVIDENCE_STAGE in observation.unsupported_outcomes
        )
        accepted = (
            not missing
            and not forbidden
            and not wrong_skill
            and unobservable_acknowledged
            and unknown_stages_accounted
        )
        status = (
            "unobservable"
            if case.unobservable_outcomes and accepted
            else ("passed" if accepted else "failed")
        )
        case_results.append(
            {
                "case_id": case.case_id,
                "runtime": case.runtime,
                "runtime_version": case.runtime_version,
                "invocation_type": case.invocation_type,
                "evidence_stage": case.evidence_stage,
                "status": status,
                "raw_events": len(observation.events)
                + observation.duplicate_deliveries,
                "unique_events": len(events),
                "duplicates_removed": (
                    len(observation.events)
                    - len(events)
                    + observation.duplicate_deliveries
                ),
                "missing_required": missing,
                "forbidden_observed": forbidden,
                "wrong_skill_observed": wrong_skill,
                "unrecognized_evidence_stages": unrecognized_stages,
                "unobservable_outcomes": list(case.unobservable_outcomes),
                "unsupported_acknowledged": unobservable_acknowledged,
            }
        )

    stage_metrics: dict[str, object] = {}
    for stage in sorted(stage_names):
        observed = 0
        unknown = 0
        required = 0
        matched = 0
        forbidden_count = 0
        for case in manifest.cases:
            events = unique_by_case[case.case_id]
            stage_events = [event for event in events if event.evidence_type == stage]
            observed += len(stage_events)
            unknown += sum(
                event.evidence_confidence == "unknown"
                or event.status in UNKNOWN_STATUSES
                for event in stage_events
            )
            if stage in case.required_outcomes:
                required += 1
                matched += any(
                    _matching_event(event, stage, case.expected_skill)
                    for event in stage_events
                )
            if stage in case.forbidden_outcomes:
                forbidden_count += len(stage_events)
        known_predictions = 0
        true_predictions = 0
        for case in manifest.cases:
            stage_events = [
                event
                for event in unique_by_case[case.case_id]
                if event.evidence_type == stage
                and event.evidence_confidence != "unknown"
                and event.status not in UNKNOWN_STATUSES
            ]
            if not stage_events:
                continue
            known_predictions += len(stage_events)
            if stage in case.required_outcomes:
                true_predictions += sum(
                    _matching_event(event, stage, case.expected_skill)
                    for event in stage_events
                )
        stage_metrics[stage] = {
            "observed": observed,
            "required": required,
            "required_matched": matched,
            "forbidden_observed": forbidden_count,
            "precision": _ratio_dict(Ratio.make(true_predictions, known_predictions)),
            "recall": _ratio_dict(Ratio.make(matched, required)),
            "unknown_rate": _ratio_dict(Ratio.make(unknown, observed)),
        }

    explicit_positive = [
        case
        for case in manifest.cases
        if case.invocation_type == "explicit"
        and not case.unobservable_outcomes
        and case.expected_skill is not None
    ]
    explicit_true_predictions = 0
    explicit_recalled_cases = 0
    explicit_predictions = 0
    for case in manifest.cases:
        if case.invocation_type not in {"explicit", "negative-control"}:
            continue
        events = unique_by_case[case.case_id]
        predictions = [
            event
            for event in events
            if event.evidence_type in ACTIVATION_STAGES
            and event.status not in UNKNOWN_STATUSES
        ]
        explicit_predictions += len(predictions)
        if case in explicit_positive:
            matching = sum(
                event.skill_name == case.expected_skill for event in predictions
            )
            explicit_true_predictions += matching
            explicit_recalled_cases += matching > 0
    explicit_precision = Ratio.make(explicit_true_predictions, explicit_predictions)
    explicit_recall = Ratio.make(explicit_recalled_cases, len(explicit_positive))

    candidate_keys: set[tuple[str, str, str]] = set()
    loaded_keys: set[tuple[str, str, str]] = set()
    candidate_total = 0
    loaded_total = 0
    for case in manifest.cases:
        if case.evidence_stage != "candidate-to-load":
            continue
        for event in unique_by_case[case.case_id]:
            if event.evidence_type == "natural-language-candidate":
                candidate_total += 1
                if event.session_id and event.turn_id and event.skill_name:
                    candidate_keys.add(
                        (event.session_id, event.turn_id, event.skill_name)
                    )
            if event.evidence_type == "canonical-file-read":
                loaded_total += 1
                if event.session_id and event.turn_id and event.skill_name:
                    loaded_keys.add((event.session_id, event.turn_id, event.skill_name))
    matched_pairs = len(candidate_keys & loaded_keys)
    candidate_conversion = Ratio.make(matched_pairs, candidate_total)
    correlation_quality = Ratio.make(2 * matched_pairs, candidate_total + loaded_total)
    unobservable_cases = sum(
        bool(case.unobservable_outcomes) for case in manifest.cases
    )
    unknown_rate = Ratio.make(unobservable_cases, len(manifest.cases))

    duplicate_proof = (
        duplicate_count > 0 and raw_event_count - duplicate_count < raw_event_count
    )
    resume_reimport_proof = any(
        case.invocation_type == "resume-reimport"
        and result["status"] == "passed"
        and cast(int, result["duplicates_removed"]) > 0
        for case, result in zip(manifest.cases, case_results, strict=True)
    )
    case_support_passed = all(result["status"] != "failed" for result in case_results)
    if gate_set == "acceptance":
        gates = {
            "supported_explicit_precision_100": explicit_precision.value == 1.0,
            "supported_explicit_recall_100": explicit_recall.value == 1.0,
            "zero_false_positives": false_positives == 0,
            "pi_candidate_to_load_100": candidate_conversion.value == 1.0,
            "pi_correlation_quality_100": correlation_quality.value == 1.0,
            "duplicate_events_do_not_inflate": duplicate_proof,
            "resume_reimport_no_double_count": resume_reimport_proof,
            "no_unexplained_provenance_errors": provenance_errors == 0,
            "unobservable_evidence_explicit": all(
                result["unsupported_acknowledged"] for result in case_results
            ),
        }
    else:
        gates = {
            "required_evidence_supported": case_support_passed,
            "zero_false_positives": false_positives == 0,
            "no_unexplained_provenance_errors": provenance_errors == 0,
            "unobservable_evidence_explicit": all(
                result["unsupported_acknowledged"] for result in case_results
            ),
        }
    return {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": manifest.campaign_id,
        "passed": all(gates.values()) and case_support_passed,
        "gates": gates,
        "metrics": {
            "supported_explicit_precision": _ratio_dict(explicit_precision),
            "supported_explicit_recall": _ratio_dict(explicit_recall),
            "unknown_rate": _ratio_dict(unknown_rate),
            "deduplication": {
                "raw_events": raw_event_count,
                "unique_events": raw_event_count - duplicate_count,
                "duplicates_removed": duplicate_count,
            },
            "candidate_to_load_conversion": _ratio_dict(candidate_conversion),
            "correlation_quality": _ratio_dict(correlation_quality),
            "false_positives": false_positives,
            "provenance_errors": provenance_errors,
            "stages": stage_metrics,
        },
        "cases": case_results,
    }


def render_markdown(report: dict[str, object]) -> str:
    """Render a concise human companion to the machine-readable report."""
    metrics = cast(dict[str, object], report["metrics"])
    precision = cast(dict[str, object], metrics["supported_explicit_precision"])
    recall = cast(dict[str, object], metrics["supported_explicit_recall"])
    conversion = cast(dict[str, object], metrics["candidate_to_load_conversion"])
    correlation = cast(dict[str, object], metrics["correlation_quality"])
    dedupe = cast(dict[str, object], metrics["deduplication"])
    cases = cast(list[dict[str, object]], report["cases"])
    lines = [
        f"# Skill telemetry campaign: {report['campaign_id']}",
        "",
        f"**Result:** {'PASS' if report['passed'] else 'FAIL'}",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Supported explicit precision | {precision['numerator']}/{precision['denominator']} |",
        f"| Supported explicit recall | {recall['numerator']}/{recall['denominator']} |",
        f"| Candidate-to-load conversion | {conversion['numerator']}/{conversion['denominator']} |",
        f"| Correlation quality | {correlation['numerator']}/{correlation['denominator']} |",
        f"| Duplicate events removed | {dedupe['duplicates_removed']} |",
        f"| False positives | {metrics['false_positives']} |",
        f"| Provenance errors | {metrics['provenance_errors']} |",
        "",
        "## Cases",
        "",
        "| Case | Runtime | Status |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {case['case_id']} | {case['runtime']} {case['runtime_version']} | {case['status']} |"
        for case in cases
    )
    producer_checks = report.get("producer_checks")
    if isinstance(producer_checks, dict):
        lines.extend(
            [
                "",
                "## Producer checks",
                "",
                "| Check | Status |",
                "|---|---|",
            ]
        )
        lines.extend(
            f"| {name} | {value['status']} |"
            for name, value in sorted(producer_checks.items())
            if isinstance(name, str) and isinstance(value, dict)
        )
    return "\n".join(lines) + "\n"
