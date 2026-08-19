from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from skill_telemetry import __version__
from skill_telemetry.cli import _write_output
from skill_telemetry.schemas import validate_json_document
from skill_telemetry.store import EventStore
from skill_telemetry.usage_contract import TokenUsagePoint
from skill_telemetry.usage_store import UsageStore


def _run(
    *args: str, input_text: str | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    executable = Path(sys.executable).with_name("skill-telemetry")
    assert executable.exists(), "the test environment must install the console script"
    return subprocess.run(  # noqa: S603 -- executable is resolved from the test environment
        [str(executable), *args],
        check=False,
        capture_output=True,
        input=input_text,
        text=True,
        env=os.environ | (env or {}),
    )


def test_bare_invocation_is_progressively_discoverable() -> None:
    result = _run()

    assert result.returncode == 0
    assert result.stderr == ""
    assert "Usage: skill-telemetry COMMAND" in result.stdout
    assert "version" in result.stdout


def test_root_help_is_successful_and_useful() -> None:
    result = _run("--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "Privacy-preserving local skill telemetry." in result.stdout
    assert "ingest" in result.stdout
    assert "version" in result.stdout


def test_command_help_is_successful_and_useful() -> None:
    result = _run("version", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "Print the installed release version." in result.stdout
    assert "--format" in result.stdout


def test_version_text() -> None:
    result = _run("version")

    assert result.returncode == 0
    assert result.stdout == f"{__version__}\n"
    assert result.stderr == ""


def test_version_json_has_stable_success_envelope() -> None:
    result = _run("version", "--format", "json")

    assert result.returncode == 0
    assert result.stderr == ""
    document = json.loads(result.stdout)
    validate_json_document(document)
    assert document == {
        "schema_version": 1,
        "command": "version",
        "tool_version": __version__,
        "status": "ok",
        "data": {"version": __version__},
        "warnings": [],
        "unsupported": [],
    }


def test_finite_json_documents_match_the_v1_schema(tmp_path: Path) -> None:
    state = tmp_path / "state"
    usage = tmp_path / "usage"
    fixture = tmp_path / "session.jsonl"
    fixture.write_text(
        '{"type":"skill-telemetry-v1","event":{"schema_version":1,"event_name":"agent.skill.activation","agent_system":"pi","activation_id":"sha256:'
        + "a" * 64
        + '","skill_name":"example-capture","trigger":"explicit-command","evidence_type":"explicit-command","evidence_confidence":"observed","status":"loaded","timestamp":"2026-01-01T00:00:00+00:00","signal_name":"pi.skill.activation"}}\n'
    )
    codex_fixture = tmp_path / "codex.json"
    codex_fixture.write_text(
        json.dumps(
            {
                "method": "turn/start",
                "params": {
                    "threadId": "thread",
                    "turnId": "turn",
                    "input": [
                        {"type": "skill", "name": "example-capture", "id": "item"}
                    ],
                },
            }
        )
    )
    commands = (
        ("version", "--format", "json"),
        ("readout", "--state-dir", str(state), "--format", "json"),
        ("usage", "--state-dir", str(usage), "--format", "json"),
        ("ingest", "pi", "--input", str(fixture), "--dry-run", "--format", "json"),
        (
            "ingest",
            "codex",
            "--input",
            str(codex_fixture),
            "--dry-run",
            "--format",
            "json",
        ),
        ("evaluate", "--format", "json"),
        ("doctor", "--endpoint", "https://invalid.example", "--format", "json"),
        ("serve", "--port", "65536", "--format", "json"),
    )
    for command in commands:
        result = _run(*command)
        assert result.returncode in {0, 3, 5, 6}
        assert result.stderr == ""
        validate_json_document(json.loads(result.stdout))


def test_output_writer_refuses_symlinked_parent_and_never_replaces(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe"
    safe.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        _write_output(linked / "report.md", "report")
    output = safe / "report.md"
    _write_output(output, "report")
    with pytest.raises(FileExistsError):
        _write_output(output, "replacement")
    assert output.read_text() == "report"


def test_usage_aggregate_overflow_is_one_json_operational_error(tmp_path: Path) -> None:
    usage_directory = tmp_path / "usage"
    store = UsageStore(usage_directory)
    first = TokenUsagePoint(
        schema_version=1,
        metric_name="codex.turn.token_usage",
        metric_kind="histogram",
        aggregation_temporality="delta",
        unit="",
        token_type="total",  # noqa: S106 -- telemetry dimension
        start_time_unix_nano=1,
        time_unix_nano=2,
        count=1,
        sum=1e308,
        bucket_counts=(1,),
        explicit_bounds=(),
    )
    assert store.append_many(
        (first, TokenUsagePoint.from_mapping({**first.to_dict(), "time_unix_nano": 3}))
    ) == (True, True)
    result = _run("usage", "--state-dir", str(usage_directory), "--format", "json")
    assert result.returncode == 7
    assert result.stderr == ""
    assert "Traceback" not in result.stdout
    document = json.loads(result.stdout)
    validate_json_document(document)
    assert document["status"] == "error"
    assert document["data"] == {"reason": "usage-aggregation-failed"}


def test_relative_state_is_contract_error_with_json_envelope() -> None:
    result = _run("readout", "--state-dir", "relative", "--format", "json")
    assert result.returncode == 3
    assert result.stderr == ""
    validate_json_document(json.loads(result.stdout))


def test_unsupported_option_uses_json_envelope_and_exit_four() -> None:
    result = _run("version", "--format", "json", "--unexpected-option")
    assert result.returncode == 4
    assert result.stderr == ""
    document = json.loads(result.stdout)
    validate_json_document(document)
    assert document["command"] == "version"
    assert document["status"] == "error"
    assert document["unsupported"] == ["unsupported-command-or-option"]


def test_command_parse_error_uses_valid_json_envelope_and_exit_two() -> None:
    result = _run("version", "--format", "json", "--format")
    assert result.returncode == 2
    assert result.stderr == ""
    document = json.loads(result.stdout)
    validate_json_document(document)
    assert document["command"] == "version"
    assert document["status"] == "error"


def test_invalid_format_has_a_stable_non_traceback_diagnostic() -> None:
    result = _run("version", "--format", "yaml")

    assert result.returncode != 0
    assert "yaml" in result.stderr
    assert "Traceback" not in result.stderr


def test_unknown_command_has_a_stable_non_traceback_diagnostic() -> None:
    result = _run("unknown-command")

    assert result.returncode == 4
    assert "unknown-command" in result.stderr
    assert "Traceback" not in result.stderr


def test_finite_text_success_commands_write_only_stdout(tmp_path: Path) -> None:
    state = tmp_path / "state"
    usage = tmp_path / "usage"
    pi_fixture = tmp_path / "session.jsonl"
    pi_fixture.write_text(
        '{"type":"custom","customType":"skill-telemetry-v1","data":{"schema_version":1,"event_name":"agent.skill.activation","agent_system":"pi","activation_id":"sha256:'
        + "a" * 64
        + '","skill_name":"example-capture","trigger":"explicit-command","evidence_type":"explicit-command","evidence_confidence":"observed","status":"loaded","timestamp":"2026-01-01T00:00:00+00:00","signal_name":"pi.skill.activation"}}\n'
    )
    codex_fixture = tmp_path / "codex.json"
    codex_fixture.write_text(
        json.dumps(
            {
                "method": "turn/start",
                "params": {
                    "threadId": "thread",
                    "turnId": "turn",
                    "input": [
                        {"type": "skill", "name": "example-capture", "id": "item"}
                    ],
                },
            }
        )
    )
    commands = (
        ("version",),
        ("readout", "--state-dir", str(state)),
        ("usage", "--state-dir", str(usage)),
        ("ingest", "pi", "--input", str(pi_fixture), "--dry-run"),
        ("ingest", "codex", "--input", str(codex_fixture), "--dry-run"),
        ("evaluate",),
    )
    for command in commands:
        result = _run(*command)
        assert result.returncode == 0
        assert result.stdout
        assert result.stderr == ""


def test_finite_command_errors_keep_text_stdout_empty_and_json_schema_valid(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "session.jsonl"
    fixture.write_text("{}\n")
    missing_manifest = tmp_path / "missing.json"
    commands = (
        (("readout", "--state-dir", "relative"), 3),
        (("usage", "--state-dir", "relative"), 3),
        (("ingest", "pi", "--input", str(fixture), "--state-dir", "relative"), 3),
        (
            ("ingest", "codex", "--input", str(fixture), "--state-dir", "relative"),
            3,
        ),
        (("evaluate", "--manifest", str(missing_manifest)), 3),
        (("doctor", "--endpoint", "https://invalid.example"), 3),
        (("serve", "--port", "65536"), 3),
        (("version", "--unexpected-option"), 4),
    )
    for command, exit_code in commands:
        text = _run(*command)
        assert text.returncode == exit_code
        assert text.stdout == ""
        assert text.stderr.startswith("error: ")

        json_result = _run(*command, "--format", "json")
        assert json_result.returncode == exit_code
        assert json_result.stderr == ""
        document = json.loads(json_result.stdout)
        validate_json_document(document)
        assert document["status"] == "error"


def test_finite_cli_json_exit_matrix_includes_every_contract_code(
    tmp_path: Path,
) -> None:
    partial = tmp_path / "partial"
    partial.mkdir()
    for name in ("one.jsonl", "two.jsonl"):
        (partial / name).write_text("{}\\n")
    commands = (
        (("version", "--format", "json"), 0, "ok"),
        (("version", "--format", "json", "--format"), 2, "error"),
        (("readout", "--state-dir", "relative", "--format", "json"), 3, "error"),
        (("version", "--format", "json", "--unknown"), 4, "error"),
        (
            (
                "ingest",
                "pi",
                "--input",
                str(partial),
                "--max-files",
                "1",
                "--format",
                "json",
            ),
            5,
            "partial",
        ),
        (
            ("doctor", "--endpoint", "http://127.0.0.1:1", "--format", "json"),
            6,
            "error",
        ),
    )
    for command, expected_exit, status in commands:
        result = _run(*command)
        assert result.returncode == expected_exit
        assert result.stderr == ""
        document = json.loads(result.stdout)
        validate_json_document(document)
        assert document["status"] == status


def test_no_color_never_emits_ansi_sequences() -> None:
    result = _run("version", "--format", "json", env={"NO_COLOR": "1"})
    assert result.returncode == 0
    assert "\x1b" not in result.stdout
    assert result.stderr == ""


def test_ingest_dry_run_does_not_create_persistent_state(tmp_path: Path) -> None:
    fixture = tmp_path / "session.jsonl"
    fixture.write_text(
        '{"type":"custom","customType":"skill-telemetry-v1","data":{"schema_version":1,"event_name":"agent.skill.activation","agent_system":"pi","activation_id":"sha256:'
        + "a" * 64
        + '","skill_name":"example-capture","trigger":"explicit-command","evidence_type":"explicit-command","evidence_confidence":"observed","status":"loaded","timestamp":"2026-01-01T00:00:00+00:00","signal_name":"pi.skill.activation"}}\n'
    )
    state = tmp_path / "state"
    result = _run(
        "ingest",
        "pi",
        "--input",
        str(fixture),
        "--state-dir",
        str(state),
        "--dry-run",
        "--format",
        "json",
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["data"]["dry_run"] is True
    assert not state.exists()


def test_serve_flushes_json_readiness_after_ephemeral_bind(tmp_path: Path) -> None:
    executable = Path(sys.executable).with_name("skill-telemetry")
    process = subprocess.Popen(  # noqa: S603 -- test environment console script
        [
            str(executable),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--state-dir",
            str(tmp_path / "state"),
            "--usage-state-dir",
            str(tmp_path / "usage"),
            "--format",
            "json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, process.stderr.read() if process.stderr else "serve did not start"
        envelope = json.loads(process.stdout.readline())
        validate_json_document(envelope)
        port = envelope["data"]["port"]
        assert isinstance(port, int) and port > 0
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=5
        ) as response:
            assert response.status == 200
            assert json.loads(response.read())["status"] == "ok"
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_invalid_skill_spec_and_limits_are_contract_errors(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    source.write_text("{}")
    for arguments in (
        ("ingest", "codex", "--input", str(source), "--skill", "missing-path"),
        ("ingest", "pi", "--input", str(source), "--max-files", "0"),
    ):
        result = _run(*arguments, "--format", "json")
        assert result.returncode == 3
        validate_json_document(json.loads(result.stdout))


def test_claude_hook_cli_persists_activation_and_fails_open(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = root / "example-capture" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: example-capture\n---\n")
    state = tmp_path / "state"
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "session",
        "prompt_id": "prompt",
        "tool_use_id": "tool",
        "tool_name": "Skill",
        "tool_input": {"skill": "example-capture"},
    }
    result = _run(
        "claude-hook",
        "--state-dir",
        str(state),
        input_text=json.dumps(payload),
        env={"SKILL_TELEMETRY_SKILL_ROOTS": str(root)},
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert len(EventStore(state).read_events()) == 1

    malformed = _run("claude-hook", "--state-dir", str(state), input_text="not-json")
    assert (malformed.returncode, malformed.stdout, malformed.stderr) == (0, "", "")
