"""The break read: what to do during a Bo3 intermission, between the game
that just ended and the next one's first state message
(``projector/live_state.py``'s ``Intermission``) — a sibling to
``table/hand_read.py`` and ``table/keep.py`` for the one window in a match
where nothing is happening on the board at all.

``build_break_read`` names the opponent from whatever has been revealed so
far (a manual pick first, then the same rule-engine/corpus read
``classify_matches`` uses per match, extracted as ``classify_seen`` so this
can run on a name set gathered at request time rather than waiting on
``project()``), finds the stored matchup brief for that archetype — or the
closest thing to one already written for this deck — and surfaces what was
actually boarded the last time this deck faced it. Nothing here writes
anything: a brief is authored by ``sensei-top brief --import`` or the
guide's own narrative, never by this module (AGENTS.md non-negotiable #5).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass

from sensei_top.archetypes.classify import (
    Candidate,
    _card_colors_by_name,
    _load_definitions,
    classify_seen,
    format_key,
    live_opponent_colors,
    rank_candidates,
)
from sensei_top.archetypes.corpus import CorpusPrior, build_prior
from sensei_top.brief.narrative import full_prompt
from sensei_top.brief.store import Brief, is_stale, list_hash, read_brief
from sensei_top.guide.deck import DeckIdentity, list_identities
from sensei_top.projector.live_state import LiveState
from sensei_top.table.boarding import named_diff

MAX_ALTERNATIVES = 3
MAX_PAST_BOARDING = 3


@dataclass(frozen=True, slots=True)
class OpponentRead:
    """Who the opponent is, per ``build_break_read``'s step 2 precedence."""

    label: str
    archetype_key: str | None
    confidence: str  # 'high' | 'medium' | 'low'
    source: str  # 'manual' | 'live'


@dataclass(frozen=True, slots=True)
class AlternativePlan:
    """One candidate archetype with a stored brief, offered when there is no
    exact plan for the opponent actually named (or none has been named at
    all) — best fit first."""

    archetype_key: str
    label: str
    confidence: str
    fit: float
    brief: Brief


@dataclass(frozen=True, slots=True)
class PastBoardingCard:
    """One card from a past sideboard swap (``table/boarding.py``'s
    ``named_diff``), flagged against the deck's *current* 75 — the same
    check ``guide/plans.py::validate_plans`` runs, applied to what was
    actually played rather than to a written plan. Never dropped, only
    flagged (rule 4): a card since cut is still part of what happened."""

    grp_id: int
    card: str | None
    n: int
    in_current_75: bool


@dataclass(frozen=True, slots=True)
class PastBoardingGame:
    game_number: int
    board_in: tuple[PastBoardingCard, ...]
    board_out: tuple[PastBoardingCard, ...]
    result: str | None
    result_reason: str | None


@dataclass(frozen=True, slots=True)
class PastBoarding:
    """One prior completed match of this deck identity against this
    archetype, and what was actually boarded in it — shown as "what you
    boarded last time", never as advice (step 5b)."""

    match_id: str
    played_at: str | None
    games: tuple[PastBoardingGame, ...]


@dataclass(frozen=True, slots=True)
class BreakRead:
    """Everything the Bo3 break card needs, built once per poll and cached
    by the API layer (``api/sql.py``) since the board never moves during a
    break — see this module's docstring and S4's "Time budget" measurement."""

    game_number: int  # the game that just ended
    next_game: int
    won: bool | None
    reason: str | None
    opponent: OpponentRead | None
    cards_seen: int
    plan: Brief | None
    plan_basis: str | None  # 'exact' | 'closest' | None
    plan_archetype_label: str | None
    stale: bool
    alternatives: tuple[AlternativePlan, ...]
    past_boarding: tuple[PastBoarding, ...]
    prompt: str | None
    deck_key: str | None


