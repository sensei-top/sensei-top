"""The deck guide's narrative: ``GET``, ``POST`` and ``PUT`` on
``/api/guide/{key}/narrative`` (``docs/llm.md``, ``docs/guide.md``)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Request

from sensei_top.ai.answers import PASTED_AUTHOR, guide_for
from sensei_top.ai.guide import narrative as guide_narrative
from sensei_top.ai.guide.authored import narrative_for, write_narrative
from sensei_top.ai.guide.narrative import (
    _GUIDE_TOOL,
    NarrativeError,
    guide_narrative_from_json,
)
from sensei_top.ai.llm import client as llm_client
from sensei_top.ai.routes.narrative import (
    check_pasted_length,
    read_pasted,
    require_credential,
    run_authored_write,
    unreadable_answer,
)
from sensei_top.api.convert import _guide_narrative_out
from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.common import PastedAnswerIn
from sensei_top.api.models.guide import GuideNarrativeResponse
from sensei_top.api.routes.guide import _no_deck
from sensei_top.api.sql import _shared_report_cache
from sensei_top.brief.from_guide import store_guide_matchups
from sensei_top.brief.store import corpus_commit, list_hash
from sensei_top.guide.bundle import DeckGuide, build_deck_guide
from sensei_top.i18n import _, english

router = APIRouter()


@english()
def _guide_and_prompt(
    request: Request, conn: sqlite3.Connection, key: str, *, answer_contract: bool,
) -> tuple[DeckGuide | None, str | None]:
    """The deck guide and its prompt, both built in English. The guide is
    built here, before ``full_prompt`` runs, and its findings and caveats are
    what the prompt quotes — so the build has to be inside ``english()``
    too, not just the serializer (the same reason ``matches.py``'s and
    ``review.py``'s ``build_context`` closures are). ``(None, None)`` is an
    unknown deck. ``answer_contract`` is the copied prompt's ending
    (``answers.answer_format``); the generate path asks for its schema
    through structured outputs instead, so it passes ``False``."""
    deck_guide = build_deck_guide(conn, key, report_cache=_shared_report_cache(request, conn))
    if deck_guide is None:
        return None, None
    return deck_guide, guide_narrative.full_prompt(
        deck_guide, conn=conn, answer_contract=answer_contract,
    )


@router.get(
    "/api/guide/{key}/narrative", response_model=GuideNarrativeResponse, tags=["guide"]
)
def guide_narrative_route(key: str, request: Request, conn: Conn) -> GuideNarrativeResponse:
    """The deck's stored narrative, and always the prompt to (re)write it
    from.

    ``status`` is ``'ok'`` when a narrative has been generated (``POST``
    on this same path) or pasted (``PUT`` on this same path) for this
    deck, and ``'prompt'`` when none has —
    either way ``prompt`` carries the text to write one from, so the tab
    can offer "write it" and "rewrite it" with the same affordance.

    ``stale`` compares the stored ``list_hash`` against the deck's
    current 75: a narrative written for a different 75 names cards the
    deck may no longer hold, which is worth flagging loudly rather than
    rendering as current.
    """
    deck_guide, prompt = _guide_and_prompt(request, conn, key, answer_contract=True)
    if deck_guide is None:
        raise _no_deck(key)
    return _stored_guide_response(conn, deck_guide, prompt)


def _stored_guide_response(
    conn: sqlite3.Connection, deck_guide: DeckGuide, prompt: str | None,
) -> GuideNarrativeResponse:
    """What the ``GET`` answers for a deck whose guide and copied prompt are
    already built — shared with the ``PUT``, which builds them once too."""
    if prompt is None:
        return GuideNarrativeResponse(status="no_report")

    stored = narrative_for(conn, deck_guide.provenance.deck.key)
    if stored is None:
        return GuideNarrativeResponse(status="prompt", prompt=prompt)

    authored, narrative = stored
    return GuideNarrativeResponse(
        status="ok",
        guide=_guide_narrative_out(narrative),
        prompt=prompt,
        authored_at=authored.authored_at,
        author=authored.author,
        cost_usd=authored.cost_usd,
        stale=authored.list_hash != list_hash(deck_guide.provenance.deck.current_cards),
    )


@router.post(
    "/api/guide/{key}/narrative", response_model=GuideNarrativeResponse, tags=["guide"]
)
def generate_guide_narrative(
    key: str, request: Request, conn: WritableConn
) -> GuideNarrativeResponse:
    """Write this deck's guide narrative with Claude, and store it.

    Sends the same ``full_prompt`` the copy-prompt path serves, minus the
    answer contract that ends a copied prompt (``answers.answer_format``):
    the answer is requested via structured outputs against
    ``_GUIDE_TOOL``'s own schema instead, parsed by
    ``guide_narrative_from_json`` — the validator the paste path uses too.
    Also fills every matchup plan the guide covers into
    ``matchup_brief`` (``brief/from_guide.py``) — this is the whole reason
    the live matchup brief needs no generate button of its own.
    """
    deck_guide, prompt = _guide_and_prompt(request, conn, key, answer_contract=False)
    if deck_guide is None:
        raise _no_deck(key)

    cfg = require_credential()

    if prompt is None:
        raise HTTPException(
            status_code=404, detail=_("Nothing to write about for this deck yet.")
        )

    schema = llm_client.strict_schema(_GUIDE_TOOL["input_schema"])
    try:
        completion = llm_client.write_json(prompt, schema, cfg=cfg, label="deck guide")
    except llm_client.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        # English: the plan problems it finds are stored with the narrative,
        # like every other stored prose.
        with english():
            narrative = guide_narrative_from_json(completion.text, deck_guide)
    except NarrativeError as exc:
        raise HTTPException(
            status_code=502,
            detail=_("Claude's answer could not be read: {error}").format(error=exc),
        ) from exc

    identity = deck_guide.provenance.deck
    # One transaction, not two: the guide's write touches a second table
    # (`matchup_brief`, via `store_guide_matchups`). A guide stored without
    # its matchup briefs would render as a guide whose matchup section
    # silently lost its plans, and the next request would read it as
    # complete rather than retrying.
    def write() -> None:
        write_narrative(
            conn, identity.key, narrative,
            list_hash=list_hash(identity.current_cards),
            prompt=prompt,
            author=completion.model,
            corpus_commit=corpus_commit(conn),
            input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd,
        )
        store_guide_matchups(conn, deck_guide, narrative, model=completion.model)

    run_authored_write(conn, write)

    stored = narrative_for(conn, identity.key)
    assert stored is not None
    authored, stored_narrative = stored
    return GuideNarrativeResponse(
        status="ok",
        guide=_guide_narrative_out(stored_narrative),
        prompt=prompt,
        authored_at=authored.authored_at,
        author=authored.author,
        cost_usd=authored.cost_usd,
        stale=False,
    )


@router.put(
    "/api/guide/{key}/narrative", response_model=GuideNarrativeResponse, tags=["guide"]
)
def paste_guide_narrative(
    key: str, body: PastedAnswerIn, request: Request, conn: WritableConn
) -> GuideNarrativeResponse:
    """Store an answer pasted into the deck guide's card — the dashboard's
    way to store a narrative written elsewhere.

    Makes no model call. The answer is read through the answer contract
    (``answers.read_answer``, header required): 422 when it is another
    card's or another deck's, is not JSON, or does not parse as a guide, and
    nothing is stored; 413 over 256 KB. It is stored with the 75 its
    ``context`` says it was written for, so one written for an older list
    reads as stale; the author is the sentinel ``pasted``, tokens and cost
    ``NULL``. Every matchup plan lands in ``matchup_brief`` in the same
    transaction as the narrative. Returns what ``GET`` on this path returns.
    """
    check_pasted_length(body.answer)
    deck_guide, prompt = _guide_and_prompt(request, conn, key, answer_contract=True)
    if deck_guide is None:
        raise _no_deck(key)
    if prompt is None:
        raise HTTPException(
            status_code=404, detail=_("Nothing to write about for this deck yet.")
        )

    identity = deck_guide.provenance.deck
    answer = read_pasted(body.answer, guide_for(identity.key))
    try:
        # English: the plan problems it finds are stored with the narrative.
        with english():
            narrative = guide_narrative_from_json(answer.body, deck_guide)
    except NarrativeError as exc:
        raise unreadable_answer(exc) from exc

    def write() -> None:
        write_narrative(
            conn, identity.key, narrative,
            list_hash=answer.context,
            prompt=prompt,
            author=PASTED_AUTHOR,
            corpus_commit=corpus_commit(conn),
        )
        store_guide_matchups(
            conn, deck_guide, narrative, model=PASTED_AUTHOR, list_hash=answer.context,
        )

    run_authored_write(conn, write)
    return _stored_guide_response(conn, deck_guide, prompt)
