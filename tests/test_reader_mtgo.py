"""``reader/mtgo.py``'s own reader-stage contract: the scan that says which
game logs moved, the store that records the bytes it is handed, and
``ingest_mtgo_dir`` built from the two — change detection, the
full-file-per-row storage model, and fail-soft handling of a file that
vanishes mid-scan. Directory *resolution* (env var, config file, no
autodetection) is ``mtgo/config.py::resolve_log_dir``'s contract instead —
see ``test_llm.py``, which already exercises that module's config-file
fail-soft behaviour end to end.

The bytes here are synthetic: the reader never decodes a payload, so what is
in a file does not matter to it, only its size, mtime and inode.
"""

import base64
import logging
import os
import re
import sqlite3
from pathlib import Path

from sensei_top.db import open_database
from sensei_top.reader.mtgo import (
    GameLogFile,
    _mtime_iso,
    ingest_mtgo_dir,
    read_game_log,
    scan_game_logs,
    store_game_log,
)

# --- _mtime_iso (Bug A guard) ------------------------------------------------


def test_mtime_iso_is_local_naive_seconds_with_no_zone_marker(tmp_path):
    # Bug A: writing MTGO's logged_at as UTC-with-Z made an MTGO match sort
    # as though it were UTC-offset hours newer than an Arena match at the
    # same instant (module docstring). The fix is shape parity with
    # segmenter.py's Arena timestamps: local wall clock, no 'Z', no numeric
    # offset — assert the exact shape rather than a specific value, since the
    # value is this machine's own clock/timezone.
    f = tmp_path / "Match_GameLog_deadbeef.dat"
    f.write_bytes(b"x")
    stamp = _mtime_iso(f)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", stamp), stamp


# --- ingest_mtgo_dir ----------------------------------------------------------


def _rows_for(conn, source_file: str) -> list[str]:
    """Every payload stored for one source_file, in insertion (id) order."""
    return [
        r["payload"]
        for r in conn.execute(
            "SELECT payload FROM raw_events WHERE source_file = ? ORDER BY id", (source_file,)
        ).fetchall()
    ]


def test_a_grown_file_yields_a_second_strictly_longer_row(tmp_path):
    conn = open_database(tmp_path / "t.db")
    directory = tmp_path / "mtgo-share"
    directory.mkdir()
    f = directory / "Match_GameLog_grows.dat"
    f.write_bytes(b"short-prefix")

    first = ingest_mtgo_dir(conn, directory)
    assert first.rows_inserted == 1

    # MTGO flushes the same file progressively during a live match (module
    # docstring): a later poll re-reads the grown file in full and stores
    # the entire current content as a new row, not just the delta.
    f.write_bytes(b"short-prefix-plus-a-lot-more-bytes-appended-during-play")

    second = ingest_mtgo_dir(conn, directory)
    assert second.rows_inserted == 1
    assert second.rows_duplicate == 0

    payloads = _rows_for(conn, f.name)
    assert len(payloads) == 2
    assert len(payloads[1]) > len(payloads[0])


def test_unchanged_directory_inserts_nothing_and_opens_no_transaction(tmp_path):
    conn = open_database(tmp_path / "t.db")
    directory = tmp_path / "mtgo-share"
    directory.mkdir()
    f = directory / "Match_GameLog_steady.dat"
    f.write_bytes(b"unchanging-content")

    baseline = ingest_mtgo_dir(conn, directory)
    assert baseline.rows_inserted == 1

    # A poll that finds every file unchanged must not take a write lock: the
    # two-pass design (module docstring) skips BEGIN entirely when the first,
    # transaction-free pass finds nothing changed.
    again = ingest_mtgo_dir(conn, directory)
    assert again.rows_inserted == 0
    assert again.rows_duplicate == 0
    assert again.entries_seen == 0
    assert conn.in_transaction is False

    assert len(_rows_for(conn, f.name)) == 1


def test_a_file_vanishing_between_glob_and_read_warns_and_the_rest_still_ingest(
    tmp_path, monkeypatch, caplog
):
    conn = open_database(tmp_path / "t.db")
    directory = tmp_path / "mtgo-share"
    directory.mkdir()
    survivor = directory / "Match_GameLog_aaaaaaaa.dat"
    vanishing = directory / "Match_GameLog_bbbbbbbb.dat"
    survivor.write_bytes(b"still here")
    vanishing.write_bytes(b"gone by read time")

    # scan_game_logs's stat() (the transaction-free scan) sees both files;
    # simulate the file disappearing before read_game_log's
    # path.read_bytes() — a torn-down virtiofs share or a rotated-away match
    # log, per ingest_mtgo_dir's own docstring.
    real_read_bytes = Path.read_bytes

    def flaky_read_bytes(self: Path, *args, **kwargs):
        if self.name == vanishing.name:
            raise OSError("vanished mid-scan")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)

    with caplog.at_level(logging.WARNING):
        stats = ingest_mtgo_dir(conn, directory)

    # One unreadable file must never block every other file in the directory.
    assert stats.rows_inserted == 1
    assert _rows_for(conn, survivor.name)
    assert _rows_for(conn, vanishing.name) == []
    assert any(vanishing.name in message for message in caplog.messages)


