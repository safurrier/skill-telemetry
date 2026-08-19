"""Normalization adapters for documented Claude and Codex signals."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import cast

from skill_telemetry.claude_hooks import map_invocation_trigger
from skill_telemetry.contract import SkillEvent
from skill_telemetry.privacy import pseudonym, safe_name

EXPLICIT_CODEX = re.compile(r"^\$([A-Za-z0-9][A-Za-z0-9._+-]{0,127})$")
CLAUDE_REDACTED_SKILL_NAMES = frozenset({"custom", "custom_skill", "redacted"})


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def attributes(source: dict[str, object]) -> dict[str, object]:
    value = source.get("attributes", {})
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def first(mapping: dict[str, object], *names: str) -> object | None:
    for name in names:
        value = mapping.get(name)
        if value is not None:
            return value
    return None


def activation_digest(
    agent_system: str,
    session_id: str | None,
    turn_id: str | None,
    skill_name: str | None,
    trigger: str,
    evidence_type: str,
    occurrence_id: object | None = None,
) -> str:
    """Create a stable dedupe key including an opaque runtime occurrence identity."""
    parts = (
        agent_system,
        session_id or "",
        turn_id or "",
        skill_name or "",
        trigger,
        evidence_type,
        str(occurrence_id) if occurrence_id is not None else "",
    )
    return pseudonym("|".join(parts), namespace="activation") or ""


def normalize_claude(source: dict[str, object]) -> SkillEvent | None:
    """Normalize Claude's native skill event without retaining non-allowlisted fields."""
    signal = first(source, "event_name", "name", "event")
    if signal != "claude_code.skill_activated":
        return None
    attrs = attributes(source)
    skill_name = safe_name(first(attrs, "skill_name", "skill.name", "skill"))
    if skill_name is not None and skill_name.casefold() in CLAUDE_REDACTED_SKILL_NAMES:
        skill_name = None
    session_id = pseudonym(
        first(attrs, "session.id", "session_id", "conversation.id"),
        namespace="claude-session",
    )
    turn_id = pseudonym(
        first(attrs, "prompt.id", "turn.id", "turn_id"), namespace="claude-turn"
    )
    raw_trigger = (
        safe_name(first(attrs, "invocation_trigger", "trigger", "skill.trigger"))
        or "native"
    )
    trigger = map_invocation_trigger(raw_trigger, default=raw_trigger)
    if trigger not in {"explicit", "proactive", "nested"}:
        trigger = "native"
    status = "loaded" if skill_name else "identity-redacted"
    occurrence = first(source, "occurrence_id", "event_id", "record_id") or first(
        attrs,
        "event.id",
        "event_id",
        "record.id",
        "record_id",
        "trace_id",
        "span_id",
        "timestamp",
    )
    activation_id = activation_digest(
        "claude", session_id, turn_id, skill_name, trigger, "native-event", occurrence
    )
    return SkillEvent.from_mapping(
        {
            "schema_version": 1,
            "event_name": "agent.skill.activation",
            "agent_system": "claude",
            "session_id": session_id,
            "turn_id": turn_id,
            "activation_id": activation_id,
            "skill_name": skill_name,
            "skill_source": "claude-native",
            "trigger": trigger,
            "evidence_type": "native-event",
            "evidence_confidence": "observed",
            "status": status,
            "timestamp": str(source.get("timestamp") or now_iso()),
            "signal_name": "claude_code.skill_activated",
        }
    )


def normalize_codex(source: dict[str, object]) -> list[SkillEvent]:
    """Normalize structured skill input and qualified Codex fallback evidence.

    Opaque runtime identifiers take precedence. In their absence, structured
    skill inputs use only their method and ordinal inside the intrinsic turn; this
    deliberately excludes input-file ordering, paths, prompts, and content.
    """
    params_value = source.get("params", {})
    params = (
        cast(dict[str, object], params_value) if isinstance(params_value, dict) else {}
    )
    session_raw = first(params, "threadId", "thread_id") or first(
        source, "threadId", "thread_id", "conversation_id"
    )
    turn_raw = first(params, "turnId", "turn_id") or first(source, "turnId", "turn_id")
    session_id = pseudonym(session_raw, namespace="codex-session")
    turn_id = pseudonym(turn_raw, namespace="codex-turn")
    timestamp = str(source.get("timestamp") or now_iso())
    events: list[SkillEvent] = []

    inputs = params.get("input", [])
    if isinstance(inputs, list):
        for index, item in enumerate(inputs):
            if not isinstance(item, dict) or item.get("type") != "skill":
                continue
            skill_name = safe_name(item.get("name"))
            if skill_name:
                occurrence = first(
                    item, "id", "item_id", "tool_use_id", "prompt_id", "request_id"
                )
                # Array position is structural runtime metadata, not user content.
                events.append(
                    build_codex_event(
                        session_id=session_id,
                        turn_id=turn_id,
                        skill_name=skill_name,
                        trigger="structured-input",
                        evidence_type="structured-input",
                        confidence="observed",
                        timestamp=timestamp,
                        signal_name="codex.app_server.skill_input",
                        occurrence_id=(
                            occurrence
                            if occurrence is not None
                            else ("skill-input", source.get("method"), index)
                        ),
                    )
                )

    explicit = source.get("explicit_skill")
    match = (
        EXPLICIT_CODEX.fullmatch(explicit.strip())
        if isinstance(explicit, str)
        else None
    )
    if match:
        # Prefer an opaque runtime occurrence. Timestamp, command text, paths,
        # and prompt data cannot establish occurrence identity. Without one,
        # direct and ingested records intentionally receive conservative semantic
        # dedupe rather than an input-file-dependent synthetic identity.
        occurrence = first(
            source, "event_id", "request_id", "item_id", "prompt_id", "id"
        ) or first(params, "event_id", "request_id", "item_id", "prompt_id", "id")
        events.append(
            build_codex_event(
                session_id=session_id,
                turn_id=turn_id,
                skill_name=match.group(1),
                trigger="explicit-command",
                evidence_type="explicit-command",
                confidence="qualified",
                timestamp=timestamp,
                signal_name="codex.explicit_skill",
                occurrence_id=occurrence,
            )
        )

    # Canonical reads are deliberately absent here. Qualification requires the
    # generated command-action plus an independently resolved inventory path in
    # ingest_codex(); caller-asserted names and hashes are never sufficient.
    return events


def build_codex_event(
    *,
    session_id: str | None,
    turn_id: str | None,
    skill_name: str,
    trigger: str,
    evidence_type: str,
    confidence: str,
    timestamp: str,
    signal_name: str,
    skill_content_hash: str | None = None,
    occurrence_id: object | None = None,
) -> SkillEvent:
    activation_id = activation_digest(
        "codex", session_id, turn_id, skill_name, trigger, evidence_type, occurrence_id
    )
    return SkillEvent.from_mapping(
        {
            "schema_version": 1,
            "event_name": "agent.skill.activation",
            "agent_system": "codex",
            "session_id": session_id,
            "turn_id": turn_id,
            "activation_id": activation_id,
            "skill_name": skill_name,
            "skill_source": "codex",
            "skill_content_hash": skill_content_hash,
            "trigger": trigger,
            "evidence_type": evidence_type,
            "evidence_confidence": confidence,
            "status": "loaded",
            "timestamp": timestamp,
            "signal_name": signal_name,
        }
    )
