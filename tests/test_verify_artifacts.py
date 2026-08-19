"""Regression tests for the release artifact privacy scanner."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "verify_artifacts", Path(__file__).parents[1] / "scripts/verify_artifacts.py"
)
assert SPEC is not None and SPEC.loader is not None
verify_artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_artifacts)


@pytest.mark.parametrize(
    "sample",
    (
        "/" + "Users/example/project/",
        "/" + "home/example/project/",
        "C:/" + "Users/example/project/",
        "/private/" + "var/folders/example/",
    ),
)
@pytest.mark.parametrize("artifact", ("tracked source", "wheel", "sdist"))
def test_artifact_scanner_rejects_machine_specific_absolute_paths(
    sample: str, artifact: str
) -> None:
    with pytest.raises(AssertionError):
        verify_artifacts._assert_neutral(sample.encode(), artifact)


@pytest.mark.parametrize(
    ("pattern", "sample"),
    tuple(
        zip(
            verify_artifacts.CREDENTIAL_PATTERNS,
            (
                "gh" + "p_" + "a" * 20,
                "github" + "_pat_" + "a" * 20,
                "xox" + "b-" + "a" * 20,
                "sk-" + "proj-" + "a" * 16,
                "AK" + "IA" + "A" * 16,
            ),
            strict=True,
        )
    ),
)
def test_artifact_scanner_rejects_every_credential_pattern(
    pattern: object, sample: str
) -> None:
    assert hasattr(pattern, "search") and pattern.search(sample.encode())
    with pytest.raises(AssertionError):
        verify_artifacts._assert_neutral(sample.encode(), "credential sample")


@pytest.mark.parametrize(
    "near_miss",
    (
        "gh" + "p_" + "a" * 19,
        "github" + "_pat_" + "a" * 19,
        "xox" + "b-" + "a" * 19,
        "sk-" + "proj-" + "a" * 15,
        "AK" + "IA" + "A" * 15,
    ),
)
def test_artifact_scanner_accepts_credential_pattern_near_misses(
    near_miss: str,
) -> None:
    verify_artifacts._assert_neutral(near_miss.encode(), "credential near miss")
