"""The match list/detail drill-down, the opponent-deck override, the MTGO
deck pick, the post-game report and its narrative — everything under the ``matches`` tag
except the current-match reads, which have their own router.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from sensei_top.answers import PASTED_AUTHOR, match_for
from sensei_top.api.convert import _finding_out, _summary_out
from sensei_top.api.deps import Conn, DeckFilter, SourceFilter, WritableConn
from sensei_top.api.models.common import NarrativeResponse, PastedAnswerIn
from sensei_top.api.models.matches import (
    Match,
    MatchDetail,
    MatchGame,
    MatchReportOut,
    MtgoDeckCandidate,
    MtgoNeedsPick,
    MtgoPick,
    MtgoPickCandidates,
    MtgoPickIn,
    OpponentDeck,
    OpponentDeckCandidate,
    OpponentDeckLabelIn,
    PositionPoint,
    ReportGap,
    SideboardCardOut,
    SideboardGameOut,
    SideboardingOut,
)
from sensei_top.api.routes.narrative import (
    NarrativeSpec,
    check_pasted_length,
    narrative_get,
    narrative_post,
    read_pasted_prose,
    run_authored_write,
)
from sensei_top.api.sql import (
    _attach_zones,
    _cached_corpus_prior,
    _consensus_window,
    _rows,
    match_format,
)
from sensei_top.archetypes import Candidate, rank_candidates
from sensei_top.i18n import _, english
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


def _no_match(match_id: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail=_("No match {id}.").format(id=match_id),
    )


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

    The corpus prior is the match's own format's (``v_match_format``); a
    match no source names a format for gets none.
    """
    if conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone() is None:
        raise _no_match(match_id)
    prior = _cached_corpus_prior(request, conn, match_format(conn, match_id))
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

    An empty label clears the override, so
    the same verb both sets and unsets and the classifier's own answer
    comes back — which is why the response is read from the view rather
    than echoing what was sent.
    """
    label = " ".join(body.label.split())
    if any(character < " " for character in label):
        raise HTTPException(
            status_code=422,
            detail=_("Label may not contain control characters."),
        )
    if conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone() is None:
        raise _no_match(match_id)

    archetype_key = body.archetype_key
    if not label:
        if archetype_key is not None:
            raise HTTPException(
                status_code=422, detail=_("archetype_key requires a non-empty label."),
            )
    elif archetype_key is not None:
        if conn.execute(
            "SELECT 1 FROM archetypes WHERE source = ?", (archetype_key,)
        ).fetchone() is None:
            raise HTTPException(
                status_code=422,
                detail=_("No such archetype {key}.").format(key=repr(archetype_key)),
            )
    elif label != ROGUE_LABEL:
        raise HTTPException(
            status_code=422,
            detail=_("Pick a candidate from GET .../opponent-deck/candidates, or 'Rogue'."),
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


def _match_source(conn: sqlite3.Connection, match_id: str) -> sqlite3.Row | None:
    """The match's ``match_id, self_seat, source`` row, or ``None``."""
    return conn.execute(
        "SELECT match_id, self_seat, source FROM matches WHERE match_id = ?", (match_id,)
    ).fetchone()


