"""The log file: ``<db dir>/logs/sensei-top.log`` (release plan 3, D10).

Every launch appends to one file beside the database it was given, so a
problem a user reports arrives with the lines that led up to it, and a scratch
``--db`` keeps its lines out of the real install's file. ``cli.main`` calls
``install`` once the database path is known; nothing else installs a handler.

- **Levels.** The file takes WARNING and up, DEBUG with ``--verbose``; the
  console keeps the levels it had before the file existed, ERROR, WARNING with
  ``--verbose``. Both also take the generate call's INFO lines, from
  ``sensei_top.llm`` (trap 8). Each handler filters on its own, and the root
  logger's level is the lower of the two, so neither starves the other.
- **Lines.** ``2026-10-06T14:03:22.418Z 3f9a1c2e WARNING sensei_top.live: …``:
  UTC, so a file compares across machines and across a DST change without
  arithmetic; then the launch's session id, which tells apart ``serve`` and a
  hand-run ``ingest-mtgo`` appending to the same file. The id is a filter on
  the file handler, so every record carries it, uvicorn's and every other
  library's included.
- **The header.** The first line each launch writes names the version, the
  subcommand, the platform and the database, at INFO through the handler
  directly, so it is written whatever the handler's level.
- **Size.** Five backups of 2 MB each, rotated.

Traps:

1. ``config --set-key KEY`` carries a credential on argv. The header names
   the subcommand only, never ``sys.argv``.
2. The home directory is written as ``~``, on the formatted line rather than
   on the message, so a traceback's paths are covered too. On Windows the
   match ignores case and takes either separator, or a doubled backslash,
   which is how ``repr`` writes one and so how every ``OSError`` names a path.
   Elsewhere it is exact. Either way a longer name that merely starts with the
   home's last part (``/home/al`` inside ``/home/alice``) is left alone.
   After any other character, a full stop ending a sentence or a ``-``, the
   home is still written as ``~``. A home that is a filesystem root is not
   substituted at all.
3. On Windows a file another process holds open cannot be renamed, and
   ``serve`` beside a hand-run command is two processes appending to one file.
   ``RotatingFileHandler`` shifts the backups before it renames the current
   file, so each refused attempt (one per record while the file is over size)
   would push another backup off the end, and ``handleError`` would print a
   traceback for each. ``_SharedRotatingFileHandler`` renames the current file
   first; refused, there or at a backup still held open by the launch that
   was writing it, it puts the current file back, reopens it and keeps
   appending, and a later record retries.
4. Under pytest the root logger already holds pytest's capture handlers, and
   ``basicConfig``, which this replaced, then added no console handler.
   ``install`` keeps that rule, so a test's ``capsys`` sees what it saw
   before. Repeated calls (one per ``main()`` in a test) replace what the
   previous call installed rather than stacking it.
5. ``serve --watch``'s watcher child writes no file: it hands its records to
   ``serve`` through a queue (``live.WatcherProcess``), and they reach this
   process's file handler, and its session id, there.
6. UTF-8 with ``backslashreplace``: Windows would otherwise open the file in
   the ANSI code page, which card names fall outside, and a path holding an
   undecodable byte (a surrogate escape on Linux) would fail the write.
7. Logging never stops a command: a file that cannot be opened is one
   console warning, and the command runs on without it.
8. A handler's level cannot say "WARNING and up, plus one logger's INFO", and
   the cost of each generate call is the one INFO line a user is promised
   (non-negotiable 5, "never silent"). So the console sits at INFO, and the
   file at INFO, or at DEBUG under ``--verbose``, where no floor is needed; a
   ``_Level`` filter holds the floor each would otherwise have had. The file's
   header is written before that filter goes on, or it would be dropped.
"""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import re
import secrets
import sys
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import override

LOG_DIR = "logs"
LOG_NAME = "sensei-top.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5

LINE_FORMAT = "%(asctime)s.%(msecs)03dZ %(session)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
HEADER = "started sensei-top {version} ({command}) on {platform}, Python {python}, database {db}"
CONSOLE_FORMAT = "%(levelname)s %(message)s"

# What the last ``install`` added to the root logger, so the next one can
# take it back off (trap 4).
_installed: list[logging.Handler] = []


def log_path(db_path: Path) -> Path:
    """The log file beside ``db_path``."""
    return db_path.parent / LOG_DIR / LOG_NAME


class _Session(logging.Filter):
    """Puts the launch's id on every record the file handler takes."""

    def __init__(self, session: str) -> None:
        super().__init__()
        self.session = session

    def filter(self, record: logging.LogRecord) -> bool:
        record.session = self.session
        return True


