"""Output helpers for the slice-workflow CLI."""

from __future__ import annotations

import sys


def log_step(message: str) -> None:
    print(f"==> {message}")


def log_ok(message: str) -> None:
    print(f"  ok {message}")


def log_error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
