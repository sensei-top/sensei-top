"""Three questions about MTGO, all answered from the same ``[mtgo]`` table:
which seat in the log is ours, where the log files even are, and where the
user's exported deck files are.

MTGO's log has no auth event (unlike Arena's ``authenticateResponse``), so
there is no way to learn "which player is us" from the log itself. Nor does
this module search for a directory the way ``steam.py`` finds Arena's:
where MTGO's ``Match_GameLog_*.dat`` files end up depends on how and where
MTGO itself is run, so this module never guesses one — the user must say
so, for all three questions, and there is no default.

Resolution order, first match wins:

Handle —

1. ``MTGO_HANDLE`` in the environment.
2. ``[mtgo] handle`` in ``llm.config.config_path()`` (the same
   ``~/.config/sensei-top/config.toml`` the Claude credential lives in —
   one config file, one XDG path, several tables).

Directory —

1. ``MTGO_LOG_DIR`` in the environment.
2. ``[mtgo] dir`` in that same config file.
3. Nothing — callers get ``None`` and stay Arena-only.

Deck folder (``resolve_deck_dir``) — the same shape, for the user's exported
``.dek`` files: ``MTGO_DECK_DIR``, then ``[mtgo] deck_dir``, then ``None``.

Mirrors ``llm/config.py``'s fail-soft contract: a config file that exists
but can't be parsed logs a warning and hands back ``None`` rather than
raising, for all three. Past that, the handle and the two directories don't
warn alike. The directories are silent on every kind of absence — no env
var, no file, no ``[mtgo]`` table, no ``dir`` or ``deck_dir`` key — and warn
only on that unreadable-file case or a value that's already present but
unusable (wrong type, or empty), since plenty of installs are Arena-only and
"not configured" is their steady state, not a misconfiguration. The handle
is silent only when there's no config file at all; a file that exists but
has no ``[mtgo]`` table, or a table with no ``handle``, warns. Either way,
``None`` never means a guessed value (AGENTS.md non-negotiable #4 — never
synthesize data, and a guessed self/opponent split, or a scan of directories
the user never pointed at, would be exactly that).
"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

from sensei_top.llm.config import config_path

log = logging.getLogger(__name__)


def load_handle() -> str | None:
    """``None`` means "not configured" — the caller must handle it, never
    raise past it."""
    env_handle = os.environ.get("MTGO_HANDLE")
    if env_handle:
        return env_handle
    return _load_file_handle()


def _load_file_handle() -> str | None:
    data = _read_config()
    if data is None:
        return None
    mtgo = data.get("mtgo")
    if not isinstance(mtgo, dict):
        log.warning("%s has no [mtgo] table", config_path())
        return None
    handle = mtgo.get("handle")
    if not isinstance(handle, str) or not handle:
        log.warning("%s's [mtgo] table has no handle", config_path())
        return None
    return handle


def resolve_log_dir() -> tuple[Path, str] | None:
    """Where MTGO writes ``Match_GameLog_*.dat``, and which source supplied
    it — ``"$MTGO_LOG_DIR"`` or ``"config.toml [mtgo] dir"``, for callers
    that print provenance alongside the path (``cli.py``'s ``mtgo-status``
    and ``config``). ``None`` means "not configured", silently: unlike a
    missing handle, there is nothing to warn about, since plenty of installs
    are Arena-only and this is their steady state, not a misconfiguration.
    """
    env_dir = os.environ.get("MTGO_LOG_DIR")
    if env_dir:
        return Path(env_dir).expanduser(), "$MTGO_LOG_DIR"

    data = _read_config()
    if data is None:
        return None
    mtgo = data.get("mtgo")
    if not isinstance(mtgo, dict):
        return None
    directory = mtgo.get("dir")
    if directory is None:
        return None
    if not isinstance(directory, str) or not directory:
        log.warning("%s's [mtgo] dir is not a usable path: %r", config_path(), directory)
        return None
    return Path(directory).expanduser(), "config.toml [mtgo] dir"


def resolve_deck_dir() -> tuple[Path, str] | None:
    """Where the user's MTGO deck files (``*.dek``) are, and which source
    supplied it — ``"$MTGO_DECK_DIR"`` or ``"config.toml [mtgo] deck_dir"``.
    ``--deck-dir`` (``ingest-mtgo``) and ``--mtgo-deck-dir`` (the watch
    commands) outrank both, but that is the CLI's to apply.

    Same contract as ``resolve_log_dir``: ``None`` means "not configured",
    silently, never a guessed path; a ``deck_dir`` that is present but not a
    usable string warns, since that is a misconfiguration rather than an
    absence.
    """
    env_dir = os.environ.get("MTGO_DECK_DIR")
    if env_dir:
        return Path(env_dir).expanduser(), "$MTGO_DECK_DIR"

    data = _read_config()
    if data is None:
        return None
    mtgo = data.get("mtgo")
    if not isinstance(mtgo, dict):
        return None
    directory = mtgo.get("deck_dir")
    if directory is None:
        return None
    if not isinstance(directory, str) or not directory:
        log.warning("%s's [mtgo] deck_dir is not a usable path: %r", config_path(), directory)
        return None
    return Path(directory).expanduser(), "config.toml [mtgo] deck_dir"


def _read_config() -> dict | None:
    """The shared tolerant-read step behind every resolver: ``None`` silently
    when there's no file to read, ``None`` with a warning when the file
    exists but can't be parsed. None of them goes further into a bad return
    — a warning already happened here, and warning twice about the same
    broken file would just be noise."""
    path = config_path()
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return None
