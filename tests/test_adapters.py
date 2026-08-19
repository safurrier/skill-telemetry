from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_telemetry.adapters import normalize_claude, normalize_codex
from skill_telemetry.ingest import ingest_codex
from skill_telemetry.store import EventStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_claude_native_skill_event_maps_trigger_without_raw_content() -> None:
    source = {
        "event_name": "claude_code.skill_activated",
        "timestamp": "2026-07-17T12:00:00Z",
        "attributes": {
            "session.id": "private-session",
            "prompt.id": "private-turn",
            "skill_name": "example-capture",
            "trigger": "nested",
            "prompt": "PROHIBITED SENTINEL",
            "tool.input": {"private": True},
        },
    }
    result = normalize_claude(source)
    assert result is not None
    payload = result.to_dict()
    assert payload["agent_system"] == "claude"
    assert payload["skill_name"] == "example-capture"
    assert payload["trigger"] == "nested"
    assert "PROHIBITED" not in str(payload)
    assert payload["session_id"].startswith("sha256:")


def test_claude_secret_like_skill_identity_is_redacted() -> None:
    result = normalize_claude(
        {
            "event_name": "claude_code.skill_activated",
            "attributes": {
                "session.id": "private-session",
                "skill_name": "sk-proj-SECRET123",
                "trigger": "explicit",
            },
        }
    )

    assert result is not None
    assert result.skill_name is None
    assert result.status == "identity-redacted"
    assert "SECRET123" not in str(result.to_dict())


@pytest.mark.parametrize(
    "redacted_name",
    [None, "custom", "Custom", "custom_skill", "CUSTOM_SKILL", "redacted", "REDACTED"],
)
def test_claude_redacted_identity_remains_unknown_instead_of_invented(
    redacted_name: str | None,
) -> None:
    attributes = {"session.id": "s", "trigger": "proactive"}
    if redacted_name is not None:
        attributes["skill_name"] = redacted_name
    result = normalize_claude(
        {
            "event_name": "claude_code.skill_activated",
            "attributes": attributes,
        }
    )
    assert result is not None
    assert result.skill_name is None
    assert result.status == "identity-redacted"


def test_codex_structured_skill_input_is_observed() -> None:
    source = {
        "method": "turn/start",
        "params": {
            "threadId": "thread-private",
            "turnId": "turn-private",
            "input": [
                {
                    "type": "skill",
                    "name": "example-capture",
                    "path": "/private/absolute/SKILL.md",
                }
            ],
        },
    }
    events = normalize_codex(source)
    assert len(events) == 1
    payload = events[0].to_dict()
    assert payload["evidence_type"] == "structured-input"
    assert payload["skill_name"] == "example-capture"
    assert "/private/" not in str(payload)


def test_codex_secret_like_structured_name_is_not_activation_evidence() -> None:
    events = normalize_codex(
        {
            "method": "turn/start",
            "params": {
                "threadId": "thread-private",
                "input": [{"type": "skill", "name": "sk-proj-SECRET123"}],
            },
        }
    )

    assert events == []


def test_sanitized_runtime_fixtures_normalize_against_schema() -> None:
    claude = normalize_claude(
        json.loads((FIXTURES / "claude-skill-activated.json").read_text())
    )
    historical = json.loads(
        (FIXTURES / "claude-2.1.211-skill-activated.json").read_text()
    )
    historical_claude = normalize_claude(
        {
            "event_name": historical["expected"]["signal_name"],
            "attributes": historical["record"]["attributes"],
        }
    )
    codex = normalize_codex(
        json.loads((FIXTURES / "codex-app-server-skill.json").read_text())
    )
    assert claude is not None and historical_claude is not None
    assert claude.to_dict()["schema_version"] == 1
    assert historical_claude.to_dict()["schema_version"] == 1
    assert historical_claude.status == historical["expected"]["status"]
    assert codex[0].to_dict()["schema_version"] == 1


def test_native_claude_occurrence_identity_preserves_repeated_turn_events(
    tmp_path: Path,
) -> None:
    base = {
        "event_name": "claude_code.skill_activated",
        "attributes": {
            "session.id": "session",
            "prompt.id": "turn",
            "skill_name": "example-capture",
        },
    }
    first = normalize_claude({**base, "occurrence_id": "opaque-record-1"})
    repeated = normalize_claude({**base, "occurrence_id": "opaque-record-2"})
    replay = normalize_claude({**base, "occurrence_id": "opaque-record-1"})
    assert first is not None and repeated is not None and replay is not None
    assert first.activation_id != repeated.activation_id
    store = EventStore(tmp_path / "claude")
    assert store.append_many((first, repeated, replay)) == (True, True, False)


