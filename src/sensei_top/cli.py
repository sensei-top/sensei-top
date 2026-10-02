"""Command line interface: ``sensei-top <command>``.

    sensei-top ingest --file <path> [--from-start]   replay a log
    sensei-top ingest --watch [--file <path>]        follow a live log
    sensei-top ingest-mtgo [--dir <path>] [--deck-dir <path>] [--from-start]
                                                      read MTGO game logs and deck files
    sensei-top mtgo-status [--dir <path>]            diagnose the MTGO pipeline
    sensei-top project                                raw_events -> matches/games/turns
    sensei-top report [winrate|playdraw|gamelength|curves]
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
    sensei-top config --set-key KEY                  opt in to Claude-generated narratives
    sensei-top config --set-mtgo-handle HANDLE       which MTGO player is you
    sensei-top config --set-mtgo-dir DIR             where MTGO writes its game logs
    sensei-top config                                show the resolved credential (masked)
    sensei-top backup [--force] [--dir PATH] [--keep N] [--deep-verify]
                                                      daily VACUUM INTO snapshot of the database
    sensei-top serve --no-backup                     serve without the automatic daily backup

A Claude API call is opt-in (AGENTS.md non-negotiable #5): with no credential
configured, `--prompt` prints text to paste into an assistant you already pay
for and `--import` reads the answer back, exactly as before `config` existed.
`config --set-key` (or an `ANTHROPIC_API_KEY` env var) turns the dashboard's
"write it with Claude" buttons on instead.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sensei_top.archetypes.source import ARCHIVE_URL
from sensei_top.db import connect, open_database
from sensei_top.live import DECK_POLL_SECONDS
from sensei_top.mtgo.config import load_handle as mtgo_load_handle
from sensei_top.mtgo.config import resolve_deck_dir, resolve_log_dir
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import (
    default_log_path,
    ingest_file,
    ingest_with_recovery,
    watch,
)
from sensei_top.reader.mtgo import _mtime_iso, ingest_mtgo_dir
from sensei_top.reader.mtgo_decks import ingest_deck_dir

DEFAULT_DB = Path("data/sensei-top.db")


def _resolve_log(argument: str | None) -> Path:
    path = Path(argument) if argument else default_log_path()
    if path is None:
        sys.exit("No log file found. Pass --file or set MTGA_LOG.")
    if not path.exists():
        sys.exit(f"Log file not found: {path}")
    return path


def _resolve_mtgo_dir(argument: str | None) -> Path:
    if argument:
        directory = Path(argument)
        source = None
    else:
        resolved = resolve_log_dir()
        if resolved is None:
            sys.exit(
                "No MTGO log directory configured. Pass --dir, set MTGO_LOG_DIR, or run "
                "'sensei-top config --set-mtgo-dir DIR'."
            )
        directory, source = resolved
    if not directory.exists():
        suffix = f" (from {source})" if source else ""
        sys.exit(f"Directory not found: {directory}{suffix}")
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
    two commands read the game logs only once, at their own startup (the deck
    folder they poll), though — this command is how a match played later in
    a session actually gets in. No ``--locale`` either: MTGO's log carries no
    header timestamps to parse.
    """
    conn = _open(args)
    deck_dir = _resolve_mtgo_deck_dir(args.deck_dir)
    # With a deck folder and no game-log directory anywhere, read the decks
    # alone; with neither, keep the existing "nothing configured" exit.
    read_logs = bool(args.dir) or resolve_log_dir() is not None or deck_dir is None
    if read_logs:
        directory = _resolve_mtgo_dir(args.dir)
        stats = ingest_mtgo_dir(conn, directory, from_start=args.from_start)
        total_bytes = conn.execute(
            "SELECT SUM(LENGTH(payload)) FROM raw_events WHERE source = 'mtgo'"
        ).fetchone()[0] or 0
        print(f"{directory}: {stats}")
        print(
            f"  {total_bytes:,} bytes of base64 payload stored for source='mtgo' "
            "(docs/architecture.md's storage note explains why this grows faster than the raw logs)"
        )
        # MTGO keeps its deck store, ``grouping *.xml``, beside the game logs
        # (plan 12, D14): read it from the same directory. A deck folder that
        # is this directory is read once, below only if it is a different one.
        grouping_stats = ingest_deck_dir(conn, directory, from_start=args.from_start)
        print(f"{directory}: {grouping_stats}")
        print("  deck store files (grouping *.xml) stored for source='mtgo_deck'")
        if deck_dir is not None and deck_dir.resolve() == directory.resolve():
            deck_dir = None
    if deck_dir is not None:
        deck_stats = ingest_deck_dir(conn, deck_dir, from_start=args.from_start)
        print(f"{deck_dir}: {deck_stats}")
        print("  deck files stored for source='mtgo_deck'")
    # The live watcher's MTGO game-log leg reads once, at its own startup, and
    # never polls again (live.py) — so these rows need a nudge to reach a
    # session that was already running when they landed. A running watcher
    # still notices them on its own (poll_once's external-rows check), but
    # only at its next due rebuild; a bare 'project' with no watcher attached
    # needs telling explicitly.
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
    file, and how far did the database get. Reproduces, in one place, the
    manual debugging steps behind ``.claude/handoffs/mtgo-config-diagnostic.md``
    — the session that found a blank Current-match tab was two unmet
    prerequisites (no handle, a stale transport), neither a code defect, and
    neither visible anywhere without reading raw_events by hand.

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


