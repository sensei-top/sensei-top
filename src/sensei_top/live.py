"""Live mode: keep the database current while Arena and MTGO write their logs.

The only module that drives both stages of the pipeline: ``LiveIngester`` runs
the reader on one thread and the projector on another, each on its own timer.
The design (the two cadences, the duty-cycle gate and its one exception, MTGO's
game logs stored once a game ends, the deck-folder poll, the watcher as a child
process of ``serve``) is in docs/architecture.md, "Live mode's two cadences";
what a rebuild costs is in docs/architecture.md, "Full rebuild, always".

Nothing here holds a transaction open across polls: readers (the API) see the
previous snapshot until each rebuild commits, so the dashboard never renders a
half-rebuilt projection.

MTGO is a second ingest leg on the same ``LiveIngester``, never a second
watcher: two processes would both upsert the ``projection_state`` id=1
singleton, ping-ponging ``projected_through_id`` so a boundary could be
silently missed, and both would run the same rebuild against SQLite's single
writer (``busy_timeout=5000``) for byte-identical output.
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import multiprocessing
import multiprocessing.connection
import signal
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sensei_top import arena_config, procs
from sensei_top.archetypes import classify_matches
from sensei_top.db import connect, open_database
from sensei_top.llm.provenance import now_iso as _now
from sensei_top.projector import PROJECTOR_VERSION
from sensei_top.projector.matches import has_match_boundary, project
from sensei_top.projector.mtgo.parse import last_game_decided
from sensei_top.reader.ingest import default_log_path, ingest_file, ingest_with_recovery
from sensei_top.reader.mtgo import (
    GameLogFile,
    ingest_mtgo_dir,
    read_game_log,
    scan_game_logs,
    store_game_log,
)
from sensei_top.reader.mtgo_decks import ingest_deck_dir

log = logging.getLogger(__name__)

# How long a group SIGTERM or Ctrl+C gets to reach stop() after it has
# already killed the child (the lifespan's stop() comes a moment later).
_SHUTDOWN_GRACE_SECONDS = 10.0

# How often the MTGO deck folder is read, in seconds. The default of
# ``LiveIngester.deck_poll_every``, and the number ``cli.py`` tells the user:
# one place, so the three cannot drift apart.
DECK_POLL_SECONDS = 30.0

# How often the MTGO game-log folder is checked, in seconds. The
# default of ``LiveIngester.mtgo_poll_every``, and the number ``cli.py`` tells
# the user, as ``DECK_POLL_SECONDS`` is for the deck folder.
MTGO_POLL_SECONDS = 2.0

# How long a changed game log stays unchanged, on the watcher's own clock,
# before it is stored: 5 s once its last game names a winner, a
# loser or a draw, so a row does not catch a write half done (MTGO's own, or
# a copy's); 10 minutes whatever its last game says, for a game that ends
# with none of those lines.
_DECIDED_QUIET_SECONDS = 5.0
_FALLBACK_QUIET_SECONDS = 600.0

# Per-file warnings of the game-log checks, each written once per file for
# the life of one watcher: the scan meets every file in the folder every
# MTGO_POLL_SECONDS, so a broken entry would otherwise put the same line in
# the log thirty times a minute.
_STAT_FAILED = "mtgo: skipping %s (could not stat): %s"
_READ_FAILED = "mtgo: %s not stored yet (could not read): %s"


def _same_folder(a: Path, b: Path) -> bool:
    """True when two configured folders are one place. Never raises: a path
    that cannot be resolved (a dead mount) is compared as written."""
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


@dataclass(slots=True)
class _Waiting:
    """A changed game log ``_poll_mtgo`` has not stored yet: its identity as
    last seen, the watcher's clock at the check that first saw that identity,
    and whether the bytes behind it were already judged undecided."""

    file: GameLogFile
    since: float
    undecided: bool = False


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


# How often a watcher with no Arena log looks for one.
ARENA_LOG_RESOLVE_SECONDS = 60.0


def resolve_arena_log() -> Path | None:
    """Where Arena's log is right now, or ``None`` when there is none.

    The one place the watcher, ``serve`` and ``/api/live`` ask. First match
    that exists wins: ``$MTGA_LOG``, then ``[arena] log``, then the
    autodetected locations (``default_log_path``). A value that names a
    missing file is passed over silently: the watcher asks again every
    ``ARENA_LOG_RESOLVE_SECONDS`` while it has no log."""
    return arena_config.resolve_log(default_log_path)[0]


@dataclass
class LiveIngester:
    """Polls the log, ingesting always and re-projecting on a slower beat.

    ``run_forever`` drives ``ingest_once`` and ``project_if_due`` on two
    separate threads (docs/architecture.md, "Live mode's two cadences");
    ``poll_once`` composes both on a single connection for callers, mainly
    tests, that want one deterministic step."""

    db_path: Path
    # None means "no Arena log yet": Arena's side waits, and looks again
    # every ``log_resolve_every`` seconds until ``log_resolver`` finds one.
    log_path: Path | None
    locale_hint: str | None = None
    interval: float = 1.0
    log_resolver: Callable[[], Path | None] = field(default=resolve_arena_log, repr=False)
    log_resolve_every: float = ARENA_LOG_RESOLVE_SECONDS
    # The clock timing those looks; a test moves it by hand.
    log_clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    # None means "this machine has no MTGO share", the normal case. log_path
    # keeps its exact meaning unchanged: Arena's Player.log, nothing else.
    mtgo_dir: Path | None = None
    # How often mtgo_dir's game logs are checked (``_poll_mtgo``).
    mtgo_poll_every: float = MTGO_POLL_SECONDS
    # The clock that times those checks and measures a game log's quiet:
    # time.monotonic, or one a test moves by hand. Never a file's mtime, which
    # a copied file carries from another machine's clock.
    mtgo_clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    # The MTGO deck-export folder, polled on a slower clock of its own
    # (``_poll_mtgo_decks``) and stored whenever a file changes, with no wait
    # for quiet, unlike ``mtgo_dir``'s game logs. ``mtgo_dir``'s
    # ``grouping *.xml`` files ride the same poll. None means none configured.
    mtgo_deck_dir: Path | None = None
    deck_poll_every: float = DECK_POLL_SECONDS
    project_every: float = 5.0
    project_enabled: bool = True
    # project_every is a floor, not the beat: a rebuild outlasts it on a real
    # database, and a fixed threshold would then rebuild back-to-back forever.
    # project_if_due's gate is max(project_every, _last_duration *
    # duty_factor): rest duty_factor times as long as the *last* rebuild took,
    # roughly a 1/(1+duty_factor) duty cycle (~50% at 1.0), so the rebuild's
    # cost stays a fixed fraction of wall time as history grows.
    duty_factor: float = 1.0

    stats: LiveStats = field(default_factory=LiveStats)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _recovered: bool = field(default=False, repr=False)
    _dirty: bool = field(default=False, repr=False)
    _last_projection: float = field(default=0.0, repr=False)
    # How long the last rebuild (project() + classify_matches()) actually
    # took, in seconds: what the duty_factor gate paces off. 0.0 until the
    # first rebuild completes, so the gate is the project_every floor until
    # then.
    _last_duration: float = field(default=0.0, repr=False)
    # The raw_events id projected through as of the last rebuild — the
    # watermark has_match_boundary checks against to decide whether a new
    # match room has opened since. Restored from projection_state on the
    # first project_if_due call (_watermark_loaded) rather than starting at
    # 0: at 0 project_if_due's high-water-mark check would find every row
    # unprojected, so every restart would rebuild once with nothing new.
    _projected_through: int = field(default=0, repr=False)
    _watermark_loaded: bool = field(default=False, repr=False)
    # mtgo_clock() at the last game-log check, set before the attempt; None
    # until the first, which is the catch-up pass (_poll_mtgo).
    _last_mtgo_poll: float | None = field(default=None, repr=False)
    # log_clock() at the last look for a missing Arena log; None until
    # the first pass, which starts the wait rather than looking (the caller
    # has just resolved).
    _last_log_resolve: float | None = field(default=None, repr=False)
    # Every changed game log not stored yet, by path, as of the last check.
    _mtgo_waiting: dict[Path, _Waiting] = field(default_factory=dict, repr=False)
    # Game logs already warned of, so each is warned of once (_STAT_FAILED
    # and _READ_FAILED above): one set per warning, since a file can fail both.
    _mtgo_unstattable: set[Path] = field(default_factory=set, repr=False)
    _mtgo_unreadable: set[Path] = field(default_factory=set, repr=False)
    # True from a check whose folder could not be read until one that could:
    # a run of failing checks is warned about and counted once.
    _mtgo_failing: bool = field(default=False, repr=False)
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
    # threads. _dirty stays a plain bool (not a threading.Event) so tests can
    # read and set it directly; a test has one thread, so the lock is never
    # contended there.
    _dirty_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _poll_mtgo(self, conn: sqlite3.Connection) -> int:
        """Store MTGO's game logs as their games end (docs/architecture.md,
        "Live mode's two cadences"), checking ``mtgo_dir`` at most once per
        ``mtgo_poll_every`` seconds of ``mtgo_clock``. Returns the rows inserted. A no-op when
        ``mtgo_dir`` is ``None`` (no MTGO share on this machine, the normal
        case).

        The first check catches up: ``ingest_mtgo_dir`` stores every changed
        file at once, decided or not, since whatever is there was written
        while nothing watched. Every check after holds a changed file back
        until ``_store_ended_games`` finds its game ended. A file counts as
        read (``ingest_state``) only once it is stored, so a watcher stopped
        mid-game leaves it for the next one's catch-up.

        Never raises for a folder it cannot read (non-negotiable #4): the
        virtiofs share this project's MTGO transport uses can vanish
        mid-session (unmounted, torn down, a VM stopped), and that must not
        end the Arena watch. The reader already tolerates one file going
        missing; this catches the coarser failure, the whole folder becoming
        unreachable (``glob()`` raising on a dead mount). The clock is set
        before the attempt, so a failing folder is tried again on the next
        check, not on every ingest pass, and a run of failing checks is warned
        about and counted once rather than every ``mtgo_poll_every``. A failed
        first check is not repeated: the files it missed meet the rule on the
        checks after, as they do in a folder that appears only later. A file
        that cannot be statted is warned of once (``_warn_unstattable``),
        whether the catch-up or a later check meets it first.
        """
        if self.mtgo_dir is None:
            return 0
        now = self.mtgo_clock()
        if self._last_mtgo_poll is not None and now - self._last_mtgo_poll < self.mtgo_poll_every:
            return 0
        catch_up = self._last_mtgo_poll is None
        self._last_mtgo_poll = now
        try:
            if catch_up:
                stats = ingest_mtgo_dir(
                    conn, self.mtgo_dir, on_stat_error=self._warn_unstattable
                )
                inserted = stats.rows_inserted
            else:
                inserted = self._store_ended_games(conn, self.mtgo_dir, now)
        except OSError as exc:
            if not self._mtgo_failing:
                self._mtgo_failing = True
                with self._stats_lock:
                    self.stats.errors += 1
                    self.stats.last_error = str(exc)
                log.warning("mtgo poll failed: %s", exc)
            return 0
        self._mtgo_failing = False
        return inserted

    def _warn_unstattable(self, path: Path, exc: OSError) -> None:
        """The scan's ``on_stat_error``: the first time a file cannot be
        statted, a warning; every time after, nothing."""
        if path not in self._mtgo_unstattable:
            self._mtgo_unstattable.add(path)
            log.warning(_STAT_FAILED, path.name, exc)

    def _store_ended_games(self, conn: sqlite3.Connection, folder: Path, now: float) -> int:
        """One check after the catch-up: store each changed game log whose
        game has ended, and remember the rest. Returns the rows inserted.

        A file is stored when its last game names a winner, a loser or a draw
        (``last_game_decided``) and its identity (``GameLogFile``: size, mtime
        and inode) has not moved for ``_DECIDED_QUIET_SECONDS``, or when it
        has not moved for ``_FALLBACK_QUIET_SECONDS``, whatever its last game
        says. Quiet runs from ``now`` at the check that first saw the current
        identity.

        The bytes stored are the bytes judged, and only while they are still
        the bytes the scan saw: a file that moved between the scan and the
        read is not quiet, so its clock restarts at the read's identity. An
        undecided verdict is kept with the identity it was given for, so a
        quiet mid-game file is read and judged once, not on every check until
        the fallback, and ``last_game_decided``'s own warning, when it has
        one, is not repeated. A file the scan stops reporting (stored by
        another process, or gone) is forgotten.
        """
        waiting: dict[Path, _Waiting] = {}
        inserted = 0
        for file in scan_game_logs(conn, folder, on_stat_error=self._warn_unstattable):
            entry = self._mtgo_waiting.get(file.path)
            if entry is None or entry.file != file:
                waiting[file.path] = _Waiting(file, now)
                continue
            waiting[file.path] = entry
            quiet = now - entry.since
            if quiet < _DECIDED_QUIET_SECONDS:
                continue
            fallback = quiet >= _FALLBACK_QUIET_SECONDS
            if entry.undecided and not fallback:
                continue
            try:
                read = read_game_log(file.path)
            except OSError as exc:
                if file.path not in self._mtgo_unreadable:
                    self._mtgo_unreadable.add(file.path)
                    log.warning(_READ_FAILED, file.path.name, exc)
                del waiting[file.path]
                continue
            if read.file != file:
                waiting[file.path] = _Waiting(read.file, now)
                continue
            if not fallback and not last_game_decided(read.data):
                entry.undecided = True
                continue
            if store_game_log(conn, read):
                inserted += 1
            del waiting[file.path]
        self._mtgo_waiting = waiting
        return inserted

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
        seconds (``DECK_POLL_SECONDS`` by default): the
        ``.dek`` files in ``mtgo_deck_dir`` and the ``grouping *.xml`` files in
        ``mtgo_dir``. A no-op when neither is set.

        Stored whenever they change, with no wait for quiet, unlike the game
        logs above (which share ``mtgo_dir`` but are not touched here:
        ``ingest_deck_dir`` takes only the two deck file kinds): a deck file
        changes only when the user saves one, so an unchanged folder costs one
        ``stat()`` per file (``ingest_state`` skips the rest) and writes
        nothing, and the user expects a just-exported deck to be there when
        they open the picker.
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

    def _find_arena_log(self) -> Path | None:
        """The Arena log to read this pass, looking for one at most once per
        ``log_resolve_every`` seconds while there is none. The reader's role is
        unchanged: a file that appears is read from offset 0 like any new one."""
        if self.log_path is not None:
            return self.log_path
        now = self.log_clock()
        if self._last_log_resolve is None:
            self._last_log_resolve = now
            log.warning("no Arena log found; looking again every %g s", self.log_resolve_every)
            if self.log_resolve_every > 0:
                return None
        elif now - self._last_log_resolve < self.log_resolve_every:
            return None
        self._last_log_resolve = now
        found = self.log_resolver()
        if found is not None:
            log.info("Arena log found at %s", found)
            self.log_path = found
        return found

    def ingest_once(self, conn: sqlite3.Connection) -> int:
        """One ingest pass: the previous-session recovery on this instance's
        first pass that has an Arena log, then a normal tail read, plus the MTGO game-log check
        (``_poll_mtgo``) and the MTGO deck-folder poll (``_poll_mtgo_decks``),
        each on its own clock. Marks the projection dirty when anything landed.
        Returns the number of rows inserted.

        ``run_forever`` runs this on its own thread and its own connection,
        so a rebuild's write lock never holds up the next log line from
        reaching ``raw_events``; ``poll_once`` calls it directly.
        """
        with self._stats_lock:
            self.stats.polls += 1

        arena_log = self._find_arena_log()
        inserted = 0
        if arena_log is None:
            pass  # no Arena log yet; MTGO below still runs
        elif not self._recovered:
            # First pass only: Arena wipes Player.log on launch, so the previous
            # session survives only in Player-prev.log, and only until the next one.
            inserted = sum(
                result.rows_inserted
                for result in ingest_with_recovery(
                    conn, arena_log, locale_hint=self.locale_hint
                ).values()
            )
            self._recovered = True
        else:
            inserted = ingest_file(conn, arena_log, locale_hint=self.locale_hint).rows_inserted

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

        ``run_forever`` loops this on the calling thread while another thread
        ingests, so it never assumes the caller just ran ``ingest_once`` on
        this connection: the high-water-mark check below notices rows the
        ingest thread, or a hand-run ``sensei-top ingest-mtgo``/``ingest``,
        landed on another one.
        """
        if not self._watermark_loaded:
            # Restore the watermark a previous run persisted rather than
            # starting at 0 (why: the _projected_through comment).
            # sqlite3.OperationalError covers a database missing either
            # column (pre-034 or pre-065) on this first poll.
            try:
                row = conn.execute(
                    "SELECT projected_through_id, projector_version"
                    " FROM projection_state WHERE id = 1"
                ).fetchone()
                if row is not None and row[0] is not None:
                    self._projected_through = row[0]
                    # Rows a different projector wrote (or one that never
                    # recorded its version) are stale however far the
                    # watermark got: rebuild once, on this first poll.
                    if row[1] != PROJECTOR_VERSION:
                        with self._dirty_lock:
                            self._dirty = True
            except sqlite3.OperationalError:
                pass
            self._watermark_loaded = True

        with self._dirty_lock:
            already_dirty = self._dirty

        if not already_dirty:
            # The high-water-mark check. Rows another connection wrote (the
            # ingest thread, a hand-run `sensei-top ingest-mtgo` or `ingest`)
            # raise the table's high-water mark past what this watcher
            # projected through. They take the duty-cycle gate below like any
            # other dirty poll; this is not a boundary exception. MAX(id) is
            # one indexed lookup, and _projected_through is already restored
            # (the block above), so the comparison holds on a fresh process's
            # first poll too.
            row = conn.execute("SELECT MAX(id) FROM raw_events").fetchone()
            if row[0] is not None and row[0] > self._projected_through:
                with self._dirty_lock:
                    self._dirty = True
                already_dirty = True

        if not self.project_enabled or not already_dirty:
            return False

        # A match room opening rebuilds on sight, past the gate: it is what
        # puts a deck on the Live page, and the mulligan decision that read
        # informs arrives within seconds (docs/architecture.md, "Live mode's
        # two cadences"). has_match_boundary is an index search on label past
        # the watermark, then a LIKE over the room-state payloads it finds:
        # cheap on every dirty poll.
        boundary = has_match_boundary(conn, after_event_id=self._projected_through)
        # The duty-cycle gate (duty_factor's comment above).
        gate = max(self.project_every, self._last_duration * self.duty_factor)
        elapsed = time.monotonic() - self._last_projection
        if not force_project and not boundary and elapsed < gate:
            return False   # stays dirty; a later tick rebuilds

        # Clear dirty *before* the rebuild starts, never after: run_forever
        # runs this concurrently with the ingest thread, and clearing after
        # project()/classify_matches() returned would stomp on a True that
        # thread set mid-rebuild, leaving its row unprojected until some
        # later, unrelated dirty event. Clearing first makes the worst case
        # harmless: a row that lands between this clear and the MAX(id)
        # snapshot just below costs at most one extra rebuild, never a
        # missed one.
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
                (id, last_projection_at, projections, projected_through_id,
                 projector_version, updated_at)
            VALUES (1, ?, 1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_projection_at = excluded.last_projection_at,
                projections = projection_state.projections + 1,
                projected_through_id = excluded.projected_through_id,
                projector_version = excluded.projector_version,
                updated_at = excluded.updated_at
            """,
            (now, self._projected_through, PROJECTOR_VERSION, now),
        )
        return True

    def poll_once(self, conn: sqlite3.Connection, *, force_project: bool = False) -> bool:
        """Ingest, then project if due, both on ``conn``. Returns True if
        anything changed — a rebuild ran, or (if not) at least one row was
        inserted.

        For callers, mainly tests, that want one deterministic step rather
        than the two threads ``run_forever`` drives.
        """
        inserted = self.ingest_once(conn)
        rebuilt = self.project_if_due(conn, force_project=force_project)
        return rebuilt or bool(inserted)

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
                        # project()) has measured past connect()'s 5 s default
                        # busy_timeout (docs/architecture.md, "Live mode's two
                        # cadences"). This connection alone gets a longer one,
                        # so an ingest tick waits out a rebuild's commit
                        # instead of raising SQLITE_BUSY mid-transaction.
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

        Runs two loops concurrently: a dedicated ingest thread
        (``_ingest_loop``, its own connection) and this calling thread
        looping ``project_if_due`` on ``conn`` (or a connection it opens
        itself), so a rebuild's write lock never blocks the next log line.
        Both stop on the same ``_stop`` event.
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


def _run_watcher(
    *,
    db_path: Path,
    log_path: Path | None,
    locale_hint: str | None,
    interval: float,
    project_every: float,
    stop_conn: multiprocessing.connection.Connection,
    log_queue: multiprocessing.queues.Queue,
    log_level: int,
    duty_factor: float = 1.0,
    mtgo_dir: Path | None = None,
    mtgo_deck_dir: Path | None = None,
) -> None:
    """``WatcherProcess``'s process entry point.

    Module-level (not a bound method or a closure) so it pickles under both
    the ``fork`` and ``spawn`` start methods. ``LiveIngester`` stops on a
    ``threading.Event``, so a small bridging thread waits on ``stop_conn``,
    the read end of a one-way pipe from ``serve``, and relays whatever
    arrives — the minimal seam that leaves ``run_forever``'s signature and
    ``LiveIngester._stop`` alone. Calling ``ingester.stop()`` from that
    thread is safe even though ``ingester.start()`` was never called:
    ``_thread`` stays ``None``, so ``stop()`` just sets ``_stop`` and
    returns.

    A pipe rather than a ``multiprocessing.Event``, because ``Event.set()``
    waits for every sleeper to wake. The bridging thread is one, and a child
    that dies while it sleeps (SIGTERM to the whole group, SIGKILL, a crash,
    or only the main thread's return, the bridging thread being a daemon)
    leaves it counted but never woken, so ``serve``'s ``set()`` blocked
    forever and ``serve`` never exited. Writing one message into a pipe
    waits on nobody.

    Keyword-only, and ``WatcherProcess.start()`` passes ``kwargs=`` rather
    than ``args=``: a positional list this long breaks silently on a
    reorder rather than raising. Every argument stays picklable (``Path``,
    primitives, the pipe's ``Connection`` and the ``Queue``).

    It first sends every record it logs to ``log_queue``, for ``serve`` to
    write: this process writes no file (``logs.py``, trap 5). Then it ties
    itself to ``serve`` (``procs.die_with_parent``), so a ``serve`` killed
    outright takes the watcher with it.
    """
    root = logging.getLogger()
    # Under fork these are serve's own, the log file's among them: closing
    # this process's copy leaves serve's open. Under spawn there are none.
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.addHandler(logging.handlers.QueueHandler(log_queue))
    root.setLevel(log_level)
    if not procs.die_with_parent():
        return
    try:
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

        def relay_stop() -> None:
            # EOF, or an error, means serve's write end is gone; stop all the
            # same. Only a spawned child (Windows, macOS) ever sees it: a
            # forked one holds its own copy of that end, so on Linux only the
            # message ends the wait, and procs.die_with_parent covers a
            # killed serve.
            with contextlib.suppress(EOFError, OSError):
                stop_conn.recv_bytes()
            ingester.stop()

        threading.Thread(target=relay_stop, daemon=True).start()
        ingester.run_forever()
    except KeyboardInterrupt:
        # Ctrl+C in a console reaches every process attached to it, this one
        # included, and multiprocessing would print the interrupt's traceback
        # over serve's own last lines. serve's shutdown stops this process
        # anyway; an interrupted rebuild's transaction rolls back when
        # run_forever closes its connection.
        pass


class _Drain(logging.handlers.QueueListener):
    """Writes the watcher child's records through this process's handlers.

    Its ``stop`` waits a bounded time. A child that ``WatcherProcess.stop``
    had to terminate may have died partway through writing a record into the
    queue's pipe, and the drain would then wait forever for the rest of it;
    the stdlib's ``stop`` would wait with it, and ``serve`` would never exit.
    The thread is a daemon, so one left waiting ends with the process.

    A child killed mid-write can also die holding the queue's write lock,
    which is shared across processes on POSIX. The sentinel ``stop`` puts
    starts this process's feeder thread, which then waits for that lock
    forever, and at exit multiprocessing joins the feeder of any queue that
    has one: ``serve`` would hang there instead. So when ``stop`` times out,
    ``WatcherProcess.stop`` cancels that join and warns that the child's
    last records may be lost, which a killed child has lost already.
    """

    def stop(self, timeout: float = 5.0) -> bool:
        """Returns whether the thread finished, and so whether the queue is
        free to close."""
        thread = self._thread
        if thread is None:
            return True
        self.enqueue_sentinel()
        thread.join(timeout)
        self._thread = None
        return not thread.is_alive()


@dataclass
class WatcherProcess:
    """Runs a ``LiveIngester`` in a separate OS process instead of a thread.

    Every API route is a sync ``def``, so a watcher thread would share the
    interpreter's GIL with every request while a rebuild runs, and a rebuild
    runs much of the time (the duty-cycle gate): the measured tax is in
    docs/architecture.md, "Live mode's two cadences". In its own process the
    rebuild has its own GIL and, on a multi-core machine, its own core.

    Used only by ``serve --watch`` (``cli.cmd_serve``); ``ingest --watch``
    drives ``LiveIngester.run_forever()`` in the foreground. The API cannot
    read ``LiveIngester.stats`` across the process boundary: the one field it
    needs (``last_projection_at``) crosses via the ``projection_state`` table
    (``LiveIngester.project_if_due`` and
    ``migrations/026_projection_state.sql``), and ``is_alive()`` answers "is
    it running" without shared memory.

    The child dies with ``serve``, however ``serve`` ends (``procs.py``).

    The child's log records cross to this process through a queue, and a
    drain thread here hands them to the root logger's handlers, each at its
    own level, so they reach the console and the log file (``logs.py``) as
    ``serve``'s own would. ``stop()`` stops the drain after the child has
    exited, so the shutdown on a SIGTERM writes everything the child logged;
    only a SIGKILL of ``serve`` loses what is still queued.
    """

    db_path: Path
    log_path: Path | None
    locale_hint: str | None = None
    interval: float = 1.0
    project_every: float = 5.0
    duty_factor: float = 1.0
    mtgo_dir: Path | None = None
    mtgo_deck_dir: Path | None = None

    _process: multiprocessing.process.BaseProcess | None = field(default=None, repr=False)
    _stop_conn: multiprocessing.connection.Connection | None = field(default=None, repr=False)
    _job: int | None = field(default=None, repr=False)
    _log_queue: multiprocessing.queues.Queue | None = field(default=None, repr=False)
    _drain: _Drain | None = field(default=None, repr=False)
    _monitor: threading.Thread | None = field(default=None, repr=False)
    _stopping: bool = field(default=False, repr=False)
    _stop_asked: threading.Event = field(default_factory=threading.Event, repr=False)
    # Set by the monitor when the child exits without stop() having asked.
    exit_code: int | None = field(default=None)

    def start(self) -> None:
        """Start the child. Call it from the main thread before any other
        thread starts, as ``cmd_serve`` does: on Linux the child is forked,
        so ``serve`` rather than a forkserver is its parent (``procs.py``,
        trap 6), and it dies when the thread that started it exits (trap 1)."""
        if self._process is not None:
            return
        if sys.platform == "linux":
            context = multiprocessing.get_context("fork")
        else:
            context = multiprocessing.get_context()
        # From the same context as the Process: another context's Queue
        # cannot be handed to it. Making the queue starts no thread; only a
        # put does, and this process never puts before the fork. The stop
        # signal is a pipe, never an Event (_run_watcher's docstring).
        stop_reader, self._stop_conn = context.Pipe(duplex=False)
        self._log_queue = context.Queue()
        root = logging.getLogger()
        self._process = context.Process(
            target=_run_watcher,
            kwargs={
                "db_path": self.db_path,
                "log_path": self.log_path,
                "locale_hint": self.locale_hint,
                "interval": self.interval,
                "project_every": self.project_every,
                "stop_conn": stop_reader,
                "log_queue": self._log_queue,
                "log_level": root.level,
                "duty_factor": self.duty_factor,
                "mtgo_dir": self.mtgo_dir,
                "mtgo_deck_dir": self.mtgo_deck_dir,
            },
            name="mtga-live",
            daemon=True,
        )
        self._process.start()
        # The child has its own copy of the read end by now, under any start
        # method.
        stop_reader.close()
        self._job = procs.kill_with_this_process(self._process.pid)
        # After the child, never before: the fork must find no thread but
        # this one (procs.py, trap 6).
        self._drain = _Drain(self._log_queue, *root.handlers, respect_handler_level=True)
        self._drain.start()
        self._monitor = threading.Thread(
            target=self._watch_for_death,
            args=(self._process,),
            name="mtga-live-monitor",
            daemon=True,
        )
        self._monitor.start()

    def _watch_for_death(self, process: multiprocessing.process.BaseProcess) -> None:
        """Wait for the child to exit; say so if nobody asked it to."""
        multiprocessing.connection.wait([process.sentinel])
        if self._stopping:
            return
        # Joined first: the sentinel can fire before the child is reaped.
        # The process comes as an argument because stop() clears self._process.
        process.join(timeout=1.0)
        code = process.exitcode
        # 0, SIGTERM and SIGINT are what a group signal gives the child: serve
        # is probably shutting down, and its stop() is about to ask. None is
        # there because a stop() that reaps the child first leaves no code here.
        if code in (None, 0, -signal.SIGTERM, -signal.SIGINT) and self._stop_asked.wait(
            _SHUTDOWN_GRACE_SECONDS
        ):
            return
        # Read again: another thread's is_alive() may have reaped it meanwhile.
        self.exit_code = process.exitcode
        log.error(
            "The watcher process stopped unexpectedly (exit code %s); "
            "nothing new is being read until the tracker restarts.",
            self.exit_code,
        )

    def stopped_unexpectedly(self) -> bool:
        return self._process is not None and not self._stopping and self.exit_code is not None

    def stop(self, timeout: float = 5.0) -> None:
        if self._process is None:
            return
        self._stopping = True
        self._stop_asked.set()
        if self._stop_conn is not None:
            # An OSError means the child, and the only read end, are gone.
            with contextlib.suppress(OSError):
                self._stop_conn.send_bytes(b"stop")
            self._stop_conn.close()
        self._process.join(timeout=timeout)
        if self._process.is_alive():
            # The bridging thread didn't unblock run_forever in time — don't
            # leave a daemon process behind.
            self._process.terminate()
            self._process.join(timeout=timeout)
        procs.close_job(self._job)
        self._job = None
        # The drain stops only after the join: an exiting child flushes its
        # queue into the pipe, and blocks there until something reads it.
        drained = True
        if self._drain is not None:
            drained = self._drain.stop(timeout)
            self._drain = None
        if self._log_queue is not None:
            if drained:
                self._log_queue.close()
            else:
                # Or exit waits on the feeder thread forever (_Drain's docstring).
                self._log_queue.cancel_join_thread()
                log.warning(
                    "The watcher process was killed mid-write; its last log records may be lost."
                )
        self._log_queue = None
        self._process = None
        self._stop_conn = None
        if self._monitor is not None:
            self._monitor.join(timeout=timeout)
            self._monitor = None

    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()
