"""One ``VACUUM INTO`` snapshot of the whole database, taken at most once a
day and never touching the previous good copy until a new one is verified.

Contract mirrors ``archetypes/source.py``'s ``RefreshResult``/
``refresh_archetypes``: a plain ``status`` string so callers only format,
``None`` never ``0`` for "this never happened yet" (AGENTS.md non-negotiable
#4), and ``run_backup`` never raises past its own boundary -- every failure
this module can anticipate comes back as ``BackupResult(status="failed"...)``
or ``"interrupted"``, not an exception a caller has to wrap.

Four things below are load-bearing, not stylistic:

- **``_vacuum_into`` opens its own connection.** Measured empirically: an
  open, partly-consumed cursor on the *same* connection ``VACUUM INTO`` runs
  on blocks it outright with ``cannot VACUUM - SQL statements in progress``.
  It uses ``db.connect()``, not ``open_database()`` -- migrations already
  ran on the caller's connection, and re-running them on a throwaway one
  buys nothing. No extra pragma tuning either: whatever ``db.connect()``
  already sets is what runs here, on purpose (see that function's own
  reasoning) -- this is not the place to guess at something faster.
- **Rotation only ever unlinks a path it reconstructed itself** via
  ``config.slot_path`` -- never a glob. This code deletes files in a
  directory the user configured; a glob would happily eat a same-looking
  file that isn't one of ours.
- **A failed run never touches the backup that already exists.** Every
  write lands in a pid-suffixed temp file first; only a *verified* temp file
  is ever renamed onto a real slot, and the temp is unlinked on every exit
  path (the single ``finally`` in ``run_backup``), success or not.
- **``running_since``/``running_pid`` are an advisory claim, not a lock.**
  They stop two runs from wasting a copy on each other; they are not what
  keeps a half-written backup from being mistaken for a good one -- the
  temp-then-verify-then-``os.replace`` sequence above is what does that.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sensei_top import db
from sensei_top.backup.config import BackupConfig, slot_path, temp_path

log = logging.getLogger(__name__)

MAX_AGE_SECONDS = 24 * 3600
CLAIM_STALE_SECONDS = 6 * 3600
# VACUUM INTO needs room for a whole second copy of the database; 1.1x
# leaves a 10% margin over that copy's own size for the small amount SQLite
# writes as it goes rather than needing exactly the source's byte count.
FREE_SPACE_MARGIN = 1.1
_SLOT_RE = re.compile(r"\.(\d+)\Z")  # exact pattern, never a glob


class BackupError(Exception):
    """A verification invariant failed. Always caught inside ``run_backup``
    and turned into ``BackupResult(status="failed", ...)`` -- nothing above
    this module should ever need to catch it directly."""


@dataclass(frozen=True, slots=True)
class BackupResult:
    status: str  # 'ok' | 'fresh' | 'busy' | 'failed' | 'interrupted'
    path: Path | None = None
    bytes: int | None = None
    source_bytes: int | None = None
    duration_seconds: float | None = None
    schema_version: int | None = None
    age_seconds: float | None = None  # on 'fresh'/'failed'/'busy': age of the copy still on disk
    numbered_kept: int = 0
    running_pid: int | None = None  # on 'busy'
    error: str | None = None


def read_state(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """The single ``backup_state`` row, or ``None`` before the very first
    write to it -- the migration seeds no row (see
    ``migrations/039_backup_state.sql``)."""
    return conn.execute("SELECT * FROM backup_state WHERE id = 1").fetchone()


def last_backup_age_seconds(conn: sqlite3.Connection) -> float | None:
    """Seconds since the last *successful* backup, or ``None`` when there
    has never been one -- never ``0``, which would read as "just backed up"
    and could suppress the first real one forever (AGENTS.md non-negotiable
    #4). Mirrors ``archetypes.source.cache_age_seconds``."""
    row = read_state(conn)
    if row is None or not row["last_backup_at"]:
        return None
    try:
        backed_up_at = datetime.strptime(row["last_backup_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        return None
    return (datetime.now(UTC) - backed_up_at).total_seconds()


def last_error_age_seconds(conn: sqlite3.Connection) -> float | None:
    """Seconds since the most recent *failed* run, or ``None`` when none has
    ever failed. This is the one channel a failure actually reaches a user
    through: ``cli.main()`` sets logging to ERROR unless ``--verbose``, so a
    scheduled run's ``log.warning`` is otherwise invisible, and
    ``cmd_config``'s display block reads this back next to the last good
    backup's own age -- the reason ``last_error``/``last_error_at`` are
    columns on ``backup_state`` at all."""
    row = read_state(conn)
    if row is None or not row["last_error_at"]:
        return None
    try:
        failed_at = datetime.strptime(row["last_error_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        return None
    return (datetime.now(UTC) - failed_at).total_seconds()


def claim_age_seconds(conn: sqlite3.Connection) -> float | None:
    """Seconds since the currently-held claim was taken, or ``None`` when
    nothing is claimed right now. Powers ``cmd_backup``'s ``busy`` message
    ("a backup started 41s ago (pid N) is still running") -- ``running_pid``
    alone says who; this says how long, which is what tells a user whether
    that pid is plausibly still working or plainly stale."""
    row = read_state(conn)
    if row is None or not row["running_since"]:
        return None
    try:
        started_at = datetime.strptime(row["running_since"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        return None
    return (datetime.now(UTC) - started_at).total_seconds()


def run_backup(
    conn: sqlite3.Connection,
    db_path: Path,
    *,
    cfg: BackupConfig,
    force: bool = False,
    deep_verify: bool = False,
    max_age_seconds: float = MAX_AGE_SECONDS,
    stop: threading.Event | None = None,
) -> BackupResult:
    """Run the whole backup routine once. Never raises.

    ``conn`` is the caller's own already-open connection, used only to read
    and record ``backup_state`` -- the copy itself always runs on a private
    connection opened by ``_vacuum_into``, for the reason in this module's
    docstring. ``stop``, when given, lets a long-running copy be cancelled
    promptly (``BackupScheduler`` passes its own stop event so ``serve``
    shuts down without waiting out a multi-minute VACUUM).
    """
    # 4.1 -- the freshness gate. No I/O beyond one indexed SELECT already
    # open on `conn`.
    age = last_backup_age_seconds(conn)
    if not force and age is not None and age < max_age_seconds:
        return BackupResult(status="fresh", age_seconds=age)

    # 4.2 -- preconditions.
    if not db_path.exists():
        error = f"No database at {db_path}"
        return BackupResult(status="failed", age_seconds=age, error=error)

    try:
        cfg.directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _record_failure(conn, str(exc))
        return BackupResult(status="failed", age_seconds=age, error=str(exc))

    _sweep_stale_temps(cfg, db_path)

    source_bytes = db_path.stat().st_size
    try:
        free = shutil.disk_usage(cfg.directory).free
    except OSError as exc:
        _record_failure(conn, str(exc))
        return BackupResult(
            status="failed", age_seconds=age, source_bytes=source_bytes, error=str(exc)
        )
    needed = int(source_bytes * FREE_SPACE_MARGIN)
    if free < needed:
        # Caught before any write, not after a multi-minute VACUUM discovers
        # it the hard way -- see FREE_SPACE_MARGIN above.
        error = f"only {free:,} bytes free in {cfg.directory}, need at least {needed:,}"
        _record_failure(conn, error)
        return BackupResult(
            status="failed", age_seconds=age, source_bytes=source_bytes, error=error
        )

    # 4.3 -- the claim. Everything from here on releases it and cleans up
    # the temp file on every exit path via the single `finally` below.
    claimed, abandoned_pid = _claim(conn)
    if not claimed:
        row = read_state(conn)
        return BackupResult(
            status="busy",
            age_seconds=age,
            source_bytes=source_bytes,
            running_pid=row["running_pid"] if row is not None else None,
        )
    if abandoned_pid is not None:
        log.warning("backup: taking over a stale claim left by pid %s", abandoned_pid)

    temp = temp_path(cfg, db_path)
    try:
        # 4.4 -- source facts, read before the copy. Sound only because
        # raw_events is append-only (non-negotiable #2): nothing can shrink
        # between this read and the verification read of the copy.
        source_version = (
            conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"] or 0
        )
        source_rows = conn.execute("SELECT COUNT(*) AS n FROM raw_events").fetchone()["n"]

        # 4.5 -- the copy.
        temp.unlink(missing_ok=True)  # VACUUM INTO refuses a non-empty target
        started = time.monotonic()
        try:
            _vacuum_into(db_path, temp, stop=stop)
        except sqlite3.OperationalError as exc:
            interrupted = stop is not None and stop.is_set()
            error = str(exc)
            if not interrupted:
                _record_failure(conn, error)
            return BackupResult(
                status="interrupted" if interrupted else "failed",
                age_seconds=age,
                source_bytes=source_bytes,
                error=error,
            )

        # 4.6 -- verification: three cheap invariants, a fourth (quick_check)
        # only under --deep-verify (measured 67.7s on the real database).
        try:
            _verify(
                temp,
                source_version=source_version,
                source_rows=source_rows,
                deep_verify=deep_verify,
            )
        except BackupError as exc:
            _record_failure(conn, str(exc))
            return BackupResult(
                status="failed", age_seconds=age, source_bytes=source_bytes, error=str(exc)
            )

        backup_bytes = temp.stat().st_size

        # 4.7 -- rotation: oldest-first shift, then the atomic publish.
        try:
            numbered_kept = _rotate(cfg, db_path, temp)
        except BackupError as exc:
            _record_failure(conn, str(exc))
            return BackupResult(
                status="failed", age_seconds=age, source_bytes=source_bytes, error=str(exc)
            )
        duration = time.monotonic() - started
        final_path = slot_path(cfg, db_path, 0)

        # 4.8 -- record. A measured fact, never an estimate.
        _record_success(
            conn,
            path=final_path,
            size=backup_bytes,
            duration_ms=int(duration * 1000),
            schema_version=source_version,
        )
        return BackupResult(
            status="ok",
            path=final_path,
            bytes=backup_bytes,
            source_bytes=source_bytes,
            duration_seconds=duration,
            schema_version=source_version,
            numbered_kept=numbered_kept,
        )
    finally:
        temp.unlink(missing_ok=True)
        conn.execute(
            "UPDATE backup_state SET running_since = NULL, running_pid = NULL, updated_at = ? "
            "WHERE id = 1",
            (_now_iso(),),
        )


def _claim(conn: sqlite3.Connection) -> tuple[bool, int | None]:
    """One atomic statement: autocommit means this is its own transaction,
    and SQLite serializes writers, so this is race-free without a lock
    file. Returns ``(claimed, abandoned_pid)`` -- ``abandoned_pid`` is only
    ever non-``None`` when the claim just taken had to override a stale one,
    so the caller can name the pid it took over from."""
    prior = read_state(conn)
    prior_running_since = prior["running_since"] if prior is not None else None
    prior_pid = prior["running_pid"] if prior is not None else None

    now = _now_iso()
    stale_before = (datetime.now(UTC) - timedelta(seconds=CLAIM_STALE_SECONDS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    before = conn.total_changes
    conn.execute(
        """
        INSERT INTO backup_state (id, running_since, running_pid, updated_at)
        VALUES (1, :now, :pid, :now)
        ON CONFLICT(id) DO UPDATE SET
            running_since = excluded.running_since,
            running_pid   = excluded.running_pid,
            updated_at    = excluded.updated_at
         WHERE backup_state.running_since IS NULL
            OR backup_state.running_since < :stale_before
        """,
        {"now": now, "pid": os.getpid(), "stale_before": stale_before},
    )
    claimed = conn.total_changes != before
    if not claimed:
        return False, None
    return True, (prior_pid if prior_running_since is not None else None)


def _record_success(
    conn: sqlite3.Connection, *, path: Path, size: int, duration_ms: int, schema_version: int
) -> None:
    """Increments ``backups`` from its stored value, the same idiom
    ``projection_state.projections`` and ``archetype_fetch`` use, and clears
    any earlier failure -- a success after a failure is what a user actually
    wants to see, not a stale error next to a fresh good backup."""
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO backup_state
            (id, last_backup_at, last_path, last_bytes, last_duration_ms,
             last_schema_version, backups, last_error, last_error_at, updated_at)
        VALUES (1, :now, :path, :size, :duration_ms, :schema_version, 1, NULL, NULL, :now)
        ON CONFLICT(id) DO UPDATE SET
            last_backup_at      = excluded.last_backup_at,
            last_path           = excluded.last_path,
            last_bytes          = excluded.last_bytes,
            last_duration_ms    = excluded.last_duration_ms,
            last_schema_version = excluded.last_schema_version,
            backups             = backup_state.backups + 1,
            last_error          = NULL,
            last_error_at       = NULL,
            updated_at          = excluded.updated_at
        """,
        {
            "now": now,
            "path": str(path),
            "size": size,
            "duration_ms": duration_ms,
            "schema_version": schema_version,
        },
    )


def _record_failure(conn: sqlite3.Connection, error: str) -> None:
    """Writes only ``last_error``/``last_error_at``/``updated_at`` --
    ``last_backup_at``/``last_path``/``last_bytes`` keep describing the good
    copy that a failed run never touched."""
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO backup_state (id, last_error, last_error_at, updated_at)
        VALUES (1, :error, :now, :now)
        ON CONFLICT(id) DO UPDATE SET
            last_error    = excluded.last_error,
            last_error_at = excluded.last_error_at,
            updated_at    = excluded.updated_at
        """,
        {"error": error, "now": now},
    )


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _vacuum_into(db_path: Path, temp: Path, *, stop: threading.Event | None) -> None:
    """Runs ``VACUUM INTO`` on a connection of its own -- see this module's
    docstring for why that is the one non-negotiable part of this function.
    It is also the only statement this connection ever runs.

    ``stop`` is polled by a small daemon watchdog thread that calls
    ``conn.interrupt()`` once asked to stop, the same bridging-thread shape
    ``live._run_watcher`` uses to relay one event kind into another. The
    watchdog exits promptly once ``done`` is set in the ``finally`` below,
    whether or not ``stop`` was ever set -- without that, a watchdog thread
    from every backup run would sit blocked until the whole process exits.
    """
    conn = db.connect(db_path)
    done = threading.Event()
    if stop is not None:

        def _watch() -> None:
            while not done.wait(0.5):
                if stop.is_set():
                    conn.interrupt()
                    return

        threading.Thread(target=_watch, name="backup-vacuum-watchdog", daemon=True).start()
    try:
        conn.execute("VACUUM INTO ?", (str(temp),))
    finally:
        done.set()
        conn.close()


def _verify(
    temp: Path, *, source_version: int, source_rows: int, deep_verify: bool
) -> None:
    """Three cheap invariants, in increasing order of what they catch; a
    fourth (``quick_check``) only under ``--deep-verify``, measured at 67.7s
    on the real 1.7 GB database -- roughly doubling a run for a check the
    other three already make redundant in the failure modes that matter
    here (a truncated write, a copy of the wrong database, an empty one).
    Opened ``immutable=1`` so nothing here creates a ``-wal``/``-shm``
    sidecar beside a file meant to sit untouched until it is restored.
    """
    try:
        size = temp.stat().st_size
    except OSError as exc:
        raise BackupError(f"backup file missing after VACUUM INTO: {exc}") from exc

    conn = sqlite3.connect(Path(temp).absolute().as_uri() + "?immutable=1", uri=True)
    try:
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        if page_count * page_size != size:
            raise BackupError(
                f"backup file size {size} does not match its own "
                f"page_count*page_size ({page_count * page_size}) -- a truncated or short write"
            )

        copied_version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
        if copied_version != source_version:
            raise BackupError(
                f"backup schema_version {copied_version} does not match "
                f"source schema_version {source_version}"
            )

        copied_rows = conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
        if copied_rows < source_rows:
            raise BackupError(
                f"backup has {copied_rows} raw_events rows, fewer than the source's {source_rows}"
            )

        if deep_verify:
            result = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
            if result != "ok":
                raise BackupError(f"quick_check reported: {result}")
    finally:
        conn.close()


def _sweep_stale_temps(cfg: BackupConfig, db_path: Path) -> None:
    """Removes a temp file orphaned by a run that never reached its own
    ``finally`` -- a killed process, an interpreter crash. Unlike rotation's
    slot pruning, a glob is safe here: ``<db name>.backup.tmp.<pid>`` is a
    name only this code mints, not one a user could plausibly already have
    in their configured directory."""
    cutoff = time.time() - CLAIM_STALE_SECONDS
    try:
        candidates = list(cfg.directory.glob(f"{db_path.name}.backup.tmp.*"))
    except OSError:
        return
    for candidate in candidates:
        try:
            if candidate.stat().st_mtime < cutoff:
                candidate.unlink(missing_ok=True)
        except OSError:
            continue


def _rotate(cfg: BackupConfig, db_path: Path, temp: Path) -> int:
    """Oldest-first shift, then the atomic publish, then a prune of any
    surplus numbered slot a shrunk ``keep`` left behind. Returns how many
    numbered slots (index >= 1) exist after rotation.

    Raises ``BackupError``, never a bare ``OSError``, so ``run_backup`` can
    handle a failure here the same way it already handles ``_verify``'s: one
    ``except BackupError`` block, ``_record_failure``, ``status="failed"``.
    That holds whether the failure lands before the publish (``temp`` is
    untouched, so ``run_backup``'s own ``finally`` still finds it to clean
    up) or after (``os.replace`` has already moved ``temp`` onto slot 0, so
    it no longer exists at that path for the same ``finally`` to touch —
    ``unlink(missing_ok=True)`` stays a no-op either way).
    """
    try:
        for i in range(cfg.keep - 1, 0, -1):  # oldest first: nothing is
            src = slot_path(cfg, db_path, i - 1)  # overwritten while still a source
            if src.exists():
                os.replace(src, slot_path(cfg, db_path, i))
        os.replace(temp, slot_path(cfg, db_path, 0))  # the atomic publish

        _prune_surplus_slots(cfg, db_path)
    except OSError as exc:
        raise BackupError(f"rotation failed: {exc}") from exc

    return sum(1 for i in range(1, cfg.keep) if slot_path(cfg, db_path, i).exists())


def _prune_surplus_slots(cfg: BackupConfig, db_path: Path) -> None:
    """Deletes numbered slots a shrunk ``keep`` (e.g. 3 -> 1) left behind.

    Candidates are *discovered* by listing the directory -- there is no
    other way to find them -- but nothing is unlinked unless its name is
    byte-for-byte the name ``slot_path`` would itself construct for that
    index. Never a bare ``glob("*.backup.*")``: this code deletes files in a
    directory the user configured, and a glob would just as happily eat
    ``other.db.backup.1`` or ``sensei-top.db.backup.keepme``.
    """
    for candidate in cfg.directory.iterdir():
        match = _SLOT_RE.search(candidate.name)
        if match is None:
            continue
        index = int(match.group(1))
        if index < cfg.keep:
            continue
        if candidate == slot_path(cfg, db_path, index):
            candidate.unlink(missing_ok=True)
