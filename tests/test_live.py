"""M4 live-mode tests.

``poll_once`` is driven directly rather than through the thread: the loop is
five lines around it, and testing the timing behaviour by sleeping would make
the suite slow and flaky. The thread itself is covered by a start/stop test.
"""

import base64
import contextlib
import hashlib
import logging
import multiprocessing.connection
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sensei_top import db, procs
from sensei_top import live as live_module
from sensei_top.api import create_app
from sensei_top.db import open_database
from sensei_top.live import LiveIngester
from sensei_top.reader.ingest import previous_log_path

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"


@pytest.fixture
def live(tmp_path):
    """A watcher over a log that starts empty, so tests append to it."""
    log = tmp_path / "Player.log"
    log.write_text("", newline="")
    return LiveIngester(
        db_path=tmp_path / "live.db",
        log_path=log,
        locale_hint="mdy",
        interval=0.01,
        project_every=0.0,   # project on every dirty poll unless a test says otherwise
    )


@pytest.fixture
def conn(live):
    connection = open_database(live.db_path)
    yield connection
    connection.close()


def append(path: Path, text: str) -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        handle.write(text)


def append_bytes(path: Path, data: bytes) -> None:
    with path.open("ab") as handle:
        handle.write(data)


def counts(conn) -> dict[str, int]:
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("raw_events", "matches", "games", "turns")
    }


# --- ingest + project together ----------------------------------------------


def test_poll_ingests_and_projects_new_events(live, conn):
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    assert live.poll_once(conn) is True

    after = counts(conn)
    assert after["raw_events"] == 34
    assert after["matches"] == 2
    assert after["games"] == 5
    assert after["turns"] == 16


def test_quiet_poll_reports_no_change(live, conn):
    assert live.poll_once(conn) is False
    assert live.stats.events_ingested == 0
    assert live.stats.projections == 0


def test_appending_between_polls_is_picked_up(live, conn):
    lines = FIXTURE.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    half = len(lines) // 2

    append(live.log_path, "".join(lines[:half]))
    live.poll_once(conn)
    first = counts(conn)["raw_events"]

    append(live.log_path, "".join(lines[half:]))
    live.poll_once(conn)
    assert counts(conn)["raw_events"] > first
    assert counts(conn)["raw_events"] == 34


def test_first_poll_recovers_the_previous_session(live, conn):
    """Arena wipes Player.log on launch; the last session is only in -prev."""
    previous_log_path(live.log_path).write_text(
        FIXTURE.read_text(encoding="utf-8", errors="replace"), newline=""
    )
    live.poll_once(conn)
    assert counts(conn)["raw_events"] == 34


def relaunch(live: LiveIngester) -> LiveIngester:
    """Arena relaunches (Player.log becomes Player-prev.log, a fresh empty log
    starts) and the watcher process starts again, over the same database."""
    live.log_path.rename(previous_log_path(live.log_path))
    live.log_path.write_bytes(b"")
    return LiveIngester(
        db_path=live.db_path, log_path=live.log_path, locale_hint=live.locale_hint,
        interval=live.interval, project_every=live.project_every,
    )


def test_the_previous_session_adds_nothing_its_live_polls_stored(live, conn):
    """D9 reads Player-prev.log whole at every watcher startup, and that file
    is usually the Player.log the last watcher already tailed poll by poll.
    The digest leaves the file name out, so the whole read must find every
    entry already stored (34: fixture_peek.py index of match_session.log)."""
    lines = FIXTURE.read_bytes().splitlines(keepends=True)
    third = len(lines) // 3
    for piece in (lines[:third], lines[third : 2 * third], lines[2 * third :]):
        append_bytes(live.log_path, b"".join(piece))
        live.ingest_once(conn)
    assert counts(conn)["raw_events"] == 34

    restarted = relaunch(live)
    assert restarted.ingest_once(conn) == 0
    assert counts(conn)["raw_events"] == 34
    sources = {row[0] for row in conn.execute("SELECT source_path FROM ingest_state")}
    assert str(previous_log_path(live.log_path)) in sources  # a resume row of its own


# A header, then a request inheriting its timestamp (segmenter.py, shapes 1
# and 2): the same payload in the same second, the shape of Arena's repeated
# client-state polls.
SAME_SECOND_HEADER = "[UnityCrossThreadLogger]8/13/2026 2:40:28 PM\r\n"
SAME_SECOND_POLL = '[UnityCrossThreadLogger]==> Ping {"id":"same","request":"{}"}\r\n'


def test_a_same_second_repeat_split_across_polls_is_restored_not_doubled(live, conn):
    """The occurrence ordinal counts per read (reader/ingest.py, "Digest
    strategy"): the second of two identical same-second entries, landing on
    the next poll, digests like the first and is not stored. Reading the
    rotated file whole at the next startup counts both, so it adds that one
    entry back, and nothing more: the file holds two, the table ends with
    two."""
    append(live.log_path, SAME_SECOND_HEADER + SAME_SECOND_POLL)
    live.ingest_once(conn)
    append(live.log_path, SAME_SECOND_POLL)
    live.ingest_once(conn)
    assert counts(conn)["raw_events"] == 1  # the per-read tradeoff the docstring states

    restarted = relaunch(live)
    assert restarted.ingest_once(conn) == 1
    stamps = [row[0] for row in conn.execute("SELECT logged_at FROM raw_events")]
    assert stamps == ["2026-08-13T14:40:28", "2026-08-13T14:40:28"]


# --- the two cadences --------------------------------------------------------

# A single-line request (segmenter.py's case 1) with no match-room content at
# all — appending this, unlike re-appending FIXTURE, is genuinely new content
# (digests are content-addressed, so a repeat of FIXTURE inserts nothing) and
# never trips has_match_boundary, so it isolates the elapsed-time throttle
# from the boundary override tested separately below.
NOISE_REQUEST = '[UnityCrossThreadLogger]==> Ping {"id":"noise","request":"{}"}\n'


def test_projection_is_throttled_but_ingestion_is_not(live, conn):
    """New events within an already-known match must land immediately; the
    rebuild may wait for its beat. A new match room is the one thing that
    bypasses this — see test_a_new_match_room_forces_projection below."""
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)  # this fixture opens two match rooms, so it force-
    assert counts(conn)["matches"] == 2  # projects regardless of the beat

    live.project_every = 60.0
    live._last_projection = time.monotonic()  # a rebuild just happened

    append(live.log_path, NOISE_REQUEST)
    live.poll_once(conn)

    assert counts(conn)["raw_events"] == 35   # ingested now
    assert counts(conn)["matches"] == 2       # rebuild deferred, not re-run
    assert live.stats.projections == 1        # only the first poll's
    assert live._dirty is True


def test_deferred_projection_runs_on_a_later_poll(live, conn):
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)
    assert counts(conn)["matches"] == 2

    live.project_every = 60.0
    live._last_projection = time.monotonic()
    append(live.log_path, NOISE_REQUEST)
    live.poll_once(conn)
    assert live._dirty is True

    # Its beat comes round: the gate is max(project_every, _last_duration *
    # duty_factor), so both have to be zeroed — the first rebuild above took
    # some (real, nonzero) wall time, and duty_factor alone would still hold
    # the gate open past this instant.
    live.project_every = 0.0
    live._last_duration = 0.0
    live.poll_once(conn)
    assert live._dirty is False
    assert live.stats.projections == 2


def test_a_new_match_room_forces_projection(live, conn):
    """The one exception to the beat: a match room opening rebuilds
    immediately even with a long project_every still running."""
    live.project_every = 3600.0
    live._last_projection = time.monotonic()   # a rebuild just happened

    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)

    assert counts(conn)["matches"] == 2
    assert live.stats.projections == 1
    assert live._dirty is False


