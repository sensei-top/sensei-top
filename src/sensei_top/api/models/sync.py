"""The cloud-backup payloads — ``/api/sync/payloads``. Read by the desktop
shell's main process, which uploads them; every field is one the privacy
policy lists for cloud backup.

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
