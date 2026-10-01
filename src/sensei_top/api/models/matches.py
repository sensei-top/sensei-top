"""The match list/detail drill-down, the opponent-deck override, the
post-game report and its digest, and the per-game sideboarding diff —
everything under the ``matches`` tag except the current-match and
narrative reads, which have their own files.

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from sensei_top.api.models.current_match import CurrentCardEvent, CurrentTurn


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
    free-text path any more — the label always names either an
    ``archetype_key`` the picker showed, or the fixed ``'Rogue'`` category."""

    label: str = Field(max_length=80)
    archetype_key: str | None = Field(
        None, description="one of the keys from GET .../opponent-deck/candidates; null for Rogue"
    )


class Match(BaseModel):
    match_id: str
    source: str = Field(description="the client that logged this match: 'arena' or 'mtgo'")
    event_id: str | None = None
    deck_id: str | None = None
    deck_name: str | None = None
    # Kept although the dashboard no longer shows it: it is what Arena said,
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
    rank_class: str | None = Field(
        None,
        description="constructed rank at the most recent snapshot at or before started_at "
        "(rank_snapshot); null when no snapshot precedes this match, and always null for "
        "an MTGO match, which has no Arena rank; never guessed",
    )
    rank_level: int | None = Field(
        None, description="paired with rank_class; e.g. 4 in 'Platinum 4'"
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
    """One named number a finding was computed from — the same identity a
    Phase B aggregate rollup would later group and average on, which is why
    ``key`` is a stable identifier rather than free text."""

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
        True, description="kept for wire compatibility; GET .../narrative always serves a "
        "prompt, and POST there generates it with Claude when a credential is configured"
    )


class SideboardCardOut(BaseModel):
    """One card whose copy count changed between two consecutive games'
    decks — the sideboarding decision itself, not the plan someone wrote
    down (see brief/'s own BoardCardOut for that authored version)."""

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
