"""The ``[arena]`` table: where Arena's log is, when the user chose it, and
which day/month order its header dates use (plan 6, D11).

Each answer is a fallback, not a rule. ``--file`` and ``$MTGA_LOG`` outrank
``[arena] log``, and autodetection comes after it (``resolve_log`` below
applies that order); ``--locale`` outranks ``[arena] date_order``, and
``auto`` comes after it (``cli.py`` applies that one). This module only reads
the table, written by ``sensei-top config --set-arena-log`` and
``--set-date-order``.

Fail-soft like ``mtgo/config.py``: no file, no table and no key all read as
``None``, silently, since an unset value is the normal state. A file that
cannot be parsed, or a value that is present but unusable, warns and reads as
``None`` too, never an exception. The watcher asks for the log once a minute
while it has none, so each bad value warns once per process, not once a
minute.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Callable
from pathlib import Path

from sensei_top.llm.config import config_path
from sensei_top.reader.dates import AUTO
from sensei_top.reader.ingest import default_log_path
from sensei_top.reader.segmenter import DATE_ORDERS

log = logging.getLogger(__name__)

# Every value ``[arena] date_order`` may hold, and ``--set-date-order`` accepts.
DATE_ORDER_CHOICES = (AUTO, *DATE_ORDERS)

_warned: set[str] = set()


def _warn_once(message: str, *args: object) -> None:
    text = message % args
    if text not in _warned:
        _warned.add(text)
        log.warning(text)


def _table() -> dict | None:
    path = config_path()
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _warn_once("could not read %s: %s", path, exc)
        return None
    arena = data.get("arena")
    return arena if isinstance(arena, dict) else None


def load_log() -> Path | None:
    """``[arena] log``, or ``None`` when unset or unusable. Whether the file
    exists is the caller's question."""
    arena = _table()
    if arena is None or arena.get("log") is None:
        return None
    value = arena["log"]
    if not isinstance(value, str) or not value:
        _warn_once("%s's [arena] log is not a usable path: %r", config_path(), value)
        return None
    return Path(value).expanduser()


def load_date_order() -> str | None:
    """``[arena] date_order`` (``auto``, ``mdy`` or ``dmy``), or ``None``
    when unset or unusable."""
    arena = _table()
    if arena is None or arena.get("date_order") is None:
        return None
    value = arena["date_order"]
    if value not in DATE_ORDER_CHOICES:
        _warn_once(
            "%s's [arena] date_order is not one of %s: %r",
            config_path(),
            ", ".join(DATE_ORDER_CHOICES),
            value,
        )
        return None
    return value


def resolve_log(
    autodetect: Callable[[], Path | None] | None = None,
) -> tuple[Path | None, str]:
    """Where Arena's log is right now, and which source supplied it:
    ``"environment"``, ``"config"``, ``"autodetect"`` or ``"none"``.

    The one place that order lives (``live.resolve_arena_log`` wraps it, and
    ``doctor`` and ``cards.arena_card_database_path`` ask it too). First match
    that exists wins: ``$MTGA_LOG``, then ``[arena] log`` (D11), then the
    autodetected locations. A value that names a missing file is passed over
    silently, as ``$MTGA_LOG``'s always was: the watcher asks again every
    minute while it has no log. ``--file`` outranks all three, but that is
    the caller's to apply. ``autodetect`` is a parameter so ``live`` can hand
    in its own binding of ``default_log_path``, which its tests replace.
    Lives here, not in ``reader/``, because the config file is not the
    reader's business; ``reader.ingest`` does not import this module, so
    there is no cycle."""
    env = os.environ.get("MTGA_LOG")
    if env and Path(env).exists():
        return Path(env), "environment"
    configured = load_log()
    if configured is not None and configured.exists():
        return configured, "config"
    detected = (autodetect or default_log_path)()
    if detected is not None:
        return detected, "autodetect"
    return None, "none"
