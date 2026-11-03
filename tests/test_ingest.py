"""Ingester tests: digest semantics, resume, truncation, rotation recovery."""

import inspect
import json
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sensei_top import db, steam
from sensei_top.cli import build_parser
from sensei_top.db import open_database
from sensei_top.live import LiveIngester
from sensei_top.reader import dates, segmenter
from sensei_top.reader.ingest import (
    compute_digest,
    default_log_path,
    found_log_paths,
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
    """Advancing the offset by len(line.encode("utf-8", errors="replace"))
    on an already-decoded line would drift it: U+FFFD (the replacement character) re-encodes
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
    """The ordinal keeps byte-identical entries apart: two byte-identical
    polls are two events, not one."""
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


# --- day/month order under --locale auto, and the stored header ------------

# Both captured on 2026-10-06. A tracked fixture's own mtime is
# checkout time, not data, so neither is ever read under auto in place: each
# test reads a copy whose last write it sets. The afternoon of the capture day
# is a last write whose week holds every captured stamp's real date; neither
# reading of a captured stamp falls in the week before 2026-12-01.
HEADER_LANGUAGES = FIXTURES / "header_languages.log"
HEADER_RELAUNCH = FIXTURES / "header_relaunch.log"
CAPTURE_DAY = "2026-10-06"
CAPTURE_AFTERNOON = datetime(2026, 10, 6, 15, 0)
STALE = datetime(2026, 12, 1, 15, 0)
_DOTNET_EPOCH = datetime(1, 1, 1)


@pytest.fixture(autouse=True)
def _unwarned(monkeypatch):
    """dates.py warns once per process per file and shape; every test starts
    unwarned."""
    monkeypatch.setattr(dates, "_warned_unsettled", set())
    monkeypatch.setattr(dates, "_warned_contradicted", set())


def _touch(path: Path, last_write: datetime) -> None:
    when = last_write.timestamp()   # naive: local time, as the header is
    os.utime(path, (when, when))


def _copy(fixture: Path, directory: Path, last_write: datetime) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    copy = directory / fixture.name
    shutil.copyfile(fixture, copy)
    _touch(copy, last_write)
    return copy


def _stored(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT kind, label, logged_at, header, payload FROM raw_events ORDER BY id"
    ).fetchall()


def _learned(conn) -> dict[str, tuple[str, str, str]]:
    return {
        row["shape"]: (row["date_order"], row["settled_by"], row["source_file"])
        for row in conn.execute("SELECT * FROM header_date_order")
    }


def _dates_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == dates.__name__]


def _payload_times(payloads: list[str]) -> list[str]:
    """Each entry's local time to the second, read from its own payload: a
    DeckUpsertDeckV3 response's LastPlayed is local time with its offset,
    written the second its header was; a ClientToGreuimessage's timestamp is
    .NET ticks (100 ns since 0001-01-01) in UTC, put in local time by the
    offset of the response before it."""
    times = []
    offset = None
    for payload in payloads:
        body = json.loads(payload)
        if "Attributes" in body:
            raw = next(a["value"] for a in body["Attributes"] if a["name"] == "LastPlayed")
            played = datetime.fromisoformat(json.loads(raw))
            offset = played.utcoffset()
            local = played.replace(tzinfo=None)
        else:
            assert offset is not None
            local = _DOTNET_EPOCH + timedelta(microseconds=int(body["timestamp"]) // 10) + offset
        times.append(local.replace(microsecond=0).isoformat())
    return times


def test_auto_dates_every_language_at_its_payloads_time_in_one_read(conn, tmp_path):
    stats = ingest_file(
        conn, _copy(HEADER_LANGUAGES, tmp_path, CAPTURE_AFTERNOON), locale_hint="auto"
    )
    rows = _stored(conn)
    assert stats.rows_inserted == len(rows) == 13
    english, languages = rows[0], rows[1:]
    assert [r["logged_at"] for r in languages] == _payload_times(
        [r["payload"] for r in languages]
    )
    # The English response ({"MatchesV3": []}) carries no time of its own:
    # its stamp is "10/6/2026 2:37:04 PM", its date the session's, which
    # the Japanese response's LastPlayed fixes.
    session_date = _payload_times([languages[0]["payload"]])[0][:10]
    assert english["label"] == "EventGetActiveMatches"
    assert english["logged_at"] == f"{session_date}T14:37:04"


@pytest.mark.parametrize("locale_hint", ["auto", "mdy", "dmy"])
def test_raw_events_header_holds_each_stamp_as_written(conn, tmp_path, locale_hint):
    """Kept whatever the order, so a date misread today stays
    re-derivable."""
    ingest_file(
        conn, _copy(HEADER_LANGUAGES, tmp_path, CAPTURE_AFTERNOON), locale_hint=locale_hint
    )
    headers = [r["header"] for r in _stored(conn)]
    assert headers[0] == "10/6/2026 2:37:04 PM"
    # One response each in four of the fixture's languages, its header as written
    assert [headers[i] for i in (1, 3, 5, 7)] == [
        "2026/10/06 14:37:42",
        "2026-10-06 오후 2:38:24",
        "06/10/2026 14:39:17",
        "06.10.2026 14:39:58",
    ]
    assert all(headers)


def test_auto_on_the_relaunch_capture(conn, tmp_path):
    ingest_file(conn, _copy(HEADER_RELAUNCH, tmp_path, CAPTURE_AFTERNOON), locale_hint="auto")
    request, *responses = _stored(conn)
    assert (request["kind"], request["label"]) == ("request", "GraphGetGraphState")
    assert (request["logged_at"], request["header"]) == (None, None)
    # The relaunch came up in Portuguese, day first, on the capture day. Its
    # payloads carry no time, so the time is the one each stamp shows.
    assert [r["header"].split()[-1] for r in responses] == ["14:42:30", "14:42:37"]
    assert [r["logged_at"] for r in responses] == [
        f"{CAPTURE_DAY}T14:42:30",
        f"{CAPTURE_DAY}T14:42:37",
    ]
    assert {shape: order for shape, (order, _, _) in _learned(conn).items()} == {
        "slash-24h": "dmy"
    }


def _rows_with_header(conn) -> set[tuple]:
    return {
        tuple(row)
        for row in conn.execute(
            "SELECT digest, logged_at, kind, label, payload, header FROM raw_events"
        ).fetchall()
    }


@pytest.fixture(scope="module")
def migrated(tmp_path_factory) -> Path:
    """An empty database at the current schema, copied by each split case:
    the fixture has over a hundred lines, and migrating a fresh file for each
    would cost more than the reads it checks."""
    path = tmp_path_factory.mktemp("migrated") / "t.db"
    open_database(path).close()
    return path


@pytest.fixture(scope="module")
def languages_single_pass(tmp_path_factory):
    directory = tmp_path_factory.mktemp("languages-single-pass")
    c = open_database(directory / "t.db")
    ingest_file(c, _copy(HEADER_LANGUAGES, directory, CAPTURE_AFTERNOON), locale_hint="auto")
    rows = _rows_with_header(c)
    c.close()
    return rows


_LANGUAGES_SPLIT_OFFSETS = []
_cumulative = 0
for _line in HEADER_LANGUAGES.read_bytes().splitlines(keepends=True):
    _cumulative += len(_line)
    _LANGUAGES_SPLIT_OFFSETS.append(_cumulative)


@pytest.mark.parametrize("split_at", _LANGUAGES_SPLIT_OFFSETS)
def test_auto_split_anywhere_equals_single_pass(
    tmp_path, migrated, split_at, languages_single_pass
):
    """Every line boundary, so a poll ends right after each header as well as
    mid-entry: the time, the context and the stamp all carry, and the order a
    first poll learned is read back by the second."""
    shutil.copyfile(migrated, tmp_path / "t.db")
    conn = db.connect(tmp_path / "t.db")
    data = HEADER_LANGUAGES.read_bytes()
    log = tmp_path / "Player.log"
    log.write_bytes(data[:split_at])
    _touch(log, CAPTURE_AFTERNOON)
    ingest_file(conn, log, locale_hint="auto")
    with log.open("ab") as fh:
        fh.write(data[split_at:])
    _touch(log, CAPTURE_AFTERNOON)
    ingest_file(conn, log, locale_hint="auto")
    try:
        assert _rows_with_header(conn) == languages_single_pass
    finally:
        conn.close()


def test_carry_header_crosses_a_poll_boundary(conn, tmp_path):
    stamp = "06/10/2026 14:39:30"
    log = tmp_path / "Player.log"
    log.write_text(
        f"[UnityCrossThreadLogger]{stamp}: SELFCLIENTID0001 to Match: ClientToGreuimessage\r\n",
        newline="",
    )
    _touch(log, CAPTURE_AFTERNOON)
    ingest_file(conn, log, locale_hint="auto")
    assert count(conn) == 0
    carry = tuple(
        conn.execute("SELECT carry_ts, carry_context, carry_header FROM ingest_state").fetchone()
    )
    assert carry == ("2026-10-06T14:39:30", "ClientToGreuimessage", stamp)

    with log.open("a", newline="") as fh:
        fh.write('{"requestId": 5}\r\n')
    _touch(log, CAPTURE_AFTERNOON)
    ingest_file(conn, log, locale_hint="auto")
    row = conn.execute("SELECT logged_at, label, header FROM raw_events").fetchone()
    assert tuple(row) == carry


def test_truncation_resets_carry_header(conn, tmp_path):
    log = tmp_path / "Player.log"
    log.write_text("[UnityCrossThreadLogger]8/13/2026 2:40:28 PM\r\n", newline="")
    ingest_file(conn, log, locale_hint="mdy")
    # Arena wipes Player.log on launch: a smaller file, no header before the
    # request this time.
    log.write_text('[UnityCrossThreadLogger]==> A {"id": "2"}\r\n', newline="")
    assert ingest_file(conn, log, locale_hint="mdy").truncation_detected
    row = conn.execute("SELECT logged_at, header FROM raw_events").fetchone()
    assert tuple(row) == (None, None)


def test_a_stale_last_write_with_nothing_learned_stores_none_and_warns(conn, tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        ingest_file(conn, _copy(HEADER_LANGUAGES, tmp_path, STALE), locale_hint="auto")
    rows = _stored(conn)
    year_first, others = rows[1:5], [rows[0], *rows[5:]]
    assert [r["logged_at"] for r in year_first] == _payload_times(
        [r["payload"] for r in year_first]
    )
    assert [r["logged_at"] for r in others] == [None] * 9
    assert all(r["header"] for r in rows)   # kept, to re-derive from later
    assert _learned(conn) == {}
    tail = (
        "is not within the week before the file's last write (2026-12-01 15:00), and "
        "this database has not learned the order of {shape} headers; its entries are "
        "stored with no time"
    )
    # Once per shape: Italian and French share Spanish's.
    assert _dates_warnings(caplog) == [
        f"header_languages.log: header {stamp!r} reads as a date either way, "
        + tail.format(shape=shape)
        for stamp, shape in (
            ("10/6/2026 2:37:04 PM", "slash-12h"),
            ("06/10/2026 14:39:17", "slash-24h"),
            ("06.10.2026 14:39:58", "dot-24h"),
        )
    ]


def test_a_stale_last_write_uses_the_order_an_earlier_read_learned(conn, tmp_path, caplog):
    earlier = _copy(HEADER_LANGUAGES, tmp_path / "earlier", CAPTURE_AFTERNOON)
    ingest_file(conn, earlier, locale_hint="auto")
    # Steps 2 and 4 teach, so the year-first shapes teach nothing; each row
    # names the first stamp of its shape in the fixture.
    assert _learned(conn) == {
        "slash-12h": ("mdy", "10/6/2026 2:37:04 PM", "header_languages.log"),
        "slash-24h": ("dmy", "06/10/2026 14:39:17", "header_languages.log"),
        "dot-24h": ("dmy", "06.10.2026 14:39:58", "header_languages.log"),
    }
    taught = _learned(conn)

    later = _copy(HEADER_LANGUAGES, tmp_path / "later", STALE)
    with caplog.at_level(logging.WARNING):
        stats = ingest_file(conn, later, locale_hint="auto")
    # Dated as the earlier read dated them, so every entry is already stored.
    assert stats.rows_duplicate == stats.entries_seen == 13
    assert _dates_warnings(caplog) == []
    assert _learned(conn) == taught


@pytest.mark.parametrize(
    ("locale_hint", "consults"), [("auto", True), ("mdy", False), ("dmy", False)]
)
def test_an_override_neither_reads_nor_writes_header_date_order(
    conn, tmp_path, locale_hint, consults
):
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        ingest_file(
            conn, _copy(HEADER_LANGUAGES, tmp_path, CAPTURE_AFTERNOON), locale_hint=locale_hint
        )
    finally:
        conn.set_trace_callback(None)
    assert any("header_date_order" in s for s in statements) is consults
    assert bool(_learned(conn)) is consults


def test_what_a_read_learns_rolls_back_with_its_rows(conn, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("sensei_top.reader.ingest._write_state", fail)
    with pytest.raises(RuntimeError):
        ingest_file(
            conn, _copy(HEADER_LANGUAGES, tmp_path, CAPTURE_AFTERNOON), locale_hint="auto"
        )
    assert count(conn) == 0
    assert _learned(conn) == {}


@pytest.mark.parametrize("command", ["ingest", "serve"])
def test_the_cli_defaults_to_auto(command):
    parser = build_parser()
    assert parser.parse_args([command]).locale == "auto"
    assert parser.parse_args([command, "--locale", "dmy"]).locale == "dmy"


def test_the_library_keeps_no_order_by_default():
    for function in (ingest_file, ingest_with_recovery, watch):
        assert inspect.signature(function).parameters["locale_hint"].default is None


def test_migration_062_adds_nullable_header_columns_and_the_learned_order_table(tmp_path):
    conn = db.connect(tmp_path / "at_61.db")
    for version, migration_path in db.discover_migrations():
        if version > 61:
            break
        conn.execute("BEGIN")
        for statement in db._split_statements(migration_path.read_text(encoding="utf-8")):
            conn.execute(statement)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.execute("COMMIT")
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload) "
        "VALUES ('before', 'Player.log', '2026-10-06T14:37:04', 'response', "
        "'EventGetActiveMatches', '{}')"
    )
    conn.execute(
        "INSERT INTO ingest_state (source_path, carry_ts, carry_context) "
        "VALUES ('/logs/Player.log', '2026-10-06T14:37:04', 'ClientToGreuimessage')"
    )
    conn.commit()

    assert 62 in db.migrate(conn)
    # No backfill (rule 4): what was stored before keeps no header.
    assert conn.execute("SELECT header FROM raw_events").fetchone()[0] is None
    assert conn.execute("SELECT carry_header FROM ingest_state").fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM header_date_order").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO header_date_order (shape, date_order, settled_by, source_file, "
            "settled_at) VALUES ('slash-24h', 'ymd', 's', 'Player.log', '2026-10-06T17:00:00Z')"
        )
    conn.close()


# --- the same entry read under a second date ---------------------------------

# Stamps in the shape of header_languages.log's English line. The ambiguous one
# is that line's own: October 6th month first, June 10th day first. The other
# has a 25, so only month first reads as a date.
AMBIGUOUS = "10/6/2026 2:37:04 PM"
AMBIGUOUS_MDY = "2026-10-06T14:37:04"
AMBIGUOUS_DMY = "2026-06-10T14:37:04"
ONE_READING = "10/25/2026 2:37:04 PM"
ONE_READING_MDY = "2026-10-25T14:37:04"


def _write_log(path: Path, *sections: tuple[str, str]) -> Path:
    """One header and one bare payload per ``(stamp, payload)``."""
    path.write_text(
        "".join(
            f"[UnityCrossThreadLogger]{stamp}: Match to X: GreToClientEvent\r\n{payload}\r\n"
            for stamp, payload in sections
        ),
        newline="",
        encoding="utf-8",
    )
    return path


def _ingest_undated(conn, log: Path) -> None:
    """Read ``log`` under auto with its last write far from any reading and
    nothing learned: the header's last step, no time."""
    _touch(log, STALE)
    ingest_file(conn, log, locale_hint="auto", from_start=True)


def _learn_month_first(conn, directory: Path) -> None:
    teacher = _write_log(directory / "teacher.log", (ONE_READING, '{"teacher": 1}'))
    _touch(teacher, STALE)
    ingest_file(conn, teacher, locale_hint="auto")
    conn.execute("DELETE FROM raw_events WHERE source_file = 'teacher.log'")


def _reread(conn, log: Path, locale_hint: str | None = "auto"):
    _touch(log, STALE)
    return ingest_file(conn, log, locale_hint=locale_hint, from_start=True)


def _identity(conn) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT id, digest, logged_at, header, payload FROM raw_events ORDER BY id"
        )
    ]