def test_duty_cycle_holds_the_gate_open_past_project_every(live, conn):
    """A rebuild that took real wall time must not be immediately followed
    by another one just because project_every has elapsed: the adaptive
    gate is max(project_every, _last_duration * duty_factor), so a slow
    rebuild earns itself a proportionally longer rest — the whole point of
    Phase 2 (a rebuild that outlasts project_every used to run back-to-back
    forever, pegging a core for the rest of the session)."""
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)  # forced by the match-room boundary
    assert live.stats.projections == 1

    # Simulate a rebuild that took 16s, same order of magnitude as the one
    # measured against the real 238k-event database this plan was written
    # against. Set explicitly rather than relying on the class default: the
    # default itself changed (4.0 -> 1.0) once the Current match tab went
    # Arena-only (live.py's module docstring), and this test is about the
    # gate math, not about pinning whatever the default happens to be —
    # duty_factor=4.0 makes the gate 64s.
    live.duty_factor = 4.0
    live._last_duration = 16.0
    live.project_every = 5.0  # the old fixed threshold, now just the floor
    live._last_projection = time.monotonic()

    append(live.log_path, NOISE_REQUEST)
    live.poll_once(conn)  # elapsed is ~0s, nowhere near the 64s gate
    assert live._dirty is True
    assert live.stats.projections == 1  # no second rebuild yet

    # Once elapsed does clear the duty-cycle gate (not just project_every),
    # the deferred rebuild runs.
    live._last_projection = time.monotonic() - 65.0
    live.poll_once(conn)
    assert live._dirty is False
    assert live.stats.projections == 2


def test_a_new_match_room_bypasses_the_duty_cycle_gate(live, conn):
    """The boundary force is the one thing duty_factor must never delay —
    it exists precisely so a fresh match/draft room still rebuilds inside
    the mulligan/pick window even while a long duty-cycle gate is open."""
    live._last_duration = 16.0
    live.project_every = 3600.0
    live._last_projection = time.monotonic()  # a rebuild "just happened"

    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)

    assert counts(conn)["matches"] == 2
    assert live.stats.projections == 1
    assert live._dirty is False


def test_watermark_survives_a_restart(tmp_path):
    """``_projected_through`` is restored from ``projection_state`` on the
    first poll of a fresh ``LiveIngester`` — otherwise every restart resets
    it to 0 and the next boundary check LIKE-scans every row ever ingested,
    not just the ones since the last rebuild."""
    log = tmp_path / "Player.log"
    log.write_text("", newline="")
    db_path = tmp_path / "live.db"

    first = LiveIngester(
        db_path=db_path, log_path=log, locale_hint="mdy",
        interval=0.01, project_every=0.0,
    )
    conn = open_database(db_path)
    append(log, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    first.poll_once(conn)
    watermark = first._projected_through
    assert watermark == counts(conn)["raw_events"] == 34
    conn.close()

    # A brand-new LiveIngester over the same database, as after a process
    # restart: _projected_through starts at the dataclass default (0) until
    # the first poll_once call restores it.
    second = LiveIngester(
        db_path=db_path, log_path=log, locale_hint="mdy",
        interval=0.01, project_every=0.0,
    )
    assert second._projected_through == 0
    conn = open_database(db_path)
    second.poll_once(conn)  # nothing new to ingest; still restores the watermark
    assert second._projected_through == watermark
    conn.close()


def _restart_with_stored_version(tmp_path, version=...):
    """Rebuild once, set ``projection_state.projector_version`` to ``version``
    (left as the rebuild wrote it when omitted), then poll a fresh
    ``LiveIngester`` over the same database with no new ``raw_events``.
    Returns that second watcher's ``projections`` count."""
    log = tmp_path / "Player.log"
    log.write_text("", newline="")
    db_path = tmp_path / "live.db"
    first = LiveIngester(
        db_path=db_path, log_path=log, locale_hint="mdy",
        interval=0.01, project_every=0.0,
    )
    conn = open_database(db_path)
    append(log, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    first.poll_once(conn)
    assert first.stats.projections == 1
    if version is not ...:
        conn.execute("UPDATE projection_state SET projector_version = ?", (version,))
        conn.commit()
    conn.close()

    second = LiveIngester(
        db_path=db_path, log_path=log, locale_hint="mdy",
        interval=0.01, project_every=0.0,
    )
    conn = open_database(db_path)
    second.poll_once(conn)
    conn.close()
    return second.stats.projections


def test_a_null_projector_version_rebuilds_on_the_first_poll(tmp_path):
    """Rows written before the column existed carry NULL and must be rebuilt once."""
    assert _restart_with_stored_version(tmp_path, None) == 1


def test_the_current_projector_version_does_not_rebuild(tmp_path):
    """The rebuild must record its version, or every restart would rebuild again."""
    assert _restart_with_stored_version(tmp_path) == 0


def test_a_new_match_room_updates_the_projected_through_watermark(live, conn):
    live.project_every = 3600.0
    live._last_projection = time.monotonic()
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)
    after_first = live._projected_through
    assert after_first == counts(conn)["raw_events"] == 34

    # No new match room in this append: the watermark must not move again
    # until the next real rebuild.
    append(live.log_path, NOISE_REQUEST)
    live.poll_once(conn)
    assert live._projected_through == after_first


def test_project_disabled_only_ingests(live, conn):
    live.project_enabled = False
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)
    assert counts(conn)["raw_events"] == 34
    assert counts(conn)["matches"] == 0


def test_projection_does_not_rerun_without_new_events(live, conn):
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)
    assert live.stats.projections == 1

    live.poll_once(conn)   # nothing new
    assert live.stats.projections == 1


# --- robustness --------------------------------------------------------------


def test_a_watcher_with_no_arena_log_picks_one_up_when_it_appears(tmp_path):
    """D10: started with no path, it ingests nothing, and reads a log that
    shows up later from offset 0. Expectations: the fixture's index lists 34
    entries; the 2 matches, 5 games, 16 turns are the figures
    test_poll_ingests_and_projects_new_events asserts for this fixture."""
    found: list[Path] = []
    looks: list[int] = []

    def resolver() -> Path | None:
        looks.append(1)
        return found[0] if found else None

    watcher = LiveIngester(
        db_path=tmp_path / "live.db",
        log_path=None,
        locale_hint="mdy",
        project_every=0.0,
        log_resolver=resolver,
        log_resolve_every=0.0,   # look on every pass; the real interval is 60 s
    )
    connection = open_database(watcher.db_path)
    try:
        assert watcher.poll_once(connection) is False
        assert watcher.poll_once(connection) is False
        assert len(looks) == 2 and watcher.log_path is None
        assert counts(connection)["raw_events"] == 0
        assert watcher.stats.errors == 0

        late = tmp_path / "Player.log"
        shutil.copyfile(FIXTURE, late)
        found.append(late)
        assert watcher.poll_once(connection) is True

        assert watcher.log_path == late
        after = counts(connection)
        assert after["raw_events"] == 34
        assert (after["matches"], after["games"], after["turns"]) == (2, 5, 16)
        looks.clear()
        watcher.poll_once(connection)
        assert looks == []   # found: it stops looking
    finally:
        connection.close()


def test_a_watcher_with_no_arena_log_looks_once_per_interval(tmp_path):
    looks: list[int] = []
    now = [1000.0]
    watcher = LiveIngester(
        db_path=tmp_path / "live.db",
        log_path=None,
        log_resolver=lambda: looks.append(1),
        log_resolve_every=60.0,
        log_clock=lambda: now[0],
    )
    connection = open_database(watcher.db_path)
    try:
        for offset in (0, 1, 30, 59):   # the start, then inside the first interval
            now[0] = 1000.0 + offset
            watcher.poll_once(connection)
        assert looks == []
        now[0] = 1060.0                  # exactly one interval after the start
        watcher.poll_once(connection)
        assert len(looks) == 1
        for offset in (61, 90, 119):     # before twice the interval
            now[0] = 1000.0 + offset
            watcher.poll_once(connection)
        assert len(looks) == 1
        now[0] = 1120.0
        watcher.poll_once(connection)
        assert len(looks) == 2
    finally:
        connection.close()


