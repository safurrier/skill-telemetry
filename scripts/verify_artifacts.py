"""Assert distributable artifacts are complete, neutral, and installable in isolation."""

from __future__ import annotations

import os
import subprocess
import tempfile
import venv
from pathlib import Path
from tarfile import open as open_tarfile
from zipfile import ZipFile

from scripts.public_scan_rules import (  # noqa: F401
    CREDENTIAL_PATTERNS,
    PRIVATE_PATH_PATTERNS,
    find_forbidden,
)

DIST = Path("dist")
FORBIDDEN_SEGMENTS = ("node_modules/", "pi/", "package.json", "package-lock.json")
RUNTIME_FILES = tuple(
    f"skill_telemetry/{path.relative_to('src/skill_telemetry').as_posix()}"
    for path in sorted(Path("src/skill_telemetry").rglob("*.py"))
)
REQUIRED_PACKAGE_FILES = (
    *RUNTIME_FILES,
    "skill_telemetry/py.typed",
    "skill_telemetry/campaigns/acceptance-v1.json",
    "skill_telemetry/campaigns/acceptance-observations-v1.json",
    "skill_telemetry/schemas/envelope-v1.json",
    "skill_telemetry/schemas/command-data-v1.json",
)


def _assert_required(names: list[str], required: tuple[str, ...], label: str) -> None:
    for path in required:
        assert any(name.endswith(path) for name in names), f"{label} missing {path}"


def _assert_no_node_files(names: list[str], label: str) -> None:
    assert not any(
        segment in name for name in names for segment in FORBIDDEN_SEGMENTS
    ), f"{label} includes Node/Pi development files"


def _assert_neutral(content: bytes, label: str) -> None:
    reason = find_forbidden(content)
    assert reason is None, f"{label} contains {reason}"


def _assert_tracked_source_neutral() -> None:
    tracked = subprocess.check_output(
        ["git", "ls-files"],  # noqa: S607 -- repository tool is fixed
        text=True,
    ).splitlines()
    for name in tracked:
        path = Path(name)
        if path.is_file() and ".git" not in path.parts:
            _assert_neutral(path.read_bytes(), f"tracked source {name}")


def _smoke_installed(artifact: Path) -> None:
    """Install outside the checkout and exercise only public Python commands."""
    with tempfile.TemporaryDirectory(prefix="skill-telemetry-artifact-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
        executable = environment / "bin" / "skill-telemetry"
        python = environment / "bin" / "python"
        subprocess.run(  # noqa: S603 -- local artifact path is verified above
            [
                str(python),
                "-m",
                "pip",
                "install",
                str(artifact.resolve()),
            ],
            check=True,
            cwd=root,
            stdout=subprocess.DEVNULL,
        )
        clean_environment = {
            key: value
            for key, value in os.environ.items()
            if key != "PYTHONPATH" and not key.startswith("SKILL_TELEMETRY_")
        }
        clean_home = root / "home"
        clean_state = root / "state"
        clean_home.mkdir(mode=0o700)
        clean_state.mkdir(mode=0o700)
        clean_environment.update(
            {
                "HOME": str(clean_home),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "XDG_STATE_HOME": str(clean_state),
            }
        )
        for args, expected in (
            (("version", "--format", "json"), 0),
            (("readout", "--format", "json"), 0),
            (("usage", "--format", "json"), 0),
            (("evaluate", "--format", "json"), 0),
            (("doctor", "--endpoint", "http://127.0.0.1:1", "--format", "json"), 6),
        ):
            result = subprocess.run(  # noqa: S603 -- installed local console script
                [str(executable), *args],
                cwd=root,
                env=clean_environment,
                check=False,
                capture_output=True,
                text=True,
            )
            assert result.returncode == expected, (
                f"{artifact.name} {' '.join(args)}: exit={result.returncode} "
                f"stdout={result.stdout} stderr={result.stderr}"
            )


def main() -> None:
    wheels = list(DIST.glob("*.whl"))
    sdists = list(DIST.glob("*.tar.gz"))
    assert len(wheels) == 1, f"expected one wheel, found {wheels}"
    assert len(sdists) == 1, f"expected one sdist, found {sdists}"
    _assert_tracked_source_neutral()

    with ZipFile(wheels[0]) as wheel:
        wheel_names = wheel.namelist()
        entry_points = next(
            (
                name
                for name in wheel_names
                if name.endswith(".dist-info/entry_points.txt")
            ),
            None,
        )
        metadata = next(
            (name for name in wheel_names if name.endswith(".dist-info/METADATA")), None
        )
        assert entry_points is not None, "wheel missing console-script metadata"
        assert metadata is not None, "wheel missing package metadata"
        assert (
            "skill-telemetry = skill_telemetry.cli:main"
            in wheel.read(entry_points).decode()
        )
        assert "License-File: LICENSE" in wheel.read(metadata).decode()
        for name in wheel_names:
            if not name.endswith("/"):
                _assert_neutral(wheel.read(name), f"wheel {name}")
    _assert_required(wheel_names, REQUIRED_PACKAGE_FILES, "wheel")
    assert any(name.endswith("LICENSE") for name in wheel_names), (
        "wheel missing license"
    )
    _assert_no_node_files(wheel_names, "wheel")

    with open_tarfile(sdists[0]) as sdist:
        sdist_names = sdist.getnames()
        for member in sdist.getmembers():
            if member.isfile():
                extracted = sdist.extractfile(member)
                assert extracted is not None
                _assert_neutral(extracted.read(), f"sdist {member.name}")
    _assert_required(sdist_names, REQUIRED_PACKAGE_FILES, "sdist")
    assert any(name.endswith("LICENSE") for name in sdist_names), (
        "sdist missing license"
    )
    assert any(name.endswith("pyproject.toml") for name in sdist_names), (
        "sdist missing metadata"
    )
    _assert_no_node_files(sdist_names, "sdist")
    _smoke_installed(wheels[0])
    _smoke_installed(sdists[0])


if __name__ == "__main__":
    main()
