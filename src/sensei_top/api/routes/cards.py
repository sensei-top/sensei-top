"""A card's pictures, cached on disk and fetched from Scryfall on first
miss — the two routes in this layer that also write to disk outside
SQLite (AGENTS.md non-negotiable #6).
"""

from __future__ import annotations

import sqlite3
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
    first miss (AGENTS.md rule 5's third sanctioned download). The one
    read this route does — the card's own name, so Arena-exclusive
    printings with no Scryfall arena_id can still be found by name (see
    card_images.py) — stays inside query_only; the cache itself is plain
    files beside the database, so that pragma is still the whole story
    for what can write to SQLite. 404 covers "Scryfall has no image for
    this id under any name we tried" and "offline right now" alike; the
    dashboard falls back to the card's name either way. Sync def on
    purpose: FastAPI runs it in a threadpool, so the blocking download
    cannot stall the event loop.
    """
    path = card_images.get_image(_cache_dir(request), grp_id, name=_card_name(conn, grp_id))
    if path is None:
        raise HTTPException(status_code=404, detail=_("No image for card {id}.").format(id=grp_id))
    return _picture(path)


@router.get("/api/cards/{grp_id}/art", tags=["cards"])
def card_art(grp_id: int, request: Request, conn: Conn) -> FileResponse:
    """A card's art alone, from its own on-disk cache, fetched from Scryfall
    on first miss. The image route's twin: the same one database read (the
    card's name, for the retry by name), the same plain files beside the
    database, the same 404 for "Scryfall has no such picture" and "offline
    right now" alike, the same sync def. Only what it serves differs,
    Scryfall's ``art_crop`` in place of the whole card, and the two caches
    never answer for each other.
    """
    path = card_images.get_art(_cache_dir(request), grp_id, name=_card_name(conn, grp_id))
    if path is None:
        raise HTTPException(status_code=404, detail=_("No art for card {id}.").format(id=grp_id))
    return _picture(path)
