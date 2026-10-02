"""The field's own numbers: real tournament presence, win rates and
matchups, tiered by evidence quality — ``/api/metagame/*``
(``docs/metagame.md``).

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OpponentSourceBreakdown(BaseModel):
    """How the classifier resolves completed Standard matches — the number a
    stale archetype cache would move. See ``standard_opponent_source_breakdown``."""

    archetype: int
    fallback: int
    colors: int
    manual: int
    unknown: int
    total: int


class MetaTierCounts(BaseModel):
    a: int = Field(description="paper tournament of 64 or more players — win rate and matchups")
    b: int = Field(description="MTGO challenge — win rates and meta share, matchups at tiny n")
    c: int = Field(description="MTGO league — presence only, no losses recorded at all")
    d: int = Field(description="paper tournament under 64 players — win rate and matchups")


class MetaSourceStatus(BaseModel):
    source: str = Field(description="'fbettega' or 'topdeck'")
    age_hours: float | None = Field(None, description="hours since this source was last refreshed")
    events: int = Field(description="events stored from this source in its last refresh")
    configured: bool = Field(
        description="topdeck only: whether an API key is set; always true for fbettega, "
        "which needs none"
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
    archetype_files: int
    archetype_definitions_url: str | None = Field(
        None,
        description="which host the current definitions came from — the primary "
        "Badaro/MTGOFormatData archive, or the Jiliac fallback if the primary failed",
    )
    standard_opponent_sources: OpponentSourceBreakdown
    corpus_commit_sha: str | None = Field(
        None, description="the fbettega/MTG_decklistcache commit every stored event was read from"
    )
    corpus_age_hours: float | None = Field(
        None, description="hours since the tournament corpus was last refreshed; null if never"
    )
    corpus_window_days: int | None = Field(None, description="the date window of the last refresh")
    corpus_events_by_tier: MetaTierCounts
    corpus_duplicate_events: int = Field(
        description="stored tournament events set aside as a byte-identical twin of another "
        "one already counted (metagame/dedup.py) — excluded from corpus_events_by_tier"
    )
    corpus_sources: list[MetaSourceStatus] = Field(
        default_factory=list,
        description="per-source freshness — 'fbettega' (MTGO+Melee cache) always present once "
        "fetched at least once; 'topdeck' (TopDeck.gg RCQs) only once configured or fetched",
    )
    format_reset_start: str | None = Field(
        None,
        description="the first day of the current post-reset window (the latest detected "
        "Standard ban's window_start), or null when no reset has been detected; drives the "
        "Field page's default 'Since the last reset' window",
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
    Place"), not a score. See docs/metagame.md."""

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
