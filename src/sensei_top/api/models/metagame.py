"""The field's own numbers: real tournament presence, win rates and
matchups, tiered by evidence quality — ``/api/metagame/*``
(``docs/metagame.md``).

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from sensei_top.formats import FORMATS

# The seven formats, read from the one list (`formats.py`). Type checkers
# reject a variable inside `Literal`; at runtime the tuple expands to the
# seven names, so an unknown `?format=` is a 422, not an empty answer.
FormatName = Literal[FORMATS]  # type: ignore[valid-type]


class OpponentSourceBreakdown(BaseModel):
    """How the classifier resolves one format's completed matches — the
    number a stale archetype cache would move. See
    ``archetypes.classify.opponent_source_breakdown``."""

    archetype: int
    fallback: int
    corpus: int = Field(description="named by the tournament corpus's own lists, not a rule")
    colors: int
    manual: int
    unknown: int
    total: int


class MetaTierCounts(BaseModel):
    a: int = Field(description="paper tournament of 64 or more players — win rate and matchups")
    b: int = Field(description="MTGO challenge — win rates and meta share, matchups at tiny n")
    c: int = Field(description="MTGO league — presence only, no losses recorded at all")
    d: int = Field(description="paper tournament under 64 players — win rate and matchups")


class MetaSourceHold(BaseModel):
    """A source's fetch hold that still stands (``metagame/holds.py``)."""

    status: Literal["waiting", "paused"] = Field(
        description="'paused' until the user acts, or 'waiting' for the not-before time"
    )
    http_status: int = Field(description="the answer that caused the hold")
    since: str = Field(description="when the hold began, UTC, %Y-%m-%dT%H:%M:%SZ")
    not_before: str | None = Field(
        None,
        description="no fetch before this time, whether the hold is waiting or paused; UTC, "
        "%Y-%m-%dT%H:%M:%SZ; null when none is stored",
    )


class MetaSourceStatus(BaseModel):
    source: str = Field(description="'fbettega', 'mtgo' or 'topdeck'")
    age_hours: float | None = Field(None, description="hours since this source was last refreshed")
    events: int = Field(description="events stored from this source in its last refresh")
    configured: bool = Field(
        description="topdeck only: whether an API key is set; always true for fbettega "
        "and mtgo, which need none"
    )
    hold: MetaSourceHold | None = Field(
        None, description="the hold on this source's fetch, only while it still stands"
    )


class MetagameStatus(BaseModel):
    """Whether the metagame layer has anything to show, and how fresh it is.

    Diagnostic, not a metric: read once when deciding whether the archetype
    cache or the tournament corpus needs attention, not polled by the live
    heartbeat.
    """

    archetype_cache_age_hours: float | None = Field(
        None, description="hours since the archetype definitions were last refreshed; null if never"
    )
    archetype_files: int = Field(description="archetype rules stored for this format")
    archetype_definitions_url: str | None = Field(
        None,
        description="which host the current definitions came from — the primary "
        "Badaro/MTGOFormatData archive, or the Jiliac fallback if the primary failed",
    )
    format: FormatName = Field(
        description="the format every per-format figure here is for: the one asked for, "
        "else the default /api/formats reports"
    )
    opponent_sources: OpponentSourceBreakdown = Field(
        description="how the user's completed matches of this format had their opponent named"
    )
    corpus_commit_sha: str | None = Field(
        None, description="the fbettega/MTG_decklistcache commit every stored event was read from"
    )
    corpus_age_hours: float | None = Field(
        None, description="hours since the tournament corpus was last refreshed; null if never"
    )
    corpus_window_days: int | None = Field(None, description="the date window of the last refresh")
    corpus_events_by_tier: MetaTierCounts = Field(
        description="this format's stored tournament events, by tier"
    )
    corpus_duplicate_events: int = Field(
        description="this format's stored tournament events set aside as a byte-identical "
        "twin of another one already counted (metagame/dedup.py) — excluded from "
        "corpus_events_by_tier"
    )
    corpus_topdeck_events: int = Field(
        description="this format's stored TopDeck.gg events (meta_event rows of source "
        "'Topdeck' in the format, duplicates set aside excluded); 0 when none are stored, "
        "including a configured key that has fetched nothing. corpus_sources' own event "
        "counts are the whole download's, not this format's"
    )
    corpus_sources: list[MetaSourceStatus] = Field(
        default_factory=list,
        description="per-source freshness — 'fbettega' (MTGO+Melee cache) and 'mtgo' "
        "(mtgo.com) once fetched; 'topdeck' (TopDeck.gg RCQs) only once configured or fetched. "
        "A source whose hold still stands also gets a row, even with no fetch row",
    )
    format_reset_start: str | None = Field(
        None,
        description="the first day of this format's current post-reset window (its latest "
        "detected ban's window_start), or null when no reset has been detected; drives the "
        "Field page's default 'Since the last reset' window",
    )


