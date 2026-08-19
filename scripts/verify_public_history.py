"""Reject private or unsafe objects reachable from proposed public Git refs."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scripts.public_scan_rules import find_forbidden

MAX_BLOB_BYTES = 5 * 1024 * 1024
GENERATED_PATH_PARTS = frozenset(
    {
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "test-results",
    }
)
UNSAFE_MODES = frozenset({"120000", "160000"})


class PublicHistoryError(RuntimeError):
    """A selected public ref contains material that must not be published."""


@dataclass(frozen=True)
class TreeEntry:
    """One path stored in a selected Git tree."""

    mode: str
    object_id: str
    path: str


def _run_git(repository: Path, *arguments: str) -> bytes:
    return subprocess.check_output(  # noqa: S603 -- refs are explicit scanner input
        ["git", "-C", str(repository), *arguments],  # noqa: S607 -- fixed Git tool
        stderr=subprocess.STDOUT,
    )


def _tree_entries(repository: Path, ref: str) -> tuple[TreeEntry, ...]:
    output = _run_git(repository, "ls-tree", "-r", "-z", ref)
    entries: list[TreeEntry] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", maxsplit=1)
        mode, _kind, object_id = metadata.decode("ascii").split(" ")
        entries.append(
            TreeEntry(mode=mode, object_id=object_id, path=raw_path.decode("utf-8"))
        )
    return tuple(entries)


def _validate_path(entry: TreeEntry) -> None:
    path = PurePosixPath(entry.path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in GENERATED_PATH_PARTS for part in path.parts)
    ):
        raise PublicHistoryError(
            f"unsafe generated path in public history: {entry.path}"
        )
    if entry.mode in UNSAFE_MODES:
        raise PublicHistoryError(
            f"unsafe Git mode {entry.mode} in public history: {entry.path}"
        )
    reason = find_forbidden(entry.path.encode("utf-8"))
    if reason is not None:
        raise PublicHistoryError(f"{reason} in public path: {entry.path}")


def _reachable_object_ids(repository: Path, refs: Sequence[str]) -> frozenset[str]:
    output = _run_git(repository, "rev-list", "--objects", *refs)
    return frozenset(
        line.split(maxsplit=1)[0].decode("ascii")
        for line in output.splitlines()
        if line
    )


def _reachable_commits(repository: Path, refs: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        line.decode("ascii")
        for line in _run_git(repository, "rev-list", *refs).splitlines()
        if line
    )


def _read_textual_object(repository: Path, object_id: str) -> tuple[bytes, bytes]:
    object_type = _run_git(repository, "cat-file", "-t", object_id).strip()
    if object_type not in {b"blob", b"commit", b"tag"}:
        return object_type, b""
    size = int(_run_git(repository, "cat-file", "-s", object_id).strip())
    if size > MAX_BLOB_BYTES:
        raise PublicHistoryError(
            f"public {object_type.decode()} {object_id} exceeds "
            f"{MAX_BLOB_BYTES} byte scan limit"
        )
    return object_type, _run_git(
        repository, "cat-file", object_type.decode(), object_id
    )


def _selected_tag_ids(repository: Path, refs: Sequence[str]) -> frozenset[str]:
    tag_ids: set[str] = set()
    for ref in refs:
        if _run_git(repository, "cat-file", "-t", ref).strip() == b"tag":
            tag_ids.add(_run_git(repository, "rev-parse", ref).strip().decode("ascii"))
    return frozenset(tag_ids)


def scan_refs(repository: Path, refs: Sequence[str]) -> None:
    """Scan every object reachable from explicitly selected publication refs."""
    if not refs:
        raise PublicHistoryError("at least one publication ref is required")
    object_ids = _reachable_object_ids(repository, refs)
    blob_ids: set[str] = set()
    for commit in _reachable_commits(repository, refs):
        for entry in _tree_entries(repository, commit):
            _validate_path(entry)
            blob_ids.add(entry.object_id)

    # `rev-list --objects` supplies the complete reachable set, including blobs
    # that no longer appear at a selected ref's tip but remain in its ancestry.
    for object_id in sorted(object_ids | _selected_tag_ids(repository, refs)):
        object_type, content = _read_textual_object(repository, object_id)
        if object_type == b"blob":
            blob_ids.add(object_id)
        elif object_type in {b"commit", b"tag"}:
            reason = find_forbidden(content)
            if reason is not None:
                raise PublicHistoryError(
                    f"{reason} in reachable {object_type.decode()} {object_id}"
                )
    for object_id in sorted(blob_ids):
        _object_type, content = _read_textual_object(repository, object_id)
        reason = find_forbidden(content)
        if reason is not None:
            raise PublicHistoryError(f"{reason} in reachable blob {object_id}")


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        action="append",
        dest="refs",
        default=[],
        help="Git ref selected for publication; repeat for each public ref",
    )
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path.cwd(),
        help="repository to scan (default: current directory)",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = parse_args(arguments)
    refs = tuple(args.refs) or ("HEAD",)
    try:
        scan_refs(args.repository.resolve(), refs)
    except (PublicHistoryError, subprocess.CalledProcessError) as error:
        print(f"public-history verification failed: {error}")
        return 1
    print(f"public-history verification passed for: {', '.join(refs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