def opponent_seen_names(conn: sqlite3.Connection, match_id: str, live: LiveState) -> list[str]:
    """Step 1: the opponent's revealed card names, pooling ``card_events``
    (whatever ``project()`` has already caught up to) with the live replay's
    own revealed zones (``live.zone_cards`` — non-hand, ``grp_id`` not null)
    so a break before game 3 covers both games even when projection has
    only reached game 1. Public (not ``_``-prefixed): the API layer's cache
    wrapper needs this same name set for its own cache key (S4 step 7) and
    must not pay for the query twice, so it calls this directly and hands
    the result back to ``build_break_read`` via its own ``names`` parameter.

    Deliberately not run through ``_seen_forms``: ``classify_seen`` and
    ``rank_candidates`` both normalize their own ``names``/``seen_names``
    input, so this only has to gather raw names once.
    """
    rows = conn.execute(
        """
        SELECT c.name
          FROM card_events ce
          JOIN matches m ON m.match_id = ce.match_id
          JOIN cards   c ON c.grp_id   = ce.grp_id
         WHERE ce.match_id = ?
           AND ce.seat = m.opponent_seat
           AND ce.grp_id IS NOT NULL
           AND instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                     'Token') = 0
        """,
        (match_id,),
    )
    names = {row["name"] for row in rows}

    if live.opponent_seat is not None:
        grp_ids = {
            zc.grp_id
            for zc in live.zone_cards
            if zc.seat == live.opponent_seat and zc.zone != "hand" and zc.grp_id is not None
        }
        if grp_ids:
            placeholders = ",".join("?" for _ in grp_ids)
            rows = conn.execute(
                f"SELECT name FROM cards WHERE grp_id IN ({placeholders})", tuple(grp_ids)
            )
            names.update(row["name"] for row in rows)

    return sorted(names)


def _load_caches(
    conn: sqlite3.Connection, caches: dict
) -> tuple[dict[str, dict[str, list]], dict[str, frozenset[str]], CorpusPrior | None]:
    """Lazily fills ``caches`` — a plain dict the API layer owns and reuses
    across polls (S4 step 7) — with the same definitions/colours/corpus-prior
    loads ``classify_matches`` pays once per full reclassification, so a 1 Hz
    break poll during a match doesn't repeat a full-table scan on every beat."""
    if "definitions" not in caches:
        caches["definitions"] = _load_definitions(conn)
    if "colors_by_name" not in caches:
        caches["colors_by_name"] = _card_colors_by_name(conn)
    if "prior" not in caches:
        caches["prior"] = build_prior(conn)
    return caches["definitions"], caches["colors_by_name"], caches["prior"]


def _resolve_opponent(
    conn: sqlite3.Connection,
    match_id: str,
    names: list[str],
    colors: str,
    cards_seen: int,
    *,
    fmt: str | None,
    definitions: dict[str, dict[str, list]],
    colors_by_name: dict[str, frozenset[str]],
    prior: CorpusPrior | None,
) -> OpponentRead | None:
    """Step 2's precedence: a manual pick first — the user's own correction
    of their own match, which always wins — then the same rule-engine/corpus
    read ``classify_matches`` uses per match (``classify_seen``), run here on
    the name set gathered at request time instead of waiting on
    ``project()``. ``archetype_key`` mirrors ``v_match_opponent``
    (migration 035): both the rule engine's 'archetype' and 'fallback'
    methods get an ``archetype:`` prefixed key there, so this sets it from
    ``verdict.key`` regardless of ``verdict.method`` too."""
    override = conn.execute(
        "SELECT label, archetype_key FROM opponent_deck_override WHERE match_id = ?",
        (match_id,),
    ).fetchone()
    if override is not None:
        return OpponentRead(
            label=override["label"],
            archetype_key=override["archetype_key"],
            confidence="high",
            source="manual",
        )

    if fmt is None or not names:
        return None
    verdict = classify_seen(
        names, colors, cards_seen, fmt=fmt, definitions=definitions,
        colors_by_name=colors_by_name, prior=prior,
    )
    if verdict is None:
        return None
    return OpponentRead(
        label=verdict.label, archetype_key=verdict.key,
        confidence=verdict.confidence, source="live",
    )


def _closest_alternatives(
    conn: sqlite3.Connection,
    match_id: str,
    identity: DeckIdentity,
    names: list[str],
    exclude_key: str | None,
    *,
    colors_by_name: dict[str, frozenset[str]],
    prior: CorpusPrior | None,
) -> list[AlternativePlan]:
    """Step 5: up to ``MAX_ALTERNATIVES`` already-written plans for a
    *different* archetype than the one actually named, best fit first.
    ``rank_candidates`` only guarantees a globally fit-sorted return when its
    own corpus folding runs (its docstring) — otherwise archetypes and
    fallbacks are each their own internally-sorted group — so this re-sorts
    its filtered subset explicitly rather than trusting the raw order."""
    candidates: list[Candidate] = rank_candidates(
        conn, match_id, colors_by_name=colors_by_name, prior=prior, seen_names=names,
    )
    out: list[AlternativePlan] = []
    for c in candidates:
        if c.confidence == "none" or c.key == exclude_key:
            continue
        brief = read_brief(conn, identity.key, c.key)
        if brief is None:
            continue
        out.append(AlternativePlan(
            archetype_key=c.key, label=c.label, confidence=c.confidence, fit=c.fit, brief=brief,
        ))
    out.sort(key=lambda a: -a.fit)
    return out[:MAX_ALTERNATIVES]


