"""The deck guide's whole evidence bundle and the evidence-only markdown
export — ``/api/guide/*`` (``docs/guide.md``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from sensei_top.api.convert import _deck_guide_out, _deck_identity_out
from sensei_top.api.deps import Conn
from sensei_top.api.models.guide import (
    DeckGuideOut,
    DeckIdentityOut,
    GuideMarkdownOut,
)
from sensei_top.api.sql import _shared_report_cache
from sensei_top.guide.bundle import build_deck_guide
from sensei_top.guide.deck import list_identities
from sensei_top.guide.markdown import render as render_guide_markdown
from sensei_top.i18n import _, english

router = APIRouter()


def _no_deck(key: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail=_("No deck for key {key}.").format(key=repr(key)),
    )


@router.get("/api/guide/decks", response_model=list[DeckIdentityOut], tags=["guide"])
def guide_decks(conn: Conn) -> list[DeckIdentityOut]:
    """Every deck with recorded matches, one row per Arena GUID
    (``guide/deck.py``) — the picker behind the deck guide. Newest
    played first, same ordering ``list_identities`` returns.
    """
    return [_deck_identity_out(identity) for identity in list_identities(conn)]


@router.get("/api/guide/{key}", response_model=DeckGuideOut, tags=["guide"])
def guide(key: str, request: Request, conn: Conn) -> DeckGuideOut:
    """One deck's whole evidence bundle: play patterns, this deck's own
    leak-finder rollup beside every deck's, the current 75 against the
    field's consensus, and the field itself around any detected format
    reset — see ``guide/bundle.py``. 404 mirrors ``match_report``'s own
    posture: a key that resolves to nothing is a missing resource.
    """
    deck_guide = build_deck_guide(conn, key, report_cache=_shared_report_cache(request, conn))
    if deck_guide is None:
        raise _no_deck(key)
    return _deck_guide_out(deck_guide)


@router.get("/api/guide/{key}/markdown", response_model=GuideMarkdownOut, tags=["guide"])
def guide_markdown(key: str, request: Request, conn: Conn) -> GuideMarkdownOut:
    """The evidence-only guide document — ``guide/markdown.py``'s
    ``render`` with no narrative, exported for copy or save. The
    narrative sections (engine, matchups, checklist) come from the
    narrative route and are not included here: this
    route makes no Claude call, so it can never carry text that call
    alone produces.
    """
    # English, like every prompt: the export is prompt input, and the guide
    # it renders is built here, so the whole build is in scope.
    with english():
        deck_guide = build_deck_guide(
            conn, key, report_cache=_shared_report_cache(request, conn),
        )
        markdown = render_guide_markdown(deck_guide) if deck_guide is not None else None
    if markdown is None:
        raise _no_deck(key)
    return GuideMarkdownOut(markdown=markdown)
