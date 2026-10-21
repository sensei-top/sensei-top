"""The current-match reads: the match in progress, the opening-hand read,
the keep guide, the opponent-hand read and our own remaining library —
everything ``/api/current-match``, ``/api/current-match/read`` and their
tag-mates return.

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from sensei_top.api.models.common import MatchupBriefOut
from sensei_top.api.models.metagame import FormatName


class TurnZoneCard(BaseModel):
    """One card in one zone at the end of one turn — the identities behind
    ``CurrentTurn``'s bare counts (``self_hand``, ``self_permanents``, …)."""

    zone: str = Field(description="hand, battlefield, graveyard or exile")
    idx: int
    instance_id: int
    grp_id: int | None = Field(None, description="null when the card was hidden from us")
    card_name: str | None = Field(
        None, description="null until 'sensei-top cards' has downloaded the card table"
    )
    card_types: str | None = Field(None, description="Arena's CardType_* strings, comma-joined")
    drawn_on_turn: int | None = Field(None, description="the turn this card was drawn")
    is_tapped: bool | None = Field(
        None, description="battlefield only; null in every other zone, where it does not apply"
    )
    power: int | None = Field(None, description="Arena's current value, not the printed one")
    toughness: int | None = Field(None, description="Arena's current value, not the printed one")
    is_self: bool | None = None
    mana_cost: str | None = Field(
        None, description="e.g. '{2}{R}'; null until the card table is downloaded"
    )
    type_line: str | None = None
    colors: str | None = Field(
        None, description="JSON array of WUBRG letters, e.g. '[\"U\",\"R\"]'"
    )


class CurrentTurn(BaseModel):
    turn_number: int = Field(description="player-turn number; both seats alternate")
    active_seat: int | None = None
    self_life: int | None = None
    opp_life: int | None = None
    self_hand: int | None = None
    opp_hand: int | None = None
    self_lands: int | None = None
    self_permanents: int | None = None
    opp_permanents: int | None = None
    self_library: int | None = Field(None, description="cards left in your library")
    opp_library: int | None = None
    self_graveyard: int | None = None
    opp_graveyard: int | None = None
    self_open_mana: int | None = Field(
        None,
        description="untapped lands on your battlefield — a bluff/interaction proxy, "
        "not Arena's actual mana pool, which is never exposed",
    )
    opp_open_mana: int | None = None
    zones: list[TurnZoneCard] = Field(default_factory=list)


class CurrentCardEvent(BaseModel):
    seq: int = Field(description="order observed within the game, from 0")
    turn_number: int | None = None
    category: str | None = Field(
        None,
        description="Arena's own word for the move: Draw, CastSpell, PlayLand, Put, Resolve, …",
    )
    zone_src: str | None = None
    zone_dest: str | None = None
    grp_id: int | None = Field(None, description="null when the card was hidden from us")
    card_name: str | None = Field(
        None, description="null until 'sensei-top cards' has downloaded the card table"
    )
    is_self: bool | None = None


class CurrentGame(BaseModel):
    game_number: int
    on_play: bool | None = None
    self_mulligans: int | None = None
    opp_mulligans: int | None = None
    turn_count: int | None = Field(None, description="player-turns, not rounds")


class CurrentMatch(BaseModel):
    """The match being played right now, with the current game's detail."""

    match_id: str
    event_id: str | None = None
    deck_id: str | None = None
    deck_name: str | None = None
    opponent_name: str | None = None
    opponent_label: str | None = None
    opponent_source: str | None = None
    opponent_confidence: str | None = None
    opponent_cards_seen: int = 0
    opponent_colors: str | None = Field(
        None,
        description="WUBRG letters the opponent revealed this match (v_match_opponent); null "
        "when nothing colored was revealed or a revealed card's colours are unknown",
    )
    opponent_signature_cards: list[str] = Field(
        default_factory=list,
        description="up to 3 revealed nonland cards, rarity-then-frequency order "
        "(v_opponent_cards.signature_cards) — shown alongside colours when no source names "
        "the deck outright",
    )
    started_at: str | None = Field(
        None,
        description="when the match room opened, which says how stale this is: an abandoned "
        "match stays current until the next one",
    )
    games_won: int | None = None
    games_lost: int | None = None
    game: CurrentGame | None = None
    turns: list[CurrentTurn]
    cards: list[CurrentCardEvent]
    source: str = Field(
        "arena",
        description="which client wrote this match — always 'arena': v_current_match "
        "(migrations/040_arena_only_current_match.sql) only ever returns an Arena match, "
        "so an MTGO match can never reach this model",
    )


class HandSlotOut(BaseModel):
    count: int
    label: str = Field(description="e.g. 'lands', 'creature', 'plays at 1-2 mana'")


class MulliganRecordOut(BaseModel):
    mulligans: int
    games: int
    wins: int