def _flag_card(entry: dict, current_75: set[int]) -> PastBoardingCard:
    """One ``named_diff`` entry, flagged against the deck's *current* 75 —
    never dropped, only flagged (rule 4): a card since cut is still part of
    what actually happened in that past game."""
    return PastBoardingCard(
        grp_id=entry["grp_id"], card=entry["card"], n=entry["n"],
        in_current_75=entry["grp_id"] in current_75,
    )


def _past_boarding(
    conn: sqlite3.Connection, identity: DeckIdentity, archetype_key: str, current_match_id: str
) -> list[PastBoarding]:
    """Step 5b: what this deck identity actually boarded, the last few times
    it faced this archetype — recorded fact ("what you boarded last time"),
    never advice. Each boarded game diffs against that *past* match's own
    game-1 maindeck (``decks.cards_json``, since ``game_decks`` never carries
    a game-1 row) rather than a chained per-game baseline — deliberately
    different from ``/api/matches/{id}/sideboarding``'s own chained diff,
    which answers "what changed since the last game" rather than "what does
    this game's 75 look like versus game 1"."""
    if not identity.deck_ids:
        return []
    current_75 = {
        grp_id
        for key in ("maindeck", "sideboard")
        for grp_id in (identity.current_cards or {}).get(key) or []
    }
    placeholders = ",".join("?" for _ in identity.deck_ids)
    rows = conn.execute(
        f"""
        SELECT m.match_id, m.deck_id, m.started_at
          FROM matches m
          JOIN v_match_opponent o ON o.match_id = m.match_id
         WHERE m.deck_id IN ({placeholders})
           AND m.source = 'arena'
           AND m.result IS NOT NULL AND m.result != 'incomplete'
           AND m.match_id != ?
           AND o.opponent_key = ?
           AND EXISTS (SELECT 1 FROM game_decks gd WHERE gd.match_id = m.match_id)
         ORDER BY m.started_at DESC
        """,
        (*identity.deck_ids, current_match_id, f"archetype:{archetype_key}"),
    ).fetchall()

    results: list[PastBoarding] = []
    for row in rows:
        if len(results) >= MAX_PAST_BOARDING:
            break
        deck_row = conn.execute(
            "SELECT cards_json FROM decks WHERE deck_id = ?", (row["deck_id"],)
        ).fetchone()
        if deck_row is None:
            continue
        try:
            own_cards = json.loads(deck_row["cards_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        baseline = Counter(own_cards.get("maindeck") or [])

        game_decks = conn.execute(
            """
            SELECT game_number, deck_cards_json FROM game_decks
             WHERE match_id = ? ORDER BY game_number
            """,
            (row["match_id"],),
        ).fetchall()
        game_results = {
            g["game_number"]: (g["result"], g["result_reason"])
            for g in conn.execute(
                "SELECT game_number, result, result_reason FROM games WHERE match_id = ?",
                (row["match_id"],),
            )
        }

        games: list[PastBoardingGame] = []
        for gd in game_decks:
            try:
                after = Counter(json.loads(gd["deck_cards_json"]))
            except (json.JSONDecodeError, TypeError):
                continue
            cards_in, cards_out = named_diff(conn, baseline, after)
            result, result_reason = game_results.get(gd["game_number"], (None, None))
            games.append(PastBoardingGame(
                game_number=gd["game_number"],
                board_in=tuple(_flag_card(c, current_75) for c in cards_in),
                board_out=tuple(_flag_card(c, current_75) for c in cards_out),
                result=result,
                result_reason=result_reason,
            ))
        if games:
            results.append(PastBoarding(
                match_id=row["match_id"], played_at=row["started_at"], games=tuple(games)
            ))
    return results


def build_break_read(
    conn: sqlite3.Connection,
    match_id: str,
    deck_id: str | None,
    live: LiveState,
    *,
    caches: dict,
    names: list[str] | None = None,
) -> BreakRead | None:
    """Everything the Bo3 break card needs — this module's docstring and
    S4's seven numbered steps — or ``None`` when the match is not on a break
    right now, the one input every later step depends on.

    ``caches`` is a plain dict the caller owns across polls (S4 step 7): a
    request-scoped or ``app.state``-scoped cache. ``names`` lets a caller
    that already paid for ``opponent_seen_names`` (the API layer's own cache
    key) hand the result back in rather than this function querying it a
    second time on every cache miss; omitted, this computes it itself.
    """
    if live.intermission is None:
        return None
    intermission = live.intermission

    if names is None:
        names = opponent_seen_names(conn, match_id, live)
    colors, cards_seen = live_opponent_colors(conn, names)

    match_row = conn.execute(
        """
        SELECT m.event_id, d.format AS deck_format
          FROM matches m LEFT JOIN decks d ON d.deck_id = m.deck_id
         WHERE m.match_id = ?
        """,
        (match_id,),
    ).fetchone()
    fmt = (
        format_key(match_row["deck_format"], match_row["event_id"])
        if match_row is not None else None
    )

    definitions, colors_by_name, prior = _load_caches(conn, caches)
    opponent = _resolve_opponent(
        conn, match_id, names, colors, cards_seen,
        fmt=fmt, definitions=definitions, colors_by_name=colors_by_name, prior=prior,
    )
    chosen_key = opponent.archetype_key if opponent is not None else None

    identity = next(
        (i for i in list_identities(conn) if deck_id is not None and deck_id in i.deck_ids), None,
    )

    alternatives: list[AlternativePlan] = []
    if identity is not None:
        alternatives = _closest_alternatives(
            conn, match_id, identity, names, chosen_key,
            colors_by_name=colors_by_name, prior=prior,
        )

    exact_brief = (
        read_brief(conn, identity.key, chosen_key)
        if identity is not None and chosen_key is not None
        else None
    )

    plan: Brief | None
    plan_basis: str | None
    plan_archetype_label: str | None
    stale = False
    if exact_brief is not None:
        plan = exact_brief
        plan_basis = "exact"
        plan_archetype_label = opponent.label if opponent is not None else None
        stale = is_stale(
            conn, exact_brief,
            current_list_hash=list_hash(identity.current_cards) if identity is not None else None,
        )
    elif alternatives:
        first = alternatives[0]
        plan = first.brief
        plan_basis = "closest"
        plan_archetype_label = first.label
        stale = is_stale(
            conn, first.brief,
            current_list_hash=list_hash(identity.current_cards) if identity is not None else None,
        )
    else:
        plan = None
        plan_basis = None
        plan_archetype_label = None

    prompt: str | None = None
    if identity is not None and chosen_key is not None and exact_brief is None:
        # Step 6: the prompt to write the plan the opponent actually named
        # doesn't have yet. This is the same call
        # ``api/routes/current_match.py``'s ``_brief_response`` makes for
        # the live tab's own currently-known opponent — duplicated here
        # (rather than imported) because ``table/`` must never import from
        # ``api/``. Memoized per match in ``caches``: ``full_prompt``'s
        # ``format_resets`` scan and personal-rate read measured ~1s on the
        # real database, and nothing it reads moves while this match is
        # still being played — only past, completed matches and the corpus
        # feed it, and a corpus refresh resets ``caches`` wholesale (the API
        # layer's own ``_cached_break_read``).
        label = opponent.label if opponent is not None else None
        prompts = caches.setdefault("prompts", {})
        prompt_key = (match_id, identity.key, list_hash(identity.current_cards), chosen_key, label)
        if prompt_key not in prompts:
            built = full_prompt(conn, identity, chosen_key, label)
            prompts[prompt_key] = built[0] if built is not None else None
        prompt = prompts[prompt_key]

    past_boarding: list[PastBoarding] = []
    if identity is not None:
        # Step 5b: applies to the named archetype, or the top alternative
        # when none was named.
        boarding_key = chosen_key or (alternatives[0].archetype_key if alternatives else None)
        if boarding_key is not None:
            # Memoized per match like the prompt above: every row it reads
            # belongs to a *past*, completed match, which a reprojection
            # during this one's break cannot change.
            boardings = caches.setdefault("past_boarding", {})
            boarding_cache_key = (match_id, identity.key, boarding_key)
            if boarding_cache_key not in boardings:
                boardings[boarding_cache_key] = _past_boarding(
                    conn, identity, boarding_key, match_id
                )
            past_boarding = boardings[boarding_cache_key]

    return BreakRead(
        game_number=intermission.game_number,
        next_game=intermission.game_number + 1,
        won=intermission.won,
        reason=intermission.reason,
        opponent=opponent,
        cards_seen=cards_seen,
        plan=plan,
        plan_basis=plan_basis,
        plan_archetype_label=plan_archetype_label,
        stale=stale,
        alternatives=tuple(alternatives),
        past_boarding=tuple(past_boarding),
        prompt=prompt,
        deck_key=identity.key if identity is not None else None,
    )
