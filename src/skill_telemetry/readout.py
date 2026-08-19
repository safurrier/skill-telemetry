"""Pure evidence-stage-preserving local skill readout."""

from __future__ import annotations

from pathlib import Path

from skill_telemetry.store import EventStore, state_directory

RUNTIME_EVENT_PREFIX = "agent.runtime."
SKILL_EVENT_PREFIX = "agent.skill."
UNSUPPORTED_STATUSES = {"identity-redacted", "unsupported"}


def build_readout(directory: Path | None = None) -> dict[str, int]:
    """Count retained skill evidence without scanning or importing runtime state."""
    root = directory or state_directory()
    result = {
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
    if not root.exists():
        return result
    for event in EventStore(root).iter_events():
        result["total_events"] += 1
        if event.event_name.startswith(RUNTIME_EVENT_PREFIX):
            result["runtime_telemetry_events"] += 1
            if event.signal_name == "unknown":
                result["unknown_runtime_telemetry_events"] += 1
            continue
        if not event.event_name.startswith(SKILL_EVENT_PREFIX):
            continue
        result["skill_evidence_events"] += 1
        evidence = event.evidence_type
        if evidence in {"native-event", "structured-input", "structured-hook"}:
            result["native_or_structured_activations"] += 1
            if evidence == "structured-hook":
                result["structured_hook_activations"] += 1
        elif evidence == "native-metric":
            result["native_metric_events"] += 1
            result["aggregate_skill_invocations"] += event.count or 0
        elif evidence == "explicit-command":
            result["explicit_command_activations"] += 1
        elif evidence == "prompt-expansion":
            result["prompt_expansions"] += 1
        elif evidence == "canonical-file-read":
            result["file_read_evidence"] += 1
        elif evidence == "natural-language-candidate":
            result["natural_language_candidates"] += 1
        if (
            evidence in {"unobservable", "provenance-error"}
            or event.status in UNSUPPORTED_STATUSES
        ):
            result["unsupported_or_redacted_events"] += 1
    result["unknown_or_unobservable"] = (
        result["unsupported_or_redacted_events"]
        + result["unknown_runtime_telemetry_events"]
    )
    return result