def _digest(payload: str, logged_at: str | None, occurrence: int = 0) -> str:
    return compute_digest(
        LogEntry(kind=EntryKind.EVENT, payload=payload, logged_at=logged_at), occurrence
    )


def test_a_reread_dates_an_undated_row_in_place(conn, tmp_path):
    payload = '{"a": 1}'
    year_first = ("2026/10/06 14:37:42", '{"b": 2}')
    log = _write_log(tmp_path / "Player.log", (AMBIGUOUS, payload), year_first)
    _ingest_undated(conn, log)
    (first_id, _, logged_at, header, _), later = _identity(conn)
    assert (logged_at, header) == (None, AMBIGUOUS)

    _learn_month_first(conn, tmp_path)
    stats = _reread(conn, log)
    rows = _identity(conn)
    assert rows == [
        (first_id, _digest(payload, AMBIGUOUS_MDY), AMBIGUOUS_MDY, AMBIGUOUS, payload),
        later,
    ]
    assert (stats.rows_dated, stats.rows_inserted, stats.rows_duplicate) == (1, 0, 2)
    assert "1 dated" in str(stats)

    again = _reread(conn, log)
    assert _identity(conn) == rows
    assert (again.rows_dated, again.rows_inserted) == (0, 0)
    assert "dated" not in str(again)