def test_a_watcher_with_no_arena_log_still_stores_mtgo(tmp_path):
    """D10: it watches MTGO alone while Arena's log is missing."""
    folder = tmp_path / "mtgo-share"
    folder.mkdir()
    (folder / "Match_GameLog_11111111-1111-1111-1111-111111111111.dat").write_bytes(
        MTGO_FIXTURE.read_bytes()
    )
    watcher = LiveIngester(
        db_path=tmp_path / "live.db",
        log_path=None,
        log_resolver=lambda: None,
        mtgo_dir=folder,
    )
    connection = open_database(watcher.db_path)
    try:
        assert watcher.ingest_once(connection) > 0
        assert watcher.log_path is None
        assert mtgo_payloads(connection) == [MTGO_BYTES]
    finally:
        connection.close()


def test_missing_log_is_survivable(live, conn):
    """The log disappears between launches; that is not an error."""
    live.log_path.unlink()
    assert live.poll_once(conn) is False
    assert live.stats.errors == 0


def test_stats_track_progress(live, conn):
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)
    assert live.stats.polls == 1
    assert live.stats.events_ingested == 34
    assert live.stats.projections == 1
    assert live.stats.last_ingest_at is not None
    assert live.stats.last_projection_at is not None
    assert live.stats.last_error is None


# --- the thread --------------------------------------------------------------


def test_start_and_stop_are_clean(live):
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.start()
    deadline = time.monotonic() + 5
    while live.stats.projections == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    live.stop()

    assert live.stats.projections >= 1, "watcher thread never projected"
    assert live.stats.running is False
    assert live._thread is None

    conn = open_database(live.db_path)
    assert counts(conn)["matches"] == 2
    conn.close()


# --- MTGO: a second, independent ingest leg -----------------------------


def mtgo_row_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM raw_events WHERE source = 'mtgo'").fetchone()[0]


def test_mtgo_dir_none_is_a_no_op(live, conn):
    """The normal machine, with no MTGO share configured at all."""
    assert live.mtgo_dir is None
    append(live.log_path, NOISE_REQUEST)
    live.poll_once(conn)
    assert mtgo_row_count(conn) == 0


MTGO_FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_match_session.log"
MTGO_BYTES = MTGO_FIXTURE.read_bytes()
MATCH_LOG = "Match_GameLog_11111111-1111-1111-1111-111111111111.dat"


def _mtgo_span(text: str, occurrence: int = 0) -> tuple[int, int]:
    """``(start, end)`` of one string in ``MTGO_BYTES``, found in the raw
    bytes as ``test_projector_mtgo.py``'s ``_string_span`` finds it, never by
    running the decoder: ``start`` at its one-byte length prefix (.NET's
    BinaryWriter framing), ``end`` just past its last byte."""
    encoded = text.encode("utf-8")
    at = -1
    for _ in range(occurrence + 1):
        at = MTGO_BYTES.index(encoded, at + 1)
    assert MTGO_BYTES[at - 1] == len(encoded) < 0x80, text
    return at - 1, at + len(encoded)


# Cuts where the fixture's bytes end a string, so each prefix is a state MTGO
# really wrote: its writes are pure appends (plan 3, F14). The fixture is one
# two-game match, each game conceded and then won; the comments are line
# numbers of `scripts/mtgo_probe.py --force --lines 400 ... | nl -ba`.
_G1_UNDER_WAY = _mtgo_span("@PTurn 1: Player1")[1]  # line 30
_G1_LATE = _mtgo_span("@PPlayer1 casts @[Thorin, Mountain-king@:308328,481:@].")[1]  # line 86
_G1_CONCEDED = _mtgo_span("@PPlayer2000 has conceded from the game.")[1]  # line 94
_G1_WON = _mtgo_span("@PPlayer1 wins the game.")[1]  # line 95
_G1_LEADS = _mtgo_span("@PPlayer1 leads the match 1-0")[1]  # line 96
_G2_JOINED = _mtgo_span("@P@PPlayer2000 joined the game.", 1)[1]  # line 97, game 2's first
_G2_CAST = _mtgo_span("@PPlayer1 casts @[Dwarven Mauler@:308240,451:@].")[1]  # line 118
_G2_CONCEDED = _mtgo_span("@PPlayer2000 has conceded from the game.", 1)[1]  # line 142
_MATCH_OVER = len(MTGO_BYTES)  # line 144, "wins the match 2-0", the last string


class _Clock:
    """``LiveIngester.mtgo_clock``, moved by hand: a game log's quiet is
    measured on the watcher's own clock, so a test owns it."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def share(live, conn, tmp_path):
    """``live`` watching an empty MTGO folder on a hand-moved clock, its
    first pass already run at 0 s: whatever a test writes from here on is
    held to the game-end rule."""
    folder = tmp_path / "mtgo-share"
    folder.mkdir()
    live.mtgo_dir = folder
    live.mtgo_clock = _Clock()
    live.ingest_once(conn)
    return folder


def write_through(folder: Path, cut: int) -> None:
    """Append the fixture's bytes up to ``cut`` to the match's game log, as
    MTGO's next write would."""
    log = folder / MATCH_LOG
    written = log.stat().st_size if log.exists() else 0
    append_bytes(log, MTGO_BYTES[written:cut])


def at(live: LiveIngester, conn, when: float) -> None:
    """One ingest pass with the watcher's clock at ``when``."""
    live.mtgo_clock.now = when
    live.ingest_once(conn)


def run_for(live: LiveIngester, conn, seconds: float) -> None:
    """``seconds`` of the watcher's clock with an ingest pass every second,
    as ``_ingest_loop`` runs them every ``interval``."""
    end = live.mtgo_clock.now + seconds
    while live.mtgo_clock.now < end:
        at(live, conn, live.mtgo_clock.now + 1.0)


def mtgo_payloads(conn) -> list[bytes]:
    """Every stored game-log row's bytes, oldest first."""
    rows = conn.execute("SELECT payload FROM raw_events WHERE source = 'mtgo' ORDER BY id")
    return [base64.b64decode(row[0]) for row in rows]


def test_the_first_pass_stores_a_game_log_mid_game(live, conn, tmp_path):
    """The watcher's first pass catches up whatever was written while nothing
    watched, so it stores every changed file at once, decided or not (plan 3,
    D2): here a log cut in game 1's late turns. Only the first pass skips the
    wait; the same file's next write waits for its game to end."""
    folder = tmp_path / "mtgo-share"
    folder.mkdir()
    write_through(folder, _G1_LATE)
    live.mtgo_dir = folder
    live.mtgo_clock = _Clock()

    live.ingest_once(conn)
    assert mtgo_payloads(conn) == [MTGO_BYTES[:_G1_LATE]]
    assert live._dirty is True

    write_through(folder, _G1_CONCEDED)
    run_for(live, conn, 60)
    assert mtgo_payloads(conn) == [MTGO_BYTES[:_G1_LATE]]


def test_a_mid_game_log_waits_however_long_it_stays_quiet_short_of_ten_minutes(
    live, conn, share, monkeypatch
):
    """Quiet alone cannot tell a finished game from a long think (one measured
    mid-game pause lasted 36 s, plan 3 F14), so a game in progress is never
    stored for being quiet, short of the 10-minute fallback. Game 1 is already
    won earlier in this file: what counts is the last game. Judged once for as
    long as the bytes stay the same, not on every 2 s check, so the
    projector's reading, and any warning it logs, is not repeated."""
    verdicts: list[int] = []
    real = live_module.last_game_decided

    def judged(data: bytes) -> bool:
        verdicts.append(len(data))
        return real(data)

    monkeypatch.setattr(live_module, "last_game_decided", judged)
    write_through(share, _G2_CAST)
    at(live, conn, 2.0)  # the check that first sees it
    run_for(live, conn, 597.0)  # checks every 2 s, to 598 s
    at(live, conn, 601.9)  # quiet 599.9 s
    assert mtgo_payloads(conn) == []
    assert live._dirty is False
    assert verdicts == [_G2_CAST]