def _build_watcher_process(args, path: Path):
    """Same construction as ``_build_watcher``, but for ``serve --watch``:
    the rebuild has to run outside the API's own process, or it contends
    with every request for the GIL (``live.py``'s ``WatcherProcess``
    docstring has the measurements). ``ingest --watch`` has no API to
    contend with, so it keeps using ``_build_watcher``'s in-process
    ``LiveIngester`` unchanged."""
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


def _run_metagame_refresh(conn, args) -> None:
    """The fbettega cache refresh — unchanged from before --source existed."""
    from sensei_top.metagame import cache_age_seconds, refresh_metagame

    result = refresh_metagame(conn, window_days=args.window_days, force=args.force)
    if result.status == "failed":
        age = cache_age_seconds(conn, source="fbettega")
        cached = f"{age / 3600:.0f}h old" if age is not None else "no cached copy"
        print(f"cache: could not refresh ({result.error}); keeping what is stored ({cached}).")
    elif result.status == "fresh":
        print(f"cache: corpus is {(result.age_seconds or 0) / 3600:.0f}h old; nothing to do.")
    else:
        skipped = f", {result.skipped} skipped" if result.skipped else ""
        print(f"cache: {result.events} tournament events stored at {result.commit_sha}{skipped}.")


def _run_topdeck_refresh(conn, args) -> None:
    """The TopDeck.gg refresh — a silent no-op with no key configured, same
    as any other unconfigured free download (AGENTS.md non-negotiable #5)."""
    from sensei_top.metagame import cache_age_seconds, refresh_topdeck

    result = refresh_topdeck(conn, window_days=args.window_days, force=args.force)
    if result.status == "not_configured":
        if args.source == "topdeck":
            print(
                "topdeck: no API key configured — "
                "run 'sensei-top config --set-topdeck-key KEY'."
            )
        return
    if result.status == "failed":
        age = cache_age_seconds(conn, source="topdeck")
        cached = f"{age / 3600:.0f}h old" if age is not None else "no cached copy"
        print(f"topdeck: could not refresh ({result.error}); keeping what is stored ({cached}).")
    elif result.status == "fresh":
        print(f"topdeck: corpus is {(result.age_seconds or 0) / 3600:.0f}h old; nothing to do.")
    else:
        skipped = f", {result.skipped} skipped" if result.skipped else ""
        print(f"topdeck: {result.events} tournament events stored{skipped}.")


