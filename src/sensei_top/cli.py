"""Command line interface: ``sensei-top <command>``.

    sensei-top ingest --file <path> [--from-start]   replay a log
    sensei-top ingest --watch [--file <path>]        follow a live log
    sensei-top ingest-mtgo [--dir <path>] [--deck-dir <path>] [--from-start]
                                                      read MTGO game logs and deck files
    sensei-top mtgo-status [--dir <path>]            diagnose the MTGO pipeline
    sensei-top project                                raw_events -> matches/games/turns
    sensei-top report [winrate|playdraw|gamelength|curves|meta]
                                                      CLI metrics (pre-dashboard)
    sensei-top ingest --watch --project             follow a log, rebuild as it grows
    sensei-top serve [--port N]                      local dashboard + JSON API (loopback only)
    sensei-top serve --watch                         live mode: watch + rebuild + serve
    sensei-top cards [--scryfall]                    card names (installed client, else Scryfall)
    sensei-top archetypes                            download deck archetype definitions
    sensei-top meta [--reclassify]                   tournament results for the Field page
    sensei-top guide [--deck KEY] [--markdown PATH]  one deck's guide (omit --deck to list)
    sensei-top guide --deck KEY --prompt             text to write the narrative from
    sensei-top guide --deck KEY --import FILE        store a written narrative
    sensei-top brief --deck KEY --archetype KEY --prompt | --import FILE
                                                      one matchup brief (omit --deck to list)
    sensei-top rcq --deck KEY --decklist FILE --prompt | --import FILE
                                                      the RCQ guide for the exact 75 you register
    sensei-top config --set-key KEY                  opt in to Claude-generated narratives
    sensei-top config --set-key -                    the same, reading the key from stdin
    sensei-top config --clear-key                    remove the key
    sensei-top config --set-arena-log PATH           where Arena's Player.log is
    sensei-top config --set-mtgo-handle HANDLE       which MTGO player is you
    sensei-top config --set-mtgo-dir DIR             where MTGO writes its game logs
    sensei-top config --set-mtgo-deck-dir DIR        where your MTGO deck exports (.dek) are
    sensei-top config                                show the settings (keys masked)
    sensei-top config --json                         every setting as JSON, no key in it
    sensei-top backup [--force] [--dir PATH] [--keep N] [--deep-verify]
                                                      daily VACUUM INTO snapshot of the database
    sensei-top restore FILE                          replace the database with a backup
    sensei-top serve --no-backup                     serve without the automatic daily backup
    sensei-top doctor [--json] [--file PATH]         what the app can find (read-only)
    sensei-top diagnostics --out FILE                a zip of the logs and a secret-free report

A Claude API call is opt-in (AGENTS.md non-negotiable #5): with no credential
configured, `--prompt` prints text to paste into an assistant you already pay
for and `--import` reads the answer back, exactly as before `config` existed.
`config --set-key` (or an `ANTHROPIC_API_KEY` env var) turns the dashboard's
"write it with Claude" buttons on instead.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import multiprocessing
import os
import socket
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sensei_top import logs
from sensei_top.archetypes.source import ARCHIVE_URL
from sensei_top.arena_config import DATE_ORDER_CHOICES
from sensei_top.db import connect, open_database
from sensei_top.live import ARENA_LOG_RESOLVE_SECONDS, DECK_POLL_SECONDS, MTGO_POLL_SECONDS
from sensei_top.mtgo.config import load_handle as mtgo_load_handle
from sensei_top.mtgo.config import resolve_deck_dir, resolve_log_dir
from sensei_top.mtgo.discover import discover_log_folder
from sensei_top.mtgo.discover import suggestion as mtgo_suggestion
from sensei_top.projector.matches import project
from sensei_top.reader.dates import AUTO
from sensei_top.reader.ingest import (
    ingest_file,
    ingest_with_recovery,
    watch,
)
from sensei_top.reader.mtgo import _mtime_iso, ingest_mtgo_dir
from sensei_top.reader.mtgo_decks import ingest_deck_dir
from sensei_top.reader.segmenter import DATE_ORDERS

if TYPE_CHECKING:
    from sensei_top.answers import Answer
    from sensei_top.metagame.auto import RefreshState
    from sensei_top.metagame.source import RefreshResult

DEFAULT_DB = Path("data/sensei-top.db")


def _resolve_log(argument: str | None) -> Path:
    """``--file``, else ``live.resolve_arena_log``: ``$MTGA_LOG``, then
    ``[arena] log``, then autodetection. Exits when none is found, or when
    ``--file`` names a missing file."""
    if argument:
        path = Path(argument)
    else:
        # Imported here, not at the top, so a test that replaces
        # live.resolve_arena_log replaces it for this module too.
        from sensei_top.live import resolve_arena_log

        path = resolve_arena_log()
    if path is None:
        sys.exit(
            "No log file found. Pass --file, set MTGA_LOG, or run "
            "'sensei-top config --set-arena-log PATH'."
        )
    if not path.exists():
        sys.exit(f"Log file not found: {path}")
    return path


def _resolve_locale(args) -> None:
    """``--locale`` when given, else ``[arena] date_order``, else ``auto``.
    Sets ``args.locale`` in place, before any watcher is built."""
    if getattr(args, "locale_given", False):
        return
    from sensei_top.arena_config import load_date_order

    args.locale = load_date_order() or AUTO


def _resolve_serve_log(argument: str | None) -> Path | None:
    """``serve --watch``'s Arena log: ``None`` when there is none to be
    found yet, where ``_resolve_log`` exits. An explicit ``--file`` that
    does not exist still exits."""
    if argument:
        return _resolve_log(argument)
    from sensei_top.live import resolve_arena_log

    return resolve_arena_log()


def _resolve_mtgo_dir(argument: str | None) -> Path:
    if argument:
        directory = Path(argument)
        source = None
    else:
        resolved = resolve_log_dir()
        if resolved is None:
            message = (
                "No MTGO log directory configured. Pass --dir, set MTGO_LOG_DIR, or run "
                "'sensei-top config --set-mtgo-dir DIR'."
            )
            hint = mtgo_suggestion(None, discover_log_folder())
            sys.exit(f"{message}\n{hint}" if hint else message)
        directory, source = resolved
    if not directory.exists():
        suffix = f" (from {source})" if source else ""
        message = f"Directory not found: {directory}{suffix}"
        # An explicit --dir (source None) is the user's own choice: no hint.
        hint = mtgo_suggestion(directory, discover_log_folder(), source) if source else None
        sys.exit(f"{message}\n{hint}" if hint else message)
    return directory


def _resolve_mtgo_deck_dir(argument: str | None) -> Path | None:
    """The MTGO deck folder for ``ingest-mtgo``: ``--deck-dir``, then
    ``$MTGO_DECK_DIR``, then ``[mtgo] deck_dir``. ``None`` when none is set —
    the deck folder is optional, so that is not an error. One that is named
    (by the flag or by configuration) but missing, or not a directory, *is*,
    exactly as for the game-log directory."""
    if argument:
        directory, source = Path(argument), None
    else:
        resolved = resolve_deck_dir()
        if resolved is None:
            return None
        directory, source = resolved
    suffix = f" (from {source})" if source else ""
    if not directory.exists():
        sys.exit(f"Deck directory not found: {directory}{suffix}")
    if not directory.is_dir():
        sys.exit(f"Deck path is not a directory: {directory}{suffix}")
    return directory


def _resolve_watch_mtgo_deck_dir(args) -> Path | None:
    """Fail-soft twin of ``_resolve_watch_mtgo_dir`` for the deck folder:
    nothing configured is the normal case; a configured folder that does not
    exist, or is not a directory, warns and is skipped (left alone, the
    watcher would log a failed read every poll for the rest of the session);
    an explicit ``--mtgo-deck-dir`` that is either is an error, through
    ``_resolve_mtgo_deck_dir``. ``--no-mtgo`` skips it along with the game
    logs."""
    if args.no_mtgo:
        return None
    if args.mtgo_deck_dir:
        return _resolve_mtgo_deck_dir(args.mtgo_deck_dir)
    resolved = resolve_deck_dir()
    if resolved is None:
        return None
    directory, source = resolved
    if directory.is_dir():
        return directory
    problem = "is not a directory" if directory.exists() else "does not exist"
    logging.getLogger(__name__).warning(
        "MTGO deck directory %s (from %s) %s; not reading MTGO decks this session",
        directory,
        source,
        problem,
    )
    return None


def _resolve_watch_mtgo_dir(args) -> Path | None:
    """Fail-soft, unlike ``_resolve_mtgo_dir``: a watch session with no MTGO
    directory configured is the normal case, not an error — most machines
    running ``serve --watch`` will never have one. A directory that *is*
    configured (via ``$MTGO_LOG_DIR`` or config.toml) but doesn't exist warns
    once, naming where it was configured, and returns ``None`` rather than
    raising. An *explicit* ``--mtgo-dir`` that doesn't exist is still an
    error: the user asked for that path."""
    if args.no_mtgo:
        return None
    if args.mtgo_dir:
        return _resolve_mtgo_dir(args.mtgo_dir)  # sys.exit on a bad explicit path
    resolved = resolve_log_dir()
    if resolved is None:
        return None
    directory, source = resolved
    if directory.exists():
        return directory
    logging.getLogger(__name__).warning(
        "MTGO log directory %s (from %s) does not exist; not reading MTGO logs this session",
        directory,
        source,
    )
    return None


def _open(args) -> object:
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return open_database(db_path)


def cmd_ingest(args) -> None:
    conn = _open(args)
    path = _resolve_log(args.file)
    _resolve_locale(args)
    if args.watch:
        if args.project:
            print(f"Watching {path}, projecting as it changes (Ctrl-C to stop)")
            _watch_and_project(args, path)
            return
        print(f"Watching {path} (Ctrl-C to stop)")
        for stats in watch(conn, path, locale_hint=args.locale, interval=args.interval):
            print(f"  {stats}")
        return
    if args.from_start:
        stats = ingest_file(conn, path, locale_hint=args.locale, from_start=True)
        print(f"{path.name}: {stats}")
    else:
        for name, stats in ingest_with_recovery(conn, path, locale_hint=args.locale).items():
            print(f"{name}: {stats}")


def cmd_ingest_mtgo(args) -> None:
    """Mirrors ``cmd_ingest``, but for MTGO's per-match ``.dat`` game logs and,
    when a deck folder is given or configured, its exported ``.dek`` deck
    files (``--deck-dir``); a deck folder alone is enough, with no game-log
    directory configured. Whenever the game-log directory is read, the
    ``grouping *.xml`` files MTGO's deck store keeps beside the logs are read
    from it too, with no setting of their own.

    No ``--watch`` here — that leg lives on ``ingest --watch --project`` and
    ``serve --watch`` instead (``_build_watcher``/``_build_watcher_process``
    below), since ``live.py``'s ``LiveIngester`` is the one module allowed to
    drive both stages for both sources (AGENTS.md non-negotiable #1). Those
    two commands store each game log once a game ends, after a first pass that
    stores every changed file at once; this command is that first pass by
    hand, storing every changed file whether or not its game has ended. No
    ``--locale`` either: MTGO's log carries no header timestamps to parse.
    """
    conn = _open(args)
    deck_dir = _resolve_mtgo_deck_dir(args.deck_dir)
    # With a deck folder and no game-log directory anywhere, read the decks
    # alone; with neither, keep the existing "nothing configured" exit.
    read_logs = bool(args.dir) or resolve_log_dir() is not None or deck_dir is None
    if read_logs:
        directory = _resolve_mtgo_dir(args.dir)
        if not args.dir:  # an explicit --dir is the user's own choice: no hint
            hint = mtgo_suggestion(directory, discover_log_folder(), resolve_log_dir()[1])
            if hint:
                print(hint)
        stats = ingest_mtgo_dir(conn, directory, from_start=args.from_start)
        total_bytes = conn.execute(
            "SELECT SUM(LENGTH(payload)) FROM raw_events WHERE source = 'mtgo'"
        ).fetchone()[0] or 0
        print(f"{directory}: {stats}")
        print(
            f"  {total_bytes:,} bytes of base64 payload stored for source='mtgo' "
            "(docs/architecture.md's storage note explains why this grows faster than the raw logs)"
        )
        # MTGO keeps its deck store, ``grouping *.xml``, beside the game logs:
        # read it from the same directory. A deck folder that is this
        # directory is read once, below only if it is a different one.
        grouping_stats = ingest_deck_dir(conn, directory, from_start=args.from_start)
        print(f"{directory}: {grouping_stats}")
        print("  deck store files (grouping *.xml) stored for source='mtgo_deck'")
        if deck_dir is not None and deck_dir.resolve() == directory.resolve():
            deck_dir = None
    if deck_dir is not None:
        deck_stats = ingest_deck_dir(conn, deck_dir, from_start=args.from_start)
        print(f"{deck_dir}: {deck_stats}")
        print("  deck files stored for source='mtgo_deck'")
    # Rows stored here come from another process than a running watcher's,
    # which stores its own game logs as each game ends (live.py): the watcher
    # notices these through project_if_due's external-rows check, at its next
    # due rebuild. A bare 'project' with no watcher attached needs telling
    # explicitly.
    print(
        "A running 'serve --watch' picks these rows up on its next rebuild; "
        "otherwise run 'sensei-top project' to bring matches/games up to date."
    )


def _fmt_age(seconds: float) -> str:
    """Human-readable elapsed time for ``cmd_mtgo_status``'s freshness report.
    A measurement, not a verdict — see that function's docstring."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def cmd_mtgo_status(args) -> None:
    """Diagnose the MTGO pipeline in one command: is a handle configured, is
    a log directory configured, and does it exist, how old is its newest
    file, and how far did the database get.

    Never raises on a missing directory or an empty database — a health
    check that crashes on the unhealthy case defeats its own purpose. Prints
    measurements, not conclusions (AGENTS.md non-negotiable #4): the newest
    file's age is reported as a fact, with a caveat that cuts both ways,
    rather than a hardcoded threshold declaring the transport "broken" — a
    stale directory is also what a day off from MTGO looks like.
    """
    import os
    import time

    conn = _open(args)

    handle = mtgo_load_handle()
    if handle is not None:
        source = "$MTGO_HANDLE" if os.environ.get("MTGO_HANDLE") else "config file"
        print(f"Handle:    {handle} (from {source})")
    else:
        print("Handle:    not configured")

    if args.dir:
        directory, dir_source = Path(args.dir), "--dir"
    else:
        resolved = resolve_log_dir()
        directory, dir_source = resolved if resolved is not None else (None, None)

    files: list[Path] = []
    newest_age_seconds: float | None = None
    if directory is None:
        print("Directory: not configured — run 'sensei-top config --set-mtgo-dir DIR'")
    elif not directory.exists():
        print(f"Directory: {directory} (from {dir_source}) — does not exist")
    else:
        files = sorted(directory.glob("Match_GameLog_*.dat"))
        print(
            f"Directory: {directory} (from {dir_source}) "
            f"({len(files)} Match_GameLog_*.dat file(s))"
        )
        if files:
            newest = max(files, key=lambda p: p.stat().st_mtime)
            newest_age_seconds = time.time() - newest.stat().st_mtime
            print(
                f"  Newest file: {newest.name}, logged_at {_mtime_iso(newest)} "
                f"({_fmt_age(newest_age_seconds)} old)"
            )

    raw_count, raw_max = conn.execute(
        "SELECT COUNT(*), MAX(logged_at) FROM raw_events WHERE source = 'mtgo'"
    ).fetchone()
    match_count = conn.execute("SELECT COUNT(*) FROM matches WHERE source = 'mtgo'").fetchone()[0]
    print(f"Database:  {raw_count} raw_events row(s) (newest logged_at: {raw_max or 'none'})")
    print(f"           {match_count} matches row(s)")

    if handle is None:
        print(
            "Verdict:   no MTGO handle configured — files will ingest but never project "
            "('sensei-top config --set-mtgo-handle YOURHANDLE' to fix)."
        )
    elif directory is None:
        print(
            "Verdict:   no MTGO log directory configured — nothing to ingest "
            "('sensei-top config --set-mtgo-dir DIR' to fix)."
        )
    elif not directory.exists():
        print(
            f"Verdict:   directory {directory} (from {dir_source}) not found — a measurement, "
            "not a diagnosis: it may be on a drive or share that isn't mounted yet."
        )
    elif not files:
        print(
            f"Verdict:   directory {directory} (from {dir_source}) found but holds no "
            "Match_GameLog_*.dat files yet."
        )
    else:
        print(
            f"Verdict:   newest file is {_fmt_age(newest_age_seconds)} old — a measurement, "
            "not a diagnosis: it may mean the transport isn't running, or simply that no "
            "MTGO match has been played since."
        )


def _build_watcher(args, path: Path):
    from sensei_top.live import LiveIngester

    return LiveIngester(
        db_path=Path(args.db),
        log_path=path,
        locale_hint=args.locale,
        interval=args.interval,
        project_every=args.project_every,
        duty_factor=args.duty_factor,
        mtgo_dir=_resolve_watch_mtgo_dir(args),
        mtgo_deck_dir=_resolve_watch_mtgo_deck_dir(args),
    )


def _build_watcher_process(args, path: Path | None):
    """Same construction as ``_build_watcher``, but for ``serve --watch``:
    the rebuild has to run outside the API's own process, or it contends
    with every request for the GIL (measured in
    docs/architecture.md, "Live mode's two cadences"). ``ingest --watch`` has
    no API to contend with, so it uses ``_build_watcher``'s in-process
    ``LiveIngester``."""
    from sensei_top.live import WatcherProcess

    return WatcherProcess(
        db_path=Path(args.db),
        log_path=path,
        locale_hint=args.locale,
        interval=args.interval,
        project_every=args.project_every,
        duty_factor=args.duty_factor,
        mtgo_dir=_resolve_watch_mtgo_dir(args),
        mtgo_deck_dir=_resolve_watch_mtgo_deck_dir(args),
    )


def _watch_and_project(args, path: Path) -> None:
    watcher = _build_watcher(args, path)
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stats = watcher.stats
        print(
            f"\nStopped after {stats.polls} polls: {stats.events_ingested} events, "
            f"{stats.projections} projections, {stats.errors} errors"
        )


def cmd_project(args) -> None:
    from sensei_top.archetypes import classify_matches

    conn = _open(args)
    counts = project(conn)
    print(
        f"{counts['matches']} matches, {counts['games']} games, "
        f"{counts['turns']} turns, {counts['card_events']} card events, "
        f"{counts['decks']} decks ({counts['warnings']} warnings)"
    )
    named = classify_matches(conn)
    print(
        f"{named['classified']} opponent decks named "
        f"({named['high']} high, {named['medium']} medium, {named['low']} low), "
        f"{named['unclassified']} unidentified"
    )


def cmd_restore(args) -> None:
    """Replace the database with a backup. Stop ``serve`` first; the
    command cannot tell whether one is running."""
    from sensei_top.archetypes import classify_matches
    from sensei_top.backup import RestoreError, restore_files

    try:
        restore_files(Path(args.file), Path(args.db))
    except RestoreError as e:
        code = getattr(e, "exit_code", 1)
        if code == 1:
            sys.exit(str(e))
        print(str(e), file=sys.stderr)
        sys.exit(code)
    print("Migrating and rebuilding matches...")
    conn = _open(args)
    counts = project(conn)
    classify_matches(conn)
    print(f"Restored: {counts['matches']} matches.")


def cmd_archetypes(args) -> None:
    from sensei_top.archetypes import classify_matches
    from sensei_top.archetypes.source import cache_age_seconds, refresh_archetypes

    conn = _open(args)
    result = refresh_archetypes(conn, force=args.force, url=args.url)
    if result.status == "failed":
        # Being offline is not a failure of the command: the cached copy still
        # names decks, so say how old it is and exit successfully.
        age = cache_age_seconds(conn)
        cached = f"{age / 3600:.0f}h old" if age is not None else "no cached copy"
        print(f"Could not refresh ({result.error}); keeping what is stored ({cached}).")
    elif result.status == "fresh":
        print(f"Definitions are {(result.age_seconds or 0) / 3600:.0f}h old; nothing to do.")
    else:
        skipped = f", {result.skipped} skipped" if result.skipped else ""
        print(f"{result.files} archetype definitions stored{skipped}.")

    named = classify_matches(conn)
    print(f"{named['classified']} opponent decks named, {named['unclassified']} unidentified")


def _format_arg(value: str) -> str:
    """A ``--format`` value, in ``FORMATS`` spelling; anything else is refused
    with the list."""
    from sensei_top.formats import FORMATS

    for fmt in FORMATS:
        if fmt.lower() == value.strip().lower():
            return fmt
    raise argparse.ArgumentTypeError(
        f"{value!r} is not a format; choose one of {', '.join(FORMATS)}"
    )


def _utc_now() -> datetime:
    """The clock ``meta`` and ``serve``'s corpus refresh run on: an aware UTC
    time, which every hold and fetch line is judged against."""
    return datetime.now(UTC)


def _meta_force(args) -> bool:
    """A ``--format`` names formats the stored corpus may not hold yet, so the
    per-source freshness window — kept per source, not per format — must not
    decide it; unchanged files are still skipped by content."""
    return bool(args.force or getattr(args, "formats", None))


def _run_metagame_refresh(conn, args, formats: Sequence[str]) -> None:
    """The fbettega cache refresh. Its ``cache: …`` lines are this
    function's own: ``metagame/fetch_lines.py`` has none for fbettega."""
    from sensei_top.metagame import source

    result = source.refresh_metagame(
        conn, window_days=args.window_days, force=_meta_force(args), formats=formats
    )
    if result.status == "failed":
        age = source.cache_age_seconds(conn, source="fbettega")
        cached = f"{age / 3600:.0f}h old" if age is not None else "no cached copy"
        print(f"cache: could not refresh ({result.error}); keeping what is stored ({cached}).")
    elif result.status == "fresh":
        print(f"cache: corpus is {(result.age_seconds or 0) / 3600:.0f}h old; nothing to do.")
    else:
        skipped = f", {result.skipped} skipped" if result.skipped else ""
        print(f"cache: {result.events} tournament events stored at {result.commit_sha}{skipped}.")


def _print_fetch_lines(name: str, result: RefreshResult) -> None:
    """mtgo.com's or TopDeck's lines for a hand run, as ``fetch_lines``
    words them on ``meta``: it always has one."""
    from sensei_top.metagame import fetch_lines

    for line in fetch_lines.render(name, result, surface=fetch_lines.META, now=_utc_now()):
        print(line)


def _run_topdeck_refresh(conn, args, formats: Sequence[str]) -> None:
    """The TopDeck.gg refresh, run by hand. With no key configured it says so
    only under ``--source topdeck``, its line's own condition; otherwise it is
    as silent as any other unconfigured free download (AGENTS.md
    non-negotiable #5). Every other line, the "no answer for" hint
    included, is ``fetch_lines``'."""
    from sensei_top.metagame import topdeck
    from sensei_top.metagame.holds import TOPDECK

    result = topdeck.refresh_topdeck(
        conn, window_days=args.window_days, force=_meta_force(args), formats=formats,
        now=_utc_now, by_hand=True,
    )
    if result.status == "not_configured" and args.source != "topdeck":
        return
    _print_fetch_lines(TOPDECK, result)


def _run_mtgo_site_refresh(conn, args, formats: Sequence[str]) -> None:
    """Direct mtgo.com decklist pages, run by hand: a pause standing on the
    source gets one ordinary run (``holds.gate``)."""
    from sensei_top.metagame import mtgo_site
    from sensei_top.metagame.holds import MTGO

    result = mtgo_site.refresh_mtgo_site(
        conn, force=_meta_force(args), formats=formats, now=_utc_now, by_hand=True
    )
    _print_fetch_lines(MTGO, result)


def cmd_meta(args) -> None:
    from sensei_top.metagame.auto import followed_formats, reclassify_corpus

    conn = _open(args)
    if args.reclassify:
        # No network at all: re-run the classifier over whatever corpus is
        # already stored, e.g. after an archetype-definition refresh, and set
        # aside duplicate tournament events (metagame/dedup.py).
        duplicates, counts = reclassify_corpus(conn)
        if duplicates:
            print(f"{duplicates} duplicate tournament events set aside.")
        print(f"{counts['classified']} decks classified, {counts['unclassified']} unidentified "
              f"({counts['skipped_format']} skipped, other formats)")
        return

    # The formats serve's loop follows, plus any --format, so the command
    # and the loop never fetch different sets.
    formats = followed_formats(conn, args.formats or ())
    if args.source in ("cache", "all"):
        _run_metagame_refresh(conn, args, formats)
    if args.source in ("mtgo", "all"):
        _run_mtgo_site_refresh(conn, args, formats)
    if args.source in ("topdeck", "all"):
        _run_topdeck_refresh(conn, args, formats)

    duplicates, counts = reclassify_corpus(conn)
    if duplicates:
        print(f"{duplicates} duplicate tournament events set aside.")
    print(f"{counts['classified']} decks classified, {counts['unclassified']} unidentified")


def cmd_backup(args) -> None:
    """Take (or check on) today's ``VACUUM INTO`` snapshot of the database.

    One deliberate divergence from ``cmd_archetypes``: that command exits 0
    on a failed refresh because the cached definitions still name decks, so
    nothing was actually lost. A failed backup is different —
    the user (or the scheduler) asked for a safety copy and did not get one,
    so **this command exits non-zero on failure**, naming the error and the
    age of whatever good backup is still sitting there untouched.
    """
    from sensei_top.backup import claim_age_seconds, read_state, resolve, run_backup

    db_path = Path(args.db)
    if not db_path.exists():
        sys.exit(f"No database at {db_path}. Run 'sensei-top ingest' then 'project' first.")

    conn = _open(args)
    cfg = resolve(db_path, dir_override=args.dir, keep_override=args.keep)
    try:
        result = run_backup(conn, db_path, cfg=cfg, force=args.force, deep_verify=args.deep_verify)
    except KeyboardInterrupt:
        # run_backup's own `finally` ran on the way up, KeyboardInterrupt
        # included: the temp file is gone and the claim released already.
        sys.exit("Backup cancelled; any existing backup was left untouched.")

    if result.status == "ok":
        shrink = ""
        if result.bytes is not None and result.source_bytes:
            pct = 100 * (1 - result.bytes / result.source_bytes)
            shrink = f" ({pct:.1f}% smaller)" if pct >= 0 else f" ({-pct:.1f}% larger)"
        print(f"Backed up {db_path} -> {result.path}")
        print(f"  Source:    {result.source_bytes:,} bytes, schema_version {result.schema_version}")
        print(f"  Backup:    {result.bytes:,} bytes{shrink}, verified")
        # A sub-second copy of a small database rounds to "0s", which reads as
        # "nothing happened" rather than "that was fast" — so keep a decimal
        # until the number is large enough to speak for itself.
        took = result.duration_seconds
        print(f"  Took:      {took:.1f}s" if took < 10 else f"  Took:      {took:.0f}s")
        total_kept = result.numbered_kept + 1
        detail = (
            "current slot only"
            if result.numbered_kept == 0
            else f"current + {result.numbered_kept} older"
        )
        print(f"  Keeping:   {total_kept} ({detail})")
        return

    if result.status == "fresh":
        print(
            f"Last backup was {_fmt_age(result.age_seconds)} ago; "
            "nothing to do (--force to run anyway)."
        )
        state = read_state(conn)
        if state is not None and state["last_path"]:
            print(f"  Current:   {state['last_path']}")
            print(
                f"             {state['last_bytes']:,} bytes, "
                f"schema_version {state['last_schema_version']}"
            )
        return

    if result.status == "busy":
        started_ago = claim_age_seconds(conn)
        when = f"{_fmt_age(started_ago)} ago " if started_ago is not None else ""
        print(f"A backup started {when}(pid {result.running_pid}) is still running; nothing to do.")
        return

    # 'failed' or 'interrupted' (the latter only reachable if a caller passes
    # its own `stop` event, which this command never does — handled anyway
    # so this stays exhaustive rather than silently falling through).
    lines = [f"Backup failed: {result.error}"]
    if result.age_seconds is not None:
        lines.append(f"  The existing backup is untouched: {_fmt_age(result.age_seconds)} old.")
    else:
        lines.append("  No backup exists yet.")
    sys.exit("\n".join(lines))


def _read_config_tables() -> dict[str, dict[str, object]]:
    """Every top-level table this config file holds, read tolerantly.

    Every writer below goes through this pair of functions rather than
    reading and writing its own table: the file holds several unrelated
    tables, and a writer that rewrote only its own would silently drop the
    others. A value is a string, a bool, or — one level deep only,
    e.g. ``[claude.coach]`` — another such table; anything else is dropped
    rather than round-tripped imperfectly.
    """
    import tomllib

    from sensei_top.llm.config import config_path

    def _table(raw: dict) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                result[str(key)] = _table(value)
            elif isinstance(value, bool):
                result[str(key)] = value
            else:
                result[str(key)] = str(value)
        return result

    path = config_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}
    return {name: _table(table) for name, table in data.items() if isinstance(table, dict)}


