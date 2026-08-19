"""Non-interactive public CLI for local skill telemetry."""

from __future__ import annotations

import ipaddress
import json
import os
import platform
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal, cast

from cyclopts import (
    App,
    CycloptsError,
    Parameter,
    UnknownCommandError,
    UnknownOptionError,
    UnusedCliTokensError,
)

from skill_telemetry import __version__
from skill_telemetry.campaign import (
    CampaignError,
    load_manifest,
    load_observations,
    render_markdown,
    score_campaign,
)
from skill_telemetry.claude_hooks import (
    MAX_HOOK_BYTES,
    installed_skill_inventory,
    normalize_claude_hook,
)
from skill_telemetry.collector import DEFAULT_HOST, DEFAULT_PORT, CollectorServer
from skill_telemetry.ingest import IngestError, IngestLimits, ingest_codex, ingest_pi
from skill_telemetry.readout import build_readout
from skill_telemetry.schemas import COMMANDS, validate_json_document
from skill_telemetry.store import EventStore, state_directory
from skill_telemetry.usage import UsageReadoutError, build_usage_readout
from skill_telemetry.usage_store import UsageStore, usage_state_directory

OutputFormat = Annotated[
    Literal["text", "json"], Parameter(help="Output format: text or json.")
]
InputPaths = Annotated[
    list[Path],
    Parameter(
        name="--input", help="Explicit JSON/JSONL file or directory; repeat as needed."
    ),
]
SkillSpecs = Annotated[
    list[str],
    Parameter(name="--skill", help="Codex inventory NAME=PATH; repeat as needed."),
]
app = App(
    name="skill-telemetry",
    help="Privacy-preserving local skill telemetry.\n\nExamples:\n  skill-telemetry version --format json\n  skill-telemetry ingest pi --input ./session.jsonl --dry-run",
)
ingest_app = App(
    name="ingest",
    help="Import bounded, explicit runtime evidence.\n\nExamples:\n  skill-telemetry ingest pi --input ./sessions\n  skill-telemetry ingest codex --input ./events.jsonl --skill demo=./SKILL.md",
)
app.command(ingest_app)

EXIT_PARSE = 2
EXIT_CONTRACT = 3
EXIT_UNSUPPORTED = 4
EXIT_PARTIAL = 5
EXIT_HEALTH = 6
EXIT_OPERATIONAL = 7
JSON_STATUSES = frozenset({"ok", "error", "partial", "failed"})
ERROR_REASONS = frozenset(
    {
        "invalid-state-directory",
        "state-unavailable",
        "usage-aggregation-failed",
        "invalid-doctor-input",
        "collector-unavailable-or-invalid",
        "invalid-listener-input",
        "listener-unavailable",
        "at-least-one---input-is-required",
        "--skill-is-supported-only-for-ingest-codex",
        "invalid-ingest-input",
        "unsafe-or-invalid-input",
        "storage-or-input-operation-failed",
        "invalid-evaluation-input",
        "evaluation-failed",
        "evaluation-operation-failed",
        "unsupported-command-or-option",
        "invalid-command-input",
    }
)


def _envelope(
    command: str,
    status: str,
    data: object,
    *,
    warnings: list[str] | None = None,
    unsupported: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command": command,
        "tool_version": __version__,
        "status": status,
        "data": data,
        "warnings": warnings or [],
        "unsupported": unsupported or [],
    }


def _emit(
    command: str,
    output_format: OutputFormat,
    data: object,
    *,
    status: str = "ok",
    warnings: list[str] | None = None,
    unsupported: list[str] | None = None,
) -> None:
    if status not in JSON_STATUSES:
        raise ValueError("unsupported CLI JSON status")
    if output_format == "json":
        envelope = _envelope(
            command, status, data, warnings=warnings, unsupported=unsupported
        )
        validate_json_document(envelope)
        print(json.dumps(envelope, sort_keys=True, separators=(",", ":")), flush=True)
    elif isinstance(data, str):
        print(data, flush=True)
    else:
        print(json.dumps(data, indent=2, sort_keys=True), flush=True)