def cmd_meta(args) -> None:
    from sensei_top.metagame import classify_meta_decks, mark_duplicate_events

    conn = _open(args)
    if args.reclassify:
        # No network at all: re-run the classifier over whatever corpus is
        # already stored, e.g. after an archetype-definition refresh. Also
        # how an existing corpus gets cleaned of duplicate tournament events
        # with no network at all — see metagame/dedup.py.
        duplicates = mark_duplicate_events(conn)
        if duplicates:
            print(f"{duplicates} duplicate tournament events set aside.")
        counts = classify_meta_decks(conn)
        print(f"{counts['classified']} decks classified, {counts['unclassified']} unidentified "
              f"({counts['skipped_format']} skipped, not Standard)")
        return

    if args.source in ("cache", "all"):
        _run_metagame_refresh(conn, args)
    if args.source in ("topdeck", "all"):
        _run_topdeck_refresh(conn, args)

    duplicates = mark_duplicate_events(conn)
    if duplicates:
        print(f"{duplicates} duplicate tournament events set aside.")
    counts = classify_meta_decks(conn)
    print(f"{counts['classified']} decks classified, {counts['unclassified']} unidentified")


def cmd_backup(args) -> None:
    """Take (or check on) today's ``VACUUM INTO`` snapshot of the database.

    One deliberate divergence from ``cmd_archetypes`` (cli.py:282): that
    command exits 0 on a failed refresh because the cached definitions still
    name decks, so nothing was actually lost. A failed backup is different —
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
        # run_backup's own `finally` still ran on the way up (Python runs a
        # `finally` block during exception propagation, KeyboardInterrupt
        # included), so the temp file is already gone and the claim already
        # released — there is nothing left to clean up here.
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

    Both credential writers below go through this pair of functions rather
    than reading/writing their own table directly — the file holds two
    unrelated tables now (``[claude]``, ``[topdeck]``), and the original
    single-table writer would have silently dropped whichever one it wasn't
    asked to write. A value is a string, a bool, or — one level deep only,
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
    except (OSError, tomllib.TOMLDecodeError):
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
    and its ``[claude.coach]`` sub-table, leaving any other table
    (``[topdeck]``) untouched."""
    from sensei_top.llm.config import DEFAULT_EFFORT, DEFAULT_MODEL

    tables = _read_config_tables()
    current_claude = tables.get("claude", {})
    current_coach = current_claude.get("coach")
    if not isinstance(current_coach, dict):
        current_coach = {}

    new_key = api_key if api_key is not None else current_claude.get("api_key")
    if not isinstance(new_key, str) or not new_key:
        sys.exit("No API key set yet. Run 'sensei-top config --set-key KEY' first.")
    new_model = model if model is not None else current_claude.get("model", DEFAULT_MODEL)
    new_effort = effort if effort is not None else current_claude.get("effort", DEFAULT_EFFORT)

    new_coach_model = coach_model if coach_model is not None else current_coach.get("model")
    new_coach_effort = coach_effort if coach_effort is not None else current_coach.get("effort")
    new_coach_web_search = (
        coach_web_search if coach_web_search is not None else current_coach.get("web_search")
    )

    claude_table: dict[str, object] = {
        "api_key": new_key,
        "model": new_model,
        "effort": new_effort,
    }
    any_coach_field_set = (
        new_coach_model is not None
        or new_coach_effort is not None
        or new_coach_web_search is not None
    )
    if any_coach_field_set:
        coach_table: dict[str, object] = {}
        if new_coach_model is not None:
            coach_table["model"] = new_coach_model
        if new_coach_effort is not None:
            coach_table["effort"] = new_coach_effort
        if new_coach_web_search is not None:
            coach_table["web_search"] = bool(new_coach_web_search)
        claude_table["coach"] = coach_table

    tables["claude"] = claude_table
    _write_config_tables(tables)


