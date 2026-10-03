"""``ingest_mtgo_dir``'s own reader-stage contract: change detection, the
full-file-per-row storage model, and fail-soft handling of a file that
vanishes mid-scan. Directory *resolution* (env var, config file, no
autodetection) is ``mtgo/config.py::resolve_log_dir``'s contract instead —
see ``test_llm.py``, which already exercises that module's config-file
fail-soft behaviour end to end.
"""

import logging
import re
from pathlib import Path

from sensei_top.db import open_database
from sensei_top.reader.mtgo import _mtime_iso, ingest_mtgo_dir

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

    # _file_changed's stat() (the first, transaction-free pass) sees both
    # files; simulate the file disappearing before the second pass's
    # path.read_bytes() (_ingest_one_file) — a torn-down virtiofs share or a
    # rotated-away match log, per ingest_mtgo_dir's own docstring.
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
