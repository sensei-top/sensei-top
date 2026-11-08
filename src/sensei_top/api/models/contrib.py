"""The contributed games' wire models: the game keys and the records
``GET /api/contrib/records`` serves the desktop shell's main process, which
sends them (every field is one the privacy policy lists for contributed
games). A field the log never recorded is absent from the JSON, not null.

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from sensei_top.api.models.metagame import FormatName


class ContribSides(BaseModel):
    """One turn's cards, by the seat that played them; a side is absent when
    a card of its own had no name."""

    mine: list[str] | None = Field(default=None, alias="self", description="card names, in order")
    opp: list[str] | None = Field(default=None, description="card names, in order")


class ContribLife(BaseModel):
    mine: int | None = Field(default=None, alias="self")
    opp: int | None = None


class ContribTurn(BaseModel):
    n: int = Field(description="the turn's number, both players' turns counted")
    drawn: list[str] | None = Field(default=None, description="the cards we drew; Arena only")
    played: ContribSides | None = Field(default=None, description="lands played and spells cast")
    life: ContribLife | None = Field(default=None, description="Arena only")


class ContribDeck(BaseModel):
    main: list[tuple[str, int]] = Field(description="[card name, copies], by name")
    side: list[tuple[str, int]] = Field(description="[card name, copies], by name")


class ContribArchetype(BaseModel):
    key: str | None = Field(default=None, description="the archetype definition's key")
    label: str = Field(description="the name the app gave the deck")


class ContribArchetypes(BaseModel):
    mine: ContribArchetype | None = Field(default=None, alias="self")
    opp: ContribArchetype | None = None


class ContribRecord(BaseModel):
    schema_version: Literal[1]
    client: Literal["arena", "mtgo"]
    format: FormatName | None = None
    event: Literal["ranked", "play", "limited", "event"] | None = Field(
        default=None, description="the event's class, never Arena's raw id"
    )
    best_of: int | None = None
    week: str | None = Field(default=None, description="ISO year and week, e.g. 2026-W33")
    rank: str | None = Field(default=None, description="Arena's rank class, never the step")
    game: int = Field(description="which game of the match")
    on_play: bool | None = None
    mulligans: int | None = None
    kept_hand: list[tuple[str, int]] | None = Field(
        default=None,
        description="[card name, copies] on offer at our keep, the cards then put on the "
        "bottom included",
    )
    deck: ContribDeck | None = Field(default=None, description="the deck this game was played with")
    turns: list[ContribTurn]
    result: Literal["win", "loss", "draw"]
    turn_count: int | None = None
    archetypes: ContribArchetypes | None = None
    policy_version: str = Field(description="as the caller sent it")


class ContribRecordItem(BaseModel):
    key: str = Field(description="the game's key, as asked; never part of the record sent")
    record: ContribRecord
