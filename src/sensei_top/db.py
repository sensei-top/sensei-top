"""SQLite connection setup and forward-only migrations.

WAL mode, so the dashboard can read while the ingester writes. Migrations
are numbered raw-SQL files in ``sensei_top/migrations/``, recorded in
``schema_version``, forward-only: derived tables are rebuilt from
``raw_events`` instead of migrated backwards. See docs/architecture.md,
"Storage".
"""

from __future__ import annotations

import re
import sqlite3
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

# Read through importlib.resources so an installed wheel finds the files too.
MIGRATIONS_DIR: Traversable = files("sensei_top") / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{3})_.*\.sql$")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the database, applying pragmas suited to one writer + N readers."""
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit; use explicit BEGIN
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")     # safe with WAL; fsync on checkpoint
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")      # reader/writer contention -> wait, don't raise
    # SQLite's own default page cache is 2 MB — negligible against a
    # multi-hundred-MB database that cannot fit in the OS page cache either
    # on a machine also running Arena (measured: 3.3 GB already in swap, 4.7
    # GB of page cache free against a 1.33 GB database). 64 MB costs nothing
    # idle and gives the reader/writer/watcher paths room to keep hot pages
    # (raw_events' tail, the projected tables project() rewrites) resident
    # across queries instead of re-reading them from disk every time.
    conn.execute("PRAGMA cache_size=-65536")      # 64 MB, negative = KiB
    # mmap trades a page-cache copy for a direct-mapped read (measured
    # before it was kept). 256 MB is a starting point, not a target, on a
    # host already under swap pressure with Arena resident.
    conn.execute("PRAGMA mmap_size=268435456")    # 256 MB
    return conn


def discover_migrations(
    migrations_dir: Traversable = MIGRATIONS_DIR,
) -> list[tuple[int, Traversable]]:
    """Return (version, path) pairs sorted by version; validate numbering."""
    found: list[tuple[int, Traversable]] = []
    sql_files = [p for p in migrations_dir.iterdir() if p.name.endswith(".sql")]
    for path in sorted(sql_files, key=lambda p: p.name):
        m = _MIGRATION_RE.match(path.name)
        if not m:
            raise ValueError(f"migration file does not match NNN_name.sql: {path.name}")
        found.append((int(m.group(1)), path))
    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError(f"duplicate migration versions in {migrations_dir}")
    return found


def applied_version(conn: sqlite3.Connection) -> int:
    """Highest applied migration version, 0 for a fresh database."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return row["v"] or 0


def migrate(conn: sqlite3.Connection, migrations_dir: Traversable = MIGRATIONS_DIR) -> list[int]:
    """Apply pending migrations in order, each in its own transaction.

    Returns the list of versions applied in this call.
    """
    current = applied_version(conn)
    applied: list[int] = []
    for version, path in discover_migrations(migrations_dir):
        if version <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        # Deliberately not executescript(): it issues an implicit COMMIT and
        # would break per-migration atomicity.
        conn.execute("BEGIN")
        try:
            for statement in _split_statements(sql):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into statements on ';' at top level.

    Good enough for DDL: none of our schema files embed ';' inside string
    literals. If that ever changes, revisit, but keep executescript() out
    (see ``migrate``).
    """
    # Strip line comments *first*: comments may legitimately contain ';'.
    code = "\n".join(
        line.split("--", 1)[0] if "--" in line and '"' not in line and "'" not in line else line
        for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    )
    return [chunk.strip() for chunk in code.split(";") if chunk.strip()]


def open_database(db_path: str | Path) -> sqlite3.Connection:
    """Connect and bring the schema up to date. The normal entry point.

    For a process's startup only. A long-running process (``serve``) reads
    the migrations folder from the working tree, so a connection opened later on
    with this would apply whatever migration file has appeared since --
    uncommitted, unreviewed, on whatever branch is checked out -- under code
    that doesn't know the new schema. Anything that opens a connection after
    startup uses ``connect()``.
    """
    conn = connect(db_path)
    migrate(conn)
    return conn
