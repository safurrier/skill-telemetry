"""Independent typed ledger adapter for owner-only token usage points."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from skill_telemetry.ledger import JsonlLedger, LedgerError, LedgerSpec
from skill_telemetry.usage_contract import TokenUsagePoint

DEFAULT_USAGE_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_USAGE_MAX_FILES = 8


class UsageStoreError(ValueError):
    """Raised when retained usage cannot be read safely and completely."""


def usage_state_directory() -> Path:
    """Resolve the usage domain's state path independently of skill events."""
    configured = os.environ.get("SKILL_TELEMETRY_USAGE_STATE_DIR")
    if configured:
        directory = Path(configured).expanduser()
        if not directory.is_absolute():
            raise ValueError("SKILL_TELEMETRY_USAGE_STATE_DIR must be absolute")
        return directory
    xdg_state = os.environ.get("XDG_STATE_HOME")
    root = (
        Path(xdg_state).expanduser() if xdg_state else Path.home() / ".local" / "state"
    )
    if not root.is_absolute():
        raise ValueError("XDG_STATE_HOME must be absolute")
    return root / "skill-telemetry-usage"


def _fingerprint(point: TokenUsagePoint) -> str:
    payload = json.dumps(
        point.to_dict(), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(b"token-usage-v1\0" + payload).hexdigest()


def _store_error(error: LedgerError) -> UsageStoreError:
    message = str(error)
    if message in {"corrupt retained ledger", "retained record is not an object"}:
        return UsageStoreError("corrupt usage store")
    return UsageStoreError(
        message.replace("state directory", "usage state directory")
        .replace("retained path", "retained usage path")
        .replace("retained file", "retained usage file")
    )


class UsageStore:
    """TokenUsagePoint adapter over an exclusive-lock typed bounded JSONL ledger."""

    def __init__(
        self,
        directory: Path | None = None,
        *,
        max_bytes: int = DEFAULT_USAGE_MAX_BYTES,
        max_files: int = DEFAULT_USAGE_MAX_FILES,
    ) -> None:
        if max_bytes < 512:
            raise ValueError("max_bytes must be at least 512")
        if max_files < 1:
            raise ValueError("max_files must be at least 1")
        self.directory = directory or usage_state_directory()
        self.max_bytes = max_bytes
        self.max_files = max_files
        self._ledger: JsonlLedger[TokenUsagePoint, str] = JsonlLedger(
            LedgerSpec(
                directory=self.directory,
                file_prefix="usage",
                lock_name=".usage-store.lock",
                max_bytes=max_bytes,
                max_files=max_files,
                max_batch_records=50_000,
                encode=TokenUsagePoint.to_dict,
                decode=TokenUsagePoint.from_mapping,
                fingerprint=_fingerprint,
            )
        )

    @property
    def current_path(self) -> Path:
        return self._ledger.current_path

    def retained_paths(self, *, newest_first: bool = False) -> tuple[Path, ...]:
        """Enumerate validated retained files in deterministic chronological order."""
        try:
            return self._ledger.retained_paths(newest_first=newest_first)
        except LedgerError as exc:
            raise _store_error(exc) from exc

    def ensure_private(self) -> None:
        """Create the state directory with owner-only permissions."""
        try:
            self._ledger.ensure_private()
        except OSError as exc:
            if "symlinked state directory" in str(exc):
                raise OSError("refusing symlinked usage state directory") from exc
            raise

    def read_points(self) -> tuple[TokenUsagePoint, ...]:
        """Read a validated snapshot under an exclusive domain-specific lock."""
        try:
            return self._ledger.read()
        except LedgerError as exc:
            raise _store_error(exc) from exc

    def iter_points(self) -> Iterator[TokenUsagePoint]:
        yield from self.read_points()

    def append(self, point: TokenUsagePoint) -> bool:
        return self.append_many((point,))[0]

    def append_many(self, points: Iterable[TokenUsagePoint]) -> tuple[bool, ...]:
        """Append a validated batch once per exact histogram point."""
        try:
            return self._ledger.append_many(points)
        except LedgerError as exc:
            raise _store_error(exc) from exc
        except ValueError as exc:
            if str(exc) == "normalized record exceeds max_bytes":
                raise ValueError("normalized usage point exceeds max_bytes") from exc
            raise