class FormatMatchCounts(BaseModel):
    """The user's matches of one format, by where ``v_match_format`` read the
    format from."""

    log: int = Field(description="Arena matches whose log names the format")
    pick: int = Field(description="MTGO matches the user confirmed in this format")
    inferred: int = Field(
        description="MTGO matches with no confirmed format, inferred from the cards revealed"
    )
    total: int


class FormatEntry(BaseModel):
    format: FormatName
    matches: FormatMatchCounts
    has_rules: bool = Field(description="whether archetype rules are stored for this format")
    corpus_events: int = Field(
        description="tournament events stored for this format, duplicates excluded"
    )


class FormatsOut(BaseModel):
    """Every format, in ``formats.py``'s order, and the one a page shows when
    its address names none."""

    formats: list[FormatEntry]
    default: FormatName = Field(
        description="the format of the user's most recent match that has one; Standard "
        "when no match has one"
    )


class MetaPresence(BaseModel):
    archetype_key: str
    label: str
    colors: str | None = Field(
        None,
        description=(
            "the colour combination most of this row's lists carry, ties to the first "
            "in text order; null when no list has colours"
        ),
    )
    tier: str
    decks: int
    share: float = Field(description="decks / total decks seen at this tier, in this window")


class MetaWinrate(BaseModel):
    """Wins/losses/draws are summed from ``Standings[]`` — each deck's real
    whole-event match record — never inferred from ``Decks[].Result``, which
    every real Tier A/B/D file carries as a bare placement string ("1st
    Place"), not a score. See docs/metagame.md, "A trap: `Decks[].Result` is
    not a score"."""

    archetype_key: str
    label: str
    colors: str | None = Field(
        None,
        description=(
            "the colour combination most of this row's lists carry, ties to the first "
            "in text order; null when no list has colours"
        ),
    )
    entries: int = Field(description="deck entries this archetype appeared as, in this window")
    matches_won: int
    matches_lost: int
    matches_drawn: int
    winrate: float | None = Field(
        None, description="matches_won / (won + lost + drawn); null if none played"
    )


class MetaMatchup(BaseModel):
    archetype_key: str
    label: str
    opponent_key: str
    opponent_label: str
    tier: str
    n: int = Field(description="matches this row is based on — never shown without it")
    matches_won: int
    matches_lost: int
    matches_drawn: int
    games_won: int
    games_lost: int
    winrate: float | None = Field(None, description="matches_won / n; null if n is 0")


class MetaEventRow(BaseModel):
    """One stored tournament event with at least one deck."""

    key: str = Field(description="the event's id without 'Tournaments/' and '.json'")
    name: str
    date: str | None = Field(None, description="event date, YYYY-MM-DD")
    format: str | None
    tier: str
    source: str
    lists: int = Field(description="decks that carry a mainboard")
    winner: str | None = Field(
        None, description="archetype label of the first deck placed 1st; null when unknown"
    )


class MetaRecord(BaseModel):
    wins: int
    losses: int
    draws: int


class MetaDeckArchetype(BaseModel):
    key: str
    label: str
    colors: str | None = None


class MetaCard(BaseModel):
    count: int
    name: str


class MetaCardGroup(BaseModel):
    type: str | None = Field(
        None, description="the card type of the group; null for cards of no known type"
    )
    count: int = Field(description="copies in the group")
    cards: list[MetaCard]


class MetaEventDeck(BaseModel):
    placement: int | None = Field(None, description="finishing place when the result names one")
    record: MetaRecord | None = Field(None, description="null when wins, losses and draws are 0")
    archetype: MetaDeckArchetype | None = None
    main: list[MetaCardGroup] = Field(description="mainboard by card type")
    side: list[MetaCard]


class MetaEventDetail(BaseModel):
    key: str
    name: str
    date: str | None = None
    format: str | None = None
    tier: str
    source: str
    uri: str | None = None
    lists_read_at: str | None = None
    empty_read_at: str | None = None
    empty_read_kind: Literal["empty", "gone"] | None = None
    decks: list[MetaEventDeck]