def _fail(command: str, output_format: OutputFormat, reason: str, code: int) -> None:
    if output_format == "json":
        _emit(command, output_format, {"reason": reason}, status="error")
    else:
        print(f"error: {reason}", file=sys.stderr)
    raise SystemExit(code)


def _path(value: Path | None, default: Path) -> Path:
    if value is None:
        return default
    if not value.is_absolute():
        raise ValueError("state directory must be an absolute path")
    return value


def _skill_specs(values: list[str]) -> tuple[tuple[str, Path], ...]:
    result: list[tuple[str, Path]] = []
    for value in values:
        name, separator, path = value.partition("=")
        if not separator or not name or not path:
            raise ValueError("--skill must use NAME=PATH")
        result.append((name, Path(path)))
    return tuple(result)


def _write_all(fd: int, content: bytes) -> None:
    """Write every byte, retrying short writes instead of silently truncating reports."""
    offset = 0
    while offset < len(content):
        written = os.write(fd, content[offset:])
        if written <= 0:
            raise OSError("short output write")
        offset += written


def _absolute_output_path(path: Path) -> Path:
    """Normalize Darwin's standard aliases without resolving caller symlinks."""
    absolute = path.absolute()
    if platform.system() == "Darwin" and absolute.parts[:2] in {
        ("/", "tmp"),
        ("/", "var"),
    }:
        return Path("/private") / absolute.relative_to("/")
    return absolute


def _open_directory_nofollow(path: Path) -> int:
    """Open every parent component from root without a symlink race."""
    if not path.is_absolute():
        raise ValueError("output path must be absolute")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            if component in {"", ".", ".."}:
                raise ValueError("unsafe output parent")
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise ValueError("unsafe output parent")
        return fd
    except OSError as exc:
        os.close(fd)
        raise ValueError("unsafe output parent") from exc
    except ValueError:
        os.close(fd)
        raise


