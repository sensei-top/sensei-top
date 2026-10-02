"""M4: live mode — keep the database current while Arena is running.

This is the orchestration layer, and the only module that drives both stages of
the pipeline. The reader still knows nothing about Arena semantics and the
projector still knows nothing about files; ``LiveIngester`` simply runs one
after the other, each on its own timer (see "Two cadences" below).

Two cadences, deliberately different, and — since the rebuild's own write lock
was measured taking 5.7 s on a real database — now two threads, not one:

* **Ingest** runs often (default 1 s), on its own thread and its own
  connection. It is cheap — a seek to the stored byte offset and a read of
  whatever is new — and running it often is what keeps the reader from
  falling behind a log that Arena may truncate at any moment. It used to
  share a thread with projection, which meant a rebuild's write lock (or its
  parse phase, holding no lock but still running on the same thread) blocked
  every new log line from reaching ``raw_events`` until the rebuild
  finished — the exact latency the Current match tab's mulligan read cannot
  afford (see the match-boundary exception below). ``run_forever`` now runs
  ``ingest_once`` on a dedicated thread with its own SQLite connection, so a
  rebuild in progress on the calling thread never delays the next line from
  landing.
* **Projection** runs at least every ``project_every`` seconds (default 5 s) —
  a floor, not the beat (see below). It is a *full rebuild* by design (see
  ``projector.matches``), so its cost grows with total history rather than
  with the new rows: an early measurement put it at ~0.28 s over 4,595
  events (~60 µs/event); a season's worth of play (~173k raw events,
  ~800 MB) measured ~11.6 s; the database has since grown to 238,520 events
  (~1.33 GB), measuring **~16.2 s** a rebuild — parsing every payload with
  ``orjson`` is ~9.7 s of that (down from ~12.5 s once ``project()`` stopped
  calling ``orjson.loads`` once per projector per row and started parsing
  each row exactly once; dispatch and the SQL writes account for the rest).
  Either way, the rebuild has been longer than ``project_every`` for a while
  now. Left alone, that means the rebuild simply runs back-to-back — it did,
  measured: every dirty poll found ``elapsed >= project_every`` already
  true, pinning a core continuously for the life of the process. Instead,
  ``poll_once``'s gate paces rebuilds to a fixed *duty cycle*: ``gate =
  max(project_every, _last_duration * duty_factor)``, where ``duty_factor``
  (default 1.0, CLI ``--duty-factor``) means the watcher rests roughly
  ``duty_factor`` times as long as the *previous* rebuild took before
  starting the next one — a ~50% duty cycle at the default, so the
  rebuild's wall-time cost stays a fixed fraction of real time as history
  grows, rather than consuming a whole core for the rest of the session.
  (The default was 4.0/~20% until the Current match tab went Arena-only —
  see the "One named exception" note below — at which point the tab's own
  latency became worth trading for: dropping to 1.0 roughly halves a
  measured 145 s round trip between two Arena rebuilds to ~58 s, at double
  the CPU duty.)
  Anything read from ``turns``/``matches`` (the current-match tab included)
  is correspondingly stale by roughly one gate interval, not one rebuild
  duration. **This is also why ``serve --watch`` runs the watcher in a
  separate OS process (``WatcherProcess``, below) rather than a thread**: a
  rebuild that never stops running would otherwise contend for this
  interpreter's GIL with every API request, indiscriminately, not just
  requests touching stale data — measured at a ~5x tax on
  ``/api/current-match/read`` (``WatcherProcess``'s own docstring has the
  numbers). That growth is also what ``table/live.py`` and
  ``table/opening_hand.py`` exist to route around for the live tab: a
  request-time replay bounded to the *current match alone* (990-4,276
  events on the same database) costs 0.03-0.08 s regardless of how much
  history sits behind it. Re-running the full rebuild on every ingest would
  still be wasted work today and unaffordable after a year of play, so new
  rows mark the projection dirty and a later tick does the work. Naming the
  opponents' decks happens in the same step, because a rebuild erases the
  previous answers along with everything else derived.

  **One named exception to the gate**, forcing an immediate rebuild
  regardless of ``project_every``/``duty_factor``: a match room opening
  (``has_match_boundary``). It is what puts a deck on the Current match tab, and
  ``table/opening_hand.py``'s pending-mulligan read needs that deck within
  the ~11 seconds real captures show between the room opening and the first
  hand offer — waiting out even the ``project_every`` floor on top of that
  would eat a meaningful slice of the 5-second median decision window, let
  alone a duty-cycle gate that can now legitimately stay open for a minute
  or more. That boundary rebuild no longer delays the offer it exists for:
  since ingest runs on its own thread (above), the mulligan offer itself
  still lands in ``raw_events`` within one ``interval`` even while the
  rebuild the room opening triggered is still running on the other thread —
  only the *projected* view of that offer (``matches``/``turns``, and
  therefore ``v_current_match.deck_id``) waits on the rebuild, and
  ``table/live.py``'s own replay of ``raw_events`` (rather than the
  projection) is what routes the opening-hand read around that wait
  entirely. A completed match carries the same event type and gets the same
  early rebuild, which is a bonus, not a special case worth excluding. The
  boundary check scans ``raw_events`` after the watermark of the last
  committed rebuild (``_projected_through``), which ``project_if_due``
  persists to ``projection_state.projected_through_id``
  and restores on the first poll of a fresh ``LiveIngester`` — without that,
  a process restart would reset the watermark to 0 and force the first
  boundary check on a long-running database to scan every row ever ingested
  instead of just the recent tail.

  **There used to be two more: ``has_draft_boundary``, deleted with draft
  (2026-10-01), and ``has_mtgo_boundary``, deleted earlier.** The MTGO one
  forced an immediate rebuild on a *new* MTGO match file so a new MTGO match
  would hit the Current match tab inside its mulligan window. That window no
  longer exists: the tab is Arena-only now (``v_current_match``,
  ``migrations/040_arena_only_current_match.sql``), so an MTGO match can
  never become "current" regardless of how fast it is projected.

  **MTGO reads once, at the watcher's own startup, and never again.** It used
  to poll its own share on a slower clock of its own (default 5 s, against a
  measured ~7.4 s MTGO flush cadence — 28 size changes over 208 s of a real
  in-progress match, ``.claude/handoffs/mtgo-source.md``). But every MTGO
  flush rewrites the whole ``.dat`` file, so every poll that caught one
  inserted another full-file-prefix ``raw_events`` row (~28 per match,
  ``reader/mtgo.py``'s docstring) and marked the projection dirty — keeping
  the ~16 s rebuild running at the duty cycle's own pace for the entire
  length of an MTGO session, CPU spent against a source that, since
  migration 040, can never land on the one tab that latency was ever bought
  for. ``_poll_mtgo`` now runs ``ingest_mtgo_dir`` exactly once, on this
  process's first ``ingest_once`` call (tracked by ``_mtgo_read``, not a
  timer field), and is a no-op on every call after — regardless of whether
  that first attempt found anything or failed, so a missing share or a bad
  read is retried at the next process start, not on the next poll. A match
  played later in a long-running session arrives by hand
  (``sensei-top ingest-mtgo``) or at the next ``serve --watch`` restart —
  see the external-rows check in ``project_if_due`` below for how a running
  watcher still notices and rebuilds for those hand-run rows without a
  separate ``project`` step.

  **MTGO's deck files are the exception: they are polled**
  (``_poll_mtgo_decks``, every ``DECK_POLL_SECONDS``), in two places: the
  ``.dek`` exports in ``mtgo_deck_dir`` and the ``grouping *.xml`` deck store
  in ``mtgo_dir`` itself, whose game logs keep the read-once rule above. A
  deck file changes only when the user saves one, so an idle poll writes
  nothing (``ingest_state`` skips unchanged files) and the rebuild is not kept
  running; a just-exported deck shows up without a restart.

Nothing here holds a transaction open across polls: readers (the API) see the
previous snapshot until each rebuild commits, so the dashboard never renders a
half-rebuilt projection.

MTGO is a second, independent ingest leg on the same ``LiveIngester``, not a
second watcher (see ``_poll_mtgo`` and the ``mtgo_dir`` field below): two
processes would both upsert the ``projection_state`` id=1 singleton,
ping-ponging ``projected_through_id`` so a boundary could be silently missed,
and both would run the same ~16 s rebuild against SQLite's single writer
(``busy_timeout=5000``) for byte-identical output.
"""

