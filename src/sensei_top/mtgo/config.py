"""Two questions about MTGO, both answered from the same ``[mtgo]`` table:
which seat in the log is ours, and where the log files even are.

MTGO's log has no auth event (unlike Arena's ``authenticateResponse``), so
there is no way to learn "which player is us" from the log itself. Nor does
this module search for a directory the way ``steam.py`` finds Arena's:
where MTGO's ``Match_GameLog_*.dat`` files end up depends on how and where
MTGO itself is run, so this module never guesses one — the user must say
so, for both questions, and there is no default.

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

Mirrors ``llm/config.py``'s fail-soft contract: a config file that exists
but can't be parsed logs a warning and hands back ``None`` rather than
raising, for both questions. Past that, the two don't warn alike. The
directory is silent on every kind of absence — no env var, no file, no
``[mtgo]`` table, no ``dir`` key — and warns only on that unreadable-file
case or a ``dir`` value that's already present but unusable (wrong type, or
empty), since plenty of installs are Arena-only and "not configured" is
their steady state, not a misconfiguration. The handle is silent only when
there's no config file at all; a file that exists but has no ``[mtgo]``
table, or a table with no ``handle``, warns. Either way, ``None`` never
means a guessed value (AGENTS.md non-negotiable #4 — never synthesize data,
and a guessed self/opponent split, or a scan of directories the user never
pointed at, would be exactly that).
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


def _read_config() -> dict | None:
    """The shared tolerant-read step behind both resolvers: ``None`` silently
    when there's no file to read, ``None`` with a warning when the file
    exists but can't be parsed. Neither resolver goes further into a bad
    return — a warning already happened here, and warning twice about the
    same broken file would just be noise."""
    path = config_path()
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return None
