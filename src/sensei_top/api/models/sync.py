"""The cloud backup's wire models: the payloads ``GET /api/sync/payloads``
serves the desktop shell's main process, which uploads them (every field is
one the privacy policy lists for cloud backup), and the cloud rows it hands
back to ``PUT /api/sync/pulled``.

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

from sensei_top.api.models.metagame import FormatName


class SyncDeck(BaseModel):
    name: str | None = Field(description="the deck's own name, as the client saved it")
    main: list[tuple[str, int]] = Field(description="[card name, copies], by name")
    side: list[tuple[str, int]] = Field(description="[card name, copies], by name")


class SyncOpponent(BaseModel):
    label: str = Field(description="the name the app gave the opponent's deck")
    key: str = Field(description="its grouping identity, as matchups group on it")


class SyncOpponentPick(BaseModel):
    label: str
    archetype_key: str | None
    updated_at: str = Field(description="UTC ISO-8601, when the user last set it")


class SyncMtgoPick(BaseModel):
    format: FormatName | None
    updated_at: str = Field(description="UTC ISO-8601, when the user last set it")


class SyncPicks(BaseModel):
    opp: SyncOpponentPick | None = Field(description="the user's pick of the opponent's deck")
    mtgo: SyncMtgoPick | None = Field(
        description="the user's pick of their own MTGO deck and format; the deck itself is "
        "the payload's deck"
    )


class SyncMatchPayload(BaseModel):
    schema_version: Literal[1]
    played_at: str | None = Field(description="UTC ISO-8601; null when the log never said")
    event: str | None = Field(description="Arena's event id; always null for MTGO")
    format: FormatName | None
    best_of: int | None
    deck: SyncDeck | None
    result: Literal["win", "loss", "draw", "incomplete"] | None
    won: int | None = Field(description="games won")
    lost: int | None = Field(description="games lost")
    play: Literal["play", "draw"] | None = Field(description="game 1 only")
    opp: SyncOpponent | None = Field(description="null when the opponent's deck is unknown")
    opp_cards: list[str] = Field(description="distinct names of the opponent's cards seen")
    duration_s: int | None = Field(
        description="Seconds from the match's start to its end; null for an MTGO match, whose "
        "log shows only when it was first seen, not when it began."
    )
    unknown_cards: int = Field(
        description="cards left out for having no name: each deck copy, and each distinct "
        "opponent card"
    )
    picks: SyncPicks


class SyncPayload(BaseModel):
    match_id: str = Field(description="Arena's or MTGO's own id for the match")
    source: str = Field(description="arena | mtgo")
    played_at: str | None = Field(description="the payload's played_at, for ordering")
    digest: str = Field(
        description="SHA-256 hex of the payload's canonical JSON (sorted keys, no "
        "whitespace); a changed digest is a payload to push again"
    )
    payload: SyncMatchPayload


class SyncPulledMatch(BaseModel):
    """One row of the user's cloud backup, as the shell's main process pulled
    it."""

    match_id: str = Field(min_length=1, description="Arena's or MTGO's own id for the match")
    source: Literal["arena", "mtgo"]
    played_at: AwareDatetime | None = Field(None, description="the cloud row's played_at")
    payload: dict[str, Any] = Field(
        description="the payload as the cloud holds it; stored as received, never checked "
        "against this install's schema"
    )
    schema_version: int = Field(ge=1)
    updated_at: AwareDatetime = Field(description="when the cloud row last changed")
    deleted_at: AwareDatetime | None = Field(
        None, description="set when the user deleted the match from their backup"
    )


class SyncPulledIn(BaseModel):
    """One batch of pulled rows, written in one transaction, in order."""

    items: list[SyncPulledMatch] = Field(max_length=1000)


class SyncPulledWritten(BaseModel):
    stored: int = Field(description="restored matches written to this install")
    removed: int = Field(description="restored matches deleted, the cloud having deleted them")
    local: int = Field(
        description="rows for a match this install read from its own log, never stored: "
        "only their picks are considered"
    )
    picks: int = Field(description="local picks replaced by a newer pulled one")
