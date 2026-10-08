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

# Steam's own data directory, which is also where libraryfolders.vdf lives.
# Both spellings exist in the wild; the first is usually a symlink to the second.
STEAM_DATA_DIRS: tuple[Path, ...] = (
    Path.home() / ".steam/steam",
    Path.home() / ".local/share/Steam",
)

_VDF_PATH_RE = re.compile(r'"path"\s*"([^"]+)"')


def library_roots() -> list[Path]:
    """Every Steam library folder this user has registered, plus the defaults.

    Best-effort: a missing or unreadable ``libraryfolders.vdf`` simply yields
    the default data directories, so a plain single-library install still works.
    """
    roots = list(STEAM_DATA_DIRS)
    for data_dir in STEAM_DATA_DIRS:
        try:
            text = (data_dir / "steamapps/libraryfolders.vdf").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Missing, unreadable, or not text at all. Discovery is best-effort:
            # a mangled file means no extra libraries, never a failure to start.
            continue
        roots.extend(Path(match) for match in _VDF_PATH_RE.findall(text))
    # Deduplicate while keeping order: the same root is listed both as a default
    # and inside the vdf on a normal install.
    seen: set[Path] = set()
    return [root for root in roots if not (root in seen or seen.add(root))]
