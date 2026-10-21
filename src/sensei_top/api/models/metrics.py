"""The ``/api/metrics/*`` winrate/curve endpoints — each a thin ``SELECT``
over one metric view. See docs/architecture.md, "Aggregation: views versus
Python".

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DeckWinrate(BaseModel):
    deck_key: str | None = Field(
        description="'guid:<arena_deck_id>', or 'deck:<hash>' when Arena never named one; "
        "null on the one row that counts every match with no deck recorded, which for an "
        "MTGO match is one the user has not picked a deck for"
    )
    arena_deck_id: str | None = None
    deck_name: str | None = None
    versions: int = Field(
        description="distinct maindeck content hashes rolled into this deck; 0 on the "
        "row of matches with no deck"
    )
    matches_completed: int
    matches_won: int
    games_won: int
    games_lost: int
    winrate: float | None = Field(None, description="matches_won / matches_completed; null if none")


class PlayDrawWinrate(BaseModel):
    deck_id: str | None = Field(
        description="null for matches with no deck recorded; an MTGO match has one only "
        "when the user picked it"
    )
    deck_name: str | None = None
    on_play: bool
    games_completed: int
    games_won: int
    winrate: float | None = None


class GameLength(BaseModel):
    deck_id: str | None = Field(
        description="null for matches with no deck recorded; an MTGO match has one only "
        "when the user picked it"
    )
    deck_name: str | None = None
    turn_count: int = Field(description="player-turns, not rounds: 24 means 12 turns each")
    games: int
    games_won: int
    winrate: float | None = None


class TurnCurve(BaseModel):
    deck_id: str | None = Field(
        description="null for matches with no deck recorded; an MTGO match has one only "
        "when the user picked it"
    )
    deck_name: str | None = None
    turn_number: int = Field(description="player-turn number; both seats alternate")
    samples: int
    avg_self_life: float | None = None
    avg_opp_life: float | None = None
    avg_self_hand: float | None = None
    avg_opp_hand: float | None = None
    avg_self_lands: float | None = None
    avg_self_permanents: float | None = None
    avg_opp_permanents: float | None = None


class RankWinrate(BaseModel):
    """One rank tier's match record, so a Platinum grind and a Mythic run
    are not averaged into the same winrate. Grouped by (constructed_class,
    constructed_level) at the latest rank observed at or before each
    match's start; both fields are null together for an Arena match with no
    rank_snapshot before it and for every MTGO match
    (``migrations/046_rank_winrate_arena_only.sql``)."""

    constructed_class: str | None = None
    constructed_level: int | None = None
    matches_completed: int
    matches_won: int
    games_won: int
    games_lost: int
    winrate: float | None = Field(
        None, description="matches_won / matches_completed; null if none played"
    )


class Matchup(BaseModel):
    format: str | None = Field(
        None, description="the format the matches were played in; null when none resolved"
    )
    opponent_key: str
    opponent_label: str
    deck_id: str | None = None
    deck_name: str | None = None
    matches_completed: int
    matches_won: int
    games_won: int
    games_lost: int
    winrate: float | None = Field(None, description="matches_won / matches_completed; null if none")
    last_played: str | None = None
    confidence_rank: int = Field(description="4 manual, 3 high, 2 medium, 1 low, 0 unidentified")
    opponent_colors: str | None = Field(
        None,
        description="WUBRG union across this row's matches (one key, deck and format); "
        "null when nothing colored was ever revealed, or every revealed card's colours are "
        "unknown — those two cases are indistinguishable, so both render as nothing",
    )
