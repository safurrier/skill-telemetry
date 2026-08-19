from __future__ import annotations

import json
from pathlib import Path

from skill_telemetry.ingest import ingest_pi
from skill_telemetry.store import EventStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_pi_fixture_is_imported_and_replay_dedupes(tmp_path: Path) -> None:
    produced = json.loads((FIXTURES / "pi-typescript-event-v1.json").read_text())[
        "pi_produced_event"
    ]
    source = tmp_path / "pi.jsonl"
    source.write_text(
        json.dumps(
            {"type": "custom", "customType": "skill-telemetry-v1", "data": produced}
        )
        + "\n"
    )
    store = EventStore(tmp_path / "state")
    assert ingest_pi((source,), store).imported == 1
    replay = ingest_pi((source,), store)
    assert (replay.imported, replay.duplicates) == (0, 1)


def test_serialized_skill_ledger_fixture_decodes_as_portable_v02_evidence(
    tmp_path: Path,
) -> None:
    record = json.loads((FIXTURES / "serialized/skill-events-v0.2.jsonl").read_text())
    source = tmp_path / "legacy.jsonl"
    source.write_text(
        json.dumps(
            {"type": "custom", "customType": "skill-telemetry-v1", "data": record}
        )
        + "\n"
    )
    stats = ingest_pi((source,), EventStore(tmp_path / "state"))
    assert (stats.telemetry_records, stats.imported, stats.rejected) == (1, 1, 0)
