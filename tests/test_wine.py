"""Wine prefix discovery: where Linux launchers keep their prefixes.

Each test builds a fake home laid out as the launcher's own source puts it.
``conftest.py`` already points ``HOME`` and the XDG variables
at empty temp folders (``home``, ``xdg-config``, ``xdg-data`` under
``tmp_path``); these tests build under those.
"""

import json
from pathlib import Path

import pytest

from sensei_top import wine


@pytest.fixture
def home(tmp_path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


def _prefix(path: Path) -> Path:
    (path / "drive_c").mkdir(parents=True)
    return path


# --- plain Wine ---


def test_nothing_installed_is_empty(home):
    """A machine with no Wine at all is the common case and must be a quiet
    empty list."""
    assert wine.wine_prefixes() == []


def test_wine_prefix_environment_variable(home, tmp_path, monkeypatch):
    """A user who runs Wine by hand points ``$WINEPREFIX`` anywhere."""
    prefix = _prefix(tmp_path / "elsewhere/pfx")
    monkeypatch.setenv("WINEPREFIX", str(prefix))
    assert wine.wine_prefixes() == [prefix]


def test_default_wine_folder(home):
    """``~/.wine`` is where Wine puts a prefix nobody named."""
    prefix = _prefix(home / ".wine")
    assert wine.wine_prefixes() == [prefix]


def test_same_prefix_reached_twice_is_listed_once(home, monkeypatch):
    """``$WINEPREFIX`` often names ``~/.wine``; counting it twice would list
    its log twice."""
    prefix = _prefix(home / ".wine")
    monkeypatch.setenv("WINEPREFIX", str(prefix))
    assert wine.wine_prefixes() == [prefix]


def test_folder_without_drive_c_is_not_a_prefix(home, tmp_path):
    """A launcher config can name a folder Wine never initialised; it must not
    be offered as a prefix."""
    (home / ".wine").mkdir()
    games = tmp_path / "xdg-data/lutris/games"
    games.mkdir(parents=True)
    (games / "a.yml").write_text(f"game:\n  prefix: {tmp_path / 'missing'}\n")
    assert wine.wine_prefixes() == []


# --- Lutris ---


def test_lutris_yml_in_data_home_names_a_prefix_outside_games(home, tmp_path):
    """Lutris falls back to the data home for its config and the prefix can be
    anywhere, so the yml is the only way to find this one."""
    prefix = _prefix(tmp_path / "drive2/arena-prefix")
    games = tmp_path / "xdg-data/lutris/games"
    games.mkdir(parents=True)
    (games / "mtg-arena-1700000000.yml").write_text(
        f"game:\n  exe: x.exe\n  prefix: '{prefix}'\nname: Arena\n"
    )
    assert wine.wine_prefixes() == [prefix]


def test_lutris_flatpak_config_and_tilde(home):
    """The Flatpak Lutris keeps its config in its sandbox, and Lutris expands
    a leading ``~`` in the prefix."""
    prefix = _prefix(home / "wineprefixes/arena")
    games = home / ".var/app/net.lutris.Lutris/config/lutris/games"
    games.mkdir(parents=True)
    (games / "a-1.yml").write_text("game:\n  prefix: ~/wineprefixes/arena\n")
    assert wine.wine_prefixes() == [prefix]


def test_lutris_default_games_folder_one_and_two_levels(home):
    """The installer's prefix defaults to ``~/Games/<slug>`` or
    ``~/Games/<service>/<slug>``, with or without a yml naming it."""
    one = _prefix(home / "Games/arena")
    two = _prefix(home / "Games/epic/arena")
    (home / "Games/notes").mkdir()
    assert wine.wine_prefixes() == [one, two]


def test_lutris_prefix_that_is_not_a_path_names_nothing(home, tmp_path, monkeypatch):
    """``$GAMEDIR`` is Lutris's own variable, not a path; resolving it against
    the working directory would be a guess."""
    cwd = _prefix(tmp_path / "cwd")
    _prefix(cwd / "$GAMEDIR")
    _prefix(cwd / "relative/dir")
    monkeypatch.chdir(cwd)
    games = tmp_path / "xdg-data/lutris/games"
    games.mkdir(parents=True)
    (games / "a.yml").write_text("game:\n  prefix: $GAMEDIR\n")
    (games / "b.yml").write_text("game:\n  prefix: relative/dir\n")
    (games / "c.yml").write_text("game:\n  prefix: ''\n")
    assert wine.wine_prefixes() == []


def test_relative_xdg_data_home_is_treated_as_unset(home, tmp_path, monkeypatch):
    """The XDG spec calls a relative value invalid; reading it would search
    the working directory."""
    cwd = tmp_path / "cwd"
    _prefix(cwd / "bottles/bottles/Arena")
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("XDG_DATA_HOME", ".")
    assert wine.wine_prefixes() == []


# --- Heroic ---


def test_heroic_games_config_json(home, tmp_path):
    """A game's own config names its prefix, wherever the user put it."""
    prefix = _prefix(tmp_path / "heroic-elsewhere/arena")
    games = tmp_path / "xdg-config/heroic/GamesConfig"
    games.mkdir(parents=True)
    (games / "abc123.json").write_text(json.dumps({"abc123": {"winePrefix": str(prefix)}}))
    assert wine.wine_prefixes() == [prefix]


def test_heroic_prefix_found_only_under_default_folder(home):
    """Older Heroic installs keep prefixes under ``Prefixes/default/<title>``
    and may have no per-game config naming them."""
    prefix = _prefix(home / "Games/Heroic/Prefixes/default/Arena")
    assert wine.wine_prefixes() == [prefix]


def test_heroic_config_json_settings(home, tmp_path):
    """The global config names a shared prefix and a folder of prefixes."""
    shared = _prefix(tmp_path / "shared-prefix")
    base = tmp_path / "prefix-base"
    child = _prefix(base / "Arena")
    heroic = tmp_path / "xdg-config/heroic"
    heroic.mkdir(parents=True)
    settings = {"winePrefix": str(shared), "defaultWinePrefixDir": str(base)}
    (heroic / "config.json").write_text(json.dumps({"defaultSettings": settings}))
    assert wine.wine_prefixes() == [shared, child]


# --- Bottles ---


def test_flatpak_bottle(home):
    """Each bottle folder is itself a prefix; the Flatpak build keeps them in
    its sandbox."""
    bottle = _prefix(home / ".var/app/com.usebottles.bottles/data/bottles/bottles/Arena")
    assert wine.wine_prefixes() == [bottle]


def test_bottle_under_a_custom_bottles_folder(home, tmp_path):
    """Bottles lets the user move its folder, recorded in ``data.yml``."""
    custom = tmp_path / "my-bottles"
    bottle = _prefix(custom / "Arena")
    data = tmp_path / "xdg-data/bottles"
    data.mkdir(parents=True)
    (data / "data.yml").write_text(f"something: 1\ncustom_bottles_path: {custom}\n")
    assert wine.wine_prefixes() == [bottle]


def test_bottle_placeholder_is_followed(home, tmp_path):
    """A bottle created elsewhere leaves only a placeholder naming it."""
    real = _prefix(tmp_path / "far-away/Arena")
    holder = tmp_path / "xdg-data/bottles/bottles/Arena"
    holder.mkdir(parents=True)
    (holder / "placeholder.yml").write_text(f"Path: {real}\n")
    assert wine.wine_prefixes() == [real]


def test_empty_custom_bottles_path_is_not_the_working_directory(home, tmp_path, monkeypatch):
    """An empty ``custom_bottles_path`` would become ``Path('')``, the working
    directory, and its subfolders would be listed as bottles."""
    cwd = tmp_path / "cwd"
    _prefix(cwd / "x")
    monkeypatch.chdir(cwd)
    data = tmp_path / "xdg-data/bottles"
    data.mkdir(parents=True)
    (data / "data.yml").write_text("custom_bottles_path: ''\n")
    assert wine.wine_prefixes() == []


# --- order and robustness ---


def test_order_follows_the_sources(home, tmp_path, monkeypatch):
    """The newest log wins and a tie goes to candidate order, so the order
    ``wine_prefixes()`` returns is part of its contract."""
    env = _prefix(tmp_path / "env-prefix")
    monkeypatch.setenv("WINEPREFIX", str(env))
    lutris = _prefix(tmp_path / "lutris-prefix")
    games = tmp_path / "xdg-data/lutris/games"
    games.mkdir(parents=True)
    (games / "a.yml").write_text(f"game:\n  prefix: {lutris}\n")
    lutris_default = _prefix(home / "Games/arena")
    heroic = _prefix(tmp_path / "heroic-prefix")
    hgames = tmp_path / "xdg-config/heroic/GamesConfig"
    hgames.mkdir(parents=True)
    (hgames / "x.json").write_text(json.dumps({"x": {"winePrefix": str(heroic)}}))
    heroic_default = _prefix(home / "Games/Heroic/Prefixes/Other")
    bottle = _prefix(tmp_path / "xdg-data/bottles/bottles/Arena")
    dot_wine = _prefix(home / ".wine")
    assert wine.wine_prefixes() == [
        env,
        lutris,
        lutris_default,
        heroic,
        heroic_default,
        bottle,
        dot_wine,
    ]


def test_corrupt_files_do_not_hide_valid_neighbours(home, tmp_path):
    """One launcher config the user hand-edited into nonsense must cost that
    file only, not the rest of the launcher or the machine."""
    good = _prefix(home / ".wine")
    lutris = _prefix(tmp_path / "lutris-prefix")
    games = tmp_path / "xdg-data/lutris/games"
    games.mkdir(parents=True)
    (games / "bad.yml").write_bytes(b"\xff\xfe not text")
    (games / "good.yml").write_text(f"game:\n  prefix: {lutris}\n")
    heroic = _prefix(tmp_path / "heroic-prefix")
    hgames = tmp_path / "xdg-config/heroic/GamesConfig"
    hgames.mkdir(parents=True)
    (hgames / "bad.json").write_text("{not json")
    (hgames / "list.json").write_text("[1, 2]")
    (hgames / "good.json").write_text(json.dumps({"g": {"winePrefix": str(heroic)}}))
    (hgames.parent / "config.json").write_text('{"defaultSettings": 3}')
    assert wine.wine_prefixes() == [lutris, heroic, good]