def _write_topdeck_config(*, api_key: str) -> None:
    """Merge into the existing ``[topdeck]`` table (if any), leaving
    ``[claude]`` untouched."""
    tables = _read_config_tables()
    tables["topdeck"] = {"api_key": api_key}
    _write_config_tables(tables)


def _write_mtgo_config(*, handle: str | None = None, directory: str | None = None) -> None:
    """Merge into the existing ``[mtgo]`` table (if any), leaving ``[claude]``
    and ``[topdeck]`` untouched -- and, like ``_write_backup_config`` below,
    merging **within its own table field by field** too: ``--set-mtgo-dir``
    alone must not erase a ``handle`` set earlier by ``--set-mtgo-handle``, or
    vice versa, since the two flags are independent and typically run on two
    separate occasions. Neither field is a secret — the handle is the user's
    own MTGO account name, needed only because MTGO's log carries no auth
    event to learn "which player is us" from, and the directory is a path on
    the user's own machine (``mtgo/config.py``'s module docstring covers
    both) — so unlike the two API keys, nothing here masks either one."""
    tables = _read_config_tables()
    current = tables.get("mtgo", {})
    if not isinstance(current, dict):
        current = {}

    new_handle = handle if handle is not None else current.get("handle")
    new_directory = directory if directory is not None else current.get("dir")

    table: dict[str, object] = {}
    if new_handle is not None:
        table["handle"] = new_handle
    if new_directory is not None:
        table["dir"] = new_directory

    tables["mtgo"] = table
    _write_config_tables(tables)


def _write_backup_config(*, directory: str | None = None, keep: int | None = None) -> None:
    """Merge into the existing ``[backup]`` table (if any), leaving
    ``[claude]``/``[topdeck]``/``[mtgo]`` untouched -- and, like
    ``_write_mtgo_config`` above, merging **within its own table field by
    field** too: ``--set-backup-keep`` alone must not erase a ``dir`` set
    earlier by ``--set-backup-dir``, or vice versa, since ``--set-backup-dir``
    and ``--set-backup-keep`` are two independent flags that can be run on
    two separate occasions. ``keep`` is written through ``_write_config_tables``
    the same as every other value there -- as a quoted string -- which is
    exactly the shape ``backup.config._parse_keep`` exists to accept back as
    a number rather than mistake for "not configured" (see its docstring)."""
    tables = _read_config_tables()
    current = tables.get("backup", {})
    if not isinstance(current, dict):
        current = {}

    new_dir = directory if directory is not None else current.get("dir")
    new_keep = keep if keep is not None else current.get("keep")

    table: dict[str, object] = {}
    if new_dir is not None:
        table["dir"] = new_dir
    if new_keep is not None:
        table["keep"] = new_keep

    tables["backup"] = table
    _write_config_tables(tables)


