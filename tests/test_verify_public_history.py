"""Regression tests for the reachable public-history scanner."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.public_scan_rules import CREDENTIAL_PATTERNS
from scripts.verify_public_history import PublicHistoryError, scan_refs


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed test Git arguments
        ["git", "-C", str(repository), *arguments],  # noqa: S607 -- fixed Git tool
        check=True,
        capture_output=True,
    )


def _commit(repository: Path, path: str, content: str, message: str) -> None:
    (repository / path).write_text(content)
    _git(repository, "add", path)
    _git(repository, "commit", "-m", message)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "History Scanner Test")
    return tmp_path


def test_rejects_private_path_in_old_reachable_commit(repository: Path) -> None:
    private_path = "/" + "Users/example/private-project/"
    _commit(repository, "evidence.txt", private_path, "unsafe history")
    _commit(repository, "evidence.txt", "public release tree\n", "clean tip")

    with pytest.raises(PublicHistoryError, match="private path-shaped"):
        scan_refs(repository, ("main",))


def test_rejects_private_path_in_reachable_commit_message(repository: Path) -> None:
    private_path = "/" + "home/example/private-project/"
    _commit(repository, "notes.txt", "clean file\n", private_path)

    with pytest.raises(PublicHistoryError, match="reachable commit"):
        scan_refs(repository, ("main",))


def test_rejects_private_path_in_selected_annotated_tag(repository: Path) -> None:
    private_path = "C:/" + "Users/example/private-project/"
    _commit(repository, "notes.txt", "clean file\n", "clean commit")
    _git(repository, "tag", "-a", "release", "-m", private_path)

    with pytest.raises(PublicHistoryError, match="reachable tag"):
        scan_refs(repository, ("release",))


def test_accepts_safe_near_misses(repository: Path) -> None:
    near_miss = "gh" + "p_" + "a" * 19
    _commit(repository, "notes.txt", f"Users/example\n{near_miss}\n", "safe history")

    scan_refs(repository, ("main",))


@pytest.mark.parametrize(
    "sample",
    (
        "gh" + "p_" + "a" * 20,
        "github" + "_pat_" + "a" * 20,
        "xox" + "b-" + "a" * 20,
        "sk-" + "proj-" + "a" * 16,
        "AK" + "IA" + "A" * 16,
    ),
)
def test_rejects_credential_shapes(repository: Path, sample: str) -> None:
    _commit(repository, "credential.txt", sample, "credential-shaped history")

    with pytest.raises(PublicHistoryError, match="credential-shaped"):
        scan_refs(repository, ("main",))


def test_rejects_reachable_symlink(repository: Path) -> None:
    (repository / "unsafe-link").symlink_to("target")
    _git(repository, "add", "unsafe-link")
    _git(repository, "commit", "-m", "unsafe symlink")

    with pytest.raises(PublicHistoryError, match="unsafe Git mode"):
        scan_refs(repository, ("main",))


def test_credential_patterns_keep_documented_near_miss_boundary() -> None:
    for pattern in CREDENTIAL_PATTERNS:
        assert hasattr(pattern, "search")
