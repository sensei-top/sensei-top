"""Shared test helpers.

Kept deliberately small: fixtures that only one module needs stay in that
module, per docs/testing.md.
"""

import logging
from pathlib import Path

import pytest

from sensei_top import logs


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch, tmp_path):
    """Every test runs with a clean slate on ambient configuration: no
    ``MTGO_HANDLE``/``MTGO_LOG_DIR``/``MTGO_DECK_DIR``, no Claude/TopDeck.gg
    credential, and no real ``~/.config/sensei-top/config.toml``. Three separate
    things would otherwise leak in:

    - ``projector/matches.py::project()`` calls ``project_mtgo``
      unconditionally on every ``project()`` call, and
      ``mtgo/config.py::load_handle()`` falls back to that same config
      file's ``[mtgo]`` table. Without this, a developer's own shell (or
      the developer's own MTGO share and its own ``config.toml``) could
      leak into an Arena-only fixture db and corrupt the hard-coded match
      counts in ``test_projector.py``/``test_api.py``. The same module's
      ``resolve_log_dir()`` reads ``MTGO_LOG_DIR`` then ``[mtgo] dir`` for
      the same reason — a watcher test could otherwise pick up a
      developer's real MTGO share — and ``resolve_deck_dir()`` reads
      ``MTGO_DECK_DIR`` then ``[mtgo] deck_dir``, likewise a developer's real
      deck folder.
    - ``api/guard.py`` lets a request carrying the dashboard's header through
      to the four metered ``.../narrative`` handlers, which resolve a Claude
      credential from the environment or that same file (``llm/config.py``).
      A real credential on the developer's machine must never turn a test's
      "no credential configured" path into a configured one — a configured
      one is a paid call.
    - ``cards.arena_card_database_path()`` resolves the log through
      ``reader/ingest.py::default_log_path()``, which reads ``MTGA_LOG``
      first, so a developer's exported ``MTGA_LOG`` would otherwise point the
      card-database tests at the real Arena install.

    - ``mtgo/discover.py`` walks ``%LOCALAPPDATA%\\Apps\\2.0`` on Windows, so a
      machine with MTGO installed would otherwise hand the tests its real
      game-log folder; an empty, never-created temp directory makes
      discovery find nothing.

    - ``steam.py`` and ``wine.py`` look under ``HOME``, ``XDG_DATA_HOME`` and
      ``$WINEPREFIX`` for Steam libraries and Wine prefixes, so those point at
      empty, never-created temp folders too.

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
    monkeypatch.delenv("MTGO_DECK_DIR", raising=False)
    monkeypatch.delenv("MTGA_LOG", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    # Child processes (``serve`` in the CLI and live tests) inherit no
    # in-process backend; this keeps them off the real Secret Service too.
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    # Steam and Wine discovery (``steam.py``, ``wine.py``) read roots under the
    # home directory and the XDG data directory at call time; an empty,
    # never-created home means no test sees a developer's real prefix or log.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.delenv("WINEPREFIX", raising=False)


@pytest.fixture(autouse=True)
def memory_keyring():
    """Every test runs against an empty in-memory keyring, never the
    machine's real one (Secret Service, Credential Manager), which may hold a
    real, metered API key. Yields the backing dict so a test can seed it;
    a test that needs "no backend" or "a failing backend" calls
    ``keyring.set_keyring`` itself, and this leaves the
    inert ``fail`` backend behind afterwards: nothing in pytest wants the real
    one back."""
    import keyring
    from keyring.backend import KeyringBackend
    from keyring.backends import fail
    from keyring.errors import PasswordDeleteError

    class _Memory(KeyringBackend):
        priority = 1

        def __init__(self):
            super().__init__()
            self.store: dict[tuple[str, str], str] = {}

        def get_password(self, service, username):
            return self.store.get((service, username))

        def set_password(self, service, username, password):
            self.store[(service, username)] = password

        def delete_password(self, service, username):
            try:
                del self.store[(service, username)]
            except KeyError:
                raise PasswordDeleteError("not set") from None

    backend = _Memory()
    keyring.set_keyring(backend)
    yield backend.store
    keyring.set_keyring(fail.Keyring())


@pytest.fixture(autouse=True)
def _no_leftover_log_handlers():
    """``cli.main()`` puts a file handler (and, outside pytest, a console
    one) on the root logger and sets its level, for the whole process
    (``logs.install``). Every test that calls it would otherwise leave them
    there: a later test's warnings would land in an earlier test's log file,
    which Windows then cannot delete while it is held open. Here rather than
    in each module that calls ``main()``, since several do."""
    level = logging.getLogger().level
    yield
    logs.uninstall()
    logging.getLogger().setLevel(level)


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
