"""Shared test helpers.

Kept deliberately small: fixtures that only one module needs stay in that
module, per docs/testing.md.
"""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch, tmp_path):
    """Every test runs with a clean slate on ambient configuration: no
    ``MTGO_HANDLE``/``MTGO_LOG_DIR``, no Claude/TopDeck.gg credential, and no
    real ``~/.config/sensei-top/config.toml``. Two separate things would
    otherwise leak in:

    - ``projector/matches.py::project()`` calls ``project_mtgo``
      unconditionally on every ``project()`` call, and
      ``mtgo/config.py::load_handle()`` falls back to that same config
      file's ``[mtgo]`` table. Without this, a developer's own shell (or
      the developer's own MTGO share and its own ``config.toml``) could
      leak into an Arena-only fixture db and corrupt the hard-coded match
      counts in ``test_projector.py``/``test_api.py``. The same module's
      ``resolve_log_dir()`` reads ``MTGO_LOG_DIR`` then ``[mtgo] dir`` for
      the same reason — a watcher test could otherwise pick up a
      developer's real MTGO share.
    - ``api/guard.py`` lets a request carrying the dashboard's header through
      to the four metered ``.../narrative`` handlers, which resolve a Claude
      credential from the environment or that same file (``llm/config.py``).
      A real credential on the developer's machine must never turn a test's
      "no credential configured" path into a configured one — a configured
      one is a paid call.

    Pointing ``XDG_CONFIG_HOME`` at an empty, never-created temp directory
    (``llm/config.py::config_path()`` honours it) makes every one of those
    lookups miss cleanly, the same way a fresh install would. A test body
    that explicitly wants one of these still wins: it sets its own value
    with its own ``monkeypatch`` call after this fixture's already ran
    (fixture setup happens before the test body; both share one
    ``monkeypatch`` per test).
    """
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


@pytest.fixture
def make_client():
    """A ``TestClient`` that looks like the dashboard to ``api/guard.py``: a
    loopback ``Host`` (``TestClient``'s own default is ``testserver``, which
    the guard refuses) and the client header on every request. Tests of the
    guard itself build bare clients instead, to control exactly which
    headers are present."""
    from fastapi.testclient import TestClient

    from sensei_top.api.guard import CLIENT_HEADER

    def _make(app, **kwargs):
        headers = {CLIENT_HEADER: "dashboard", **kwargs.pop("headers", {})}
        return TestClient(app, base_url="http://127.0.0.1:8000", headers=headers, **kwargs)

    return _make


@pytest.fixture
def steam_libraries(tmp_path: Path) -> tuple[Path, Path]:
    """Fake a Steam install whose game library sits on another drive.

    Yields ``(steam_data_dir, other_library)``. The vdf lists both, which is
    what Steam itself writes: the default root is always entry 0.
    """
    default_steam = tmp_path / "default-steam"
    other_library = tmp_path / "other-drive/SteamLibrary"
    vdf_dir = default_steam / "steamapps"
    vdf_dir.mkdir(parents=True)
    (vdf_dir / "libraryfolders.vdf").write_text(
        "\n".join(
            [
                '"libraryfolders"',
                "{",
                '\t"0"',
                "\t{",
                f'\t\t"path"\t\t"{default_steam}"',
                "\t}",
                '\t"1"',
                "\t{",
                f'\t\t"path"\t\t"{other_library}"',
                "\t}",
                "}",
                "",
            ]
        )
    )
    return default_steam, other_library
