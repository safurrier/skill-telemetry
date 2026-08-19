"""Versioned runtime-neutral skill telemetry contract."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Self, cast

from skill_telemetry.privacy import safe_name

SCHEMA_VERSION = 1
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
EVENT_RE = re.compile(r"^agent\.(?:skill|runtime)\.[a-z][a-z0-9.-]{0,63}$")
TOKEN_RE = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
AGENT_SYSTEMS = frozenset({"pi", "claude", "codex", "local"})
CONFIDENCE_LEVELS = frozenset(
    {"observed", "qualified", "candidate", "classified", "unknown"}
)
MAX_EVENT_COUNT = 1_000_000


class ContractError(ValueError):
    """Raised when an event violates the committed local contract."""


@dataclass(frozen=True, slots=True)
class SkillEvent:
    """Schema v1 event. Optional IDs remain absent rather than fabricated."""

    schema_version: int
    event_name: str
    agent_system: str
    trigger: str
    evidence_type: str
    evidence_confidence: str
    status: str
    timestamp: str
    session_id: str | None = None
    turn_id: str | None = None
    activation_id: str | None = None
    skill_name: str | None = None
    skill_source: str | None = None
    skill_content_hash: str | None = None
    signal_name: str | None = None
    count: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> Self:
        """Validate and construct an event, rejecting silent schema widening."""
        allowed = {field.name for field in fields(cls)}
        unknown = set(value) - allowed
        if unknown:
            raise ContractError("event contains unknown fields")
        missing = sorted(
            name
            for name in (
                "schema_version",
                "event_name",
                "agent_system",
                "trigger",
                "evidence_type",
                "evidence_confidence",
                "status",
                "timestamp",
            )
            if name not in value
        )
        if missing:
            raise ContractError(f"missing event fields: {', '.join(missing)}")
        event = cls(
            schema_version=cast(int, value["schema_version"]),
            event_name=cast(str, value["event_name"]),
            agent_system=cast(str, value["agent_system"]),
            trigger=cast(str, value["trigger"]),
            evidence_type=cast(str, value["evidence_type"]),
            evidence_confidence=cast(str, value["evidence_confidence"]),
            status=cast(str, value["status"]),
            timestamp=cast(str, value["timestamp"]),
            session_id=cast(str | None, value.get("session_id")),
            turn_id=cast(str | None, value.get("turn_id")),
            activation_id=cast(str | None, value.get("activation_id")),
            skill_name=cast(str | None, value.get("skill_name")),
            skill_source=cast(str | None, value.get("skill_source")),
            skill_content_hash=cast(str | None, value.get("skill_content_hash")),
            signal_name=cast(str | None, value.get("signal_name")),
            count=cast(int | None, value.get("count")),
        )
        event.validate()
        return event

    def validate(self) -> None:
        """Validate contract, privacy, and bounded identifier invariants."""
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError("unsupported schema_version")
        if (
            not EVENT_RE.fullmatch(self.event_name)
            or safe_name(self.event_name) != self.event_name
        ):
            raise ContractError("event_name is not a supported runtime-neutral name")
        if self.agent_system not in AGENT_SYSTEMS:
            raise ContractError("agent_system is not recognized")
        for label, value in (
            ("trigger", self.trigger),
            ("evidence_type", self.evidence_type),
            ("status", self.status),
        ):
            if not TOKEN_RE.fullmatch(value) or safe_name(value) != value:
                raise ContractError(f"{label} must be a safe bounded lowercase token")
        if self.evidence_confidence not in CONFIDENCE_LEVELS:
            raise ContractError("evidence_confidence is not recognized")
        for digest_label, digest_value in (
            ("session_id", self.session_id),
            ("turn_id", self.turn_id),
            ("activation_id", self.activation_id),
            ("skill_content_hash", self.skill_content_hash),
        ):
            if digest_value is not None and not HASH_RE.fullmatch(digest_value):
                raise ContractError(f"{digest_label} must be a sha256 pseudonym")
        for identifier_label, identifier_value in (
            ("skill_name", self.skill_name),
            ("skill_source", self.skill_source),
            ("signal_name", self.signal_name),
        ):
            if (
                identifier_value is not None
                and safe_name(identifier_value) != identifier_value
            ):
                raise ContractError(
                    f"{identifier_label} is not a safe bounded identifier"
                )
        if self.count is not None and (
            isinstance(self.count, bool)
            or not isinstance(self.count, int)
            or not 1 <= self.count <= MAX_EVENT_COUNT
        ):
            raise ContractError("count must be a bounded positive integer")
        try:
            datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractError("timestamp must be ISO-8601") from exc

    def to_dict(self) -> dict[str, object]:
        """Return the canonical sparse JSON representation."""
        self.validate()
        return {key: value for key, value in asdict(self).items() if value is not None}
