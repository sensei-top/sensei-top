"""Ingester tests: digest semantics, resume, truncation, rotation recovery."""

import inspect
import logging
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.reader.ingest import (
    _STEAM_COMPATDATA_RELATIVE,
    compute_digest,
    default_log_path,
    ingest_file,
    ingest_with_recovery,
    previous_log_path,
    watch,
)
from sensei_top.reader.segmenter import EntryKind, LogEntry

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_player.log"


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]


# --- digest -----------------------------------------------------------------


def entry(payload="{}", line=1, ts="2026-08-13T14:00:00"):
    return LogEntry(kind=EntryKind.EVENT, payload=payload, logged_at=ts, line_number=line)


def test_identical_content_same_digest():
    assert compute_digest(entry()) == compute_digest(entry())


def test_repeated_occurrence_is_distinct():
    # Arena polls some endpoints repeatedly with byte-identical responses;
    # a payload-only digest would collapse them into one row.
    assert compute_digest(entry(), 0) != compute_digest(entry(), 1)


def test_the_line_a_payload_sat_on_does_not_change_its_digest():
    # The bug this replaced: a line number is file-relative, and a rotated
    # snapshot carries a different amount of preamble than the log it was cut
    # from, so the same event lands on a different line in each file.
    assert compute_digest(entry(line=10)) == compute_digest(entry(line=20))


def test_same_payload_different_timestamp_is_distinct():
    assert compute_digest(entry(ts="2026-08-13T14:00:00")) != compute_digest(
        entry(ts="2026-08-13T15:00:00")
    )


def test_digest_takes_no_source_argument():
    # Player.log rotates to Player-prev.log with identical content; including the
    # filename would duplicate the whole previous session on recovery. The
    # guarantee is structural — there is no parameter to route a filename
    # through — so this asserts the signature; the behaviour it protects is
    # covered by test_recovery_does_not_duplicate_rotated_content.
    assert list(inspect.signature(compute_digest).parameters) == ["entry", "occurrence"]


# --- ingestion --------------------------------------------------------------


def test_ingest_writes_rows(conn):
    stats = ingest_file(conn, SAMPLE, locale_hint="mdy")
    assert stats.rows_inserted > 0
    assert count(conn) == stats.rows_inserted


def test_reingest_is_idempotent(conn):
    ingest_file(conn, SAMPLE, locale_hint="mdy")
    first = count(conn)
    stats = ingest_file(conn, SAMPLE, locale_hint="mdy", from_start=True)
    assert count(conn) == first
    assert stats.rows_inserted == 0
    assert stats.rows_duplicate == stats.entries_seen


def test_resume_skips_already_read_bytes(conn):
    ingest_file(conn, SAMPLE, locale_hint="mdy")
    stats = ingest_file(conn, SAMPLE, locale_hint="mdy")
    assert stats.bytes_read == 0
    assert stats.entries_seen == 0


def test_appended_content_is_picked_up(conn, tmp_path):
    log = tmp_path / "Player.log"
    log.write_text('{"a": 1}\r\n', newline="")
    ingest_file(conn, log)
    before = count(conn)
    with log.open("a", newline="") as fh:
        fh.write('{"b": 2}\r\n')
    stats = ingest_file(conn, log)
    assert stats.rows_inserted == 1
    assert count(conn) == before + 1


def test_truncation_detected_and_reread(conn, tmp_path):
    log = tmp_path / "Player.log"
    log.write_text('{"a": 1}\r\n{"b": 2}\r\n', newline="")
    ingest_file(conn, log)
    # Arena wipes the log on launch and starts a new session
    log.write_text('{"c": 3}\r\n', newline="")
    stats = ingest_file(conn, log)
    assert stats.truncation_detected
    assert stats.rows_inserted == 1