def test_a_log_quiet_ten_minutes_is_stored_whatever_its_last_game_says(live, conn, share):
    """A disconnect, a crash or a game that ends with no winner line never
    names a winner, so 10 minutes of quiet stores the file regardless (plan
    3, D2), and the projector reads it as an unfinished game."""
    write_through(share, _G2_CAST)
    at(live, conn, 2.0)  # the check that first sees it
    at(live, conn, 400.0)
    assert mtgo_payloads(conn) == []
    at(live, conn, 602.0)  # quiet 600 s
    assert mtgo_payloads(conn) == [MTGO_BYTES[:_G2_CAST]]
    assert live._dirty is True


@pytest.mark.parametrize(("quiet", "stored"), [(4.9, False), (5.0, True)])
def test_a_won_game_is_stored_once_quiet_five_seconds(live, conn, share, quiet, stored):
    """Game 1 won and the match score written (probe lines 95-96): stored
    once the file has been quiet 5 s, counted from the check that first saw
    it. Its mtime is set an hour back, as a copy from a machine whose clock
    runs behind would carry it: quiet is the watcher's own, never the
    mtime's."""
    write_through(share, _G1_LEADS)
    log = share / MATCH_LOG
    an_hour_back = log.stat().st_mtime - 3600
    os.utime(log, (an_hour_back, an_hour_back))

    at(live, conn, 2.0)  # the check that first sees it
    assert mtgo_payloads(conn) == []
    at(live, conn, 2.0 + quiet)
    assert mtgo_payloads(conn) == ([MTGO_BYTES[:_G1_LEADS]] if stored else [])
    assert live._dirty is stored


def test_a_log_that_moves_between_scan_and_read_is_not_quiet(live, conn, share, monkeypatch):
    """The bytes stored are the bytes judged, and only while they are the
    ones the scan saw. A write landing between the scan and the read (here
    game 1's match score, after its winner line) means the file was not
    quiet after all: nothing is stored, and its quiet restarts at that
    check."""
    real = live_module.read_game_log
    reads: list[Path] = []

    def written_under_the_read(path: Path):
        if not reads:
            write_through(share, _G1_LEADS)
        reads.append(path)
        return real(path)

    monkeypatch.setattr(live_module, "read_game_log", written_under_the_read)
    write_through(share, _G1_WON)
    at(live, conn, 2.0)  # the check that first sees it
    at(live, conn, 7.0)  # quiet 5 s: read, and the file moved under the read
    assert mtgo_payloads(conn) == []
    at(live, conn, 11.9)  # quiet 4.9 s since then
    assert mtgo_payloads(conn) == []
    at(live, conn, 14.0)
    assert mtgo_payloads(conn) == [MTGO_BYTES[:_G1_LEADS]]


# One match as MTGO writes it, replayed from the fixture: each step appends the
# bytes up to a cut and then leaves the file alone for so many seconds. The gaps
# are of the measured kind (plan 3, F14): mid-game pauses up to 36 s, about 46 s
# between games, nothing after the match-winner line; a concession and its
# winner line a second apart, which a check can land between.
_REPLAY = [
    (_G1_UNDER_WAY, 8),
    (_G1_LATE, 36),
    (_G1_CONCEDED, 1),
    (_G1_WON, 1),
    (_G1_LEADS, 46),
    (_G2_JOINED, 3),
    (_G2_CAST, 36),
    (_G2_CONCEDED, 1),
    (_MATCH_OVER, 60),
]


def test_a_replayed_match_ends_with_one_row_per_game(live, conn, share):
    """Two games, two rows (plan 3, D2): game 1 as it stood once its winner
    line and the match score were written, and the whole file once game 2
    was won. Every other state the file passed through, mid-game, conceded
    without its winner line yet, or won a second ago, is passed over."""
    for cut, quiet in _REPLAY:
        write_through(share, cut)
        run_for(live, conn, quiet)
    assert mtgo_payloads(conn) == [MTGO_BYTES[:_G1_LEADS], MTGO_BYTES]


def test_a_game_log_that_cannot_be_statted_warns_once(
    live, conn, tmp_path, monkeypatch, caplog
):
    """The scan meets every file in the folder every 2 s. One it cannot
    stat() is left out each time but warned about once, not thirty times a
    minute, and the match beside it is still stored."""
    folder = tmp_path / "mtgo-share"
    folder.mkdir()
    broken = folder / "Match_GameLog_22222222-2222-2222-2222-222222222222.dat"
    broken.write_bytes(b"x")
    real_stat = Path.stat

    def stat(self: Path, *args, **kwargs):
        if self.name == broken.name:
            raise PermissionError("denied")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    live.mtgo_dir = folder
    live.mtgo_clock = _Clock()
    with caplog.at_level(logging.WARNING):
        live.ingest_once(conn)  # the first pass meets it too
        write_through(folder, _G1_LEADS)
        run_for(live, conn, 20)
    assert mtgo_payloads(conn) == [MTGO_BYTES[:_G1_LEADS]]
    assert sum(broken.name in message for message in caplog.messages) == 1


def test_a_failing_folder_is_counted_once_per_outage(live, conn, share, monkeypatch, caplog):
    """A dead mount makes the folder's listing itself raise. The watch goes
    on, and one outage is one error and one warning, not one every 2 s; a
    folder that comes back and fails again is a second outage."""
    real = live_module.scan_game_logs

    def dead(*_args, **_kwargs):
        raise OSError("not connected")

    with caplog.at_level(logging.WARNING):
        monkeypatch.setattr(live_module, "scan_game_logs", dead)
        run_for(live, conn, 20)
        assert live.stats.errors == 1
        monkeypatch.setattr(live_module, "scan_game_logs", real)
        run_for(live, conn, 4)
        monkeypatch.setattr(live_module, "scan_game_logs", dead)
        run_for(live, conn, 4)
    assert live.stats.errors == 2
    assert live.stats.last_error == "not connected"
    assert sum("mtgo poll failed" in message for message in caplog.messages) == 2


def test_nonexistent_mtgo_dir_keeps_polling_without_growing_errors(live, conn, tmp_path):
    """A torn-down virtiofs share must not end the Arena watch (module
    docstring's _poll_mtgo contract) — ingest_mtgo_dir itself treats a
    missing directory as zero files, not an error, so this never even
    reaches _poll_mtgo's own OSError guard."""
    live.mtgo_dir = tmp_path / "does-not-exist"
    append(live.log_path, NOISE_REQUEST)
    live.poll_once(conn)
    assert live.stats.errors == 0
    assert mtgo_row_count(conn) == 0


GROUPING_FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_grouping_deck.xml"
DECK_FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_deck_sample.dek"


def deck_rows(conn) -> list[tuple[str, str]]:
    """``(label, source_file)`` of every stored deck file, in name order."""
    return conn.execute(
        "SELECT label, source_file FROM raw_events WHERE source = 'mtgo_deck' "
        "ORDER BY source_file"
    ).fetchall()


def put_grouping(folder: Path, name: str) -> None:
    folder.mkdir(exist_ok=True)
    (folder / f"grouping {name}.xml").write_bytes(GROUPING_FIXTURE.read_bytes())


def test_mtgo_dir_groupings_are_polled_without_a_deck_dir(live, conn, tmp_path):
    """Only ``mtgo_dir`` is set (no ``mtgo_deck_dir``): its ``grouping *.xml``
    is stored on the first pass, and one that appears later is stored on the
    next beat of the deck clock, while a game log that appears later waits
    for its game to end."""
    share = tmp_path / "mtgo-share"
    put_grouping(share, "one")
    (share / "Match_GameLog_11111111-1111-1111-1111-111111111111.dat").write_bytes(b"first")
    live.mtgo_dir = share
    live.deck_poll_every = 0.0
    assert live.mtgo_deck_dir is None

    live.poll_once(conn)
    assert [label for label, _ in deck_rows(conn)] == ["MtgoDeckGrouping"]
    assert mtgo_row_count(conn) == 1

    put_grouping(share, "two")
    (share / "Match_GameLog_22222222-2222-2222-2222-222222222222.dat").write_bytes(b"second")
    live.poll_once(conn)
    assert len(deck_rows(conn)) == 2
    assert mtgo_row_count(conn) == 1