class KeyPlayOut(BaseModel):
    """One of this deck's key cards, chosen from its decklist and card text,
    with its record from the turn band where it does best in this deck's own
    games (``table/keep.py``'s ``KeyPlay``) — the evidence the opening-hand
    verdict checks for "pressure" before it calls a hand an unconditional
    keep."""

    card: str
    best_band: str = Field(
        description="the turn band this card's win-rate split is measured over, e.g. "
        "'T5-6'; never 'never resolved' — that bucket is excluded from the pick"
    )
    best_band_wins: int
    best_band_losses: int
    never_resolved_wins: int = Field(
        description="wins in games where this card never resolved at all"
    )
    never_resolved_losses: int = Field(
        description="losses in games where this card never resolved at all"
    )
    n: int = Field(description="total decided games behind this deck's key plays")


class MulliganCostOut(BaseModel):
    """This deck's own kept-seven vs. mulliganed-to-six-or-fewer records
    (``table/keep.py``'s ``MulliganCost``) — the brake that keeps a
    borderline hand marginal instead of letting it slide to mulligan when
    shipping it has a measured, wide cost for this deck."""

    kept_seven_games: int
    kept_seven_wins: int
    kept_seven_losses: int
    mulliganed_games: int
    mulliganed_wins: int
    mulliganed_losses: int


class KeepGuideOut(BaseModel):
    """What a keepable opening hand looks like for the deck being played,
    from its own maindeck and match history — no board state, so this is
    valid from the mulligan decision onward (``table/keep.py``)."""

    maindeck_size: int
    land_count: int
    unnamed_count: int = Field(
        description="maindeck cards not yet in the card table; nonzero suppresses "
        "land_min/land_max/ideal_hand below rather than guessing past the gap"
    )
    creature_count: int
    interaction_count: int
    untagged_count: int = Field(
        description="named nonland cards with no downloaded oracle text, so their "
        "effect could not be classified — not counted as 'no interaction'"
    )
    avg_mana_value: float | None = None
    cheap_count: int = Field(description="nonland cards at mana value 2 or less")
    curve: list[list[int]] = Field(
        description="[mana_value, copies] pairs for nonlands only; 7 means '7 or more'"
    )
    land_min: int | None = None
    land_max: int | None = None
    ideal_hand: list[HandSlotOut] = Field(
        default_factory=list, description="sums to 7 when present"
    )
    early_plays: int | None = Field(
        None, description="ideal_hand's own 'play(s) at 1-2 mana' count, as a bare int"
    )
    land_odds: list[list[float]] = Field(
        description="[k, P(exactly k lands in an opening 7)] for k = 0..7"
    )
    expected_lands_seven: float | None = None
    expected_lands_eight: float | None = Field(None, description="on the draw")
    keep_rate: float | None = Field(
        None, description="P(land count in an opening 7 falls within [land_min, land_max])"
    )
    mulligan_record: list[MulliganRecordOut] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list,
        description="the rule that produced land_min/land_max, or why it didn't",
    )
    key_plays: list[KeyPlayOut] = Field(
        default_factory=list,
        description="this deck's own evidence-backed threats, gated on a minimum decided "
        "games count; empty below that floor rather than a spike from a handful of games "
        "(see notes above when that's why)",
    )
    mulligan_cost: MulliganCostOut | None = Field(
        None,
        description="this deck's own kept-seven vs. mulliganed win rates; null below the "
        "same evidence floor as key_plays",
    )


class HandCardOut(BaseModel):
    """One card from the opponent's archetype consensus that may still be
    unaccounted for this game — an estimate, never a certainty
    (``table/hand_read.py``)."""

    name: str
    grp_id: int | None = Field(
        None,
        description="key for /api/cards/{grp_id}/image; null when this consensus card "
        "never matched a cards row",
    )
    type_line: str | None = None
    mana_cost: str | None = None
    mana_value: int | None = None
    tags: list[str] = Field(default_factory=list)
    tags_known: bool = Field(
        description="False when this card has no downloaded oracle text to classify"
    )
    expected_copies_left: float = Field(
        description="archetype consensus copies minus copies already seen this game"
    )
    p_in_hand: float = Field(description="hypergeometric odds this card is in hand right now")
    castable_now: bool | None = Field(
        None,
        description="an instant within the opponent's open mana plus other_mana_sources; "
        "null if unknown",
    )


class RevealedCardOut(BaseModel):
    """One card Arena has actually shown us, by name — a fact, not an
    estimate. ``grp_id`` is null only in the same rare case a consensus
    card's is (``table/hand_read.py``'s own ``RevealedCard``)."""

    name: str
    grp_id: int | None = None


