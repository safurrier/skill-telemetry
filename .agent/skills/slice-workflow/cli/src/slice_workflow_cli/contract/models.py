"""Dataclasses and errors for plan-contract checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PlanMeta:
    slug: str = ""
    branch: str = ""
    created: str = ""
    pr: str = ""
    status: str = ""
    source: str = ""
    contract_change: str = ""
    decision_record: str = ""
    review_mode: str = ""
    review_backend: str = ""
    review_rubrics: list[str] = field(default_factory=list)
    evidence_required: list[str] = field(default_factory=list)
    continues_from: str = ""
    supersedes: str = ""


@dataclass
class PlanContext:
    path: Path
    meta: PlanMeta


@dataclass
class MarkdownSection:
    heading: str
    level: int
    content: str


@dataclass
class ArtifactEntry:
    type: str = ""
    path: str = ""
    note: str = ""


class PlanContractError(RuntimeError):
    """Expected plan-contract failure that should be shown without a traceback."""