# --- scan_game_logs, read_game_log, store_game_log ----------------------------
#
# The live watcher (plan 3, D2) scans every 2 s and stores a changed file only
# once its last game is decided, so the scan has to keep reporting a file until
# a store records exactly the bytes it stored — and must never write anything
# itself.


def _share(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    conn = open_database(tmp_path / "t.db")
    directory = tmp_path / "mtgo-share"
    directory.mkdir()
    return conn, directory


def _store(conn, path: Path) -> bool:
    return store_game_log(conn, read_game_log(path))


def _no_stat_error(path: Path, exc: OSError) -> None:
    raise AssertionError(f"unexpected stat() failure on {path.name}: {exc}")


def _scan(conn, directory: Path, **kwargs) -> list[GameLogFile]:
    """``scan_game_logs`` where every file is expected to stat."""
    return scan_game_logs(conn, directory, on_stat_error=_no_stat_error, **kwargs)


def _stat_refused_for(monkeypatch, name: str) -> None:
    """Make ``Path.stat`` raise for one file name, as a share that refuses
    one entry would, and behave as usual for every other path."""
    real_stat = Path.stat

    def stat(self: Path, *args, **kwargs):
        if self.name == name:
            raise PermissionError("denied")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)


def test_scan_reports_a_new_and_a_grown_file_but_not_an_unchanged_one(tmp_path):
    conn, directory = _share(tmp_path)
    grown = directory / "Match_GameLog_aaaaaaaa.dat"
    steady = directory / "Match_GameLog_cccccccc.dat"
    grown.write_bytes(b"game one")
    steady.write_bytes(b"a finished match")
    assert _store(conn, grown)
    assert _store(conn, steady)

    with grown.open("ab") as fh:
        fh.write(b", game two")
    new = directory / "Match_GameLog_bbbbbbbb.dat"
    new.write_bytes(b"die roll")

    changed = _scan(conn, directory)

    assert [file.path for file in changed] == [grown, new]
    assert [file.size for file in changed] == [len(b"game one, game two"), len(b"die roll")]


def test_scanning_twice_writes_nothing(tmp_path):
    conn, directory = _share(tmp_path)
    for name in ("Match_GameLog_aaaaaaaa.dat", "Match_GameLog_bbbbbbbb.dat"):
        (directory / name).write_bytes(b"mid-game")
    before = conn.total_changes

    first = _scan(conn, directory)
    second = _scan(conn, directory)

    # Nothing is stored until a store says so, so both scans report both.
    assert len(first) == len(second) == 2
    assert conn.total_changes == before
    assert conn.in_transaction is False
    assert conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM ingest_state").fetchone()[0] == 0


def test_a_store_then_a_scan_reports_nothing(tmp_path):
    conn, directory = _share(tmp_path)
    f = directory / "Match_GameLog_aaaaaaaa.dat"
    f.write_bytes(b"game one decided")
    assert [file.path for file in _scan(conn, directory)] == [f]

    read = read_game_log(f)
    assert store_game_log(conn, read) is True

    assert _scan(conn, directory) == []
    # The same bytes again are a duplicate digest, not a second row.
    assert store_game_log(conn, read) is False
    assert len(_rows_for(conn, f.name)) == 1
    # --from-start re-reads every file, stored or not.
    assert [file.path for file in _scan(conn, directory, from_start=True)] == [f]


def test_a_file_grown_after_its_read_is_reported_again(tmp_path):
    """The store records the identity of the bytes it was handed, not the
    file's identity when it stores them: MTGO appending between the watcher's
    read and its store must leave the file reported, or the appended bytes
    would wait for the next append to be stored at all."""
    conn, directory = _share(tmp_path)
    f = directory / "Match_GameLog_aaaaaaaa.dat"
    f.write_bytes(b"game one decided")
    read = read_game_log(f)
    with f.open("ab") as fh:
        fh.write(b", game two begins")

    assert store_game_log(conn, read) is True

    # Exactly the bytes handed to the store, not the file as it now is.
    assert _rows_for(conn, f.name) == [base64.b64encode(b"game one decided").decode("ascii")]
    changed = _scan(conn, directory)
    assert [file.path for file in changed] == [f]
    assert changed[0].size == len(b"game one decided, game two begins")

    assert _store(conn, f) is True
    assert _scan(conn, directory) == []


