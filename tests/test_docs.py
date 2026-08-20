"""Validate every authored documentation page in skill-telemetry."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

# Resolve repo root: walk up from tests/ to find AGENTS.md or .mise.toml.
# Works for both single-project (tests/ at root) and apps workspace
# (apps/<module>/tests/ inside a subdirectory).
_THIS_DIR = Path(__file__).resolve().parent


def _find_repo_root() -> Path:
    candidate = _THIS_DIR.parent
    for _ in range(5):
        if (candidate / ".mise.toml").exists() or (candidate / ".git").exists():
            return candidate
        candidate = candidate.parent
    return _THIS_DIR.parent  # fallback


PROJECT_ROOT = _find_repo_root()
DOCS_DIR = PROJECT_ROOT / "docs"


# ── Minimal frontmatter helpers (inline, no external deps) ────────────────


def _has_frontmatter(path: Path) -> bool:
    return path.read_text().startswith("---\n")


def _parse_frontmatter_id(path: Path) -> str | None:
    text = path.read_text()
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    raw = text[4:end]
    m = re.search(r"^id:\s*(.+)$", raw, re.MULTILINE)
    return m.group(1).strip() if m else None


# ── Authored documentation corpus ─────────────────────────────────────────

EXPECTED_DOCS = sorted(
    path for path in DOCS_DIR.rglob("*.md") if path.name != "AGENTS.md"
)


# ── Tests ─────────────────────────────────────────────────────────────────


def test_agents_md_exists() -> None:
    """AGENTS.md must exist at repo root."""
    assert (PROJECT_ROOT / "AGENTS.md").exists()
    assert (DOCS_DIR / "AGENTS.md").exists()


def test_agents_md_has_required_sections() -> None:
    """AGENTS.md must have WHY/WHAT/HOW structure."""
    content = (PROJECT_ROOT / "AGENTS.md").read_text()
    assert "## WHY" in content
    assert "## WHAT" in content
    assert "## HOW" in content


def test_agents_md_has_no_frontmatter() -> None:
    """AGENTS.md is a steering doc, not a docs/ page — no frontmatter."""
    agents = PROJECT_ROOT / "AGENTS.md"
    if agents.exists():
        assert not _has_frontmatter(agents), "AGENTS.md should not have frontmatter"


def test_claude_md_matches_agents() -> None:
    """CLAUDE.md mirrors the public steering instructions without a symlink."""
    claude = PROJECT_ROOT / "CLAUDE.md"
    assert claude.exists(), "CLAUDE.md must exist"
    assert not claude.is_symlink(), "CLAUDE.md must be a regular public file"
    assert claude.read_text() == (PROJECT_ROOT / "AGENTS.md").read_text()


@pytest.mark.parametrize(
    "doc",
    EXPECTED_DOCS,
    ids=lambda p: str(p.relative_to(PROJECT_ROOT)),
)
def test_doc_has_frontmatter(doc: Path) -> None:
    """docs/ files must have YAML frontmatter."""
    assert _has_frontmatter(doc), f"{doc.relative_to(PROJECT_ROOT)} missing frontmatter"


@pytest.mark.parametrize(
    "doc",
    EXPECTED_DOCS,
    ids=lambda p: str(p.relative_to(PROJECT_ROOT)),
)
def test_doc_has_id(doc: Path) -> None:
    """docs/ files must have a frontmatter id field."""
    doc_id = _parse_frontmatter_id(doc)
    assert doc_id, f"{doc.relative_to(PROJECT_ROOT)} missing frontmatter id"


def test_doc_ids_are_unique() -> None:
    """All doc frontmatter ids must be unique."""
    ids: dict[str, Path] = {}
    for doc in EXPECTED_DOCS:
        if not doc.exists():
            continue
        doc_id = _parse_frontmatter_id(doc)
        if not doc_id:
            continue
        assert doc_id not in ids, (
            f"Duplicate id '{doc_id}' in {doc.relative_to(PROJECT_ROOT)} "
            f"and {ids[doc_id].relative_to(PROJECT_ROOT)}"
        )
        ids[doc_id] = doc


def test_local_markdown_links_resolve() -> None:
    """Local links in public documentation must name an existing path."""
    authored = [PROJECT_ROOT / "README.md", PROJECT_ROOT / "SPEC.md", *EXPECTED_DOCS]
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for doc in authored:
        for raw_target in pattern.findall(doc.read_text()):
            target = raw_target.split("#", 1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "#")):
                continue
            resolved = (doc.parent / target).resolve()
            assert resolved.exists(), (
                f"{doc.relative_to(PROJECT_ROOT)} links to missing path {raw_target}"
            )


def test_documented_versions_match_package_metadata() -> None:
    """Current install, response, and Pi support contexts follow metadata."""
    python_version = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())[
        "project"
    ]["version"]
    package = json.loads((PROJECT_ROOT / "package.json").read_text())
    pi_version = package["devDependencies"]["@earendil-works/pi-coding-agent"]

    for relative in ("README.md", "docs/tutorials/first-local-run.md"):
        content = (PROJECT_ROOT / relative).read_text()
        assert set(re.findall(r"@v(\d+\.\d+\.\d+)", content)) == {python_version}
    cli_reference = (PROJECT_ROOT / "docs/reference/cli.md").read_text()
    assert f'"tool_version": "{python_version}"' in cli_reference

    for relative in (
        "README.md",
        "SPEC.md",
        "docs/explanation/architecture.md",
        "docs/reference/runtime-support.md",
    ):
        content = (PROJECT_ROOT / relative).read_text()
        assert f"Pi {pi_version}" in content, relative


def test_public_docs_have_no_scaffold_placeholders() -> None:
    """Public pages must contain useful content rather than authoring prompts."""
    placeholders = (
        "No tutorials yet",
        "Add short, task-oriented guides here",
        "Put stable facts here",
        "Generated from: init",
    )
    for doc in EXPECTED_DOCS:
        content = doc.read_text()
        assert not any(marker in content for marker in placeholders), (
            f"{doc.relative_to(PROJECT_ROOT)} retains scaffold placeholder text"
        )
