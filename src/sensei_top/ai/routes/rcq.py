"""The RCQ guide's authored routes: generate (the opt-in Claude call), paste
(``PUT``, stores a pasted answer, no call), the latest stored guide and its
Markdown export — ``/api/guide/{key}/rcq*`` (``docs/guide.md``). The preview
is core's (``api/routes/rcq.py``)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Request

from sensei_top.ai.answers import PASTED_AUTHOR, rcq_for
from sensei_top.ai.guide.rcq_authored import StoredRcq, latest_rcq, write_rcq
from sensei_top.ai.guide.rcq_markdown import render_rcq
from sensei_top.ai.guide.rcq_prompt import (
    _RCQ_TOOL,
    NarrativeError,
    RcqNarrative,
    rcq_context,
    rcq_from_json,
    rcq_prompt,
)
from sensei_top.ai.llm import client as llm_client
from sensei_top.ai.routes.narrative import (
    check_pasted_length,
    read_pasted,
    require_credential,
    run_authored_write,
    unreadable_answer,
)
from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.common import BoardCardOut, PlanProblemOut
from sensei_top.api.models.rcq import (
    RcqFlexNoteOut,
    RcqGenerateIn,
    RcqGuideOut,
    RcqMarkdownOut,
    RcqMatchupOut,
    RcqNarrativeOut,
    RcqPasteIn,
)
from sensei_top.api.routes.rcq import _no_deck
from sensei_top.api.sql import _shared_report_cache
from sensei_top.guide.decklist import parse_decklist
from sensei_top.guide.rcq import RcqEvidence, build_rcq
from sensei_top.i18n import _, english

router = APIRouter()


def _narrative_out(n: RcqNarrative) -> RcqNarrativeOut:
    return RcqNarrativeOut(
        game_plan=n.game_plan,
        expected_field=n.expected_field,
        matchups=[
            RcqMatchupOut(
                archetype=m.archetype, prose=m.prose, play_draw=m.play_draw,
                board_in=[BoardCardOut(card=c.card, n=c.n) for c in m.board_in],
                board_out=[BoardCardOut(card=c.card, n=c.n) for c in m.board_out],
            )
            for m in n.matchups
        ],
        flex_notes=[RcqFlexNoteOut(card=f.card, role=f.role, why=f.why) for f in n.flex_notes],
        checklist=list(n.checklist),
        problems=[PlanProblemOut(archetype=p.archetype, message=p.message) for p in n.problems],
    )


def _guide_out(stored: StoredRcq) -> RcqGuideOut:
    # The answer's context against the list stored beside it (migration 069):
    # unknown, for a generated guide or an older prompt's answer, is not
    # "another list".
    another = stored.written_for is not None and stored.written_for != rcq_context(
        parse_decklist(stored.decklist_text), stored.expected
    )
    return RcqGuideOut(
        status="ok", id=stored.id, generated_at=stored.generated_at, model=stored.model,
        cost_usd=stored.cost_usd, decklist_text=stored.decklist_text,
        expected=list(stored.expected), guide=_narrative_out(stored.guide),
        answered_for_another_list=another,
    )


@english()
def _evidence_and_prompt(
    request: Request, conn: sqlite3.Connection, key: str, body: RcqGenerateIn,
    *, answer_contract: bool,
) -> tuple[RcqEvidence | None, str | None]:
    """The RCQ evidence for a pasted 75 and the prompt built from it, in
    English throughout, not just the prompt: the evidence is built here,
    before ``rcq_prompt`` runs, and its text is what the prompt quotes.
    ``answer_contract`` is the copied prompt's ending; the generate route
    passes ``False``. Shared by the generate and paste routes."""
    evidence = build_rcq(
        conn, key, body.decklist, body.expected, body.own,
        report_cache=_shared_report_cache(request, conn),
    )
    if evidence is None:
        return None, None
    return evidence, rcq_prompt(evidence, conn=conn, answer_contract=answer_contract)


def _newest_event(evidence: RcqEvidence) -> str | None:
    dates = [f.newest_event for f in evidence.freshness if f.newest_event]
    return max(dates) if dates else None


@router.post("/api/guide/{key}/rcq/narrative", response_model=RcqGuideOut, tags=["guide"])
def generate_rcq(
    key: str, body: RcqGenerateIn, request: Request, conn: WritableConn
) -> RcqGuideOut:
    """Write the RCQ guide with Claude, and store it (every generation keeps
    its own row). Same posture as the deck guide's route: 503 with no
    credential, 502 when the call or its answer fails."""
    # Structured outputs carry the schema, so no copied-prompt contract.
    evidence, prompt = _evidence_and_prompt(
        request, conn, key, body, answer_contract=False,
    )
    if evidence is None or prompt is None:
        raise _no_deck(key)

    cfg = require_credential()
    schema = llm_client.strict_schema(_RCQ_TOOL["input_schema"])
    try:
        completion = llm_client.write_json(prompt, schema, cfg=cfg, label="rcq")
    except llm_client.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    try:
        # English: the plan problems it finds are stored with the guide,
        # like every other stored prose.
        with english():
            narrative = rcq_from_json(completion.text, evidence)
    except NarrativeError as exc:
        raise HTTPException(
            status_code=502,
            detail=_("Claude's answer could not be read: {error}").format(error=exc),
        ) from exc

    run_authored_write(
        conn,
        lambda: write_rcq(
            conn, key, narrative,
            model=completion.model, decklist_text=body.decklist,
            expected=list(evidence.expected_keys), own_archetype_key=body.own,
            prompt=prompt, corpus_latest_event=_newest_event(evidence),
            input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd, effort=cfg.effort,
        ),
    )
    stored = latest_rcq(conn, key)
    assert stored is not None
    return _guide_out(stored)


@router.put("/api/guide/{key}/rcq/narrative", response_model=RcqGuideOut, tags=["guide"])
def paste_rcq(
    key: str, body: RcqPasteIn, request: Request, conn: WritableConn
) -> RcqGuideOut:
    """Store an answer pasted into the RCQ guide's card. Makes no model
    call. The body carries the same list fields the preview and generate
    routes take, since the guide is checked against that 75 and stored
    beside it.

    422 for another card's or an unreadable answer, nothing stored (a flex
    note role other than core, flex or risk is one); 413 over 256 KB; 404
    an unknown deck. Stored with the ``context`` the answer carries, the
    list it was written for (``rcq_context``; an answer from a prompt older
    than the hash has none, and is stored with it unknown), and the
    sentinel model ``pasted``, no tokens, no cost. Every paste keeps its own
    row, like a generation.
    """
    check_pasted_length(body.answer)
    evidence, prompt = _evidence_and_prompt(request, conn, key, body, answer_contract=True)
    if evidence is None or prompt is None:
        raise _no_deck(key)
    answer = read_pasted(body.answer, rcq_for(evidence.guide.provenance.deck.key))
    try:
        with english():
            narrative = rcq_from_json(answer.body, evidence)
    except NarrativeError as exc:
        raise unreadable_answer(exc) from exc
    for note in narrative.flex_notes:
        if note.role not in ("core", "flex", "risk"):
            raise unreadable_answer(ValueError(
                f"flex note role {note.role!r} is not core, flex or risk"
            ))

    run_authored_write(
        conn,
        lambda: write_rcq(
            conn, key, narrative,
            model=PASTED_AUTHOR, decklist_text=body.decklist,
            expected=list(evidence.expected_keys), own_archetype_key=body.own,
            prompt=prompt, corpus_latest_event=_newest_event(evidence),
            written_for=answer.context,
        ),
    )
    stored = latest_rcq(conn, key)
    assert stored is not None
    return _guide_out(stored)


@router.get("/api/guide/{key}/rcq", response_model=RcqGuideOut, tags=["guide"])
def rcq_latest(key: str, conn: Conn) -> RcqGuideOut:
    """The latest stored RCQ guide, or ``status: 'none'``."""
    stored = latest_rcq(conn, key)
    if stored is None:
        return RcqGuideOut(
            status="none", id=None, generated_at=None, model=None, cost_usd=None,
            decklist_text=None, expected=[], guide=None,
        )
    return _guide_out(stored)


@router.get("/api/guide/{key}/rcq/markdown", response_model=RcqMarkdownOut, tags=["guide"])
def rcq_markdown(key: str, request: Request, conn: Conn) -> RcqMarkdownOut:
    """The latest stored guide as Markdown; 404 when none is stored."""
    from sensei_top.guide.bundle import build_deck_guide

    stored = latest_rcq(conn, key)
    if stored is None:
        raise HTTPException(
            status_code=404,
            detail=_("No RCQ guide stored for {key}.").format(key=repr(key)),
        )
    # English: the export is prompt input, like the deck guide's.
    with english():
        deck_guide = build_deck_guide(
            conn, key, report_cache=_shared_report_cache(request, conn),
        )
        shares = {s.archetype: s.share for s in deck_guide.field.shares} if deck_guide else {}
        markdown = render_rcq(stored, share_by_archetype=shares)
    return RcqMarkdownOut(markdown=markdown)