class _Level(logging.Filter):
    """Holds a handler to ``floor`` and above, and lets through the INFO lines
    of ``sensei_top.llm`` and its submodules.

    The cost of each generate call is the one INFO line a user is promised
    (non-negotiable 5, "never silent"), and a handler's own level cannot
    express "WARNING and up, plus one logger's INFO" (trap 8). The prefix
    rather than ``sensei_top.llm.client`` covers a later module under
    ``llm/`` without a second edit; ``sensei_top.llmx`` is not under it.
    """

    def __init__(self, floor: int) -> None:
        super().__init__()
        self.floor = floor

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= self.floor:
            return True
        return record.levelno >= logging.INFO and (
            record.name == "sensei_top.llm" or record.name.startswith("sensei_top.llm.")
        )


class _FileFormatter(logging.Formatter):
    """The file's line, in UTC, with the home directory written as ``~``."""

    converter = time.gmtime

    def __init__(self, home: re.Pattern[str] | None) -> None:
        super().__init__(LINE_FORMAT, DATE_FORMAT)
        self._home = home

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        return self._home.sub("~", line) if self._home is not None else line


class _SharedRotatingFileHandler(RotatingFileHandler):
    """Renames the current file before shifting the backups (trap 3)."""

    @override
    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        base = self.baseFilename
        moving = f"{base}.rotating"
        try:
            os.replace(base, moving)
            for index in range(self.backupCount - 1, 0, -1):
                older = f"{base}.{index}"
                if os.path.exists(older):
                    os.replace(older, f"{base}.{index + 1}")
            os.replace(moving, f"{base}.1")
        except OSError:
            # Refused: on Windows, another launch holds a file open. A file
            # left aside would be overwritten by the next rotation's first
            # rename, so it goes back to the current name, and appending
            # carries on there.
            if os.path.exists(moving):
                with contextlib.suppress(OSError):
                    os.replace(moving, base)
        self.stream = self._open()


def _home_pattern(home: str, *, windows: bool) -> re.Pattern[str]:
    """``home`` as it may appear in a line, with no letter, digit or
    underscore after it to continue the name (trap 2)."""
    if windows:
        body = r"[\\/]+".join(re.escape(part) for part in re.split(r"[\\/]+", home))
        flags = re.IGNORECASE
    else:
        body, flags = re.escape(home), 0
    return re.compile(body + r"(?!\w)", flags)


def _home() -> re.Pattern[str] | None:
    try:
        home = Path.home()
    except (RuntimeError, KeyError):  # no home directory to name
        return None
    if home == Path(home.anchor):
        return None
    return _home_pattern(str(home), windows=sys.platform == "win32")


def _header(command: str, db: Path) -> logging.LogRecord:
    try:
        version = package_version("sensei-top")
    except PackageNotFoundError:
        version = "unknown"
    message = HEADER.format(
        version=version,
        command=command,
        platform=platform.platform(),
        python=platform.python_version(),
        db=db,
    )
    return logging.LogRecord("sensei_top", logging.INFO, __file__, 0, message, None, None)


def uninstall() -> None:
    """Take off and close what ``install`` put on the root logger. ``install``
    calls it first, and a test calls it after ``main()`` (trap 4)."""
    root = logging.getLogger()
    for handler in _installed:
        root.removeHandler(handler)
        handler.close()
    _installed.clear()


def install(db_path: Path, command: str, *, verbose: bool) -> Path | None:
    """Send this launch's records to the console and to the log file beside
    ``db_path``, and write the file's header line. ``command`` is the
    subcommand's name, never its arguments (trap 1).

    Returns the log file's path, or ``None`` when it could not be opened: then
    one warning is printed and the command runs on without a file.
    """
    uninstall()
    root = logging.getLogger()
    if not root.handlers:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.addFilter(_Level(logging.WARNING if verbose else logging.ERROR))
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        root.addHandler(console)
        _installed.append(console)

    db = db_path.resolve()
    path = log_path(db)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = _SharedRotatingFileHandler(
            path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
            errors="backslashreplace",
        )
    except OSError as exc:
        # Printed, not logged: the console handler shows only ERROR without
        # --verbose, and under pytest there is none.
        print(f"WARNING not writing a log file: {exc}", file=sys.stderr)
        file_handler = None
    else:
        file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        file_handler.setFormatter(_FileFormatter(_home()))
        file_handler.addFilter(_Session(secrets.token_hex(4)))
        root.addHandler(file_handler)
        _installed.append(file_handler)
        file_handler.handle(_header(command, db))
        if not verbose:  # DEBUG passes everything; the header is already written
            file_handler.addFilter(_Level(logging.WARNING))

    if _installed:
        root.setLevel(min(handler.level for handler in _installed))
    return path if file_handler is not None else None
