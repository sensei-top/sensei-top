"""The match list/detail drill-down, the opponent-deck override, the MTGO
deck pick, the post-game report and its digest, and the per-game sideboarding diff —
everything under the ``matches`` tag except the current-match and
narrative reads, which have their own files.

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from sensei_top.api.models.current_match import CurrentCardEvent, CurrentTurn
from sensei_top.api.models.metagame import FormatName
from sensei_top.mtgo.formats import MTGO_FORMATS


class OpponentDeck(BaseModel):
    """What the opponent was playing, and how much to trust the answer.

    Arena never sends the opponent's decklist, so this is inferred from the
    cards they revealed. ``opponent_key`` rather than the label is what
    matchups group on: an archetype whose name carries its colours can be
    labelled differently from match to match depending on what we happened to
    see, and grouping on the text would split one matchup in two.
    """

    opponent_label: str = Field(
        description="'Azorius Momo', or 'WUBR · Jeskai Revelation' when unclassified"
    )
    opponent_key: str = Field(description="grouping identity; matchups aggregate on this")
    opponent_source: str = Field(
        description="manual | archetype | fallback | corpus | colors | unknown"
    )
    opponent_confidence: str = Field(
        description="high | medium | low | unknown; below medium the dashboard offers to relabel"
    )
    opponent_cards_seen: int = Field(description="distinct nonland cards they revealed")
    opponent_colors: str | None = Field(
        None,
        description="WUBRG letters the opponent revealed (v_opponent_cards.colors), never the "
        "archetype's assumed colours; null when nothing colored was revealed or a revealed card's "
        "colours are unknown — those two cases are indistinguishable, so both render as nothing, "
        "never the word 'Colourless'",
    )


class SignatureCard(BaseModel):
    """One card a candidate archetype is known for, and whether the opponent
    has shown it yet — the opponent-deck read's own shortlist material
    (``OpponentRead.tsx``)."""

    name: str
    seen: bool


class OpponentDeckCandidate(BaseModel):
    """One deck the opponent might be playing, for the picker to offer.

    Ranked best-evidenced first; "Rogue" (a deck with no established
    archetype) is not among these — it is always available and always last,
    and the dashboard adds it itself rather than the API inventing a fake
    archetype for it.
    """

    archetype_key: str = Field(description="pass back to PUT .../opponent-deck to pick this one")
    label: str
    kind: str = Field(description="archetype | fallback")
    confidence: str = Field(description="high | medium | low | none")
    fit: float = Field(
        description="how well this candidate matches what's been seen, in [0, 1] — "
        "proof of its requirements times colour agreement; drives the shortlist's fit bar"
    )
    evidence: list[str] = Field(default_factory=list, description="matched cards, if any")
    reasons: list[str] = Field(
        default_factory=list,
        description="why this candidate sits where it does: matched cards, a missing colour, "
        "or (for a 'none' candidate) the seen card that ruled it out",
    )
    signature_cards: list[SignatureCard] = Field(
        default_factory=list,
        description="empty for confidence 'none' candidates, to keep that long tail light",
    )
    picked: bool = Field(
        False, description="whether this is the match's current opponent_deck_override"
    )


class OpponentDeckLabelIn(BaseModel):
    """A pick from the candidate list, or ``'Rogue'`` for a deck with no
    established archetype. An empty label clears the override. There is no
    free-text path — the label always names either an
    ``archetype_key`` the picker showed, or the fixed ``'Rogue'`` category."""

    label: str = Field(max_length=80)
    archetype_key: str | None = Field(
        None, description="one of the keys from GET .../opponent-deck/candidates; null for Rogue"
    )


# The formats an MTGO match can be played in, read from the one list
# (`mtgo/formats.py`); migration 049's CHECK is the same list. There is no
# "other". Type checkers reject a variable inside `Literal`, so
# the ignore below is safe: at runtime the tuple expands to the seven formats.
MtgoFormat = Literal[MTGO_FORMATS]  # type: ignore[valid-type]


class MtgoPickIn(BaseModel):
    """The user's answer for an MTGO match, replacing any earlier one whole.

    Either field may be null but not both: a format may be confirmed without a
    deck. ``deck_id`` is one of the ids from ``GET .../mtgo-pick/candidates``.
    """

    deck_id: str | None = Field(
        None,
        description="a deck_id from GET .../mtgo-pick/candidates; null to confirm only a format",
    )
    format: MtgoFormat | None = Field(
        None, description="one of the seven MTGO formats; null to confirm only a deck"
    )


class MtgoPickItem(BaseModel):
    """One match's answer inside a bulk write; the fields mean what
    ``MtgoPickIn``'s do."""

    match_id: str
    deck_id: str | None = Field(
        None, description="a deck_id from GET /api/mtgo/picks/candidates; null for a format only"
    )
    format: MtgoFormat | None = Field(None, description="one of the seven MTGO formats")


