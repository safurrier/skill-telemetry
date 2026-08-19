"""Repository path and decision-document helpers."""

from __future__ import annotations

from pathlib import Path

from .constants import PROJECT_ROOT


def resolve_repo_path(root: Path, raw_path: str) -> Path | None:
    candidate = (root / raw_path).resolve()
    repo_root = root.resolve()
    if candidate == repo_root or repo_root in candidate.parents:
        return candidate
    return None


def ledger_path(root: Path = PROJECT_ROOT) -> Path:
    generated = root / "docs" / "explanation" / "decision-ledger.md"
    legacy = root / "docs" / "decision-ledger.md"

    if generated.exists():
        return generated
    if legacy.exists():
        return legacy
    return generated


def adr_dir(root: Path = PROJECT_ROOT) -> Path:
    generated = root / "docs" / "explanation" / "decisions"
    legacy = root / "docs" / "decisions"

    if generated.exists():
        return generated
    if legacy.exists():
        return legacy
    return generated


def plan_reference_present(path: Path, plan_id: str, slug: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text()
    return plan_id in text or slug in text or f".ai/plans/{plan_id}" in text