def test_mtgo_dir_groupings_wait_for_the_deck_clock(live, conn, tmp_path):
    share = tmp_path / "mtgo-share"
    put_grouping(share, "one")
    live.mtgo_dir = share
    live.deck_poll_every = 3600.0

    live.poll_once(conn)
    assert len(deck_rows(conn)) == 1

    put_grouping(share, "two")
    live.poll_once(conn)
    assert len(deck_rows(conn)) == 1


def test_both_folders_are_read_when_both_are_set(live, conn, tmp_path):
    share = tmp_path / "mtgo-share"
    put_grouping(share, "one")
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "exported.dek").write_bytes(DECK_FIXTURE.read_bytes())
    live.mtgo_dir = share
    live.mtgo_deck_dir = exports

    live.poll_once(conn)
    assert sorted(label for label, _ in deck_rows(conn)) == ["MtgoDeckFile", "MtgoDeckGrouping"]


def test_one_folder_set_as_both_is_read_once(live, conn, tmp_path, monkeypatch):
    share = tmp_path / "mtgo-share"
    put_grouping(share, "one")
    live.mtgo_dir = share
    live.mtgo_deck_dir = share
    seen: list[Path] = []
    real = live_module.ingest_deck_dir

    def spy(connection, directory, **kwargs):
        seen.append(directory)
        return real(connection, directory, **kwargs)

    monkeypatch.setattr(live_module, "ingest_deck_dir", spy)
    live.poll_once(conn)
    assert seen == [share]
    assert len(deck_rows(conn)) == 1


def test_an_unreachable_deck_folder_does_not_skip_the_other(live, conn, tmp_path, monkeypatch):
    """Per-folder OSError handling: the failing folder is counted and logged,
    the other is still read, and nothing is raised."""
    share = tmp_path / "mtgo-share"
    put_grouping(share, "one")
    exports = tmp_path / "exports"
    exports.mkdir()
    live.mtgo_deck_dir = exports   # read first, and the one that fails
    live.mtgo_dir = share
    real = live_module.ingest_deck_dir

    def flaky(connection, directory, **kwargs):
        if directory == exports:
            raise OSError("share went away")
        return real(connection, directory, **kwargs)

    monkeypatch.setattr(live_module, "ingest_deck_dir", flaky)
    live.poll_once(conn)
    assert live.stats.errors == 1
    assert live.stats.last_error == "share went away"
    assert [label for label, _ in deck_rows(conn)] == ["MtgoDeckGrouping"]


def test_no_deck_folder_is_a_no_op(live, conn):
    assert live.mtgo_dir is None and live.mtgo_deck_dir is None
    live.poll_once(conn)
    assert deck_rows(conn) == []
    assert live._last_deck_poll is None


