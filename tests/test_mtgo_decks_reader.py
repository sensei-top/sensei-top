"""The MTGO deck-folder reader (``reader/mtgo_decks.py``), its folder
resolution (``mtgo/config.py::resolve_deck_dir`` and the CLI's two wrappers),
``ingest-mtgo``'s deck leg and the watcher's poll of the folder
(``live.py::_poll_mtgo_decks``).

The deck files are ``tests/fixtures/mtgo_deck_sample.dek``, an export, and
``tests/fixtures/mtgo_grouping_deck.xml``, an entry in MTGO's deck store. The
reader never decodes either, so every expectation here is about names, bytes
and rows, taken from the files themselves.
"""

import base64
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sensei_top import cli as cli_module
from sensei_top import live as live_module
from sensei_top.db import open_database
from sensei_top.live import LiveIngester
from sensei_top.llm.config import config_path
from sensei_top.mtgo import config as mtgo_config
from sensei_top.reader import mtgo_decks
from sensei_top.reader.mtgo_decks import ingest_deck_dir

FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_deck_sample.dek"
GROUPING = Path(__file__).parent / "fixtures" / "mtgo_grouping_deck.xml"


def _deck_rows(conn):
    return conn.execute(
        "SELECT source_file, label, payload, logged_at FROM raw_events "
        "WHERE source = 'mtgo_deck' ORDER BY id"
    ).fetchall()


def _folder(tmp_path, *names: str, name: str = "decks") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    for file_name in names:
        shutil.copy(FIXTURE, folder / file_name)
    return folder


def _bad_name() -> str:
    r"""The same string everywhere. On Linux it is what ``os.fsdecode`` gives
    for the bytes ``b"bad\xff.dek"`` (a name that is not valid UTF-8). On Windows
    it is a name holding a lone surrogate, which NTFS stores and UTF-8 cannot
    encode."""
    return "bad\udcff.dek"


def _copy_with_bad_name(folder: Path) -> None:
    try:
        shutil.copy(FIXTURE, folder / _bad_name())
    except OSError:
        pytest.skip("this filesystem rejects file names that are not valid UTF-8")
    except UnicodeError:
        if sys.platform != "win32":
            raise
        pytest.skip("this filesystem refuses a file name holding a lone surrogate")


def _warnings_from(caplog, module) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == module.__name__]


def _run_ingest_mtgo(db_path: Path, *extra: str) -> None:
    args = cli_module.build_parser().parse_args(["--db", str(db_path), "ingest-mtgo", *extra])
    args.func(args)