def test_two_identical_payloads_under_one_undated_stamp_stay_two_rows(conn, tmp_path):
    payload = '{"a": 1}'
    log = _write_log(tmp_path / "Player.log", (AMBIGUOUS, payload), (AMBIGUOUS, payload))
    _ingest_undated(conn, log)
    ids = [row[0] for row in _identity(conn)]
    assert len(ids) == 2

    _learn_month_first(conn, tmp_path)
    assert _reread(conn, log).rows_dated == 2
    assert _identity(conn) == [
        (ids[0], _digest(payload, AMBIGUOUS_MDY, 0), AMBIGUOUS_MDY, AMBIGUOUS, payload),
        (ids[1], _digest(payload, AMBIGUOUS_MDY, 1), AMBIGUOUS_MDY, AMBIGUOUS, payload),
    ]


def test_identical_payloads_under_two_undated_stamps_each_find_their_own(conn, tmp_path):
    payload = '{"a": 1}'
    later_stamp = "10/7/2026 2:37:05 PM"
    log = _write_log(tmp_path / "Player.log", (AMBIGUOUS, payload), (later_stamp, payload))
    _ingest_undated(conn, log)
    ids = [row[0] for row in _identity(conn)]

    _learn_month_first(conn, tmp_path)
    assert _reread(conn, log).rows_dated == 2
    assert [row[0] for row in _identity(conn)] == ids
    assert [(row[2], row[3]) for row in _identity(conn)] == [
        (AMBIGUOUS_MDY, AMBIGUOUS),
        ("2026-10-07T14:37:05", later_stamp),
    ]