def test_codex_occurrence_identity_preserves_repeated_structured_items(
    tmp_path: Path,
) -> None:
    events = normalize_codex(
        {
            "params": {
                "threadId": "thread",
                "turnId": "turn",
                "input": [
                    {"type": "skill", "name": "example-capture", "id": "one"},
                    {"type": "skill", "name": "example-capture", "id": "two"},
                ],
            }
        }
    )
    assert len(events) == 2
    assert events[0].activation_id != events[1].activation_id
    store = EventStore(tmp_path / "codex")
    assert store.append_many((*events, *events)) == (True, True, False, False)


def test_codex_explicit_occurrences_are_distinct_and_replays_dedupe(
    tmp_path: Path,
) -> None:
    base = {
        "thread_id": "thread",
        "turn_id": "turn",
        "explicit_skill": "$example-capture",
    }
    first = normalize_codex({**base, "event_id": "one"})[0]
    second = normalize_codex({**base, "event_id": "two"})[0]
    replay = normalize_codex({**base, "event_id": "one"})[0]
    assert first.activation_id != second.activation_id
    assert EventStore(tmp_path / "explicit").append_many((first, second, replay)) == (
        True,
        True,
        False,
    )


def test_codex_explicit_direct_input_without_identity_is_conservatively_deduped() -> (
    None
):
    record = {
        "thread_id": "thread",
        "turn_id": "turn",
        "timestamp": "2026-01-01T00:00:00Z",
        "explicit_skill": "$example-capture",
    }
    first = normalize_codex(record)[0]
    replay = normalize_codex(record)[0]
    assert first.activation_id == replay.activation_id


def test_codex_ingest_dedupes_equivalent_same_turn_explicit_records(
    tmp_path: Path,
) -> None:
    records = [
        {
            "thread_id": "thread",
            "turn_id": "turn",
            "timestamp": "2026-01-01T00:00:00Z",
            "explicit_skill": "$example-capture",
        },
        {
            "thread_id": "thread",
            "turn_id": "turn",
            "timestamp": "2026-01-01T00:00:00Z",
            "explicit_skill": "$example-capture",
        },
    ]
    source = tmp_path / "explicit.json"
    source.write_text(json.dumps(records))
    store = EventStore(tmp_path / "explicit")

    first = ingest_codex((source,), store)
    replay = ingest_codex((source,), store)

    assert (first.imported, first.duplicates) == (1, 1)
    assert (replay.imported, replay.duplicates) == (0, 2)


def test_codex_canonical_occurrences_are_distinct_and_replays_dedupe(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: example-capture\n---\n")
    historical = json.loads((FIXTURES / "codex-0.144.5-command-read.json").read_text())
    template = historical["request"]
    assert isinstance(template, dict)
    records = []
    for item in ("one", "two", "one"):
        params = dict(template["params"])
        params.update(
            {
                "threadId": "thread",
                "turnId": "turn",
                "itemId": item,
                "cwd": str(tmp_path),
                "commandActions": [{"type": "read", "path": str(skill)}],
            }
        )
        records.append(
            {
                "method": template["method"],
                "timestamp": template["timestamp"],
                "params": params,
            }
        )
    source = tmp_path / "events.json"
    source.write_text(json.dumps(records))
    store = EventStore(tmp_path / "canonical")
    stats = ingest_codex((source,), store, skills=(("example-capture", skill),))
    assert (stats.imported, stats.duplicates) == (2, 1)


def test_codex_skill_input_identity_is_batch_and_input_order_independent(
    tmp_path: Path,
) -> None:
    first = {
        "method": "turn/start",
        "params": {
            "threadId": "thread-a",
            "turnId": "turn-b",
            "input": [{"type": "skill", "name": "example-capture"}],
        },
    }
    unrelated = {
        "method": "turn/start",
        "params": {
            "threadId": "other-thread",
            "turnId": "other-turn",
            "input": [{"type": "skill", "name": "other-skill"}],
        },
    }
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(unrelated))
    b.write_text(json.dumps(first))
    alone = EventStore(tmp_path / "alone")
    batch = EventStore(tmp_path / "batch")
    assert ingest_codex((b,), alone).imported == 1
    assert ingest_codex((a, b), batch).imported == 2
    assert ingest_codex((b, a), batch).duplicates == 2
    assert alone.read_events()[0].activation_id in {
        event.activation_id for event in batch.read_events()
    }


def test_codex_explicit_invocation_is_qualified_but_asserted_canonical_read_is_ignored() -> (
    None
):
    explicit = normalize_codex(
        {
            "event": "user_input",
            "thread_id": "thread",
            "turn_id": "turn",
            "explicit_skill": "$example-capture",
        }
    )
    read = normalize_codex(
        {
            "event": "tool_call",
            "thread_id": "thread",
            "tool": "read",
            "canonical_skill_name": "example-capture",
            "canonical_skill_hash": f"sha256:{'a' * 64}",
        }
    )
    assert explicit[0].trigger == "explicit-command"
    assert read == []