def _write_config_tables(tables: dict[str, dict[str, object]]) -> None:
    """Serialize every table back out, including one level of nested
    sub-table (e.g. ``[claude.coach]``) and real TOML booleans.
    Hand-written TOML, not a library: the value set stays small enough that
    a ``tomli-w`` dependency buys nothing here."""
    from sensei_top.llm.config import config_path

    def _escaped(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _line(key: str, value: object) -> str:
        if isinstance(value, bool):
            return f"{key} = {'true' if value else 'false'}"
        return f'{key} = "{_escaped(str(value))}"'

    lines: list[str] = []
    for table_name, fields in tables.items():
        scalars = {k: v for k, v in fields.items() if not isinstance(v, dict)}
        sub_tables = {k: v for k, v in fields.items() if isinstance(v, dict)}

        lines.append(f"[{table_name}]")
        lines.extend(_line(key, value) for key, value in scalars.items())
        lines.append("")

        for sub_name, sub_fields in sub_tables.items():
            lines.append(f"[{table_name}.{sub_name}]")
            lines.extend(_line(key, value) for key, value in sub_fields.items())
            lines.append("")

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    path.chmod(0o600)


def _merge(table: dict[str, object], key: str, value: object | None) -> None:
    """``None`` leaves ``table[key]`` as it is; an empty string removes it, so
    the built-in default applies again; anything else sets it."""
    if value is None:
        return
    if value == "":
        table.pop(key, None)
    else:
        table[key] = value


def _put_table(tables: dict[str, dict[str, object]], name: str, table: dict[str, object]) -> None:
    """Sets one table, or drops it once nothing is left in it: an empty
    ``[topdeck]`` reads as a table with no key, which warns."""
    if table:
        tables[name] = table
    else:
        tables.pop(name, None)


def _write_llm_config(
    *,
    api_key: str | None,
    model: str | None,
    effort: str | None,
    coach_model: str | None = None,
    coach_effort: str | None = None,
    coach_web_search: bool | None = None,
) -> None:
    """Merge the given fields into the existing ``[claude]`` table (if any)
    and its ``[claude.coach]`` sub-table, leaving every other table
    untouched. ``None`` leaves a field as it is and an empty
    string removes it (``_merge``). The key need not be in this file for the
    other fields to be written: it may live in the keyring or the
    environment, or be set later."""
    tables = _read_config_tables()
    claude = dict(tables.get("claude", {}))
    coach = claude.pop("coach", None)
    coach = dict(coach) if isinstance(coach, dict) else {}

    _merge(claude, "api_key", api_key)
    _merge(claude, "model", model)
    _merge(claude, "effort", effort)
    _merge(coach, "model", coach_model)
    _merge(coach, "effort", coach_effort)
    if coach_web_search is not None:
        coach["web_search"] = bool(coach_web_search)
    if coach:
        claude["coach"] = coach

    _put_table(tables, "claude", claude)
    _write_config_tables(tables)


def _write_topdeck_config(*, api_key: str) -> None:
    """Merge into the existing ``[topdeck]`` table (if any), leaving every
    other table untouched."""
    tables = _read_config_tables()
    topdeck = dict(tables.get("topdeck", {}))
    topdeck["api_key"] = api_key
    tables["topdeck"] = topdeck
    _write_config_tables(tables)


def _drop_file_key(table_name: str) -> bool:
    """Remove ``api_key`` from one table of the file, keeping its other
    fields; ``True`` when there was one. Writes nothing when there was none."""
    tables = _read_config_tables()
    table = dict(tables.get(table_name, {}))
    if "api_key" not in table:
        return False
    del table["api_key"]
    _put_table(tables, table_name, table)
    _write_config_tables(tables)
    return True


def _write_mtgo_config(
    *, handle: str | None = None, directory: str | None = None, deck_dir: str | None = None
) -> None:
    """Merge into the existing ``[mtgo]`` table (if any), leaving every
    other table untouched, and **within its own table field by field** too:
    ``--set-mtgo-dir`` alone must not erase a ``handle`` set earlier by
    ``--set-mtgo-handle``, or vice versa, since the flags are independent and
    typically run on separate occasions. An empty string clears its field
    (``_merge``). No field is a secret — the handle is the user's own MTGO
    account name, needed only because MTGO's log carries no auth event to
    learn "which player is us" from, and the directories are paths on the
    user's own machine (``mtgo/config.py``'s module docstring covers all
    three) — so unlike the two API keys, nothing here masks any of them."""
    tables = _read_config_tables()
    table = dict(tables.get("mtgo", {}))
    _merge(table, "handle", handle)
    _merge(table, "dir", directory)
    _merge(table, "deck_dir", deck_dir)
    _put_table(tables, "mtgo", table)
    _write_config_tables(tables)


def _write_backup_config(
    *, directory: str | None = None, keep: int | str | None = None
) -> None:
    """Merge into the existing ``[backup]`` table (if any), field by field
    for the same reason as ``_write_mtgo_config``; an empty string clears its
    field. ``keep`` is written through ``_write_config_tables`` the same as
    every other value there -- as a quoted string -- which is exactly the
    shape ``backup.config._parse_keep`` exists to accept back as a number
    rather than mistake for "not configured" (see its docstring)."""
    tables = _read_config_tables()
    table = dict(tables.get("backup", {}))
    _merge(table, "dir", directory)
    _merge(table, "keep", keep)
    _put_table(tables, "backup", table)
    _write_config_tables(tables)


def _write_arena_config(*, log: str | None = None, date_order: str | None = None) -> None:
    """Merge into the ``[arena]`` table, field by field like
    ``_write_mtgo_config``; an empty string clears its field."""
    tables = _read_config_tables()
    table = dict(tables.get("arena", {}))
    _merge(table, "log", log)
    _merge(table, "date_order", date_order)
    _put_table(tables, "arena", table)
    _write_config_tables(tables)


# For each keyring entry (``secrets.CLAUDE``, ``secrets.TOPDECK``): the name a
# message uses, its config.toml table, and the environment variable that
# outranks both stores.
_KEYS = {
    "claude": ("Claude", "claude", "ANTHROPIC_API_KEY"),
    "topdeck": ("TopDeck.gg", "topdeck", "TOPDECK_API_KEY"),
}


def _key_source(which: str) -> str | None:
    """Where the key in force comes from, asked of the one module that
    resolves it (AGENTS.md non-negotiable #5 for the Claude key)."""
    if which == "claude":
        from sensei_top.llm import config as llm_config

        return llm_config.key_source()
    from sensei_top.metagame import config as topdeck_config

    return topdeck_config.key_source()


def _source_label(which: str) -> str:
    """``config``'s summary names where a key came from."""
    from sensei_top import secrets
    from sensei_top.llm.config import config_path

    source = _key_source(which)
    if source == "env":
        return f"${_KEYS[which][2]}"
    if source == "keyring":
        backend = secrets.backend_name()
        return f"the system keyring ({backend})" if backend else "the system keyring"
    return str(config_path())


def _key_value(raw: str) -> str:
    """The key ``--set-key``/``--set-topdeck-key`` was given. ``-`` reads one
    line from stdin (any process on the machine can read another's argv),
    without echo when stdin is a terminal. The value is never printed
    or logged, here or by any caller."""
    if raw == "-":
        if sys.stdin is not None and sys.stdin.isatty():
            import getpass

            raw = getpass.getpass("Key: ")
        else:
            raw = sys.stdin.readline() if sys.stdin is not None else ""
    key = raw.strip()
    if not key:
        sys.exit("No key given. To remove a key, use --clear-key or --clear-topdeck-key.")
    return key


def _store_key(which: str, key: str) -> None:
    """The system keyring when it takes the key, and then the file's copy is
    removed; else the file (mode 600), saying why."""
    from sensei_top import secrets
    from sensei_top.llm.config import config_path

    name, table, env = _KEYS[which]
    if secrets.set(which, key):
        _drop_file_key(table)
        backend = secrets.backend_name()
        print(f"{name} key stored in the system keyring ({backend}).")
    else:
        if which == "claude":
            _write_llm_config(api_key=key, model=None, effort=None)
        else:
            _write_topdeck_config(api_key=key)
        reason = (
            "no system keyring was found"
            if secrets.backend_name() is None
            else "the system keyring did not take it (the log says why)"
        )
        print(f"{name} key written to {config_path()} (mode 600): {reason}.")
        if _key_source(which) == "keyring":
            print(f"  An older {name} key in the system keyring still wins over the file.")
    if os.environ.get(env):
        print(f"  ${env} is set, and it wins over the stored key.")


def _clear_key(which: str) -> None:
    """Remove a key from the keyring and from the file. Exits non-zero when
    a keyring exists but would not let go of it."""
    from sensei_top import secrets

    name, table, env = _KEYS[which]
    gone_from_keyring = secrets.delete(which)
    _drop_file_key(table)
    if not gone_from_keyring and secrets.backend_name() is not None:
        sys.exit(f"Could not remove the {name} key from the system keyring (the log says why).")
    print(f"{name} key removed.")
    if os.environ.get(env):
        print(f"  ${env} is still set, and it still supplies a key.")


def _move_keys_to_keyring() -> None:
    """Move every key the file holds into the system keyring, on request
    only: nothing moves a key without this flag. A keyring that already
    holds a different key keeps it, and the file's copy stays where it is,
    since overwriting would change which key is in force."""
    from sensei_top import secrets
    from sensei_top.llm.config import config_path

    path = config_path()
    backend = secrets.backend_name()
    if backend is None:
        sys.exit(f"No system keyring was found; the keys stay in {path}.")
    tables = _read_config_tables()
    moved = 0
    problems: list[str] = []
    for which, (name, table, _env) in _KEYS.items():
        file_key = tables.get(table, {}).get("api_key")
        if not isinstance(file_key, str) or not file_key:
            continue
        held = secrets.get(which)
        if held is not None and held != file_key:
            problems.append(
                f"The system keyring already holds a different {name} key; "
                f"the one in {path} was left where it is. "
                "Run 'sensei-top config --set-key -' (or --set-topdeck-key -) with the key "
                "you want: it goes to the keyring and the file's copy is removed."
            )
            continue
        if held is None and not secrets.set(which, file_key):
            problems.append(
                f"Could not store the {name} key in the system keyring "
                f"(the log says why); it stays in {path}."
            )
            continue
        _drop_file_key(table)
        moved += 1
        print(f"{name} key moved to the system keyring ({backend}).")
    if problems:
        sys.exit("\n".join(problems))
    if moved == 0:
        print(f"No keys in {path} to move.")


def _config_json(db_path: Path) -> dict[str, object]:
    """Every value the Settings page shows, and no secret: for
    each key only whether one is set and where it comes from (``env``,
    ``keyring``, ``file`` or ``null``). Other values are the file's own,
    with the built-in default where one exists; the backup folder and count
    are resolved against ``--db``, as the summary resolves them."""
    from sensei_top.arena_config import load_date_order
    from sensei_top.backup import resolve as resolve_backup_config
    from sensei_top.llm import client as llm_client
    from sensei_top.llm.config import DEFAULT_EFFORT, DEFAULT_MODEL, config_path

    tables = _read_config_tables()

    def _value(table: str, key: str) -> str | None:
        value = tables.get(table, {}).get(key)
        return value if isinstance(value, str) and value else None

    claude_source = _key_source("claude")
    topdeck_source = _key_source("topdeck")
    backup = resolve_backup_config(db_path)
    return {
        "config_path": str(config_path()),
        "arena": {"log": _value("arena", "log"), "date_order": load_date_order() or AUTO},
        "mtgo": {
            "handle": _value("mtgo", "handle"),
            "dir": _value("mtgo", "dir"),
            "deck_dir": _value("mtgo", "deck_dir"),
        },
        "backup": {"dir": str(backup.directory), "keep": backup.keep},
        "claude": {
            "key_set": claude_source is not None,
            "key_source": claude_source,
            "model": _value("claude", "model") or DEFAULT_MODEL,
            "effort": _value("claude", "effort") or DEFAULT_EFFORT,
        },
        "topdeck": {"key_set": topdeck_source is not None, "key_source": topdeck_source},
        "models": [
            {"value": model_id, "label": label}
            for model_id, label in llm_client.REPORT_MODELS.items()
        ],
    }


def _written(what: str, value: str) -> None:
    from sensei_top.llm.config import config_path

    if value == "":
        print(f"{what} cleared in {config_path()}.")
    else:
        print(f"{what} written to {config_path()} (mode 600).")


def cmd_config(args) -> None:
    """``--set-*`` and ``--clear-*`` write; ``--json`` prints every setting
    for the desktop shell, which never writes the file itself; with no flag,
    or ``--show``, a summary: the two resolved credentials (source and the
    key masked to its last 4 characters) plus the configured MTGO handle, log
    directory and deck directory, each shown in full with its own source
    (none is a secret, see ``_write_mtgo_config``), and where backups go. It
    never prints a full key; outside the keyring the only full copy is the
    file's contents, which is why ``_write_config_tables`` chmods it 600.

    A key goes to the system keyring when there is one, and to the file
    otherwise; ``-`` reads it from stdin instead of argv. An empty value
    clears any other setting. Every given flag is applied in one run.

    Five independent groups share one file: the metered Claude key
    (AGENTS.md non-negotiable #5), the free, rate-limited TopDeck.gg key (the
    "free downloads" standard), the ``[mtgo]`` table (the handle
    ``project()`` needs to know which seat in an MTGO game log is ours, and
    the game-log and deck-export directories), the ``[arena]`` table, and
    the backup destination and retention count. A flag for one never touches
    another's table (``_read_config_tables``).
    """
    from sensei_top.llm import config as llm_config
    from sensei_top.metagame import config as topdeck_config

    coach_web_search = {"on": True, "off": False}.get(args.coach_web_search)
    llm_fields = (
        args.set_model,
        args.set_effort,
        args.set_coach_model,
        args.set_coach_effort,
    )
    writes = any(
        value is not None
        for value in (
            args.set_key,
            args.set_topdeck_key,
            args.set_mtgo_handle,
            args.set_mtgo_dir,
            args.set_mtgo_deck_dir,
            args.set_backup_dir,
            args.set_backup_keep,
            args.set_arena_log,
            args.set_date_order,
            coach_web_search,
            *llm_fields,
        )
    ) or (args.clear_key or args.clear_topdeck_key or args.move_keys_to_keyring)

    if args.json:
        if writes:
            sys.exit("config --json cannot be combined with a --set or --clear flag.")
        import json

        print(json.dumps(_config_json(Path(args.db))))
        return

    if args.set_key == "-" and args.set_topdeck_key == "-":
        sys.exit("Only one key can be read from stdin at a time.")

    if args.move_keys_to_keyring:
        _move_keys_to_keyring()

    for which, value, clear in (
        ("claude", args.set_key, args.clear_key),
        ("topdeck", args.set_topdeck_key, args.clear_topdeck_key),
    ):
        if clear:
            _clear_key(which)
        elif value is not None:
            _store_key(which, _key_value(value))

    if args.set_mtgo_handle is not None:
        _write_mtgo_config(handle=args.set_mtgo_handle)
        _written("MTGO handle", args.set_mtgo_handle)

    if args.set_mtgo_dir is not None:
        resolved_dir = args.set_mtgo_dir
        if resolved_dir:
            resolved_dir = str(Path(resolved_dir).expanduser().resolve())
            if not Path(resolved_dir).exists():
                print(f"{resolved_dir} does not exist yet; stored anyway.")
        _write_mtgo_config(directory=resolved_dir)
        _written("MTGO log directory", resolved_dir)

    if args.set_mtgo_deck_dir is not None:
        resolved_deck_dir = args.set_mtgo_deck_dir
        if resolved_deck_dir:
            resolved_deck_dir = str(Path(resolved_deck_dir).expanduser().resolve())
            if not Path(resolved_deck_dir).exists():
                print(f"{resolved_deck_dir} does not exist yet; stored anyway.")
        _write_mtgo_config(deck_dir=resolved_deck_dir)
        _written("MTGO deck directory", resolved_deck_dir)

    if args.set_arena_log is not None:
        arena_log = args.set_arena_log
        if arena_log:
            arena_log = str(Path(arena_log).expanduser().resolve())
            if not Path(arena_log).exists():
                print(f"{arena_log} does not exist yet; stored anyway.")
        _write_arena_config(log=arena_log)
        _written("Arena log path", arena_log)

    if args.set_date_order is not None:
        _write_arena_config(date_order=args.set_date_order)
        _written("Date order", args.set_date_order)

    if args.set_backup_dir is not None or args.set_backup_keep is not None:
        _write_backup_config(directory=args.set_backup_dir, keep=args.set_backup_keep)
        print(f"Backup settings written to {llm_config.config_path()} (mode 600).")

    if any(value is not None for value in llm_fields) or coach_web_search is not None:
        _write_llm_config(
            api_key=None,
            model=args.set_model,
            effort=args.set_effort,
            coach_model=args.set_coach_model,
            coach_effort=args.set_coach_effort,
            coach_web_search=coach_web_search,
        )
        print(f"Config written to {llm_config.config_path()} (mode 600).")

    if writes and not args.show:
        return

    cfg = llm_config.load()
    if cfg is None:
        print("No Claude credential configured. Every generate button falls back to its prompt.")
        print("  Run 'sensei-top config --set-key KEY', or export ANTHROPIC_API_KEY.")
    else:
        source = _source_label("claude")
        masked = f"...{cfg.api_key[-4:]}" if len(cfg.api_key) >= 4 else "(too short to mask)"
        print(f"Claude credential source: {source}")
        print(f"  API key: {masked}")
        print(f"  Model:   {cfg.model}")
        print(f"  Effort:  {cfg.effort}")

        coach_cfg = llm_config.load_coach()
        if coach_cfg is not None and (
            coach_cfg.model != cfg.model
            or coach_cfg.effort != cfg.effort
            or coach_cfg.web_search != cfg.web_search
        ):
            print("  Coach overrides:")
            if coach_cfg.model != cfg.model:
                print(f"    Model:       {coach_cfg.model}")
            if coach_cfg.effort != cfg.effort:
                print(f"    Effort:      {coach_cfg.effort}")
            if coach_cfg.web_search != cfg.web_search:
                print(f"    Web search:  {'on' if coach_cfg.web_search else 'off'}")

    topdeck = topdeck_config.load()
    if topdeck is None:
        print("No TopDeck.gg key configured. 'sensei-top meta' will skip that source.")
        print("  Run 'sensei-top config --set-topdeck-key KEY', or export TOPDECK_API_KEY.")
    else:
        source = _source_label("topdeck")
        masked = (
            f"...{topdeck.api_key[-4:]}" if len(topdeck.api_key) >= 4 else "(too short to mask)"
        )
        print(f"TopDeck.gg key source: {source}")
        print(f"  API key: {masked}")

    mtgo_handle = mtgo_load_handle()
    if mtgo_handle is None:
        print("No MTGO handle configured. MTGO logs will be stored but skipped at projection.")
        print("  Run 'sensei-top config --set-mtgo-handle YOURHANDLE', or export MTGO_HANDLE.")
    else:
        env_set = os.environ.get("MTGO_HANDLE")
        source = "$MTGO_HANDLE" if env_set else str(llm_config.config_path())
        print(f"MTGO handle source: {source}")
        print(f"  Handle: {mtgo_handle}")

    resolved_dir = resolve_log_dir()
    if resolved_dir is None:
        print("No MTGO log directory configured. The watcher won't read MTGO logs.")
        print("  Run 'sensei-top config --set-mtgo-dir DIR', or export MTGO_LOG_DIR.")
    else:
        mtgo_dir, mtgo_dir_source = resolved_dir
        print(f"MTGO directory source: {mtgo_dir_source}")
        print(f"  Directory: {mtgo_dir}")

    resolved_deck = resolve_deck_dir()
    if resolved_deck is None:
        print("No MTGO deck directory configured. MTGO deck exports won't be read.")
        print("  Run 'sensei-top config --set-mtgo-deck-dir DIR', or export MTGO_DECK_DIR.")
    else:
        deck_dir, deck_dir_source = resolved_deck
        print(f"MTGO deck directory source: {deck_dir_source}")
        print(f"  Directory: {deck_dir}")

    from sensei_top.arena_config import load_date_order, load_log

    arena_log = load_log()
    if arena_log is not None:
        print(f"Arena log (config.toml [arena] log): {arena_log}")
    date_order = load_date_order()
    if date_order is not None:
        print(f"Arena date order (config.toml [arena] date_order): {date_order}")

    import sqlite3

    from sensei_top.backup import last_backup_age_seconds, last_error_age_seconds, read_state
    from sensei_top.backup import resolve as resolve_backup_config

    db_path = Path(args.db)
    backup_cfg = resolve_backup_config(db_path)
    print(f"Backup destination: {backup_cfg.directory} (from {backup_cfg.dir_source})")
    print(f"  Keep:   {backup_cfg.keep}")

    if db_path.exists():
        # A read-only URI connection, never plain connect(): that would
        # *create* a missing file, and an empty database renders identically
        # to "no games yet" (docs/conventions.md). Wrapped broadly because an
        # old database with migration 039 still pending has no backup_state
        # table yet, which should read the same as "never backed up", not
        # crash this command.
        state = None
        try:
            ro_conn = sqlite3.connect(Path(db_path).absolute().as_uri() + "?mode=ro", uri=True)
            ro_conn.row_factory = sqlite3.Row
            try:
                state = read_state(ro_conn)
                last_age = last_backup_age_seconds(ro_conn)
                error_age = last_error_age_seconds(ro_conn)
            finally:
                ro_conn.close()
        except sqlite3.Error:
            last_age = error_age = None

        has_newer_error = state is not None and state["last_error"] and (
            not state["last_backup_at"]
            or (state["last_error_at"] or "") > state["last_backup_at"]
        )
        if last_age is None:
            if has_newer_error:
                print(
                    f"  Last:   never — most recent attempt FAILED {_fmt_age(error_age)} ago: "
                    f"{state['last_error']}"
                )
            else:
                print("  Last:   never — run 'sensei-top backup', or leave 'serve' running")
        elif has_newer_error:
            print(
                f"  Last:   {_fmt_age(last_age)} ago ({state['last_bytes']:,} bytes); "
                f"most recent attempt FAILED {_fmt_age(error_age)} ago: {state['last_error']}"
            )
        else:
            print(
                f"  Last:   {_fmt_age(last_age)} ago, "
                f"{state['last_bytes']:,} bytes at {state['last_path']}"
            )
    else:
        # An explicit empty state rather than silence, the same way cmd_report
        # prints "(no completed matches yet)" — a destination and a keep with
        # nothing under them otherwise reads as "configured and working".
        print(f"  Last:   no database at {db_path} yet")


def cmd_cards(args) -> None:
    from sensei_top.cards import (
        arena_card_database_path,
        fetch_default_cards,
        import_arena_cards,
        upsert_cards,
    )

    conn = _open(args)
    source = None if args.scryfall else arena_card_database_path()
    if source is not None:
        print(f"Reading card names from the installed client: {source.name}")
        count = import_arena_cards(conn, source)
    else:
        if not args.scryfall:
            print("No Arena installation found; falling back to Scryfall.")
        as_json = args.progress
        count = upsert_cards(conn, fetch_default_cards(as_json=as_json), progress_json=as_json)
    print(f"{count} cards stored in {args.db}")


def _fmt(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "  —"


def cmd_report(args) -> None:
    conn = _open(args)
    if args.metric in ("winrate", "all"):
        print("\nWinrate by deck")
        print("-" * 62)
        rows = conn.execute(
            """
            SELECT COALESCE(deck_name, substr(deck_id, 1, 8), '(no deck)') AS deck, event_id,
                   matches_completed, matches_won, games_won, games_lost
              FROM v_deck_winrate ORDER BY matches_completed DESC
            """
        ).fetchall()
        for r in rows:
            played = r["matches_completed"] or 0
            rate = f"{100 * r['matches_won'] / played:5.1f}%" if played else "    —"
            print(
                f"{r['deck'][:22]:<22} {r['event_id'] or '':<20} "
                f"{r['matches_won']}/{played} matches {rate}  "
                f"games {r['games_won']}-{r['games_lost']}"
            )
        if not rows:
            print("(no completed matches yet)")

    if args.metric in ("playdraw", "all"):
        print("\nWinrate on the play vs on the draw (per game)")
        print("-" * 62)
        rows = conn.execute(
            """
            SELECT COALESCE(d.name, substr(v.deck_id, 1, 8), '(no deck)') AS deck,
                   v.on_play, v.games_completed, v.games_won
              FROM v_play_draw_winrate v
              LEFT JOIN decks d ON d.deck_id = v.deck_id
             ORDER BY deck, v.on_play DESC
            """
        ).fetchall()
        for r in rows:
            played = r["games_completed"] or 0
            rate = f"{100 * r['games_won'] / played:5.1f}%" if played else "    —"
            label = "on the play" if r["on_play"] else "on the draw"
            print(f"{r['deck'][:22]:<22} {label:<12} {r['games_won']}/{played} games {rate}")
        if not rows:
            print("(no games with a determined play/draw yet)")

    if args.metric in ("gamelength", "all"):
        # Arena counts player-turns, not rounds: a 12-round game reports 24.
        print("\nGame length by deck (player-turns; both seats, so ~2 per round)")
        print("-" * 62)
        rows = conn.execute(
            """
            SELECT COALESCE(d.name, substr(v.deck_id, 1, 8), '(no deck)') AS deck,
                   v.turn_count, v.games, v.games_won
              FROM v_deck_game_length v
              LEFT JOIN decks d ON d.deck_id = v.deck_id
             ORDER BY deck, v.turn_count
            """
        ).fetchall()
        totals: dict[str, list[int]] = {}
        for r in rows:
            played = r["games"] or 0
            rate = f"{100 * r['games_won'] / played:5.1f}%" if played else "    —"
            print(
                f"{r['deck'][:22]:<22} turn {r['turn_count']:>3}   "
                f"{r['games_won']}/{played} games {rate}"
            )
            weighted = totals.setdefault(r["deck"], [0, 0])
            weighted[0] += r["turn_count"] * played
            weighted[1] += played
        for deck, (turn_games, played) in totals.items():
            if played:
                avg = turn_games / played
                print(f"{deck[:22]:<22} avg length {avg:.1f} turns ({played} games)")
        if not rows:
            print("(no completed games with a recorded length yet)")

    if args.metric in ("curves", "all"):
        print("\nTurn curves by deck (averages, by player-turn)")
        print("-" * 62)
        rows = conn.execute(
            """
            SELECT COALESCE(d.name, substr(v.deck_id, 1, 8), '(no deck)') AS deck,
                   v.turn_number, v.samples, v.avg_self_life, v.avg_opp_life,
                   v.avg_self_hand, v.avg_opp_hand, v.avg_self_lands,
                   v.avg_self_permanents, v.avg_opp_permanents
              FROM v_deck_turn_curves v
              LEFT JOIN decks d ON d.deck_id = v.deck_id
             ORDER BY deck, v.turn_number
            """
        ).fetchall()
        for r in rows:
            print(
                f"{r['deck'][:22]:<22} turn {r['turn_number']:>3}  n={r['samples']:<3} "
                f"life {_fmt(r['avg_self_life'])}/{_fmt(r['avg_opp_life'])}  "
                f"hand {_fmt(r['avg_self_hand'])}/{_fmt(r['avg_opp_hand'])}  "
                f"lands {_fmt(r['avg_self_lands'])}  "
                f"board {_fmt(r['avg_self_permanents'])}/{_fmt(r['avg_opp_permanents'])}"
            )
        if not rows:
            print("(no turn data recorded yet)")

    if args.metric in ("meta", "all"):
        from sensei_top.archetypes import opponent_source_breakdown
        from sensei_top.formats import FORMATS

        shown = False
        for fmt in FORMATS:
            counts = opponent_source_breakdown(conn, fmt)
            if not counts["total"]:
                continue
            shown = True
            print(f"\nOpponent classification (completed {fmt} matches)")
            print("-" * 62)
            for source in ("archetype", "fallback", "colors", "manual", "unknown"):
                pct = 100 * counts[source] / counts["total"]
                print(f"{source:<12} {counts[source]:>4} / {counts['total']} ({pct:5.1f}%)")
        if not shown:
            print("\nOpponent classification")
            print("-" * 62)
            print("(no completed matches with a known format yet)")
    print()


def _read_import(path: str, expected_for: str) -> Answer:
    """An ``--import FILE`` answer, read through the same contract the
    dashboard's paste box uses (``answers.read_answer``), except that an
    answer with no header — one saved before prompts asked for it — is read
    whole, with a warning. Exits with the reason when it cannot be read."""
    from sensei_top.answers import AnswerError, headerless_warning, read_answer

    raw = Path(path).read_text(encoding="utf-8")
    try:
        answer = read_answer(raw, expected_for, require_header=False)
    except AnswerError as exc:
        sys.exit(f"Could not read {path}: {exc}")
    if answer.headerless:
        warning = headerless_warning()
        # Not the file's path: a log line never carries a local path.
        logging.getLogger(__name__).warning("import: %s", warning)
        print(warning, file=sys.stderr)
    return answer


def cmd_guide(args) -> None:
    from sensei_top.guide.bundle import build_deck_guide
    from sensei_top.guide.deck import list_identities

    conn = _open(args)

    if not args.deck:
        identities = list_identities(conn)
        if not identities:
            print("No decks with recorded matches yet.")
            return
        print("Decks (pass one of these keys to --deck):")
        for identity in identities:
            print(
                f"  {identity.key:<48} {identity.name or '(unnamed)':<24} "
                f"{identity.matches} matches ({identity.match_wins}-{identity.match_losses})"
            )
        return

    guide = build_deck_guide(conn, args.deck)
    if guide is None:
        sys.exit(f"No deck found for key {args.deck!r}. Run `guide` with no --deck to list keys.")

    # --prompt prints the text to hand an assistant, and stops: the
    # no-credential path, answered with --import. See docs/guide.md, "CLI".
    if args.prompt:
        from sensei_top.guide.narrative import full_prompt

        text = full_prompt(guide, conn=conn)
        if text is None:
            sys.exit("Nothing to write about for this deck yet (no recorded matches).")
        print(text)
        return

    if args.import_file:
        from sensei_top.answers import guide_for
        from sensei_top.brief.from_guide import store_guide_matchups
        from sensei_top.brief.store import corpus_commit, list_hash
        from sensei_top.guide.authored import write_narrative
        from sensei_top.guide.narrative import (
            NarrativeError,
            full_prompt,
            guide_narrative_from_json,
        )

        identity = guide.provenance.deck
        answer = _read_import(args.import_file, guide_for(identity.key))
        try:
            narrative = guide_narrative_from_json(answer.body, guide)
        except NarrativeError as exc:
            sys.exit(f"Could not read {args.import_file}: {exc}")

        write_narrative(
            conn, identity.key, narrative,
            # The 75 the answer says it was written for, so one written for
            # an older list reads as stale.
            list_hash=(
                answer.context if answer.context is not None
                else list_hash(identity.current_cards)
            ),
            prompt=full_prompt(guide, conn=conn) or "",
            author=args.author,
            corpus_commit=corpus_commit(conn),
        )
        written = store_guide_matchups(
            conn, guide, narrative, model=args.author, list_hash=answer.context,
        )
        conn.commit()
        print(f"Imported the guide for {identity.name or identity.key}.")
        print(f"  {written} matchup brief(s) stored — these also drive the Live page.")
        if narrative.problems:
            print("  Sideboard plan problems (recorded, not repaired):")
            for problem in narrative.problems:
                print(f"    [{problem.archetype}] {problem.message}")
        return

    # Default: the evidence document, plus whatever narrative was imported.
    from sensei_top.guide.authored import narrative_for
    from sensei_top.guide.markdown import render

    stored = narrative_for(conn, guide.provenance.deck.key)
    narrative = stored[1] if stored is not None else None
    markdown = render(guide, narrative)

    if args.markdown:
        Path(args.markdown).write_text(markdown, encoding="utf-8")
        print(f"Guide written to {args.markdown}")
    else:
        print(markdown)


def cmd_rcq(args) -> None:
    from sensei_top.guide.rcq import NarrativeError, build_rcq, rcq_from_json, rcq_prompt
    from sensei_top.guide.rcq_authored import write_rcq

    conn = _open(args)
    text = Path(args.decklist).read_text(encoding="utf-8")
    expected = [k.strip() for k in (args.expect or "").split(",") if k.strip()]
    evidence = build_rcq(conn, args.deck, text, expected, args.own)
    if evidence is None:
        sys.exit(f"No deck found for key {args.deck!r}. Run `guide` with no --deck to list keys.")

    prompt = rcq_prompt(evidence, conn=conn)
    if args.prompt:
        print(prompt)
        return

    if args.import_file:
        from sensei_top.answers import rcq_for

        answer = _read_import(args.import_file, rcq_for(evidence.guide.provenance.deck.key))
        try:
            narrative = rcq_from_json(answer.body, evidence)
        except NarrativeError as exc:
            sys.exit(f"Could not read {args.import_file}: {exc}")
        for note in narrative.flex_notes:
            if note.role not in ("core", "flex", "risk"):
                sys.exit(
                    f"Could not read {args.import_file}: flex note role {note.role!r} "
                    "is not core, flex or risk"
                )
        newest = [f.newest_event for f in evidence.freshness if f.newest_event]
        write_rcq(
            conn, args.deck, narrative,
            model=args.author, decklist_text=text, expected=list(evidence.expected_keys),
            own_archetype_key=args.own, prompt=prompt,
            corpus_latest_event=max(newest) if newest else None,
        )
        conn.commit()
        print(f"Imported the RCQ guide for {args.deck}.")
        for problem in narrative.problems:
            print(f"  [{problem.archetype}] {problem.message}")
        return

    sys.exit("Pass --prompt to print the prompt, or --import FILE to store an answer.")


def cmd_brief(args) -> None:
    from sensei_top.brief.store import briefs_for_deck, corpus_commit
    from sensei_top.guide.deck import list_identities, resolve

    conn = _open(args)

    if not args.deck:
        current_commit = corpus_commit(conn)
        found_any = False
        for identity in list_identities(conn):
            for brief in briefs_for_deck(conn, identity.key):
                found_any = True
                stale = (
                    " (stale — corpus has moved)"
                    if brief.corpus_commit != current_commit else ""
                )
                print(
                    f"  {brief.deck_key:<40} {brief.archetype_key:<24} "
                    f"{brief.generated_at} [{brief.source}]{stale}"
                )
        if not found_any:
            print("No matchup briefs stored yet.")
            print("Write one with:  sensei-top guide --deck KEY --prompt   (then --import)")
        return

    if args.archetype and args.missing:
        sys.exit("--archetype and --missing are mutually exclusive.")

    if not args.archetype and not args.missing:
        sys.exit("--archetype is required with --deck (or pass --missing).")

    identity = resolve(conn, args.deck)
    if identity is None:
        sys.exit(f"No deck found for key {args.deck!r}. Run `guide` with no --deck to list keys.")

    from sensei_top.guide.deck import identity_format

    if identity_format(conn, identity) is None:
        sys.exit(
            "This deck's format is unknown, so there is no field to write a brief from. "
            "On MTGO, confirm the format on one of its matches, then run this again."
        )

    if args.missing:
        cmd_brief_missing(conn, identity, args)
        return

    if args.prompt:
        from sensei_top.brief.narrative import full_prompt

        built = full_prompt(conn, identity, args.archetype, args.archetype)
        if built is None:
            sys.exit(f"No field consensus for archetype {args.archetype!r} yet.")
        print(built[0])
        return

    if args.import_file:
        from sensei_top.answers import brief_for
        from sensei_top.brief.importer import import_brief
        from sensei_top.brief.narrative import NarrativeError

        answer = _read_import(args.import_file, brief_for(identity.key, args.archetype))
        try:
            brief = import_brief(
                conn, identity, args.archetype, args.archetype, answer.body,
                author=args.author, written_for=answer.context,
            )
        except NarrativeError as exc:
            sys.exit(f"Could not read {args.import_file}: {exc}")
        except LookupError as exc:
            sys.exit(str(exc))
        conn.commit()
        print(f"Brief stored for {identity.name or identity.key} vs {args.archetype}.")
        if brief.problems:
            print("Sideboard plan problems (recorded, not repaired):")
            for problem in brief.problems:
                print(f"  [{problem.archetype}] {problem.message}")
        return

    sys.exit("Pass --prompt to get the text to write from, or --import FILE to store an answer.")


def cmd_brief_missing(conn, identity, args) -> None:
    """The ``--missing`` half of ``brief``: every archetype
    ``brief/coverage.py`` marks ``missing``/``stale`` for this deck, in the
    same order its own ``Coverage.rows`` are already sorted (times faced
    desc, then field share desc, then key) — so the multi-prompt and the
    dashboard's own coverage table always name gaps in the same order.
    """
    from sensei_top.brief.coverage import build_coverage

    coverage = build_coverage(conn, identity)
    gap_rows = [row for row in coverage.rows if row.status in ("missing", "stale")]
    archetypes = [(row.archetype_key, row.label) for row in gap_rows]
    labels = {row.archetype_key: row.label for row in gap_rows}

    if args.prompt:
        from sensei_top.brief.narrative import full_multi_prompt

        if not archetypes:
            print("Nothing missing or stale — every coverage row already has a fresh brief.")
            return
        built = full_multi_prompt(conn, identity, archetypes)
        if built is None:
            sys.exit("No field consensus for any missing/stale archetype yet.")
        print(built.prompt)
        if built.no_consensus:
            print(
                f"No field consensus (skipped): {', '.join(built.no_consensus)}",
                file=sys.stderr,
            )
        if built.deferred:
            print(
                f"Deferred past this prompt's limit: {', '.join(built.deferred)}",
                file=sys.stderr,
            )
        return

    if args.import_file:
        from sensei_top.answers import coverage_for
        from sensei_top.brief.importer import import_briefs
        from sensei_top.brief.narrative import NarrativeError

        answer = _read_import(args.import_file, coverage_for(identity.key))
        try:
            stored, skipped = import_briefs(
                conn, identity, answer.body, author=args.author, labels=labels,
                written_for=answer.context,
            )
        except NarrativeError as exc:
            sys.exit(f"Could not read {args.import_file}: {exc}")
        conn.commit()
        print(f"{len(stored)} brief(s) stored for {identity.name or identity.key}.")
        for brief in stored:
            if brief.problems:
                print(
                    f"Sideboard plan problems for {brief.archetype_key} "
                    "(recorded, not repaired):"
                )
                for problem in brief.problems:
                    print(f"  [{problem.archetype}] {problem.message}")
        if skipped:
            print("Skipped (no field consensus):", file=sys.stderr)
            for key, message in skipped:
                print(f"  {key}: {message}", file=sys.stderr)
        return

    sys.exit("Pass --prompt to get the text to write from, or --import FILE to store an answer.")


def _start_archetype_refresh(db_path: Path) -> None:
    """Freshen the archetype definitions in the background, best-effort.

    On its own thread with its own connection, because SQLite connections
    belong to the thread that opened them and because startup must not wait on
    the network. Every failure is swallowed: an offline machine keeps the
    definitions it already has, and a machine that never had any simply shows
    colours instead of archetype names.

    New definitions rename the stored corpus's decks as well as the user's
    opponents, so an update reclassifies both. ``reclassify_corpus`` takes a
    lock the corpus refresh's thread shares, since that thread reclassifies
    after a store on a connection of its own.
    """

    def run() -> None:
        try:
            from sensei_top.archetypes import classify_matches, refresh_archetypes
            from sensei_top.metagame.auto import reclassify_corpus

            conn = connect(db_path)
            try:
                if refresh_archetypes(conn).status == "updated":
                    classify_matches(conn)
                    reclassify_corpus(conn)
            finally:
                conn.close()
        except Exception as exc:                      # never fatal: startup must not care
            logging.getLogger(__name__).warning("archetype refresh skipped: %s", exc)

    threading.Thread(target=run, name="archetype-refresh", daemon=True).start()


# How often `_start_reference_refresh`'s loop re-checks each of its steps.
# Cheap by construction (a `stat()` and, usually, one no-op SELECT), so 300s
# is about "notice an Arena patch within five minutes of serve starting",
# not a rate limit.
_REFERENCE_REFRESH_INTERVAL = 300.0


def _start_reference_refresh(db_path: Path) -> None:
    """Freshen locally-sourced reference data in the background, best-effort
    — but a repeating loop rather than the one-shot check
    ``_start_archetype_refresh`` above runs: that one fires once at startup
    and is done, while the installed Arena client can be patched at any point
    during a long ``serve --watch`` session, so this one keeps checking on its
    own thread for as long as the process runs.

    Written as a list of steps, each a no-argument callable run in order on
    every tick, so a later step can be appended without restructuring this
    loop. One step's exception is caught and logged at warning level on its
    own — never fatal, and never stops the others, this tick or the next.
    The first run happens on the thread too, so this never blocks ``serve``'s
    startup.
    """
    import time

    last_state: tuple[Path, float] | None = None

    def refresh_arena_cards_step() -> None:
        """Re-import the installed client's card database, but only when its
        own (path, mtime) has changed since the last check — a quiet
        machine between Arena patches does no work here at all.
        """
        nonlocal last_state
        from sensei_top.cards import arena_card_database_path, refresh_arena_cards

        path = arena_card_database_path()
        if path is None:
            return
        state = (path, path.stat().st_mtime)
        if state == last_state:
            return
        conn = connect(db_path)
        try:
            imported = refresh_arena_cards(conn)
        finally:
            conn.close()
        last_state = state
        if imported:
            logging.getLogger(__name__).info(
                "Arena card database re-imported: %d row(s) new", imported
            )

    steps = [refresh_arena_cards_step]

    def run() -> None:
        while True:
            for step in steps:
                try:
                    step()
                except Exception as exc:      # never fatal: one step's failure is not another's
                    logging.getLogger(__name__).warning(
                        "reference refresh step %s skipped: %s",
                        getattr(step, "__name__", step), exc,
                    )
            time.sleep(_REFERENCE_REFRESH_INTERVAL)

    threading.Thread(target=run, name="reference-refresh", daemon=True).start()


# How often the corpus refresh asks whether a source is due. Each source keeps
# its own cadence (docs/metagame.md, "Fetching the corpus"), and a tick with
# none due reads their stamps and sends nothing, so this only bounds how late
# a due source is noticed.
_CORPUS_REFRESH_INTERVAL = 300.0

# How long the corpus refresh's connection waits for the write lock: long
# enough to outlast the watcher's rebuild rather than lose the run to a busy
# error. See docs/opponent-deck.md, "Naming the opponent's deck".
_CORPUS_BUSY_TIMEOUT_MS = 60_000


def _corpus_refresh_tick(
    db_path: Path, state: RefreshState, *, now: Callable[[], datetime]
) -> None:
    """One tick of ``serve``'s corpus refresh: ``metagame.auto.refresh_corpus``
    on a connection of its own, then each source's result, printed or logged.

    A line is printed only when ``fetch_lines.render`` gives one on
    ``serve``, which is only when the server's own attempt moved a hold.
    Everything else is logged: a run that was attempted at warning level,
    ordinary successes and generic failures included, and a source that was
    not due, held or has no key at debug, since that is most ticks. A result
    ``render`` refuses is logged, and the other sources' lines still print.
    See docs/metagame.md, "Fetching the corpus".

    An exception from opening the connection or from ``refresh_corpus``
    itself (``followed_formats`` reads the database outside its per-source
    guard) is raised to the loop, which logs it.
    """
    from sensei_top.metagame import auto, fetch_lines
    from sensei_top.metagame.holds import MTGO, TOPDECK

    log = logging.getLogger(__name__)
    conn = connect(db_path)
    try:
        conn.execute(f"PRAGMA busy_timeout = {_CORPUS_BUSY_TIMEOUT_MS}")
        results = auto.refresh_corpus(conn, state, now=now)
    finally:
        conn.close()

    at = now()
    for name, result in results.items():
        lines: list[str] = []
        # fbettega's ``cache: …`` lines are ``meta``'s alone, and ``render``
        # refuses a source it has no lines for.
        if name in (MTGO, TOPDECK):
            try:
                lines = fetch_lines.render(name, result, surface=fetch_lines.SERVE, now=at)
            except ValueError as exc:
                log.warning("corpus refresh: no line for %s's %s run: %s",
                            name, result.status, exc)
        for line in lines:
            # Flushed: printed hours into a session, a line must not wait in
            # a buffer for the next one when stdout is a pipe or a file.
            print(line, flush=True)
        if not lines:
            _log_corpus_result(name, result)


def _log_corpus_result(name: str, result: RefreshResult) -> None:
    """A corpus result ``serve`` prints no line for: see
    ``_corpus_refresh_tick``."""
    attempted = result.status in ("updated", "failed")
    logging.getLogger(__name__).log(
        logging.WARNING if attempted else logging.DEBUG,
        "corpus refresh: %s %s, %d tournament events stored, %d skipped%s",
        name, result.status, result.events, result.skipped,
        f" ({result.error})" if result.error else "",
    )


def _start_corpus_refresh(
    db_path: Path,
    *,
    interval: float = _CORPUS_REFRESH_INTERVAL,
    stop: threading.Event | None = None,
) -> threading.Thread:
    """Keep the tournament corpus current while ``serve`` runs: one
    ``_corpus_refresh_tick`` every ``interval`` seconds, the first at once, on
    a daemon thread of its own, "corpus-refresh", modelled on
    ``_start_reference_refresh``.

    The loop's ``RefreshState`` lives as long as the thread: its hour after
    an incomplete run is forgotten on a restart, while a stored not-before
    is not. An exception is logged at warning level and never ends
    the loop; the next tick tries again. ``stop`` ends it, which only a test
    does: ``serve`` lets the thread die with the process, as its siblings do.
    Returns the started thread.
    """
    from sensei_top.metagame.auto import RefreshState

    halt = stop if stop is not None else threading.Event()

    def run() -> None:
        state = RefreshState()
        while True:
            try:
                _corpus_refresh_tick(db_path, state, now=_utc_now)
            except Exception as exc:      # never fatal: the next tick tries again
                logging.getLogger(__name__).warning(
                    "corpus refresh tick failed: %s: %s", type(exc).__name__, exc
                )
            if halt.wait(interval):
                return

    thread = threading.Thread(target=run, name="corpus-refresh", daemon=True)
    thread.start()
    return thread


def _start_backup(db_path: Path):
    """Starts the daily backup schedule -- structurally a sibling of
    ``_start_archetype_refresh`` above, but unlike it this returns a handle
    rather than firing a thread and forgetting it. That one is a one-shot
    check that either finishes or gets abandoned at process exit with
    nothing left mid-write; this one runs for as long as
    ``serve`` does and can be in the middle of a multi-minute ``VACUUM INTO``
    when a shutdown arrives, so ``cmd_serve`` needs a ``stop()`` to call in
    its own ``finally`` rather than trusting the daemon thread flag alone.
    """
    from sensei_top.backup import BackupScheduler

    scheduler = BackupScheduler(db_path=db_path)
    scheduler.start()
    return scheduler


def _require_loopback(host: str) -> None:
    """Refuse to bind anywhere but loopback, before anything else in
    ``cmd_serve`` runs (no watcher, no refresh thread, no backup scheduler,
    no ``open_database`` call). AGENTS.md non-negotiable #5: widening
    ``--host`` means building an authentication story first.

    Delegates the actual rule (``'localhost'`` accepted by name with no DNS
    resolution, everything else parsed as a literal IP address) to
    ``api.guard.is_loopback_host`` — the same function ``api/guard.py``'s
    ``LoopbackGuard`` checks every request's ``Host`` header against, so the
    bind-time gate here and the per-request gate there can never quietly
    disagree.
    """
    # Lazy: sensei_top.api pulls in FastAPI (its __init__ re-exports
    # create_app), and every subcommand imports this module, not just serve.
    from sensei_top.api.guard import is_loopback_host

    if is_loopback_host(host):
        return
    sys.exit(
        f"Refusing to bind {host}: serve binds loopback only (127.0.0.1, "
        "::1 or localhost) — this dashboard has no authentication, and "
        "exposing it would publish your match history "
        "(AGENTS.md non-negotiable #5)."
    )


def _bind_listening_socket(host: str, port: int) -> socket.socket:
    """Bind and listen on ``host:port`` (0 = any free port), or exit 1 saying why.

    ``socket.create_server`` sets SO_REUSEADDR on POSIX (a restart is not
    refused for TIME_WAIT) and nothing on Windows: there SO_REUSEADDR would
    let a second socket bind a port another holds, defeating the shell's
    "pick a new port only when it is taken", while SO_EXCLUSIVEADDRUSE can
    refuse a rebind while the old listener's connections linger, so a restart
    would look taken. Windows' default already refuses a held port."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        return socket.create_server((host, port), family=family, backlog=2048)
    except OSError as exc:
        message = (
            f"Cannot listen on {host}:{port}: {exc} "
            "— pass a free --port, or --port 0"
        )
        logging.getLogger(__name__).error(message)
        sys.exit(message)


def _announce_when_started(server, port: int) -> None:
    """``--ready-line``: one JSON line on stdout once uvicorn is accepting."""
    import json
    import time

    while not server.started:
        if server.should_exit:
            return
        time.sleep(0.05)
    print(json.dumps({"listening": port}), flush=True)


def _wait_for_pipe_eof(fd: int) -> bool:
    """Windows: poll stdin's pipe until its writer closes it. ``False`` means
    stdin is not a pipe (a console, NUL or a file), so the caller must fall
    back to a blocking read."""
    import _winapi
    import msvcrt
    import time

    handle = msvcrt.get_osfhandle(fd)
    first = True
    while True:
        try:
            available, _left = _winapi.PeekNamedPipe(handle, 0)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 109:  # ERROR_BROKEN_PIPE: EOF
                return True
            if first:
                return False
            raise
        first = False
        if available:
            os.read(fd, available)  # exactly what is there, so it cannot block
        else:
            time.sleep(0.25)


def _exit_when_stdin_closes(server) -> None:
    """``--exit-on-stdin-close``: a parent that holds our stdin open and dies
    closes it; EOF runs the same orderly shutdown Ctrl+C does."""
    # os.read, not sys.stdin.buffer.read: the latter holds the BufferedReader's
    # lock while it blocks, and a SIGINT then aborts the interpreter.
    try:
        # No stdin at all (fd 0 closed at launch) is end of file too.
        if sys.stdin is not None:
            fd = sys.stdin.fileno()
            # Windows polls: a read pending on the pipe serializes I/O on the
            # handle, and the watcher child, which shares it, stalls at startup.
            if sys.platform == "win32" and _wait_for_pipe_eof(fd):
                pass
            else:
                while os.read(fd, 4096):
                    pass
    except (OSError, ValueError):  # a closed or unreadable stdin is EOF too
        pass
    server.should_exit = True


def cmd_serve(args) -> None:
    _require_loopback(args.host)

    import uvicorn

    from sensei_top.api import create_app

    db_path = Path(args.db)
    watcher = None
    backup_scheduler = None

    if args.watch:
        # The watcher writes, so it may create the database; a read-only serve
        # must not, since an empty file is indistinguishable from "no games yet".
        _open(args).close()
        # With no --file and no log anywhere, the watcher waits for one
        # (an explicit --file that is missing still exits, in _resolve_log).
        path = _resolve_serve_log(args.file)
        _resolve_locale(args)
        watcher = _build_watcher_process(args, path)
        watcher.start()
        if path is None:
            print(
                "No Arena log yet: waiting for it, looking again every "
                f"{ARENA_LOG_RESOLVE_SECONDS:g}s"
            )
        else:
            print(f"Watching {path} every {args.interval}s")
        print(
            f"Projecting at least every {args.project_every}s "
            f"(adaptive up to duty_factor={args.duty_factor}x the last rebuild's duration)"
        )
        if watcher.mtgo_dir is not None:
            print(
                f"MTGO logs at {watcher.mtgo_dir}: checked every {MTGO_POLL_SECONDS:g}s, "
                "each game stored when it ends"
            )
            if mtgo_load_handle() is None:
                print(
                    "  No [mtgo] handle configured — these files will be stored but skipped "
                    "at projection ('sensei-top config --set-mtgo-handle YOURHANDLE' to fix)."
                )
            if not args.mtgo_dir:  # an explicit --mtgo-dir is the user's own choice: no hint
                hint = mtgo_suggestion(
                    watcher.mtgo_dir, discover_log_folder(), resolve_log_dir()[1]
                )
                if hint:
                    print(hint)
        elif args.no_mtgo:
            print("Not reading MTGO logs (--no-mtgo)")
        elif resolve_log_dir() is None:
            print(
                "Not reading MTGO logs (no directory configured — pass --mtgo-dir, set "
                "MTGO_LOG_DIR, or run 'sensei-top config --set-mtgo-dir DIR')"
            )
            if not args.mtgo_dir:
                hint = mtgo_suggestion(None, discover_log_folder())
                if hint:
                    print(hint)
        else:
            print(
                "Not reading MTGO logs (the configured directory doesn't exist — see the "
                "warning above)"
            )
            configured, source = resolve_log_dir()
            hint = mtgo_suggestion(configured, discover_log_folder(), source)
            if hint and not args.mtgo_dir:
                print(hint)
        if watcher.mtgo_deck_dir is not None:
            print(
                f"MTGO deck files at {watcher.mtgo_deck_dir} polled every {DECK_POLL_SECONDS:g}s"
            )
        if watcher.mtgo_dir is not None:
            print(
                f"MTGO deck store (grouping *.xml) at {watcher.mtgo_dir} polled every "
                f"{DECK_POLL_SECONDS:g}s"
            )
    elif not db_path.exists():
        sys.exit(f"No database at {db_path}. Run 'sensei-top ingest' then 'project' first.")
    else:
        open_database(db_path).close()
    # Migrations are applied above, once, before anything else starts: every
    # thread and process serve runs from here on opens with connect(), so a
    # migration file that appears in the working tree mid-session waits for
    # the next restart (db.open_database's docstring).

    if not args.no_archetype_refresh:
        _start_archetype_refresh(db_path)
    if not args.no_reference_refresh:
        _start_reference_refresh(db_path)
    # With or without --watch. Its own lines print only when a hold
    # moves (_corpus_refresh_tick), so a running refresh says nothing here.
    if args.no_corpus_refresh:
        print("Not downloading tournament results (--no-corpus-refresh)")
    else:
        _start_corpus_refresh(db_path)

    if args.no_backup:
        print("Not backing up (--no-backup)")
    else:
        from sensei_top.backup import last_backup_age_seconds
        from sensei_top.backup import resolve as resolve_backup_config

        backup_cfg = resolve_backup_config(db_path)
        backup_conn = connect(db_path)
        try:
            age = last_backup_age_seconds(backup_conn)
        finally:
            backup_conn.close()
        age_text = f"last backup {_fmt_age(age)} ago" if age is not None else "no backup taken yet"
        print(
            f"Backing up to {backup_cfg.directory} every 24h "
            f"(keep {backup_cfg.keep}); {age_text}"
        )
        backup_scheduler = _start_backup(db_path)

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(db_path, watcher=watcher),
            host=args.host,
            port=args.port,
            log_level="warning",
            # No handlers of uvicorn's own: its loggers propagate to the root,
            # whose handlers (logs.install) put its lines in the log file.
            log_config=None,
        )
    )
    try:
        # Bound here, not by uvicorn, so `--port 0` yields a port we can
        # report (docs/desktop.md, "The desktop shell"). The ready line
        # waits for `server.started`, which is the guarantee that uvicorn
        # accepts connections.
        sock = _bind_listening_socket(args.host, args.port)
        port = sock.getsockname()[1]
        print(f"Serving {db_path} on http://{args.host}:{port}  (Ctrl-C to stop)")
        print(f"  API docs: http://{args.host}:{port}/docs")
        if args.ready_line:
            threading.Thread(
                target=_announce_when_started, args=(server, port), name="ready-line",
                daemon=True,
            ).start()
        if args.exit_on_stdin_close:
            threading.Thread(
                target=_exit_when_stdin_closes, args=(server,), name="stdin-lifeline",
                daemon=True,
            ).start()
        # uvicorn re-raises the Ctrl+C it turned into a shutdown;
        # uvicorn.run swallowed it, so a clean exit stays status 0.
        with contextlib.suppress(KeyboardInterrupt):
            server.run(sockets=[sock])
    finally:
        # Runs after Ctrl+C (swallowed above, as uvicorn.run did), never after
        # a SIGTERM, whose re-raise ends the process first. The app's shutdown
        # stops the watcher on both (api/app.py), so this stop() is a no-op
        # after it, and the backstop for a second Ctrl+C, which can make
        # uvicorn skip that shutdown.
        if watcher is not None:
            watcher.stop()
        if backup_scheduler is not None:
            backup_scheduler.stop()


class _GivenLocale(argparse.Action):
    """Stores ``--locale`` and notes that it was given, so ``[arena]
    date_order`` applies only when it was not."""

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        namespace.locale_given = True


def _add_watch_arguments(sub_parser: argparse.ArgumentParser) -> None:
    """Options shared by the two ways to watch: ``ingest --watch`` and
    ``serve --watch``."""
    sub_parser.add_argument("--file", help="path to Player.log (default: autodetect / $MTGA_LOG)")
    sub_parser.add_argument("--interval", type=float, default=1.0, help="poll seconds (default 1)")
    sub_parser.add_argument(
        "--project-every", type=float, default=5.0,
        help="seconds between rebuilds while watching (default 5)",
    )
    sub_parser.add_argument(
        "--duty-factor", type=float, default=1.0,
        help=(
            "rebuild gate multiplier: the watcher waits at least "
            "duty_factor * (last rebuild's duration) between rebuilds, "
            "never less than --project-every (default 1, ~50%% duty cycle)"
        ),
    )
    # Only the CLI defaults to auto: ingest_file and the watcher keep None and
    # pass whatever they are given through unchanged. The parsed default
    # stays auto; _resolve_locale puts [arena] date_order in its place when
    # the flag was not given, which _GivenLocale records.
    sub_parser.add_argument(
        "--locale", choices=(AUTO, *DATE_ORDERS), default=AUTO, action=_GivenLocale,
        help=(
            "day/month order in log headers: auto settles each header from its "
            "fields, the file's last write and what this database has learned; "
            "mdy or dmy reads every header that way (default: [arena] date_order "
            "in config.toml, else auto)"
        ),
    )
    sub_parser.add_argument(
        "--no-mtgo", action="store_true",
        help=(
            "skip MTGO (logs and decks) even when a directory is configured (default: read MTGO "
            "when one is configured, via --mtgo-dir, $MTGO_LOG_DIR, or "
            "[mtgo] dir in config.toml)"
        ),
    )
    sub_parser.add_argument(
        "--mtgo-dir", default=None,
        help=(
            "directory of Match_GameLog_*.dat files; its grouping *.xml deck store "
            "is polled too (default: $MTGO_LOG_DIR, else [mtgo] dir in config.toml)"
        ),
    )
    sub_parser.add_argument(
        "--mtgo-deck-dir", default=None,
        help=(
            f"directory of exported MTGO *.dek deck files, polled every {DECK_POLL_SECONDS:g} s "
            "(default: $MTGO_DECK_DIR, else [mtgo] deck_dir in config.toml)"
        ),
    )


def _positive_int(raw: str) -> int:
    """argparse ``type=`` for ``--keep``, on both ``backup`` and ``config
    --set-backup-keep``: rejects zero, negative, and non-numeric values
    before ``backup.config`` ever sees them. An explicit flag naming an
    invalid value is a user error to reject outright, not something to fall
    back on — unlike the same field read from ``config.toml``, which
    ``backup.config.resolve`` clamps to ``DEFAULT_KEEP`` with a warning
    instead (see that module's docstring for why the two cases are handled
    in different places on purpose)."""
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def _positive_int_or_empty(raw: str) -> int | str:
    """``_positive_int``, except that an empty value passes through: it
    clears ``config --set-backup-keep``."""
    return "" if raw == "" else _positive_int(raw)


def _version_text() -> str:
    """The installed version, which a frozen build reads from the
    ``sensei_top-*.dist-info`` the spec copies in."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("sensei-top")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sensei-top", description=__doc__)
    parser.add_argument(
        "--db", default=str(DEFAULT_DB), help="SQLite file (default: data/sensei-top.db)"
    )
    parser.add_argument("--verbose", action="store_true", help="show projection warnings")
    parser.add_argument("--version", action="version", version=_version_text())
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="read a log into raw_events")
    p_ingest.add_argument("--watch", action="store_true", help="poll the file continuously")
    p_ingest.add_argument(
        "--project", action="store_true",
        help="with --watch: rebuild derived tables as new events arrive",
    )
    p_ingest.add_argument("--from-start", action="store_true", help="ignore saved offset")
    _add_watch_arguments(p_ingest)
    p_ingest.set_defaults(func=cmd_ingest)

    p_mtgo = sub.add_parser(
        "ingest-mtgo", help="read MTGO game logs and deck files into raw_events"
    )
    p_mtgo.add_argument(
        "--dir",
        help=(
            "directory of Match_GameLog_*.dat files; its grouping *.xml deck store "
            "is read too (default: $MTGO_LOG_DIR, else [mtgo] dir in config.toml)"
        ),
    )
    p_mtgo.add_argument(
        "--deck-dir",
        help=(
            "directory of exported *.dek deck files, read as well when set "
            "(default: $MTGO_DECK_DIR, else [mtgo] deck_dir in config.toml); "
            "with no game-log directory configured, only the decks are read"
        ),
    )
    p_mtgo.add_argument("--from-start", action="store_true", help="re-read every file in full")
    p_mtgo.set_defaults(func=cmd_ingest_mtgo)

    p_mtgo_status = sub.add_parser(
        "mtgo-status",
        help=(
            "diagnose the MTGO pipeline: handle, log directory and where it was "
            "configured, freshest file, row counts"
        ),
    )
    p_mtgo_status.add_argument(
        "--dir",
        help=(
            "directory of Match_GameLog_*.dat files "
            "(default: $MTGO_LOG_DIR, else [mtgo] dir in config.toml)"
        ),
    )
    p_mtgo_status.set_defaults(func=cmd_mtgo_status)

    p_project = sub.add_parser("project", help="rebuild matches/games/turns from raw_events")
    p_project.set_defaults(func=cmd_project)

    p_report = sub.add_parser("report", help="print MVP metrics")
    p_report.add_argument(
        "metric", nargs="?", default="all",
        choices=("all", "winrate", "playdraw", "gamelength", "curves", "meta"),
    )
    p_report.set_defaults(func=cmd_report)

    p_guide = sub.add_parser(
        "guide", help="deck guide: your play, the list vs. consensus, the field, matchups"
    )
    p_guide.add_argument(
        "--deck", default=None,
        help="a deck key from this command's own no-argument listing (omit to list decks)",
    )
    p_guide.add_argument(
        "--markdown", default=None, help="write the guide to this file instead of stdout"
    )
    p_guide.add_argument(
        "--prompt", action="store_true",
        help="print the text to write the narrative from, and stop (makes no network call)",
    )
    p_guide.add_argument(
        "--import", dest="import_file", default=None, metavar="FILE",
        help="store a written narrative (JSON); also fills every matchup brief it covers",
    )
    p_guide.add_argument(
        "--author", default="hand-written",
        help="recorded beside an imported narrative (default: hand-written)",
    )
    p_guide.set_defaults(func=cmd_guide)

    p_rcq = sub.add_parser(
        "rcq", help="RCQ guide: the prompt for the exact 75 you register (makes no call)"
    )
    p_rcq.add_argument("--deck", required=True, help="a deck key from `guide`'s listing")
    p_rcq.add_argument("--decklist", required=True, metavar="FILE", help="the 75, as pasted")
    p_rcq.add_argument(
        "--expect", default=None, metavar="K1,K2",
        help="comma-separated archetype keys you expect at the store",
    )
    p_rcq.add_argument("--own", default=None, help="your own archetype key, if you must pick it")
    p_rcq.add_argument("--prompt", action="store_true", help="print the prompt, and stop")
    p_rcq.add_argument(
        "--import", dest="import_file", default=None, metavar="FILE",
        help="store a written answer (JSON)",
    )
    p_rcq.add_argument(
        "--author", default="hand-written",
        help="recorded beside an imported guide (default: hand-written)",
    )
    p_rcq.set_defaults(func=cmd_rcq)

    p_brief = sub.add_parser(
        "brief", help="matchup briefs: what to play around, stored per (deck, archetype)"
    )
    p_brief.add_argument(
        "--deck", default=None,
        help="a deck key (omit, with no other flags, to list cached briefs)",
    )
    p_brief.add_argument(
        "--archetype", default=None, help="an archetype key from the metagame corpus"
    )
    p_brief.add_argument(
        "--missing", action="store_true",
        help=(
            "every missing/stale archetype this deck's coverage report names, instead of one "
            "--archetype (brief/coverage.py); errors if combined with --archetype"
        ),
    )
    p_brief.add_argument(
        "--prompt", action="store_true",
        help="print the text to write this brief from, and stop (makes no network call)",
    )
    p_brief.add_argument(
        "--import", dest="import_file", default=None, metavar="FILE",
        help="store a written brief (JSON)",
    )
    p_brief.add_argument(
        "--author", default="hand-written",
        help="recorded beside an imported brief (default: hand-written)",
    )
    p_brief.set_defaults(func=cmd_brief)

    p_serve = sub.add_parser("serve", help="run the local dashboard + JSON API")
    # Loopback by default and on purpose (AGENTS.md non-negotiable #5).
    # --host still exists for picking a *different* loopback address (a
    # container's own lo, an IPv6 ::1 setup) — never for binding somewhere
    # reachable from outside this machine. cmd_serve's own _require_loopback
    # enforces that no other value gets past argument parsing.
    p_serve.add_argument(
        "--host", default="127.0.0.1",
        help="loopback bind address only (default 127.0.0.1) — rejected otherwise",
    )
    p_serve.add_argument(
        "--port", type=int, default=8000,
        help="port (default 8000); 0 lets the OS choose a free one",
    )
    p_serve.add_argument(
        "--ready-line", action="store_true",
        help='once the server accepts connections, print one line {"listening": PORT} to stdout',
    )
    p_serve.add_argument(
        "--exit-on-stdin-close", action="store_true",
        help="shut down in order when stdin reaches end of file (for a parent that holds the "
        "pipe open and may die)",
    )
    p_serve.add_argument(
        "--watch", action="store_true",
        help="live mode: follow the log and rebuild while the dashboard runs",
    )
    p_serve.add_argument(
        "--no-archetype-refresh", action="store_true",
        help="skip the background check for updated deck definitions",
    )
    p_serve.add_argument(
        "--no-reference-refresh", action="store_true",
        help="skip the background check for a new installed-client card database",
    )
    p_serve.add_argument(
        "--no-backup", action="store_true",
        help="skip the automatic daily database backup",
    )
    p_serve.add_argument(
        "--no-corpus-refresh", action="store_true",
        help="skip the background download of tournament results",
    )
    _add_watch_arguments(p_serve)
    p_serve.set_defaults(func=cmd_serve)

    # Read from the installed client by default; --scryfall downloads card
    # names plus the rules text and legality the installed client never
    # carries, which the deck guide needs at least once. See
    # docs/user/getting-started.md, "Card names".
    p_cards = sub.add_parser("cards", help="load card names (from the installed Arena client)")
    p_cards.add_argument(
        "--scryfall", action="store_true",
        help="download from Scryfall instead of reading the local Arena install",
    )
    p_cards.add_argument(
        "--progress", action="store_true",
        help="report the download and save as JSON lines (the desktop shell reads them)",
    )
    p_cards.set_defaults(func=cmd_cards)

    # The opponent's deck is never in the log, so naming it needs a list of
    # what decks exist. `serve` refreshes this in the background; this command
    # is how to force it or see what happened.
    p_arch = sub.add_parser("archetypes", help="download deck archetype definitions")
    p_arch.add_argument("--force", action="store_true", help="refresh even if the cache is fresh")
    p_arch.add_argument("--url", default=ARCHIVE_URL, help=argparse.SUPPRESS)
    p_arch.set_defaults(func=cmd_archetypes)

    # The field's own numbers: real MTGO/paper tournament results, downloaded
    # from fbettega/MTG_decklistcache and windowed by date (the corpus is far
    # bigger than the archetype definitions, so a full fetch is never right).
    p_meta = sub.add_parser("meta", help="download tournament results and classify them")
    p_meta.add_argument(
        "--window-days", type=int, default=90,
        help="how far back to fetch tournament events (default 90)",
    )
    p_meta.add_argument("--force", action="store_true", help="refresh even if the cache is fresh")
    p_meta.add_argument(
        "--reclassify", action="store_true",
        help="re-run the classifier over the stored corpus, no network access",
    )
    p_meta.add_argument(
        "--source", choices=["cache", "topdeck", "mtgo", "all"], default="all",
        help="'cache' is fbettega/MTG_decklistcache (MTGO+Melee); 'mtgo' is "
        "mtgo.com's own decklist pages; 'topdeck' is "
        "TopDeck.gg RCQs, skipped silently with no key configured (default: all)",
    )
    p_meta.add_argument(
        "--format", dest="formats", action="append", default=None, metavar="FORMAT",
        type=_format_arg,
        help="also fetch this format (repeatable, e.g. --format Pauper); Standard, Modern and every format already in the corpus are always fetched. Implies --force",  # noqa: E501
    )
    p_meta.set_defaults(func=cmd_meta)

    # One VACUUM INTO snapshot a day, never more than once without --force;
    # docs/architecture.md's Backups section has the destination/rotation/
    # verification design this command and `serve`'s background schedule
    # (--no-backup below) both share.
    p_backup = sub.add_parser(
        "backup", help="verified daily snapshot of the whole database (VACUUM INTO)"
    )
    p_backup.add_argument(
        "--force", action="store_true", help="back up even if the last one is under 24h old"
    )
    p_backup.add_argument(
        "--dir", default=None,
        help=(
            "destination directory "
            "(default: $SENSEI_TOP_BACKUP_DIR / [backup] dir / 'backups' beside the db)"
        ),
    )
    p_backup.add_argument(
        "--keep", type=_positive_int, default=None, metavar="N",
        help="how many backup slots to retain (default: [backup] keep, or 1)",
    )
    p_backup.add_argument(
        "--deep-verify", action="store_true",
        help="also run PRAGMA quick_check on the copy (~68s on a 1.7 GB database)",
    )
    p_backup.set_defaults(func=cmd_backup)

    p_restore = sub.add_parser(
        "restore",
        help="replace the database with a backup (stop serve first)",
        description=(
            "Stop serve before running this: the watcher holds the database open. "
            "The database it replaces is kept beside it as .replaced. "
            "A backup made by a newer version of Sensei Top is refused."
        ),
    )
    p_restore.add_argument(
        "file", metavar="FILE",
        help="the backup to restore, e.g. one 'sensei-top backup' wrote",
    )
    p_restore.set_defaults(func=cmd_restore)

    # Opt-in only (AGENTS.md non-negotiable #5): config itself never calls
    # out, and a Claude credential set here only turns the generate buttons
    # on. Of --db it uses only the backup lines (the default backup folder
    # sits beside it, and the last backup's state is read from it, read-only)
    # and, as every command does, the log folder beside it. The TopDeck.gg
    # key lives in the same file but is a separate, free/rate-limited
    # credential, governed by the free-download standard instead — see
    # docs/llm.md, "The standard for the free downloads".
    p_config = sub.add_parser(
        "config",
        help="set or show keys, the Arena log, MTGO and backups (no flags: show them)",
        description='An empty value ("") clears a setting.',
    )
    p_config.add_argument(
        "--show", action="store_true", help="print the summary that no flag at all prints"
    )
    p_config.add_argument(
        "--json", action="store_true",
        help="print every setting as one JSON object, with no key in it",
    )
    claude_key = p_config.add_mutually_exclusive_group()
    claude_key.add_argument(
        "--set-key", default=None, metavar="KEY",
        help="Anthropic API key; '-' reads it from stdin, off the command line. "
        "Kept in the system keyring when there is one, else in the config file",
    )
    claude_key.add_argument(
        "--clear-key", action="store_true",
        help="remove the Anthropic API key from the keyring and the config file",
    )
    p_config.add_argument(
        "--set-model", default=None, metavar="ID", help="e.g. claude-opus-5-5"
    )
    p_config.add_argument(
        "--set-effort", default=None, metavar="LEVEL",
        help="low | medium | high | xhigh | max",
    )
    topdeck_key = p_config.add_mutually_exclusive_group()
    topdeck_key.add_argument(
        "--set-topdeck-key", default=None, metavar="KEY",
        help="TopDeck.gg API key — enables 'meta --source topdeck'; '-' reads it from stdin",
    )
    topdeck_key.add_argument(
        "--clear-topdeck-key", action="store_true",
        help="remove the TopDeck.gg API key from the keyring and the config file",
    )
    p_config.add_argument(
        "--move-keys-to-keyring", action="store_true",
        help="move the keys the config file holds into the system keyring",
    )
    p_config.add_argument(
        "--set-arena-log", default=None, metavar="PATH",
        help="Arena's Player.log, used when neither --file nor $MTGA_LOG names one",
    )
    p_config.add_argument(
        "--set-date-order", default=None, metavar="ORDER",
        choices=(*DATE_ORDER_CHOICES, ""),
        help="day/month order in Arena's log headers when --locale is not given: "
        "auto | mdy | dmy (default auto)",
    )
    p_config.add_argument(
        "--set-mtgo-handle", default=None, metavar="HANDLE",
        help="your own MTGO account name — enables MTGO match projection",
    )
    p_config.add_argument(
        "--set-mtgo-dir", default=None, metavar="DIR",
        help="directory of Match_GameLog_*.dat files — enables MTGO ingestion",
    )
    p_config.add_argument(
        "--set-mtgo-deck-dir", default=None, metavar="DIR",
        help="directory of your MTGO .dek deck exports — read with the game logs",
    )
    p_config.add_argument(
        "--set-backup-dir", default=None, metavar="DIR",
        help="destination for daily database backups (default: a 'backups' folder beside the db)",
    )
    p_config.add_argument(
        "--set-backup-keep", type=_positive_int_or_empty, default=None, metavar="N",
        help="how many backup slots to retain (default: 1)",
    )
    # Coach-only overrides: written to a separate [claude.coach] table,
    # never touching the [claude] defaults the other four POST .../narrative
    # routes use via load().
    p_config.add_argument(
        "--set-coach-model", default=None, metavar="ID",
        help="the coach report's default model, which the Coach tab's model picker "
        "preselects, e.g. claude-fable-5-1",
    )
    p_config.add_argument(
        "--set-coach-effort", default=None, metavar="LEVEL",
        choices=["low", "medium", "high", "xhigh", "max", ""],
        help="effort override for the coach report only: low | medium | high | xhigh | max",
    )
    p_config.add_argument(
        "--coach-web-search", default=None, choices=["on", "off"],
        help="enable or disable the coach's web search tool (default: on)",
    )
    p_config.set_defaults(func=cmd_config)

    p_doctor = sub.add_parser(
        "doctor",
        help="report what the app can find: Arena's log, MTGO, cards, the database (read-only)",
        description="Never changes the database, migrates or downloads. "
        "Safe to run while serve is running.",
    )
    p_doctor.add_argument(
        "--json", action="store_true",
        help="print the report as one JSON object, with no key in it",
    )
    p_doctor.add_argument(
        "--file", default=None, metavar="PATH",
        help="the Player.log to check instead of the one serve would find",
    )
    p_doctor.set_defaults(func=cmd_doctor)

    p_diagnostics = sub.add_parser(
        "diagnostics",
        help="zip the logs and a secret-free report for a bug report",
        description="Never includes the database or any API key. "
        "Player.log only with --with-player-log.",
    )
    p_diagnostics.add_argument(
        "--out", default=None, metavar="FILE",
        help="the zip to write (required unless --list)",
    )
    p_diagnostics.add_argument(
        "--shell-log", default=None, metavar="PATH", help="also include the desktop app's log"
    )
    p_diagnostics.add_argument(
        "--with-player-log", action="store_true",
        help="also include Arena's Player.log (it names your opponents and your decks)",
    )
    p_diagnostics.add_argument(
        "--list", action="store_true",
        help="print what would go in, one entry per line with its size, and write nothing",
    )
    p_diagnostics.set_defaults(func=cmd_diagnostics)
    return parser


