"""The version is set in one place, ``pyproject.toml``. The API advertises it
in its OpenAPI document, and ``web/package.json`` carries the same string."""

from __future__ import annotations

import json
import tomllib
from importlib.metadata import version
from pathlib import Path

from sensei_top.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_installed_metadata_matches_pyproject() -> None:
    assert version("sensei-top") == _pyproject_version()


def test_web_package_matches_pyproject() -> None:
    package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == _pyproject_version()


def test_api_version_matches_pyproject(tmp_path: Path) -> None:
    assert create_app(tmp_path / "v.db").version == _pyproject_version()
