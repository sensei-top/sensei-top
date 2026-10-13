"""Where MTGO is writing game logs right now, and whether to say so.

MTGO moves its data folder under ``%LOCALAPPDATA%\\Apps\\2.0\\Data`` whenever
it updates, so a configured ``[mtgo] dir`` goes stale. This module finds the
folder and builds a *suggestion*; it never reads the folder's contents as
data and nothing uses the result until the user runs ``config
--set-mtgo-dir`` or points ``MTGO_LOG_DIR`` at it
(``mtgo/config.py``'s "never guessed" rule stands).
Windows only: elsewhere discovery returns ``None``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PATTERN = "Match_GameLog_*.dat"

_COMMAND = '  sensei-top config --set-mtgo-dir "{folder}"'
_MESSAGE_UNCONFIGURED = (
    "MTGO writes its game logs to a folder that isn't configured yet. To read them, run:\n"
    + _COMMAND
)
_MESSAGE_ENV = (
    "MTGO's newest game logs are in a different folder from {configured}: "
    "it moves the folder when it updates. To read them, point MTGO_LOG_DIR at:\n"
    "  {folder}"
)
_ENV_SOURCE = "$MTGO_LOG_DIR"
_MESSAGE_BEHIND = (
    "MTGO's newest game logs are in a different folder from {configured}: "
    "it moves the folder when it updates. To read them, run:\n" + _COMMAND
)


def _created(path: Path) -> float:
    # Python 3.12 added st_birthtime on Windows and deprecated creation time
    # via st_ctime there; Linux has no st_birthtime, so the fallback keeps
    # this callable (and testable) there.
    stat = path.stat()
    return getattr(stat, "st_birthtime", stat.st_ctime)


def newest_log_mtime(folder: Path) -> float | None:
    """Latest mtime of a game log directly in ``folder``; ``None`` when the
    folder is missing or holds none."""
    try:
        return max((p.stat().st_mtime for p in folder.glob(_PATTERN)), default=None)
    except OSError:
        return None


def discover_log_folder() -> Path | None:
    """The newest-by-creation-time folder under ``%LOCALAPPDATA%\\Apps\\2.0\\Data``
    holding a ``Match_GameLog_*.dat``; ``None`` off Windows or when none does."""
    if sys.platform != "win32":
        return None
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    root = Path(local) / "Apps" / "2.0" / "Data"
    candidates: list[tuple[float, Path]] = []
    try:
        for dirpath, _dirnames, filenames in os.walk(root):
            if any(Path(name).match(_PATTERN) for name in filenames):
                folder = Path(dirpath)
                try:
                    candidates.append((_created(folder), folder))
                except OSError:
                    continue
    except OSError:
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


def _same_folder(a: Path, b: Path) -> bool:
    ra, rb = str(a.resolve()), str(b.resolve())
    if sys.platform == "win32":
        return ra.casefold() == rb.casefold()
    return ra == rb


def suggestion(
    configured: Path | None, discovered: Path | None, source: str | None = None
) -> str | None:
    """The two-line suggestion, or ``None`` when there is nothing to suggest:
    no discovered folder, the same folder, or a configured folder that is not
    behind the discovered one. ``source`` is ``resolve_log_dir()``'s: when the
    folder came from ``$MTGO_LOG_DIR`` the variable outranks the config file,
    so ``config --set-mtgo-dir`` would change nothing and the message says to
    point the variable instead."""
    if discovered is None:
        return None
    if configured is None:
        return _MESSAGE_UNCONFIGURED.format(folder=discovered)
    if _same_folder(configured, discovered):
        return None
    found = newest_log_mtime(discovered)
    if found is None:
        return None
    have = newest_log_mtime(configured)
    if have is None or found > have:
        if source == _ENV_SOURCE:
            return _MESSAGE_ENV.format(configured=configured, folder=discovered)
        return _MESSAGE_BEHIND.format(configured=configured, folder=discovered)
    return None
