"""Bounded, descriptor-relative ingestion for Pi and Codex telemetry inputs."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import platform
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, cast

import ijson

from skill_telemetry.adapters import build_codex_event, first, normalize_codex
from skill_telemetry.contract import ContractError, SkillEvent
from skill_telemetry.privacy import pseudonym, safe_name
from skill_telemetry.store import EventStore


@dataclass(frozen=True, slots=True)
class IngestLimits:
    """Positive caps for work performed on externally-owned source trees."""

    max_traversal_entries: int = 4_096
    max_directories: int = 512
    max_depth: int = 8
    max_files: int = 256
    max_file_bytes: int = 8 * 1024 * 1024
    max_total_bytes: int = 32 * 1024 * 1024
    # Includes every regular-file snapshot hashed during discovery, including
    # direct duplicate paths and candidates rejected from the selected set.
    max_discovery_bytes: int = 32 * 1024 * 1024
    max_top_level_records: int = 50_000
    max_structured_records: int = 50_000
    max_json_depth: int = 64
    max_json_string_bytes: int = 1 * 1024 * 1024
    max_jsonl_line_bytes: int = 1 * 1024 * 1024
    max_live_descriptors: int = 4
    max_codex_skills: int = 64
    max_codex_skill_file_bytes: int = 1 * 1024 * 1024
    max_codex_skill_total_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if any(
            value < 1
            for value in self.__dataclass_fields__.values()
            for value in (getattr(self, value.name),)
        ):
            raise ValueError("ingestion limits must be positive")


DEFAULT_INGEST_LIMITS = IngestLimits()
LIMIT_STATUSES = frozenset(
    {
        *(field.replace("_", "-") for field in IngestLimits.__dataclass_fields__),
        "max-normalized-batch-bytes",
    }
)
FileIdentity = tuple[int, int]


class IngestError(ValueError):
    """Raised when a declared telemetry source cannot be safely ingested."""


class _MalformedJson(IngestError):
    """Parser failure carrying structural work already charged to this operation."""

    def __init__(self, nodes: int) -> None:
        super().__init__("telemetry input is not valid UTF-8 JSON")
        self.nodes = nodes


class IngestLimitError(IngestError):
    """A safe, content-free resource cap was reached."""

    def __init__(self, limit: str) -> None:
        super().__init__("limit-exhausted")
        if limit not in LIMIT_STATUSES:
            raise ValueError("unsupported ingest limit")
        self.limit = limit


@dataclass(frozen=True, slots=True)
class ImportStats:
    """Content-free import accounting suitable for machine output."""

    agent_system: str
    files_scanned: int
    records_scanned: int
    telemetry_records: int
    imported: int
    duplicates: int
    rejected: int
    malformed_records_skipped: int = 0
    limit_status: str | None = None

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        if self.limit_status is None:
            del result["limit_status"]
        return result


@dataclass(frozen=True, slots=True)
class _Source:
    """Discovery metadata only; selected inputs never retain an open descriptor."""

    path: Path
    identities: tuple[FileIdentity, ...]
    size: int
    digest: str


def _identity(metadata: os.stat_result) -> FileIdentity:
    return metadata.st_dev, metadata.st_ino


def _raise_safe_os_error(exc: OSError) -> IngestError:
    if exc.errno in {errno.EMFILE, errno.ENFILE}:
        return IngestLimitError("max-live-descriptors")
    return IngestError("unsafe-or-changed-input")


def _descriptor_limit(limits: IngestLimits, needed: int) -> None:
    """Bound descriptors owned by this operation, independent of process-global FDs."""
    if needed > limits.max_live_descriptors:
        raise IngestLimitError("max-live-descriptors")


def _expanded_path(path: Path) -> Path:
    """Expand a path without resolving caller symlinks; Darwin has two OS aliases."""
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    if platform.system() == "Darwin" and expanded.parts[:2] in {
        ("/", "tmp"),
        ("/", "var"),
    }:
        return Path("/private") / expanded.relative_to("/")
    return expanded


def _open_components(
    path: Path, *, directory: bool, limits: IngestLimits, held_descriptors: int = 0
) -> tuple[int, tuple[FileIdentity, ...]]:
    """Open every component relative to a no-follow descriptor, closing parents promptly."""
    try:
        no_follow = os.O_NOFOLLOW
        directory_flag = os.O_DIRECTORY
    except AttributeError as exc:
        raise IngestError("safe-no-follow-unsupported") from exc
    expanded = _expanded_path(path)
    components = expanded.parts[1:]
    _descriptor_limit(limits, held_descriptors + 2)
    fd = -1
    try:
        fd = os.open("/", os.O_RDONLY | directory_flag | no_follow)
        identities = [_identity(os.fstat(fd))]
        if not components:
            if not directory:
                raise IngestError("unsafe-or-changed-input")
            return fd, tuple(identities)
        for index, component in enumerate(components):
            if component in {"", ".", ".."}:
                raise IngestError("unsafe-or-changed-input")
            leaf = index == len(components) - 1
            flags = os.O_RDONLY | no_follow
            if directory or not leaf:
                flags |= directory_flag
            else:
                # A raced FIFO must never wait for a writer before fstat rejects it.
                flags |= os.O_NONBLOCK
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            identities.append(_identity(os.fstat(fd)))
        result = fd
        fd = -1
        return result, tuple(identities)
    except OSError as exc:
        raise _raise_safe_os_error(exc) from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _open_checked(
    path: Path, *, directory: bool, limits: IngestLimits, held_descriptors: int = 0
) -> tuple[int, tuple[FileIdentity, ...], os.stat_result]:
    fd = -1
    try:
        fd, identities = _open_components(
            path, directory=directory, limits=limits, held_descriptors=held_descriptors
        )
        metadata = os.fstat(fd)
        valid = (
            stat.S_ISDIR(metadata.st_mode)
            if directory
            else (stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid())
        )
        if not valid:
            raise IngestError("unsafe-or-changed-input")
        result = fd
        fd = -1
        return result, identities, metadata
    except IngestError:
        raise
    except OSError as exc:
        raise _raise_safe_os_error(exc) from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _digest_fd(fd: int, size: int) -> str:
    """Hash exactly a discovery snapshot without materializing a second source copy."""
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = os.read(fd, min(64 * 1024, remaining))
        if not chunk:
            raise IngestError("unsafe-or-changed-input")
        digest.update(chunk)
        remaining -= len(chunk)
    if os.fstat(fd).st_size != size:
        raise IngestError("unsafe-or-changed-input")
    return digest.hexdigest()


def _discover_file(
    path: Path,
    limits: IngestLimits,
    expected: tuple[FileIdentity, ...] | None = None,
    *,
    expected_parent: tuple[FileIdentity, ...] | None = None,
    held_descriptors: int = 0,
    discovery_bytes: int = 0,
) -> _Source:
    """Snapshot a regular source identity, charging bytes before its digest read."""
    safe_path = _expanded_path(path)
    try:
        listed = os.lstat(safe_path)
    except OSError as exc:
        raise IngestError("unsafe-or-changed-input") from exc
    if stat.S_ISLNK(listed.st_mode):
        raise IngestError("refusing symlinked telemetry input")
    if not stat.S_ISREG(listed.st_mode):
        raise IngestError("unsafe-or-changed-input")
    listed_identity = _identity(listed)
    if expected is not None and listed_identity != expected[-1]:
        raise IngestError("unsafe-or-changed-input")
    fd, identities, metadata = _open_checked(
        safe_path, directory=False, limits=limits, held_descriptors=held_descriptors
    )
    try:
        if (
            _identity(metadata) != listed_identity
            or (expected is not None and identities != expected)
            or (expected_parent is not None and identities[:-1] != expected_parent)
        ):
            raise IngestError("unsafe-or-changed-input")
        if metadata.st_size > limits.max_file_bytes:
            raise IngestLimitError("max-file-bytes")
        if discovery_bytes + metadata.st_size > limits.max_discovery_bytes:
            raise IngestLimitError("max-discovery-bytes")
        digest = _digest_fd(fd, metadata.st_size)
        return _Source(
            path=safe_path, identities=identities, size=metadata.st_size, digest=digest
        )
    finally:
        os.close(fd)


def _lexical_path(path: Path) -> str | None:
    """Compare safe Codex action paths without resolving caller-controlled symlinks."""
    expanded = _expanded_path(path)
    if ".." in expanded.parts:
        return None
    return os.path.normpath(os.fspath(expanded))


def _add_source(
    sources: list[_Source],
    seen: set[tuple[FileIdentity, ...]],
    aggregate_bytes: int,
    discovery_bytes: int,
    path: Path,
    limits: IngestLimits,
    expected: tuple[FileIdentity, ...] | None = None,
    *,
    held_descriptors: int = 0,
) -> tuple[int, int]:
    source = _discover_file(
        path,
        limits,
        expected,
        held_descriptors=held_descriptors,
        discovery_bytes=discovery_bytes,
    )
    discovery_bytes += source.size
    if source.identities in seen:
        return aggregate_bytes, discovery_bytes
    if len(sources) >= limits.max_files:
        raise IngestLimitError("max-files")
    if aggregate_bytes + source.size > limits.max_total_bytes:
        raise IngestLimitError("max-total-bytes")
    seen.add(source.identities)
    sources.append(source)
    return aggregate_bytes + source.size, discovery_bytes


def discover_inputs(
    inputs: tuple[Path, ...], limits: IngestLimits = DEFAULT_INGEST_LIMITS
) -> tuple[_Source, ...]:
    """Bounded no-follow discovery; queues carry identities, not descriptors."""
    sources: list[_Source] = []
    pending: list[tuple[Path, int, tuple[FileIdentity, ...]]] = []
    traversal_entries = directories = aggregate_bytes = discovery_bytes = 0
    seen: set[tuple[FileIdentity, ...]] = set()
    for raw_path in inputs:
        traversal_entries += 1
        if traversal_entries > limits.max_traversal_entries:
            raise IngestLimitError("max-traversal-entries")
        path = _expanded_path(raw_path)
        try:
            listed = os.lstat(path)
        except OSError as exc:
            raise IngestError("unsafe-or-changed-input") from exc
        if stat.S_ISLNK(listed.st_mode):
            raise IngestError("refusing symlinked telemetry input")
        if stat.S_ISREG(listed.st_mode):
            aggregate_bytes, discovery_bytes = _add_source(
                sources, seen, aggregate_bytes, discovery_bytes, path, limits
            )
        elif stat.S_ISDIR(listed.st_mode):
            fd, identities, metadata = _open_checked(
                path, directory=True, limits=limits
            )
            try:
                if _identity(listed) != _identity(metadata):
                    raise IngestError("unsafe-or-changed-input")
                pending.append((path, 0, identities))
            finally:
                os.close(fd)
        else:
            raise IngestError("unsafe-or-changed-input")
    while pending:
        path, depth, expected = pending.pop()
        directories += 1
        if directories > limits.max_directories:
            raise IngestLimitError("max-directories")
        fd, identities, _ = _open_checked(path, directory=True, limits=limits)
        scan_fd = -1
        try:
            if identities != expected:
                raise IngestError("unsafe-or-changed-input")
            _descriptor_limit(limits, 3)
            scan_fd = os.dup(fd)
            with os.scandir(scan_fd) as entries:
                for entry in entries:
                    traversal_entries += 1
                    if traversal_entries > limits.max_traversal_entries:
                        raise IngestLimitError("max-traversal-entries")
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise _raise_safe_os_error(exc) from exc
                    if stat.S_ISLNK(metadata.st_mode):
                        continue
                    candidate = path / entry.name
                    if stat.S_ISDIR(metadata.st_mode):
                        if depth >= limits.max_depth:
                            raise IngestLimitError("max-depth")
                        pending.append(
                            (candidate, depth + 1, (*identities, _identity(metadata)))
                        )
                    elif stat.S_ISREG(metadata.st_mode) and candidate.suffix in {
                        ".json",
                        ".jsonl",
                    }:
                        aggregate_bytes, discovery_bytes = _add_source(
                            sources,
                            seen,
                            aggregate_bytes,
                            discovery_bytes,
                            candidate,
                            limits,
                            (*identities, _identity(metadata)),
                            held_descriptors=2,
                        )
        except OSError as exc:
            raise _raise_safe_os_error(exc) from exc
        finally:
            # scandir may close an fd it was given on some runtimes; close our dup either way.
            if scan_fd >= 0:
                try:
                    os.close(scan_fd)
                except OSError as exc:
                    if exc.errno != errno.EBADF:
                        raise
            os.close(fd)
    return tuple(sorted(sources, key=lambda source: os.fspath(source.path)))


def _open_source(source: _Source, limits: IngestLimits) -> int:
    fd, identities, metadata = _open_checked(
        source.path, directory=False, limits=limits
    )
    if identities != source.identities or metadata.st_size != source.size:
        os.close(fd)
        raise IngestError("unsafe-or-changed-input")
    return fd


def _read_source_bytes(source: _Source, limits: IngestLimits) -> bytes:
    """Read exactly the discovered snapshot and reject same-inode in-place mutation."""
    fd = _open_source(source, limits)
    try:
        content = bytearray()
        remaining = source.size
        digest = hashlib.sha256()
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                raise IngestError("unsafe-or-changed-input")
            content.extend(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        metadata = os.fstat(fd)
        if (
            _identity(metadata) != source.identities[-1]
            or metadata.st_size < source.size
        ):
            raise IngestError("unsafe-or-changed-input")
        if digest.hexdigest() != source.digest:
            raise IngestError("unsafe-or-changed-input")
        return bytes(content)
    finally:
        os.close(fd)


def _read_source(
    source: _Source, limits: IngestLimits, *, tolerate_trailing_utf8: bool
) -> tuple[str, bool]:
    """Compatibility helper for callers that need one bounded decoded source."""
    content = _read_source_bytes(source, limits)
    try:
        return content.decode("utf-8"), False
    except UnicodeDecodeError as exc:
        if tolerate_trailing_utf8 and exc.end == len(content):
            try:
                return content[: exc.start].decode("utf-8"), True
            except UnicodeDecodeError as prefix_error:
                raise IngestError(
                    "telemetry input is not valid UTF-8"
                ) from prefix_error
        raise IngestError("telemetry input is not valid UTF-8") from exc


def _preflight_json(raw: bytes, limits: IngestLimits, nodes_before: int) -> int:
    """Incrementally validate JSON token shape before json.loads materializes it."""
    depth = 0
    nodes = nodes_before
    try:
        for event, value in ijson.basic_parse(raw):
            if event in {"start_map", "start_array"}:
                depth += 1
                nodes += 1
                if depth > limits.max_json_depth:
                    raise IngestLimitError("max-json-depth")
            elif event in {"end_map", "end_array"}:
                depth -= 1
            elif event in {"map_key", "string", "number", "boolean", "null"}:
                nodes += 1
                if event in {"map_key", "string"} and (
                    len(value.encode("utf-8")) > limits.max_json_string_bytes
                ):
                    raise IngestLimitError("max-json-string-bytes")
            if nodes > limits.max_structured_records:
                raise IngestLimitError("max-structured-records")
    except IngestLimitError:
        raise
    except (ijson.JSONError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise _MalformedJson(nodes) from exc
    return nodes


def _next_non_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _json_document_list(text: str, remaining_records: int) -> tuple[object, ...]:
    index = _next_non_whitespace(text, 0)
    if index == len(text):
        raise json.JSONDecodeError("Expecting value", text, index)
    if text[index] != "[":
        if remaining_records < 1:
            raise IngestLimitError("max-top-level-records")
        return (json.loads(text),)
    decoder = json.JSONDecoder()
    values: list[object] = []
    index = _next_non_whitespace(text, index + 1)
    if index < len(text) and text[index] == "]":
        if _next_non_whitespace(text, index + 1) != len(text):
            raise json.JSONDecodeError("Extra data", text, index + 1)
        return ()
    while True:
        if len(values) >= remaining_records:
            raise IngestLimitError("max-top-level-records")
        value, index = decoder.raw_decode(text, index)
        values.append(value)
        index = _next_non_whitespace(text, index)
        if index == len(text):
            raise json.JSONDecodeError("Expecting ',' delimiter", text, index)
        if text[index] == "]":
            if _next_non_whitespace(text, index + 1) != len(text):
                raise json.JSONDecodeError("Extra data", text, index + 1)
            return tuple(values)
        if text[index] != ",":
            raise json.JSONDecodeError("Expecting ',' delimiter", text, index)
        index = _next_non_whitespace(text, index + 1)


def _documents(
    source: _Source,
    limits: IngestLimits,
    *,
    tolerate_jsonl: bool,
    records_before: int,
    nodes_before: int,
) -> tuple[tuple[object, ...], int, int, int]:
    """Decode only preflighted records; JSONL streams bytes and bounds each line."""
    remaining_records = limits.max_top_level_records - records_before
    if source.path.suffix != ".jsonl":
        raw = _read_source_bytes(source, limits)
        nodes = _preflight_json(raw, limits, nodes_before)
        try:
            text = raw.decode("utf-8")
            documents = _json_document_list(text, remaining_records)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise IngestError("telemetry input is not valid UTF-8 JSON") from exc
        return documents, 0, len(documents), nodes

    values: list[object] = []
    malformed = records = 0
    nodes = nodes_before
    fd = _open_source(source, limits)
    stream: BinaryIO | None = None
    try:
        stream = os.fdopen(fd, "rb")
        fd = -1
        remaining = source.size
        digest = hashlib.sha256()
        while remaining:
            # Never let a live, unterminated JSONL record make BufferedReader allocate
            # beyond the configured line cap, and never read later appends.
            line = stream.readline(min(limits.max_jsonl_line_bytes + 1, remaining))
            if not line:
                raise IngestError("unsafe-or-changed-input")
            remaining -= len(line)
            digest.update(line)
            if len(line) > limits.max_jsonl_line_bytes:
                raise IngestLimitError("max-jsonl-line-bytes")
            if not line.strip():
                continue
            if records >= remaining_records:
                raise IngestLimitError("max-top-level-records")
            records += 1
            if tolerate_jsonl and not line.endswith(b"\n"):
                malformed += 1
                break
            try:
                nodes = _preflight_json(line, limits, nodes)
                values.append(json.loads(line))
            except _MalformedJson as exc:
                nodes = exc.nodes
                if tolerate_jsonl:
                    malformed += 1
                    continue
                raise IngestError("telemetry input is not valid UTF-8 JSONL") from exc
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
                if tolerate_jsonl:
                    malformed += 1
                    continue
                raise IngestError("telemetry input is not valid UTF-8 JSONL") from exc
        metadata = os.fstat(stream.fileno())
        if (
            _identity(metadata) != source.identities[-1]
            or metadata.st_size < source.size
            or digest.hexdigest() != source.digest
        ):
            raise IngestError("unsafe-or-changed-input")
    finally:
        if stream is not None:
            stream.close()
        elif fd >= 0:
            os.close(fd)
    return tuple(values), malformed, records, nodes


def _structured_objects(
    value: object, limits: IngestLimits, initial_records: int
) -> tuple[tuple[dict[str, object], ...], int]:
    """Charge every queued item before allocating it into the traversal worklist."""
    records: list[dict[str, object]] = []
    pending = [value]
    charged = initial_records + 1
    if charged > limits.max_structured_records:
        raise IngestLimitError("max-structured-records")
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            records.append(cast(dict[str, object], current))
            children = tuple(current.values())
        elif isinstance(current, list):
            children = tuple(current)
        else:
            continue
        # Charge all children, including scalars, before allocating containers into pending.
        if charged + len(children) > limits.max_structured_records:
            raise IngestLimitError("max-structured-records")
        charged += len(children)
        pending.extend(child for child in children if isinstance(child, (dict, list)))
    return tuple(records), charged


def _limit_stats(agent: str, error: IngestLimitError) -> ImportStats:
    return ImportStats(agent, 0, 0, 0, 0, 0, 0, limit_status=error.limit)


def ingest_pi(
    inputs: tuple[Path, ...],
    store: EventStore,
    *,
    tolerate_invalid_jsonl: bool = False,
    limits: IngestLimits = DEFAULT_INGEST_LIMITS,
) -> ImportStats:
    """Normalize Pi records completely before bounded at-least-once persistence."""
    try:
        sources = discover_inputs(inputs, limits)
        pending: list[SkillEvent] = []
        records_scanned = telemetry_records = rejected = malformed = nodes = 0
        for source in sources:
            documents, skipped, source_records, nodes = _documents(
                source,
                limits,
                tolerate_jsonl=tolerate_invalid_jsonl,
                records_before=records_scanned,
                nodes_before=nodes,
            )
            malformed += skipped
            records_scanned += source_records
            for raw in documents:
                if not isinstance(raw, dict):
                    continue
                record = cast(dict[str, object], raw)
                if (
                    record.get("type") != "custom"
                    or record.get("customType") != "skill-telemetry-v1"
                ):
                    continue
                telemetry_records += 1
                data = record.get("data")
                if not isinstance(data, dict):
                    rejected += 1
                    continue
                try:
                    event = SkillEvent.from_mapping(cast(dict[str, object], data))
                except ContractError:
                    rejected += 1
                    continue
                if event.agent_system != "pi":
                    rejected += 1
                    continue
                pending.append(event)
        retained = store.append_many(pending)
    except IngestLimitError as exc:
        return _limit_stats("pi", exc)
    except ValueError as exc:
        if str(exc) == "normalized batch exceeds max_bytes":
            return _limit_stats("pi", IngestLimitError("max-normalized-batch-bytes"))
        raise
    return ImportStats(
        "pi",
        len(sources),
        records_scanned,
        telemetry_records,
        sum(retained),
        len(retained) - sum(retained),
        rejected,
        malformed,
    )


def _inventory(
    skills: tuple[tuple[str, Path], ...], limits: IngestLimits
) -> dict[str, tuple[str, str]]:
    if len(skills) > limits.max_codex_skills:
        raise IngestLimitError("max-codex-skills")
    total = 0
    inventory: dict[str, tuple[str, str]] = {}
    for raw_name, declared in skills:
        name = safe_name(raw_name)
        if name is None:
            raise IngestError("invalid-input")
        path = _expanded_path(declared)
        try:
            listed = os.lstat(path)
        except OSError as exc:
            raise IngestError("unsafe-or-changed-input") from exc
        if stat.S_ISLNK(listed.st_mode):
            raise IngestError("unsafe-or-changed-input")
        if stat.S_ISDIR(listed.st_mode):
            directory_fd, identities, metadata = _open_checked(
                path, directory=True, limits=limits
            )
            try:
                if _identity(metadata) != _identity(listed):
                    raise IngestError("unsafe-or-changed-input")
            finally:
                os.close(directory_fd)
            target = path / "SKILL.md"
            source = _discover_file(target, limits, expected_parent=identities)
        else:
            target = path
            source = _discover_file(target, limits)
        if source.size > limits.max_codex_skill_file_bytes:
            raise IngestLimitError("max-codex-skill-file-bytes")
        if total + source.size > limits.max_codex_skill_total_bytes:
            raise IngestLimitError("max-codex-skill-total-bytes")
        raw = _read_source_bytes(source, limits)
        try:
            digest = hashlib.sha256(raw).hexdigest()
        except Exception as exc:  # pragma: no cover - hashlib is deterministic
            raise IngestError("unsafe-or-changed-input") from exc
        total += source.size
        lexical_target = _lexical_path(target)
        if lexical_target is None:
            raise IngestError("Codex skill inventory entry has an unsafe path")
        inventory[lexical_target] = (name, f"sha256:{digest}")
    return inventory


def _codex_canonical_reads(
    source: dict[str, object], inventory: dict[str, tuple[str, str]]
) -> tuple[tuple[SkillEvent, ...], int]:
    if not inventory or source.get("method") not in {
        "item/commandExecution/requestApproval",
        "execCommandApproval",
    }:
        return (), 0
    params_value = source.get("params")
    if not isinstance(params_value, dict):
        return (), 1
    params = cast(dict[str, object], params_value)
    actions = params.get("commandActions", params.get("parsedCmd", []))
    timestamp = source.get("timestamp")
    cwd = params.get("cwd")
    if not isinstance(actions, list) or not isinstance(timestamp, str) or not timestamp:
        return (), 1
    cwd_path = (
        Path(cwd).expanduser()
        if isinstance(cwd, str) and cwd and Path(cwd).is_absolute()
        else None
    )
    session_id = pseudonym(
        params.get("threadId", params.get("conversationId")), namespace="codex-session"
    )
    turn_id = pseudonym(
        params.get("turnId", params.get("itemId", params.get("callId"))),
        namespace="codex-turn",
    )
    events: list[SkillEvent] = []
    rejected = 0
    for action_index, raw_action in enumerate(actions):
        if not isinstance(raw_action, dict):
            rejected += 1
            continue
        action = cast(dict[str, object], raw_action)
        if action.get("type") != "read":
            continue
        location = action.get("path")
        if not isinstance(location, str) or not location:
            rejected += 1
            continue
        candidate = Path(location).expanduser()
        if not candidate.is_absolute():
            if cwd_path is None:
                rejected += 1
                continue
            candidate = cwd_path / candidate
        lexical_candidate = _lexical_path(candidate)
        if lexical_candidate is None:
            rejected += 1
            continue
        skill = inventory.get(lexical_candidate)
        if skill is None:
            continue
        try:
            events.append(
                build_codex_event(
                    session_id=session_id,
                    turn_id=turn_id,
                    skill_name=skill[0],
                    trigger="model-read",
                    evidence_type="canonical-file-read",
                    confidence="qualified",
                    timestamp=timestamp,
                    signal_name="codex.app_server.command_read",
                    skill_content_hash=skill[1],
                    # Command-action identity is transport metadata. The action
                    # position handles repeated reads in one request; the request
                    # identity (or timestamp) distinguishes separate deliveries.
                    occurrence_id=first(
                        action, "id", "action_id", "item_id", "request_id"
                    )
                    or f"{first(params, 'itemId', 'item_id', 'callId', 'call_id', 'requestId') or first(source, 'id', 'request_id', 'event_id') or timestamp}:{action_index}",
                )
            )
        except ContractError:
            rejected += 1
    return tuple(events), rejected


def ingest_codex(
    inputs: tuple[Path, ...],
    store: EventStore,
    *,
    skills: tuple[tuple[str, Path], ...] = (),
    limits: IngestLimits = DEFAULT_INGEST_LIMITS,
) -> ImportStats:
    """Normalize bounded Codex documents before at-least-once persistence."""
    try:
        sources = discover_inputs(inputs, limits)
        inventory = _inventory(skills, limits)
        pending: list[SkillEvent] = []
        records_scanned = telemetry_records = rejected = nodes = structured_records = 0
        for source in sources:
            documents, _, source_records, nodes = _documents(
                source,
                limits,
                tolerate_jsonl=False,
                records_before=records_scanned,
                nodes_before=nodes,
            )
            records_scanned += source_records
            for document in documents:
                structured_objects, structured_records = _structured_objects(
                    document, limits, structured_records
                )
                for structured in structured_objects:
                    # Skill-input ordinals are intrinsic to their runtime turn. Never
                    # include input-file order, source paths, or document position:
                    # replaying one input from a batch must keep the same identity.
                    normalized = (
                        normalize_codex(structured)
                        if structured.get("method") == "turn/start"
                        or "explicit_skill" in structured
                        else []
                    )
                    events = [
                        event
                        for event in normalized
                        if event.evidence_type
                        in {"structured-input", "explicit-command"}
                    ]
                    canonical, failed = _codex_canonical_reads(structured, inventory)
                    pending.extend(events)
                    pending.extend(canonical)
                    telemetry_records += len(events) + len(canonical)
                    rejected += failed
        retained = store.append_many(pending)
    except IngestLimitError as exc:
        return _limit_stats("codex", exc)
    except ValueError as exc:
        if str(exc) == "normalized batch exceeds max_bytes":
            return _limit_stats("codex", IngestLimitError("max-normalized-batch-bytes"))
        raise
    return ImportStats(
        "codex",
        len(sources),
        records_scanned,
        telemetry_records,
        sum(retained),
        len(retained) - sum(retained),
        rejected,
    )