def _insert_mtgo_raw_row(conn, *, source_file: str, data: bytes = b"x") -> int:
    """A minimal raw_events row for one MTGO source_file. Content is
    irrelevant: the watcher's dirty checks compare only ids."""
    payload = base64.b64encode(data).decode("ascii")
    digest = hashlib.sha256(f"{source_file}:{len(data)}:{time.time_ns()}".encode()).hexdigest()
    cur = conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, '2026-09-14T12:00:00', 'event', 'MtgoGameLog', ?, 'mtgo')
        """,
        (digest, source_file, payload),
    )
    return cur.lastrowid


def test_duty_factor_default_is_one(live):
    """Pins the new default (live.py's module docstring): changed from 4.0
    (~20% duty cycle) to 1.0 (~50%) once the Current match tab went
    Arena-only (migrations/040_arena_only_current_match.sql) — MTGO no
    longer needs its own off-cadence boundary trick, so the tab's own
    latency became worth trading CPU duty for."""
    assert live.duty_factor == 1.0


def test_an_mtgo_flush_marks_dirty_but_does_not_force_a_rebuild(live, conn):
    """Mirror of test_a_new_match_room_bypasses_the_duty_cycle_gate, with the
    opposite expectation. has_mtgo_boundary (former projector/mtgo/project.py
    check) used to force an immediate rebuild on a new MTGO file; it is
    deleted along with the Current match tab's MTGO support (there is no
    mulligan window left to protect for MTGO), so a flush now behaves like
    any other dirty poll — it waits for the ordinary duty-cycle gate rather
    than forcing an off-cadence rebuild.

    _insert_mtgo_raw_row bypasses live's own ``_poll_mtgo`` (there is no
    ``mtgo_dir`` configured here), so ``live._dirty`` is set by hand to
    stand in for what a real MTGO flush would have left poll_once with —
    the boundary/gate logic below this point is exactly the same either
    way."""
    live.duty_factor = 4.0
    live._last_duration = 16.0
    live.project_every = 3600.0
    live._last_projection = time.monotonic()  # a rebuild "just happened"

    _insert_mtgo_raw_row(conn, source_file="Match_GameLog_aaaa.dat")
    live._dirty = True

    live.poll_once(conn)

    assert live._dirty is True          # still dirty
    assert live.stats.projections == 0  # but nothing forced a rebuild


def test_external_rows_mark_the_watcher_dirty_and_the_next_due_poll_projects_them(live, conn):
    """A hand-run ``sensei-top ingest-mtgo`` (or a separate ``ingest``)
    writes straight to ``raw_events`` from a different connection — nothing
    ``poll_once``'s own two ingest legs did, so its ``inserted`` count stays
    0 even though the table grew. poll_once instead compares raw_events' own
    high-water mark against what this watcher has already projected
    through, and marks itself dirty when it has moved: the mechanism that
    lets a running watcher notice rows an outside process inserted, rather
    than needing its own ``project`` step."""
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)
    assert live.stats.projections == 1
    assert live._dirty is False
    watermark = live._projected_through

    other = open_database(live.db_path)
    try:
        _insert_mtgo_raw_row(other, source_file="Match_GameLog_bbbb.dat")
    finally:
        other.close()

    # Not yet due: the row is noticed (dirty), but the gate still holds the
    # rebuild off — this is not a new boundary exception.
    live.project_every = 3600.0
    live._last_duration = 0.0
    live.poll_once(conn)
    assert live._dirty is True
    assert live._projected_through == watermark
    assert live.stats.projections == 1

    # Due now: the deferred rebuild picks the external row up.
    live.project_every = 0.0
    live.poll_once(conn)
    assert live._dirty is False
    assert live._projected_through > watermark
    assert live.stats.projections == 2


def test_a_failing_poll_does_not_end_the_watch(live, monkeypatch):
    """One bad poll must never stop the watcher (brief §6).

    Two loops now, so this covers both: a failure in ingest_once must not
    end the ingest thread (or the projection loop), and a failure in
    project_if_due must not end the projection loop (or the ingest thread).
    """
    calls = {"ingest": 0, "project": 0}

    def explode_ingest(*_args, **_kwargs):
        calls["ingest"] += 1
        raise RuntimeError("boom")

    def explode_project(*_args, **_kwargs):
        calls["project"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(live, "ingest_once", explode_ingest)
    monkeypatch.setattr(live, "project_if_due", explode_project)
    live.start()
    deadline = time.monotonic() + 5
    while (calls["ingest"] < 2 or calls["project"] < 2) and time.monotonic() < deadline:
        time.sleep(0.02)
    live.stop()

    assert calls["ingest"] >= 2, "ingest loop stopped after the first failure"
    assert calls["project"] >= 2, "projection loop stopped after the first failure"
    assert live.stats.errors >= 4
    assert live.stats.last_error == "boom"


# --- ingest and projection run on separate threads ---------------------------


def test_ingest_proceeds_while_a_rebuild_is_blocked(tmp_path, monkeypatch):
    """The whole point of splitting run_forever in two: a rebuild's write
    lock must never block the next log line from reaching raw_events. This
    has to drive run_forever for real (through start()/stop()), since
    poll_once composes both halves onto one connection and can't exercise
    the concurrency between them."""
    log = tmp_path / "Player.log"
    log.write_text("", newline="")
    db_path = tmp_path / "live.db"
    ingester = LiveIngester(
        db_path=db_path, log_path=log, locale_hint="mdy",
        interval=0.05, project_every=0.0,
    )

    started = threading.Event()
    release = threading.Event()
    real_project = live_module.project

    def blocking_project(conn):
        started.set()
        # Bounded wait, not an unconditional block: if an assertion below
        # fails before release.set() runs, this must not hang the suite.
        release.wait(timeout=5.0)
        real_project(conn)

    monkeypatch.setattr(live_module, "project", blocking_project)

    lines = FIXTURE.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    # The first match room opens at fixture line 9 (fixture_peek.py's index),
    # comfortably inside this first half, so appending it alone forces the
    # boundary rebuild — the same split test_appending_between_polls_is_
    # picked_up already trusts to keep entries intact (each fixture entry is
    # exactly one physical line, so a line-boundary split never cuts one in
    # half).
    half = len(lines) // 2

    ingester.start()
    try:
        append(log, "".join(lines[:half]))
        assert started.wait(timeout=5.0), "boundary rebuild never started"

        check_conn = open_database(db_path)
        try:
            before = check_conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
            append(log, "".join(lines[half:]))

            deadline = time.monotonic() + 5.0
            grew = False
            while time.monotonic() < deadline and not grew:
                time.sleep(0.02)
                count = check_conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
                grew = count > before
            assert not release.is_set(), (
                "the rebuild finished before growth was observed — "
                "this run didn't exercise the overlap it's meant to test"
            )
            assert grew, "ingest did not proceed while the rebuild was still blocked"
        finally:
            check_conn.close()
    finally:
        release.set()
        ingester.stop(timeout=5.0)


def test_dirty_set_during_a_rebuild_survives_it(live, conn, monkeypatch):
    """project_if_due clears _dirty *before* calling project(), not after —
    otherwise a row that lands mid-rebuild (here, simulated by having the
    patched project() itself run ingest_once on a second connection, the way
    the real ingest thread would while a rebuild runs concurrently on the
    other) would be clobbered by a post-rebuild clear and sit unprojected
    until some later, unrelated dirty event happened to arrive."""
    append(live.log_path, FIXTURE.read_text(encoding="utf-8", errors="replace"))
    live.poll_once(conn)
    assert live.stats.projections == 1
    assert live._dirty is False

    other = open_database(live.db_path)
    real_project = live_module.project

    def fake_project(c):
        append(live.log_path, NOISE_REQUEST)
        live.ingest_once(other)   # stands in for the ingest thread's own tick
        real_project(c)

    try:
        monkeypatch.setattr(live_module, "project", fake_project)
        live._dirty = True
        live.project_every = 0.0
        live._last_duration = 0.0
        changed = live.project_if_due(conn, force_project=True)
        assert changed is True
        assert live._dirty is True, "the mid-rebuild ingest's dirty set did not survive"
        assert live.stats.projections == 2

        # Not stuck dirty forever: a later due tick rebuilds again and picks
        # up the row the mid-rebuild ingest landed (project() is always a
        # full rebuild, so it doesn't matter that _projected_through was
        # snapshotted before that row existed).
        monkeypatch.setattr(live_module, "project", real_project)
        live.project_every = 0.0
        live._last_duration = 0.0
        live.poll_once(conn)
        assert live._dirty is False
        assert live.stats.projections == 3
    finally:
        other.close()


def test_only_the_watchers_startup_migrates(tmp_path, monkeypatch):
    """run_forever applies migrations once, before it starts the ingest
    thread; that thread's own connection (and any retry of it, arbitrarily
    long into a serve session) must not — a migration file that appears in
    the working tree mid-session would otherwise go live under old code."""
    log = tmp_path / "Player.log"
    log.write_text("", newline="")
    db_path = tmp_path / "live.db"
    ingester = LiveIngester(
        db_path=db_path, log_path=log, locale_hint="mdy",
        interval=0.02, project_every=0.0,
    )

    real_migrate = db.migrate
    migrated_on: list[str] = []

    def recording_migrate(conn, *args, **kwargs):
        migrated_on.append(threading.current_thread().name)
        return real_migrate(conn, *args, **kwargs)

    monkeypatch.setattr(db, "migrate", recording_migrate)

    ingester.start()
    try:
        append(log, FIXTURE.read_text(encoding="utf-8", errors="replace"))
        check_conn = db.connect(db_path)
        try:
            deadline = time.monotonic() + 5.0
            count = 0
            while time.monotonic() < deadline and count == 0:
                time.sleep(0.02)
                try:
                    count = check_conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
                except sqlite3.OperationalError as exc:
                    # The watcher thread migrates; until it has, nothing is ingested.
                    if "no such table" not in str(exc):
                        raise
            assert count > 0, "the ingest thread never ingested"
        finally:
            check_conn.close()
    finally:
        ingester.stop(timeout=5.0)

    assert len(migrated_on) == 1
    assert "mtga-live-ingest" not in migrated_on


def test_ingest_thread_retries_after_a_failed_open(tmp_path, monkeypatch):
    """_ingest_loop's connect call now lives inside the loop's own
    error handling rather than before it — a locked database
    or a permissions error must not kill the ingest thread silently while
    run_forever's own loop keeps stats.running True. run_forever itself also
    opens a connection (for the projection loop), so the failure has to be
    targeted at the ingest thread's own open specifically."""
    log = tmp_path / "Player.log"
    log.write_text("", newline="")
    db_path = tmp_path / "live.db"
    ingester = LiveIngester(
        db_path=db_path, log_path=log, locale_hint="mdy",
        interval=0.02, project_every=0.0,
    )

    real_open_database = live_module.open_database
    real_connect = live_module.connect
    failed = threading.Event()

    def flaky_connect(path):
        if threading.current_thread().name == "mtga-live-ingest" and not failed.is_set():
            failed.set()
            raise OSError("locked")
        return real_connect(path)

    monkeypatch.setattr(live_module, "connect", flaky_connect)

    ingester.start()
    try:
        assert failed.wait(timeout=5.0), "the ingest thread's first open never ran"
        append(log, FIXTURE.read_text(encoding="utf-8", errors="replace"))

        check_conn = real_open_database(db_path)
        try:
            deadline = time.monotonic() + 5.0
            count = 0
            while time.monotonic() < deadline and count == 0:
                time.sleep(0.02)
                count = check_conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
            assert count > 0, "the ingest thread never recovered from the failed open"
        finally:
            check_conn.close()
    finally:
        ingester.stop(timeout=5.0)

    assert ingester.stats.errors >= 1


# --- serve's watcher process dies with serve ---------------------------------


def descendants(pid: int) -> list[int]:
    """Every process below ``pid``, read from /proc (Linux)."""
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_bytes()
        except OSError:  # exited while the scan ran
            continue
        # The command name sits in parentheses, may itself hold ") ", and is
        # bytes in no promised encoding.
        parent = int(stat[stat.rindex(b")") + 2 :].split()[1])
        children.setdefault(parent, []).append(int(entry.name))
    found: list[int] = []
    queue = [pid]
    while queue:
        below = children.get(queue.pop(), [])
        found.extend(below)
        queue.extend(below)
    return found


