"""Shared generic rules for public-source and artifact privacy checks."""

from __future__ import annotations

import re

# Detect machine-specific absolute home paths without encoding any contributor,
# organization, runtime-profile, or source-repository identity in this project.
PRIVATE_PATH_PATTERNS = (
    re.compile(rb"(?:^|[\s\"'=])/(?:Users|home)/[^/\s\"']+/", re.I),
    re.compile(rb"(?:^|[\s\"'=])[A-Za-z]:[/\\]Users[/\\][^/\\\s\"']+[/\\]", re.I),
    re.compile(rb"(?:^|[\s\"'=])/private/var/folders/", re.I),
)

CREDENTIAL_PATTERNS = (
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b", re.I),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b", re.I),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b", re.I),
    re.compile(rb"\bsk-(?:proj-|ant-|live-)[A-Za-z0-9_-]{16,}\b", re.I),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
)


def find_forbidden(content: bytes) -> str | None:
    """Return a neutral reason when content contains private-shaped material."""
    for pattern in PRIVATE_PATH_PATTERNS:
        if pattern.search(content):
            return "private path-shaped content"
    for pattern in CREDENTIAL_PATTERNS:
        if pattern.search(content):
            return "credential-shaped content"
    return None