def test_a_second_order_keeps_the_first_date(conn, tmp_path):
    log = _write_log(tmp_path / "Player.log", (AMBIGUOUS, '{"a": 1}'))
    ingest_file(conn, log, locale_hint="mdy")
    stored = _identity(conn)
    stats = _reread(conn, log, "dmy")
    assert _identity(conn) == stored
    assert stored[0][2] == AMBIGUOUS_MDY
    assert (stats.rows_inserted, stats.rows_duplicate, stats.rows_dated) == (0, 1, 0)


@pytest.mark.parametrize(
    ("stamp", "later_hint"),
    [(ONE_READING, "dmy"), (AMBIGUOUS, None)],
    ids=["no-real-reading", "no-order"],
)
def test_a_stored_date_gets_no_undated_twin(conn, tmp_path, stamp, later_hint):
    log = _write_log(tmp_path / "Player.log", (stamp, '{"a": 1}'))
    ingest_file(conn, log, locale_hint="mdy")
    stored = _identity(conn)
    assert stored[0][2] is not None
    stats = _reread(conn, log, later_hint)
    assert _identity(conn) == stored
    assert (stats.rows_inserted, stats.rows_duplicate) == (0, 1)


def test_an_order_with_no_real_reading_is_dated_by_the_one_that_has_it(conn, tmp_path):
    payload = '{"a": 1}'
    log = _write_log(tmp_path / "Player.log", (ONE_READING, payload))
    ingest_file(conn, log, locale_hint="dmy")
    ((row_id, _, logged_at, _, _),) = _identity(conn)
    assert logged_at is None
    assert _reread(conn, log, "mdy").rows_dated == 1
    assert _identity(conn) == [
        (row_id, _digest(payload, ONE_READING_MDY), ONE_READING_MDY, ONE_READING, payload)
    ]


