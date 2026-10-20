"""``sensei-top doctor``: what the app can find, read-only (plan 6, D15).

One function builds the report, ``report()``; ``cmd_doctor`` prints it and
``diagnostics.py`` zips it. Nothing here writes, migrates or downloads, so it
is safe beside a running ``serve``:

- The database is opened through a ``?mode=ro`` URI, never ``connect()`` or
  ``open_database()``: ``connect()`` sets ``journal_mode=WAL``, which writes,
  creates a missing file, and ``open_database()`` also applies pending
  migrations. A missing file, a missing table or a database that will not
  open reads as ``None`` (rule 4: unknown, not zero). A read-only open can
  still leave an empty ``-wal`` and a 32 KB ``-shm`` beside a WAL database
  nothing else has open; the main file is untouched.
- Detailed Logs is read from the first 200 lines of the Arena log. Arena
  writes ``DETAILED LOGS: ENABLED`` there; ``disabled`` needs the matching
  ``DISABLED`` line, which no capture has shown yet (docs/status.md), so the
  answer is ``unknown`` for any log that carries neither line.

The keys of the dict ``report()`` returns are a contract: the desktop shell
reads ``doctor --json`` (``docs/desktop.md``, "Support commands").
``mtgo.discovered`` is the folder ``mtgo/discover.py`` finds (Windows only,
``None`` elsewhere): a suggestion for onboarding, never a configured value.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sensei_top import arena_config, secrets
from sensei_top.db import discover_migrations
from sensei_top.llm.config import config_path
from sensei_top.mtgo import discover
from sensei_top.mtgo.config import load_handle, resolve_deck_dir, resolve_log_dir
from sensei_top.reader.ingest import found_log_paths

HEADER_LINES = 200
ENABLED_LINE = "DETAILED LOGS: ENABLED"
DISABLED_LINE = "DETAILED LOGS: DISABLED"

HINT = (
    "Arena's log does not say Detailed Logs is on. Turn on Detailed Logs "
    "(Plugin Support) in Arena, under Options, then Account, and start Arena again."
)


def detailed_logs(path: Path | None) -> str:
    """``enabled``, ``disabled`` or ``unknown``, from the log's first lines.
    ``unknown`` too when there is no path or the file cannot be read."""
    if path is None:
        return "unknown"
    try:
        with path.open("rb") as f:
            lines = [f.readline() for _ in range(HEADER_LINES)]
    except OSError:
        return "unknown"
    text = b"".join(lines).decode("utf-8", errors="replace")
    if ENABLED_LINE in text:
        return "enabled"
    if DISABLED_LINE in text:
        return "disabled"
    return "unknown"


def code_version() -> int:
    """The highest migration this code ships."""
    return max(version for version, _ in discover_migrations())


def _read_only(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(db_path.absolute().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _scalar(conn: sqlite3.Connection | None, sql: str) -> int | None:
    """One integer from ``sql``, or ``None`` when the table is missing or
    the database cannot answer."""
    if conn is None:
        return None
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None or row[0] is None else int(row[0])


def report(db_path: Path, file: str | None = None) -> dict:
    """The whole report, as the ``--json`` contract spells it.

    ``cards.arena_ids`` counts the rows keyed by an Arena ``grp_id`` (the
    table has no source column, and ``cards --scryfall`` fills Arena ids
    too); ``cards.rules_text`` counts the rows with non-null ``oracle_text``."""
    if file:
        arena_path, source = Path(file).absolute(), "flag"
    else:
        arena_path, source = arena_config.resolve_log()
    if arena_path is not None:
        arena_path = arena_path.absolute()
    log_dir = resolve_log_dir()
    deck_dir = resolve_deck_dir()
    discovered = discover.discover_log_folder()
    conn = _read_only(db_path)
    try:
        cards = {
            "arena_ids": _scalar(conn, "SELECT COUNT(*) FROM cards WHERE grp_id > 0"),
            "rules_text": _scalar(conn, "SELECT COUNT(*) FROM cards WHERE oracle_text IS NOT NULL"),
        }
        schema_version = _scalar(conn, "SELECT MAX(version) FROM schema_version")
    finally:
        if conn is not None:
            conn.close()
    arena_log: dict = {
        "path": str(arena_path) if arena_path is not None else None,
        "source": source,
        "detailed_logs": detailed_logs(arena_path),
    }
    if source == "autodetect" and arena_path is not None:
        # found_log_paths() is a second scan: the path in use goes first so
        # found[0] always equals the path reported above.
        found = [arena_path]
        seen = {arena_path.resolve()}
        for other in found_log_paths():
            other = other.absolute()
            if other.resolve() not in seen:
                seen.add(other.resolve())
                found.append(other)
        arena_log["found"] = [str(p) for p in found]
    return {
        "arena_log": arena_log,
        "mtgo": {
            "log_dir": str(log_dir[0].absolute()) if log_dir else None,
            "log_dir_source": log_dir[1] if log_dir else None,
            "deck_dir": str(deck_dir[0].absolute()) if deck_dir else None,
            "deck_dir_source": deck_dir[1] if deck_dir else None,
            "handle_set": load_handle() is not None,
            "discovered": str(discovered.absolute()) if discovered else None,
        },
        "cards": cards,
        "database": {
            "path": str(db_path.absolute()),
            "exists": db_path.exists(),
            "schema_version": schema_version,
            "code_version": code_version(),
        },
        "config_path": str(config_path()),
        "keyring_backend": secrets.backend_name(),
    }


def _fmt(value: object) -> str:
    return "unknown" if value is None else str(value)


def lines(data: dict) -> list[str]:
    """The human-readable report, one fact per line."""
    arena, mtgo = data["arena_log"], data["mtgo"]
    database = data["database"]
    out = [
        f"Arena log: {arena['path'] or 'not found'} (from {arena['source']})",
        *(f"  Also found: {p}" for p in arena.get("found", [])[1:]),
        f"  Detailed Logs: {arena['detailed_logs']}",
    ]
    if arena["detailed_logs"] == "unknown" and arena["path"]:
        out.append(f"  {HINT}")
    out += [
        f"MTGO log directory: {mtgo['log_dir'] or 'not set'}"
        + (f" (from {mtgo['log_dir_source']})" if mtgo["log_dir"] else ""),
        f"MTGO deck directory: {mtgo['deck_dir'] or 'not set'}"
        + (f" (from {mtgo['deck_dir_source']})" if mtgo["deck_dir"] else ""),
        f"MTGO handle: {'set' if mtgo['handle_set'] else 'not set'}",
        f"Cards with an Arena id: {_fmt(data['cards']['arena_ids'])}",
        f"Cards with rules text (from Scryfall): {_fmt(data['cards']['rules_text'])}",
        f"Database: {database['path']} ({'exists' if database['exists'] else 'not created yet'})",
        f"  Schema version: {_fmt(database['schema_version'])} (this code ships "
        f"{database['code_version']})",
        f"Config file: {data['config_path']}",
        f"Keyring backend: {data['keyring_backend'] or 'none usable'}",
    ]
    return out