def test_partial_trailing_line_deferred(conn, tmp_path):
    log = tmp_path / "Player.log"
    log.write_text('{"a": 1}\r\n{"b": 2', newline="")  # game is mid-write
    stats = ingest_file(conn, log)
    assert stats.rows_inserted == 1
    with log.open("a", newline="") as fh:
        fh.write('}\r\n')
    stats = ingest_file(conn, log)
    assert stats.rows_inserted == 1  # the deferred line, now complete


def test_bare_cr_line_endings_do_not_stop_ingestion(conn, tmp_path):
    # Arena's log mixes CRLF with bare CR; a "\n"-only terminator check aborts
    # ingestion at the first bare-CR line.
    log = tmp_path / "Player.log"
    log.write_text('{"a": 1}\r{"b": 2}\r\n{"c": 3}\r\n', newline="")
    stats = ingest_file(conn, log)
    assert stats.rows_inserted == 3


# --- carry state, held-back entries, byte-exactness --------------------------


def _rows(conn) -> set[tuple]:
    return {
        tuple(row)
        for row in conn.execute(
            "SELECT digest, logged_at, kind, label, payload FROM raw_events"
        ).fetchall()
    }


@pytest.fixture(scope="module")
def single_pass_rows(tmp_path_factory):
    """Every row a single, uninterrupted read of SAMPLE produces.

    The reference the split-anywhere test below checks every incremental
    split against. A separate database from the per-test ``conn`` fixture,
    since this one is built once and reused across every parametrized case.
    """
    c = open_database(tmp_path_factory.mktemp("single-pass") / "t.db")
    ingest_file(c, SAMPLE, locale_hint="mdy")
    rows = _rows(c)
    c.close()
    return rows


# Cumulative byte offset after each of the fixture's 28 lines (fixture_peek.py
# index: 6 entries, sample_player.log). Splitting the file at each of these
# offsets and feeding it to ingest_file in two calls must produce exactly the
# rows a single, uninterrupted read does -- this is what pins the carry state,
# the checkpoint and the held-back entry together, all at once.
#
# Two split offsets land mid-entry, by construction:
#   - after line 5 (byte 388): between the GraphGetGraphState response's
#     header ("<== GraphGetGraphState(...)", line 5) and its single-line
#     payload (line 6) -- confirmed with fixture_peek.py show --entry 1.
#   - after lines 11-26 (bytes 8869-9450): inside entry 4's multi-line
#     ClientToGremessage payload, which opens on line 11 and does not close
#     until line 27 -- confirmed with fixture_peek.py show --entry 4.
_FIXTURE_LINES = SAMPLE.read_bytes().splitlines(keepends=True)
_SPLIT_OFFSETS = []
_cumulative = 0
for _line in _FIXTURE_LINES:
    _cumulative += len(_line)
    _SPLIT_OFFSETS.append(_cumulative)


@pytest.mark.parametrize("split_at", _SPLIT_OFFSETS)
def test_split_anywhere_equals_single_pass(conn, tmp_path, split_at, single_pass_rows):
    data = SAMPLE.read_bytes()
    log = tmp_path / "Player.log"
    log.write_bytes(data[:split_at])
    ingest_file(conn, log, locale_hint="mdy")
    with log.open("ab") as fh:
        fh.write(data[split_at:])
    ingest_file(conn, log, locale_hint="mdy")
    assert _rows(conn) == single_pass_rows


def test_truncation_resets_carry_state(conn, tmp_path):
    """A request has no timestamp of its own and inherits the most recent
    header's -- carry_ts/carry_context must not survive a truncation, or a
    request in the new (wiped) file inherits a timestamp from a session that
    no longer exists."""
    log = tmp_path / "Player.log"
    log.write_text(
        "[UnityCrossThreadLogger]8/13/2026 2:40:28 PM\r\n"
        '[UnityCrossThreadLogger]==> First {"id": "1"}\r\n',
        newline="",
    )
    ingest_file(conn, log, locale_hint="mdy")
    first = conn.execute(
        "SELECT logged_at FROM raw_events WHERE label = 'First'"
    ).fetchone()
    assert first["logged_at"] == "2026-08-13T14:40:28"

    # Arena wipes Player.log on launch: a smaller file, and this time no
    # header precedes the request at all.
    log.write_text('[UnityCrossThreadLogger]==> Second {"id": "2"}\r\n', newline="")
    stats = ingest_file(conn, log, locale_hint="mdy")
    assert stats.truncation_detected
    second = conn.execute(
        "SELECT logged_at FROM raw_events WHERE label = 'Second'"
    ).fetchone()
    assert second["logged_at"] is None  # not inherited from the wiped session