class HandReadOut(BaseModel):
    """What the opponent might be holding, degrading in stages rather than
    going blank: unclassified/no_consensus/format_unknown still carry every observed fact,
    only the per-card lists are empty."""

    status: str = Field(description="ok | unclassified | no_consensus | format_unknown | no_game "
        "(format_unknown: the match has no format, so there is no field to read a "
        "consensus from)"
    )
    archetype_key: str | None = None
    archetype_label: str | None = None
    deck_count: int | None = Field(
        None, description="decks behind the consensus, when there is one"
    )
    hand_size: int | None = None
    hidden_pool: int | None = Field(None, description="opponent's hand + library, observed")
    open_mana: int | None = Field(None, description="untapped lands only")
    other_mana_sources: int | None = Field(
        None,
        description="untapped non-land mana sources (rocks, dorks, Treasures) — only known "
        "during a live replay, null outside one; castable_now already sums this with open_mana",
    )
    held_turns: int | None = Field(
        None, description="consecutive latest turns at this same hand size"
    )
    known_in_hand: list[RevealedCardOut] = Field(
        default_factory=list, description="revealed right now — a fact, not an estimate"
    )
    revealed_this_match: list[RevealedCardOut] = Field(default_factory=list)
    interaction: list[HandCardOut] = Field(default_factory=list)
    threats: list[HandCardOut] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class LibraryCardOut(BaseModel):
    """One maindeck card and how many copies are still unaccounted for in
    the library this game — the page's primary panel once a game is under
    way (``table/live.py``). ``left`` is never negative, and a card stays in
    the list at 0 once every copy is seen."""

    grp_id: int
    name: str | None = None
    mana_cost: str | None = None
    mana_value: int | None = Field(None, description="null for a land")
    type_line: str | None = None
    is_land: bool
    quantity: int = Field(description="copies in the maindeck")
    left: int = Field(description="copies not yet seen outside the library this game")
    is_interaction: bool | None = Field(
        None,
        description="removal, a sweeper or a counterspell; null when the card has no "
        "downloaded oracle text, so its effect could not be classified — not the same "
        "as 'not interaction'",
    )


class OpeningHandCardOut(BaseModel):
    """One card in the hand being evaluated pre-keep (``table/opening_hand.py``)."""

    grp_id: int
    name: str | None = Field(None, description="null only when the card table has never named this")
    type_line: str | None = None
    mana_cost: str | None = None
    is_land: bool = Field(description="from Arena's own CardType_Land — always known")
    mana_value: int | None = None
    tags: list[str] = Field(default_factory=list)
    tags_known: bool = True
    castable_turn: int | None = Field(
        None,
        description="earliest turn this hand's own lands can pay for it; null for a land, "
        "an unparseable cost, or one these lands never pay. With colors_known false, a land "
        "whose colors are unknown counts as colorless",
    )
    reduced_castable_turn: int | None = Field(
        None,
        description="earliest turn this hand's own lands *and its own in-hand or on-board "
        "fuel* can pay for it, for a card with a cost-reduction clause (e.g. 'costs {1} "
        "less for each instant/sorcery in your graveyard'); null for a land, when this "
        "card carries no cost-reduction clause, when the reduction's shape or fuel could "
        "not be parsed, or when this hand never reaches it. Same colorless reading as "
        "castable_turn, which it never overwrites: castable_turn always stays the "
        "printed-cost answer",
    )


class OpeningHandOut(BaseModel):
    """The hand on offer right now, read from a replay of ``raw_events``
    before the keep/mulligan decision, never from the projection — see
    docs/current-match.md, "The opening-hand read (`table/opening_hand.py`)"."""

    seat: int
    game_number: int | None = Field(
        None,
        description="the game this hand is for, from the same live replay; null when no "
        "gameInfo has named one. The projected game lags in a game 2 or 3 hand",
    )
    mulligan_count: int = Field(description="0 on the first offer; already-mulliganed count")
    on_the_play: bool | None = None
    cards: list[OpeningHandCardOut] = Field(default_factory=list)
    land_count: int
    land_min: int | None = None
    land_max: int | None = None
    ideal_hand: list[HandSlotOut] = Field(default_factory=list)
    keep_rate: float | None = None
    mulligan_record: list[MulliganRecordOut] = Field(default_factory=list)
    unnamed_count: int = 0
    colors_known: bool = Field(
        description="false when a land in hand resolves to neither produced_mana nor a "
        "chosen basic land type"
    )
    verdict: str | None = Field(
        None, description="keep | mulligan | marginal | null (withheld — see caveats)"
    )
    reasons: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class IntermissionOpponentOut(BaseModel):
    """Who the opponent is, per ``table/intermission.py``'s
    ``OpponentRead`` — a manual pick first, then a live rule-engine/corpus
    read over whatever has been revealed so far."""

    label: str
    archetype_key: str | None = None
    confidence: str = Field(description="high | medium | low")
    source: str = Field(description="manual | live")


