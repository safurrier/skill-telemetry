"""Privacy primitives shared by collectors and runtime adapters."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
SECRET_LIKE = re.compile(
    r"(?i)(?:^|[._+-])(?:sk-(?:proj-|ant-|or-|[A-Za-z0-9_-]{12,})|github_pat_|"
    r"gh[pousr]_|glpat-|xox[baprs]-|bearer[-_:]|A[KS]IA[0-9A-Z]{12,})"
)
SIGNAL_PREFIXES = ("claude_code.", "codex.", "gen_ai.", "pi.")
PROHIBITED_KEYS = frozenset(
    {
        "prompt",
        "raw_prompt",
        "user_prompt",
        "assistant_response",
        "response_text",
        "api_body",
        "request_body",
        "response_body",
        "tool_input",
        "tool_output",
        "tool_content",
        "path",
        "file_path",
        "repository_content",
    }
)


def pseudonym(value: object, *, namespace: str) -> str | None:
    """Return a stable namespaced digest without retaining the source value."""
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    digest = hashlib.sha256(
        f"skill-telemetry-v1:{namespace}:{text}".encode()
    ).hexdigest()
    return f"sha256:{digest}"


def content_hash(content: bytes) -> str:
    """Hash content without retaining it."""
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def safe_name(value: object) -> str | None:
    """Return a bounded identifier only when it cannot encode a filesystem path."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not SAFE_NAME.fullmatch(candidate):
        return None
    if ".." in candidate or candidate.startswith(("/", "~")):
        return None
    if SECRET_LIKE.search(candidate):
        return None
    return candidate


def safe_signal_name(value: object) -> str | None:
    """Accept only scoped runtime signal identifiers, never arbitrary record content."""
    candidate = safe_name(value)
    if candidate is None or not candidate.startswith(SIGNAL_PREFIXES):
        return None
    return candidate


def find_prohibited_keys(value: object, *, prefix: str = "") -> list[str]:
    """Find prohibited raw-content field names recursively."""
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower().replace(".", "_").replace("-", "_")
            field = f"{prefix}.{key}" if prefix else str(key)
            if normalized in PROHIBITED_KEYS:
                findings.append(field)
            findings.extend(find_prohibited_keys(nested, prefix=field))
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            findings.extend(find_prohibited_keys(nested, prefix=f"{prefix}[{index}]"))
    return findings
