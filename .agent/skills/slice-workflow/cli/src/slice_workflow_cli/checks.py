"""Contract check command logic for slice workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contract import (
    PlanContext,
    PlanContractError,
    adr_dir,
    changed_plan_contexts,
    checklist_has_meaningful_items,
    extract_paths_from_bullets,
    file_has_meaningful_content,
    git_changed_paths,
    git_current_branch,
    git_diff_paths,
    git_path_is_ignored,
    git_path_is_tracked,
    in_progress_plan_contexts,
    is_placeholder_value,
    keyed_bullets,
    ledger_path,
    missing_required_plan_files,
    parse_artifact_manifest,
    plan_reference_present,
    resolve_plan_artifact_path,
    resolve_repo_path,
    section_bullets,
    section_has_meaningful_bullets,
    selected_plan_context,
    strip_changed_plan_paths,
    strip_plan_local_changes,
    validate_meta_yaml,
    validation_has_commands,
)
from .output import log_ok, log_step

CONTRACT_TASKS = ("plan-check", "spec-check", "evidence-check", "review-check")


class ContractCheckError(RuntimeError):
    """Expected contract check failure."""


def _selected(root: Path, plan_dir: str | None) -> tuple[PlanContext | None, bool]:
    args = ["--plan-dir", plan_dir] if plan_dir else []
    try:
        return selected_plan_context(root, args)
    except PlanContractError as e:
        raise ContractCheckError(str(e)) from e


def check_plan(root: Path, plan_dir: str | None = None) -> int:
    log_step("Checking plan contract")
    current, explicit_plan = _selected(root, plan_dir)

    meaningful_changes: list[str] = []
    if not explicit_plan:
        in_progress = in_progress_plan_contexts(root)
        if len(in_progress) > 1:
            lines = "\n".join(
                f"  - {ctx.path.relative_to(root)}" for ctx in in_progress
            )
            raise ContractCheckError(
                "Multiple plans are marked in-progress. Keep exactly one active slice."
                f"\n{lines}"
            )

        try:
            changed_paths = git_changed_paths(root)
        except PlanContractError as e:
            raise ContractCheckError(str(e)) from e
        meaningful_changes = strip_plan_local_changes(
            changed_paths, current.path if current else None, root
        )

    if current is None:
        if meaningful_changes:
            lines = "\n".join(f"  - {path}" for path in meaningful_changes)
            raise ContractCheckError(
                "Meaningful changes exist, but no active plan was found.\n" + lines
            )
        log_ok("No active plan and no meaningful changes")
        return 0

    missing = missing_required_plan_files(current.path)
    if missing:
        lines = "\n".join(f"  - {rel}" for rel in missing)
        raise ContractCheckError("Active plan is missing required files:\n" + lines)

    errors = validate_meta_yaml(current.meta)
    if errors:
        lines = "\n".join(f"  - {error}" for error in errors)
        raise ContractCheckError("META.yaml is incomplete:\n" + lines)

    branch = git_current_branch(root)
    if branch and current.meta.branch and current.meta.branch != branch:
        raise ContractCheckError(
            f"Plan branch '{current.meta.branch}' does not match current branch '{branch}'."
        )

    if not checklist_has_meaningful_items(current.path / "TODO.md"):
        raise ContractCheckError(
            "TODO.md must contain at least one meaningful checklist item."
        )

    if (
        not explicit_plan
        and meaningful_changes
        and current.meta.status != "in-progress"
    ):
        raise ContractCheckError(
            "Meaningful changes require the active plan status to be 'in-progress'."
        )

    if current.meta.status in {
        "in-progress",
        "complete",
    } and not file_has_meaningful_content(current.path / "LEARNING_LOG.md"):
        raise ContractCheckError(
            "LEARNING_LOG.md should record at least one in-progress note once work starts."
        )

    log_ok(f"Plan contract ready: {current.path.relative_to(root)}")
    return 0


def check_spec(root: Path, plan_dir: str | None = None) -> int:
    log_step("Checking spec and decision contract")
    current, _explicit_plan = _selected(root, plan_dir)
    if current is None:
        log_ok("No active plan to spec-check")
        return 0

    decisions_file = current.path / "DECISIONS.md"
    if not file_has_meaningful_content(decisions_file):
        raise ContractCheckError(
            "DECISIONS.md needs a real change summary before handoff."
        )

    for heading in ("What Changed", "Why"):
        if not section_has_meaningful_bullets(decisions_file, heading):
            raise ContractCheckError(
                f"DECISIONS.md is missing a meaningful '{heading}' section."
            )

    if current.meta.contract_change in {"docs_only", "contract_changed"}:
        reflected_paths = extract_paths_from_bullets(decisions_file, "Where Reflected")
        if not reflected_paths:
            raise ContractCheckError(
                "Docs or contract changes must list durable reflected paths in DECISIONS.md."
            )
        for raw_path in reflected_paths:
            target = resolve_repo_path(root, raw_path)
            if target is None:
                raise ContractCheckError(
                    f"Reflected path escapes the repository: {raw_path}"
                )
            if not target.exists():
                raise ContractCheckError(f"Reflected path does not exist: {raw_path}")

    if current.meta.decision_record == "ledger":
        active_ledger = ledger_path(root)
        if not active_ledger.exists():
            raise ContractCheckError("Decision ledger is missing.")
        if not plan_reference_present(
            active_ledger, current.path.name, current.meta.slug
        ):
            raise ContractCheckError(
                "Decision ledger must contain an entry referencing the active plan before sync-check passes."
            )

    if current.meta.decision_record == "adr":
        decisions_dir = adr_dir(root)
        adr_files = sorted(decisions_dir.glob("*.md")) if decisions_dir.exists() else []
        if not adr_files:
            raise ContractCheckError(
                "decision_record=adr requires an ADR under docs/explanation/decisions/."
            )
        if not any(
            plan_reference_present(path, current.path.name, current.meta.slug)
            for path in adr_files
        ):
            raise ContractCheckError(
                "No ADR references the active plan. Add or update an ADR before handoff."
            )

    log_ok(f"Spec contract ready: {current.path.relative_to(root)}")
    return 0


def check_evidence(root: Path, plan_dir: str | None = None) -> int:
    log_step("Checking evidence contract")
    current, _explicit_plan = _selected(root, plan_dir)
    if current is None:
        log_ok("No active plan to evidence-check")
        return 0

    validation_path = current.path / "VALIDATION.md"
    if not validation_has_commands(validation_path):
        raise ContractCheckError(
            "VALIDATION.md must contain real commands or captured verification output."
        )

    manifest_path = current.path / "artifacts" / "manifest.yaml"
    artifacts = parse_artifact_manifest(manifest_path)

    for artifact in artifacts:
        if not artifact.type:
            raise ContractCheckError(
                f"Artifact entry in {manifest_path.relative_to(root)} is missing a type."
            )
        if not artifact.path:
            raise ContractCheckError(
                f"Artifact entry in {manifest_path.relative_to(root)} is missing a path."
            )
        target = resolve_plan_artifact_path(current.path, artifact.path)
        if target is None:
            raise ContractCheckError(
                f"Artifact path escapes the active plan directory: {artifact.path}"
            )
        if not target.exists():
            raise ContractCheckError(
                f"Artifact path does not exist: {target.relative_to(root)}"
            )
        try:
            ignored = git_path_is_ignored(root, target)
            tracked = git_path_is_tracked(root, target)
        except PlanContractError as e:
            raise ContractCheckError(str(e)) from e
        if ignored:
            raise ContractCheckError(
                "Artifact path is ignored by git and will not survive CI checkout: "
                f"{target.relative_to(root)}"
            )
        if not tracked:
            raise ContractCheckError(
                "Artifact path is not tracked or staged for commit: "
                f"{target.relative_to(root)}"
            )

    for evidence_type in current.meta.evidence_required:
        if evidence_type == "commands":
            continue
        if not any(artifact.type == evidence_type for artifact in artifacts):
            raise ContractCheckError(
                f"Missing declared evidence type '{evidence_type}' in artifacts/manifest.yaml."
            )

    log_ok(f"Evidence contract ready: {current.path.relative_to(root)}")
    return 0


def check_review(root: Path, plan_dir: str | None = None) -> int:
    log_step("Checking review contract")
    current, _explicit_plan = _selected(root, plan_dir)
    if current is None:
        log_ok("No active plan to review-check")
        return 0

    review_path = current.path / "REVIEW.md"
    if not file_has_meaningful_content(review_path):
        raise ContractCheckError(
            "REVIEW.md must contain a completed review, not only placeholders."
        )

    context = keyed_bullets(review_path, "Review Context")
    mode = context.get("mode", "")
    backend = context.get("backend", "") or current.meta.review_backend
    reviewer = context.get("reviewer", "")

    if current.meta.review_mode == "external_required" and mode != "external":
        raise ContractCheckError(
            "REVIEW.md must record Mode: external when external review is required."
        )
    if not reviewer or is_placeholder_value(reviewer):
        raise ContractCheckError(
            "REVIEW.md must record the reviewer identity or external review context."
        )
    if not current.meta.review_backend or is_placeholder_value(
        current.meta.review_backend
    ):
        raise ContractCheckError(
            "META.yaml must record the backend that performed the review."
        )
    if not backend or backend.lower() == "self" or is_placeholder_value(backend):
        raise ContractCheckError(
            "An external review backend is required (subagent, skill, or manual_external)."
        )
    if current.meta.review_backend and current.meta.review_backend != backend:
        raise ContractCheckError("META.yaml review_backend does not match REVIEW.md.")

    rubrics = set(section_bullets(review_path, "Rubrics"))
    missing_rubrics = [
        name for name in current.meta.review_rubrics if name not in rubrics
    ]
    if missing_rubrics:
        lines = "\n".join(f"  - {rubric}" for rubric in missing_rubrics)
        raise ContractCheckError("REVIEW.md is missing rubric coverage for:\n" + lines)

    for heading in ("Findings", "Disposition"):
        if not section_has_meaningful_bullets(review_path, heading):
            raise ContractCheckError(
                f"REVIEW.md needs a meaningful '{heading}' section."
            )

    log_ok(f"Review contract ready: {current.path.relative_to(root)}")
    return 0


def run_contract_for_plan(root: Path, plan_dir: str) -> int:
    log_step(f"Checking plan: {plan_dir}")
    for task_name in CONTRACT_TASKS:
        run_check(root, task_name, plan_dir=plan_dir)
    return 0


REGENERATE_HK_EXPORT_HINT = (
    "Try: regenerate with `WORK_ID=$(hk status --target . --json | "
    "python3 -c 'import json,sys; print(json.load(sys.stdin)[\"active_work\"])')` "
    'then `hk export --format handoff-dir --output ".ai/hk/$WORK_ID" --target .`.'
)

HK_EXPORT_REQUIRED_FILES = (
    "README.md",
    "meta.json",
    "artifacts/README.md",
)
HK_EXPORT_HASHED_FILES = frozenset({"README.md", "artifacts/README.md"})


def _safe_export_relative(value: object) -> str | None:
    relative = str(value)
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not relative.strip():
        return None
    return path.as_posix()


HK_EXPORT_OBSOLETE_GENERATED_FILES = (
    "AGENTS.md",
    "SUMMARY.md",
    "HANDOFF.md",
    "VALIDATION.md",
    "REVIEW.md",
    "DECISIONS.md",
    "META.json",
)


def hk_export_dirs_from_paths(root: Path, paths: list[str]) -> list[Path]:
    exports: list[Path] = []
    for raw_path in paths:
        parts = Path(raw_path).parts
        if len(parts) >= 4 and parts[0] == ".ai" and parts[1] == "hk":
            candidate = root / parts[0] / parts[1] / parts[2]
            if candidate.is_dir() and candidate not in exports:
                exports.append(candidate)
    return exports


def validate_hk_export_dir(root: Path, export_dir: Path) -> None:
    if not export_dir.exists() or not export_dir.is_dir():
        raise ContractCheckError(
            f"HK export directory is missing: {export_dir.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    missing = [
        filename
        for filename in HK_EXPORT_REQUIRED_FILES
        if not (export_dir / filename).exists()
    ]
    present_top_level_names = {path.name for path in export_dir.iterdir()}
    obsolete = [
        filename
        for filename in HK_EXPORT_OBSOLETE_GENERATED_FILES
        if filename in present_top_level_names
    ]
    if missing:
        lines = "\n".join(f"  - {item}" for item in missing)
        raise ContractCheckError(
            f"HK export is missing required files: {export_dir.relative_to(root)}\n"
            + lines
            + "\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    if obsolete:
        lines = "\n".join(f"  - {item}" for item in obsolete)
        raise ContractCheckError(
            f"HK export contains obsolete generated files: {export_dir.relative_to(root)}\n"
            + lines
            + "\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    meta_path = export_dir / "meta.json"
    if meta_path.is_symlink():
        raise ContractCheckError(
            f"HK export metadata must not be a symlink: {meta_path.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    try:
        metadata = json.loads(meta_path.read_text())
    except json.JSONDecodeError as e:
        raise ContractCheckError(
            f"Invalid HK export metadata {meta_path}: {e}\n" + REGENERATE_HK_EXPORT_HINT
        ) from e
    if not isinstance(metadata, dict):
        raise ContractCheckError(
            f"Invalid HK export metadata {meta_path}: expected JSON object\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    required = {
        "schema_version",
        "generated_by",
        "work_id",
        "git_sha",
        "diff_hash",
        "event_count",
        "event_seq",
        "evidence_count",
        "output_path",
        "files",
    }
    missing_keys = sorted(key for key in required if key not in metadata)
    if missing_keys:
        raise ContractCheckError(
            f"HK export metadata missing keys in {meta_path.relative_to(root)}: "
            + ", ".join(missing_keys)
            + "\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    if metadata.get("generated_by") != "hk export --format handoff-dir":
        raise ContractCheckError(
            f"HK export metadata has unexpected generated_by in {meta_path.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    if metadata.get("output_path") != export_dir.relative_to(root).as_posix():
        raise ContractCheckError(
            f"HK export metadata output_path does not match directory: {meta_path.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    files_value = metadata.get("files")
    if not isinstance(files_value, list):
        raise ContractCheckError(
            f"HK export metadata files list is invalid: {meta_path.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    files = [str(item) for item in files_value]
    unsafe_files = sorted(item for item in files if _safe_export_relative(item) is None)
    missing_required_files = sorted(set(HK_EXPORT_REQUIRED_FILES) - set(files))
    if unsafe_files or missing_required_files:
        details = []
        if missing_required_files:
            details.append(
                "missing required files: " + ", ".join(missing_required_files)
            )
        if unsafe_files:
            details.append("unsafe files: " + ", ".join(unsafe_files))
        raise ContractCheckError(
            f"HK export metadata files list does not match compact package shape: {meta_path.relative_to(root)} ("
            + "; ".join(details)
            + ")\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    if not str(metadata.get("diff_hash", "")).startswith("sha256:"):
        raise ContractCheckError(
            f"HK export metadata diff_hash is invalid: {meta_path.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    try:
        event_count = int(metadata.get("event_count") or 0)
    except (TypeError, ValueError) as e:
        raise ContractCheckError(
            f"HK export metadata event_count must be an integer: {meta_path.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        ) from e
    if event_count <= 0:
        raise ContractCheckError(
            f"HK export metadata event_count must be positive: {meta_path.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    file_hashes = metadata.get("file_hashes", {})
    if not isinstance(file_hashes, dict):
        raise ContractCheckError(
            f"HK export metadata file_hashes is invalid: {meta_path.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    attached_artifacts = metadata.get("attached_artifacts", [])
    if not isinstance(attached_artifacts, list):
        raise ContractCheckError(
            f"HK export metadata attached_artifacts is invalid: {meta_path.relative_to(root)}\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    copied_artifact_paths: set[str] = set()
    for index, item in enumerate(attached_artifacts):
        if not isinstance(item, dict):
            raise ContractCheckError(
                f"HK export attached_artifacts[{index}] is invalid: {meta_path.relative_to(root)}\n"
                + REGENERATE_HK_EXPORT_HINT
            )
        if "source_path" in item or "artifact_path" in item:
            raise ContractCheckError(
                f"HK export attached artifact metadata contains local-only paths: {meta_path.relative_to(root)}\n"
                + REGENERATE_HK_EXPORT_HINT
            )
        if not item.get("copied"):
            continue
        export_path = _safe_export_relative(item.get("export_path", ""))
        if export_path is None or not export_path.startswith("artifacts/"):
            raise ContractCheckError(
                f"HK export copied artifact has invalid export_path in {meta_path.relative_to(root)}\n"
                + REGENERATE_HK_EXPORT_HINT
            )
        copied_artifact_paths.add(export_path)
        if export_path not in files:
            raise ContractCheckError(
                f"HK export copied artifact is missing from files list: {export_path}\n"
                + REGENERATE_HK_EXPORT_HINT
            )
        if export_path not in file_hashes:
            raise ContractCheckError(
                f"HK export copied artifact is missing from file_hashes: {export_path}\n"
                + REGENERATE_HK_EXPORT_HINT
            )
        if item.get("sha256") and item.get("sha256") != file_hashes.get(export_path):
            raise ContractCheckError(
                f"HK export copied artifact sha256 does not match file_hashes: {export_path}\n"
                + REGENERATE_HK_EXPORT_HINT
            )
    expected_files = set(HK_EXPORT_REQUIRED_FILES) | copied_artifact_paths
    unexpected_files = sorted(set(files) - expected_files)
    if unexpected_files:
        raise ContractCheckError(
            f"HK export metadata files list has unexpected entries in {meta_path.relative_to(root)}: "
            + ", ".join(unexpected_files)
            + "\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    unsafe_hash_paths = sorted(
        str(relative)
        for relative in file_hashes
        if _safe_export_relative(relative) is None
    )
    unexpected_hash_paths = sorted(
        str(relative) for relative in file_hashes if str(relative) not in set(files)
    )
    if unsafe_hash_paths or unexpected_hash_paths:
        details = []
        if unsafe_hash_paths:
            details.append("unsafe paths: " + ", ".join(unsafe_hash_paths))
        if unexpected_hash_paths:
            details.append("unexpected paths: " + ", ".join(unexpected_hash_paths))
        raise ContractCheckError(
            f"HK export metadata file_hashes contains invalid paths in {meta_path.relative_to(root)}: "
            + "; ".join(details)
            + "\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    missing_hashes = sorted(HK_EXPORT_HASHED_FILES - set(file_hashes))
    if missing_hashes:
        raise ContractCheckError(
            f"HK export metadata file_hashes missing generated files in {meta_path.relative_to(root)}: "
            + ", ".join(missing_hashes)
            + "\n"
            + REGENERATE_HK_EXPORT_HINT
        )
    for relative, expected_hash in file_hashes.items():
        safe_relative = _safe_export_relative(relative)
        assert safe_relative is not None
        file_path = export_dir / safe_relative
        if not file_path.exists():
            raise ContractCheckError(
                f"HK export hashed file is missing: {file_path.relative_to(root)}\n"
                + REGENERATE_HK_EXPORT_HINT
            )
        if file_path.is_symlink():
            raise ContractCheckError(
                f"HK export hashed file must not be a symlink: {file_path.relative_to(root)}\n"
                + REGENERATE_HK_EXPORT_HINT
            )
        content = file_path.read_bytes()
        actual_hash = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            raise ContractCheckError(
                f"HK export file hash mismatch: {file_path.relative_to(root)}\n"
                + REGENERATE_HK_EXPORT_HINT
            )


def run_changed_hk_exports(root: Path, refspec: str) -> int:
    try:
        changed_paths = git_diff_paths(root, refspec)
    except PlanContractError as e:
        raise ContractCheckError(str(e)) from e
    exports = hk_export_dirs_from_paths(root, changed_paths)
    if not exports:
        ignored = {".ai/hk/AGENTS.md"}
        meaningful = [path for path in changed_paths if path not in ignored]
        if meaningful:
            lines = "\n".join(f"  - {path}" for path in meaningful)
            raise ContractCheckError(
                "Meaningful branch changes exist, but no changed HK export was found.\n"
                + lines
                + '\nRun `hk export --format handoff-dir --output ".ai/hk/$WORK_ID" --target .` and commit the generated export.'
            )
        log_ok("No changed HK exports and no meaningful branch changes")
        return 0
    log_step("Checking changed HK exports")
    for export_dir in exports:
        validate_hk_export_dir(root, export_dir)
        log_ok(f"HK export ready: {export_dir.relative_to(root)}")
    return 0


def run_all_hk_exports(root: Path) -> int:
    exports_root = root / ".ai" / "hk"
    if not exports_root.exists():
        log_ok("No HK exports")
        return 0
    log_step("Checking HK exports")
    for export_dir in sorted(path for path in exports_root.iterdir() if path.is_dir()):
        validate_hk_export_dir(root, export_dir)
        log_ok(f"HK export ready: {export_dir.relative_to(root)}")
    return 0


def run_changed_plans(root: Path, refspec: str) -> int:
    try:
        contexts = changed_plan_contexts(root, refspec)
        changed_paths = git_diff_paths(root, refspec)
    except PlanContractError as e:
        raise ContractCheckError(str(e)) from e

    meaningful_paths = strip_changed_plan_paths(changed_paths, contexts, root)
    if not contexts:
        if meaningful_paths:
            lines = "\n".join(f"  - {path}" for path in meaningful_paths)
            raise ContractCheckError(
                "Meaningful branch changes exist, but no changed plan was found.\n"
                + lines
            )
        log_ok("No changed plans and no meaningful branch changes")
        return 0

    if meaningful_paths:
        log_step("Non-plan branch changes covered by changed plan validation")
        for path in meaningful_paths:
            print(f"  - {path}")

    for context in contexts:
        if context.meta.status != "complete":
            raise ContractCheckError(
                "Changed plans must be marked complete before PR sync-check passes: "
                f"{context.path.relative_to(root)}"
            )
        run_contract_for_plan(root, str(context.path.relative_to(root)))
    return 0


def run_check(root: Path, check_name: str, plan_dir: str | None = None) -> int:
    if check_name == "plan-check":
        return check_plan(root, plan_dir)
    if check_name == "spec-check":
        return check_spec(root, plan_dir)
    if check_name == "evidence-check":
        return check_evidence(root, plan_dir)
    if check_name == "review-check":
        return check_review(root, plan_dir)
    raise ContractCheckError(f"Unknown check: {check_name}")


def run_sync_check(
    root: Path,
    *,
    plan_dir: str | None = None,
    changed_plans: str | None = None,
    changed_hk_exports: str | None = None,
    hk_exports_only: bool = False,
) -> int:
    log_step("Running sync-check")
    modes = [
        bool(plan_dir),
        bool(changed_plans),
        bool(changed_hk_exports),
        hk_exports_only,
    ]
    if sum(modes) > 1:
        raise ContractCheckError(
            "Use only one of --plan-dir, --changed-plans, --changed-hk-exports, or --hk-exports-only."
        )
    if plan_dir:
        run_contract_for_plan(root, plan_dir)
    elif changed_plans:
        run_changed_plans(root, changed_plans)
    elif changed_hk_exports:
        run_changed_hk_exports(root, changed_hk_exports)
    elif hk_exports_only:
        run_all_hk_exports(root)
    else:
        run_all_hk_exports(root)
        for task_name in CONTRACT_TASKS:
            run_check(root, task_name)
    log_ok("Sync-check passed")
    return 0
