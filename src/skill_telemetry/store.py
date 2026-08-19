"""Owner-only bounded XDG event storage."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from skill_telemetry.contract import SkillEvent
from skill_telemetry.ledger import JsonlLedger, LedgerError, LedgerSpec

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_FILES = 4


class StoreError(ValueError):
    """Raised when retained telemetry cannot be read safely and completely."""


def state_directory() -> Path:
    """Resolve an absolute XDG state-owned directory without a machine-specific path."""
    configured = os.environ.get("SKILL_TELEMETRY_STATE_DIR")
    if configured:
        directory = Path(configured).expanduser()
        if not directory.is_absolute():
            raise ValueError("SKILL_TELEMETRY_STATE_DIR must be absolute")
        return directory
    xdg_state = os.environ.get("XDG_STATE_HOME")
    root = (
        Path(xdg_state).expanduser() if xdg_state else Path.home() / ".local" / "state"
    )
    if not root.is_absolute():
        raise ValueError("XDG_STATE_HOME must be absolute")
    return root / "skill-telemetry"


def _activation_fingerprint(event: SkillEvent) -> str | None:
    return event.activation_id


def _store_error(error: LedgerError) -> StoreError:
    message = str(error)
    if message in {"corrupt retained ledger", "retained record is not an object"}:
        return StoreError("corrupt skill telemetry event store")
    return StoreError(
        message.replace("state directory", "skill telemetry state directory")
        .replace("retained path", "retained skill telemetry path")
        .replace("retained file", "retained skill telemetry file")
    )


class EventStore:
    """SkillEvent adapter over an exclusive-lock typed bounded JSONL ledger."""

    def __init__(
        self,
        directory: Path | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        if max_bytes < 256:
            raise ValueError("max_bytes must be at least 256")
        if max_files < 1:
            raise ValueError("max_files must be at least 1")
        self.directory = directory or state_directory()
        self.max_bytes = max_bytes
        self.max_files = max_files
        self._ledger: JsonlLedger[SkillEvent, str] = JsonlLedger(
            LedgerSpec(
                directory=self.directory,
                file_prefix="events",
                lock_name=".store.lock",
                max_bytes=max_bytes,
                max_files=max_files,
                max_batch_records=50_000,
                encode=SkillEvent.to_dict,
                decode=SkillEvent.from_mapping,
                fingerprint=_activation_fingerprint,
            )
        )

    @property
    def current_path(self) -> Path:
        return self._ledger.current_path

    def retained_paths(self, *, newest_first: bool = False) -> tuple[Path, ...]:
        """Enumerate every retained event file in deterministic chronological order."""
        try:
            return self._ledger.retained_paths(newest_first=newest_first)
        except LedgerError as exc:
            raise _store_error(exc) from exc

    def ensure_private(self) -> None:
        """Create the state directory and enforce owner-only permissions and ownership."""
        try:
            self._ledger.ensure_private()
        except OSError as exc:
            if "symlinked state directory" in str(exc):
                raise OSError(
                    "refusing symlinked skill telemetry state directory"
                ) from exc
            raise

    def read_events(self) -> tuple[SkillEvent, ...]:
        """Read every retained event under an exclusive lock, failing on corruption."""
        try:
            return self._ledger.read()
        except LedgerError as exc:
            raise _store_error(exc) from exc

    def iter_events(self) -> Iterator[SkillEvent]:
        """Iterate over a validated snapshot from oldest retained file to newest."""
        yield from self.read_events()

    def append(self, event: SkillEvent) -> bool:
        """Append once. Return false for an already-retained activation fingerprint."""
        return self.append_many((event,))[0]

    def append_many(self, events: Iterable[SkillEvent]) -> tuple[bool, ...]:
        """Append a validated batch under one lock and return per-event retention results."""
        try:
            return self._ledger.append_many(events)
        except LedgerError as exc:
            raise _store_error(exc) from exc
        except ValueError as exc:
            if str(exc) == "normalized record exceeds max_bytes":
                raise ValueError("normalized event exceeds max_bytes") from exc
            raise
