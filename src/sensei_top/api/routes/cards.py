"""A card's pictures, cached on disk and fetched from Scryfall on first
miss — the two routes in this layer that also write to disk outside
SQLite (AGENTS.md non-negotiable #6).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from functools import partial
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from sensei_top import card_images
from sensei_top.api.deps import Conn
from sensei_top.i18n import _

router = APIRouter()


def _card_name(conn: sqlite3.Connection, grp_id: int) -> str | None:
    row = conn.execute("SELECT name FROM cards WHERE grp_id = ?", (grp_id,)).fetchone()
    return row["name"] if row else None


def _other_face(conn: sqlite3.Connection, grp_id: int) -> tuple[int, str] | None:
    """Another card of the same ``oracle_id`` under another name: the other
    face of a card Scryfall knows only whole. A prepare card's spell
    (Enroot, of "Carnivorous Cultivator // Enroot") has no Scryfall
    ``arena_id`` and no exact match by its own name, but the creature's
    name finds the card, and the card is one picture. NULL ``oracle_id``
    (``cards --scryfall`` not run) matches nothing."""
    row = conn.execute(
        "SELECT other.grp_id, other.name FROM cards AS own"
        " JOIN cards AS other ON other.oracle_id = own.oracle_id AND other.name <> own.name"
        " WHERE own.grp_id = ? ORDER BY other.grp_id LIMIT 1",
        (grp_id,),
    ).fetchone()
    return (row["grp_id"], row["name"]) if row else None


def _find(
    conn: sqlite3.Connection,
    grp_id: int,
    get: Callable[[int, str | None], Path | None],
) -> Path | None:
    """The card's own picture, else its other face's (``_other_face``),
    cached under that face's id. A transient miss (offline) asks for the
    other face too, and it misses the same way."""
    path = get(grp_id, _card_name(conn, grp_id))
    if path is None and (face := _other_face(conn, grp_id)) is not None:
        path = get(*face)
    return path


def _cache_dir(request: Request) -> Path:
    return request.app.state.database.parent / "card_images"


def _picture(path: Path) -> FileResponse:
    # A printing's picture is stable, so the browser may keep it forever.
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/api/cards/{grp_id}/image", tags=["cards"])
def card_image(grp_id: int, request: Request, conn: Conn) -> FileResponse:
    """A card's picture, from the on-disk cache, fetched from Scryfall on
    first miss (AGENTS.md rule 5's third sanctioned download). The reads
    this route does — the card's own name, so Arena-exclusive printings
    with no Scryfall arena_id can still be found by name (see
    card_images.py), and its other face's (``_other_face``) — stay inside
    query_only; the cache itself is plain files beside the database, so
    that pragma is still the whole story for what can write to SQLite.
    404 covers "Scryfall has no image for this id under any name we
    tried" and "offline right now" alike; the dashboard falls back to
    the card's name either way. Sync def on purpose: FastAPI runs it in a
    threadpool, so the blocking download cannot stall the event loop.
    """
    path = _find(conn, grp_id, partial(card_images.get_image, _cache_dir(request)))
    if path is None:
        raise HTTPException(status_code=404, detail=_("No image for card {id}.").format(id=grp_id))
    return _picture(path)


@router.get("/api/cards/{grp_id}/art", tags=["cards"])
def card_art(grp_id: int, request: Request, conn: Conn) -> FileResponse:
    """A card's art alone, from its own on-disk cache, fetched from Scryfall
    on first miss. The image route's twin: the same database reads (the
    card's name and its other face's), the same plain files beside the
    database, the same 404 for "Scryfall has no such picture" and "offline
    right now" alike, the same sync def. Only what it serves differs,
    Scryfall's ``art_crop`` in place of the whole card, and the two caches
    never answer for each other.
    """
    path = _find(conn, grp_id, partial(card_images.get_art, _cache_dir(request)))
    if path is None:
        raise HTTPException(status_code=404, detail=_("No art for card {id}.").format(id=grp_id))
    return _picture(path)