@pytest.mark.parametrize(
    ("dated_stamp", "undated_stamp", "hint", "date"),
    [
        (AMBIGUOUS, ONE_READING, "dmy", AMBIGUOUS_DMY),
        # A 25 settles the first under auto. The second is German's shape, which
        # the first teaches nothing about, and neither of its readings is near
        # the stale last write.
        (ONE_READING, "06.10.2026 14:39:58", "auto", ONE_READING_MDY),
    ],
    ids=["dmy", "auto"],
)
def test_dating_a_row_does_not_free_its_digest_for_the_next_undated_entry(
    conn, tmp_path, dated_stamp, undated_stamp, hint, date
):
    """Both entries digest under one undated count, so dating the first frees
    occurrence 0, which the second, still undated, then counts to."""
    payload = '{"a": 1}'
    log = _write_log(tmp_path / "Player.log", (dated_stamp, payload), (undated_stamp, payload))
    ingest_file(conn, log)
    (first_id, *_), second = _identity(conn)
    assert second[2] is None

    stats = _reread(conn, log, hint)
    rows = _identity(conn)
    assert rows == [
        (first_id, _digest(payload, date), date, dated_stamp, payload),
        second,
    ]
    assert (stats.rows_dated, stats.rows_inserted, stats.rows_duplicate) == (1, 0, 2)

    again = _reread(conn, log, hint)
    assert _identity(conn) == rows
    assert (again.rows_dated, again.rows_inserted) == (0, 0)