def test_byte_exact_offset_survives_invalid_utf8(conn, tmp_path):
    """offset used to advance by len(line.encode("utf-8", errors="replace"))
    on an already-decoded line: U+FFFD (the replacement character) re-encodes
    to 3 bytes, so a single invalid input byte drifts the offset and the next
    seek lands mid-line. Binary reading advances by the raw byte count
    instead, so a real entry appended right after survives intact.
    """
    # Line 3 of the fixture (fixture_peek.py index: entry 0, kind=request,
    # label=GraphGetGraphState) -- a real, complete raw line, prefix and all.
    real_entry_line = SAMPLE.read_bytes().splitlines(keepends=True)[2]

    log = tmp_path / "Player.log"
    log.write_bytes(b'{"noise": "\xff"}\r\n')  # one invalid UTF-8 byte, line complete
    stats = ingest_file(conn, log)
    assert stats.rows_inserted == 1

    with log.open("ab") as fh:
        fh.write(real_entry_line)
    stats = ingest_file(conn, log)
    assert stats.rows_inserted == 1
    row = conn.execute(
        "SELECT kind, label FROM raw_events WHERE kind = 'request'"
    ).fetchone()
    assert row["label"] == "GraphGetGraphState"  # read intact, not garbled by drift


def test_chunk_boundary_does_not_split_a_crlf_terminator(conn, tmp_path, monkeypatch):
    # Sized so the first chunk ends exactly on the line's trailing "\r": the
    # "\n" that completes the terminator only arrives in the next chunk.
    monkeypatch.setattr("sensei_top.reader.ingest._CHUNK_BYTES", len('{"a": 1}\r'))
    log = tmp_path / "Player.log"
    log.write_bytes(b'{"a": 1}\r\n{"b": 2}\r\n')
    stats = ingest_file(conn, log)
    assert stats.rows_inserted == 2
    payloads = {row[0] for row in conn.execute("SELECT payload FROM raw_events")}
    assert payloads == {'{"a": 1}', '{"b": 2}'}