def _write_output(path: Path, content: str) -> None:
    """Create a new owner-only report through a no-follow parent descriptor."""
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ValueError("output path must be an absolute file path")
    output_path = _absolute_output_path(path)
    parent_fd = _open_directory_nofollow(output_path.parent)
    fd = -1
    try:
        fd = os.open(
            output_path.name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise ValueError("unsafe output destination")
        _write_all(fd, content.encode())
        os.fchmod(fd, 0o600)
        os.fsync(fd)
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(parent_fd)


def _loopback_host(host: str) -> str:
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("host must be a literal loopback address") from exc
    if not parsed.is_loopback:
        raise ValueError("host must be a literal loopback address")
    return str(parsed)


def _health_url(endpoint: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        host = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("--endpoint must be literal loopback HTTP") from exc
    if (
        parsed.scheme != "http"
        or not host.is_loopback
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("--endpoint must be literal loopback HTTP")
    text = f"[{host}]" if host.version == 6 else str(host)
    return f"http://{text}{f':{port}' if port else ''}/healthz"


@app.default
def root() -> None:
    """Show the command tree. Run `skill-telemetry <command> --help` for examples."""
    app.help_print()


@app.command
def version(*, format: OutputFormat = "text") -> None:
    """Print the installed release version. Example: skill-telemetry version --format json."""
    if format == "text":
        print(__version__)
    else:
        _emit("version", format, {"version": __version__})


@app.command
def readout(
    *,
    state_dir: Annotated[
        Path | None, Parameter(help="Explicit absolute skill state directory.")
    ] = None,
    format: OutputFormat = "text",
) -> None:
    """Read retained skill evidence only; this never imports or scans runtime roots."""
    try:
        directory = _path(state_dir, state_directory())
    except ValueError:
        _fail("readout", format, "invalid-state-directory", EXIT_CONTRACT)
    try:
        _emit("readout", format, build_readout(directory))
    except (OSError, ValueError):
        _fail("readout", format, "state-unavailable", EXIT_OPERATIONAL)


@app.command
def usage(
    *,
    state_dir: Annotated[
        Path | None, Parameter(help="Explicit absolute usage state directory.")
    ] = None,
    format: OutputFormat = "text",
) -> None:
    """Read independent token histograms; no model, cost, or session attribution exists."""
    try:
        directory = _path(state_dir, usage_state_directory())
    except ValueError:
        _fail("usage", format, "invalid-state-directory", EXIT_CONTRACT)
    try:
        _emit("usage", format, build_usage_readout(directory))
    except UsageReadoutError:
        _fail("usage", format, "usage-aggregation-failed", EXIT_OPERATIONAL)
    except (OSError, ValueError):
        _fail("usage", format, "state-unavailable", EXIT_OPERATIONAL)


@app.command
def doctor(
    *,
    endpoint: Annotated[
        str, Parameter(help="Literal loopback collector endpoint.")
    ] = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}",
    state_dir: Annotated[
        Path | None, Parameter(help="Explicit absolute skill state directory.")
    ] = None,
    format: OutputFormat = "text",
) -> None:
    """Check a loopback receiver and local state policy. Example: skill-telemetry doctor --format json."""
    try:
        health_url = _health_url(endpoint)
        directory = _path(state_dir, state_directory())
    except ValueError:
        _fail("doctor", format, "invalid-doctor-input", EXIT_CONTRACT)
    try:
        with urllib.request.urlopen(health_url, timeout=2) as response:  # noqa: S310
            health = json.loads(response.read())
        if not isinstance(health, dict) or (
            health.get("external_export") is not False
            or health.get("bind") != "loopback"
        ):
            raise ValueError("invalid health response")
        EventStore(directory).ensure_private()
        _emit(
            "doctor",
            format,
            {
                "collector": endpoint,
                "loopback_only": True,
                "state_directory_mode": oct(stat.S_IMODE(directory.stat().st_mode)),
            },
        )
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        _fail("doctor", format, "collector-unavailable-or-invalid", EXIT_HEALTH)


@app.command
def serve(
    *,
    host: Annotated[
        str, Parameter(help="Literal loopback bind address.")
    ] = DEFAULT_HOST,
    port: Annotated[int, Parameter(help="Loopback port (1-65535). ")] = DEFAULT_PORT,
    state_dir: Annotated[
        Path | None, Parameter(help="Explicit absolute skill state directory.")
    ] = None,
    usage_state_dir: Annotated[
        Path | None, Parameter(help="Explicit absolute usage state directory.")
    ] = None,
    format: OutputFormat = "text",
) -> None:
    """Run the foreground-only loopback receiver. It never daemonizes or exports data."""
    try:
        if not 0 <= port <= 65535:
            raise ValueError("port out of range")
        host = _loopback_host(host)
        skill_directory = _path(state_dir, state_directory())
        usage_directory = _path(usage_state_dir, usage_state_directory())
    except ValueError:
        _fail("serve", format, "invalid-listener-input", EXIT_CONTRACT)
    try:
        server = CollectorServer(
            (host, port),
            EventStore(skill_directory),
            usage_store=UsageStore(usage_directory),
        )
        try:
            _emit(
                "serve",
                format,
                {
                    "host": host,
                    "port": int(server.server_address[1]),
                    "external_export": False,
                    "foreground": True,
                },
            )
            server.serve_forever()
        finally:
            server.server_close()
    except (OSError, ValueError):
        _fail("serve", format, "listener-unavailable", EXIT_OPERATIONAL)


def _ingest(
    agent: Literal["pi", "codex"],
    input: InputPaths,
    skill: SkillSpecs,
    dry_run: bool,
    state_dir: Path | None,
    format: OutputFormat,
    max_files: int | None,
    max_file_bytes: int | None,
    max_total_bytes: int | None,
    max_records: int | None,
    max_depth: int | None,
) -> None:
    command = f"ingest.{agent}"
    if not input:
        _fail(command, format, "at-least-one---input-is-required", EXIT_CONTRACT)
    if agent == "pi" and skill:
        _fail(
            command, format, "--skill-is-supported-only-for-ingest-codex", EXIT_CONTRACT
        )
    try:
        overrides = {
            "max_files": max_files,
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "max_top_level_records": max_records,
            "max_depth": max_depth,
        }
        limits = IngestLimits(
            **{key: value for key, value in overrides.items() if value is not None}
        )
        directory = _path(state_dir, state_directory())
        skills = _skill_specs(skill) if agent == "codex" else ()
    except ValueError:
        _fail(command, format, "invalid-ingest-input", EXIT_CONTRACT)
    try:
        store = EventStore(directory)
        # Dry runs normalize into an isolated temporary state via the ingest implementation's normal seams.
        if dry_run:
            from tempfile import TemporaryDirectory

            with TemporaryDirectory(prefix="skill-telemetry-dry-run-") as temporary:
                store = EventStore(Path(temporary))
                stats = (
                    ingest_pi(tuple(input), store, limits=limits)
                    if agent == "pi"
                    else ingest_codex(tuple(input), store, skills=skills, limits=limits)
                )
        else:
            stats = (
                ingest_pi(tuple(input), store, limits=limits)
                if agent == "pi"
                else ingest_codex(tuple(input), store, skills=skills, limits=limits)
            )
        data = {**stats.to_dict(), "dry_run": dry_run}
        if stats.limit_status:
            _emit(command, format, data, status="partial", warnings=["limit-exhausted"])
            raise SystemExit(EXIT_PARTIAL)
        if stats.rejected or stats.malformed_records_skipped:
            _emit(
                command,
                format,
                data,
                status="partial",
                warnings=["records-rejected-or-skipped"],
            )
            raise SystemExit(EXIT_PARTIAL)
        _emit(command, format, data)
    except SystemExit:
        raise
    except IngestError:
        _fail(command, format, "unsafe-or-invalid-input", EXIT_CONTRACT)
    except (OSError, ValueError):
        _fail(command, format, "storage-or-input-operation-failed", EXIT_OPERATIONAL)


@ingest_app.command
def pi(
    *,
    input: InputPaths,
    dry_run: Annotated[bool, Parameter(help="Normalize without persisting.")] = False,
    state_dir: Annotated[
        Path | None, Parameter(help="Explicit absolute skill state directory.")
    ] = None,
    format: OutputFormat = "text",
    max_files: int | None = None,
    max_file_bytes: int | None = None,
    max_total_bytes: int | None = None,
    max_records: int | None = None,
    max_depth: int | None = None,
) -> None:
    """Import explicit Pi session JSON/JSONL. Example: skill-telemetry ingest pi --input ./session.jsonl."""
    _ingest(
        "pi",
        input,
        [],
        dry_run,
        state_dir,
        format,
        max_files,
        max_file_bytes,
        max_total_bytes,
        max_records,
        max_depth,
    )


@ingest_app.command
def codex(
    *,
    input: InputPaths,
    skill: SkillSpecs | None = None,
    dry_run: Annotated[bool, Parameter(help="Normalize without persisting.")] = False,
    state_dir: Annotated[
        Path | None, Parameter(help="Explicit absolute skill state directory.")
    ] = None,
    format: OutputFormat = "text",
    max_files: int | None = None,
    max_file_bytes: int | None = None,
    max_total_bytes: int | None = None,
    max_records: int | None = None,
    max_depth: int | None = None,
) -> None:
    """Import explicit Codex JSON/JSONL. Example: skill-telemetry ingest codex --input events.jsonl --skill demo=SKILL.md."""
    _ingest(
        "codex",
        input,
        skill or [],
        dry_run,
        state_dir,
        format,
        max_files,
        max_file_bytes,
        max_total_bytes,
        max_records,
        max_depth,
    )


@app.command
def evaluate(
    *,
    manifest: Annotated[
        Path | None, Parameter(help="Optional campaign manifest.")
    ] = None,
    observations: Annotated[
        Path | None, Parameter(help="Optional sanitized observations.")
    ] = None,
    markdown_output: Annotated[
        Path | None, Parameter(help="Optional owner-only human report path.")
    ] = None,
    format: OutputFormat = "text",
) -> None:
    """Run packaged deterministic evaluation using Python only. Example: skill-telemetry evaluate --format json."""
    try:
        if markdown_output is not None and not markdown_output.is_absolute():
            raise CampaignError("markdown output must be absolute")
        campaign_dir = Path(str(files("skill_telemetry").joinpath("campaigns")))
        selected_manifest = manifest or campaign_dir / "acceptance-v1.json"
        campaign = load_manifest(selected_manifest)
        report = score_campaign(
            campaign,
            load_observations(
                observations or campaign.source_directory / campaign.observations,
                campaign,
            ),
        )
        if markdown_output:
            _write_output(markdown_output, render_markdown(report))
        status = "ok" if report["passed"] else "failed"
        _emit("evaluate", format, report, status=status)
        if not report["passed"]:
            raise SystemExit(EXIT_HEALTH)
    except SystemExit:
        raise
    except CampaignError:
        _fail("evaluate", format, "invalid-evaluation-input", EXIT_CONTRACT)
    except ValueError:
        _fail("evaluate", format, "evaluation-failed", EXIT_HEALTH)
    except OSError:
        _fail("evaluate", format, "evaluation-operation-failed", EXIT_OPERATIONAL)


@app.command(name="claude-hook")
def claude_hook(
    *,
    state_dir: Annotated[
        Path | None, Parameter(help="Explicit absolute skill state directory.")
    ] = None,
) -> None:
    """Fail-open hook: bounded stdin, no stdout, and exit 0 on every telemetry failure."""
    try:
        raw = sys.stdin.buffer.read(MAX_HOOK_BYTES + 1)
        if len(raw) > MAX_HOOK_BYTES:
            return
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            event = normalize_claude_hook(
                cast(dict[str, object], payload), installed_skill_inventory()
            )
            if event is not None:
                EventStore(_path(state_dir, state_directory())).append(event)
    except Exception:  # Fail-open by contract; never log or emit hook payloads.
        return


def _parse_command_context(tokens: list[str]) -> str | None:
    """Identify a finite command without interpreting user option values."""
    if not tokens:
        return None
    if tokens[0] == "ingest" and len(tokens) > 1 and tokens[1] in {"pi", "codex"}:
        return f"ingest.{tokens[1]}"
    aliases = {"claude-hook": None, **{command: command for command in COMMANDS}}
    return aliases.get(tokens[0])


def _json_requested(tokens: list[str]) -> bool:
    return any(
        token == "--format=json"
        or (
            token == "--format"
            and index + 1 < len(tokens)
            and tokens[index + 1] == "json"
        )
        for index, token in enumerate(tokens)
    )


def main() -> None:
    """Run Cyclopts while preserving the finite-command JSON error contract."""
    tokens = sys.argv[1:]
    try:
        app(exit_on_error=False, print_error=False)
    except CycloptsError as exc:
        command = _parse_command_context(tokens)
        unsupported = isinstance(
            exc, (UnknownCommandError, UnknownOptionError, UnusedCliTokensError)
        )
        code = EXIT_UNSUPPORTED if unsupported else EXIT_PARSE
        reason = (
            "unsupported-command-or-option" if unsupported else "invalid-command-input"
        )
        if command is not None and _json_requested(tokens):
            _emit(
                command,
                "json",
                {"reason": reason},
                status="error",
                unsupported=[reason] if unsupported else None,
            )
        else:
            print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(code) from None


if __name__ == "__main__":
    main()
