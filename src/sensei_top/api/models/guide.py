"""The deck guide's whole evidence bundle and its authored narrative —
``/api/guide/*`` (``docs/guide.md``).

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sensei_top.api.models.common import BoardCardOut, LeakOut, PlanProblemOut

# See guide/bundle.py for the assembly this section translates; every field
# here mirrors a guide/ dataclass one-to-one so this module stays the only
# place that decides the wire shape.


class DeckIdentityOut(BaseModel):
    """One deck, stitched across list edits via ``deck_guids`` — see
    ``guide/deck.py``. ``key`` is what every other guide route takes.
    ``deck_ids`` is every content-hash version this identity groups — the
    dashboard's global deck filter selects a bare ``deck_id``, so the
    frontend needs this list to find which guide identity a filter
    selection belongs to."""

    key: str
    arena_deck_id: str | None
    name: str | None
    format: str | None
    deck_ids: list[str]
    matches: int
    match_wins: int
    match_losses: int
    games_won: int
    games_lost: int
    first_played: str | None
    last_played: str | None


class FormatResetOut(BaseModel):
    date: str
    cards: list[str]
    detected_from: str


class ProvenanceOut(BaseModel):
    deck: DeckIdentityOut
    reset: FormatResetOut | None
    window_start: str | None
    matches_before_reset: int
    corpus_fetched_at: str | None
    corpus_latest_event: str | None
    classified_decks: int
    oracle_coverage: tuple[int, int] = Field(
        description="(cards with oracle text, cards in your current 75)"
    )


class PlayEvidenceOut(BaseModel):
    """Four views of the deck's own play — see ``guide/play.py``. Each
    field is a nested JSON object keyed by turn, card name, or result
    ('win'/'loss'), not a fixed schema; the frontend renders these
    directly rather than the API imposing a shape on data whose keys are
    inherently dynamic."""

    board_curve: dict[str, Any]
    zone_curve: dict[str, Any]
    key_card_timing: dict[str, Any]
    mulligan_record: dict[str, Any]
    game_length: dict[str, Any]


class CardVerdictOut(BaseModel):
    card: str
    yours: int
    board: str = Field(description="main | side")
    consensus_copies: float | None
    consensus_share: float | None
    recommended: int
    verdict: str = Field(description="correct | add | trim | cut | flex")


class ListDiffOut(BaseModel):
    archetype_key: str
    archetype_name: str
    winning_decks: int
    min_wins: int
    maindeck: list[CardVerdictOut]
    sideboard: list[CardVerdictOut]
    duplicate_warnings: list[str]


class ArchetypeShareOut(BaseModel):
    archetype: str
    decks: int
    share: float
    share_before_reset: float | None
    movement: float | None


class ArchetypeChangeOut(BaseModel):
    archetype: str
    pre_reset_decks: int
    fraction_playing_a_banned_card: float
    banned_cards: list[str]
    post_reset_decks: int
    verdict: str = Field(description="intact | changed | gone")
    carryable: bool


class PersonalRateOut(BaseModel):
    archetype: str
    matches: int
    wins: int
    losses: int
    carryable: bool = Field(
        description="false when the reset voided this archetype's pre-reset identity"
    )


class DeckPerformanceOut(BaseModel):
    decks: int
    wins: int
    losses: int
    win_rate: float | None


class FieldEvidenceOut(BaseModel):
    fmt: str | None
    window_start: str | None
    classified_decks: int
    shares: list[ArchetypeShareOut]
    changes: dict[str, ArchetypeChangeOut]
    personal_rates: list[PersonalRateOut]
    own_performance: DeckPerformanceOut | None
    corpus_fetched_at: str | None
    corpus_latest_event: str | None


class DeckGuideOut(BaseModel):
    provenance: ProvenanceOut
    play: PlayEvidenceOut
    leaks: list[LeakOut] = Field(description="this deck's own recurring patterns")
    leaks_all_decks: list[LeakOut] = Field(description="the same patterns across every deck")
    list_diff: ListDiffOut | None
    field: FieldEvidenceOut
    gaps: list[str]


class CardNoteOut(BaseModel):
    card: str
    verdict: str
    why: str


class MatchupPlanOut(BaseModel):
    archetype: str
    prose: str
    board_in: list[BoardCardOut]
    board_out: list[BoardCardOut]


class GuideNarrativeOut(BaseModel):
    engine: str
    fix: str
    card_notes: list[CardNoteOut]
    matchups: list[MatchupPlanOut]
    checklist: list[str]
    problems: list[PlanProblemOut] = Field(
        description="sideboard plans that failed validation against the real 75"
    )


class GuideNarrativeResponse(BaseModel):
    """Mirrors ``NarrativeResponse`` closely, with the structured guide
    attached when ``status == 'ok'``. Always a 200, same reasoning."""

    status: str = Field(description="ok | prompt | no_report")
    guide: GuideNarrativeOut | None = Field(
        None, description="the stored narrative, once generated or imported for this deck"
    )
    prompt: str | None = Field(
        None,
        description="the full text to write the narrative from — pass it to POST on this "
        "same path to generate it with Claude, or into an assistant you already pay for and "
        "`sensei-top guide --deck KEY --import FILE` the answer back",
    )
    authored_at: str | None = Field(None, description="when the stored narrative was written")
    author: str | None = Field(None, description="who or what wrote it — a model id, or free text")
    cost_usd: float | None = Field(
        None, description="measured cost of the call that wrote it; null for a hand-written one"
    )
    stale: bool = Field(False, description="the 75 has changed since this was written")
    error: str | None = Field(None, description="set when something could not be built")


class GuideMarkdownOut(BaseModel):
    markdown: str


class CoverageRowOut(BaseModel):
    """One archetype worth having a brief for — see ``brief/coverage.py``."""

    archetype_key: str
    label: str | None
    times_faced: int
    field_share: float | None = Field(
        None, description="this archetype's windowed share of the field, 0..1; null only "
        "when the window has no classified decks at all"
    )
    status: str = Field(
        description="ok | stale | missing | no_consensus (no brief, and too few field "
        "decklists to write one from); format_unknown never appears on a row, it is "
        "the whole deck's answer (fmt null, no rows)"
    )


class CoverageOut(BaseModel):
    fmt: str | None = Field(
        description="the deck's format; null when unknown: there is no field, so no rows"
    )
    rows: list[CoverageRowOut]
    matches_covered: float | None = Field(
        description="share of this deck's classified, decided matches whose opponent archetype "
        "has an ok brief; null when the deck has no classified matches yet"
    )
    matches_covered_numerator: int
    matches_covered_denominator: int
    field_covered: float = Field(description="summed windowed field share of every ok row")


class BriefPromptOut(BaseModel):
    """The single-brief prompt for one archetype, fetched on demand — the
    same text ``sensei-top brief --deck KEY --archetype KEY --prompt``
    prints. Always a 200: no field consensus is an ordinary outcome for a
    corpus that hasn't classified that archetype yet, not a server error."""

    status: str = Field(description="ok | no_consensus | format_unknown")
    archetype_key: str
    prompt: str | None = Field(None, description="the text to write this brief from")


class CoveragePromptOut(BaseModel):
    """The multi-brief prompt for every ``missing``/``stale`` coverage row —
    the same text ``sensei-top brief --deck KEY --missing --prompt``
    prints. Always a 200: nothing missing, or no field consensus for any
    missing/stale archetype, are both ordinary outcomes."""

    status: str = Field(description="ok | nothing_missing | no_consensus | format_unknown")
    prompt: str | None = Field(None, description="the text to write these briefs from")
    included: list[str] = Field(description="archetype keys this prompt covers")
    no_consensus: list[str] = Field(
        description="missing/stale archetype keys skipped for lack of field consensus"
    )
    deferred: list[str] = Field(
        description="missing/stale archetype keys past this prompt's own limit"
    )