def test_pending_cap_gives_up_on_an_entry_that_never_closes(conn, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("sensei_top.reader.ingest.MAX_PENDING_BYTES", 20)
    log = tmp_path / "Player.log"
    unclosed = '{"a": "' + "x" * 40 + '"\r\n'  # opening brace never balanced
    log.write_text(unclosed, newline="")
    with caplog.at_level(logging.WARNING):
        stats = ingest_file(conn, log)
    assert stats.rows_inserted == 0  # never emitted half-parsed
    assert stats.bytes_read == len(unclosed.encode())
    assert any("exceeded" in r.message for r in caplog.records)

    # A later, well-formed entry reads normally -- proof the offset moved
    # past the abandoned one instead of holding it back forever, which would
    # make every future poll re-read an ever-growing tail.
    with log.open("a", newline="") as fh:
        fh.write('{"b": 2}\r\n')
    stats = ingest_file(conn, log)
    assert stats.rows_inserted == 1
    assert conn.execute("SELECT payload FROM raw_events").fetchone()[0] == '{"b": 2}'


def test_previous_log_path_naming():
    assert previous_log_path("/x/Player.log").name == "Player-prev.log"


def test_recovery_reads_prev_then_current(conn, tmp_path):
    (tmp_path / "Player-prev.log").write_text('{"old": 1}\r\n', newline="")
    (tmp_path / "Player.log").write_text('{"new": 1}\r\n', newline="")
    results = ingest_with_recovery(conn, tmp_path / "Player.log")
    assert set(results) == {"Player-prev.log", "Player.log"}
    assert count(conn) == 2


def test_recovery_does_not_duplicate_rotated_content(conn, tmp_path):
    """The live log of session 1 becomes Player-prev.log in session 2."""
    live = tmp_path / "Player.log"
    live.write_text('{"session": 1}\r\n', newline="")
    ingest_file(conn, live)
    assert count(conn) == 1
    live.rename(tmp_path / "Player-prev.log")          # Arena rotates on launch
    live.write_text('{"session": 2}\r\n', newline="")  # fresh log
    ingest_with_recovery(conn, live)
    assert count(conn) == 2  # not 3: the rotated content is recognised


def test_shared_content_dedups_when_the_two_files_disagree_on_line_numbers(conn, tmp_path):
    """The case the rotation test above missed, because it put the shared line
    at line 1 of both files.

    Rotation is a snapshot, not a split: Player-prev.log keeps a different
    amount of preamble than the Player.log it was cut from, so a shared event
    sits at a different line in each. Keying identity on that position split
    3,842 shared entries into two rows apiece in a real pair of logs — and
    because matches/games/turns all overwrite by natural key, the only place it
    surfaced was card_events, which appends.
    """
    shared = '{"shared": "event"}\r\n'
    prev = tmp_path / "Player-prev.log"
    prev.write_text('{"preamble": 1}\r\n{"preamble": 2}\r\n' + shared, newline="")
    live = tmp_path / "Player.log"
    live.write_text(shared, newline="")  # same event, now on line 1

    ingest_file(conn, prev)
    ingest_file(conn, live)
    assert count(conn) == 3  # two preamble lines plus one shared event, not 4


def test_an_identical_entry_repeated_within_one_file_stays_distinct(conn, tmp_path):
    """The property the line number used to carry, now carried by the ordinal:
    two byte-identical polls are two events, not one."""
    log = tmp_path / "Player.log"
    log.write_text('{"poll": 1}\r\n{"poll": 1}\r\n', newline="")
    ingest_file(conn, log)
    assert count(conn) == 2


def test_missing_file_is_not_an_error(conn, tmp_path):
    stats = ingest_file(conn, tmp_path / "nope.log")
    assert stats.entries_seen == 0


def test_watch_bounded_polls(conn, tmp_path):
    log = tmp_path / "Player.log"
    log.write_text('{"a": 1}\r\n', newline="")
    results = list(watch(conn, log, interval=0, max_polls=2))
    assert len(results) == 1  # second pass finds nothing new
    assert count(conn) == 1


# --- default log path discovery ---------------------------------------------


def test_env_var_takes_priority_over_everything(monkeypatch, tmp_path):
    explicit = tmp_path / "Custom.log"
    explicit.write_text("")
    monkeypatch.setenv("MTGA_LOG", str(explicit))
    assert default_log_path() == explicit


def test_finds_the_log_in_a_non_default_steam_library(monkeypatch, steam_libraries):
    """Regression: MTGA installed under a second Steam library (a separate
    drive registered in libraryfolders.vdf) must still be found. Only the
    default Steam data directories were searched before this test existed."""
    monkeypatch.delenv("MTGA_LOG", raising=False)
    default_steam, other_library = steam_libraries

    log_path = other_library / _STEAM_COMPATDATA_RELATIVE
    log_path.parent.mkdir(parents=True)
    log_path.write_text("")

    monkeypatch.setattr("sensei_top.steam.STEAM_DATA_DIRS", (default_steam,))
    assert default_log_path() == log_path


def test_no_plausible_location_returns_none(tmp_path, monkeypatch):
    monkeypatch.delenv("MTGA_LOG", raising=False)
    monkeypatch.setattr("sensei_top.steam.STEAM_DATA_DIRS", (tmp_path / "nope",))
    monkeypatch.setattr("sensei_top.reader.ingest.Path.home", staticmethod(lambda: tmp_path))
    assert default_log_path() is None