class MtgoPicksIn(BaseModel):
    """Many picks written together: every one is accepted or none is."""

    items: list[MtgoPickItem] = Field(min_length=1, max_length=1000)


class MtgoPicksWritten(BaseModel):
    written: int = Field(description="how many picks were written")


class MtgoPick(BaseModel):
    """An MTGO match's deck and format as the user has confirmed them, read
    from ``v_match_deck``."""

    deck_id: str | None = None
    format: MtgoFormat | None = None
    deck_confirmed: bool = Field(
        description="true once the match has a pick, even one that confirms only a format"
    )


class MtgoDeckCandidate(BaseModel):
    deck_id: str
    name: str | None = Field(None, description="the deck file's name, without its extension")
    cards_matched: int = Field(
        description="how many of the distinct cards the user played in this match, among those "
        "that resolve to an Arena card, this deck's list holds, maindeck or sideboard"
    )
    format_prefill: MtgoFormat | None = Field(
        None,
        description="the format MTGO's deck store files this deck under, else the format "
        "most recently confirmed for this same deck on any match, else the format inferred "
        "for this match from the cards it revealed; null when none exists. "
        "A suggestion only: the user still confirms",
    )
    format_prefill_source: Literal["deck_store", "last_pick", "inferred"] | None = Field(
        None,
        description="which step gave format_prefill: the deck store, the last pick for this "
        "deck, or this match's inferred format; null when format_prefill is null",
    )
    card_names: list[str] = Field(
        default_factory=list,
        description="up to five of the deck's card names to tell decks apart, basic lands "
        "left out. Spells before lands (a double-faced card by its front face); within each, "
        "cards the user played in this match first, then more maindeck copies, then name. "
        "A sideboard-only card counts as zero copies",
    )


class MtgoPickCandidates(BaseModel):
    """The MTGO decks to offer for one match, best-matching first. Every deck
    is listed, one that matches nothing included, so the user can always pick."""

    cards_seen: int = Field(
        description="distinct cards the user played in this match that resolve to an Arena "
        "card; the denominator for every candidate's cards_matched"
    )
    candidates: list[MtgoDeckCandidate]
    current: MtgoPick | None = Field(
        None, description="the match's existing pick; null when it has none"
    )


class MtgoNeedsPick(BaseModel):
    """An MTGO match the user has not yet confirmed a deck or format for."""

    match_id: str
    opponent_name: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    result: str | None = None
    games_won: int | None = None
    games_lost: int | None = None


class MtgoMissingCard(BaseModel):
    name: str
    matches: int = Field(description="in how many of the group's matches the user played it")


class MtgoGroupList(BaseModel):
    """One list a group of waiting matches could be confirmed as."""

    deck_id: str
    name: str | None = Field(None, description="the deck file's name, without its extension")
    top: bool = Field(description="true for a list at the top of the group's matches")
    close_in: int = Field(
        description="in how many of the group's matches this list was within 2 cards of the "
        "top without being on it; 0 for a top list"
    )
    format_prefill: MtgoFormat | None = None
    format_prefill_source: Literal["deck_store", "last_pick", "inferred"] | None = Field(
        None,
        description="as on the single pick, except the inferred step is the most common "
        "inferred format among the group's matches",
    )
    card_names: list[str] = Field(default_factory=list)
    missing: list[MtgoMissingCard] = Field(
        default_factory=list,
        description="up to 8 cards the user played in the group's matches that this list "
        "lacks, by number of matches then name",
    )


class MtgoWaitingMatch(BaseModel):
    """What the bulk page shows of an MTGO match that waits for a deck."""

    match_id: str
    started_at: str | None = None
    opponent_name: str | None = None
    result: str | None = None
    games_won: int | None = None
    games_lost: int | None = None
    cards_seen: int


class MtgoGroupMatch(MtgoWaitingMatch):
    scores: dict[str, int] = Field(
        description="deck_id to cards matched, for every list in the group's lists"
    )


class MtgoBestList(BaseModel):
    deck_id: str
    name: str | None = None
    cards_matched: int


