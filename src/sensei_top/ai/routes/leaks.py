"""The leak finder's narrative: ``GET``, ``POST`` and ``PUT`` on
``/api/review/leaks/narrative`` (``docs/llm.md``, ``docs/review.md``)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Request

from sensei_top.ai.answers import LEAKS_FOR, PASTED_AUTHOR
from sensei_top.ai.review import leaks_narrative, leaks_store
from sensei_top.ai.routes.narrative import (
    NarrativeSpec,
    check_pasted_length,
    narrative_get,
    narrative_post,
    read_pasted_prose,
    run_authored_write,
)
from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.common import NarrativeResponse, PastedAnswerIn
from sensei_top.api.routes.review import _leaks_consensus_window
from sensei_top.api.sql import _shared_report_cache
from sensei_top.i18n import _, english
from sensei_top.review.leaks import find_leaks

router = APIRouter()


def _leaks_narrative_spec(request: Request, conn: sqlite3.Connection) -> NarrativeSpec:
    # English throughout, not just the serializer: each leak's text is
    # written here, by find_leaks, and the prompt quotes it.
    @english()
    def build_context():
        leaks = find_leaks(
            conn, consensus_window=_leaks_consensus_window(conn),
            report_cache=_shared_report_cache(request, conn),
        )
        return leaks_narrative.build_leaks_context(list(leaks))

    return NarrativeSpec(
        build_context=build_context,
        full_prompt=leaks_narrative.full_prompt,
        copied_prompt=lambda context: leaks_narrative.copied_prompt(
            context, answer_for=LEAKS_FOR,
            context_hash=leaks_store.context_hash(context),
        ),
        read_stored=lambda: leaks_store.read_leaks_narrative(conn),
        context_hash=leaks_store.context_hash,
        no_context_detail=_("Nothing to write a training plan from yet."),
        label="leak finder",
    )


@router.get(
    "/api/review/leaks/narrative", response_model=NarrativeResponse, tags=["review"]
)
def review_leaks_narrative_route(request: Request, conn: Conn) -> NarrativeResponse:
    """The stored training-plan prose over the leak finder's own ranked
    output, and always the prompt to (re)write it from. Same shape and
    posture as the per-match narrative route.
    """
    env = narrative_get(_leaks_narrative_spec(request, conn))
    return NarrativeResponse(
        status=env.status, narrative=env.content, prompt=env.prompt,
        model=env.who, generated_at=env.when, cost_usd=env.cost_usd, stale=env.stale,
    )


@router.post(
    "/api/review/leaks/narrative", response_model=NarrativeResponse, tags=["review"]
)
def generate_leaks_narrative(request: Request, conn: WritableConn) -> NarrativeResponse:
    """Write a training plan over the leak finder's own ranked output
    with Claude, and store it. Same evidence and posture as the
    per-match generate route.
    """
    spec = _leaks_narrative_spec(request, conn)

    def write(prompt: str, completion, context) -> None:
        leaks_store.write_leaks_narrative(
            conn,
            prose=completion.text, prompt=prompt, model=completion.model,
            context_hash=leaks_store.context_hash(context),
            input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd,
        )

    env = narrative_post(conn, spec, write=write)
    return NarrativeResponse(
        status=env.status, narrative=env.content, prompt=env.prompt,
        model=env.who, generated_at=env.when, cost_usd=env.cost_usd, stale=env.stale,
    )


@router.put(
    "/api/review/leaks/narrative", response_model=NarrativeResponse, tags=["review"]
)
def paste_leaks_narrative(
    request: Request, body: PastedAnswerIn, conn: WritableConn
) -> NarrativeResponse:
    """Store an answer pasted into the training plan's card. Makes no model
    call; same refusals, storage and response as the per-match paste route
    (422 for another card's answer or one with no prose, 413 over 256 KB,
    the header's context stored, the model ``pasted``)."""
    check_pasted_length(body.answer)
    spec = _leaks_narrative_spec(request, conn)
    context = spec.build_context()
    if context is None:
        raise HTTPException(status_code=404, detail=spec.no_context_detail)
    answer, prose = read_pasted_prose(body.answer, LEAKS_FOR)
    prompt = spec.copied_prompt(context)

    run_authored_write(conn, lambda: leaks_store.write_leaks_narrative(
        conn,
        prose=prose, prompt=prompt, model=PASTED_AUTHOR,
        context_hash=answer.context,
    ))

    stored = spec.read_stored()
    assert stored is not None
    return NarrativeResponse(
        status="ok", narrative=stored.prose, prompt=prompt, model=stored.model,
        generated_at=stored.generated_at, cost_usd=stored.cost_usd,
        stale=stored.context_hash != spec.context_hash(context),
    )