def _upsert_mtgo_pick(
    conn: sqlite3.Connection, match_id: str, deck_id: str | None, fmt: str | None
) -> None:
    """Write one pick, replacing any earlier one whole. The caller owns the
    transaction."""
    conn.execute(
        """
        INSERT INTO mtgo_match_pick (match_id, deck_id, format)
             VALUES (?, ?, ?)
        ON CONFLICT (match_id) DO UPDATE SET
             deck_id = excluded.deck_id,
             format = excluded.format,
             updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        (match_id, deck_id, fmt),
    )


def _pick_problem(
    match: sqlite3.Row, deck_id: str | None, fmt: str | None, mtgo_deck_ids: set[str]
) -> str | None:
    """Why a pick for an existing match cannot be written: ``"arena"``,
    ``"empty"`` or ``"unknown_deck"``, checked in that order; ``None`` when it
    can. Each route words and codes the reason itself."""
    if match["source"] != "mtgo":
        return "arena"
    if deck_id is None and fmt is None:
        return "empty"
    if deck_id is not None and deck_id not in mtgo_deck_ids:
        return "unknown_deck"
    return None


def _require_mtgo_match(conn: sqlite3.Connection, match_id: str) -> sqlite3.Row:
    """The match's row, or 404 for no such match and 400 for an Arena one,
    whose deck the log already names."""
    row = _match_source(conn, match_id)
    if row is None:
        raise _no_match(match_id)
    if row["source"] != "mtgo":
        raise HTTPException(
            status_code=400,
            detail=_("Only an MTGO match takes a deck pick; Arena's log names its deck."),
        )
    return row


def _mtgo_decks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every deck an MTGO deck file produced.

    ``decks`` has no source column. Arena only writes a ``decks`` row for a
    deck some match played (``projector/matches.py::project``), and no MTGO
    match ever sets ``matches.deck_id``, so a deck no match carries is an
    MTGO deck. Picking one never changes that, because a pick lives in
    ``mtgo_match_pick`` and ``v_match_deck``, not in ``matches``.
    """
    return conn.execute(
        """
        SELECT d.deck_id, d.name, d.format, d.cards_json, d.last_seen
          FROM decks d
         WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.deck_id = d.deck_id)
        """
    ).fetchall()


def _mtgo_pick(conn: sqlite3.Connection, match_id: str) -> dict[str, Any] | None:
    """The match's pick as ``v_match_deck`` has it, or ``None`` before one."""
    row = conn.execute(
        "SELECT deck_id, format, deck_confirmed FROM v_match_deck WHERE match_id = ?",
        (match_id,),
    ).fetchone()
    if row is None or not row["deck_confirmed"]:
        return None
    return {
        "deck_id": row["deck_id"],
        "format": row["format"],
        "deck_confirmed": True,
    }


def _last_pick_formats(conn: sqlite3.Connection) -> dict[str, str]:
    """``{deck_id: format}`` of the most recent pick that named both."""
    prefill: dict[str, str] = {}
    for row in conn.execute(
        """
        SELECT deck_id, format FROM mtgo_match_pick
         WHERE deck_id IS NOT NULL AND format IS NOT NULL
         ORDER BY updated_at DESC, match_id
        """
    ):
        prefill.setdefault(row["deck_id"], row["format"])
    return prefill


def _format_prefill(
    deck: sqlite3.Row, last_picks: dict[str, str], inferred: str | None
) -> tuple[str | None, str | None]:
    """``(format, source)`` to pre-fill for a deck: the deck store's, else the
    last one confirmed for the deck, else ``inferred``, else ``(None, None)``."""
    if deck["format"]:
        return deck["format"], "deck_store"
    if deck["deck_id"] in last_picks:
        return last_picks[deck["deck_id"]], "last_pick"
    if inferred is not None:
        return inferred, "inferred"
    return None, None


# How many card names a candidate carries; enough to tell decks apart.
_CANDIDATE_CARD_NAMES = 5
_LAND = re.compile(r"\bLand\b")
_BASIC_LAND = re.compile(r"\bBasic\b")


def _card_names(conn: sqlite3.Connection, cards: dict[str, Any], played: set[int]) -> list[str]:
    """A few of a deck's card names, for the picker to show beside its name.

    Sorted by ``(front face is a land, not played in this match, -maindeck
    copies, name)``: spells before lands, because a land says little about a
    deck; within each group the cards the user played in this match first, so
    an overlap is visible at a glance; then more maindeck copies, then name.
    The land test reads the front face's type line only (the part before
    `` // ``), so a spell//land double-faced card is a spell. A sideboard-only
    card is kept, with zero copies, so it follows the maindeck cards of the
    same group: a deck's identity hashes its maindeck, so two candidates
    always differ in their maindeck, and that is what tells them apart. Basic
    lands are left out, and a card whose ``cards`` row is missing has no name
    to show. ``unresolved`` is ignored: those copies have no name here.
    """
    maindeck = Counter(cards.get("maindeck", []))
    held = maindeck.keys() | set(cards.get("sideboard", []))
    if not held:
        return []
    names = {
        row["grp_id"]: row
        for row in conn.execute(
            "SELECT grp_id, name, type_line FROM cards WHERE grp_id IN "
            f"({','.join('?' * len(held))})",
            list(held),
        )
    }
    entries: list[tuple[bool, bool, int, str]] = []
    for grp_id in held:
        row = names.get(grp_id)
        if row is None:
            continue
        front = (row["type_line"] or "").split(" // ")[0]
        is_land = bool(_LAND.search(front))
        if is_land and _BASIC_LAND.search(front):
            continue
        entries.append((is_land, grp_id not in played, -maindeck[grp_id], row["name"]))
    entries.sort()
    # Two printings of one card are one name.
    return list(dict.fromkeys(name for *_, name in entries))[:_CANDIDATE_CARD_NAMES]


@router.get(
    "/api/matches/{match_id}/mtgo-pick/candidates",
    response_model=MtgoPickCandidates,
    tags=["matches"],
)
def mtgo_pick_candidates(match_id: str, conn: Conn) -> dict[str, Any]:
    """The MTGO decks to offer for this match, the best match first.

    A deck's score is how many of the distinct cards the user played in this
    match (``card_events`` on the user's seat, resolved to an Arena
    ``grp_id``) its list holds, maindeck or sideboard. A card Arena lacks
    never resolves, so it counts for nothing on either side; a deck that
    matches nothing is still listed, last, because the user may know better
    than the overlap. Ties break on the deck's newest file, then its id.

    The format pre-fill is the format MTGO's deck store files the deck
    under, else the last one confirmed for the same deck, else the format
    inferred for this match from the cards it revealed
    (``match_format_inference``), else none. The inferred
    step reads the inference itself, not ``v_match_format``, so a match the
    user already picked a format for still offers its inference to a deck
    the first two steps miss. ``format_prefill_source`` says which step
    answered. Each candidate also carries a few card names
    (``_card_names``). Nothing is
    written, and the pick is never inferred from this ranking: the user
    always confirms.
    """
    match = _require_mtgo_match(conn, match_id)
    played = {
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT grp_id FROM card_events
             WHERE match_id = ? AND seat = ? AND grp_id IS NOT NULL
            """,
            (match_id, match["self_seat"]),
        )
    }
    prefill = _last_pick_formats(conn)
    inferred_row = conn.execute(
        "SELECT format FROM match_format_inference WHERE match_id = ?", (match_id,)
    ).fetchone()
    inferred = inferred_row["format"] if inferred_row is not None else None

    ranked: list[tuple[int, str, str, MtgoDeckCandidate]] = []
    for deck in _mtgo_decks(conn):
        cards = json.loads(deck["cards_json"])
        held = set(cards.get("maindeck", [])) | set(cards.get("sideboard", []))
        fill, fill_source = _format_prefill(deck, prefill, inferred)
        candidate = MtgoDeckCandidate(
            deck_id=deck["deck_id"],
            name=deck["name"],
            cards_matched=len(played & held),
            format_prefill=fill,
            format_prefill_source=fill_source,
            card_names=_card_names(conn, cards, played),
        )
        ranked.append(
            (candidate.cards_matched, deck["last_seen"] or "", deck["deck_id"], candidate)
        )
    # Most cards first, then the newest file, then the id for a stable order.
    ranked.sort(key=lambda r: r[2])
    ranked.sort(key=lambda r: r[1], reverse=True)
    ranked.sort(key=lambda r: r[0], reverse=True)

    return {
        "cards_seen": len(played),
        "candidates": [r[3] for r in ranked],
        "current": _mtgo_pick(conn, match_id),
    }


@router.put(
    "/api/matches/{match_id}/mtgo-pick",
    response_model=MtgoPick,
    tags=["matches"],
)
def set_mtgo_pick(match_id: str, body: MtgoPickIn, conn: WritableConn) -> dict[str, Any]:
    """Confirm an MTGO match's deck and format. 400 for an Arena match, for a
    deck that is not one of the candidates, and for a body with neither field.

    The body replaces any earlier pick whole, so a PUT with only a format
    drops a deck confirmed before. There is no way back to "unconfirmed":
    the user always confirms, and a pick that said something can only be
    corrected, not withdrawn. The response is read from the view the rest of
    the app reads, not echoed.
    """
    match = _require_mtgo_match(conn, match_id)
    problem = _pick_problem(
        match, body.deck_id, body.format, {deck["deck_id"] for deck in _mtgo_decks(conn)}
    )
    if problem == "empty":
        raise HTTPException(status_code=400, detail=_("Pick a deck, a format, or both."))
    if problem == "unknown_deck":
        raise HTTPException(
            status_code=400,
            detail=_("Pick a deck from GET .../mtgo-pick/candidates."),
        )

    conn.execute("BEGIN")
    try:
        _upsert_mtgo_pick(conn, match_id, body.deck_id, body.format)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    pick = _mtgo_pick(conn, match_id)
    assert pick is not None  # the row was just written
    return pick


@router.get("/api/mtgo/needs-pick", response_model=list[MtgoNeedsPick], tags=["matches"])
def mtgo_needs_pick(conn: Conn) -> list[dict[str, Any]]:
    """MTGO matches with no pick yet, newest first, for the Home queue. A
    match with a pick of only a format has been answered and is not listed."""
    return _rows(
        conn,
        """
        SELECT m.match_id, m.opponent_name, m.started_at, m.ended_at,
               m.result, m.games_won, m.games_lost
          FROM matches m
          JOIN v_match_deck v ON v.match_id = m.match_id
         WHERE m.source = 'mtgo' AND v.deck_confirmed = 0
         ORDER BY m.started_at DESC, m.match_id
        """,
    )


# The four per-match split columns, shared by the list and the detail so a
# match reads the same on both. Each is NULL unless the match is a best of
# three; a game that has not finished (no win/loss/draw) is not counted.
_BO3_SPLIT_COLUMNS = """m.best_of,
               CASE WHEN m.best_of = 3 THEN
                 (SELECT g.result FROM games g
                   WHERE g.match_id = m.match_id AND g.game_number = 1
                     AND g.result IN ('win', 'loss', 'draw'))
               END AS game1_result,
               CASE WHEN m.best_of = 3 THEN
                 (SELECT COUNT(*) FROM games g
                   WHERE g.match_id = m.match_id AND g.game_number >= 2
                     AND g.result = 'win')
               END AS postboard_won,
               CASE WHEN m.best_of = 3 THEN
                 (SELECT COUNT(*) FROM games g
                   WHERE g.match_id = m.match_id AND g.game_number >= 2
                     AND g.result = 'loss')
               END AS postboard_lost,"""


@router.get("/api/matches", response_model=list[Match], tags=["matches"])
def matches(
    conn: Conn,
    deck_id: DeckFilter = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    source: SourceFilter = "arena",
) -> list[dict[str, Any]]:
    sql = f"""
        SELECT m.match_id, m.source, m.event_id, md.deck_id, d.name AS deck_name,
               m.opponent_name, m.started_at, m.ended_at, m.result, m.games_won, m.games_lost,
               {_BO3_SPLIT_COLUMNS}
               o.opponent_label, o.opponent_key, o.opponent_source,
               o.opponent_confidence, o.opponent_cards_seen, o.opponent_colors,
               (SELECT r.constructed_class FROM rank_snapshot r
                 WHERE m.source = 'arena' AND r.observed_at <= m.started_at
                 ORDER BY r.observed_at DESC LIMIT 1) AS rank_class,
               (SELECT r.constructed_level FROM rank_snapshot r
                 WHERE m.source = 'arena' AND r.observed_at <= m.started_at
                 ORDER BY r.observed_at DESC LIMIT 1) AS rank_level,
               f.format
          FROM matches m
          JOIN v_match_deck md ON md.match_id = m.match_id
          LEFT JOIN v_match_format f ON f.match_id = m.match_id
          LEFT JOIN decks d ON d.deck_id = md.deck_id
          LEFT JOIN v_match_opponent o ON o.match_id = m.match_id
    """
    clauses: list[str] = []
    params: list[Any] = []
    if deck_id:
        clauses.append("md.deck_id = ?")
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
        f"""
        SELECT m.match_id, m.source, m.event_id, md.deck_id, d.name AS deck_name,
               m.opponent_name, m.self_seat, m.started_at, m.ended_at, m.result,
               m.games_won, m.games_lost,
               {_BO3_SPLIT_COLUMNS}
               o.opponent_label, o.opponent_key, o.opponent_source,
               o.opponent_confidence, o.opponent_cards_seen, o.opponent_colors,
               (SELECT r.constructed_class FROM rank_snapshot r
                 WHERE m.source = 'arena' AND r.observed_at <= m.started_at
                 ORDER BY r.observed_at DESC LIMIT 1) AS rank_class,
               (SELECT r.constructed_level FROM rank_snapshot r
                 WHERE m.source = 'arena' AND r.observed_at <= m.started_at
                 ORDER BY r.observed_at DESC LIMIT 1) AS rank_level,
               f.format
          FROM matches m
          JOIN v_match_deck md ON md.match_id = m.match_id
          LEFT JOIN v_match_format f ON f.match_id = m.match_id
          LEFT JOIN decks d ON d.deck_id = md.deck_id
          LEFT JOIN v_match_opponent o ON o.match_id = m.match_id
         WHERE m.match_id = ?
        """,
        (match_id,),
    ).fetchone()
    if match is None:
        raise _no_match(match_id)

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
        "SELECT deck_id FROM v_match_deck WHERE match_id = ?", (match_id,)
    ).fetchone()
    if match is None:
        raise _no_match(match_id)

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
        raise _no_match(match_id)
    view_cache: dict = {}
    consensus_since = _consensus_window(conn, match_format(conn, match_id))
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
        raise _no_match(match_id)


def _field_context(
    conn: sqlite3.Connection, match_id: str, fmt: str | None, since: str | None
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
    return review_narrative.FieldContext(
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
        return review_narrative.build_narrative_context(report, snap, field=field)

    return NarrativeSpec(
        build_context=build_context,
        full_prompt=review_narrative.full_prompt,
        copied_prompt=lambda context: review_narrative.copied_prompt(
            context, answer_for=match_for(match_id),
            context_hash=match_narrative_store.context_hash(context),
        ),
        read_stored=lambda: match_narrative_store.read_match_narrative(conn, match_id),
        context_hash=match_narrative_store.context_hash,
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
    evidence but nothing stored yet, and
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

    Sends ``full_prompt`` (``review/narrative.py``): the evidence ``GET``
    on this same path builds, without the answer contract that ``GET``'s
    ``copied_prompt`` adds, since the reply is prose. 503
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

    run_authored_write(conn, lambda: match_narrative_store.write_match_narrative(
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
