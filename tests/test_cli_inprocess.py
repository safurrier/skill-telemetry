# ruff: noqa
"""In-process command tests keep whole-package coverage honest for finite CLI paths."""

from __future__ import annotations

import io
import json
import os
import sys
import threading
from pathlib import Path

import pytest

import skill_telemetry.cli as cli
from skill_telemetry.collector import CollectorServer
from skill_telemetry.store import EventStore
from skill_telemetry.usage_store import UsageStore


def test_cli_helpers_validate_paths_skills_endpoints_and_token_context(
    tmp_path: Path,
) -> None:
    assert cli._path(None, tmp_path) == tmp_path
    with pytest.raises(ValueError):
        cli._path(Path("relative"), tmp_path)
    assert cli._skill_specs([f"sample={tmp_path}"]) == (("sample", tmp_path),)
    with pytest.raises(ValueError):
        cli._skill_specs(["invalid"])
    assert cli._loopback_host("127.0.0.1") == "127.0.0.1"
    with pytest.raises(ValueError):
        cli._loopback_host("0.0.0.0")
    assert cli._health_url("http://127.0.0.1:4318") == "http://127.0.0.1:4318/healthz"
    with pytest.raises(ValueError):
        cli._health_url("https://127.0.0.1:4318")
    assert cli._parse_command_context(["ingest", "pi"]) == "ingest.pi"
    assert cli._parse_command_context(["claude-hook"]) is None
    assert cli._parse_command_context(["nope"]) is None
    assert cli._json_requested(["version", "--format", "json"])
    assert cli._json_requested(["version", "--format=json"])
    assert not cli._json_requested(["version"])


def test_cli_finite_commands_emit_schema_valid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.version(format="json")
    version = json.loads(capsys.readouterr().out)
    assert version["data"]["version"]

    cli.readout(state_dir=tmp_path / "state", format="json")
    assert json.loads(capsys.readouterr().out)["command"] == "readout"
    cli.usage(state_dir=tmp_path / "usage", format="json")
    assert json.loads(capsys.readouterr().out)["command"] == "usage"

    cli.evaluate(format="json")
    report = json.loads(capsys.readouterr().out)
    assert report["command"] == "evaluate"
    assert report["status"] == "ok"


def test_doctor_accepts_real_loopback_health_and_rejects_nonobjects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    server = CollectorServer(
        ("127.0.0.1", 0),
        EventStore(tmp_path / "events"),
        usage_store=UsageStore(tmp_path / "usage"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        cli.doctor(
            endpoint=f"http://{host}:{port}",
            state_dir=tmp_path / "state",
            format="json",
        )
        assert json.loads(capsys.readouterr().out)["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b"[]"

    monkeypatch.setattr(
        cli.urllib.request, "urlopen", lambda *_args, **_kwargs: Response()
    )
    with pytest.raises(SystemExit) as error:
        cli.doctor(
            endpoint="http://127.0.0.1:1", state_dir=tmp_path / "other", format="json"
        )
    assert error.value.code == cli.EXIT_HEALTH
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_ingest_paths_have_success_partial_and_contract_exits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    event = {
        "schema_version": 1,
        "event_name": "agent.skill.activation",
        "agent_system": "pi",
        "activation_id": "sha256:" + "a" * 64,
        "skill_name": "sample-skill",
        "trigger": "explicit-command",
        "evidence_type": "explicit-command",
        "evidence_confidence": "observed",
        "status": "loaded",
        "timestamp": "2026-01-01T00:00:00Z",
        "signal_name": "pi.skill.activation",
    }
    source = tmp_path / "events.jsonl"
    source.write_text(
        json.dumps(
            {"type": "custom", "customType": "skill-telemetry-v1", "data": event}
        )
        + "\n"
    )
    cli._ingest(
        "pi",
        [source],
        [],
        True,
        tmp_path / "state",
        "json",
        None,
        None,
        None,
        None,
        None,
    )
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    with pytest.raises(SystemExit) as partial:
        cli._ingest(
            "pi", [source], [], True, tmp_path / "state", "json", 1, 1, None, None, None
        )
    assert partial.value.code == cli.EXIT_PARTIAL
    assert json.loads(capsys.readouterr().out)["status"] == "partial"
    with pytest.raises(SystemExit) as invalid:
        cli._ingest(
            "pi",
            [],
            [],
            False,
            tmp_path / "state",
            "json",
            None,
            None,
            None,
            None,
            None,
        )
    assert invalid.value.code == cli.EXIT_CONTRACT


def test_output_writer_and_fail_write_only_expected_streams(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "report.md"
    cli._write_output(output, "report")
    assert output.read_text() == "report"
    with pytest.raises(FileExistsError):
        cli._write_output(output, "again")
    writes: list[bytes] = []
    monkeypatch.setattr(
        cli.os, "write", lambda _fd, value: writes.append(bytes(value)) or len(value)
    )
    cli._write_all(1, b"abc")
    assert b"".join(writes) == b"abc"
    with pytest.raises(SystemExit) as error:
        cli._fail("version", "json", "invalid-state-directory", cli.EXIT_CONTRACT)
    assert error.value.code == cli.EXIT_CONTRACT
    assert (
        json.loads(capsys.readouterr().out)["data"]["reason"]
        == "invalid-state-directory"
    )


def test_claude_hook_is_fail_open_for_invalid_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Input:
        buffer = io.BytesIO(b"not-json")

    monkeypatch.setattr(sys, "stdin", Input())
    cli.claude_hook(state_dir=Path("/tmp"))