class MtgoUnsurePick(MtgoWaitingMatch):
    """A waiting match no list fits well enough to group."""

    reason: Literal["few_cards", "low_fit", "no_list"]
    best: MtgoBestList | None = None
    format: str | None = Field(
        None, description="the format inferred for the match; null when none was"
    )


class MtgoPickGroup(BaseModel):
    """Waiting MTGO matches that share a top list; confirming is the user's click."""

    key: str
    fit: Literal["sure", "partial"]
    proposed: str | None = Field(
        None, description="the top list's deck_id; null on a tie, when the user chooses"
    )
    lists: list[MtgoGroupList] = Field(
        description="top lists first, then close lists by close_in desc, then name"
    )
    matches: list[MtgoGroupMatch] = Field(description="newest first")
    first_started: str | None = None
    last_started: str | None = None


class MtgoPickHints(BaseModel):
    """Archetypes read from the user's own played cards; never stored."""

    groups: dict[str, str | None] = Field(
        description="group key to the most common archetype, partial groups only"
    )
    unsure: dict[str, str | None] = Field(description="match id to its archetype")


class MtgoPickGroups(BaseModel):
    waiting: int = Field(description="MTGO matches with no pick yet")
    mtgo_matches: int = Field(description="every MTGO match, picked or not")
    groups: list[MtgoPickGroup] = Field(
        description="sure before partial, then by match count desc, then the first list's name"
    )
    unsure: list[MtgoUnsurePick] = Field(description="newest first")


class Match(BaseModel):
    match_id: str
    source: str = Field(description="the client that logged this match: 'arena' or 'mtgo'")
    event_id: str | None = None
    deck_id: str | None = None
    deck_name: str | None = None
    # Kept although no page shows it from this model: it is what Arena said,
    # and dropping honest data from the contract to enforce a display choice
    # would put that decision in the wrong layer.
    opponent_name: str | None = None
    opponent_label: str | None = None
    opponent_key: str | None = None
    opponent_source: str | None = None
    opponent_confidence: str | None = None
    opponent_cards_seen: int = 0
    opponent_colors: str | None = Field(
        None,
        description="WUBRG letters the opponent revealed (v_opponent_cards.colors), never the "
        "archetype's assumed colours; null when nothing colored was revealed or a revealed "
        "card's colours are unknown — those two cases are indistinguishable",
    )
    started_at: str | None = None
    ended_at: str | None = None
    result: str | None = None
    games_won: int | None = None
    games_lost: int | None = None
    best_of: int | None = Field(
        None,
        description="3 for a best-of-three match, 1 for a best of one, null when the log never "
        "said (Arena's matchWinCondition; every MTGO match is 3).",
    )
    game1_result: str | None = Field(
        None,
        description="Game 1's result ('win', 'loss' or 'draw') when the match is a best of three "
        "and game 1 finished; null otherwise.",
    )
    postboard_won: int | None = Field(
        None, description="Games 2 and 3 won, for a best-of-three match; null otherwise."
    )
    postboard_lost: int | None = Field(
        None,
        description="Games 2 and 3 lost, for a best-of-three match; null otherwise. A drawn "
        "game is in neither count.",
    )
    rank_class: str | None = Field(
        None,
        description="constructed rank at the most recent snapshot at or before started_at "
        "(rank_snapshot); null when no snapshot precedes this match, and always null for "
        "an MTGO match, which has no Arena rank; never guessed",
    )
    rank_level: int | None = Field(
        None, description="paired with rank_class; e.g. 4 in 'Platinum 4'"
    )
    format: FormatName | None = Field(
        None,
        description="the match's format (v_match_format); null when it is unknown or not a "
        "tracked format",
    )


class MatchGame(BaseModel):
    game_number: int
    on_play: bool | None = None
    result: str | None = None
    result_reason: str | None = None
    self_mulligans: int | None = None
    opp_mulligans: int | None = None
    turn_count: int | None = Field(None, description="player-turns, not rounds")
    turns: list[CurrentTurn]
    cards: list[CurrentCardEvent]


class MatchDetail(Match):
    """One match with every game's turns and card events — the history drill-down."""

    self_seat: int | None = Field(
        None, description="Arena's systemSeatNumber for us; a turn is ours when active_seat matches"
    )
    games: list[MatchGame]


class ReportEvidence(BaseModel):
    """One named number a finding was computed from. ``key`` is a stable
    identifier rather than free text; ``label`` names it for a reader."""

    key: str
    label: str
    value: float | int | str | bool | None = None
    unit: str | None = None
    display: str | None = Field(
        None, description="a human phrase for `value`, e.g. '0.49 — a decisive swing'; "
                           "`value` itself stays the raw number to group or graph on"
    )