def running(pid: int) -> bool:
    """A zombie has already died; only its new parent has yet to reap it."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_bytes()
    except OSError:
        return False
    state = stat.rindex(b")") + 2
    return stat[state : state + 1] != b"Z"


@pytest.fixture
def watched_serve(tmp_path, request):
    """``serve --watch`` as its own process, on a temp database, an empty log
    and a free loopback port, with every download off. Yields the process,
    the processes below it (the watcher), and the file holding its output,
    once it accepts connections: by then uvicorn has its signal handlers.
    Its own session, so a test can send Ctrl+C to the group a console would.
    Anything still running at teardown is killed, so a failing test leaves no
    watcher behind either.

    Parametrized indirectly with ``"unreadable log"``, the log is a directory
    instead, which every one of the watcher's ingest polls fails to read and
    warns about. Its local time is fourteen hours ahead of UTC (POSIX ``TZ``
    inverts the sign), so a local timestamp in its log file could never pass
    for a UTC one."""
    log = tmp_path / "Player.log"
    if getattr(request, "param", None) == "unreadable log":
        log.mkdir()
    else:
        log.write_text("", newline="")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    output = tmp_path / "serve.out"
    command = [
        sys.executable, "-m", "sensei_top.cli", "--db", str(tmp_path / "serve.db"),
        "serve", "--watch", "--file", str(log), "--port", str(port),
        "--no-mtgo", "--no-backup", "--no-corpus-refresh",
        "--no-archetype-refresh", "--no-reference-refresh",
    ]
    # A file, not a pipe: an orphaned watcher holds serve's output open, so
    # reading a pipe to its end would wait on the orphan forever.
    with output.open("wb") as sink:
        serve = subprocess.Popen(
            command,
            stdout=sink,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "TZ": "<+14>-14"},
        )
    watchers: list[int] = []
    try:
        listening = False
        deadline = time.monotonic() + 30
        while not listening and serve.poll() is None and time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    listening = True
            except OSError:
                time.sleep(0.05)
        if not listening:
            pytest.fail(f"serve never listened:\n{output.read_text(errors='replace')[-2000:]}")
        watchers = descendants(serve.pid)
        assert watchers, "serve --watch started no watcher"
        yield serve, watchers, output
    finally:
        if serve.poll() is None:
            serve.kill()
            serve.wait()
        for pid in watchers:
            if running(pid):
                os.kill(pid, signal.SIGKILL)


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="reads /proc; on Windows windows-runner kills serve with taskkill /F instead",
)
@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGKILL"])
def test_serve_leaves_no_watcher_behind(watched_serve, signal_name):
    """SIGTERM orphaned the watcher: uvicorn re-raises it once its shutdown
    is done, and the default action ended serve before cmd_serve's finally
    could stop the child. SIGKILL runs nothing in serve at all, so only the
    kernel can end the child. A watcher left behind keeps writing, and the
    next serve starts a second one beside it: two watchers upsert one
    projection_state row and run the same rebuild against SQLite's single
    writer (live.py's docstring)."""
    serve, watchers, _ = watched_serve

    serve.send_signal(getattr(signal, signal_name))
    serve.wait(timeout=30)

    deadline = time.monotonic() + 10
    while any(running(pid) for pid in watchers) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert [pid for pid in watchers if running(pid)] == []


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc; signals a process group")
def test_ctrl_c_ends_serve_and_its_watcher_quietly(watched_serve):
    """A console's Ctrl+C reaches every process in the foreground group, the
    watcher as well as serve, and the watcher's KeyboardInterrupt printed a
    traceback over serve's last lines. A clean exit is exit status 0 with no
    traceback."""
    serve, watchers, output = watched_serve

    os.killpg(serve.pid, signal.SIGINT)
    serve.wait(timeout=30)

    deadline = time.monotonic() + 10
    while any(running(pid) for pid in watchers) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert [pid for pid in watchers if running(pid)] == []
    text = output.read_text(errors="replace")
    assert serve.returncode == 0, text[-2000:]
    assert "Traceback" not in text


LOG_LINE = re.compile(
    r"(?P<stamp>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3})Z (?P<session>[0-9a-f]{8}) "
    r"(?P<level>[A-Z]+) (?P<name>\S+): (?P<message>.*)"
)


def open_files(pid: int) -> set[str]:
    """What process ``pid`` holds open, read from /proc (Linux)."""
    held = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            held.add(os.readlink(fd))
        except OSError:  # closed while the scan ran
            continue
    return held


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc")
@pytest.mark.parametrize("watched_serve", ["unreadable log"], indirect=True)
def test_the_watchers_warnings_land_in_serves_log_file(watched_serve, tmp_path):
    """Only serve writes the log file (logs.py, trap 5): a watcher with a
    handle of its own would be a second process rotating it. What the child
    logs crosses to serve through a queue and is written there, under
    serve's session id and in UTC, like serve's own lines. The warning is
    the child's: serve runs no ingest poll of its own."""
    serve, watchers, _ = watched_serve
    path = tmp_path / "logs" / "sensei-top.log"

    def polled(line: re.Match[str]) -> bool:
        return line["message"].startswith("live ingest poll failed")

    found: list[re.Match[str]] = []
    deadline = time.monotonic() + 30
    while not any(polled(line) for line in found) and time.monotonic() < deadline:
        time.sleep(0.1)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        found = [m for line in text.splitlines() if (m := LOG_LINE.fullmatch(line))]
    now = datetime.now(UTC)

    assert found, "serve wrote no log file"
    header = found[0]
    db = (tmp_path / "serve.db").resolve()
    shown = f"~{os.sep}{db.relative_to(Path.home())}" if db.is_relative_to(Path.home()) else db
    assert header["message"].startswith("started sensei-top ")
    assert " (serve) on " in header["message"]
    assert header["message"].endswith(f", database {shown}")
    stamp = datetime.strptime(header["stamp"], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=UTC)
    assert now - timedelta(minutes=5) <= stamp <= now
    warned = [line for line in found if polled(line)]
    assert warned, "the watcher's warning never reached the file"
    assert {(line["level"], line["name"]) for line in warned} == {("WARNING", "sensei_top.live")}
    assert {line["session"] for line in found} == {header["session"]}
    held = str(path.resolve())
    assert held in open_files(serve.pid)
    for pid in watchers:
        assert held not in open_files(pid)


def test_the_apps_shutdown_stops_its_watcher(tmp_path, make_client):
    """The shutdown is the one hook that runs on a SIGTERM: uvicorn re-raises
    the signal after it, and the process ends before cmd_serve's finally. On
    Linux and Windows the kernel would still end a watcher left running, but
    only once serve was gone; on macOS nothing would."""

    class Watcher:
        stops = 0

        def is_alive(self) -> bool:
            return True

        def stop(self) -> None:
            self.stops += 1

    watcher = Watcher()
    with make_client(create_app(tmp_path / "unused.db", watcher=watcher)):
        assert watcher.stops == 0
    assert watcher.stops == 1


def projected(db_path: Path) -> bool:
    """Whether the watcher has finished a projection. Read-only, so it never
    creates the database before the watcher does."""
    try:
        with contextlib.closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as c:
            row = c.execute("SELECT projections FROM projection_state WHERE id = 1").fetchone()
    except sqlite3.Error:  # not created or not migrated yet
        return False
    return bool(row and row[0])


@pytest.fixture
def watcher_process(tmp_path):
    """A ``WatcherProcess`` over a scratch copy of a small Arena capture,
    started, and running past its first projection: by then its bridging
    thread has long been waiting for the stop signal, the state a group
    SIGTERM finds it in. Stopped at teardown whatever the test did."""
    log = tmp_path / "Player.log"
    shutil.copyfile(FIXTURE, log)
    watcher = live_module.WatcherProcess(
        db_path=tmp_path / "live.db",
        log_path=log,
        locale_hint="mdy",
        interval=0.05,
        project_every=0.0,
    )
    watcher.start()
    process = watcher._process
    try:
        deadline = time.monotonic() + 30
        while not projected(watcher.db_path) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert projected(watcher.db_path), "the watcher process never projected"
        yield watcher, process
    finally:
        if process.is_alive():
            process.kill()
        stopper = threading.Thread(target=watcher.stop, daemon=True)
        stopper.start()
        stopper.join(timeout=15)


def stop_within(watcher: live_module.WatcherProcess, seconds: float) -> float:
    """``stop()`` on a thread, so a regression fails the test instead of
    hanging the suite. Returns how long it took."""
    started = time.monotonic()
    stopper = threading.Thread(target=watcher.stop, daemon=True)
    stopper.start()
    stopper.join(timeout=seconds)
    assert not stopper.is_alive(), f"stop() still blocked after {seconds} s"
    return time.monotonic() - started


def test_stop_ends_a_running_watcher_process_without_terminating_it(watcher_process):
    """The stop signal reaches the child and run_forever returns: exit code
    0, where a child stop() had to terminate would show -SIGTERM."""
    watcher, process = watcher_process

    stop_within(watcher, 15)

    assert process.exitcode == 0
    assert watcher._process is None
    assert watcher._log_queue is None


@pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL is POSIX")
def test_stop_returns_after_the_watcher_process_died(watcher_process):
    """A group SIGTERM kills the child while its bridging thread sleeps on
    the stop signal. With a multiprocessing.Event that thread stayed counted
    as a sleeper that would never wake, and set() blocked forever waiting
    for it: every stop after the child had died, however it died, hung
    serve. stop()'s own waits are bounded (5 s for the join, 5 s for the
    drain), and a dead child should need neither."""
    watcher, process = watcher_process

    os.kill(process.pid, signal.SIGKILL)
    # Not process.join(): the monitor reaps the child, and two joiners race.
    watcher._monitor.join(timeout=10)
    assert not watcher._monitor.is_alive()
    assert process.exitcode == -signal.SIGKILL

    elapsed = stop_within(watcher, 15)

    assert elapsed < 10
    assert watcher._process is None
    assert watcher._log_queue is None
    assert watcher._stop_conn is None


STOP_AFTER_DEATH = """\
import logging, os, signal, sqlite3, sys, time
from pathlib import Path

from sensei_top.live import WatcherProcess


def projected(db_path):
    try:
        c = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        try:
            row = c.execute("SELECT projections FROM projection_state WHERE id = 1").fetchone()
        finally:
            c.close()
    except sqlite3.Error:
        return False
    return bool(row and row[0])


if __name__ == "__main__":
    db_path, log_path = Path(sys.argv[1]), Path(sys.argv[2])
    hold_lock = sys.argv[3:] == ["hold-lock"]
    # Before start(): the drain writes through the handlers it finds then.
    logging.basicConfig(level=logging.INFO)
    watcher = WatcherProcess(
        db_path=db_path, log_path=log_path, locale_hint="mdy",
        interval=0.05, project_every=0.0,
    )
    watcher.start()
    deadline = time.monotonic() + 15
    while not projected(db_path) and time.monotonic() < deadline:
        time.sleep(0.05)
    if not projected(db_path):
        sys.exit("the watcher process never projected")
    if hold_lock:
        # Stands in for a child that died holding the queue's write lock:
        # nothing releases it before this process exits.
        watcher._log_queue._wlock.acquire()
    os.kill(watcher._process.pid, signal.SIGKILL)
    watcher._process.join(timeout=5)
    watcher.stop()
"""


@pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL is POSIX")
def test_a_process_whose_watcher_died_still_exits(tmp_path):
    """The real hang's shape, end to end: start, the child killed, stop,
    and the interpreter's exit, where multiprocessing joins what it still
    holds. serve hung on all ten group SIGTERMs of a scratch run."""
    log = tmp_path / "Player.log"
    shutil.copyfile(FIXTURE, log)
    script = tmp_path / "stop_after_death.py"
    script.write_text(STOP_AFTER_DEATH, encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "live.db"), str(log)],
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert done.returncode == 0, done.stderr[-2000:]


@pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL is POSIX; no write lock on Windows")
def test_a_process_whose_watcher_died_holding_the_queue_lock_still_exits(tmp_path):
    """A child killed mid-write dies holding the log queue's write lock,
    shared across processes on POSIX. The drain's sentinel then starts this
    process's feeder thread, which waits for that lock forever, and
    multiprocessing would join the feeder at exit. stop() gives up on the
    drain after its bounded wait, cancels that join, and says records may
    be lost."""
    log = tmp_path / "Player.log"
    shutil.copyfile(FIXTURE, log)
    script = tmp_path / "stop_after_death.py"
    script.write_text(STOP_AFTER_DEATH, encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "live.db"), str(log), "hold-lock"],
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert done.returncode == 0, done.stderr[-2000:]
    assert (
        "The watcher process was killed mid-write; its last log records may be lost."
        in done.stderr
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
def test_closing_the_job_kills_the_process_in_it():
    """What taskkill /F on serve does to the watcher: the kernel closes a
    killed process's handles, and closing the last handle to a kill-on-close
    job ends every process in it."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        job = procs.kill_with_this_process(child.pid)
        assert job is not None
        assert child.poll() is None, "joining the job must not end the process"
        procs.close_job(job)
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL is POSIX")
def test_a_child_that_dies_on_its_own_is_noticed(watcher_process, caplog):
    """The monitor logs one ERROR with the exit code, and the watcher reports
    the death, so /api/live can say so."""
    watcher, process = watcher_process
    assert watcher.stopped_unexpectedly() is False

    with caplog.at_level(logging.ERROR, logger=live_module.log.name):
        os.kill(process.pid, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while not watcher.stopped_unexpectedly() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert watcher.stopped_unexpectedly()
        watcher._monitor.join(timeout=5)
        assert not watcher._monitor.is_alive()

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].getMessage() == (
        f"The watcher process stopped unexpectedly (exit code {-signal.SIGKILL}); "
        "nothing new is being read until the tracker restarts."
    )
    assert watcher.exit_code == -signal.SIGKILL


def test_a_stop_asked_for_first_is_not_an_unexpected_death(watcher_process, caplog):
    watcher, _ = watcher_process
    monitor = watcher._monitor

    with caplog.at_level(logging.ERROR, logger=live_module.log.name):
        stop_within(watcher, 15)
        monitor.join(timeout=5)
        assert not monitor.is_alive()

    assert [r for r in caplog.records if r.levelno == logging.ERROR] == []
    assert watcher.stopped_unexpectedly() is False
    assert watcher.exit_code is None


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM kills a child outright on POSIX")
def test_a_group_sigterm_then_stop_is_a_normal_shutdown(watcher_process, caplog):
    """A group SIGTERM kills the child before the lifespan's stop() runs; the
    monitor must give stop() a moment rather than report a death."""
    watcher, process = watcher_process
    monitor = watcher._monitor

    with caplog.at_level(logging.ERROR, logger=live_module.log.name):
        os.kill(process.pid, signal.SIGTERM)
        # Not process.join(): the monitor reaps the child, and two joiners race.
        assert multiprocessing.connection.wait([process.sentinel], timeout=10)
        # Gives a monitor without the grace time to log, so the assertions below catch it.
        time.sleep(0.1)
        assert watcher.stopped_unexpectedly() is False
        stop_within(watcher, 15)
        monitor.join(timeout=5)
        assert not monitor.is_alive()

    assert [r for r in caplog.records if r.levelno == logging.ERROR] == []
    assert watcher.stopped_unexpectedly() is False


# --- where the watcher finds Arena's log (plan 6, D11) ----------------------
#
# $MTGA_LOG, then [arena] log, then autodetection; a configured file that does
# not exist yet is passed over, so the 60 s re-resolution picks it up later.


def _logs(tmp_path: Path) -> tuple[Path, Path, Path]:
    paths = []
    for name in ("autodetected", "configured", "env"):
        path = tmp_path / name / "Player.log"
        path.parent.mkdir()
        path.write_text("", encoding="utf-8")
        paths.append(path)
    return tuple(paths)


def test_resolve_arena_log_reads_arena_after_mtga_log(tmp_path, monkeypatch):
    from sensei_top import cli as cli_module

    autodetected, configured, from_env = _logs(tmp_path)
    monkeypatch.setattr(live_module, "default_log_path", lambda: autodetected)

    assert live_module.resolve_arena_log() == autodetected
    cli_module._write_arena_config(log=str(configured))
    assert live_module.resolve_arena_log() == configured
    monkeypatch.setenv("MTGA_LOG", str(from_env))
    assert live_module.resolve_arena_log() == from_env


def test_resolve_arena_log_passes_over_a_configured_log_not_there_yet(tmp_path, monkeypatch):
    from sensei_top import cli as cli_module

    autodetected, _, _ = _logs(tmp_path)
    monkeypatch.setattr(live_module, "default_log_path", lambda: autodetected)
    later = tmp_path / "later" / "Player.log"
    cli_module._write_arena_config(log=str(later))

    assert live_module.resolve_arena_log() == autodetected
    later.parent.mkdir()
    later.write_text("", encoding="utf-8")
    assert live_module.resolve_arena_log() == later