class AlternativePlanOut(BaseModel):
    """One candidate archetype with a stored brief, offered when there is
    no exact plan for the opponent actually named — best fit first."""

    archetype_key: str
    label: str
    confidence: str = Field(description="high | medium | low")
    fit: float
    brief: MatchupBriefOut


class PastBoardingCardOut(BaseModel):
    grp_id: int
    card: str | None
    n: int
    in_current_75: bool = Field(
        description="false when this card has since been cut from the current 75 — flagged, "
        "never dropped"
    )


class PastBoardingGameOut(BaseModel):
    game_number: int
    board_in: list[PastBoardingCardOut]
    board_out: list[PastBoardingCardOut]
    result: str | None = None
    result_reason: str | None = None


class PastBoardingOut(BaseModel):
    """One prior completed match of this deck identity against this
    archetype, and what was actually boarded in it — shown as "what you
    boarded last time", never as advice."""

    match_id: str
    played_at: str | None = None
    games: list[PastBoardingGameOut]


class PostboardRecordOut(BaseModel):
    won: int = Field(description="Games won.")
    lost: int = Field(description="Games lost.")


class IntermissionOut(BaseModel):
    """The Bo3 break card: the game that just ended, who the opponent looks
    like from whatever has been revealed so far, the stored matchup plan for
    them (exact or the closest already-written one), what this deck actually
    boarded the last few times it faced them, and a prompt to write an exact
    plan when none exists yet — see ``docs/current-match.md`` and
    ``table/intermission.py``."""

    game_number: int = Field(description="the game that just ended")
    next_game: int
    won: bool | None = None
    reason: str | None = Field(None, description="Arena's ResultReason_* verbatim")
    opponent: IntermissionOpponentOut | None = None
    cards_seen: int
    plan: MatchupBriefOut | None = None
    plan_basis: str | None = Field(None, description="exact | closest")
    plan_archetype_label: str | None = None
    stale: bool = Field(False, description="the corpus or the 75 has moved since plan was written")
    alternatives: list[AlternativePlanOut] = Field(default_factory=list)
    past_boarding: list[PastBoardingOut] = Field(default_factory=list)
    postboard_record: PostboardRecordOut | None = Field(
        None,
        description=(
            "This deck identity's earlier games 2 and 3 against the named or picked "
            "archetype, best-of-three matches only, the current match excluded; null when "
            "there is no archetype, no identity, or no such game."
        ),
    )
    record: PostboardRecordOut | None = Field(
        None,
        description=(
            "This match's games so far, the one just ended included, a drawn game in "
            "neither — from the break's own live read, so it never trails `won` the way "
            "the projected match can. Null when any of those games is unresolved."
        ),
    )
    prompt: str | None = Field(
        None, description="text to write an exact plan from, when none exists yet"
    )
    deck_key: str | None = None
    fmt: FormatName | None = Field(
        None,
        description=(
            "the match's format; null when unknown, "
            "and then no live read of the opponent is attempted"
        ),
    )


class CurrentMatchRead(BaseModel):
    """The current-match reads: an opening-hand read for a pending mulligan
    decision, a keep guide for the deck in play, a read on what the
    opponent may be holding, and our own remaining library. One route,
    polled every second while the page is open — see docs/current-match.md,
    "Wiring: one route".

    ``opening_hand`` is populated even with ``status == "no_match"``: it
    reads straight from ``raw_events`` and does not wait on a projected
    ``matches`` row (``table/opening_hand.py``)."""

    status: str = Field(description="ok | no_match")
    opening_hand: OpeningHandOut | None = None
    keep: KeepGuideOut | None = None
    hand: HandReadOut | None = None
    library: list[LibraryCardOut] = Field(default_factory=list)
    library_count: int | None = Field(
        None,
        description="our own library size right now, from the same live replay as `library` "
        "above — deliberately not the projected turns.self_library, which runs a rebuild "
        "behind (projector/live_state.py)",
    )
    source: str = Field(
        "arena",
        description="which client wrote the current match — always 'arena': v_current_match "
        "(migrations/040_arena_only_current_match.sql) only ever returns an Arena match, so "
        "this is 'arena' both when a match is current and when there is none at all",
    )
    intermission: IntermissionOut | None = Field(
        None,
        description="the Bo3 break card — set only between games, never mid-game "
        "(table/intermission.py)",
    )
    advice: bool = Field(
        False,
        description="the page may show advice now: the keep verdict and keep guide, the "
        "opponent-hand estimate, the matchup brief. False during a game in an event or an "
        "unknown queue, true in a casual or ladder one and between games (table/queues.py). "
        "The dashboard obeys it and never re-derives it; the user's own Settings switch can "
        "only hide more",
    )
