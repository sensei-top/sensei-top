"""FastAPI dependencies every router shares: one connection per request
(read-only, or the one writable exception rule 6 allows), and the deck
filter every metric endpoint accepts.

Both connection dependencies stay at module scope, reading the database
path off ``request.app.state`` rather than being closed over inside
``create_app``: with ``from __future__ import annotations`` a
locally-defined alias is an unresolvable forward reference to pydantic —
this was a real failure, not hypothetical.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request

__all__ = [
    "Conn", "DeckFilter", "SourceFilter", "WritableConn", "get_conn", "get_writable_conn",
]


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection per request, read-only. Kept at module scope (reading the
    path off ``app.state``) rather than closed over in ``create_app``: with
    ``from __future__ import annotations`` a locally-defined alias is an
    unresolvable forward reference to pydantic."""
    database: Path = request.app.state.database
    if not database.exists():
        # Connecting would create an empty file — refuse instead, and say what
        # to run, since an empty database renders identically to "no games
        # played yet" once the dashboard draws it.
        raise HTTPException(
            status_code=503,
            detail=f"No database at {database}. Run 'sensei-top ingest' then 'project'.",
        )
    conn = sqlite3.connect(database, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")   # this layer is read-only, enforced
    conn.execute("PRAGMA busy_timeout=5000")
    # Same pragmas as db.py's connect() and for the same reason: the default
    # 2 MB page cache and disabled mmap were measured costing real time on
    # every one of these per-request connections against a database too
    # large to stay resident in the OS page cache alongside Arena itself.
    conn.execute("PRAGMA cache_size=-65536")      # 64 MB, negative = KiB
    conn.execute("PRAGMA mmap_size=268435456")    # 256 MB
    try:
        yield conn
    finally:
        conn.close()


def get_writable_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """The one writable connection in this layer.

    Rule 6 in AGENTS.md allows exactly one exception to the read-only API, and
    this is it: a manual deck label is the user's own words about their own
    match, there is no other source for it, and it has to survive the full
    rebuild that erases every derived row. Kept beside ``get_conn`` rather than
    inside ``create_app`` for the same reason — under ``from __future__ import
    annotations`` a locally-defined alias is an unresolvable forward reference
    to pydantic.

    Pragmas match ``db.py``'s ``connect()`` deliberately: ``isolation_level=
    None`` so a write block is an explicit ``BEGIN``/``COMMIT``/``ROLLBACK``
    (``docs/conventions.md``) rather than sqlite3's implicit transaction, and
    ``foreign_keys=ON`` so this connection enforces what every other one in
    the project does. Neither is currently load-bearing — no table on rule 6's
    write allowlist declares a foreign key, and ``opponent_deck_override``
    deliberately never will (see ``docs/architecture.md``) — but a writable
    connection that silently enforces *less* than the rest of the project is
    the kind of difference that only shows up as a corrupted row much later.
    """
    database: Path = request.app.state.database
    if not database.exists():
        raise HTTPException(
            status_code=503,
            detail=f"No database at {database}. Run 'sensei-top ingest' then 'project'.",
        )
    conn = sqlite3.connect(database, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
WritableConn = Annotated[sqlite3.Connection, Depends(get_writable_conn)]
DeckFilter = Annotated[str | None, Query(description="restrict to one deck_id")]
# Defaults to 'arena': every dashboard number before this feature existed was
# an Arena number, and every existing test/screenshot assumes that. 'all'
# means no filter at all (both sources together); 'mtgo' is the only other
# value _filtered() (api/sql.py) recognises.
SourceFilter = Annotated[
    str, Query(description="'arena' (default), 'mtgo', or 'all'")
]
