from __future__ import annotations

import importlib.metadata
import json
import tomllib
from pathlib import Path

from skill_telemetry import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.1.0"


def test_release_version_contract_is_consistent_everywhere() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    package = json.loads((PROJECT_ROOT / "package.json").read_text())
    package_lock = json.loads((PROJECT_ROOT / "package-lock.json").read_text())
    uv_lock = (PROJECT_ROOT / "uv.lock").read_text()
    installed_version = importlib.metadata.version("skill-telemetry")

    assert pyproject["project"]["version"] == EXPECTED_VERSION
    assert __version__ == EXPECTED_VERSION
    assert package["version"] == EXPECTED_VERSION
    assert package_lock["packages"][""]["version"] == EXPECTED_VERSION
    assert installed_version == EXPECTED_VERSION
    assert (
        'name = "skill-telemetry"\nversion = "0.1.0"\nsource = { editable = "." }'
        in uv_lock
    )


def test_pi_manifest_uses_the_documented_core_dependency_split() -> None:
    package = json.loads((PROJECT_ROOT / "package.json").read_text())
    package_lock = json.loads((PROJECT_ROOT / "package-lock.json").read_text())

    assert package["private"] is True
    assert "pi-package" in package["keywords"]
    assert package["pi"]["extensions"] == ["./pi/src/index.ts"]
    assert package["peerDependencies"]["@earendil-works/pi-coding-agent"] == "*"
    assert package["devDependencies"]["@earendil-works/pi-coding-agent"] == "0.84.2"
    assert (
        package_lock["packages"][""]["peerDependencies"][
            "@earendil-works/pi-coding-agent"
        ]
        == "*"
    )
    assert (
        package_lock["packages"][""]["devDependencies"][
            "@earendil-works/pi-coding-agent"
        ]
        == "0.84.2"
    )


def test_node_manifest_has_no_install_lifecycle_scripts() -> None:
    scripts = json.loads((PROJECT_ROOT / "package.json").read_text())["scripts"]

    assert not {"preinstall", "install", "postinstall"}.intersection(scripts)
