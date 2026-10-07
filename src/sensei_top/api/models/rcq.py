"""The RCQ guide's four routes — ``/api/guide/{key}/rcq*`` (``docs/guide.md``).

Field names are the frontend's contract (``web/src/lib/rcq.ts``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from sensei_top.api.models.common import BoardCardOut, PlanProblemOut
from sensei_top.api.models.guide import ListDiffOut
from sensei_top.api.models.metagame import FormatName


class RcqRecentShareOut(BaseModel):
    archetype: str
    archetype_key: str | None
    share: float
    decks: int


class RcqRecentEventOut(BaseModel):
    date: str
    name: str
    source: str
    tier: str
    decks: int
    top8: list[str]


class RcqFreshnessOut(BaseModel):
    source: str
    newest_event: str | None
    fetched_at: str | None


class RcqExpectedOut(BaseModel):
    key: str
    name: str
    share: float | None
    wins: int | None  # None: this deck has never faced it
    losses: int | None
    carryable: bool | None  # False: the rate is from before a reset that changed the archetype


class RcqPreviewOut(BaseModel):
    format: FormatName | None = Field(
        description="the deck's format; null when unknown, in which case the 75 is not "
        "classified and there is no field to read"
    )
    main_count: int
    side_count: int
    warnings: list[str]
    unresolved: list[str]
    own_archetype_key: str | None
    own_archetype_name: str | None
    own_unclassified_reason: str | None
    list_diff: ListDiffOut | None
    recent_shares: list[RcqRecentShareOut]
    recent_events: list[RcqRecentEventOut]
    freshness: list[RcqFreshnessOut]
    expected: list[RcqExpectedOut]
    prompt: str | None


class RcqGenerateIn(BaseModel):
    decklist: str
    expected: list[str] = []
    own: str | None = None


class RcqMatchupOut(BaseModel):
    archetype: str
    prose: str
    play_draw: str
    board_in: list[BoardCardOut]
    board_out: list[BoardCardOut]


class RcqFlexNoteOut(BaseModel):
    card: str
    role: Literal["core", "flex", "risk"]
    why: str


class RcqNarrativeOut(BaseModel):
    game_plan: str
    expected_field: str
    matchups: list[RcqMatchupOut]
    flex_notes: list[RcqFlexNoteOut]
    checklist: list[str]
    problems: list[PlanProblemOut]


class RcqGuideOut(BaseModel):
    status: Literal["ok", "none"]
    id: int | None
    generated_at: str | None
    model: str | None
    cost_usd: float | None
    decklist_text: str | None
    expected: list[str]
    guide: RcqNarrativeOut | None


class RcqMarkdownOut(BaseModel):
    markdown: str
