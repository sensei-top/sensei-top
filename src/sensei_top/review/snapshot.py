"""One read of the database per match, shared by every analyzer.

Every analyzer in ``analyzers/`` is a pure function of the ``MatchSnapshot``
built here, which keeps them testable without a database and keeps the
whole report at a fixed number of queries however many analyzers exist.
Which other modules of this package query the database: docs/review.md,
"The match report, and its optional narrative".
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from sensei_top.archetypes import rank_candidates
from sensei_top.archetypes.classify import (
    Candidate,
    Verdict,
    card_colors_by_name,
    card_colors_of,
    choose,
    load_definitions,
    seen_forms,
)
from sensei_top.formats import arena_format
from sensei_top.metagame.matchup import ranked_field_matchup
from sensei_top.review import effects
from sensei_top.review.consensus import ArchetypeConsensus, build_consensus
from sensei_top.review.findings import GameFacts


@dataclass(frozen=True, slots=True)
class SelfTurnRow:
    """One row of ``v_self_turns`` — one of our own player-turns, indexed by
    ``self_turn_index`` rather than Arena's shared ``turn_number`` counter.

    ``self_power``/``opp_power`` and ``opp_lands`` are not in ``turns``
    itself (the projector has no ``opp_lands`` column at all, and power is
    per-object, not a turn-level count) — both are aggregated here from
    ``turn_zones``, one query per match, so every analyzer reasoning about
    the position index gets them without a read of its own.
    """

    game_number: int
    turn_number: int
    self_turn_index: int | None
    self_life: int | None
    opp_life: int | None
    self_hand: int | None
    opp_hand: int | None
    self_lands: int | None
    opp_lands: int | None
    self_permanents: int | None
    opp_permanents: int | None
    self_power: int | None
    opp_power: int | None
    self_library: int | None
    self_graveyard: int | None
    self_open_mana: int | None
    prev_self_permanents: int | None


@dataclass(frozen=True, slots=True)
class CardPlay:
    """One ``CastSpell``/``Resolve`` card event, from ``v_card_events`` —
    used for both ``opponent_plays`` and ``self_plays``. ``card_name`` is
    ``None`` when the card was hidden from us — a spell we saw resolve but
    never identified, not a parsing gap."""

    game_number: int
    turn_number: int
    grp_id: int | None
    card_name: str | None
    category: str | None


@dataclass(frozen=True, slots=True)
class DeckLandRatio:
    """The maindeck's own land ratio, from ``v_deck_land_count``.
    ``unnamed_count`` above zero means the deck is not fully named yet —
    every caller must treat that as "unknown", never compute a ratio from
    a partial list. It also counts an MTGO deck's unresolved maindeck copies
    (``v_deck_land_count.unresolved_count``): a list with copies missing is
    as partial as one with a card still unnamed."""

    maindeck_size: int
    land_count: int
    unnamed_count: int


@dataclass(frozen=True, slots=True)
class OwnCard:
    """One maindeck card of our own, with the effect tags ``role``-assignment
    reasons about. Unlike the opponent's consensus list, this comes from our
    *exact* decklist (``decks.cards_json``), not a field average — strictly
    better information whenever it is available."""

    grp_id: int
    name: str | None
    type_line: str | None
    count: int
    tags: frozenset[str] | str  # effects.classify's output; "unknown" per rule 4


@dataclass(frozen=True, slots=True)
class DamageRow:
    """One ``damage_events`` row, seat-mapped like ``v_card_events``.
    ``source_is_self``/``target_is_self`` are ``None`` when unresolvable —
    a hidden source, or self_seat itself unresolved."""

    game_number: int
    turn_number: int | None
    amount: int
    damage_type: int | None
    source_instance_id: int | None
    source_grp_id: int | None
    source_is_self: bool | None
    target_instance_id: int | None
    target_is_self: bool | None


@dataclass(frozen=True, slots=True)
class LifeRow:
    game_number: int
    turn_number: int | None
    seat_is_self: bool | None
    delta: int
    affector_grp_id: int | None


@dataclass(frozen=True, slots=True)
class CounteredCard:
    """One ``Countered`` zone transfer, from ``v_card_events`` — a card that
    never resolved. ``is_self`` is whose spell it was, not who cast the
    counter; ``card_name`` is ``None`` when the countered card itself was
    never identified (its owner's hidden card, countered before we ever
    saw it resolve)."""

    game_number: int
    turn_number: int | None
    is_self: bool | None
    card_name: str | None


@dataclass(frozen=True, slots=True)
class PersonalMatchup:
    """Our own record in this exact matchup (same deck, same opponent
    archetype key), excluding the match this snapshot is itself for —
    otherwise a report would cite the very game it is reporting on as part
    of its own baseline."""

    matches_completed: int
    matches_won: int
    games_won: int
    games_lost: int


@dataclass(frozen=True, slots=True)
class FieldMatchup:
    """The field's own numbers for this archetype pairing, from exactly one
    tier — never blended across tiers, which is what makes ``n`` here a real
    sample size, not an inflated one. ``tier`` names which one, chosen by
    ``metagame.matchup.ranked_field_matchup``'s walk."""

    n: int
    matches_won: int
    matches_lost: int
    tier: str


