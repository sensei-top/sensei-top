"""M4 live-mode tests.

``poll_once`` is driven directly rather than through the thread: the loop is
five lines around it, and testing the timing behaviour by sleeping would make
the suite slow and flaky. The thread itself is covered by a start/stop test.
"""

import base64
import hashlib
import threading
import time
from pathlib import Path

import pytest

from sensei_top import db
from sensei_top import live as live_module
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
    with path.open("a", newline="") as handle:
        handle.write(text)


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


def test_mtgo_reads_once_at_startup_and_never_again(live, conn, tmp_path):
    """The MTGO leg is one-shot (live.py's ``_poll_mtgo``) — it ingests
    whatever is on disk on this process's first poll, and does nothing on
    every poll after, even once a new match's file appears."""
    mtgo_dir = tmp_path / "mtgo-share"
    mtgo_dir.mkdir()
    live.mtgo_dir = mtgo_dir

    first_dat = mtgo_dir / "Match_GameLog_11111111-1111-1111-1111-111111111111.dat"
    first_dat.write_bytes(b"first-payload")

    live.poll_once(conn)
    assert mtgo_row_count(conn) == 1

    # A second match's file, created only after the startup read: still not
    # picked up on any later poll, because the leg never polls again.
    second_dat = mtgo_dir / "Match_GameLog_22222222-2222-2222-2222-222222222222.dat"
    second_dat.write_bytes(b"second-payload")
    for _ in range(3):
        live.poll_once(conn)
    assert mtgo_row_count(conn) == 1


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
    next beat of the deck clock, while the game logs keep their read-once
    rule."""
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
                count = check_conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
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
