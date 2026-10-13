"""scripts/release_notes.py, exercised as a subprocess against a changelog
written in the test. There is no Arena or MTGO log in play: the input is the
Keep a Changelog form (https://keepachangelog.com/en/1.1.0/), and each
expected value is the text of that fixture, not the script's output."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_notes.py"

CHANGELOG = """\
# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- Not yet released.

## [0.8.0] - 2026-11-02

### Added

- A newer thing.

## [0.7.10] - 2026-10-25

### Added

- The tenth patch, whose heading begins with 0.7.1.

## [0.7.1] - 2026-10-20

### Fixed

- The thing that broke.

  A second paragraph of the same item.

### Changed

- Another thing.

## [0.7.0] - 2026-10-15

### Added

- The first public release.

[Unreleased]: https://example.invalid/compare/v0.8.0...HEAD
[0.8.0]: https://example.invalid/compare/v0.7.1...v0.8.0
[0.7.1]: https://example.invalid/compare/v0.7.0...v0.7.1
[0.7.0]: https://example.invalid/releases/tag/v0.7.0
"""


def run(tmp_path: Path, *args: str, text: str = CHANGELOG) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--changelog", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_middle_version_comes_back_exactly(tmp_path):
    """The trap: `## [0.7.10]` sits above `## [0.7.1]`, so a heading match that is a
    bare prefix of the version would start at the wrong section."""
    result = run(tmp_path, "--version", "0.7.1")
    assert result.returncode == 0
    assert result.stdout == (
        "### Fixed\n"
        "\n"
        "- The thing that broke.\n"
        "\n"
        "  A second paragraph of the same item.\n"
        "\n"
        "### Changed\n"
        "\n"
        "- Another thing.\n"
    )
    assert "## [" not in result.stdout


def test_last_section_stops_before_the_link_references(tmp_path):
    result = run(tmp_path, "--version", "0.7.0")
    assert result.returncode == 0
    assert result.stdout == "### Added\n\n- The first public release.\n"


def test_first_section_stops_at_the_next_heading(tmp_path):
    result = run(tmp_path, "--version", "0.8.0")
    assert result.returncode == 0
    assert result.stdout == "### Added\n\n- A newer thing.\n"


def test_missing_version_exits_1(tmp_path):
    result = run(tmp_path, "--version", "0.9.0")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "0.9.0" in result.stderr


def test_a_version_longer_than_a_heading_is_not_matched(tmp_path):
    result = run(tmp_path, "--version", "0.7.100")
    assert result.returncode == 1


def test_unreleased_exits_1(tmp_path):
    result = run(tmp_path, "--version", "Unreleased")
    assert result.returncode == 1
    assert result.stdout == ""


def test_default_version_is_pyprojects(tmp_path):
    # Nothing in the fixture is named for pyproject's version, so the run
    # shows which version was looked up, not what was printed.
    version = next(
        line.split('"')[1]
        for line in (SCRIPT.parents[1] / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        if line.startswith("version = ")
    )
    result = run(tmp_path, text="## [Unreleased]\n\n- x\n")
    assert result.returncode == 1
    assert version in result.stderr


def test_an_empty_section_exits_1(tmp_path):
    text = "## [0.7.0] - 2026-10-15\n\n## [0.6.0] - 2026-09-01\n\n- x\n"
    result = run(tmp_path, "--version", "0.7.0", text=text)
    assert result.returncode == 1
