"""Typed owner-only bounded JSONL ledger mechanics shared by retained domains."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import stat
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar, cast

ItemT = TypeVar("ItemT")
FingerprintT = TypeVar("FingerprintT", bound=Hashable)
JsonObject = dict[str, object]
MAX_FILE_INDEX = 1024
# A full retained window (current + rotations) also owns one lock file.
MAX_DIRECTORY_ENTRIES = MAX_FILE_INDEX + 1


class LedgerError(ValueError):
    """Raised when a retained ledger cannot be accessed safely and completely."""


@dataclass(frozen=True, slots=True)
class LedgerSpec(Generic[ItemT, FingerprintT]):
    """Domain-owned names and codecs for one typed JSONL ledger."""

    directory: Path
    file_prefix: str
    lock_name: str
    max_bytes: int
    max_files: int
    max_batch_records: int
    encode: Callable[[ItemT], Mapping[str, object]]
    decode: Callable[[JsonObject], ItemT]
    fingerprint: Callable[[ItemT], FingerprintT | None]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", self.file_prefix):
            raise ValueError("file_prefix must be a safe filename segment")
        if not re.fullmatch(r"\.[a-z][a-z0-9-]*\.lock", self.lock_name):
            raise ValueError("lock_name must be a safe hidden lock filename")
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if not 1 <= self.max_files <= MAX_FILE_INDEX:
            raise ValueError(f"max_files must be between 1 and {MAX_FILE_INDEX}")
        if self.max_batch_records < 1:
            raise ValueError("max_batch_records must be at least 1")


class JsonlLedger(Generic[ItemT, FingerprintT]):
    """Append-only typed ledger with bounded reads, dedupe, rotation, and pruning.

    Batches are completely normalized before the first write.  Storage errors are
    deliberately at-least-once: a failed append may have durably written a prefix.
    Retrying the same items suppresses that prefix by stable fingerprint and writes
    the remaining suffix.
    """

    def __init__(self, spec: LedgerSpec[ItemT, FingerprintT]) -> None:
        self.spec = spec
        self._retained_name = re.compile(
            rf"^{re.escape(spec.file_prefix)}(?:\.([1-9][0-9]*))?\.jsonl$"
        )

    @property
    def directory(self) -> Path:
        return self.spec.directory

    @property
    def current_path(self) -> Path:
        return self.directory / f"{self.spec.file_prefix}.jsonl"

    @staticmethod
    def _no_follow_flag() -> int:
        try:
            return os.O_NOFOLLOW
        except AttributeError as exc:
            raise OSError(
                "safe no-follow file access is unsupported on this platform"
            ) from exc

    def _directory_exists(self) -> bool:
        try:
            os.lstat(self.directory)
        except FileNotFoundError:
            return False
        return True

    def _validate_directory(self) -> None:
        try:
            metadata = os.lstat(self.directory)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(metadata.st_mode):
            raise LedgerError("state directory is not a safe directory")
        if stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != os.getuid():
            raise LedgerError("state directory is not owner-only")

    def _directory_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        try:
            with os.scandir(self.directory) as entries:
                for entry in entries:
                    if len(paths) >= MAX_DIRECTORY_ENTRIES:
                        raise LedgerError(
                            "state directory entry count exceeds configured bound"
                        )
                    paths.append(Path(entry.path))
        except LedgerError:
            raise
        except OSError as exc:
            raise LedgerError("unable to inspect state directory") from exc
        return tuple(paths)

    def _validate_regular(
        self, path: Path, *, max_size: int | None = None
    ) -> os.stat_result:
        try:
            metadata = os.lstat(path)
        except FileNotFoundError as exc:
            raise LedgerError("missing retained file") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (max_size is not None and metadata.st_size > max_size)
        ):
            raise LedgerError("retained file is not owner-only")
        return metadata

    def retained_paths(
        self, *, newest_first: bool = False, allow_excess_retention: bool = False
    ) -> tuple[Path, ...]:
        """Return validated retained files from oldest to newest by default."""
        if not self._directory_exists():
            return ()
        self._validate_directory()
        indexed: list[tuple[int, Path]] = []
        for path in self._directory_paths():
            match = self._retained_name.fullmatch(path.name)
            if match is None:
                continue
            index = int(match.group(1)) if match.group(1) else 0
            if index >= MAX_FILE_INDEX or (
                index >= self.spec.max_files and not allow_excess_retention
            ):
                raise LedgerError("retained file index exceeds configured bound")
            self._validate_regular(path, max_size=self.spec.max_bytes)
            indexed.append((index, path))
        if len(indexed) > MAX_FILE_INDEX or (
            len(indexed) > self.spec.max_files and not allow_excess_retention
        ):
            raise LedgerError("retained file count exceeds configured bound")
        indexed.sort(key=lambda item: item[0], reverse=not newest_first)
        return tuple(path for _, path in indexed)

    def ensure_private(self) -> None:
        """Create the ledger directory and enforce owner-only permissions."""
        if self.directory.is_symlink():
            raise OSError("refusing symlinked state directory")
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.directory.chmod(0o700)
        self._validate_directory()

    def _read_unlocked(self) -> tuple[ItemT, ...]:
        items: list[ItemT] = []
        record_limit = (self.spec.max_bytes // 3) * self.spec.max_files
        try:
            for path in self.retained_paths():
                fd = os.open(path, os.O_RDONLY | self._no_follow_flag())
                try:
                    metadata = os.fstat(fd)
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or stat.S_IMODE(metadata.st_mode) != 0o600
                        or metadata.st_uid != os.getuid()
                        or metadata.st_size > self.spec.max_bytes
                    ):
                        raise LedgerError("retained file is not owner-only")
                    with os.fdopen(fd, encoding="utf-8") as stream:
                        fd = -1
                        for line in stream:
                            if not line.strip():
                                continue
                            if len(items) >= record_limit:
                                raise LedgerError(
                                    "retained record count exceeds configured bound"
                                )
                            value = json.loads(line)
                            if not isinstance(value, dict):
                                raise LedgerError("retained record is not an object")
                            items.append(self.spec.decode(cast(JsonObject, value)))
                finally:
                    if fd >= 0:
                        os.close(fd)
        except LedgerError:
            raise
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise LedgerError("corrupt retained ledger") from exc
        return tuple(items)

    def read(self) -> tuple[ItemT, ...]:
        """Read a validated snapshot under an exclusive lock."""
        if not self._directory_exists():
            return ()
        self._validate_directory()
        lock_fd = self._open_private(self.directory / self.spec.lock_name)
        locked = False
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            locked = True
            return self._read_unlocked()
        finally:
            if locked:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def iterate(self) -> Iterator[ItemT]:
        yield from self.read()

    def append(self, item: ItemT) -> bool:
        return self.append_many((item,))[0]

    def append_many(self, items: Iterable[ItemT]) -> tuple[bool, ...]:
        """Preflight a bounded batch, then append it under one exclusive lock."""
        prepared: list[tuple[FingerprintT | None, bytes]] = []
        prepared_bytes = 0
        for item in items:
            if len(prepared) >= self.spec.max_batch_records:
                raise ValueError("normalized batch exceeds max_records")
            payload = dict(self.spec.encode(item))
            line = (
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()
            if len(line) > self.spec.max_bytes:
                raise ValueError("normalized record exceeds max_bytes")
            prepared_bytes += len(line)
            if prepared_bytes > self.spec.max_bytes:
                raise ValueError("normalized batch exceeds max_bytes")
            prepared.append((self.spec.fingerprint(item), line))
        if not prepared:
            return ()

        self.ensure_private()
        lock_fd = self._open_private(self.directory / self.spec.lock_name)
        locked = False
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            locked = True
            self._enforce_retention_limit()
            fingerprints = {
                fingerprint
                for retained in self._read_unlocked()
                if (fingerprint := self.spec.fingerprint(retained)) is not None
            }
            results: list[bool] = []
            for fingerprint, line in prepared:
                if fingerprint is not None and fingerprint in fingerprints:
                    results.append(False)
                    continue
                self._rotate_if_needed(len(line))
                self._append_line(line)
                if fingerprint is not None:
                    fingerprints.add(fingerprint)
                results.append(True)
            return tuple(results)
        except LedgerError:
            raise
        except OSError as exc:
            raise LedgerError(
                "ledger append failed; retry may suppress a durable prefix"
            ) from exc
        finally:
            if locked:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _open_private(self, path: Path, *, append: bool = False) -> int:
        flags = os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | self._no_follow_flag()
        if append:
            flags |= os.O_APPEND
        fd = os.open(path, flags, 0o600)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise LedgerError("ledger lock is not a regular file")
            if metadata.st_uid != os.getuid():
                raise LedgerError("ledger lock is not owner-only")
            os.fchmod(fd, 0o600)
            return fd
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _write_all(fd: int, content: bytes) -> None:
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError(errno.EIO, "short ledger write")
            view = view[written:]

    def _append_line(self, line: bytes) -> None:
        fd = self._open_private(self.current_path, append=True)
        try:
            original_size = os.fstat(fd).st_size
            try:
                self._write_all(fd, line)
            except OSError:
                # For caught write errors, try to truncate the partial JSON line so
                # retry sees only complete records. Abrupt termination or failure of
                # this ftruncate/fsync repair can still leave a torn final line that
                # requires corruption recovery or manual cleanup. A later fsync failure
                # after a complete write keeps that line as an at-least-once prefix.
                os.ftruncate(fd, original_size)
                os.fsync(fd)
                raise
            os.fsync(fd)
        finally:
            os.close(fd)

    def _enforce_retention_limit(self) -> None:
        for path in self.retained_paths(newest_first=True, allow_excess_retention=True):
            match = self._retained_name.fullmatch(path.name)
            assert match is not None
            index = int(match.group(1)) if match.group(1) else 0
            if index >= self.spec.max_files:
                os.unlink(path)

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        try:
            current_size = self._validate_regular(
                self.current_path, max_size=self.spec.max_bytes
            ).st_size
        except LedgerError as exc:
            if "missing retained file" in str(exc):
                return
            raise
        if current_size + incoming_bytes <= self.spec.max_bytes:
            return
        if self.spec.max_files == 1:
            os.unlink(self.current_path)
            return
        oldest = self._rotated_path(self.spec.max_files - 1)
        try:
            os.unlink(oldest)
        except FileNotFoundError:
            pass
        for index in range(self.spec.max_files - 2, 0, -1):
            source = self._rotated_path(index)
            try:
                self._validate_regular(source, max_size=self.spec.max_bytes)
            except LedgerError as exc:
                if "missing retained file" in str(exc):
                    continue
                raise
            os.replace(source, self._rotated_path(index + 1))
        os.replace(self.current_path, self._rotated_path(1))

    def _rotated_path(self, index: int) -> Path:
        return self.directory / f"{self.spec.file_prefix}.{index}.jsonl"