@dataclass(frozen=True, slots=True)
class MatchSnapshot:
    match_id: str
    deck_id: str | None
    self_seat: int | None
    result: str | None
    games: tuple[GameFacts, ...]
    self_turns: tuple[SelfTurnRow, ...]
    # (game_number, turn_number) -> lands played that turn
    lands_played: dict[tuple[int, int], int]
    # (game_number, turn_number) -> (hand_lands, named_cards) at end of that turn
    hand_lands: dict[tuple[int, int], tuple[int, int]]
    # game_number -> self_hand size at end of turn 1 (from `turns`, not v_self_turns —
    # turn 1 belongs to whichever seat was on the play, so it may not be "our" turn)
    turn1_hand_size: dict[int, int | None]
    deck_land_ratio: DeckLandRatio | None
    opponent_plays: tuple[CardPlay, ...]
    self_plays: tuple[CardPlay, ...]
    # (turn_count, games, games_won) for this deck, from v_deck_game_length
    deck_game_length: tuple[tuple[int, int, int], ...]
    # (on_play, games_won, games_lost) for this deck, from v_play_draw_winrate;
    # a drawn game is in neither, so a side's record is won plus lost
    play_draw: tuple[tuple[bool, int, int], ...]
    candidates: tuple[Candidate, ...]
    own_cards: tuple[OwnCard, ...]
    own_archetype: Verdict | None
    # v_match_opponent's key: archetype:/manual:/colors:<…>, or the literal
    # "unknown"; None when the view had no row for this match
    opponent_key: str | None
    opponent_label: str | None
    opponent_archetype_key: str | None  # bare key, only when opponent_key names one
    opponent_revealed_names: frozenset[str]
    opp_consensus: ArchetypeConsensus | None
    damage_events: tuple[DamageRow, ...]
    life_events: tuple[LifeRow, ...]
    countered: tuple[CounteredCard, ...]
    personal_matchup: PersonalMatchup | None
    field_matchup: FieldMatchup | None
    # the format-reset window field_matchup was counted from, or None when it
    # wasn't windowed (no reset detected, or no legality data yet) — carried
    # so a caller rendering field_matchup can say which window it means
    # rather than showing a bare number. Defaulted, so last: tests construct
    # MatchSnapshot by keyword without it.
    field_since: str | None = None

    def turns_in(self, game_number: int) -> list[SelfTurnRow]:
        """Our own turns for one game, in turn order. A plain filter over an
        already-fetched tuple — the loop every analyzer starts with."""
        return sorted(
            (t for t in self.self_turns if t.game_number == game_number),
            key=lambda t: t.turn_number,
        )


