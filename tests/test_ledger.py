from __future__ import annotations

import json
from pathlib import Path

from skill_telemetry.contract import SkillEvent
from skill_telemetry.store import EventStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_ledger_restart_and_rotation_retains_valid_events(tmp_path: Path) -> None:
    base = json.loads((FIXTURES / "serialized/skill-events-v0.2.jsonl").read_text())
    store = EventStore(tmp_path / "state", max_bytes=700, max_files=2)
    events = tuple(
        SkillEvent.from_mapping({**base, "activation_id": f"sha256:{index:064x}"})
        for index in range(5)
    )
    assert all(store.append(event) for event in events)
    restarted = EventStore(store.directory, max_bytes=700, max_files=2)
    retained = restarted.read_events()
    assert retained
    assert len(restarted.retained_paths()) <= 2
    assert restarted.append(retained[-1]) is False
