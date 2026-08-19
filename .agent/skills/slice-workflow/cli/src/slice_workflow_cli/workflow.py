"""Prompt rendering and status logic for slice workflow tasks."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .contract import (
    ArtifactEntry,
    PlanContext,
    current_plan_context,
    file_has_meaningful_content,
    missing_required_plan_files,
    parse_artifact_manifest,
    parse_meta_yaml,
    validation_has_commands,
)

WORKFLOW_SKILL_NAME = "slice-workflow"
PROMPTS_DIR_NAME = "prompts"
TASK_SNAPSHOT_NAME = "TASK.md"
TEMPLATE_VAR_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

PHASE_TEMPLATE_FILES = {
    "planner": "planner.md",
    "implementer": "implementer.md",
    "reviewer": "reviewer.md",
}

PHASE_OUTPUT_FILES = {
    "planner": "planner.md",
    "implementer": "implementer.md",
    "reviewer": "reviewer.md",
}

VALID_PHASES = tuple(PHASE_TEMPLATE_FILES)


class SliceWorkflowError(RuntimeError):
    """Expected workflow error that should be shown without a traceback."""


@dataclass(frozen=True)
class RenderResult:
    phase: str
    plan_path: str
    prompt_path: str
    task_path: str
    printed: bool
    changed: bool


@dataclass(frozen=True)
class SliceStatus:
    plan_path: str
    slug: str
    branch: str
    status: str
    required_files_missing: list[str]
    prompts: dict[str, str]
    validation_has_commands: bool
    review_has_content: bool
    artifact_count: int


def relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def load_plan(root: Path, plan_arg: str | None) -> PlanContext:
    if plan_arg:
        plan_path = Path(plan_arg)
        if not plan_path.is_absolute():
            plan_path = root / plan_path
        meta = parse_meta_yaml(plan_path / "META.yaml")
        if meta is None:
            raise SliceWorkflowError(
                f"Plan not found or missing META.yaml: {relative_path(plan_path, root)}"
            )
        return PlanContext(path=plan_path, meta=meta)

    plan = current_plan_context(root)
    if plan is None:
        raise SliceWorkflowError(
            "No active plan found. Run `mise run plan -- <slug>` first, then retry."
        )
    return plan


def workflow_skill_dir(root: Path) -> Path:
    candidates = [
        root / ".agent" / "skills" / WORKFLOW_SKILL_NAME,
        root / "templates" / ".agent" / "skills" / WORKFLOW_SKILL_NAME,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise SliceWorkflowError(
        "slice-workflow skill not found. Expected .agent/skills/slice-workflow "
        "or templates/.agent/skills/slice-workflow."
    )


def template_path(root: Path, phase: str) -> Path:
    if phase not in PHASE_TEMPLATE_FILES:
        raise SliceWorkflowError(
            f"Unknown slice workflow phase '{phase}'. Valid phases: "
            f"{', '.join(VALID_PHASES)}"
        )
    path = workflow_skill_dir(root) / "templates" / PHASE_TEMPLATE_FILES[phase]
    if not path.exists():
        raise SliceWorkflowError(
            f"Prompt template missing: {relative_path(path, root)}"
        )
    return path


def read_task_context(
    root: Path, task: str | None, task_text: str | None
) -> tuple[str, str]:
    if task and task_text:
        raise SliceWorkflowError("Use either --task or --task-text, not both.")
    if task:
        task_path = Path(task)
        if not task_path.is_absolute():
            task_path = root / task_path
        if not task_path.exists():
            raise SliceWorkflowError(
                f"Task file not found: {relative_path(task_path, root)}"
            )
        return task_path.read_text().strip(), relative_path(task_path, root)
    if task_text:
        return task_text.strip(), "(inline task text)"
    return "", ""


def write_task_snapshot(plan: PlanContext, task_body: str, task_path: str) -> str:
    if not task_body:
        return ""

    target = plan.path / TASK_SNAPSHOT_NAME
    content = "\n".join(
        [
            f"# Task - {plan.meta.slug}",
            "",
            f"- Source: {task_path}",
            "",
            "## Task Text",
            "",
            task_body,
            "",
        ]
    )
    target.write_text(content)
    return str(target)


def plan_summary(plan: PlanContext) -> str:
    parts: list[str] = []
    for filename in ("SPEC.md", "IMPLEMENTATION.md", "TODO.md", "DECISIONS.md"):
        path = plan.path / filename
        if path.exists() and file_has_meaningful_content(path):
            parts.append(f"## {filename}\n\n{path.read_text().strip()}")
    if not parts:
        return "No meaningful plan content has been written yet."
    return "\n\n---\n\n".join(parts)


def render_template(source: str, values: dict[str, str]) -> str:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.append(key)
            return match.group(0)
        return values[key]

    rendered = TEMPLATE_VAR_RE.sub(replace, source)
    if missing:
        raise SliceWorkflowError(
            "Prompt template has unknown variable(s): "
            + ", ".join(sorted(set(missing)))
        )
    return rendered


def render_phase_prompt(
    *,
    root: Path,
    phase: str,
    plan_arg: str | None = None,
    task: str | None = None,
    task_text: str | None = None,
    print_prompt: bool = False,
) -> RenderResult:
    plan = load_plan(root, plan_arg)
    task_body, task_path = read_task_context(root, task, task_text)
    if phase == "planner" and not task_body:
        raise SliceWorkflowError(
            "slice-plan requires --task <path> or --task-text <text>."
        )

    task_snapshot = write_task_snapshot(plan, task_body, task_path)
    template = template_path(root, phase).read_text()
    prompt_dir = plan.path / PROMPTS_DIR_NAME
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / PHASE_OUTPUT_FILES[phase]

    values = {
        "phase": phase,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_root": str(root),
        "plan_path": relative_path(plan.path, root),
        "plan_slug": plan.meta.slug,
        "plan_status": plan.meta.status,
        "plan_branch": plan.meta.branch,
        "task_path": task_path or "(see active plan)",
        "task_text": task_body or "(see active plan)",
        "task_snapshot_path": relative_path(Path(task_snapshot), root)
        if task_snapshot
        else "",
        "plan_summary": plan_summary(plan),
    }
    rendered = render_template(template, values)
    previous = prompt_path.read_text() if prompt_path.exists() else ""
    changed = previous != rendered
    prompt_path.write_text(rendered)

    if print_prompt:
        print(rendered)

    return RenderResult(
        phase=phase,
        plan_path=relative_path(plan.path, root),
        prompt_path=relative_path(prompt_path, root),
        task_path=task_path,
        printed=print_prompt,
        changed=changed,
    )


def artifact_count(entries: list[ArtifactEntry]) -> int:
    return len(entries)


def inspect_status(root: Path, plan_arg: str | None = None) -> SliceStatus:
    plan = load_plan(root, plan_arg)
    prompts_dir = plan.path / PROMPTS_DIR_NAME
    prompts: dict[str, str] = {}
    if prompts_dir.exists():
        for path in sorted(prompts_dir.glob("*.md")):
            prompts[path.stem] = relative_path(path, root)

    return SliceStatus(
        plan_path=relative_path(plan.path, root),
        slug=plan.meta.slug,
        branch=plan.meta.branch,
        status=plan.meta.status,
        required_files_missing=[
            str(path) for path in missing_required_plan_files(plan.path)
        ],
        prompts=prompts,
        validation_has_commands=validation_has_commands(plan.path / "VALIDATION.md"),
        review_has_content=file_has_meaningful_content(plan.path / "REVIEW.md"),
        artifact_count=artifact_count(
            parse_artifact_manifest(plan.path / "artifacts" / "manifest.yaml")
        ),
    )


def print_render_result(result: RenderResult, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        return

    print(f"Prompt written: {result.prompt_path}")
    if result.task_path:
        print(f"Task source: {result.task_path}")
    print(f"Changed: {'yes' if result.changed else 'no'}")


def print_status(status: SliceStatus, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(asdict(status), indent=2, sort_keys=True))
        return

    print(f"Plan: {status.plan_path}")
    print(f"Slug: {status.slug}")
    print(f"Status: {status.status}")
    print(f"Branch: {status.branch}")
    if status.required_files_missing:
        print("Missing required files:")
        for path in status.required_files_missing:
            print(f"  - {path}")
    else:
        print("Missing required files: none")
    print("Prompts:")
    if status.prompts:
        for phase, path in status.prompts.items():
            print(f"  - {phase}: {path}")
    else:
        print("  none")
    print(f"Validation commands: {'yes' if status.validation_has_commands else 'no'}")
    print(f"Review content: {'yes' if status.review_has_content else 'no'}")
    print(f"Artifacts declared: {status.artifact_count}")
