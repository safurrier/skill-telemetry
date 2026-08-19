from __future__ import annotations

import json
import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

import skill_telemetry.store as store_module
from skill_telemetry.contract import ContractError, SkillEvent
from skill_telemetry.store import EventStore, state_directory

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIVACY_CORPUS = json.loads(
    (REPO_ROOT / "tests/fixtures/privacy-corpus.json").read_text()
)


def event(**updates: object) -> SkillEvent:
    values: dict[str, object] = {
        "schema_version": 1,
        "event_name": "agent.skill.activation",
        "agent_system": "pi",
        "session_id": f"sha256:{'1' * 64}",
        "turn_id": f"sha256:{'2' * 64}",
        "activation_id": f"sha256:{'3' * 64}",
        "skill_name": "example-capture",
        "skill_source": "user",
        "skill_content_hash": f"sha256:{'4' * 64}",
        "trigger": "explicit-command",
        "evidence_type": "native-event",
        "evidence_confidence": "observed",
        "status": "loaded",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    values.update(updates)
    return SkillEvent.from_mapping(values)


def test_contract_rejects_unknown_fields_and_raw_content() -> None:
    with pytest.raises(ContractError):
        SkillEvent.from_mapping({**event().to_dict(), "prompt": "private request"})
    with pytest.raises(ContractError):
        event(skill_name="../../private/SKILL.md")
    with pytest.raises(ContractError):
        event(session_id="unhashed-private-session")
    with pytest.raises(ContractError):
        event(skill_name="sk-proj-SECRET123")
    with pytest.raises(ContractError):
        event(skill_source="C:/" + "Users/private/skill")
    with pytest.raises(ContractError):
        event(signal_name="private/repository/content")


@pytest.mark.parametrize("field", ["event_name", "trigger", "evidence_type", "status"])
def test_contract_rejects_path_like_token_segments(field: str) -> None:
    value = "agent.skill.private..event" if field == "event_name" else "private..token"
    with pytest.raises(ContractError):
        event(**{field: value})


@pytest.mark.parametrize("count", [0, -1, 1_000_001, 1.5, True])
def test_contract_rejects_unbounded_or_non_integer_counts(count: object) -> None:
    with pytest.raises(ContractError, match="bounded positive integer"):
        event(count=count)


def test_contract_accepts_bounded_aggregate_count() -> None:
    assert event(count=7).count == 7


def test_contract_structure_errors_do_not_echo_untrusted_values() -> None:
    secret_like_value = PRIVACY_CORPUS["rejected_identifiers"][0]
    with pytest.raises(ContractError) as unknown_error:
        SkillEvent.from_mapping({**event().to_dict(), secret_like_value: "unexpected"})
    with pytest.raises(ContractError) as version_error:
        event(schema_version=secret_like_value)

    assert secret_like_value not in str(unknown_error.value)
    assert secret_like_value not in str(version_error.value)


@pytest.mark.parametrize(
    ("field", "secret_like_value"),
    [
        pytest.param(
            "event_name",
            "agent.skill.xoxb-private123",
            id="runtime-neutral-event-name",
        ),
        pytest.param(
            "skill_name",
            "codex.sk-proj-SECRET123",
            id="runtime-prefixed-skill-name",
        ),
        pytest.param(
            "skill_source",
            "claude_code.github_pat_PRIVATE123",
            id="runtime-prefixed-skill-source",
        ),
        pytest.param(
            "signal_name",
            "gen_ai.xoxb-PRIVATE123",
            id="runtime-prefixed-signal-name",
        ),
    ],
)
def test_contract_rejects_embedded_secrets_without_echoing_them(
    field: str,
    secret_like_value: str,
) -> None:
    with pytest.raises(ContractError) as error:
        event(**{field: secret_like_value})

    assert secret_like_value not in str(error.value)


@pytest.mark.parametrize("secret_like_value", PRIVACY_CORPUS["rejected_tokens"])
def test_store_rejects_secret_like_event_names_without_persisting_or_echoing(
    private_state: Path,
    secret_like_value: str,
) -> None:
    event_name = f"agent.skill.{secret_like_value}"
    invalid = replace(event(), event_name=event_name)

    with pytest.raises(ContractError) as error:
        EventStore().append(invalid)

    assert secret_like_value not in str(error.value)
    assert not list(private_state.glob("events*.jsonl"))


@pytest.mark.parametrize("field", ["trigger", "evidence_type", "status"])
@pytest.mark.parametrize("secret_like_value", PRIVACY_CORPUS["rejected_tokens"])
def test_store_rejects_secret_like_tokens_without_persisting_or_echoing(
    private_state: Path,
    field: str,
    secret_like_value: str,
) -> None:
    invalid = replace(event(), **{field: secret_like_value})

    with pytest.raises(ContractError) as error:
        EventStore().append(invalid)

    assert secret_like_value not in str(error.value)
    assert not list(private_state.glob("events*.jsonl"))


@pytest.mark.parametrize("field", ["skill_name", "skill_source", "signal_name"])
@pytest.mark.parametrize("secret_like_value", PRIVACY_CORPUS["rejected_identifiers"])
def test_store_rejects_secret_like_identifiers_without_persisting_or_echoing(
    private_state: Path,
    field: str,
    secret_like_value: str,
) -> None:
    invalid = replace(event(), **{field: secret_like_value})

    with pytest.raises(ContractError) as error:
        EventStore().append(invalid)

    assert secret_like_value not in str(error.value)
    assert not list(private_state.glob("events*.jsonl"))


@pytest.mark.parametrize("safe_value", PRIVACY_CORPUS["safe_tokens"])
def test_contract_accepts_safe_event_names(safe_value: str) -> None:
    event_name = f"agent.skill.{safe_value}"
    assert event(event_name=event_name).event_name == event_name


@pytest.mark.parametrize("field", ["trigger", "evidence_type", "status"])
@pytest.mark.parametrize("safe_value", PRIVACY_CORPUS["safe_tokens"])
def test_contract_accepts_safe_tokens(field: str, safe_value: str) -> None:
    assert event(**{field: safe_value}).to_dict()[field] == safe_value


@pytest.mark.parametrize("field", ["skill_name", "skill_source", "signal_name"])
@pytest.mark.parametrize("safe_value", PRIVACY_CORPUS["safe_identifiers"])
def test_contract_accepts_safe_identifiers(field: str, safe_value: str) -> None:
    assert event(**{field: safe_value}).to_dict()[field] == safe_value


@pytest.mark.parametrize("variable", ["SKILL_TELEMETRY_STATE_DIR", "XDG_STATE_HOME"])
def test_state_directory_rejects_relative_storage_roots(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
) -> None:
    monkeypatch.delenv("SKILL_TELEMETRY_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv(variable, "relative/private-state")

    with pytest.raises(ValueError, match="absolute"):
        state_directory()


def test_store_is_owner_only_deduplicated_and_bounded(private_state: Path) -> None:
    store = EventStore(max_bytes=900, max_files=2)
    first = event()
    assert store.append(first) is True
    assert store.append(first) is False

    for index in range(12):
        store.append(event(activation_id=f"sha256:{index:064x}"))

    files = sorted(private_state.glob("events*.jsonl"))
    assert 1 <= len(files) <= 2
    assert stat.S_IMODE(private_state.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files)
    assert all(path.stat().st_size <= store.max_bytes for path in files)

    records = [
        json.loads(line) for path in files for line in path.read_text().splitlines()
    ]
    assert all("prompt" not in record for record in records)
    assert all("/" + "Users/" not in json.dumps(record) for record in records)


def test_store_fails_visibly_on_corrupt_retained_events(private_state: Path) -> None:
    private_state.mkdir(parents=True, mode=0o700)
    corrupt = private_state / "events.jsonl"
    corrupt.write_text("{not-json}\n")
    corrupt.chmod(0o600)

    with pytest.raises(ValueError, match="corrupt"):
        EventStore().append(event())


def test_store_fails_clearly_when_no_follow_open_is_unsupported(
    monkeypatch: pytest.MonkeyPatch, private_state: Path
) -> None:
    monkeypatch.delattr(store_module.os, "O_NOFOLLOW")

    with pytest.raises(OSError, match="no-follow"):
        EventStore().append(event())

    assert not list(private_state.glob("events*.jsonl"))


def test_store_read_interface_validates_contract_and_append_many_batches(
    private_state: Path,
) -> None:
    first = event()
    second = event(activation_id=f"sha256:{'e' * 64}")
    store = EventStore()

    assert store.append_many((first, first, second)) == (True, False, True)
    assert store.read_events() == (first, second)
    assert tuple(store.iter_events()) == (first, second)


def test_store_fails_loud_on_invalid_retained_event_contract(
    private_state: Path,
) -> None:
    EventStore().append(event())
    path = private_state / "events.jsonl"
    payload = json.loads(path.read_text())
    del payload["timestamp"]
    path.write_text(json.dumps(payload) + "\n")
    path.chmod(0o600)

    with pytest.raises(ValueError, match="corrupt"):
        EventStore().read_events()


def test_store_enforces_retention_when_max_files_is_lowered(
    private_state: Path,
) -> None:
    rotating = EventStore(max_bytes=900, max_files=4)
    for index in range(8):
        rotating.append(event(activation_id=f"sha256:{index:064x}"))
    assert len(rotating.retained_paths()) > 1

    downshifted = EventStore(max_bytes=900, max_files=1)
    downshifted.append(event(activation_id=f"sha256:{'f' * 64}"))

    assert [path.name for path in downshifted.retained_paths()] == ["events.jsonl"]


def test_store_rejects_a_single_event_larger_than_the_rotation_limit(
    private_state: Path,
) -> None:
    with pytest.raises(ValueError, match="exceeds max_bytes"):
        EventStore(max_bytes=256).append(event())
    assert not list(private_state.glob("events*.jsonl"))


def test_store_resume_and_fork_dedupe_uses_stable_activation_id(
    private_state: Path,
) -> None:
    original = event()
    assert EventStore().append(original)
    assert not EventStore().append(original)
    assert EventStore().append(event(activation_id=f"sha256:{'f' * 64}"))
