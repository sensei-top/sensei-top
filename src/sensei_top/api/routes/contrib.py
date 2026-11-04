"""The contributed games' two routes, both read-only, neither calling
anything outside the machine: the desktop shell's main process sends what
they return.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from sensei_top.api.deps import Conn
from sensei_top.api.models.contrib import ContribRecordItem
from sensei_top.contrib import build_records, finished_game_keys

router = APIRouter()

# The most records one request builds: the shell sends them in batches of
# this size.
MAX_KEYS = 50


@router.get("/api/contrib/games", response_model=list[str], tags=["contrib"])
def contrib_games(conn: Conn) -> list[str]:
    """The key, ``match_id:game_number``, of every finished game, oldest
    match first; the caller keeps which ones it has sent."""
    return finished_game_keys(conn)


@router.get(
    "/api/contrib/records",
    response_model=list[ContribRecordItem],
    response_model_exclude_none=True,
    tags=["contrib"],
)
def contrib_records(
    conn: Conn,
    keys: Annotated[list[str], Query(min_length=1, max_length=MAX_KEYS)],
    policy_version: Annotated[str, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")],
) -> list[dict[str, Any]]:
    """One record per key that names a finished game, in the order asked;
    any other key is left out of the answer, so the caller sends nothing for
    it."""
    return [
        {"key": key, "record": record}
        for key, record in build_records(conn, keys, policy_version=policy_version)
    ]
