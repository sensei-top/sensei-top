"""Finding Wine prefixes on this machine.

Filesystem discovery only, like ``steam.py`` beside it. This module knows where
Linux launchers keep their prefixes (Lutris, Heroic, Bottles, a plain Wine
prefix) and nothing else: not what is inside one, and nothing about Arena.
A folder counts as a prefix only if it holds ``drive_c/``. Every root is
computed from the home directory and the XDG variables at call time, and an
unreadable or odd config file yields nothing from that file, never an error.
See docs/architecture.md, "Finding the clients' files".

YAML is read with a regex for the one key wanted, as ``steam.py`` reads the
vdf, so no parser dependency is needed.

Where each launcher keeps its files was read from the launchers' own source on
2026-10-19; each function below names the file and key it reads.
A value that is empty or not an absolute path (after ``~``) is ignored: a
relative path would resolve against the working directory, which is a guess.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# Matches any ``prefix:`` line, not only the one under ``game:``. That is safe:
# a stray match is only a candidate, and the ``drive_c`` check in
# ``wine_prefixes()`` drops anything that is not a prefix, and every prefix a
# launcher names is a candidate, whatever the game.
_LUTRIS_PREFIX_RE = re.compile(r"^[ \t]*prefix:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_BOTTLES_CUSTOM_RE = re.compile(r"^custom_bottles_path:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_BOTTLE_PLACEHOLDER_RE = re.compile(r"^Path:[ \t]*(.+?)[ \t]*$", re.MULTILINE)


def _xdg(name: str, fallback: str) -> Path:
    value = os.environ.get(name)
    # The XDG spec: a relative value is invalid and treated as unset.
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / fallback


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _path(value: str) -> Path | None:
    """The absolute path a config value names, or None.

    Empty values and ones that stay relative after ``~`` (``relative/dir``, an
    unexpanded ``$GAMEDIR``) are refused rather than resolved against wherever
    the process happens to be running.
    """
    text = _unquote(value)
    if not text:
        return None
    path = Path(os.path.expanduser(text))
    return path if path.is_absolute() else None


def _paths(values: list[str]) -> list[Path]:
    return [p for p in map(_path, values) if p is not None]


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_json(path: Path) -> dict:
    text = _read(path)
    if text is None:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _children(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_dir())
    except OSError:
        return []


def _files(folder: Path, pattern: str) -> list[Path]:
    try:
        return sorted(folder.glob(pattern))
    except OSError:
        return []


def _lutris() -> list[Path]:
    """Prefixes Lutris names.

    Reads ``game:`` -> ``prefix:`` in ``lutris/games/*.yml`` under both the
    config and the data home (``lutris/lutris@master``, ``settings.py:22-26,34``,
    ``config.py:21-30,182,220``, ``runners/wine.py:708,713``), plus the default
    install folders ``~/Games/<slug>`` and ``~/Games/<service>/<slug>``
    (``sysoptions.py:108-112``, ``installer/interpreter.py:123-128``,
    ``installer/commands.py:431``). The Flatpak ``net.lutris.Lutris`` paths are
    inferred from the XDG mapping, not read from its manifest.
    """
    home = Path.home()
    config_data = [
        (_xdg("XDG_CONFIG_HOME", ".config"), _xdg("XDG_DATA_HOME", ".local/share")),
        (
            home / ".var/app/net.lutris.Lutris/config",
            home / ".var/app/net.lutris.Lutris/data",
        ),
    ]
    found: list[Path] = []
    for config, data in config_data:
        # Lutris uses the config folder if it exists, else the data one, and
        # never migrates; read both.
        for base in (config, data):
            for yml in _files(base / "lutris/games", "*.yml"):
                text = _read(yml)
                if text is not None:
                    found.extend(_paths(_LUTRIS_PREFIX_RE.findall(text)))
    # Lutris's default install folder: <slug> or <service>/<slug>.
    for first in _children(home / "Games"):
        found.append(first)
        found.extend(_children(first))
    return found


def _heroic() -> list[Path]:
    """Prefixes Heroic names.

    Reads ``winePrefix`` in ``heroic/GamesConfig/<appName>.json``, then
    ``defaultSettings`` in ``heroic/config.json``: ``winePrefix``, and the
    folders ``defaultWinePrefixDir`` and ``defaultWinePrefix``
    (``HeroicGamesLauncher@main``, ``src/backend/constants/paths.ts:8,23,29``,
    ``game_config.ts:36,290,308-309``, ``config.ts:344-356,404-407``). Also the
    default folders ``~/Games/Heroic/Prefixes`` and ``.../Prefixes/default``
    (``paths.ts:32-37,39``, ``config.ts:305-307``). The Flatpak
    ``com.heroicgameslauncher.hgl`` config path is inferred from the XDG
    mapping.
    """
    home = Path.home()
    config_homes = [
        _xdg("XDG_CONFIG_HOME", ".config") / "heroic",
        home / ".var/app/com.heroicgameslauncher.hgl/config/heroic",
    ]
    found: list[Path] = []
    folders_of_prefixes = [
        home / "Games/Heroic/Prefixes",
        home / "Games/Heroic/Prefixes/default",
    ]
    for heroic in config_homes:
        for js in _files(heroic / "GamesConfig", "*.json"):
            for entry in _read_json(js).values():
                prefix = entry.get("winePrefix") if isinstance(entry, dict) else None
                if isinstance(prefix, str):
                    found.extend(_paths([prefix]))
    for heroic in config_homes:
        settings = _read_json(heroic / "config.json").get("defaultSettings")
        if not isinstance(settings, dict):
            continue
        prefix = settings.get("winePrefix")
        if isinstance(prefix, str):
            found.extend(_paths([prefix]))
        for key in ("defaultWinePrefixDir", "defaultWinePrefix"):
            folder = settings.get(key)
            if isinstance(folder, str):
                folders_of_prefixes.extend(_paths([folder]))
    for folder in folders_of_prefixes:
        found.extend(_children(folder))
    return found


def _bottles() -> list[Path]:
    """Prefixes Bottles keeps: each bottle folder is a prefix.

    Reads ``$XDG_DATA_HOME/bottles/bottles/<name>/`` (``bottlesdevs/Bottles@main``,
    ``backend/globals.py:62-79``; ``winecommand.py:844``), ``custom_bottles_path``
    in ``bottles/data.yml`` (``managers/data.py:30,49``, ``manager.py:183-196``)
    and ``Path:`` in a bottle's ``placeholder.yml`` (``manager.py:1437-1447,
    1991-1996``). The Flatpak ``com.usebottles.bottles`` data path is inferred
    from the XDG mapping.
    """
    home = Path.home()
    data_homes = [
        _xdg("XDG_DATA_HOME", ".local/share") / "bottles",
        home / ".var/app/com.usebottles.bottles/data/bottles",
    ]
    bottle_folders = [d / "bottles" for d in data_homes]
    for data in data_homes:
        text = _read(data / "data.yml")
        match = _BOTTLES_CUSTOM_RE.search(text) if text else None
        if match:
            bottle_folders.extend(_paths([match.group(1)]))
    found: list[Path] = []
    for folder in bottle_folders:
        for bottle in _children(folder):
            found.append(bottle)
            # A bottle created elsewhere leaves a placeholder naming the real one.
            text = _read(bottle / "placeholder.yml")
            match = _BOTTLE_PLACEHOLDER_RE.search(text) if text else None
            if match:
                found.extend(_paths([match.group(1)]))
    return found


def wine_prefixes() -> list[Path]:
    """Every Wine prefix on this machine, in a fixed order.

    ``$WINEPREFIX``, Lutris, Heroic, Bottles, then ``~/.wine``. Only folders
    holding ``drive_c/`` are returned, each once (by real path, first
    spelling kept).
    """
    candidates: list[Path] = []
    env = os.environ.get("WINEPREFIX")
    candidates.extend(_paths([env]) if env else [])
    candidates.extend(_lutris())
    candidates.extend(_heroic())
    candidates.extend(_bottles())
    candidates.append(Path.home() / ".wine")

    seen: set[Path] = set()
    prefixes: list[Path] = []
    for candidate in candidates:
        try:
            if not (candidate / "drive_c").is_dir():
                continue
            key = candidate.resolve()
        except (OSError, RuntimeError):
            continue
        if key not in seen:
            seen.add(key)
            prefixes.append(candidate)
    return prefixes
