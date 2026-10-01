"""The match list/detail drill-down, the opponent-deck override, the
post-game report and its narrative — everything under the ``matches`` tag
except the current-match reads, which have their own router.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from sensei_top.api.convert import _finding_out, _summary_out
from sensei_top.api.deps import Conn, DeckFilter, SourceFilter, WritableConn
from sensei_top.api.models.common import NarrativeResponse
from sensei_top.api.models.matches import (
    Match,
    MatchDetail,
    MatchGame,
    MatchReportOut,
    OpponentDeck,
    OpponentDeckCandidate,
    OpponentDeckLabelIn,
    PositionPoint,
    ReportGap,
    SideboardCardOut,
    SideboardGameOut,
    SideboardingOut,
)
from sensei_top.api.routes.narrative import NarrativeSpec, narrative_get, narrative_post
from sensei_top.api.sql import (
    _attach_zones,
    _cached_corpus_prior,
    _consensus_window,
    _rows,
)
from sensei_top.archetypes import Candidate, rank_candidates
from sensei_top.review import build_match_report, build_summary
from sensei_top.review import narrative as review_narrative
from sensei_top.review import narrative_store as match_narrative_store
from sensei_top.review.position import turn_position
from sensei_top.review.snapshot import build_snapshot
from sensei_top.table.boarding import named_diff

router = APIRouter()

# Magic's own term for a deck with no established archetype. Not one of the
# downloaded definitions, so it is never in the candidates list — the picker
# adds it itself, always last.
ROGUE_LABEL = "Rogue"


@router.get(
    "/api/matches/{match_id}/opponent-deck/candidates",
    response_model=list[OpponentDeckCandidate],
    tags=["matches"],
)
def opponent_deck_candidates(
    match_id: str, conn: Conn, request: Request
) -> list[dict[str, Any]]:
    """Every deck this match's opponent might be playing, best-evidenced
    first, for the picker to offer.

    "Rogue" is deliberately absent: it names the absence of an established
    archetype rather than one of the downloaded definitions, so the
    dashboard adds it itself, pinned last, instead of the API inventing a
    fake candidate for it.
    """
    if conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"No match {match_id}.")
    prior = _cached_corpus_prior(request, conn)
    candidates = _one_per_label(rank_candidates(conn, match_id, prior=prior))
    return [
        {
            "archetype_key": c.key,
            "label": c.label,
            "kind": c.kind,
            "confidence": c.confidence,
            "fit": c.fit,
            "evidence": list(c.evidence),
            "reasons": list(c.reasons),
            "signature_cards": [
                {"name": s.name, "seen": s.seen} for s in c.signature_cards
            ],
            "picked": c.picked,
        }
        for c in candidates
    ]


def _one_per_label(candidates: list[Candidate]) -> list[Candidate]:
    """One candidate per label, in the order given. Two definitions of one
    archetype in different colours rank as two candidates under one name
    (``classify._margins`` says why that is not a disagreement), and a
    picker offering the same name twice asks a question with no answer.
    The better fit keeps the name, since ``rank_candidates`` puts it
    first, unless the user already picked the other one."""
    kept: dict[str, Candidate] = {}
    for candidate in candidates:
        if candidate.label not in kept or candidate.picked:
            kept[candidate.label] = candidate
    return list(kept.values())


@router.put(
    "/api/matches/{match_id}/opponent-deck",
    response_model=OpponentDeck,
    tags=["matches"],
)
def set_opponent_deck(
    match_id: str, body: OpponentDeckLabelIn, conn: WritableConn
) -> dict[str, Any]:
    """Name the opponent's deck yourself: pick from the candidate list, or
    'Rogue' for a deck with no established archetype.

    The only write in this layer. An empty label clears the override, so
    the same verb both sets and unsets and the classifier's own answer
    comes back — which is why the response is read from the view rather
    than echoing what was sent.
    """
    label = " ".join(body.label.split())
    if any(character < " " for character in label):
        raise HTTPException(status_code=422, detail="Label may not contain control characters.")
    if conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"No match {match_id}.")

    archetype_key = body.archetype_key
    if not label:
        if archetype_key is not None:
            raise HTTPException(
                status_code=422, detail="archetype_key requires a non-empty label."
            )
    elif archetype_key is not None:
        if conn.execute(
            "SELECT 1 FROM archetypes WHERE source = ?", (archetype_key,)
        ).fetchone() is None:
            raise HTTPException(status_code=422, detail=f"No such archetype {archetype_key!r}.")
    elif label != ROGUE_LABEL:
        raise HTTPException(
            status_code=422,
            detail="Pick a candidate from GET .../opponent-deck/candidates, or 'Rogue'.",
        )

    conn.execute("BEGIN")
    try:
        if label:
            conn.execute(
                """
                INSERT INTO opponent_deck_override (match_id, label, archetype_key)
                     VALUES (?, ?, ?)
                ON CONFLICT (match_id) DO UPDATE SET
                     label = excluded.label,
                     archetype_key = excluded.archetype_key,
                     updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                """,
                (match_id, label, archetype_key),
            )
        else:
            conn.execute("DELETE FROM opponent_deck_override WHERE match_id = ?", (match_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    row = conn.execute(
        """
        SELECT opponent_label, opponent_key, opponent_source, opponent_confidence,
               opponent_cards_seen, opponent_colors
          FROM v_match_opponent WHERE match_id = ?
        """,
        (match_id,),
    ).fetchone()
    return dict(row)


@router.get("/api/matches", response_model=list[Match], tags=["matches"])
def matches(
    conn: Conn,
    deck_id: DeckFilter = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    source: SourceFilter = "arena",
) -> list[dict[str, Any]]:
    sql = """
        SELECT m.match_id, m.source, m.event_id, m.deck_id, d.name AS deck_name,
               m.opponent_name, m.started_at, m.ended_at, m.result, m.games_won, m.games_lost,
               o.opponent_label, o.opponent_key, o.opponent_source,
               o.opponent_confidence, o.opponent_cards_seen, o.opponent_colors,
               (SELECT r.constructed_class FROM rank_snapshot r
                 WHERE m.source = 'arena' AND r.observed_at <= m.started_at
                 ORDER BY r.observed_at DESC LIMIT 1) AS rank_class,
               (SELECT r.constructed_level FROM rank_snapshot r
                 WHERE m.source = 'arena' AND r.observed_at <= m.started_at
                 ORDER BY r.observed_at DESC LIMIT 1) AS rank_level
          FROM matches m
          LEFT JOIN decks d ON d.deck_id = m.deck_id
          LEFT JOIN v_match_opponent o ON o.match_id = m.match_id
    """
    clauses: list[str] = []
    params: list[Any] = []
    if deck_id:
        clauses.append("m.deck_id = ?")
        params.append(deck_id)
    if source != "all":
        clauses.append("m.source = ?")
        params.append(source)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY COALESCE(m.started_at, '') DESC LIMIT ?"
    params.append(limit)
    return _rows(conn, sql, tuple(params))


@router.get("/api/matches/{match_id}", response_model=MatchDetail, tags=["matches"])
def match_detail(match_id: str, conn: Conn) -> MatchDetail:
    """One past match, turn by turn, for the history drill-down.

    A 404 here (unlike /api/current-match's null) because the id was asked
    for by name: a match that does not exist is a missing resource, not an
    ordinary empty answer. Composing per-game reads is not aggregation —
    each is a thin select, nothing is counted or averaged in Python.
    """
    match = conn.execute(
        """
        SELECT m.match_id, m.source, m.event_id, m.deck_id, d.name AS deck_name,
               m.opponent_name, m.self_seat, m.started_at, m.ended_at, m.result,
               m.games_won, m.games_lost,
               o.opponent_label, o.opponent_key, o.opponent_source,
               o.opponent_confidence, o.opponent_cards_seen, o.opponent_colors,
               (SELECT r.constructed_class FROM rank_snapshot r
                 WHERE m.source = 'arena' AND r.observed_at <= m.started_at
                 ORDER BY r.observed_at DESC LIMIT 1) AS rank_class,
               (SELECT r.constructed_level FROM rank_snapshot r
                 WHERE m.source = 'arena' AND r.observed_at <= m.started_at
                 ORDER BY r.observed_at DESC LIMIT 1) AS rank_level
          FROM matches m
          LEFT JOIN decks d ON d.deck_id = m.deck_id
          LEFT JOIN v_match_opponent o ON o.match_id = m.match_id
         WHERE m.match_id = ?
        """,
        (match_id,),
    ).fetchone()
    if match is None:
        raise HTTPException(status_code=404, detail=f"No match {match_id}.")

    games = []
    for game in conn.execute(
        """
        SELECT game_number, on_play, result, result_reason,
               self_mulligans, opp_mulligans, turn_count
          FROM games WHERE match_id = ? ORDER BY game_number
        """,
        (match_id,),
    ).fetchall():
        key = (match_id, game["game_number"])
        turns = _rows(
            conn,
            """
            SELECT turn_number, active_seat, self_life, opp_life, self_hand, opp_hand,
                   self_lands, self_permanents, opp_permanents, self_library, opp_library,
                   self_graveyard, opp_graveyard, self_open_mana, opp_open_mana
              FROM turns WHERE match_id = ? AND game_number = ? ORDER BY turn_number
            """,
            key,
        )
        cards = _rows(
            conn,
            """
            SELECT seq, turn_number, category, zone_src, zone_dest, grp_id, card_name, is_self
              FROM v_card_events WHERE match_id = ? AND game_number = ? ORDER BY seq
            """,
            key,
        )
        _attach_zones(conn, match_id, game["game_number"], turns)
        games.append(MatchGame(**dict(game), turns=turns, cards=cards))
    return MatchDetail(**dict(match), games=games)


@router.get(
    "/api/matches/{match_id}/sideboarding",
    response_model=SideboardingOut,
    tags=["matches"],
)
def match_sideboarding(match_id: str, conn: Conn) -> SideboardingOut:
    """What actually changed between games, from ClientMessageType_
    SubmitDeckResp (migrations/024_game_decks.sql) — the boarding
    decision as played, not as planned. 404 mirrors match_detail's
    posture. An empty ``games`` list is a normal answer (Bo1, or a Bo3
    that ended 2-0 with nothing ever resubmitted), never an error.
    """
    match = conn.execute(
        "SELECT deck_id FROM matches WHERE match_id = ?", (match_id,)
    ).fetchone()
    if match is None:
        raise HTTPException(status_code=404, detail=f"No match {match_id}.")

    baseline: Counter = Counter()
    if match["deck_id"]:
        deck_row = conn.execute(
            "SELECT cards_json FROM decks WHERE deck_id = ?", (match["deck_id"],)
        ).fetchone()
        if deck_row is not None:
            baseline = Counter(
                int(g) for g in json.loads(deck_row["cards_json"]).get("maindeck") or []
            )

    games = []
    for row in conn.execute(
        "SELECT game_number, deck_cards_json FROM game_decks "
        "WHERE match_id = ? ORDER BY game_number",
        (match_id,),
    ):
        after = Counter(int(g) for g in json.loads(row["deck_cards_json"]))
        cards_in, cards_out = named_diff(conn, baseline, after)
        games.append(
            SideboardGameOut(
                game_number=row["game_number"],
                cards_in=[SideboardCardOut(**c) for c in cards_in],
                cards_out=[SideboardCardOut(**c) for c in cards_out],
            )
        )
        baseline = after  # game N+1's diff is against game N's own submission

    return SideboardingOut(match_id=match_id, games=games)


@router.get("/api/matches/{match_id}/report", response_model=MatchReportOut, tags=["matches"])
def match_report(match_id: str, conn: Conn) -> MatchReportOut:
    """The post-game report for one match: local, deterministic findings
    computed fresh from already-projected data on every request, never
    stored — see ``review/__init__.py`` for why a stored table would go
    stale in a way a view does not. 404 mirrors ``match_detail``'s
    posture: an id asked for by name that does not exist is a missing
    resource, not an ordinary empty answer.
    """
    if conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"No match {match_id}.")
    view_cache: dict = {}
    consensus_since = _consensus_window(conn)
    report = build_match_report(
        conn, match_id, consensus_since=consensus_since, view_cache=view_cache,
    )
    snap = build_snapshot(conn, match_id, consensus_since=consensus_since, view_cache=view_cache)
    position_track = []
    if snap is not None:
        for t in snap.self_turns:
            pos = turn_position(
                t.turn_number, self_life=t.self_life, opp_life=t.opp_life,
                self_power=t.self_power, opp_power=t.opp_power,
                self_permanents=t.self_permanents, opp_permanents=t.opp_permanents,
                self_hand=t.self_hand, opp_hand=t.opp_hand,
                self_lands=t.self_lands, opp_lands=t.opp_lands,
            )
            if pos is not None:
                position_track.append(
                    PositionPoint(
                        game_number=t.game_number, turn_number=t.turn_number,
                        self_turn_index=t.self_turn_index, index=round(pos.index, 3),
                    )
                )
    return MatchReportOut(
        match_id=match_id,
        summary=_summary_out(build_summary(report)),
        findings=[_finding_out(f) for f in report.findings],
        gaps=[
            ReportGap(analyzer=g.analyzer, reason=g.reason, game_number=g.game_number)
            for g in report.gaps
        ],
        position_track=position_track,
        narrative_available=True,
    )


def _require_match(conn: sqlite3.Connection, match_id: str) -> None:
    if conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"No match {match_id}.")


def _field_context(
    conn: sqlite3.Connection, match_id: str, since: str | None
) -> review_narrative.FieldContext | None:
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
    """
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
         WHERE archetype_key = ? AND (? IS NULL OR event_date >= ?)
         GROUP BY label
        """,
        (key.removeprefix("archetype:"), since, since),
    ).fetchone()
    if agg is None or not agg["matches"]:
        return None
    return review_narrative.FieldContext(
        archetype_label=agg["label"], matches=agg["matches"],
        winrate=agg["matches_won"] / agg["matches"],
        since=since,
    )


def _match_report_narrative_spec(conn: sqlite3.Connection, match_id: str) -> NarrativeSpec:
    def build_context():
        consensus_since = _consensus_window(conn)
        report = build_match_report(conn, match_id, consensus_since=consensus_since)
        snap = build_snapshot(conn, match_id, consensus_since=consensus_since)
        field = _field_context(conn, match_id, consensus_since)
        return review_narrative.build_narrative_context(report, snap, field=field)

    return NarrativeSpec(
        build_context=build_context,
        full_prompt=review_narrative.full_prompt,
        read_stored=lambda: match_narrative_store.read_match_narrative(conn, match_id),
        context_hash=match_narrative_store.context_hash,
        no_context_detail="Nothing to write about for this match yet.",
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
    one, ``'prompt'`` when there is evidence but nothing stored yet, and
    ``'no_report'`` when there is nothing to narrate at all — an empty
    report is an ordinary outcome, not an error. Always a 200.
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

    Sends exactly the evidence ``GET`` on this same path already builds
    and has always served as copyable text (``review/narrative.py`` —
    no prompt text changes for this feature, only who sends it). 503
    with no credential configured (``sensei-top config --set-key``) —
    the dashboard falls back to the copy-prompt path automatically. 502
    wraps whatever the Claude API itself objected to.
    """
    _require_match(conn, match_id)
    spec = _match_report_narrative_spec(conn, match_id)

    def write(prompt: str, completion, context) -> None:
        match_narrative_store.write_match_narrative(
            conn, match_id,
            prose=completion.text, prompt=prompt, model=completion.model,
            context_hash=match_narrative_store.context_hash(context),
            input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd,
        )

    env = narrative_post(conn, spec, write=write)
    return NarrativeResponse(
        status=env.status, narrative=env.content, prompt=env.prompt,
        model=env.who, generated_at=env.when, cost_usd=env.cost_usd, stale=env.stale,
    )