def test_a_year_first_stamp_has_nothing_to_compare(conn, tmp_path):
    log = _write_log(tmp_path / "Player.log", ("2026/10/06 14:37:42", '{"a": 1}'))
    ingest_file(conn, log, locale_hint="mdy")
    stored = _identity(conn)
    stats = _reread(conn, log, "dmy")
    assert _identity(conn) == stored
    assert (stats.rows_inserted, stats.rows_duplicate, stats.rows_dated) == (0, 1, 0)


def _store_legacy_twin(conn, payload: str, logged_at: str) -> None:
    """The dated row of a pair stored before a re-read could date in place."""
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, header) "
        "VALUES (?, 'Player.log', ?, 'event', 'GreToClientEvent', ?, ?)",
        (_digest(payload, logged_at), logged_at, payload, AMBIGUOUS),
    )


@pytest.mark.parametrize("hint", ["mdy", "dmy"], ids=["same-date", "other-reading"])
def test_a_legacy_twin_pair_is_left_alone(conn, tmp_path, hint):
    payload = '{"a": 1}'
    log = _write_log(tmp_path / "Player.log", (AMBIGUOUS, payload))
    _ingest_undated(conn, log)
    _store_legacy_twin(conn, payload, AMBIGUOUS_MDY)
    stored = _identity(conn)
    assert [row[2] for row in stored] == [None, AMBIGUOUS_MDY]

    stats = _reread(conn, log, hint)
    assert _identity(conn) == stored
    assert (stats.rows_inserted, stats.rows_duplicate, stats.rows_dated) == (0, 1, 0)


def test_a_reads_first_statement_is_a_write(conn, tmp_path):
    """A SELECT first takes a WAL snapshot, and the next write can then fail at
    once with SQLITE_BUSY (_segmenter's docstring)."""
    log = _write_log(tmp_path / "Player.log", (AMBIGUOUS, '{"a": 1}'))
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        ingest_file(conn, log, locale_hint="mdy")
    finally:
        conn.set_trace_callback(None)
    begin = statements.index("BEGIN")
    assert statements[begin + 1].split()[0] == "UPDATE"
    assert not any(s.split()[0] == "SELECT" for s in statements[begin + 1:])


def test_a_dated_row_marks_the_projection_dirty(tmp_path):
    log = _write_log(tmp_path / "Player.log", (AMBIGUOUS, '{"a": 1}'))
    live = LiveIngester(db_path=tmp_path / "live.db", log_path=log, locale_hint="mdy", interval=0)
    conn = open_database(live.db_path)
    try:
        _ingest_undated(conn, log)
        conn.execute("UPDATE ingest_state SET byte_offset = 0, last_size = 0, inode = NULL")
        assert live._dirty is False
        assert live.ingest_once(conn) == 1
        assert live._dirty is True
        assert conn.execute("SELECT logged_at FROM raw_events").fetchone()[0] == AMBIGUOUS_MDY
        assert live.stats.events_ingested == 0
    finally:
        conn.close()


def test_migration_070_indexes_the_undated_rows_of_an_existing_database(tmp_path):
    conn = db.connect(tmp_path / "at_69.db")
    for version, migration_path in db.discover_migrations():
        if version > 69:
            break
        conn.execute("BEGIN")
        for statement in db._split_statements(migration_path.read_text(encoding="utf-8")):
            conn.execute(statement)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.execute("COMMIT")
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload) "
        "VALUES ('before', 'Player.log', NULL, 'response', 'EventGetActiveMatches', '{}')"
    )
    conn.commit()

    assert 70 in db.migrate(conn)
    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM raw_events "
        "WHERE header = 's' AND logged_at IS NULL AND payload = 'p' ORDER BY id LIMIT 1"
    ).fetchall()
    assert any("idx_raw_events_undated_header" in row["detail"] for row in plan)
    # No backfill (rule 4): a row from before 062 keeps no header and no time.
    row = conn.execute("SELECT logged_at, header FROM raw_events").fetchone()
    assert tuple(row) == (None, None)
    conn.close()


# --- a summarized block at the end of a dead file ------------------------------

# SYNTHETIC, as tests/test_segmenter.py's: no real capture of this block exists.
_SUMMARIZED_TAIL = (
    "[UnityCrossThreadLogger]10/6/2026 2:37:04 PM: Match to X: GreToClientEvent\r\n"
    '{"before": 1}\r\n'
    "[Message summarized because one or more GameStateMessages exceeded the "
    "50 GameObject or 50 Annotation limit.]\r\n"
    "::: GameStateMessage\r\n"
    ":: GameObject Count = 61\r\n"
)
_SUMMARY_MARKER_OFFSET = _SUMMARIZED_TAIL.index("[Message summarized")


