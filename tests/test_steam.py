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