from __future__ import annotations

import logging
import multiprocessing
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from sensei_top.archetypes import classify_matches
from sensei_top.db import connect, open_database
from sensei_top.llm.provenance import now_iso as _now
from sensei_top.projector.matches import has_match_boundary, project
from sensei_top.reader.ingest import ingest_file, ingest_with_recovery
from sensei_top.reader.mtgo import ingest_mtgo_dir
from sensei_top.reader.mtgo_decks import ingest_deck_dir

log = logging.getLogger(__name__)

# How often the MTGO deck folder is read, in seconds (plan 12, D8). The
# default of ``LiveIngester.deck_poll_every``, and the number ``cli.py`` tells
# the user: one place, so the three cannot drift apart.
DECK_POLL_SECONDS = 30.0


def _same_folder(a: Path, b: Path) -> bool:
    """True when two configured folders are one place. Never raises: a path
    that cannot be resolved (a dead mount) is compared as written."""
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


@dataclass
class LiveStats:
    """Observable state of the watcher. Read from other threads, so it holds
    only plain immutable values — no partially-built structures."""

    running: bool = False
    polls: int = 0
    events_ingested: int = 0
    projections: int = 0
    last_ingest_at: str | None = None
    last_projection_at: str | None = None
    last_error: str | None = None
    errors: int = 0