def classify_own_deck(
    conn: sqlite3.Connection,
    deck_id: str | None,
    event_id: str | None,
    *,
    colors_by_name: dict[str, frozenset[str]] | None = None,
    fmt: str | None = None,
    use_deck_format: bool = True,
) -> tuple[Verdict | None, tuple[OwnCard, ...]]:
    """Our own archetype, from our exact decklist — normally the same
    ``complete=True`` path ``metagame.classify_meta`` runs over a corpus
    decklist (a deck with unresolved copies is the exception, below). Never
    stored (``review/__init__.py``'s own rule): a deck classified once could
    point at a definition set later refreshed by ``sensei-top archetypes``.

    ``colors_by_name``, when given, replaces the ``card_colors_by_name``
    scan (see ``build_snapshot``'s ``colors_cache``).

    The format is ``fmt`` when the caller knows it, already one of
    ``formats.FORMATS``: a match's ``v_match_format.format`` (``build_snapshot``)
    or a deck's format (``guide/deck.py``'s ``identity_format``, which
    ``guide/field.py``, ``guide/list_diff.py`` and ``coach/evidence.py`` pass).
    Without one, ``decks.format`` is read through ``formats.arena_format``,
    unless the caller passes ``use_deck_format=False``: an MTGO match does, since
    its deck's format is the store's FormatCode, which only pre-fills the pick.

    A deck whose ``cards_json`` counts unresolved maindeck copies is a partial
    list, so it is classified with ``complete=False``: the evidence gates apply
    and a missing card is unknown, not absent.
    """
    own_cards: list[OwnCard] = []
    if deck_id is None:
        return None, ()

    deck_row = conn.execute(
        "SELECT cards_json, format FROM decks WHERE deck_id = ?", (deck_id,)
    ).fetchone()
    if deck_row is None:
        return None, ()

    try:
        deck_json = json.loads(deck_row["cards_json"])
    except json.JSONDecodeError:
        return None, ()
    maindeck: list[int] = deck_json.get("maindeck") or []
    # An MTGO deck's copies that resolved to no card are counted under
    # "unresolved", not listed. Arena rows have no such key, so they stay
    # complete.
    unresolved = (deck_json.get("unresolved") or {}).get("maindeck") or 0
    if not maindeck:
        return None, ()

    counts: dict[int, int] = {}
    for grp_id in maindeck:
        counts[grp_id] = counts.get(grp_id, 0) + 1

    card_rows = {
        row["grp_id"]: row
        for row in conn.execute(
            f"SELECT grp_id, name, type_line, oracle_text, mana_cost FROM cards "
            f"WHERE grp_id IN ({','.join('?' for _ in counts)})",
            list(counts),
        )
    } if counts else {}

    for grp_id, count in counts.items():
        found = card_rows.get(grp_id)
        tags = (
            effects.classify(found["oracle_text"], found["type_line"], found["mana_cost"])
            if found is not None
            else effects.UNKNOWN
        )
        own_cards.append(
            OwnCard(
                grp_id=grp_id,
                name=found["name"] if found is not None else None,
                type_line=found["type_line"] if found is not None else None,
                count=count,
                tags=tags.tags if isinstance(tags, effects.EffectTags) else tags,
            )
        )
    own_cards.sort(key=lambda c: (c.name or "", c.grp_id))

    if fmt is None and use_deck_format:
        fmt = arena_format(deck_row["format"], event_id)
    definitions = load_definitions(conn)
    if fmt is None or fmt not in definitions:
        return None, tuple(own_cards)

    names = [c.name for c in own_cards if c.name is not None for _ in range(c.count)]
    if not names:
        return None, tuple(own_cards)
    seen = seen_forms(names)
    if colors_by_name is None:
        colors_by_name = card_colors_by_name(conn)
    present: set[str] = set()
    for name in names:
        if (card_colors := card_colors_of(name, colors_by_name)) is not None:
            present |= card_colors
    colors = "".join(letter for letter in "WUBRG" if letter in present)

    verdict = choose(
        definitions[fmt]["archetype"], definitions[fmt]["fallback"], seen, colors,
        colors_by_name, cards_seen=len(names), complete=not unresolved,
    )
    return verdict, tuple(own_cards)


