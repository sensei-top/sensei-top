"""The RCQ guide: preview (read-only), generate (the opt-in Claude call),
paste (``PUT``, stores a pasted answer, no call), the latest stored guide and
its Markdown export — ``/api/guide/{key}/rcq*``
(``docs/guide.md``).
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from sensei_top.answers import PASTED_AUTHOR, rcq_for
from sensei_top.api.convert import _list_diff_out
from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.common import BoardCardOut, PlanProblemOut
from sensei_top.api.models.rcq import (
    RcqExpectedOut,
    RcqFlexNoteOut,
    RcqFreshnessOut,
    RcqGenerateIn,
    RcqGuideOut,
    RcqMarkdownOut,
    RcqMatchupOut,
    RcqNarrativeOut,
    RcqPasteIn,
    RcqPreviewOut,
    RcqRecentEventOut,
    RcqRecentShareOut,
)
from sensei_top.api.routes.narrative import (
    check_pasted_length,
    read_pasted,
    require_credential,
    run_authored_write,
    unreadable_answer,
)
from sensei_top.api.sql import _shared_report_cache
from sensei_top.guide.decklist import parse_decklist
from sensei_top.guide.rcq import (
    _RCQ_TOOL,
    NarrativeError,
    RcqEvidence,
    RcqNarrative,
    build_rcq,
    rcq_from_json,
    rcq_prompt,
    top8_name,
)
from sensei_top.guide.rcq_authored import StoredRcq, latest_rcq, write_rcq
from sensei_top.guide.rcq_markdown import render_rcq
from sensei_top.i18n import _, english
from sensei_top.llm import client as llm_client

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
    return RcqGuideOut(
        status="ok", id=stored.id, generated_at=stored.generated_at, model=stored.model,
        cost_usd=stored.cost_usd, decklist_text=stored.decklist_text,
        expected=list(stored.expected), guide=_narrative_out(stored.guide),
    )


def _key_by_name(conn: sqlite3.Connection) -> dict[str, str]:
    """Corpus archetype name -> key, the most common key per name."""
    rows = conn.execute(
        """
        SELECT archetype_name AS name, archetype_key AS key, COUNT(*) AS n
          FROM meta_deck_archetype WHERE archetype_key IS NOT NULL
         GROUP BY 1, 2 ORDER BY n ASC, key DESC
        """
    ).fetchall()
    # Ascending count, so the last write per name is the most common key.
    return {r["name"]: r["key"] for r in rows}


def _no_deck(key: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail=_("No deck for key {key}.").format(key=repr(key)),
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


def _preview(evidence: RcqEvidence, conn: sqlite3.Connection, prompt: str) -> RcqPreviewOut:
    """The page's fields in the request's language. ``evidence`` was built
    in English, for ``prompt``, so nothing here copies its text: each
    sentence is written now from the data behind it — the pasted text is
    parsed again (``parse_decklist`` is pure), and the unclassified reason,
    the duplicate warnings and the top-8 sentinel are formatted from
    codes."""
    keys = _key_by_name(conn)
    return RcqPreviewOut(
        format=evidence.guide.field.fmt,
        main_count=sum(evidence.parsed.main.values()),
        side_count=sum(evidence.parsed.side.values()),
        warnings=list(parse_decklist(evidence.decklist_text).warnings),
        unresolved=list(evidence.resolved.unresolved),
        own_archetype_key=evidence.own_verdict_key,
        own_archetype_name=evidence.own_verdict_name,
        own_unclassified_reason=evidence.own_unclassified_reason,
        list_diff=_list_diff_out(evidence.list_diff),
        recent_shares=[
            RcqRecentShareOut(
                archetype=s.archetype, archetype_key=keys.get(s.archetype),
                share=s.share, decks=s.decks,
            )
            for s in evidence.recent_shares
        ],
        recent_events=[
            RcqRecentEventOut(
                date=e.date, name=e.name, source=e.source, tier=e.tier,
                decks=e.decks, top8=[top8_name(name) for name in e.top8],
            )
            for e in evidence.recent_events
        ],
        freshness=[
            RcqFreshnessOut(
                source=f.source, newest_event=f.newest_event, fetched_at=f.fetched_at
            )
            for f in evidence.freshness
        ],
        expected=[
            RcqExpectedOut(
                key=x.key, name=x.name, share=x.share,
                wins=x.record.wins if x.record else None,
                losses=x.record.losses if x.record else None,
                carryable=x.record.carryable if x.record else None,
            )
            for x in evidence.expected
        ],
        prompt=prompt,
    )


def _newest_event(evidence: RcqEvidence) -> str | None:
    dates = [f.newest_event for f in evidence.freshness if f.newest_event]
    return max(dates) if dates else None


@router.get("/api/guide/{key}/rcq/preview", response_model=RcqPreviewOut, tags=["guide"])
def rcq_preview(
    key: str,
    request: Request,
    conn: Conn,
    decklist: str = "",
    expected: Annotated[list[str] | None, Query()] = None,
    own: str | None = None,
) -> RcqPreviewOut:
    """The pasted 75 read back against the field, and the prompt that would
    be sent. Read-only; makes no call. 404 is an unknown deck."""
    # One build serves both: the evidence is built in English, because the
    # prompt quotes it, and _preview writes the page's own sentences in the
    # request's language from the data behind them.
    with english():
        evidence = build_rcq(
            conn, key, decklist, list(expected or []), own,
            report_cache=_shared_report_cache(request, conn),
        )
        prompt = rcq_prompt(evidence, conn=conn) if evidence is not None else None
    if evidence is None or prompt is None:
        raise _no_deck(key)
    return _preview(evidence, conn, prompt)


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
        # English: the plan problems it finds are stored with the guide
        # (plan S4, D-c), like every other stored prose.
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
    """Store an answer pasted into the RCQ guide's card — what ``sensei-top
    rcq --deck KEY --import FILE`` stores. Makes no model call. The body
    carries the same list fields the preview and generate routes take, since
    the guide is checked against that 75 and stored beside it.

    422 for another card's or an unreadable answer, nothing stored (a flex
    note role other than core, flex or risk is refused as on the CLI); 413
    over 256 KB; 404 an unknown deck. The RCQ prompt carries no context
    hash, so the header is ``for`` alone. Stored with the sentinel model
    ``pasted``, no tokens, no cost. Every paste keeps its own row, like a
    generation.
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
    # English: the export is prompt input (plan D7), like the deck guide's.
    with english():
        deck_guide = build_deck_guide(
            conn, key, report_cache=_shared_report_cache(request, conn),
        )
        shares = {s.archetype: s.share for s in deck_guide.field.shares} if deck_guide else {}
        markdown = render_rcq(stored, share_by_archetype=shares)
    return RcqMarkdownOut(markdown=markdown)
