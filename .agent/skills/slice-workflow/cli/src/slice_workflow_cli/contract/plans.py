"""Plan discovery, metadata, and changed-plan helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import (
    ALLOWED_CONTRACT_CHANGES,
    ALLOWED_DECISION_RECORDS,
    ALLOWED_META_STATUSES,
    ALLOWED_REVIEW_MODES,
    NON_SLICE_BOOTSTRAP_FILENAMES,
    NON_SLICE_BOOTSTRAP_PATHS,
    PLAN_DIR_RE,
    PLAN_REQUIRED_FILES,
    PROJECT_ROOT,
)
from .docs import resolve_repo_path
from .git import git_diff_paths
from .models import PlanContext, PlanContractError, PlanMeta


def parse_meta_yaml(path: Path) -> PlanMeta | None:
    if not path.exists():
        return None

    meta = PlanMeta()
    list_fields = {"review_rubrics", "evidence_required"}
    current_list_key: str | None = None

    for raw_line in path.read_text().splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if current_list_key and raw_line.startswith("  - "):
            getattr(meta, current_list_key).append(raw_line[4:].strip())
            continue

        if not raw_line.startswith(" "):
            current_list_key = None
            match = re.match(r"^([a-z_]+):\s*(.*)$", line)
            if not match:
                continue
            key, value = match.group(1), match.group(2).strip()
            if key in list_fields:
                current_list_key = key
                setattr(meta, key, [])
            elif hasattr(meta, key):
                setattr(meta, key, value)

    return meta


def validate_meta_yaml(meta: PlanMeta) -> list[str]:
    errors: list[str] = []

    if not meta.slug:
        errors.append("missing 'slug' field")
    if not meta.created:
        errors.append("missing 'created' field")
    elif not re.match(r"^\d{4}-\d{2}-\d{2}$", meta.created):
        errors.append(f"created '{meta.created}' is not YYYY-MM-DD format")

    if not meta.status:
        errors.append("missing 'status' field")
    elif meta.status not in ALLOWED_META_STATUSES:
        errors.append(
            f"status '{meta.status}' not in allowed values: "
            f"{', '.join(sorted(ALLOWED_META_STATUSES))}"
        )

    if not meta.contract_change:
        errors.append("missing 'contract_change' field")
    elif meta.contract_change not in ALLOWED_CONTRACT_CHANGES:
        errors.append(
            f"contract_change '{meta.contract_change}' not in allowed values: "
            f"{', '.join(sorted(ALLOWED_CONTRACT_CHANGES))}"
        )

    if not meta.decision_record:
        errors.append("missing 'decision_record' field")
    elif meta.decision_record not in ALLOWED_DECISION_RECORDS:
        errors.append(
            f"decision_record '{meta.decision_record}' not in allowed values: "
            f"{', '.join(sorted(ALLOWED_DECISION_RECORDS))}"
        )

    if not meta.review_mode:
        errors.append("missing 'review_mode' field")
    elif meta.review_mode not in ALLOWED_REVIEW_MODES:
        errors.append(
            f"review_mode '{meta.review_mode}' not in allowed values: "
            f"{', '.join(sorted(ALLOWED_REVIEW_MODES))}"
        )

    if not meta.review_rubrics:
        errors.append("missing or empty 'review_rubrics' field")
    if not meta.evidence_required:
        errors.append("missing or empty 'evidence_required' field")

    return errors


def list_plan_contexts(root: Path = PROJECT_ROOT) -> list[PlanContext]:
    plans_root = root / ".ai" / "plans"
    if not plans_root.exists():
        return []
    contexts: list[PlanContext] = []
    for path in sorted(plans_root.iterdir()):
        if not path.is_dir() or not PLAN_DIR_RE.match(path.name):
            continue
        meta = parse_meta_yaml(path / "META.yaml")
        if meta is None:
            continue
        contexts.append(PlanContext(path=path, meta=meta))
    return contexts


def plan_context_from_dir(root: Path, raw_path: str) -> PlanContext:
    target = resolve_repo_path(root, raw_path)
    if target is None:
        raise PlanContractError(f"Plan path escapes the repository: {raw_path}")
    if not target.is_dir():
        raise PlanContractError(f"Plan path is not a directory: {raw_path}")

    plans_root = (root / ".ai" / "plans").resolve()
    if target.parent != plans_root:
        raise PlanContractError(f"Plan path is not under .ai/plans: {raw_path}")
    if not PLAN_DIR_RE.match(target.name):
        raise PlanContractError(f"Plan directory name is invalid: {target.name}")

    meta = parse_meta_yaml(target / "META.yaml")
    if meta is None:
        raise PlanContractError(f"Plan is missing META.yaml: {raw_path}")
    return PlanContext(path=target, meta=meta)


def current_plan_context(root: Path = PROJECT_ROOT) -> PlanContext | None:
    contexts = list_plan_contexts(root)
    in_progress = [ctx for ctx in contexts if ctx.meta.status == "in-progress"]
    if len(in_progress) == 1:
        return in_progress[0]
    planned = [ctx for ctx in contexts if ctx.meta.status == "planned"]
    if planned:
        return planned[-1]
    return None


def in_progress_plan_contexts(root: Path = PROJECT_ROOT) -> list[PlanContext]:
    return [ctx for ctx in list_plan_contexts(root) if ctx.meta.status == "in-progress"]


def selected_plan_context(
    root: Path, args: list[str]
) -> tuple[PlanContext | None, bool]:
    if not args:
        return current_plan_context(root), False
    if len(args) == 2 and args[0] == "--plan-dir":
        return plan_context_from_dir(root, args[1]), True
    raise PlanContractError("Usage: [--plan-dir .ai/plans/<plan-dir>]")


def missing_required_plan_files(plan_dir: Path) -> list[Path]:
    return [rel for rel in PLAN_REQUIRED_FILES if not (plan_dir / rel).exists()]


def changed_plan_dir_names(paths: list[str]) -> list[str]:
    names: set[str] = set()
    for path in paths:
        parts = Path(path).parts
        if len(parts) >= 3 and parts[0] == ".ai" and parts[1] == "plans":
            if PLAN_DIR_RE.match(parts[2]):
                names.add(parts[2])
    return sorted(names)


def changed_plan_contexts(root: Path, refspec: str) -> list[PlanContext]:
    names = changed_plan_dir_names(git_diff_paths(root, refspec))
    return [plan_context_from_dir(root, f".ai/plans/{name}") for name in names]


def strip_changed_plan_paths(
    paths: list[str], contexts: list[PlanContext], root: Path = PROJECT_ROOT
) -> list[str]:
    prefixes = {str(ctx.path.relative_to(root)) for ctx in contexts}
    return [
        path
        for path in paths
        if path not in prefixes
        and not any(path.startswith(f"{prefix}/") for prefix in prefixes)
    ]


def strip_plan_local_changes(
    paths: list[str], plan_dir: Path | None, root: Path = PROJECT_ROOT
) -> list[str]:
    def _is_ignored(path: str) -> bool:
        if path in NON_SLICE_BOOTSTRAP_PATHS:
            return True
        if Path(path).name in NON_SLICE_BOOTSTRAP_FILENAMES:
            return True
        if (
            "__pycache__/" in path
            or path.endswith("/__pycache__")
            or path.endswith(".pyc")
        ):
            return True
        return False

    if plan_dir is None:
        return [path for path in paths if not _is_ignored(path)]
    try:
        prefix = str(plan_dir.resolve().relative_to(root.resolve()))
    except ValueError as e:
        raise PlanContractError("Plan path is not under repository root.") from e
    return [
        path
        for path in paths
        if not _is_ignored(path)
        and path != prefix
        and not path.startswith(f"{prefix}/")
    ]