def cmd_config(args) -> None:
    """No ``--set-*`` flag: show the two resolved credentials (source and the
    key masked to its last 4 characters) plus the configured MTGO handle and
    log directory, each shown in full with its own source — neither is a
    secret: the handle is the user's own account name, the directory a path
    on their own machine — and where backups go. This never echoes a full
    key, on disk or in the config file's own directory listing — only in the
    file's contents, which is why ``_write_config_tables`` chmods it 600.

    Four independent settings share one file: the metered Claude key
    (AGENTS.md non-negotiable #5), the free, rate-limited TopDeck.gg key (the
    "free downloads" standard), the ``[mtgo]`` table (the handle
    ``project()`` needs to know which seat in an MTGO game log is ours, and
    the directory its files are read from — two fields, one table, each
    settable on its own), and the backup destination and retention count. A
    flag for one never touches another's table — see
    ``_write_llm_config``/``_write_topdeck_config``/``_write_mtgo_config``/
    ``_write_backup_config``.
    """
    import os

    from sensei_top.llm import config as llm_config
    from sensei_top.metagame import config as topdeck_config

    if args.set_topdeck_key:
        _write_topdeck_config(api_key=args.set_topdeck_key)
        print(f"TopDeck.gg key written to {llm_config.config_path()} (mode 600).")
        return

    if args.set_mtgo_handle:
        _write_mtgo_config(handle=args.set_mtgo_handle)
        print(f"MTGO handle written to {llm_config.config_path()} (mode 600).")
        return

    if args.set_mtgo_dir:
        resolved_dir = str(Path(args.set_mtgo_dir).expanduser().resolve())
        if not Path(resolved_dir).exists():
            print(f"{resolved_dir} does not exist yet; stored anyway.")
        _write_mtgo_config(directory=resolved_dir)
        print(f"MTGO log directory written to {llm_config.config_path()} (mode 600).")
        return

    if args.set_backup_dir or args.set_backup_keep:
        _write_backup_config(directory=args.set_backup_dir, keep=args.set_backup_keep)
        print(f"Backup settings written to {llm_config.config_path()} (mode 600).")
        return

    coach_web_search = {"on": True, "off": False}.get(args.coach_web_search)
    if (
        args.set_key
        or args.set_model
        or args.set_effort
        or args.set_coach_model
        or args.set_coach_effort
        or coach_web_search is not None
    ):
        _write_llm_config(
            api_key=args.set_key,
            model=args.set_model,
            effort=args.set_effort,
            coach_model=args.set_coach_model,
            coach_effort=args.set_coach_effort,
            coach_web_search=coach_web_search,
        )
        print(f"Config written to {llm_config.config_path()} (mode 600).")
        return

    cfg = llm_config.load()
    if cfg is None:
        print("No Claude credential configured. Every generate button falls back to its prompt.")
        print("  Run 'sensei-top config --set-key KEY', or export ANTHROPIC_API_KEY.")
    else:
        env_set = os.environ.get("ANTHROPIC_API_KEY")
        source = "$ANTHROPIC_API_KEY" if env_set else str(llm_config.config_path())
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
        env_set = os.environ.get("TOPDECK_API_KEY")
        source = "$TOPDECK_API_KEY" if env_set else str(llm_config.config_path())
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
        print("No MTGO log directory configured. MTGO won't be read at watcher startup.")
        print("  Run 'sensei-top config --set-mtgo-dir DIR', or export MTGO_LOG_DIR.")
    else:
        mtgo_dir, mtgo_dir_source = resolved_dir
        print(f"MTGO directory source: {mtgo_dir_source}")
        print(f"  Directory: {mtgo_dir}")

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
            ro_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
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
        count = upsert_cards(conn, fetch_default_cards())
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
        from sensei_top.archetypes import standard_opponent_source_breakdown

        print("\nOpponent classification (completed Standard matches)")
        print("-" * 62)
        counts = standard_opponent_source_breakdown(conn)
        if counts["total"]:
            for source in ("archetype", "fallback", "colors", "manual", "unknown"):
                pct = 100 * counts[source] / counts["total"]
                print(f"{source:<12} {counts[source]:>4} / {counts['total']} ({pct:5.1f}%)")
        else:
            print("(no completed Standard matches yet)")
    print()


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

    # --prompt: print the text to hand an assistant, and stop -- the
    # no-credential path (AGENTS.md non-negotiable #5, docs/llm.md). Paste
    # it into a Claude Code session on a subscription that is already paid
    # for, then feed the answer back with --import. The Deck guide tab's own
    # "Write the guide" button does the same round trip in one click when
    # `sensei-top config --set-key` has been run.
    if args.prompt:
        from sensei_top.guide.narrative import full_prompt

        text = full_prompt(guide, conn=conn)
        if text is None:
            sys.exit("Nothing to write about for this deck yet (no recorded matches).")
        print(text)
        return

    if args.import_file:
        from sensei_top.brief.from_guide import store_guide_matchups
        from sensei_top.brief.store import corpus_commit, list_hash
        from sensei_top.guide.authored import write_narrative
        from sensei_top.guide.narrative import (
            NarrativeError,
            full_prompt,
            guide_narrative_from_json,
        )

        raw = Path(args.import_file).read_text()
        try:
            narrative = guide_narrative_from_json(raw, guide)
        except NarrativeError as exc:
            sys.exit(f"Could not read {args.import_file}: {exc}")

        identity = guide.provenance.deck
        write_narrative(
            conn, identity.key, narrative,
            list_hash=list_hash(identity.current_cards),
            prompt=full_prompt(guide, conn=conn) or "",
            author=args.author,
            corpus_commit=corpus_commit(conn),
        )
        written = store_guide_matchups(conn, guide, narrative, model=args.author)
        conn.commit()
        print(f"Imported the guide for {identity.name or identity.key}.")
        print(f"  {written} matchup brief(s) stored — these also drive the Current match tab.")
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
        Path(args.markdown).write_text(markdown)
        print(f"Guide written to {args.markdown}")
    else:
        print(markdown)


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
        from sensei_top.brief.importer import import_brief
        from sensei_top.brief.narrative import NarrativeError

        raw = Path(args.import_file).read_text()
        try:
            brief = import_brief(
                conn, identity, args.archetype, args.archetype, raw, author=args.author,
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
        from sensei_top.brief.importer import import_briefs
        from sensei_top.brief.narrative import NarrativeError

        raw = Path(args.import_file).read_text()
        try:
            stored, skipped = import_briefs(
                conn, identity, raw, author=args.author, labels=labels,
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
    """
    import threading

    def run() -> None:
        try:
            from sensei_top.archetypes import classify_matches, refresh_archetypes

            conn = connect(db_path)
            try:
                if refresh_archetypes(conn).status == "updated":
                    classify_matches(conn)
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
    loop. (17lands' bulk stats were the second step until the draft
    assistant was deleted, 2026-10-01.) One step's exception is caught
    and logged at warning level on its own — never fatal, and never lets one
    step's failure stop the others from running this tick or the next.
    Starting the thread returns immediately; the loop's own body — including
    its first run — happens entirely on that thread, so this never blocks
    ``serve``'s own startup the way a synchronous first check would.
    """
    import threading
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
    no ``open_database`` call). AGENTS.md non-negotiable #5: "Loopback binds
    only ... this is why no part of this app needs an authentication story";
    changing that means building one first, not quietly widening ``--host``.

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
        path = _resolve_log(args.file)
        watcher = _build_watcher_process(args, path)
        watcher.start()
        print(
            f"Watching {path} every {args.interval}s, "
            f"projecting at least every {args.project_every}s "
            f"(adaptive up to duty_factor={args.duty_factor}x the last rebuild's duration)"
        )
        if watcher.mtgo_dir is not None:
            print(
                f"MTGO logs at {watcher.mtgo_dir} read once at startup; run "
                "'sensei-top ingest-mtgo' (or restart) to pick up newer MTGO matches"
            )
            if mtgo_load_handle() is None:
                print(
                    "  No [mtgo] handle configured — these files will be stored but skipped "
                    "at projection ('sensei-top config --set-mtgo-handle YOURHANDLE' to fix)."
                )
        elif args.no_mtgo:
            print("Not reading MTGO logs (--no-mtgo)")
        elif resolve_log_dir() is None:
            print(
                "Not reading MTGO logs (no directory configured — pass --mtgo-dir, set "
                "MTGO_LOG_DIR, or run 'sensei-top config --set-mtgo-dir DIR')"
            )
        else:
            print(
                "Not reading MTGO logs (the configured directory doesn't exist — see the "
                "warning above)"
            )
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

    print(f"Serving {db_path} on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    print(f"  API docs: http://{args.host}:{args.port}/docs")
    try:
        uvicorn.run(
            create_app(db_path, watcher=watcher),
            host=args.host,
            port=args.port,
            log_level="warning",
        )
    finally:
        if watcher is not None:
            watcher.stop()
        if backup_scheduler is not None:
            backup_scheduler.stop()


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
    sub_parser.add_argument(
        "--locale", choices=("mdy", "dmy"), default="mdy",
        help="date order in log headers (default mdy)",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sensei-top", description=__doc__)
    parser.add_argument(
        "--db", default=str(DEFAULT_DB), help="SQLite file (default: data/sensei-top.db)"
    )
    parser.add_argument("--verbose", action="store_true", help="show projection warnings")
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
    # Loopback by default and on purpose (AGENTS.md non-negotiable #5): the
    # brief forbids exposing game data to the network. --host still exists
    # for picking a *different* loopback address (a container's own lo, an
    # IPv6 ::1 setup) — never for binding somewhere reachable from outside
    # this machine. cmd_serve's own _require_loopback enforces that no
    # other value gets past argument parsing.
    p_serve.add_argument(
        "--host", default="127.0.0.1",
        help="loopback bind address only (default 127.0.0.1) — rejected otherwise",
    )
    p_serve.add_argument("--port", type=int, default=8000, help="port (default 8000)")
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
    _add_watch_arguments(p_serve)
    p_serve.set_defaults(func=cmd_serve)

    # Card names are the one thing an Arena log cannot supply on its own. Read
    # from the installed client by default; --scryfall is for machines without
    # Arena on them, and is the project's only network call.
    p_cards = sub.add_parser("cards", help="load card names (from the installed Arena client)")
    p_cards.add_argument(
        "--scryfall", action="store_true",
        help="download from Scryfall instead of reading the local Arena install",
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
        "--source", choices=["cache", "topdeck", "all"], default="all",
        help="'cache' is fbettega/MTG_decklistcache (MTGO+Melee); 'topdeck' is "
        "TopDeck.gg RCQs, skipped silently with no key configured (default: all)",
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

    # Opt-in only (AGENTS.md non-negotiable #5): nothing here makes a Claude
    # API call until a credential is set. Needs no --db at all. The TopDeck.gg
    # key lives in the same file but is a separate, free/rate-limited
    # credential, governed by the free-download standard instead — see
    # "The standard for the free downloads" in docs/llm.md.
    p_config = sub.add_parser(
        "config",
        help="set or show the opt-in Claude and TopDeck.gg credentials (no flags: show them)",
    )
    p_config.add_argument("--set-key", default=None, metavar="KEY", help="Anthropic API key")
    p_config.add_argument("--set-model", default=None, metavar="ID", help="e.g. claude-opus-5")
    p_config.add_argument(
        "--set-effort", default=None, metavar="LEVEL",
        help="low | medium | high | xhigh | max",
    )
    p_config.add_argument(
        "--set-topdeck-key", default=None, metavar="KEY",
        help="TopDeck.gg API key — enables 'meta --source topdeck'",
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
        "--set-backup-dir", default=None, metavar="DIR",
        help="destination for daily database backups (default: a 'backups' folder beside the db)",
    )
    p_config.add_argument(
        "--set-backup-keep", type=_positive_int, default=None, metavar="N",
        help="how many backup slots to retain (default: 1)",
    )
    # Coach-only overrides: written to a separate [claude.coach] table,
    # never touching the [claude] defaults the other three narrative routes
    # use via load().
    p_config.add_argument(
        "--set-coach-model", default=None, metavar="ID",
        help="the coach report's default model, which the Coach tab's model picker "
        "preselects, e.g. claude-fable-5-1",
    )
    p_config.add_argument(
        "--set-coach-effort", default=None, metavar="LEVEL",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="effort override for the coach report only: low | medium | high | xhigh | max",
    )
    p_config.add_argument(
        "--coach-web-search", default=None, choices=["on", "off"],
        help="enable or disable the coach's web search tool (default: on)",
    )
    p_config.set_defaults(func=cmd_config)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.verbose else logging.ERROR,
        format="%(levelname)s %(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