def _summary_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "summarized" in r.getMessage()]


def test_a_summarized_block_at_the_end_of_the_previous_log_warns_once(
    conn, tmp_path, caplog, monkeypatch
):
    monkeypatch.setattr(segmenter, "_warned_summaries", set())
    prev = tmp_path / "Player-prev.log"
    prev.write_text(_SUMMARIZED_TAIL, newline="")
    with caplog.at_level(logging.WARNING):
        ingest_with_recovery(conn, tmp_path / "Player.log", locale_hint="mdy")
        ingest_with_recovery(conn, tmp_path / "Player.log", locale_hint="mdy")
    warnings = _summary_warnings(caplog)
    assert len(warnings) == 1
    assert "GameObject Count = 61" in warnings[0]
    # What is stored is what a read without the flush stores: the entry before
    # the block, and an offset still held at the block's marker.
    assert [r["payload"] for r in _stored(conn)] == ['{"before": 1}']
    offset = conn.execute("SELECT byte_offset FROM ingest_state").fetchone()[0]
    assert offset == _SUMMARY_MARKER_OFFSET


def test_a_summarized_block_at_the_end_of_the_live_log_waits(conn, tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(segmenter, "_warned_summaries", set())
    log = tmp_path / "Player.log"
    log.write_text(_SUMMARIZED_TAIL, newline="")
    with caplog.at_level(logging.WARNING):
        ingest_with_recovery(conn, log, locale_hint="mdy")
    assert _summary_warnings(caplog) == []
    assert conn.execute("SELECT byte_offset FROM ingest_state").fetchone()[0] == (
        _SUMMARY_MARKER_OFFSET
    )


# --- default log path discovery ---------------------------------------------

_STEAM_COMPATDATA_RELATIVE = (
    f"steamapps/compatdata/{steam.MTGA_APP_ID}/pfx/drive_c/users/steamuser/"
    "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
)
_LOG_IN_PREFIX = "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"


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
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # a Windows runner's own profile
    monkeypatch.setattr("sensei_top.steam.STEAM_DATA_DIRS", (tmp_path / "nope",))
    monkeypatch.setattr("sensei_top.reader.ingest.Path.home", staticmethod(lambda: tmp_path))
    assert default_log_path() is None


def _windows_log(profile: Path) -> Path:
    log_path = profile / "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("")
    return log_path


def test_finds_the_log_under_the_windows_profile(monkeypatch, tmp_path):
    """Native Windows keeps the log under the user's profile whichever
    installer put Arena there; nothing looked there before."""
    monkeypatch.delenv("MTGA_LOG", raising=False)
    monkeypatch.setattr("sensei_top.steam.STEAM_DATA_DIRS", (tmp_path / "nope",))
    monkeypatch.setattr("sensei_top.reader.ingest.Path.home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    profile = tmp_path / "profile"
    monkeypatch.setenv("USERPROFILE", str(profile))
    log_path = _windows_log(profile)
    assert default_log_path() == log_path


def test_the_windows_profile_is_not_searched_elsewhere(monkeypatch, tmp_path):
    """The profile folder is a Windows one: off Windows a stray
    ``USERPROFILE`` must not name a log."""
    monkeypatch.delenv("MTGA_LOG", raising=False)
    monkeypatch.setattr("sensei_top.steam.STEAM_DATA_DIRS", (tmp_path / "nope",))
    monkeypatch.setattr("sensei_top.reader.ingest.Path.home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    profile = tmp_path / "profile"
    monkeypatch.setenv("USERPROFILE", str(profile))
    _windows_log(profile)
    assert default_log_path() is None


# --- Linux candidates: every Steam library and every Wine prefix -------------


def _linux_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "fakehome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("MTGA_LOG", raising=False)
    monkeypatch.delenv("WINEPREFIX", raising=False)
    return home


def _prefix_log(prefix: Path, user: str, mtime: float | None = None) -> Path:
    log_path = prefix / "drive_c/users" / user / _LOG_IN_PREFIX
    log_path.parent.mkdir(parents=True)
    log_path.write_text("")
    if mtime is not None:
        os.utime(log_path, (mtime, mtime))
    return log_path


def test_proton_prefix_with_a_user_other_than_steamuser(monkeypatch, tmp_path):
    """The Wine user is whatever folder sits under drive_c/users; a hard-coded
    name hid every prefix whose user was something else."""
    home = _linux_home(monkeypatch, tmp_path)
    prefix = home / ".local/share/Steam/steamapps/compatdata" / steam.MTGA_APP_ID / "pfx"
    log_path = _prefix_log(prefix, "someone")
    assert default_log_path() == log_path


def test_public_wine_user_is_skipped(monkeypatch, tmp_path):
    """Public is Windows' shared profile, never the player's."""
    home = _linux_home(monkeypatch, tmp_path)
    _prefix_log(home / ".wine", "Public")
    assert default_log_path() is None
    assert found_log_paths() == []


def test_a_newer_lutris_log_beats_a_stale_steam_one(monkeypatch, tmp_path):
    """A stale prefix must not shadow the one Arena wrote to last."""
    home = _linux_home(monkeypatch, tmp_path)
    steam_prefix = home / ".local/share/Steam/steamapps/compatdata" / steam.MTGA_APP_ID / "pfx"
    stale = _prefix_log(steam_prefix, "steamuser", mtime=1_000_000)
    lutris_prefix = tmp_path / "elsewhere/arena-prefix"
    fresh = _prefix_log(lutris_prefix, "me", mtime=2_000_000)
    games = Path(os.environ["XDG_CONFIG_HOME"]) / "lutris/games"
    games.mkdir(parents=True)
    (games / "arena.yml").write_text(f"game:\n  prefix: {lutris_prefix}\n")
    assert default_log_path() == fresh
    assert found_log_paths() == [fresh, stale]


def test_an_mtime_tie_keeps_candidate_order(monkeypatch, tmp_path):
    """Steam comes before Wine prefixes when nothing separates them."""
    home = _linux_home(monkeypatch, tmp_path)
    steam_prefix = home / ".local/share/Steam/steamapps/compatdata" / steam.MTGA_APP_ID / "pfx"
    first = _prefix_log(steam_prefix, "steamuser", mtime=1_500_000)
    second = _prefix_log(home / ".wine", "me", mtime=1_500_000)
    assert found_log_paths() == [first, second]


def test_the_same_prefix_reached_twice_counts_once(monkeypatch, tmp_path):
    """A symlinked root (as ~/.steam/steam is) must list its log once, under
    the first spelling, which the watcher keys its offset by."""
    home = _linux_home(monkeypatch, tmp_path)
    real = home / ".local/share/Steam"
    prefix = real / "steamapps/compatdata" / steam.MTGA_APP_ID / "pfx"
    log_path = _prefix_log(prefix, "steamuser")
    (home / ".steam").mkdir()
    (home / ".steam/steam").symlink_to(real)
    assert found_log_paths() == [home / ".steam/steam" / log_path.relative_to(real)]


def test_mtga_log_leads_whatever_its_mtime(monkeypatch, tmp_path):
    """An explicit $MTGA_LOG is a choice, not a candidate to out-age."""
    home = _linux_home(monkeypatch, tmp_path)
    prefix_log = _prefix_log(home / ".wine", "me", mtime=2_000_000)
    explicit = tmp_path / "Custom.log"
    explicit.write_text("")
    os.utime(explicit, (1_000_000, 1_000_000))
    monkeypatch.setenv("MTGA_LOG", str(explicit))
    assert found_log_paths() == [explicit, prefix_log]


def test_a_wine_user_without_a_log_is_skipped(monkeypatch, tmp_path):
    """A user folder that holds no Player.log (or one that vanished) must be
    skipped, never raise."""
    home = _linux_home(monkeypatch, tmp_path)
    (home / ".wine/drive_c/users/empty").mkdir(parents=True)
    kept = _prefix_log(home / ".wine", "kept", mtime=1_000_000)
    assert found_log_paths() == [kept]


def test_wineprefix_naming_the_proton_prefix_counts_once(monkeypatch, tmp_path):
    """The same prefix reached as a Steam library and as $WINEPREFIX is one
    log, listed under the Steam spelling (the first candidate)."""
    home = _linux_home(monkeypatch, tmp_path)
    prefix = home / ".local/share/Steam/steamapps/compatdata" / steam.MTGA_APP_ID / "pfx"
    log_path = _prefix_log(prefix, "steamuser")
    monkeypatch.setenv("WINEPREFIX", str(prefix))
    assert found_log_paths() == [log_path]
    assert default_log_path() == log_path


def test_the_debug_line_repeats_only_when_it_changes(monkeypatch, tmp_path, caplog):
    """The dashboard's heartbeat resolves the log every few seconds."""
    from sensei_top.reader import ingest

    home = _linux_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ingest, "_last_debug", None)
    _prefix_log(home / ".wine", "me")
    with caplog.at_level(logging.DEBUG, logger=ingest.log.name):
        default_log_path()
        default_log_path()
        assert len(caplog.records) == 1
        _prefix_log(home / ".wine", "other")
        default_log_path()
        assert len(caplog.records) == 2
        assert str(tmp_path) not in caplog.text
