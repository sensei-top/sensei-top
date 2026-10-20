"""The auto day/month order (reader/dates.py; docs/arena-log.md, "Timestamps").

Each step of the chain on stamps parsed from the five captured shapes, with a
fixed last write. Stamps named after a language are real headers from
tests/fixtures/header_languages.log; the rest are synthetic, built in a
captured shape. Every capture was made on 2026-10-06, so the afternoon of
that day is a last write whose week holds each captured stamp's real date,
and 2026-12-01 one whose week holds neither of its readings.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from sensei_top.db import open_database
from sensei_top.reader import dates
from sensei_top.reader.dates import auto_resolver
from sensei_top.reader.segmenter import HeaderStamp, parse_header_timestamp

ENGLISH = "10/6/2026 2:37:04 PM"        # slash-12h, month first
SPANISH = "06/10/2026 14:39:17"         # slash-24h, day first
GERMAN = "06.10.2026 14:39:58"          # dot-24h, day first
JAPANESE = "2026/10/06 14:37:42"        # ymd-slash-24h
KOREAN = "2026-10-06 오후 2:38:24"       # ymd-dash-ko

CAPTURE_AFTERNOON = datetime(2026, 10, 6, 15, 0)
STALE = datetime(2026, 12, 1, 15, 0)


@pytest.fixture(autouse=True)
def _unwarned(monkeypatch):
    """Both warnings fire once per process; every test starts unwarned."""
    monkeypatch.setattr(dates, "_warned_unsettled", set())
    monkeypatch.setattr(dates, "_warned_contradicted", set())


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def stamp(text: str) -> HeaderStamp:
    header = parse_header_timestamp(text)
    assert header is not None and header.parsed is not None
    return header.parsed


def learned(conn) -> dict[str, tuple[str, str, str]]:
    return {
        row["shape"]: (row["date_order"], row["settled_by"], row["source_file"])
        for row in conn.execute("SELECT * FROM header_date_order")
    }


def messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == dates.__name__]


# --- the chain, one step at a time ---------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [(JAPANESE, "2026-10-06T14:37:42"), (KOREAN, "2026-10-06T14:38:24")],
)
def test_step_1_a_year_first_stamp_reads_as_written_and_teaches_nothing(
    conn, caplog, text, expected
):
    """A year-first shape names its month: no window, no learned order needed,
    and nothing learned from it, since it says nothing about any other shape."""
    resolve = auto_resolver(conn, source_file="Player.log", last_write=STALE)
    with caplog.at_level(logging.WARNING):
        assert resolve(stamp(text)) == expected
    assert learned(conn) == {}
    assert messages(caplog) == []


@pytest.mark.parametrize(
    ("text", "shape", "order", "expected"),
    [
        ("13/10/2026 14:39:17", "slash-24h", "dmy", "2026-10-13T14:39:17"),
        ("13.10.2026 14:39:58", "dot-24h", "dmy", "2026-10-13T14:39:58"),
        ("10/13/2026 2:37:04 PM", "slash-12h", "mdy", "2026-10-13T14:37:04"),
    ],
)
def test_step_2_the_only_real_reading_is_taken_and_taught(conn, text, shape, order, expected):
    """A field above 12 can only be the day. Settled with a stale last write,
    so the window plays no part."""
    resolve = auto_resolver(conn, source_file="Player.log", last_write=STALE)
    assert resolve(stamp(text)) == expected
    assert learned(conn) == {shape: (order, text, "Player.log")}


def test_step_3_equal_fields_read_the_same_either_way_and_teach_nothing(conn, caplog):
    resolve = auto_resolver(conn, source_file="Player.log", last_write=STALE)
    with caplog.at_level(logging.WARNING):
        assert resolve(stamp("06/06/2026 14:39:17")) == "2026-06-06T14:39:17"
    assert learned(conn) == {}
    assert messages(caplog) == []


@pytest.mark.parametrize(
    ("text", "shape", "order", "expected"),
    [
        (ENGLISH, "slash-12h", "mdy", "2026-10-06T14:37:04"),
        (SPANISH, "slash-24h", "dmy", "2026-10-06T14:39:17"),
        (GERMAN, "dot-24h", "dmy", "2026-10-06T14:39:58"),
    ],
)
def test_step_4_the_reading_within_the_files_week_is_taken_and_taught(
    conn, text, shape, order, expected
):
    """Each captured stamp reads as a date either way (6 October or 10 June);
    only the capture day is within the week of a last write that afternoon."""
    resolve = auto_resolver(conn, source_file="Player.log", last_write=CAPTURE_AFTERNOON)
    assert resolve(stamp(text)) == expected
    assert learned(conn) == {shape: (order, text, "Player.log")}


@pytest.mark.parametrize(
    ("last_write", "expected"),
    [
        (datetime(2026, 10, 13, 14, 39, 17), "2026-10-06T14:39:17"),   # a week after it
        (datetime(2026, 10, 5, 14, 39, 17), "2026-10-06T14:39:17"),    # a day before it
        (datetime(2026, 10, 13, 14, 39, 18), None),
        (datetime(2026, 10, 5, 14, 39, 16), None),
    ],
)
def test_step_4_the_window_runs_from_a_week_before_the_last_write_to_a_day_after(
    conn, last_write, expected
):
    """Both ends included; one second past either and nothing settles it."""
    resolve = auto_resolver(conn, source_file="Player.log", last_write=last_write)
    assert resolve(stamp(SPANISH)) == expected


def test_step_5_the_learned_order_dates_a_header_outside_the_window(conn, caplog):
    auto_resolver(conn, source_file="Player-prev.log", last_write=CAPTURE_AFTERNOON)(
        stamp(SPANISH)
    )
    later = auto_resolver(conn, source_file="Player.log", last_write=STALE)
    with caplog.at_level(logging.WARNING):
        assert later(stamp(SPANISH)) == "2026-10-06T14:39:17"
    # Read, not taught again: the row still names the read that settled it.
    assert learned(conn) == {"slash-24h": ("dmy", SPANISH, "Player-prev.log")}
    assert messages(caplog) == []


def test_a_learned_order_belongs_to_its_own_shape_alone(conn):
    """German and Spanish are both day first, but a dot is not a slash: what
    one shape taught never dates another."""
    auto_resolver(conn, source_file="Player-prev.log", last_write=CAPTURE_AFTERNOON)(
        stamp(SPANISH)
    )
    later = auto_resolver(conn, source_file="Player.log", last_write=STALE)
    assert later(stamp(GERMAN)) is None
    assert later(stamp(ENGLISH)) is None


def test_step_6_nothing_settles_it_so_none_and_the_d3_warning(conn, caplog):
    resolve = auto_resolver(conn, source_file="Player.log", last_write=STALE)
    with caplog.at_level(logging.WARNING):
        assert resolve(stamp(SPANISH)) is None
    assert learned(conn) == {}
    assert messages(caplog) == [
        "Player.log: header '06/10/2026 14:39:17' reads as a date either way, is not "
        "within the week before the file's last write (2026-12-01 15:00), and this "
        "database has not learned the order of slash-24h headers; its entries are "
        "stored with no time"
    ]


# --- teaching ------------------------------------------------------------------


def test_a_header_agreeing_with_the_learned_order_writes_nothing(conn):
    """The row is written only when the order changes: it keeps naming the
    stamp that first settled it."""
    resolve = auto_resolver(conn, source_file="Player.log", last_write=CAPTURE_AFTERNOON)
    resolve(stamp(SPANISH))                            # step 4: dmy
    before = tuple(conn.execute("SELECT * FROM header_date_order").fetchone())
    resolve(stamp("13/10/2026 14:40:00"))              # step 2: dmy again
    resolve(stamp("06/10/2026 14:40:53"))              # step 4: dmy again
    after = auto_resolver(conn, source_file="Player-prev.log", last_write=STALE)
    after(stamp("06/10/2026 14:41:34"))                # step 5
    assert tuple(conn.execute("SELECT * FROM header_date_order").fetchone()) == before


def test_what_a_read_learns_dates_its_later_headers_never_its_earlier_ones(conn):
    """No second pass: the header before the lesson stays None."""
    resolve = auto_resolver(conn, source_file="Player.log", last_write=STALE)
    assert resolve(stamp(SPANISH)) is None
    assert resolve(stamp("13/10/2026 14:40:00")) == "2026-10-13T14:40:00"
    assert resolve(stamp("06/10/2026 14:40:53")) == "2026-10-06T14:40:53"


def test_a_header_settling_its_shape_against_the_learned_order_warns_and_wins(conn, caplog):
    auto_resolver(conn, source_file="Player-prev.log", last_write=CAPTURE_AFTERNOON)(
        stamp(SPANISH)
    )
    resolve = auto_resolver(conn, source_file="Player.log", last_write=STALE)
    with caplog.at_level(logging.WARNING):
        assert resolve(stamp("10/13/2026 14:00:00")) == "2026-10-13T14:00:00"   # step 2: mdy
        # The latest evidence wins, for this read's later headers too.
        assert resolve(stamp(SPANISH)) == "2026-06-10T14:39:17"
    assert learned(conn) == {"slash-24h": ("mdy", "10/13/2026 14:00:00", "Player.log")}
    assert messages(caplog) == [
        "Player.log: header '10/13/2026 14:00:00' reads mdy, but this database had "
        "learned dmy for slash-24h headers (from '06/10/2026 14:39:17'); mdy from now "
        "on, and rows already stored keep their dates"
    ]


def test_a_window_reading_against_the_learned_order_is_a_contradiction_too(conn, caplog):
    auto_resolver(conn, source_file="Player-prev.log", last_write=STALE)(
        stamp("10/13/2026 14:00:00")                   # step 2: mdy
    )
    resolve = auto_resolver(conn, source_file="Player.log", last_write=CAPTURE_AFTERNOON)
    with caplog.at_level(logging.WARNING):
        assert resolve(stamp(SPANISH)) == "2026-10-06T14:39:17"                 # step 4: dmy
    assert learned(conn) == {"slash-24h": ("dmy", SPANISH, "Player.log")}
    assert messages(caplog) == [
        "Player.log: header '06/10/2026 14:39:17' reads dmy, but this database had "
        "learned mdy for slash-24h headers (from '10/13/2026 14:00:00'); dmy from now "
        "on, and rows already stored keep their dates"
    ]


def test_settled_at_is_utc_to_the_second(conn):
    auto_resolver(conn, source_file="Player.log", last_write=CAPTURE_AFTERNOON)(stamp(SPANISH))
    (settled_at,) = conn.execute("SELECT settled_at FROM header_date_order").fetchone()
    # The format alone would pass a local time with a literal Z: it must also
    # be now, read as UTC.
    settled = datetime.strptime(settled_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert abs(datetime.now(UTC) - settled) < timedelta(minutes=1)


# --- warnings: once per process per file and shape -----------------------------


def test_the_d3_warning_fires_once_per_file_and_shape(conn, caplog):
    """The watcher builds a resolver per poll, every second: a warning per
    header, or per poll, would bury everything else."""
    with caplog.at_level(logging.WARNING):
        for source_file in ("Player.log", "Player.log", "Player-prev.log"):
            resolve = auto_resolver(conn, source_file=source_file, last_write=STALE)
            resolve(stamp(SPANISH))
            resolve(stamp("06/10/2026 14:40:53"))
            resolve(stamp(GERMAN))
    tail = (
        "is not within the week before the file's last write (2026-12-01 15:00), and "
        "this database has not learned the order of {shape} headers; its entries are "
        "stored with no time"
    )
    assert messages(caplog) == [
        f"{name}: header {text!r} reads as a date either way, " + tail.format(shape=shape)
        for name in ("Player.log", "Player-prev.log")
        for text, shape in ((SPANISH, "slash-24h"), (GERMAN, "dot-24h"))
    ]


def test_the_contradiction_warning_fires_once_per_file_and_shape(conn, caplog):
    resolve = auto_resolver(conn, source_file="Player.log", last_write=STALE)
    with caplog.at_level(logging.WARNING):
        resolve(stamp("13/10/2026 14:39:17"))   # dmy, and nothing to contradict
        resolve(stamp("10/13/2026 14:39:17"))   # mdy: warns
        resolve(stamp("13/10/2026 14:40:00"))   # dmy: same file and shape, silent
        other = auto_resolver(conn, source_file="Player-prev.log", last_write=STALE)
        other(stamp("10/13/2026 14:41:00"))     # mdy: another file, warns
    assert learned(conn) == {"slash-24h": ("mdy", "10/13/2026 14:41:00", "Player-prev.log")}
    assert messages(caplog) == [
        "Player.log: header '10/13/2026 14:39:17' reads mdy, but this database had "
        "learned dmy for slash-24h headers (from '13/10/2026 14:39:17'); mdy from now "
        "on, and rows already stored keep their dates",
        "Player-prev.log: header '10/13/2026 14:41:00' reads mdy, but this database had "
        "learned dmy for slash-24h headers (from '13/10/2026 14:40:00'); mdy from now "
        "on, and rows already stored keep their dates",
    ]