def test_a_same_size_change_of_mtime_is_reported(tmp_path):
    conn, directory = _share(tmp_path)
    f = directory / "Match_GameLog_aaaaaaaa.dat"
    f.write_bytes(b"sized first, filled later")
    assert _store(conn, f)
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    assert [file.path for file in _scan(conn, directory)] == [f]


def test_a_same_size_same_mtime_replacement_is_reported(tmp_path):
    conn, directory = _share(tmp_path)
    f = directory / "Match_GameLog_aaaaaaaa.dat"
    f.write_bytes(b"original")
    assert _store(conn, f)
    st = f.stat()
    replacement = directory / "replacement.tmp"
    replacement.write_bytes(b"replaced")
    os.utime(replacement, ns=(st.st_atime_ns, st.st_mtime_ns))
    os.replace(replacement, f)
    assert f.stat().st_ino != st.st_ino
    assert (f.stat().st_size, f.stat().st_mtime_ns) == (st.st_size, st.st_mtime_ns)

    assert [file.path for file in _scan(conn, directory)] == [f]


def test_an_idle_scan_costs_one_stat_per_file_and_one_state_query(tmp_path, monkeypatch):
    """The watcher pays this every 2 s for as long as it runs, over a folder
    that keeps every match ever played, almost always with nothing changed."""
    conn, directory = _share(tmp_path)
    names = [f"Match_GameLog_{n:08d}.dat" for n in range(5)]
    for name in names:
        (directory / name).write_bytes(b"a finished match")
        assert _store(conn, directory / name)

    stats_by_name: dict[str, int] = {}
    real_stat = Path.stat

    def counting_stat(self: Path, *args, **kwargs):
        if self.name.startswith("Match_GameLog_"):
            stats_by_name[self.name] = stats_by_name.get(self.name, 0) + 1
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", counting_stat)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        assert _scan(conn, directory) == []
    finally:
        conn.set_trace_callback(None)

    assert stats_by_name == dict.fromkeys(names, 1)
    assert len(statements) == 1
    assert "ingest_state" in statements[0]


def test_scan_of_a_missing_directory_is_empty(tmp_path):
    conn, _directory = _share(tmp_path)
    assert _scan(conn, tmp_path / "not-mounted") == []


def test_a_file_that_cannot_be_statted_is_handed_to_the_caller_not_logged(
    tmp_path, monkeypatch, caplog
):
    """The scan leaves the file out and hands it, with its error, to
    ``on_stat_error``; it logs nothing itself, because the watcher scans
    every 2 s and warns once per file, which only it can count. The file
    beside it is still reported."""
    conn, directory = _share(tmp_path)
    fine = directory / "Match_GameLog_aaaaaaaa.dat"
    refused = directory / "Match_GameLog_bbbbbbbb.dat"
    fine.write_bytes(b"die roll")
    refused.write_bytes(b"die roll")
    _stat_refused_for(monkeypatch, refused.name)
    failed: list[tuple[Path, OSError]] = []

    with caplog.at_level(logging.DEBUG):
        changed = scan_game_logs(
            conn, directory, on_stat_error=lambda path, exc: failed.append((path, exc))
        )

    assert [file.path for file in changed] == [fine]
    assert [(path, type(exc), str(exc)) for path, exc in failed] == [
        (refused, PermissionError, "denied")
    ]
    assert caplog.messages == []


def test_ingest_mtgo_dir_warns_of_a_file_it_cannot_stat_on_every_call(
    tmp_path, monkeypatch, caplog
):
    """``sensei-top ingest-mtgo`` runs once and exits, so each run says what
    it skipped: one warning per call, and the file beside it still stored."""
    conn, directory = _share(tmp_path)
    fine = directory / "Match_GameLog_aaaaaaaa.dat"
    refused = directory / "Match_GameLog_bbbbbbbb.dat"
    fine.write_bytes(b"die roll")
    refused.write_bytes(b"die roll")
    _stat_refused_for(monkeypatch, refused.name)

    with caplog.at_level(logging.WARNING):
        first = ingest_mtgo_dir(conn, directory)
        ingest_mtgo_dir(conn, directory)

    assert first.rows_inserted == 1
    assert _rows_for(conn, fine.name)
    assert _rows_for(conn, refused.name) == []
    warned = [m for m in caplog.messages if refused.name in m]
    assert len(warned) == 2
    assert all("could not stat" in m for m in warned)
