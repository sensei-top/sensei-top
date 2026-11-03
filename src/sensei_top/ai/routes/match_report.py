"""The match report's narrative: ``GET``, ``POST`` and ``PUT`` on
``/api/matches/{match_id}/report/narrative`` (``docs/llm.md``, ``docs/review.md``)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from sensei_top.ai.answers import PASTED_AUTHOR, match_for
from sensei_top.ai.review import narrative, narrative_store
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
from sensei_top.api.routes.matches import _no_match
from sensei_top.api.sql import _consensus_window, match_format
from sensei_top.i18n import _, english
from sensei_top.review import build_match_report
from sensei_top.review.snapshot import build_snapshot

router = APIRouter()


def _require_match(conn: sqlite3.Connection, match_id: str) -> None:
    if conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone() is None:
        raise _no_match(match_id)


def _field_context(
    conn: sqlite3.Connection, match_id: str, fmt: str | None, since: str | None
) -> narrative.FieldContext | None:
    """Public tournament data for this match's own opponent archetype, or
    ``None`` when there isn't any — same guard the Matchups tab's field-
    winrate column uses: only an ``opponent_key`` the classifier itself named
    (``'archetype:...'``) shares a vocabulary with the metagame corpus. A
    manual label, a colours-only guess, or 'unknown' has nothing to join.

    ``since`` windows the read to post-format-reset rounds only, the same
    boundary ``consensus_since`` already enforces for the opponent's
    consensus decklist (docs/metagame.md's "The format-reset boundary") —
    ``None`` means no reset detected (or no legality data yet), same as
    every other ``consensus_since`` caller.

    ``fmt`` is the match's ``v_match_format.format``: the field is that
    format's tournaments only, and a match with no format has no field.
    """
    if fmt is None:
        return None
    row = conn.execute(
        "SELECT opponent_key FROM v_match_opponent WHERE match_id = ?", (match_id,)
    ).fetchone()
    key = row["opponent_key"] if row else None
    if not key or not key.startswith("archetype:"):
        return None
    agg = conn.execute(
        """
        SELECT label, SUM(wins) AS matches_won, SUM(wins) + SUM(losses) + SUM(draws) AS matches
          FROM v_meta_winrate
         WHERE archetype_key = ? AND format = ? AND (? IS NULL OR event_date >= ?)
         GROUP BY label
        """,
        (key.removeprefix("archetype:"), fmt, since, since),
    ).fetchone()
    if agg is None or not agg["matches"]:
        return None
    return narrative.FieldContext(
        archetype_label=agg["label"], matches=agg["matches"],
        winrate=agg["matches_won"] / agg["matches"],
        since=since,
    )


def _match_report_narrative_spec(conn: sqlite3.Connection, match_id: str) -> NarrativeSpec:
    # English throughout, not just the serializer: the report and snapshot
    # are built here, and their findings' text is what the prompt quotes.
    @english()
    def build_context():
        fmt = match_format(conn, match_id)
        consensus_since = _consensus_window(conn, fmt)
        report = build_match_report(conn, match_id, consensus_since=consensus_since)
        snap = build_snapshot(conn, match_id, consensus_since=consensus_since)
        field = _field_context(conn, match_id, fmt, consensus_since)
        return narrative.build_narrative_context(report, snap, field=field)

    return NarrativeSpec(
        build_context=build_context,
        full_prompt=narrative.full_prompt,
        copied_prompt=lambda context: narrative.copied_prompt(
            context, answer_for=match_for(match_id),
            context_hash=narrative_store.context_hash(context),
        ),
        read_stored=lambda: narrative_store.read_match_narrative(conn, match_id),
        context_hash=narrative_store.context_hash,
        no_context_detail=_("Nothing to write about for this match yet."),
        label="match report",
    )


@router.get(
    "/api/matches/{match_id}/report/narrative",
    response_model=NarrativeResponse,
    tags=["matches"],
)
def match_report_narrative(match_id: str, conn: Conn) -> NarrativeResponse:
    """The stored "Coach's summary" for this match, and always the
    prompt to (re)write it from — see ``docs/llm.md``.

    ``status`` is ``'ok'`` once ``POST`` on this same path has generated
    one or ``PUT`` has stored a pasted one, ``'prompt'`` when there is
    evidence but nothing stored yet, and ``'no_report'`` when there is
    nothing to narrate at all — an empty report is an ordinary outcome, not
    an error. Always a 200 for a match that exists; an unknown
    ``match_id`` is a 404.
    """
    _require_match(conn, match_id)
    env = narrative_get(_match_report_narrative_spec(conn, match_id))
    return NarrativeResponse(
        status=env.status, narrative=env.content, prompt=env.prompt,
        model=env.who, generated_at=env.when, cost_usd=env.cost_usd, stale=env.stale,
    )


@router.post(
    "/api/matches/{match_id}/report/narrative",
    response_model=NarrativeResponse,
    tags=["matches"],
)
def generate_match_report_narrative(match_id: str, conn: WritableConn) -> NarrativeResponse:
    """Write this match's "Coach's summary" with Claude, and store it.

    Sends ``full_prompt`` (``ai/review/narrative.py``): the evidence ``GET``
    on this same path builds, without the answer contract that ``GET``'s
    ``copied_prompt`` adds, since the reply is prose. 503
    with no credential configured (``sensei-top config --set-key``) —
    the dashboard falls back to the copy-prompt path automatically. 502
    wraps whatever the Claude API itself objected to.
    """
    _require_match(conn, match_id)
    spec = _match_report_narrative_spec(conn, match_id)

    def write(prompt: str, completion, context) -> None:
        narrative_store.write_match_narrative(
            conn, match_id,
            prose=completion.text, prompt=prompt, model=completion.model,
            context_hash=narrative_store.context_hash(context),
            input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd,
        )

    env = narrative_post(conn, spec, write=write)
    return NarrativeResponse(
        status=env.status, narrative=env.content, prompt=env.prompt,
        model=env.who, generated_at=env.when, cost_usd=env.cost_usd, stale=env.stale,
    )


@router.put(
    "/api/matches/{match_id}/report/narrative",
    response_model=NarrativeResponse,
    tags=["matches"],
)
def paste_match_report_narrative(
    match_id: str, body: PastedAnswerIn, conn: WritableConn
) -> NarrativeResponse:
    """Store an answer pasted into this match's "Coach's summary" card.

    Makes no model call. The answer is read through the answer contract
    (``answers.read_answer``, header required): 422 when it is another
    card's or another match's, is not JSON, or carries no prose, and nothing
    is stored; 413 over 256 KB, before anything else; 404 for an unknown
    match, as for ``GET``. It is stored with the context its header says it
    was written for, so one written for older evidence reads as stale, and
    beside the copyable prompt rebuilt now; the model is the sentinel
    ``pasted``, tokens and cost ``NULL``. Returns what ``GET`` on this path
    returns.
    """
    check_pasted_length(body.answer)
    _require_match(conn, match_id)
    spec = _match_report_narrative_spec(conn, match_id)
    context = spec.build_context()
    if context is None:
        raise HTTPException(status_code=404, detail=spec.no_context_detail)
    answer, prose = read_pasted_prose(body.answer, match_for(match_id))
    prompt = spec.copied_prompt(context)

    run_authored_write(conn, lambda: narrative_store.write_match_narrative(
        conn, match_id,
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