class ReportFinding(BaseModel):
    code: str = Field(description="stable across matches; e.g. 'turning_point'")
    analyzer: str
    category: str = Field(
        description="frame | clock | trajectory | role | information | resources | baseline"
    )
    severity: str = Field(description="note | notice | flag | decisive")
    confidence: str = Field(description="observed | partial")
    title: str
    detail: str
    game_number: int | None = None
    turn_number: int | None = Field(None, description="player-turn, not round")
    self_turn_index: int | None = Field(None, description="which of your own turns this was")
    evidence: list[ReportEvidence] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    pattern: str | None = Field(
        None, description="this code's own cross-match name, when it is a leak candidate "
                           "(review/leaks.py); null means it never enters that ranking"
    )


class ReportGap(BaseModel):
    """What the report could not evaluate, and why — kept separate from
    findings so silence is never mistaken for 'nothing was wrong' (AGENTS.md
    rule 4)."""

    analyzer: str
    reason: str
    game_number: int | None = None


class PositionPoint(BaseModel):
    """One turn's position index (review/position.py) — a transparent,
    fixed-weight formula over life/board/hand/mana, never fitted to
    outcomes. Computed here, not in the frontend, so there is exactly one
    implementation of the formula."""

    game_number: int
    turn_number: int
    self_turn_index: int
    index: float


class SummaryBeat(BaseModel):
    """One compact digest line — review/summary.py's own ``Beat``."""

    code: str
    label: str
    text: str
    magnitude: str | None = None
    severity: str
    game_number: int | None = None
    meter: tuple[float, float] | None = Field(
        None, description="(self, opp) for a two-sided proportional bar, e.g. the damage race"
    )
    turn_number: int | None = Field(
        None, description="The source finding's player-turn; None when it has none"
    )
    definition: str | None = Field(
        None, description="One plain sentence saying what a game beat's label measures; None "
        "when the label has none, and on every matchup beat"
    )


class SummaryGameLine(BaseModel):
    game_number: int
    result: str | None = None
    result_reason_text: str | None = None
    turn_count: int | None = None
    on_play: bool | None = None
    self_mulligans: int | None = None
    beats: list[SummaryBeat] = Field(default_factory=list)


class SummaryGapGroup(BaseModel):
    cause: str
    blocked: list[str] = Field(default_factory=list)


class MatchSummaryOut(BaseModel):
    """review/summary.py's own digest: a headline, a per-game read and the
    report's gaps collapsed to their real root causes — computed from the
    same ``MatchReport`` as ``findings``/``gaps`` below, never a second
    read of the database."""

    headline: str
    subhead: str | None = None
    matchup: list[SummaryBeat] = Field(default_factory=list)
    games: list[SummaryGameLine] = Field(default_factory=list)
    gap_groups: list[SummaryGapGroup] = Field(default_factory=list)


class MatchReportOut(BaseModel):
    """The post-game report: local, deterministic findings recomputed on
    every request rather than stored — see ``review/__init__.py`` for why."""

    match_id: str
    summary: MatchSummaryOut
    findings: list[ReportFinding]
    gaps: list[ReportGap]
    position_track: list[PositionPoint] = Field(
        default_factory=list,
        description="one point per turn with both life totals recorded; see review/position.py",
    )
    narrative_available: bool = Field(
        True, description="always true, kept for wire compatibility; GET .../narrative serves "
        "a prompt whenever there is something to narrate, and POST there generates it with "
        "Claude when a credential is configured"
    )


class SideboardCardOut(BaseModel):
    """One card whose copy count changed between two consecutive games'
    decks — the sideboarding decision itself, not the plan someone wrote
    down (``BoardCardOut`` in ``api/models/common.py`` is that authored
    version)."""

    grp_id: int
    card: str | None = Field(
        None, description="null until 'sensei-top cards' has downloaded the card table"
    )
    n: int = Field(description="net copies changed, always positive")


class SideboardGameOut(BaseModel):
    game_number: int
    cards_in: list[SideboardCardOut] = Field(
        description="present in this game's deck, absent (or fewer copies) in the previous game's"
    )
    cards_out: list[SideboardCardOut] = Field(
        description="present in the previous game's deck, absent (or fewer copies) in this one"
    )


class SideboardingOut(BaseModel):
    match_id: str
    games: list[SideboardGameOut] = Field(
        description="one entry per game whose post-board deck was actually captured — "
        "game 1 is never included, since it is simply the match's own maindeck"
    )
