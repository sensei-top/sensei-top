"""Finding Arena's install directory from the first line of its own log.

Filesystem discovery only, like ``steam.py`` beside it: this module reads one
line of a file and resolves a path. It knows nothing about ``raw_events`` or
any other line of the log, which is why it lives outside ``reader/``.

Unity writes the folder its managed assemblies load from as the log's very
first line, ``Mono path[0] = '<install>/MTGA_Data/Managed'`` (verified on a
real Steam/Proton log, 2026-09-27). The client is the one that knows where it
was installed, so this is one method for Wizards' installer, Steam and Epic
alike, where the Steam library glob in ``cards.py`` covers Steam alone.

Two traps:

1. **Under Proton or any Wine prefix the path is a Wine one** (``C:/...`` or
   ``Z:/...``), meaningless to the host as written. The prefix's own
   ``dosdevices/`` maps each drive letter to a host folder (``c:`` to
   ``../drive_c``, ``z:`` to ``/``), and the prefix is the nearest folder
   above the log that holds a ``dosdevices/``: the log always sits inside
   it, at ``<prefix>/drive_c/users/<user>/AppData/LocalLow/...``. A Wine
   path whose prefix or drive cannot be found resolves to ``None``, never to
   a guess.
2. **The first line may end in a bare CR.** Arena's log mixes CRLF with bare
   CR (``docs/arena-log.md``), so the line is cut at the first of either, not
   at ``\\n`` alone, which would run on into line 2.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sys
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)

# Line 1 is a few hundred bytes on a real log. The cap keeps a file that is
# not Arena's log at all (``MTGA_LOG`` pointed at the wrong thing) from being
# read whole looking for a line break.
_FIRST_LINE_BYTES = 4096

# Greedy to the last quote: a folder name may itself hold an apostrophe.
_MONO_PATH_RE = re.compile(r"^Mono path\[0\]\s*=\s*'(?P<path>.+)'\s*$")

_DRIVE_RE = re.compile(r"^(?P<letter>[A-Za-z]):(?:/(?P<rest>.*))?$")

# The two folders below the install that the Mono path names, compared
# case-insensitively: Windows paths are.
_MANAGED_SUFFIX = ("mtga_data", "managed")


def _first_line(log_path: Path) -> str | None:
    try:
        with log_path.open("rb") as fh:
            head = fh.read(_FIRST_LINE_BYTES)
    except OSError:
        return None
    line = re.split(rb"[\r\n]", head, maxsplit=1)[0]
    return line.decode("utf-8", errors="replace").lstrip("\ufeff")


def _wine_prefix(log_path: Path) -> Path | None:
    for folder in log_path.absolute().parents:
        if (folder / "dosdevices").is_dir():
            return folder
    return None


def _host_path(text: str, log_path: Path) -> Path | None:
    """``text``, a path as the client wrote it, as a path on this machine."""
    drive = _DRIVE_RE.match(text)
    if drive is None:
        return Path(text)
    letter, rest = drive["letter"], drive["rest"] or ""
    if sys.platform == "win32":
        return Path(f"{letter}:/{rest}")
    prefix = _wine_prefix(log_path)
    if prefix is None:
        log.debug("%s names a Wine path but sits in no Wine prefix", log_path.name)
        return None
    device = prefix / "dosdevices" / f"{letter.lower()}:"
    if not device.exists():
        return None
    return device / rest


def install_dir(log_path: str | Path | None) -> Path | None:
    """The Arena install that wrote ``log_path``, or None.

    None when there is no log, when its first line is not the Mono path line
    (a log Arena has just truncated on launch has no line 1 yet), when that
    line does not end in ``MTGA_Data/Managed``, when a Wine path cannot be
    mapped to the host (module docstring), or when the folder it names is not
    there any more.
    """
    if log_path is None:
        return None
    log_path = Path(log_path)
    line = _first_line(log_path)
    if line is None:
        return None
    mono = _MONO_PATH_RE.match(line)
    if mono is None:
        return None
    managed = PurePosixPath(mono["path"].replace("\\", "/").rstrip("/"))
    if tuple(part.lower() for part in managed.parts[-2:]) != _MANAGED_SUFFIX:
        return None
    install = _host_path(str(managed.parent.parent), log_path)
    if install is None:
        return None
    # Through dosdevices' symlinks to the host folder itself, so a caller that
    # prints the path shows the one the user knows. A symlink loop or a dead
    # mount keeps the path as mapped.
    with contextlib.suppress(OSError, RuntimeError):
        install = install.resolve()
    return install if install.is_dir() else None
