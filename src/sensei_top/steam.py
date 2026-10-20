"""Finding a Steam installation's files on this machine.

Filesystem discovery only — nothing here knows what Arena's data *means*. Two
things need it: the reader looking for ``Player.log``, and the card importer
looking for Arena's own card database. Both live inside the game's install,
and the game can be installed in any library folder the user has added (a
second drive, an external mount), not just the one Steam itself sits in. Steam
records those in ``libraryfolders.vdf``, so that file — rather than a fixed
path — is what this module follows.
"""

from __future__ import annotations

import re
from pathlib import Path

MTGA_APP_ID = "2141910"

# Test seam: ``None`` means "compute from the home directory at call time"
# (``steam_data_dirs()``). A test that wants a specific set of data directories
# assigns a tuple here.
STEAM_DATA_DIRS: tuple[Path, ...] | None = None

_VDF_PATH_RE = re.compile(r'"path"\s*"([^"]+)"')

# Steam is closed source; these are the two places other launchers read the
# file from. Heroic reads the first, Lutris the second (Lutris's
# ``util/steam/config.py:216``). Both are tried, and the dedupe drops repeats.
_VDF_RELATIVE = ("steamapps/libraryfolders.vdf", "config/libraryfolders.vdf")


def steam_data_dirs() -> tuple[Path, ...]:
    """Steam's own data directories, computed from ``Path.home()`` now.

    ``~/.steam/root`` and ``~/.steam/steam`` are usually symlinks to the native
    folder; the Flatpak and Snap builds keep their own copy under the app's
    sandbox home (the older Flatpak layout used ``data/Steam``). Sources
    (plan 31, S0): Flatpak ``steam_wrapper.py:24,330-345``
    (flathub/com.valvesoftware.Steam); the older ``data/Steam`` from Lutris's
    ``util/steam/config.py:22-28``; Snap ``snapcraft.yaml:551``
    (canonical/steam-snap), where ``HOME`` is ``$SNAP_USER_COMMON``.

    The order keeps the two spellings that were searched before this list grew
    first. The deduplication keeps the first spelling, and the watcher keys
    ``ingest_state`` by the log's path string: a new spelling of an existing
    install's log would re-read it from offset 0.
    """
    home = Path.home()
    flatpak = home / ".var/app/com.valvesoftware.Steam"
    return (
        home / ".steam/steam",
        home / ".local/share/Steam",
        home / ".steam/root",
        flatpak / ".local/share/Steam",
        home / "snap/steam/common/.local/share/Steam",
        flatpak / "data/Steam",
    )


def library_roots() -> list[Path]:
    """Every Steam library folder this user has registered, plus the defaults.

    Best-effort: a missing or unreadable ``libraryfolders.vdf`` simply yields
    the default data directories, so a plain single-library install still works.
    """
    data_dirs = STEAM_DATA_DIRS if STEAM_DATA_DIRS is not None else steam_data_dirs()
    roots = list(data_dirs)
    for data_dir in data_dirs:
        for relative in _VDF_RELATIVE:
            try:
                text = (data_dir / relative).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # Missing, unreadable, or not text at all. Discovery is
                # best-effort: a mangled file means no extra libraries, never
                # a failure to start.
                continue
            roots.extend(Path(match) for match in _VDF_PATH_RE.findall(text))
    # Deduplicate by real path while keeping the first spelling: the same root
    # is listed as a default and inside the vdf, and ~/.steam/* are symlinks.
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            key = root.resolve()
        except (OSError, RuntimeError):
            key = root
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique
