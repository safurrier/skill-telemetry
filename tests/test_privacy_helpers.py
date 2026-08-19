# ruff: noqa
from __future__ import annotations

from skill_telemetry.privacy import (
    content_hash,
    find_prohibited_keys,
    pseudonym,
    safe_name,
    safe_signal_name,
)


def test_privacy_helpers_reject_unsafe_names_and_find_nested_content() -> None:
    assert pseudonym(None, namespace="test") is None
    assert pseudonym("", namespace="test") is None
    assert pseudonym("value", namespace="test") != pseudonym("value", namespace="other")
    assert content_hash(b"value").startswith("sha256:")
    assert safe_name("sample-skill") == "sample-skill"
    for unsafe in ("../sample", "/sample", "bad/name", "sk-proj-secret-token"):
        assert safe_name(unsafe) is None
    assert safe_signal_name("pi.skill.activation") == "pi.skill.activation"
    assert safe_signal_name("unscoped") is None
    assert find_prohibited_keys({"prompt": "x", "nested": [{"tool.output": "x"}]}) == [
        "prompt",
        "nested[0].tool.output",
    ]