@dataclass
class LiveIngester:
    """Polls the log, ingesting always and re-projecting on a slower beat.

    ``run_forever`` drives ``ingest_once`` and ``project_if_due`` on two
    separate threads (see the module docstring's "Two cadences" section);
    ``poll_once`` still composes both on a single connection for callers —
    mainly tests — that want one deterministic step."""

    db_path: Path
    log_path: Path
    locale_hint: str | None = None
    interval: float = 1.0
    # None means "this machine has no MTGO share", the normal case. log_path
    # keeps its exact meaning unchanged: Arena's Player.log, nothing else.
    mtgo_dir: Path | None = None
    # The MTGO deck-export folder, polled on its own clock
    # (``_poll_mtgo_decks``), unlike ``mtgo_dir``'s read-once rule for game
    # logs. ``mtgo_dir``'s ``grouping *.xml`` files ride the same poll.
    # None means none configured.
    mtgo_deck_dir: Path | None = None
    deck_poll_every: float = DECK_POLL_SECONDS
    project_every: float = 5.0
    project_enabled: bool = True
    # project_every is a floor, not the beat: once a rebuild outlasts it the
    # watcher would otherwise run back-to-back forever (it did, measured at
    # 16.2 s a rebuild against a 5 s project_every on a 238k-event database —
    # every dirty poll found elapsed >= project_every already true). The gate
    # in poll_once instead holds the watcher to roughly a 1/duty_factor duty
    # cycle: sleep duty_factor times as long as the *last* rebuild took, so
    # its cost stays a fixed fraction of wall time as history grows, rather
    # than consuming a whole core continuously. 1.0 is a ~50% duty cycle.
    duty_factor: float = 1.0

    stats: LiveStats = field(default_factory=LiveStats)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _recovered: bool = field(default=False, repr=False)
    _dirty: bool = field(default=False, repr=False)
    _last_projection: float = field(default=0.0, repr=False)
    # How long the last rebuild (project() + classify_matches()) actually
    # took, in seconds — what the adaptive gate above paces off of. 0.0 until
    # the first rebuild completes, which is why the gate falls back to the
    # project_every floor until then.
    _last_duration: float = field(default=0.0, repr=False)
    # The raw_events id projected through as of the last rebuild — the
    # watermark has_match_boundary checks against to decide whether a new
    # match room has opened since. Restored from projection_state on the
    # first poll_once call (see _watermark_loaded below) rather than always
    # starting at 0, so a restart doesn't force the first boundary check to
    # LIKE-scan every row ever ingested.
    _projected_through: int = field(default=0, repr=False)
    _watermark_loaded: bool = field(default=False, repr=False)
    # Set the first time _poll_mtgo runs (whether or not it found or ingested
    # anything, and even on a failed read — see _poll_mtgo). MTGO is read
    # once, at this process's own startup, and never again for the rest of
    # the session.
    _mtgo_read: bool = field(default=False, repr=False)
    # time.monotonic() of the last deck-file read (both folders); None until
    # the first one, which therefore happens on this instance's first
    # ingest_once.
    _last_deck_poll: float | None = field(default=None, repr=False)
    # Guards every LiveStats mutation: run_forever updates it from both the
    # ingest thread and the calling (projection) thread. Read-only access —
    # tests reading live.stats.whatever between poll_once calls — needs no
    # lock, since nothing else is running at the same time in that case.
    _stats_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # Guards read-modify-write access to _dirty from run_forever's two
    # threads. _dirty itself stays a plain bool (not a threading.Event) so
    # tests can keep reading and setting it directly, the way they already
    # do — there is only ever one thread touching it in a test, so the lock
    # is never contended there.
    _dirty_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- one pass ----------------------------------------------------------

    def _poll_mtgo(self, conn: sqlite3.Connection) -> int:
        """Ingest the MTGO game-log directory once, on this process's first
        poll, and do nothing on every poll after. A no-op when ``mtgo_dir``
        is ``None`` (no MTGO share on this machine — the normal case).

        One-shot rather than polled: MTGO rewrites its ``.dat`` file whole on
        every flush, so a leg that kept polling would insert another
        full-file-prefix ``raw_events`` row (~28 per match, ``reader/mtgo.py``)
        and mark the projection dirty on every one of those flushes, keeping
        the ~16 s rebuild running at the duty cycle's own pace for the whole
        length of an MTGO session — CPU spent for a source that can never
        land on the Current match tab that latency matters for (Arena-only
        since ``migrations/040_arena_only_current_match.sql``). A match
        played later in a long session arrives by hand
        (``sensei-top ingest-mtgo``) or at the next restart; see
        ``project_if_due``'s external-rows check for how a running watcher
        still notices and rebuilds for rows inserted that way.

        Must never raise (non-negotiable #4): the virtiofs share this
        project's MTGO transport uses can vanish mid-session (unmounted,
        torn down, a VM stopped) and that must not end the Arena watch.
        ``ingest_mtgo_dir`` already tolerates a single file going missing
        internally; this catches the coarser failure — the whole directory
        becoming unreachable (e.g. ``directory.glob()`` itself raising on a
        dead mount) — the same way ``run_forever``'s outer loop guards
        against a bad poll ending the whole watch. ``_mtgo_read`` is set
        before the attempt, not after, so a failed startup read is retried at
        the next process start rather than on every following poll.
        """
        if self.mtgo_dir is None or self._mtgo_read:
            return 0
        self._mtgo_read = True
        try:
            return ingest_mtgo_dir(conn, self.mtgo_dir).rows_inserted
        except OSError as exc:
            with self._stats_lock:
                self.stats.errors += 1
                self.stats.last_error = str(exc)
            log.warning("mtgo poll failed: %s", exc)
            return 0

    def _deck_folders(self) -> list[Path]:
        """The folders ``_poll_mtgo_decks`` reads: ``mtgo_deck_dir`` (the
        user's exported ``.dek`` files) and ``mtgo_dir`` (where MTGO keeps its
        deck store, ``grouping *.xml``, beside the game logs), each when set
        and once when both name the same place."""
        folders: list[Path] = []
        for folder in (self.mtgo_deck_dir, self.mtgo_dir):
            if folder is None:
                continue
            if any(_same_folder(folder, seen) for seen in folders):
                continue
            folders.append(folder)
        return folders

    def _poll_mtgo_decks(self, conn: sqlite3.Connection) -> int:
        """Ingest MTGO's deck files at most once per ``deck_poll_every``
        seconds (``DECK_POLL_SECONDS`` by default; plan 12, D8 and D17): the
        ``.dek`` files in ``mtgo_deck_dir`` and the ``grouping *.xml`` files in
        ``mtgo_dir``. A no-op when neither is set.

        Polled rather than read once, unlike the game logs above (which share
        ``mtgo_dir`` but are not touched here: ``ingest_deck_dir`` takes only
        the two deck file kinds): a deck file changes only when the user
        saves one, so an unchanged folder costs one ``stat()`` per file
        (``ingest_state`` skips the rest) and writes nothing, and the user
        expects a just-exported deck to be there when they open the picker.
        The clock is set before the read, so a failing folder is retried on
        the next beat, not on every poll.

        Must never raise (non-negotiable #4): an unreachable folder is logged
        and counted, and the loop continues with the other folder.
        """
        if self.mtgo_deck_dir is None and self.mtgo_dir is None:
            return 0
        now = time.monotonic()
        if self._last_deck_poll is not None and now - self._last_deck_poll < self.deck_poll_every:
            return 0
        self._last_deck_poll = now
        inserted = 0
        for folder in self._deck_folders():
            try:
                inserted += ingest_deck_dir(conn, folder).rows_inserted
            except OSError as exc:
                with self._stats_lock:
                    self.stats.errors += 1
                    self.stats.last_error = str(exc)
                log.warning("mtgo deck poll of %s failed: %s", folder, exc)
        return inserted

    def ingest_once(self, conn: sqlite3.Connection) -> int:
        """One ingest pass: the previous-session recovery on this instance's
        very first call, then a normal tail read, plus the one-shot MTGO
        game-log leg and the MTGO deck-folder poll (``_poll_mtgo_decks``, on
        its own clock). Marks the projection dirty when anything landed.
        Returns the number of rows inserted.

        Split out of the old combined ``poll_once`` so ``run_forever`` can
        run this on its own thread and its own connection (module docstring,
        "Two cadences") — a rebuild's write lock must never hold up the next
        log line from reaching ``raw_events``. ``poll_once`` still calls this
        directly for callers that want one synchronous step.
        """
        with self._stats_lock:
            self.stats.polls += 1

        if not self._recovered:
            # First pass only: Arena wipes Player.log on launch, so the previous
            # session survives only in Player-prev.log, and only until the next one.
            inserted = sum(
                result.rows_inserted
                for result in ingest_with_recovery(
                    conn, self.log_path, locale_hint=self.locale_hint
                ).values()
            )
            self._recovered = True
        else:
            inserted = ingest_file(conn, self.log_path, locale_hint=self.locale_hint).rows_inserted

        inserted += self._poll_mtgo(conn)
        inserted += self._poll_mtgo_decks(conn)

        if inserted:
            with self._stats_lock:
                self.stats.events_ingested += inserted
                self.stats.last_ingest_at = _now()
            with self._dirty_lock:
                self._dirty = True

        return inserted

    def project_if_due(self, conn: sqlite3.Connection, *, force_project: bool = False) -> bool:
        """Rebuild the projection if the gate says it's due. Returns True
        only when a rebuild actually ran.

        Split out of the old combined ``poll_once`` (see ``ingest_once``)
        so ``run_forever`` can loop this on the calling thread while a
        separate thread keeps ingesting. It no longer assumes the caller
        just ran ``ingest_once`` on this same connection — the external-rows
        check below is what lets it notice rows the ingest thread (or a
        hand-run ``sensei-top ingest-mtgo``/``ingest``) landed elsewhere.
        """
        if not self._watermark_loaded:
            # Restore the watermark a previous run persisted, rather than
            # starting every restart back at 0: has_match_boundary below
            # LIKE-scans every raw_events row *after* this id, and 0 means
            # "all of them" on a database that may hold hundreds of
            # thousands. sqlite3.OperationalError covers a pre-034 database
            # that hasn't been migrated yet on this first poll.
            try:
                row = conn.execute(
                    "SELECT projected_through_id FROM projection_state WHERE id = 1"
                ).fetchone()
                if row is not None and row[0] is not None:
                    self._projected_through = row[0]
            except sqlite3.OperationalError:
                pass
            self._watermark_loaded = True

        with self._dirty_lock:
            already_dirty = self._dirty

        if not already_dirty:
            # Nothing landed through the ingest side on its own dirty flag
            # yet, but a hand-run `sensei-top ingest-mtgo` (or a separate
            # `ingest`) writes straight to raw_events from another
            # connection — this is how a running watcher notices those rows
            # rather than needing its own `project` step. Compare the
            # table's own high-water mark against what this watcher has
            # already projected through: if it moved, someone else's rows
            # are waiting. This still goes through the normal duty-cycle
            # gate below, same as any other dirty poll — it is not a new
            # boundary exception. One indexed MAX(id) lookup, so it's O(1);
            # by this point _projected_through has already been restored
            # from projection_state (the block above), so the comparison is
            # correct even on this process's very first poll.
            row = conn.execute("SELECT MAX(id) FROM raw_events").fetchone()
            if row[0] is not None and row[0] > self._projected_through:
                with self._dirty_lock:
                    self._dirty = True
                already_dirty = True

        if not self.project_enabled or not already_dirty:
            return False

        # A match room opening is worth a rebuild on sight rather than on the
        # next scheduled tick: it is what puts a deck on the Current match
        # tab, and the mulligan decision that read informs arrives roughly
        # eleven seconds later (measured on real captures) — comfortably
        # inside a poll tick, but not inside a multi-second wait for
        # project_every. has_match_boundary is cheap (one indexed lookup),
        # so it costs nothing to check on every dirty poll.
        boundary = has_match_boundary(conn, after_event_id=self._projected_through)
        # project_every is a floor, not the beat: once a rebuild outlasts it
        # the watcher would otherwise run back-to-back forever (it did,
        # measured at 16.2 s a rebuild against a 5 s project_every on a
        # 238k-event database — every dirty poll already found elapsed >=
        # project_every true). Sleeping duty_factor times the *last*
        # rebuild's own duration instead holds the watcher to roughly a
        # 1/duty_factor duty cycle, so its cost stays a fixed fraction of
        # wall time as history grows rather than consuming a whole core
        # continuously. Before the first rebuild, _last_duration is 0.0 and
        # this falls back to the project_every floor, same as before.
        gate = max(self.project_every, self._last_duration * self.duty_factor)
        elapsed = time.monotonic() - self._last_projection
        if not force_project and not boundary and elapsed < gate:
            return False   # stays dirty; a later tick rebuilds

        # Clear dirty *before* the rebuild starts, never after: run_forever
        # runs this concurrently with the ingest thread, so a row that lands
        # on that thread's own connection mid-rebuild must not be lost. If
        # this were cleared after project()/classify_matches() returned (as
        # the old single-threaded poll_once did), it would unconditionally
        # stomp on a True the ingest thread set while the rebuild was still
        # running, and that row would sit unprojected until some *later*,
        # unrelated dirty event happened to arrive. Clearing first means the
        # worst case is the opposite and harmless: a row that lands between
        # this clear and the MAX(id) snapshot just below causes at most one
        # extra rebuild next tick, never a missed one.
        with self._dirty_lock:
            self._dirty = False
        row = conn.execute("SELECT MAX(id) FROM raw_events").fetchone()
        self._projected_through = row[0] or 0
        rebuild_started = time.monotonic()
        project(conn)
        # Classification rides the projection beat because its input *is* the
        # projection: a rebuild deletes every opponent_archetype row, so naming
        # the decks again is part of finishing the rebuild, not a separate job.
        classify_matches(conn)
        self._last_duration = time.monotonic() - rebuild_started
        self._last_projection = time.monotonic()
        now = _now()
        with self._stats_lock:
            self.stats.projections += 1
            self.stats.last_projection_at = now
        # Mirrored into the database, not just this process's LiveStats: a
        # separate-process watcher (WatcherProcess, below) can't share memory
        # with the API, so /api/live's last_projection_at has to cross here.
        # projected_through_id is likewise persisted so a restart doesn't
        # reset the boundary-check watermark to 0 (see _watermark_loaded
        # above).
        conn.execute(
            """
            INSERT INTO projection_state
                (id, last_projection_at, projections, projected_through_id, updated_at)
            VALUES (1, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_projection_at = excluded.last_projection_at,
                projections = projection_state.projections + 1,
                projected_through_id = excluded.projected_through_id,
                updated_at = excluded.updated_at
            """,
            (now, self._projected_through, now),
        )
        return True

    def poll_once(self, conn: sqlite3.Connection, *, force_project: bool = False) -> bool:
        """Ingest, then project if due, both on ``conn``. Returns True if
        anything changed — a rebuild ran, or (if not) at least one row was
        inserted.

        ``ingest_once`` + ``project_if_due`` composed onto a single
        connection and a single call, for callers — mainly tests — that want
        one deterministic step rather than the two independent threads
        ``run_forever`` drives them on (module docstring, "Two cadences").
        """
        inserted = self.ingest_once(conn)
        rebuilt = self.project_if_due(conn, force_project=force_project)
        return rebuilt or bool(inserted)

    # -- loops -------------------------------------------------------------

    def _ingest_loop(self) -> None:
        """The ingest thread's own loop, on its own connection.

        SQLite connections belong to the thread that made them, so this
        opens and closes its own inside this same thread's try/finally
        rather than sharing ``run_forever``'s — by the time
        ``run_forever``'s own ``finally`` finishes joining this thread, this
        connection has already been closed here.
        """
        connection: sqlite3.Connection | None = None
        try:
            while not self._stop.is_set():
                try:
                    if connection is None:
                        # Opened inside the loop's own try, not before it —
                        # a locked database or a permissions error must not
                        # kill this thread silently while run_forever's loop
                        # keeps stats.running True. A failed open is caught
                        # below like any other bad ingest tick and retried
                        # next interval. connect(), not open_database():
                        # run_forever migrated before starting this thread,
                        # and a retry an hour in must not apply a migration
                        # file that appeared since.
                        connection = connect(self.db_path)
                        # The rebuild's own write lock (BEGIN...COMMIT inside
                        # project()) was measured at 5.7 s on a real database
                        # — past connect()'s 5 s default busy_timeout. This
                        # connection only gets a longer one, so an ingest
                        # tick waits out a rebuild's commit instead of
                        # raising SQLITE_BUSY while it's mid-transaction.
                        connection.execute("PRAGMA busy_timeout = 30000")
                    self.ingest_once(connection)
                except Exception as exc:  # a bad poll — or a failed open — must never end the watch
                    with self._stats_lock:
                        self.stats.errors += 1
                        self.stats.last_error = str(exc)
                    log.warning("live ingest poll failed: %s", exc)
                self._stop.wait(self.interval)
        finally:
            if connection is not None:
                connection.close()

    def run_forever(self, conn: sqlite3.Connection | None = None) -> None:
        """Poll until stopped. Used directly by ``ingest --watch``.

        Runs two loops concurrently rather than the old single one: a
        dedicated ingest thread (``_ingest_loop``, its own connection) and
        this calling thread looping ``project_if_due`` on ``conn`` (or a
        connection it opens itself). This is what keeps a rebuild's write
        lock from blocking the next log line — see the module docstring's
        "Two cadences" section. Both stop on the same ``_stop`` event.
        """
        owned = conn is None
        # SQLite connections belong to the thread that made them, so the loop
        # opens its own rather than borrowing the caller's.
        connection = conn or open_database(self.db_path)
        self.stats.running = True
        ingest_thread = threading.Thread(
            target=self._ingest_loop, name="mtga-live-ingest", daemon=True
        )
        ingest_thread.start()
        try:
            while not self._stop.is_set():
                try:
                    self.project_if_due(connection)
                except Exception as exc:  # a bad poll must never end the watch
                    with self._stats_lock:
                        self.stats.errors += 1
                        self.stats.last_error = str(exc)
                    log.warning("live projection poll failed: %s", exc)
                self._stop.wait(self.interval)
        finally:
            self.stats.running = False
            ingest_thread.join(timeout=5.0)
            if owned:
                connection.close()

    def start(self) -> None:
        """Run the loop on a background thread (used by ``serve --watch``)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run_forever, name="mtga-live", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def is_alive(self) -> bool:
        """Same question ``WatcherProcess.is_alive()`` answers for the
        separate-process case, so ``/api/live``'s ``watching`` flag can ask
        either kind of watcher the same way without knowing which one it
        has."""
        return self.stats.running


# -- separate-process watcher --------------------------------------------

def _run_watcher(
    *,
    db_path: Path,
    log_path: Path,
    locale_hint: str | None,
    interval: float,
    project_every: float,
    stop_event: multiprocessing.synchronize.Event,
    duty_factor: float = 1.0,
    mtgo_dir: Path | None = None,
    mtgo_deck_dir: Path | None = None,
) -> None:
    """``WatcherProcess``'s process entry point.

    Module-level (not a bound method or a closure) so it pickles under both
    the ``fork`` and ``spawn`` start methods. ``LiveIngester`` stops on a
    ``threading.Event``, not a ``multiprocessing.Event``, so a small bridging
    thread waits on the process-level event and relays it — the minimal seam
    that leaves ``run_forever``'s signature and ``LiveIngester._stop`` alone.
    Calling ``ingester.stop()`` from that thread is safe even though
    ``ingester.start()`` was never called: ``_thread`` stays ``None``, so
    ``stop()`` just sets ``_stop`` and returns.

    Keyword-only: this was 7 positional args passed straight through
    ``Process(args=...)`` even before ``mtgo_dir`` joined them — the shape
    that breaks silently on a reorder rather than raising.
    ``WatcherProcess.start()`` passes ``kwargs=`` instead of ``args=`` for
    the same reason. Every argument stays picklable (``Path``, primitives,
    the ``multiprocessing.Event``).
    """
    ingester = LiveIngester(
        db_path=db_path,
        log_path=log_path,
        locale_hint=locale_hint,
        interval=interval,
        project_every=project_every,
        duty_factor=duty_factor,
        mtgo_dir=mtgo_dir,
        mtgo_deck_dir=mtgo_deck_dir,
    )
    threading.Thread(
        target=lambda: (stop_event.wait(), ingester.stop()), daemon=True
    ).start()
    ingester.run_forever()


@dataclass
class WatcherProcess:
    """Runs a ``LiveIngester`` in a separate OS process instead of a thread.

    ``project()`` is a total rebuild that measured ~11.6 s wall time on a
    real database (module docstring above) — past ``project_every``, so the
    rebuild runs back-to-back and the watcher thread never actually sleeps.
    Every API route is a sync ``def``, so it shares the interpreter's GIL
    with whatever thread is mid-rebuild: measured ~27 ms for
    ``/api/current-match/read`` with the watcher thread idle, against
    ~145-160 ms with a rebuild contending for the GIL — still a ~5x tax
    even with the parser now ``orjson`` rather than the slower stdlib
    ``json`` (the rebuild finishes faster, but it is still slower than
    ``project_every`` and still holds the GIL while it runs). That tax
    disappears once the rebuild runs in its own process with its own GIL
    (and, on a multi-core machine, its own core).

    Used only by ``serve --watch`` (``cli.cmd_serve``). ``ingest --watch``
    still drives ``LiveIngester.run_forever()`` directly in the foreground,
    and ``tests/test_live.py`` still drives ``LiveIngester.poll_once()``
    in-process — neither needed to change for this. The API can no longer
    read ``LiveIngester.stats`` from across the process boundary; the one
    field it needs (``last_projection_at``) crosses via the
    ``projection_state`` table instead (see ``poll_once`` above and
    ``migrations/026_projection_state.sql``), and ``is_alive()`` answers
    "is it running" without needing shared memory at all.
    """

    db_path: Path
    log_path: Path
    locale_hint: str | None = None
    interval: float = 1.0
    project_every: float = 5.0
    duty_factor: float = 1.0
    mtgo_dir: Path | None = None
    mtgo_deck_dir: Path | None = None

    _process: multiprocessing.Process | None = field(default=None, repr=False)
    _stop_event: multiprocessing.synchronize.Event | None = field(default=None, repr=False)

    def start(self) -> None:
        if self._process is not None:
            return
        self._stop_event = multiprocessing.Event()
        self._process = multiprocessing.Process(
            target=_run_watcher,
            kwargs={
                "db_path": self.db_path,
                "log_path": self.log_path,
                "locale_hint": self.locale_hint,
                "interval": self.interval,
                "project_every": self.project_every,
                "stop_event": self._stop_event,
                "duty_factor": self.duty_factor,
                "mtgo_dir": self.mtgo_dir,
                "mtgo_deck_dir": self.mtgo_deck_dir,
            },
            name="mtga-live",
            daemon=True,
        )
        self._process.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._process is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        self._process.join(timeout=timeout)
        if self._process.is_alive():
            # The bridging thread didn't unblock run_forever in time — don't
            # leave a daemon process behind.
            self._process.terminate()
            self._process.join(timeout=timeout)
        self._process = None
        self._stop_event = None

    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()
