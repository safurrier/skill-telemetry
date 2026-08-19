"""Constants for plan-contract validation."""

from __future__ import annotations

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("MISE_PROJECT_ROOT", "."))

CHECKLIST_PREFIX = re.compile(r"^\[[ xX]\]\s+")
COMMAND_PATTERN = re.compile(
    r"\bmise\s+(?:-[\w-]+\s+)*run\b|\bcargo (?:fmt|check|test|clippy|run|build)\b|"
    r"\buv run\b|\bgo test\b|\bpytest\b|\bdocker\b"
)

PLAN_REQUIRED_FILES = (
    Path("META.yaml"),
    Path("TODO.md"),
    Path("LEARNING_LOG.md"),
    Path("VALIDATION.md"),
    Path("REVIEW.md"),
    Path("DECISIONS.md"),
    Path("artifacts") / "manifest.yaml",
)
PLAN_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}-")
PLAN_ACTIVE_STATUSES = {"planned", "in-progress"}
ALLOWED_META_STATUSES = {"planned", "in-progress", "complete", "abandoned"}
ALLOWED_CONTRACT_CHANGES = {"implementation_only", "docs_only", "contract_changed"}
ALLOWED_DECISION_RECORDS = {"none", "ledger", "adr"}
ALLOWED_REVIEW_MODES = {"external_required"}
PLACEHOLDER_VALUES = {
    "",
    "-",
    "todo",
    "tbd",
    "pending",
    "pending review",
    "pending review.",
    "pending sync",
    "pending sync.",
    "pending implementation",
    "fill me in",
    "replace this placeholder with the actual slice tasks",
    "add artifact paths to artifacts/manifest.yaml as they are produced",
}
NON_SLICE_BOOTSTRAP_PATHS = {
    "uv.lock",
    "go.sum",
    "Cargo.lock",
    "test-results",
    "test-results/",
}
NON_SLICE_BOOTSTRAP_FILENAMES = {"uv.lock", "go.sum", "Cargo.lock"}