def build_snapshot(
    conn: sqlite3.Connection,
    match_id: str,
    *,
    consensus_since: str | None = None,
    consensus_cache: dict[tuple[str | None, str | None, str | None], ArchetypeConsensus | None]
    | None = None,
    colors_cache: dict[str, dict[str, frozenset[str]]] | None = None,
    view_cache: dict | None = None,
) -> MatchSnapshot | None:
    """``consensus_since`` is the format-reset window start
    (``guide/window.py``'s ``window_start``), passed straight through as
    ``build_consensus``'s ``since`` and ``ranked_field_matchup``'s, so
    neither the opponent's consensus nor the field record pools decklists
    or rounds from both sides of a ban. ``None`` is not a neutral default;
    it is the pre-reset-inclusive answer, and is only correct when the
    caller knows the corpus cannot cross a reset — no reset detected in
    this format, or no legality data yet to detect one from. A caller that
    *can* see a reset (``coach/evidence.py``, the API routes under
    ``api/routes/matches.py``) must compute it and pass it here; this module
    never imports ``guide.window`` itself, since ``guide/`` is built on
    ``review/`` and a reverse import would be a package cycle.

    ``consensus_cache``, when given, memoizes ``build_consensus`` across
    repeated calls within one caller's request, as ``build_consensus`` asks
    of a caller needing it more than once — ``review/leaks.py``'s
    ``find_leaks`` and ``coach/evidence.py`` rebuild a snapshot per match,
    and many matches share an opponent archetype. The key is
    ``(opponent_archetype_key, fmt, consensus_since)`` rather than the
    archetype key alone, so two callers sharing one cache dict with
    different formats or windows never hand each other a consensus built
    from the wrong corpus or the wrong side of a reset.

    ``colors_cache`` is the same idea for ``archetypes.classify.
    card_colors_by_name`` — a full-table scan of ``cards`` that both
    ``rank_candidates`` and ``classify_own_deck`` need, and whose result
    depends only on ``cards``, not on the match. It is computed at most once
    and stored in the dict under ``"colors_by_name"``, so a caller shares
    one scan across every match in its request.

    ``view_cache`` follows the same pattern for statements that would
    otherwise rescan a whole view per match. The first call given the dict
    fills ``"opponents"`` and ``"opponent_cards"`` (one query each) and
    later calls read them from memory:

    - ``"opponents"``: one pass over ``matches JOIN v_match_opponent JOIN
      v_match_deck`` (exactly one row per match; the deck is ``v_match_deck``'s,
      so an MTGO match's pick, not ``matches.deck_id``), split into a
      per-match_id map for the opponent_key/label lookup and a
      ``(opponent_key, deck_id)`` -> rows map for the personal-matchup
      aggregate, computed in Python with the uncached SQL's exact semantics
      (``matches_completed``/``matches_won`` filtered by ``result``;
      ``games_won``/``games_lost`` summed with ``COALESCE(..., 0)`` over every
      other matching row regardless of ``result``).
    - ``"opponent_cards"``: one pass over ``v_opponent_cards`` (the
      expensive CTE ``rank_candidates`` would otherwise query once per
      match — ``api/sql.py::_cached_match_opponent``'s docstring records
      why the match_id filter can't be pushed through it), passed to
      ``rank_candidates`` through its own ``opponent_cards`` keyword.
    - ``"field_matchup"``: a memo keyed ``(own_archetype.key,
      opponent_archetype_key, fmt, consensus_since)``, since ``v_meta_matchup``'s
      windowed result for one format depends only on those four, not on the
      match: the same pairing in two formats is two corpora.
    """
    colors_by_name = None
    if colors_cache is not None:
        colors_by_name = colors_cache.get("colors_by_name")
        if colors_by_name is None:
            colors_by_name = card_colors_by_name(conn)
            colors_cache["colors_by_name"] = colors_by_name

    opponents_by_match: dict[str, tuple[str | None, str | None]] | None = None
    opponents_by_key_deck: dict[tuple[str, str], list[tuple]] | None = None
    opponent_cards_map: dict[str, tuple[str, int]] | None = None
    field_matchup_memo: (
        dict[tuple[str, str, str | None, str | None], FieldMatchup | None] | None
    ) = None
    if view_cache is not None:
        opponents_entry = view_cache.get("opponents")
        if opponents_entry is None:
            by_match: dict[str, tuple[str | None, str | None]] = {}
            by_key_deck: dict[tuple[str, str], list[tuple]] = defaultdict(list)
            for row in conn.execute(
                """
                SELECT m.match_id, md.deck_id, m.result, m.games_won, m.games_lost,
                       v.opponent_key, v.opponent_label
                  FROM matches m JOIN v_match_opponent v ON v.match_id = m.match_id
                  JOIN v_match_deck md ON md.match_id = m.match_id
                """
            ):
                by_match[row["match_id"]] = (row["opponent_key"], row["opponent_label"])
                if row["deck_id"] is not None:
                    by_key_deck[(row["opponent_key"], row["deck_id"])].append(
                        (row["match_id"], row["result"], row["games_won"], row["games_lost"])
                    )
            opponents_entry = {"by_match": by_match, "by_key_deck": dict(by_key_deck)}
            view_cache["opponents"] = opponents_entry
        opponents_by_match = opponents_entry["by_match"]
        opponents_by_key_deck = opponents_entry["by_key_deck"]

        opponent_cards_map = view_cache.get("opponent_cards")
        if opponent_cards_map is None:
            opponent_cards_map = {
                row["match_id"]: (row["colors"], row["cards_seen"])
                for row in conn.execute("SELECT match_id, colors, cards_seen FROM v_opponent_cards")
            }
            view_cache["opponent_cards"] = opponent_cards_map

        field_matchup_memo = view_cache.setdefault("field_matchup", {})

    match = conn.execute(
        "SELECT m.match_id, m.source, md.deck_id, f.format AS match_format, "
        "m.self_seat, m.opponent_seat, m.event_id, m.result "
        "FROM matches m JOIN v_match_deck md ON md.match_id = m.match_id "
        "JOIN v_match_format f ON f.match_id = m.match_id "
        "WHERE m.match_id = ?",
        (match_id,),
    ).fetchone()
    if match is None:
        return None

    games = tuple(
        GameFacts(
            game_number=row["game_number"],
            on_play=bool(row["on_play"]) if row["on_play"] is not None else None,
            result=row["result"],
            result_reason=row["result_reason"],
            turn_count=row["turn_count"],
            self_mulligans=row["self_mulligans"],
            opp_mulligans=row["opp_mulligans"],
        )
        for row in conn.execute(
            """
            SELECT game_number, on_play, result, result_reason, turn_count,
                   self_mulligans, opp_mulligans
              FROM games WHERE match_id = ? ORDER BY game_number
            """,
            (match_id,),
        )
    )

    # Board power and opponent lands, per (game, turn, seat) — see SelfTurnRow.
    # `card_types` here is Arena's own projected vocabulary, not
    # `cards.type_line` -- no em-dash split needed, so this is not a case
    # for review/effects.py::is_land.
    power_and_lands: dict[tuple[int, int, int], tuple[int | None, int]] = {}
    for row in conn.execute(
        """
        SELECT game_number, turn_number, seat,
               SUM(power) AS total_power,
               SUM(CASE WHEN card_types LIKE '%CardType_Land%' THEN 1 ELSE 0 END) AS lands
          FROM turn_zones
         WHERE match_id = ? AND zone = 'battlefield'
         GROUP BY game_number, turn_number, seat
        """,
        (match_id,),
    ):
        power_and_lands[(row["game_number"], row["turn_number"], row["seat"])] = (
            row["total_power"], row["lands"]
        )

    self_seat = match["self_seat"]
    opponent_seat = match["opponent_seat"]

    self_turns = tuple(
        SelfTurnRow(
            game_number=row["game_number"],
            turn_number=row["turn_number"],
            self_turn_index=row["self_turn_index"],
            self_life=row["self_life"],
            opp_life=row["opp_life"],
            self_hand=row["self_hand"],
            opp_hand=row["opp_hand"],
            self_lands=row["self_lands"],
            opp_lands=(power_and_lands.get((row["game_number"], row["turn_number"], opponent_seat))
                       or (None, None))[1],
            self_permanents=row["self_permanents"],
            opp_permanents=row["opp_permanents"],
            self_power=(power_and_lands.get((row["game_number"], row["turn_number"], self_seat))
                        or (None, None))[0],
            opp_power=(power_and_lands.get((row["game_number"], row["turn_number"], opponent_seat))
                       or (None, None))[0],
            self_library=row["self_library"],
            self_graveyard=row["self_graveyard"],
            self_open_mana=row["self_open_mana"],
            prev_self_permanents=row["prev_self_permanents"],
        )
        for row in conn.execute(
            "SELECT * FROM v_self_turns WHERE match_id = ? ORDER BY game_number, turn_number",
            (match_id,),
        )
    )

    lands_played = {
        (row["game_number"], row["turn_number"]): row["lands_played"]
        for row in conn.execute(
            "SELECT game_number, turn_number, lands_played FROM v_self_lands_played "
            "WHERE match_id = ?",
            (match_id,),
        )
    }

    hand_lands = {
        (row["game_number"], row["turn_number"]): (row["hand_lands"], row["named_cards"])
        for row in conn.execute(
            "SELECT game_number, turn_number, hand_lands, named_cards FROM v_self_hand_lands "
            "WHERE match_id = ?",
            (match_id,),
        )
    }

    turn1_hand_size = {
        row["game_number"]: row["self_hand"]
        for row in conn.execute(
            "SELECT game_number, self_hand FROM turns WHERE match_id = ? AND turn_number = 1",
            (match_id,),
        )
    }

    deck_id = match["deck_id"]

    deck_land_ratio = None
    if deck_id is not None:
        row = conn.execute(
            "SELECT maindeck_size, land_count, unnamed_count, unresolved_count "
            "FROM v_deck_land_count "
            "WHERE deck_id = ?",
            (deck_id,),
        ).fetchone()
        if row is not None:
            deck_land_ratio = DeckLandRatio(
                row["maindeck_size"],
                row["land_count"],
                row["unnamed_count"] + row["unresolved_count"],
            )

    opponent_plays = tuple(
        CardPlay(
            game_number=row["game_number"],
            turn_number=row["turn_number"],
            grp_id=row["grp_id"],
            card_name=row["card_name"],
            category=row["category"],
        )
        for row in conn.execute(
            """
            SELECT game_number, turn_number, grp_id, card_name, category
              FROM v_card_events
             WHERE match_id = ? AND is_self = 0 AND turn_number IS NOT NULL
               AND category IN ('CastSpell', 'Resolve')
             ORDER BY game_number, turn_number
            """,
            (match_id,),
        )
    )

    # Our own side of the same play-by-play, for narrative.py's prompt; no
    # analyzer reads it.
    self_plays = tuple(
        CardPlay(
            game_number=row["game_number"],
            turn_number=row["turn_number"],
            grp_id=row["grp_id"],
            card_name=row["card_name"],
            category=row["category"],
        )
        for row in conn.execute(
            """
            SELECT game_number, turn_number, grp_id, card_name, category
              FROM v_card_events
             WHERE match_id = ? AND is_self = 1 AND turn_number IS NOT NULL
               AND category IN ('CastSpell', 'Resolve')
             ORDER BY game_number, turn_number
            """,
            (match_id,),
        )
    )

    opponent_revealed_names = frozenset(
        row["name"]
        for row in conn.execute(
            """
            SELECT DISTINCT c.name AS name
              FROM card_events ce
              JOIN matches m ON m.match_id = ce.match_id
              JOIN cards c ON c.grp_id = ce.grp_id
             WHERE ce.match_id = ? AND ce.seat = m.opponent_seat AND ce.grp_id IS NOT NULL
            """,
            (match_id,),
        )
    )

    deck_game_length = (
        tuple(
            (row["turn_count"], row["games"], row["games_won"])
            for row in conn.execute(
                "SELECT turn_count, games, games_won FROM v_deck_game_length WHERE deck_id = ?",
                (deck_id,),
            )
        )
        if deck_id is not None
        else ()
    )

    play_draw = (
        tuple(
            (bool(row["on_play"]), row["games_won"], row["games_lost"])
            for row in conn.execute(
                "SELECT on_play, games_won, games_lost FROM v_play_draw_winrate "
                "WHERE deck_id = ?",
                (deck_id,),
            )
        )
        if deck_id is not None
        else ()
    )

    candidates = tuple(
        rank_candidates(
            conn, match_id, colors_by_name=colors_by_name, opponent_cards=opponent_cards_map
        )
    )

    own_archetype, own_cards = classify_own_deck(
        conn,
        deck_id,
        match["event_id"],
        colors_by_name=colors_by_name,
        # The match's own read-time format, the one rank_candidates names
        # the opponent under too: an Arena match's from the log, an MTGO
        # match's pick, else its inference. A database whose matches.format
        # (migration 055) is not projected yet falls back to decks.format
        # for an Arena match, as rank_candidates does.
        fmt=match["match_format"],
        use_deck_format=match["source"] != "mtgo",
    )

    if opponents_by_match is not None:
        opponent_key, opponent_label = opponents_by_match.get(match_id, (None, None))
    else:
        opp_row = conn.execute(
            "SELECT opponent_key, opponent_label FROM v_match_opponent WHERE match_id = ?",
            (match_id,),
        ).fetchone()
        opponent_key = opp_row["opponent_key"] if opp_row else None
        opponent_label = opp_row["opponent_label"] if opp_row else None
    opponent_archetype_key = (
        opponent_key.removeprefix("archetype:")
        if opponent_key and opponent_key.startswith("archetype:")
        else None
    )

    consensus_cache_key = (opponent_archetype_key, match["match_format"], consensus_since)
    if opponent_archetype_key is None:
        opp_consensus = None
    elif consensus_cache is not None and consensus_cache_key in consensus_cache:
        opp_consensus = consensus_cache[consensus_cache_key]
    else:
        opp_consensus = build_consensus(
            conn, opponent_archetype_key, fmt=match["match_format"], since=consensus_since
        )
        if consensus_cache is not None:
            consensus_cache[consensus_cache_key] = opp_consensus

    damage_events = tuple(
        DamageRow(
            game_number=row["game_number"],
            turn_number=row["turn_number"],
            amount=row["amount"],
            damage_type=row["damage_type"],
            source_instance_id=row["source_instance_id"],
            source_grp_id=row["source_grp_id"],
            # SQLite hands back a plain 0/1/None int for a CASE expression,
            # never a real bool — analyzers compare these with `is True`/
            # `is False` (see clock.py), so an un-converted int would never
            # match either and would silently look like "unknown" instead.
            source_is_self=None if row["source_is_self"] is None else bool(row["source_is_self"]),
            target_instance_id=row["target_instance_id"],
            target_is_self=None if row["target_is_self"] is None else bool(row["target_is_self"]),
        )
        for row in conn.execute(
            "SELECT * FROM v_damage_events WHERE match_id = ? ORDER BY game_number, turn_number",
            (match_id,),
        )
    )

    life_events = tuple(
        LifeRow(
            game_number=row["game_number"],
            turn_number=row["turn_number"],
            seat_is_self=(None if self_seat is None else row["seat"] == self_seat),
            delta=row["delta"],
            affector_grp_id=row["affector_grp_id"],
        )
        for row in conn.execute(
            "SELECT * FROM life_events WHERE match_id = ? ORDER BY game_number, turn_number",
            (match_id,),
        )
    )

    countered = tuple(
        CounteredCard(
            game_number=row["game_number"],
            turn_number=row["turn_number"],
            is_self=bool(row["is_self"]) if row["is_self"] is not None else None,
            card_name=row["card_name"],
        )
        for row in conn.execute(
            "SELECT game_number, turn_number, is_self, card_name FROM v_card_events "
            "WHERE match_id = ? AND category = 'Countered' ORDER BY game_number, seq",
            (match_id,),
        )
    )

    personal_matchup = None
    if opponent_key and deck_id is not None:
        if opponents_by_key_deck is not None:
            others = [
                r for r in opponents_by_key_deck.get((opponent_key, deck_id), ())
                if r[0] != match_id
            ]
            matches_completed = sum(1 for r in others if r[1] in ("win", "loss", "draw"))
            matches_won = sum(1 for r in others if r[1] == "win")
            games_won = sum(r[2] or 0 for r in others)
            games_lost = sum(r[3] or 0 for r in others)
            if matches_completed:
                personal_matchup = PersonalMatchup(
                    matches_completed=matches_completed,
                    matches_won=matches_won,
                    games_won=games_won,
                    games_lost=games_lost,
                )
        else:
            row = conn.execute(
                """
                SELECT COUNT(*) FILTER (WHERE m.result IN ('win','loss','draw'))
                           AS matches_completed,
                       COUNT(*) FILTER (WHERE m.result = 'win') AS matches_won,
                       SUM(COALESCE(m.games_won, 0)) AS games_won,
                       SUM(COALESCE(m.games_lost, 0)) AS games_lost
                  FROM matches m
                  JOIN v_match_opponent v ON v.match_id = m.match_id
                  JOIN v_match_deck md ON md.match_id = m.match_id
                 WHERE v.opponent_key = ? AND md.deck_id = ? AND m.match_id != ?
                """,
                (opponent_key, deck_id, match_id),
            ).fetchone()
            if row and row["matches_completed"]:
                personal_matchup = PersonalMatchup(
                    matches_completed=row["matches_completed"],
                    matches_won=row["matches_won"] or 0,
                    games_won=row["games_won"] or 0,
                    games_lost=row["games_lost"] or 0,
                )

    field_matchup = None
    if own_archetype is not None and opponent_archetype_key is not None:
        memo_key = (
            own_archetype.key, opponent_archetype_key, match["match_format"], consensus_since,
        )
        if field_matchup_memo is not None and memo_key in field_matchup_memo:
            field_matchup = field_matchup_memo[memo_key]
        else:
            ranked = ranked_field_matchup(
                conn, own_archetype.key, opponent_archetype_key, consensus_since,
                fmt=match["match_format"],
            )
            if ranked is not None:
                field_matchup = FieldMatchup(
                    n=ranked.n, matches_won=ranked.matches_won,
                    matches_lost=ranked.matches_lost, tier=ranked.tier,
                )
            if field_matchup_memo is not None:
                field_matchup_memo[memo_key] = field_matchup

    return MatchSnapshot(
        match_id=match["match_id"],
        deck_id=deck_id,
        self_seat=self_seat,
        result=match["result"],
        games=games,
        self_turns=self_turns,
        lands_played=lands_played,
        hand_lands=hand_lands,
        turn1_hand_size=turn1_hand_size,
        deck_land_ratio=deck_land_ratio,
        opponent_plays=opponent_plays,
        self_plays=self_plays,
        deck_game_length=deck_game_length,
        play_draw=play_draw,
        candidates=candidates,
        own_cards=own_cards,
        own_archetype=own_archetype,
        opponent_key=opponent_key,
        opponent_label=opponent_label,
        opponent_archetype_key=opponent_archetype_key,
        opponent_revealed_names=opponent_revealed_names,
        opp_consensus=opp_consensus,
        damage_events=damage_events,
        life_events=life_events,
        countered=countered,
        personal_matchup=personal_matchup,
        field_matchup=field_matchup,
        field_since=consensus_since,
    )