def test_one_row_per_dek_file_and_nothing_else_is_read(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek", "Beta.dek")
    (folder / "notes.txt").write_text("not a deck")  # D13: .txt waits
    (folder / "nested").mkdir()
    shutil.copy(FIXTURE, folder / "nested" / "Gamma.dek")  # not recursive
    conn = open_database(tmp_path / "t.db")

    stats = ingest_deck_dir(conn, folder)

    rows = _deck_rows(conn)
    assert [r["source_file"] for r in rows] == ["Alpha.dek", "Beta.dek"]
    assert stats.rows_inserted == 2
    assert {r["label"] for r in rows} == {"MtgoDeckFile"}


def test_a_directory_named_like_a_deck_is_not_a_deck(tmp_path, caplog):
    """Skipped for what it is, not through the read failing: a warning here
    would mean the regular-file check is gone and the directory only failed
    at ``read_bytes``."""
    folder = _folder(tmp_path, "Alpha.dek")
    (folder / "Folder.dek").mkdir()
    conn = open_database(tmp_path / "t.db")

    with caplog.at_level(logging.WARNING, logger=mtgo_decks.__name__):
        ingest_deck_dir(conn, folder)

    assert [r["source_file"] for r in _deck_rows(conn)] == ["Alpha.dek"]
    assert _warnings_from(caplog, mtgo_decks) == []


def test_the_payload_is_the_files_bytes_verbatim(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek")
    conn = open_database(tmp_path / "t.db")

    ingest_deck_dir(conn, folder)

    (row,) = _deck_rows(conn)
    assert base64.b64decode(row["payload"]) == FIXTURE.read_bytes()


def test_deck_rows_carry_their_own_source_and_label(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek")
    conn = open_database(tmp_path / "t.db")

    ingest_deck_dir(conn, folder)

    rows = conn.execute("SELECT DISTINCT source, label FROM raw_events").fetchall()
    assert [tuple(r) for r in rows] == [("mtgo_deck", "MtgoDeckFile")]


def test_an_unchanged_file_adds_nothing(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek")
    conn = open_database(tmp_path / "t.db")
    ingest_deck_dir(conn, folder)

    again = ingest_deck_dir(conn, folder)

    assert again.entries_seen == 0  # skipped through ingest_state, not re-read
    assert again.rows_inserted == 0
    assert len(_deck_rows(conn)) == 1


def test_a_changed_file_adds_a_row_and_keeps_the_old_one(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek")
    conn = open_database(tmp_path / "t.db")
    ingest_deck_dir(conn, folder)

    edited = FIXTURE.read_bytes().replace(b'Name="Plains"', b'Name="Island"')
    assert len(edited) == FIXTURE.stat().st_size  # same size: the case inode+size misses
    path = folder / "Alpha.dek"
    inode_before = path.stat().st_ino
    path.write_bytes(edited)
    # Same inode (an in-place write) and a forced-different mtime: the file's
    # clock may not tick between two writes in one test.
    st = path.stat()
    assert st.st_ino == inode_before
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

    stats = ingest_deck_dir(conn, folder)

    assert stats.rows_inserted == 1
    payloads = [base64.b64decode(r["payload"]) for r in _deck_rows(conn)]
    assert payloads == [FIXTURE.read_bytes(), edited]


def test_the_state_row_keeps_the_size_in_byte_offset_and_the_token_in_inode(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek")
    conn = open_database(tmp_path / "t.db")

    ingest_deck_dir(conn, folder)

    st = (folder / "Alpha.dek").stat()
    row = conn.execute(
        "SELECT byte_offset, inode, last_size FROM ingest_state WHERE source_path = ?",
        (str(folder / "Alpha.dek"),),
    ).fetchone()
    assert row["byte_offset"] == FIXTURE.stat().st_size
    assert row["last_size"] == FIXTURE.stat().st_size
    assert row["inode"] == f"{st.st_ino}:{st.st_mtime_ns}"


def test_the_same_bytes_under_another_name_is_another_row(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek", "Copy of Alpha.dek")
    conn = open_database(tmp_path / "t.db")

    ingest_deck_dir(conn, folder)

    assert len(_deck_rows(conn)) == 2


def test_from_start_re_reads_but_stores_no_duplicate(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek")
    conn = open_database(tmp_path / "t.db")
    ingest_deck_dir(conn, folder)

    stats = ingest_deck_dir(conn, folder, from_start=True)

    assert stats.entries_seen == 1
    assert stats.rows_duplicate == 1
    assert len(_deck_rows(conn)) == 1


def test_a_missing_folder_is_an_empty_result(tmp_path):
    conn = open_database(tmp_path / "t.db")

    stats = ingest_deck_dir(conn, tmp_path / "nope")

    assert stats.rows_inserted == 0
    assert _deck_rows(conn) == []


def test_a_name_that_is_not_valid_utf8_is_skipped_and_the_rest_are_stored(tmp_path, caplog):
    folder = _folder(tmp_path, "Good.dek")
    _copy_with_bad_name(folder)
    conn = open_database(tmp_path / "t.db")

    with caplog.at_level(logging.WARNING, logger=mtgo_decks.__name__):
        stats = ingest_deck_dir(conn, folder)

    assert [r["source_file"] for r in _deck_rows(conn)] == ["Good.dek"]
    assert stats.rows_inserted == 1
    (warning,) = _warnings_from(caplog, mtgo_decks)
    assert repr(_bad_name()) in warning


def test_the_store_pass_skips_a_bad_name_too(tmp_path, monkeypatch, caplog):
    """Pass one normally stops a bad name first; forcing it through proves
    the second pass has its own guard rather than relying on the first."""
    folder = _folder(tmp_path, "Good.dek")
    _copy_with_bad_name(folder)
    monkeypatch.setattr(mtgo_decks, "_deck_changed", lambda conn, path, *, from_start: True)
    conn = open_database(tmp_path / "t.db")

    with caplog.at_level(logging.WARNING, logger=mtgo_decks.__name__):
        ingest_deck_dir(conn, folder)

    assert [r["source_file"] for r in _deck_rows(conn)] == ["Good.dek"]
    (warning,) = _warnings_from(caplog, mtgo_decks)
    assert repr(_bad_name()) in warning


def test_an_entry_that_cannot_be_read_is_skipped_and_the_rest_are_stored(tmp_path, caplog):
    folder = _folder(tmp_path, "Good.dek")
    try:
        (folder / "Dangling.dek").symlink_to(tmp_path / "gone.dek")
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot make a symlink")
    conn = open_database(tmp_path / "t.db")

    with caplog.at_level(logging.WARNING, logger=mtgo_decks.__name__):
        ingest_deck_dir(conn, folder)

    assert [r["source_file"] for r in _deck_rows(conn)] == ["Good.dek"]
    (warning,) = _warnings_from(caplog, mtgo_decks)
    assert "Dangling.dek" in warning


def test_nothing_configured_resolves_to_none(tmp_path):
    assert mtgo_config.resolve_deck_dir() is None


def test_the_environment_then_the_config_file_name_the_folder(monkeypatch):
    config_file = config_path()
    config_file.parent.mkdir(parents=True)
    config_file.write_text('[mtgo]\ndeck_dir = "/from/config"\n')

    assert mtgo_config.resolve_deck_dir() == (Path("/from/config"), "config.toml [mtgo] deck_dir")

    monkeypatch.setenv("MTGO_DECK_DIR", "/from/env")
    assert mtgo_config.resolve_deck_dir() == (Path("/from/env"), "$MTGO_DECK_DIR")


def test_the_watcher_without_a_deck_folder_reads_nothing(tmp_path):
    live = LiveIngester(db_path=tmp_path / "t.db", log_path=tmp_path / "Player.log")
    conn = open_database(live.db_path)

    assert live.mtgo_deck_dir is None
    assert live._poll_mtgo_decks(conn) == 0
    assert _deck_rows(conn) == []


def test_ingest_mtgo_with_only_a_deck_folder_stores_one_row_per_dek(tmp_path, capsys):
    folder = _folder(tmp_path, "Alpha.dek", "Beta.dek")
    db_path = tmp_path / "t.db"

    _run_ingest_mtgo(db_path, "--deck-dir", str(folder))

    conn = open_database(db_path)
    assert [r["source_file"] for r in _deck_rows(conn)] == ["Alpha.dek", "Beta.dek"]
    assert str(folder) in capsys.readouterr().out


def test_ingest_mtgo_reads_game_logs_and_decks_in_one_run(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "Match_GameLog_aaaaaaaa.dat").write_bytes(b"opaque")
    folder = _folder(tmp_path, "Alpha.dek")
    db_path = tmp_path / "t.db"

    _run_ingest_mtgo(db_path, "--dir", str(logs), "--deck-dir", str(folder))

    conn = open_database(db_path)
    counts = dict(conn.execute("SELECT source, COUNT(*) FROM raw_events GROUP BY source"))
    assert counts == {"mtgo": 1, "mtgo_deck": 1}


def test_ingest_mtgo_with_nothing_configured_still_exits_naming_the_fix(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        _run_ingest_mtgo(tmp_path / "t.db")

    assert "--set-mtgo-dir" in excinfo.value.code


def test_the_deck_dir_flag_outranks_the_environment_for_ingest_mtgo(
    monkeypatch, tmp_path
):
    flagged = _folder(tmp_path, "Flagged.dek", name="flagged")
    ambient = _folder(tmp_path, "Ambient.dek", name="ambient")
    monkeypatch.setenv("MTGO_DECK_DIR", str(ambient))
    db_path = tmp_path / "t.db"

    _run_ingest_mtgo(db_path, "--deck-dir", str(flagged))

    conn = open_database(db_path)
    assert [r["source_file"] for r in _deck_rows(conn)] == ["Flagged.dek"]


def test_the_environment_alone_names_the_deck_folder_for_ingest_mtgo(monkeypatch, tmp_path):
    ambient = _folder(tmp_path, "Ambient.dek", name="ambient")
    monkeypatch.setenv("MTGO_DECK_DIR", str(ambient))
    db_path = tmp_path / "t.db"

    _run_ingest_mtgo(db_path)

    conn = open_database(db_path)
    assert [r["source_file"] for r in _deck_rows(conn)] == ["Ambient.dek"]


def test_a_deck_path_that_is_a_file_exits_for_an_explicit_argument(tmp_path):
    not_a_dir = tmp_path / "Alpha.dek"
    shutil.copy(FIXTURE, not_a_dir)

    with pytest.raises(SystemExit) as excinfo:
        cli_module._resolve_mtgo_deck_dir(str(not_a_dir))

    assert excinfo.value.code == f"Deck path is not a directory: {not_a_dir}"


def test_a_deck_path_that_is_a_file_exits_naming_the_env_source(monkeypatch, tmp_path):
    not_a_dir = tmp_path / "Alpha.dek"
    shutil.copy(FIXTURE, not_a_dir)
    monkeypatch.setenv("MTGO_DECK_DIR", str(not_a_dir))

    with pytest.raises(SystemExit) as excinfo:
        cli_module._resolve_mtgo_deck_dir(None)

    assert excinfo.value.code == f"Deck path is not a directory: {not_a_dir} (from $MTGO_DECK_DIR)"


def test_a_missing_deck_directory_exits_naming_the_env_source(monkeypatch, tmp_path):
    missing = tmp_path / "not-mounted-yet"
    monkeypatch.setenv("MTGO_DECK_DIR", str(missing))

    with pytest.raises(SystemExit) as excinfo:
        cli_module._resolve_mtgo_deck_dir(None)

    assert excinfo.value.code == f"Deck directory not found: {missing} (from $MTGO_DECK_DIR)"


def test_the_watch_resolver_skips_a_configured_file_with_one_warning(
    monkeypatch, tmp_path, caplog
):
    not_a_dir = tmp_path / "Alpha.dek"
    shutil.copy(FIXTURE, not_a_dir)
    monkeypatch.setenv("MTGO_DECK_DIR", str(not_a_dir))
    args = SimpleNamespace(no_mtgo=False, mtgo_deck_dir=None)

    with caplog.at_level(logging.WARNING):
        result = cli_module._resolve_watch_mtgo_deck_dir(args)

    assert result is None
    (warning,) = _warnings_from(caplog, cli_module)
    assert str(not_a_dir) in warning
    assert "$MTGO_DECK_DIR" in warning
    assert "is not a directory" in warning


def test_the_watch_resolver_skips_a_configured_missing_directory_with_one_warning(
    monkeypatch, tmp_path, caplog
):
    missing = tmp_path / "not-mounted-yet"
    monkeypatch.setenv("MTGO_DECK_DIR", str(missing))
    args = SimpleNamespace(no_mtgo=False, mtgo_deck_dir=None)

    with caplog.at_level(logging.WARNING):
        result = cli_module._resolve_watch_mtgo_deck_dir(args)

    assert result is None
    (warning,) = _warnings_from(caplog, cli_module)
    assert "does not exist" in warning


def test_the_watch_resolver_exits_for_an_explicit_file(tmp_path):
    not_a_dir = tmp_path / "Alpha.dek"
    shutil.copy(FIXTURE, not_a_dir)
    args = SimpleNamespace(no_mtgo=False, mtgo_deck_dir=str(not_a_dir))

    with pytest.raises(SystemExit) as excinfo:
        cli_module._resolve_watch_mtgo_deck_dir(args)

    assert excinfo.value.code == f"Deck path is not a directory: {not_a_dir}"


def test_the_watch_resolver_returns_a_configured_directory_and_no_mtgo_skips_it(
    monkeypatch, tmp_path
):
    folder = _folder(tmp_path, "Alpha.dek")
    monkeypatch.setenv("MTGO_DECK_DIR", str(folder))

    on = SimpleNamespace(no_mtgo=False, mtgo_deck_dir=None)
    off = SimpleNamespace(no_mtgo=True, mtgo_deck_dir=None)

    assert cli_module._resolve_watch_mtgo_deck_dir(on) == folder
    assert cli_module._resolve_watch_mtgo_deck_dir(off) is None


def _watcher(tmp_path, folder, *, every):
    log = tmp_path / "Player.log"
    log.write_text("")
    return LiveIngester(
        db_path=tmp_path / "live.db",
        log_path=log,
        mtgo_deck_dir=folder,
        deck_poll_every=every,
        project_enabled=False,
    )


def test_a_new_deck_file_is_picked_up_on_the_next_deck_poll(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek")
    live = _watcher(tmp_path, folder, every=0.02)
    conn = open_database(live.db_path)

    assert live.ingest_once(conn) == 1  # the first poll reads at once
    shutil.copy(FIXTURE, folder / "Beta.dek")
    time.sleep(0.05)  # past deck_poll_every

    assert live.ingest_once(conn) == 1
    assert [r["source_file"] for r in _deck_rows(conn)] == ["Alpha.dek", "Beta.dek"]


def test_the_folder_is_not_read_again_before_the_interval(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek")
    live = _watcher(tmp_path, folder, every=live_module.DECK_POLL_SECONDS)
    conn = open_database(live.db_path)
    live.ingest_once(conn)
    shutil.copy(FIXTURE, folder / "Beta.dek")

    assert live.ingest_once(conn) == 0
    assert len(_deck_rows(conn)) == 1


def test_an_unreachable_folder_is_logged_and_the_loop_continues(tmp_path, monkeypatch, caplog):
    def boom(conn, directory):
        raise OSError("mount is gone")

    monkeypatch.setattr(live_module, "ingest_deck_dir", boom)
    live = _watcher(tmp_path, tmp_path / "decks", every=0.0)
    conn = open_database(live.db_path)

    with caplog.at_level(logging.WARNING, logger=live_module.__name__):
        assert live.ingest_once(conn) == 0

    assert live.stats.errors == 1
    assert "mount is gone" in (live.stats.last_error or "")
    (warning,) = _warnings_from(caplog, live_module)
    assert "mount is gone" in warning


def test_a_grouping_is_stored_verbatim_under_its_own_label(tmp_path):
    """Byte for byte, the BOM and the CRLF line ends included."""
    folder = _folder(tmp_path)
    shutil.copy(GROUPING, folder / "grouping 0001.xml")
    conn = open_database(tmp_path / "t.db")
    assert GROUPING.read_bytes().startswith(b"\xef\xbb\xbf")

    stats = ingest_deck_dir(conn, folder)

    (row,) = _deck_rows(conn)
    assert stats.rows_inserted == 1
    assert (row["source_file"], row["label"]) == ("grouping 0001.xml", "MtgoDeckGrouping")
    assert base64.b64decode(row["payload"]) == GROUPING.read_bytes()
    source = conn.execute("SELECT DISTINCT source FROM raw_events").fetchall()
    assert [tuple(r) for r in source] == [("mtgo_deck",)]


def test_groupings_and_exports_in_one_folder_each_keep_their_label(tmp_path):
    folder = _folder(tmp_path, "Alpha.dek")
    shutil.copy(GROUPING, folder / "grouping 0001.xml")
    conn = open_database(tmp_path / "t.db")

    ingest_deck_dir(conn, folder)

    labels = {r["source_file"]: r["label"] for r in _deck_rows(conn)}
    assert labels == {"Alpha.dek": "MtgoDeckFile", "grouping 0001.xml": "MtgoDeckGrouping"}


@pytest.mark.parametrize(
    ("file_name", "stored"),
    [
        ("grouping 0001.xml", True),
        ("Grouping 0001.XML", True),  # MTGO runs on Windows: case is not a name
        ("grouping .xml", True),
        ("grouping.xml", False),  # no space: not grouping *.xml
        ("groupings 0001.xml", False),
        ("my grouping 0001.xml", False),
        ("grouping 0001.xml.bak", False),
        ("grouping 0001.txt", False),
        ("settings.xml", False),
        ("Match_GameLog_aaaaaaaa.dat", False),  # the game logs share the folder
    ],
)
def test_only_grouping_star_xml_is_a_grouping(tmp_path, file_name, stored):
    folder = _folder(tmp_path)
    shutil.copy(GROUPING, folder / file_name)
    conn = open_database(tmp_path / "t.db")

    ingest_deck_dir(conn, folder)

    assert [r["source_file"] for r in _deck_rows(conn)] == ([file_name] if stored else [])


def test_an_unchanged_grouping_adds_nothing_and_a_changed_one_adds_a_row(tmp_path):
    folder = _folder(tmp_path)
    path = folder / "grouping 0001.xml"
    shutil.copy(GROUPING, path)
    conn = open_database(tmp_path / "t.db")
    ingest_deck_dir(conn, folder)

    again = ingest_deck_dir(conn, folder)
    assert (again.entries_seen, again.rows_inserted) == (0, 0)

    edited = GROUPING.read_bytes().replace(b'CatId="308"', b'CatId="309"')
    assert len(edited) == GROUPING.stat().st_size
    path.write_bytes(edited)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

    stats = ingest_deck_dir(conn, folder)

    assert stats.rows_inserted == 1
    payloads = [base64.b64decode(r["payload"]) for r in _deck_rows(conn)]
    assert payloads == [GROUPING.read_bytes(), edited]
