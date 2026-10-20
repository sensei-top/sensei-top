"""Steam install discovery: following libraryfolders.vdf rather than guessing.

The bug this guards: MTGA installed on a second drive was invisible, because
only Steam's own data directory was searched.
"""

from sensei_top import steam


def test_library_roots_include_folders_from_the_vdf(monkeypatch, steam_libraries):
    default_steam, other_library = steam_libraries
    monkeypatch.setattr(steam, "STEAM_DATA_DIRS", (default_steam,))
    assert steam.library_roots() == [default_steam, other_library]


def test_library_roots_deduplicate_the_default_root(monkeypatch, steam_libraries):
    """A normal install lists its own root in the vdf as entry 0, so it would
    otherwise be searched twice."""
    default_steam, _ = steam_libraries
    monkeypatch.setattr(steam, "STEAM_DATA_DIRS", (default_steam,))
    roots = steam.library_roots()
    assert len(roots) == len(set(roots))


def test_missing_vdf_still_yields_the_defaults(monkeypatch, tmp_path):
    """A Steam install with no vdf must not be an error — just no extras."""
    monkeypatch.setattr(steam, "STEAM_DATA_DIRS", (tmp_path / "nope",))
    assert steam.library_roots() == [tmp_path / "nope"]


def test_unreadable_vdf_is_not_fatal(monkeypatch, tmp_path):
    """Discovery is best-effort: a corrupt file must not stop the app from
    starting, it just means no extra libraries are known."""
    data_dir = tmp_path / "steam"
    (data_dir / "steamapps").mkdir(parents=True)
    (data_dir / "steamapps/libraryfolders.vdf").write_bytes(b"\xff\xfe not utf-8 at all")
    monkeypatch.setattr(steam, "STEAM_DATA_DIRS", (data_dir,))
    assert steam.library_roots() == [data_dir]


def _vdf(*paths):
    lines = ['"libraryfolders"', "{"]
    for i, path in enumerate(paths):
        lines += [f'\t"{i}"', "\t{", f'\t\t"path"\t\t"{path}"', "\t}"]
    return "\n".join([*lines, "}", ""])


def _home(monkeypatch, tmp_path):
    home = tmp_path / "fakehome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def test_flatpak_and_snap_data_dirs_are_roots(monkeypatch, tmp_path):
    """Those installs were invisible: Steam under a sandbox keeps its own data
    directory, which the two classic spellings never reach."""
    home = _home(monkeypatch, tmp_path)
    roots = steam.library_roots()
    assert home / ".var/app/com.valvesoftware.Steam/.local/share/Steam" in roots
    assert home / ".var/app/com.valvesoftware.Steam/data/Steam" in roots
    assert home / "snap/steam/common/.local/share/Steam" in roots
    assert home / ".steam/root" in roots


def test_symlinked_steam_root_appears_once(monkeypatch, tmp_path):
    """The three native spellings are one folder; searching it three times
    would also list its log three times. The kept spelling is the one an
    existing install already ingests under, since the watcher keys its offset
    by the path string."""
    home = _home(monkeypatch, tmp_path)
    native = home / ".local/share/Steam"
    native.mkdir(parents=True)
    (home / ".steam").mkdir()
    (home / ".steam/root").symlink_to(native)
    (home / ".steam/steam").symlink_to(native)
    roots = steam.library_roots()
    # The first spelling is kept; the other two spellings are dropped.
    assert roots.count(home / ".steam/steam") == 1
    assert home / ".local/share/Steam" not in roots
    assert home / ".steam/root" not in roots


def test_vdf_inside_the_flatpak_data_dir_names_a_second_library(monkeypatch, tmp_path):
    """A Flatpak Steam user with a game on another drive keeps the vdf inside
    the sandbox's data directory, so that is where the extra library is named."""
    home = _home(monkeypatch, tmp_path)
    flatpak = home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    other = tmp_path / "second-drive/SteamLibrary"
    (flatpak / "steamapps").mkdir(parents=True)
    (flatpak / "steamapps/libraryfolders.vdf").write_text(_vdf(flatpak, other))
    roots = steam.library_roots()
    assert other in roots
    assert roots.count(flatpak) == 1


def test_config_libraryfolders_vdf_is_read_too(monkeypatch, tmp_path):
    """Lutris reads the vdf from ``config/``, not ``steamapps/``; a library
    named only there must not be missed."""
    home = _home(monkeypatch, tmp_path)
    native = home / ".local/share/Steam"
    other = tmp_path / "another/SteamLibrary"
    (native / "config").mkdir(parents=True)
    (native / "config/libraryfolders.vdf").write_text(_vdf(other))
    assert other in steam.library_roots()
