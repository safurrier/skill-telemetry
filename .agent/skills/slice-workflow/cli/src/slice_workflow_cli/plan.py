"""Plan creation command logic."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .output import log_ok, log_step

PLANS_DIR = Path(".ai") / "plans"
REQUIRED_PLAN_FILES = (
    "META.yaml",
    "TODO.md",
    "LEARNING_LOG.md",
    "VALIDATION.md",
    "REVIEW.md",
    "DECISIONS.md",
    "artifacts/manifest.yaml",
)
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PlanCreateError(RuntimeError):
    """Expected plan creation failure."""


def git_current_branch(root: Path) -> str:
    git = shutil.which("git")
    if git is None:
        return ""
    result = subprocess.run(  # noqa: S603 - executable is resolved with shutil.which.
        [git, "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def validate_slug(raw_slug: str) -> str:
    slug = raw_slug.strip()
    if not SLUG_RE.fullmatch(slug):
        raise PlanCreateError(
            "Invalid slug: use lowercase letters, digits, and single hyphens "
            "(example: add-user-auth)"
        )
    return slug


def resolve_templates_dir(root: Path) -> Path:
    candidates = [
        root / ".ai" / "plans" / "_templates",
        root / "templates" / ".ai" / "plans" / "_templates",
    ]
    for path in candidates:
        if not path.is_dir():
            continue
        missing = [name for name in REQUIRED_PLAN_FILES if not (path / name).exists()]
        if missing:
            raise PlanCreateError(
                "Plan templates are incomplete: "
                f"{', '.join(missing)} missing in {path.relative_to(root)}"
            )
        return path

    expected = ", ".join(str(path.relative_to(root)) for path in candidates)
    raise PlanCreateError(f"Plan templates not found. Expected one of: {expected}")


def find_existing_plan(root: Path, slug: str) -> Path | None:
    plans_root = root / PLANS_DIR
    if not plans_root.is_dir():
        return None
    for path in sorted(plans_root.iterdir()):
        if path.is_dir() and path.name.endswith(f"-{slug}"):
            return path
    return None


def create_plan(root: Path, slug: str, branch: str) -> Path:
    templates_dir = resolve_templates_dir(root)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    plan_dir = root / PLANS_DIR / f"{timestamp}-{slug}"
    plan_dir.mkdir(parents=True, exist_ok=False)

    created = datetime.now().strftime("%Y-%m-%d")

    for src in sorted(templates_dir.rglob("*")):
        if src.is_dir():
            continue
        dst = plan_dir / src.relative_to(templates_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text()
        content = content.replace("{{slug}}", slug)
        content = content.replace("{{branch}}", branch)
        content = content.replace("{{created}}", created)
        dst.write_text(content)

    return plan_dir


def run_plan(root: Path, slug_arg: str) -> int:
    slug = validate_slug(slug_arg)
    branch = git_current_branch(root)
    if not branch:
        raise PlanCreateError(
            "No git branch detected. Initialize git and create a feature branch first."
        )
    if branch in {"main", "master"}:
        raise PlanCreateError(
            f"You're on '{branch}'. Create a feature branch before starting work.\n"
            f"  git checkout -b feat/{slug}"
        )

    existing = find_existing_plan(root, slug)
    if existing is not None:
        raise PlanCreateError(
            f"A plan for '{slug}' already exists: {existing.relative_to(root)}"
        )

    log_step(f"Creating plan: {slug}")
    plan_dir = create_plan(root, slug, branch)
    log_ok(f"Plan created: {plan_dir.relative_to(root)}")

    print()
    print("  Files:")
    for path in sorted(
        file.relative_to(plan_dir) for file in plan_dir.rglob("*") if file.is_file()
    ):
        print(f"    {path}")
    print()
    print("  Next steps:")
    print("    1. Edit TODO.md, DECISIONS.md, and any scoped SPEC/IMPLEMENTATION docs")
    print("    2. Fill in META.yaml source and contract fields")
    print(
        "    3. Start working - append to LEARNING_LOG.md and VALIDATION.md as you go"
    )
    print("    4. Before handoff, complete REVIEW.md and artifacts/manifest.yaml")
    return 0
