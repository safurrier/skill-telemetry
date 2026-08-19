"""Git helpers for plan-contract checks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .constants import PROJECT_ROOT
from .models import PlanContractError


def git_current_branch(root: Path = PROJECT_ROOT) -> str:
    git_bin = shutil.which("git")
    if git_bin is None:
        return ""
    result = subprocess.run(  # noqa: S603
        [git_bin, "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def git_changed_paths(root: Path = PROJECT_ROOT) -> list[str]:
    git_bin = shutil.which("git")
    if git_bin is None:
        raise PlanContractError(
            "git executable not found; cannot inspect changed paths."
        )
    result = subprocess.run(  # noqa: S603
        [git_bin, "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise PlanContractError(
            f"git status failed; cannot inspect changed paths: {message}"
        )

    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        entry = line[3:].strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        paths.append(entry)
    return paths


def git_diff_paths(root: Path, refspec: str) -> list[str]:
    git_bin = shutil.which("git")
    if git_bin is None:
        raise PlanContractError(
            "git executable not found; cannot inspect branch diff paths."
        )
    result = subprocess.run(  # noqa: S603
        [git_bin, "diff", "--name-only", refspec],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise PlanContractError(
            f"git diff failed for '{refspec}'; cannot inspect changed plans: {message}"
        )
    return [path.strip() for path in result.stdout.splitlines() if path.strip()]


def git_path_is_ignored(root: Path, path: Path) -> bool:
    git_bin = shutil.which("git")
    if git_bin is None:
        raise PlanContractError(
            "git executable not found; cannot inspect artifact ignore status."
        )
    try:
        relative = str(path.resolve().relative_to(root.resolve()))
    except ValueError as e:
        raise PlanContractError(f"Path is outside the repository: {path}") from e
    result = subprocess.run(  # noqa: S603
        [git_bin, "check-ignore", "--quiet", "--", relative],
        cwd=root,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise PlanContractError(f"git check-ignore failed for artifact path: {relative}")


def git_path_is_tracked(root: Path, path: Path) -> bool:
    git_bin = shutil.which("git")
    if git_bin is None:
        raise PlanContractError(
            "git executable not found; cannot inspect artifact tracked status."
        )
    try:
        relative = str(path.resolve().relative_to(root.resolve()))
    except ValueError as e:
        raise PlanContractError(f"Path is outside the repository: {path}") from e
    result = subprocess.run(  # noqa: S603
        [git_bin, "ls-files", "--error-unmatch", "--", relative],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    message = result.stderr.strip() or result.stdout.strip() or "unknown git error"
    raise PlanContractError(
        f"git ls-files failed for artifact path {relative}: {message}"
    )