def cmd_doctor(args) -> None:
    """What the app can find, read-only (``doctor.py``). Safe beside ``serve``."""
    import json

    from sensei_top import doctor

    data = doctor.report(Path(args.db), args.file)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for line in doctor.lines(data):
        print(line)


def cmd_diagnostics(args) -> None:
    """The support zip (``diagnostics.py``); ``--list`` writes nothing."""
    from sensei_top import diagnostics

    if not args.list and not args.out:
        sys.exit("Pass --out FILE.zip, or --list to see what it would contain.")
    out = Path(args.out) if args.out else None
    if out is not None and not args.list and out.exists():
        sys.exit(f"{out} already exists; choose another name.")
    if out is not None and not args.list and not out.absolute().parent.is_dir():
        sys.exit(
            f"{out.absolute().parent} does not exist. "
            "Create it, or pass an --out inside a folder that does."
        )
    items = diagnostics.entries(
        Path(args.db),
        shell_log=Path(args.shell_log) if args.shell_log else None,
        with_player_log=args.with_player_log,
    )
    if args.list:
        for item in items:
            print(f"{item.name}\t{item.size}")
        return
    assert out is not None
    diagnostics.write_zip(out, items)
    print(f"Wrote {out} ({len(items)} entries).")


def main(argv: list[str] | None = None) -> None:
    # First, before anything else runs: in a frozen build (PyInstaller) a
    # multiprocessing child is this same executable, and this call is what
    # makes it run its target instead of the CLI. A no-op everywhere else.
    multiprocessing.freeze_support()
    # Redirected pipes and files fall back to the ANSI code page on Windows
    # (the console itself has been UTF-8 since PEP 528), and reports carry
    # card names outside it. reconfigure() resets errors to "strict" unless
    # it is passed, and stderr's "backslashreplace" is what still prints a
    # message naming a path with an undecodable byte.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors=stream.errors)
    args = build_parser().parse_args(argv)
    logs.install(Path(args.db), args.command, verbose=args.verbose)
    args.func(args)


if __name__ == "__main__":
    main()
