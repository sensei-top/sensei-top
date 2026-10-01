"""The coach report's evidence bundle and its authored narrative —
``/api/coach*`` (``docs/coach.md``).

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.

Every model here mirrors a ``coach/evidence.py`` or ``coach/store.py``
dataclass field for field (``api/routes/coach.py``'s ``_evidence_out``/
``_report_out`` do the conversion explicitly, never via ``model_validate``
on a dataclass instance). Two evidence fields are deliberately left off
``CoachEvidenceModel``: ``examples`` and ``decklists`` are prompt-only —
the Coach tab never renders either, so there is nothing here for the
frontend to receive.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RateModel(BaseModel):
    """One win rate, split out of ``coach.evidence.Rate`` — ``ci`` (a tuple
    there) becomes ``ci_low``/``ci_high`` here since a plain 2-tuple gives
    the frontend nothing to name each half by."""

    wins: int
    n: int
    rate: float | None = Field(
        None, description="None at n=0 — never a bare 0%, which would read as always losing"
    )
    ci_low: float
    ci_high: float
    anecdotal: bool = Field(description="below the leak finder's own minimum sample")


class DeckLineOut(BaseModel):
    label: str
    archetype: str | None
    matches: RateModel
    g1: RateModel
    post_board: RateModel
    on_play: RateModel
    on_draw: RateModel


class MatchupLineOut(BaseModel):
    archetype: str
    rate: RateModel
    variants: list[tuple[str, int]] = Field(
        description="other opponent_label wordings that voted for this same archetype key, "
        "count desc"
    )


class LeakLineOut(BaseModel):
    code: str
    category: str
    pattern: str
    present: RateModel
    absent: RateModel
    gap: float


class DeckLeaksOut(BaseModel):
    deck_label: str
    leaks: list[LeakLineOut]


class TurningBucketOut(BaseModel):
    stage: str = Field(description="early (your turns 1-3) / mid (4-6) / late (7+)")
    severity: str
    games: int


class FieldLineOut(BaseModel):
    archetype: str
    variants: list[tuple[str, int]]
    decks: int
    share: float
    your_rate: RateModel


class CoachEvidenceModel(BaseModel):
    """Mirrors ``coach.evidence.CoachEvidence``, minus three fields: ``source``
    (always ``"all"`` in v1 — there is no source query parameter, see
    ``api/routes/coach.py``), ``format_population`` (the ``gaps`` lines
    already say how many matches each exclusion reason removed), and
    ``examples``/``decklists`` (prompt-only, per the module docstring
    above)."""

    as_of: str | None
    population: int
    window_start: str | None
    overall: RateModel
    overall_games: RateModel
    g1: RateModel
    post_board: RateModel
    on_play: RateModel
    on_draw: RateModel
    by_deck: list[DeckLineOut]
    by_role: dict[str, RateModel]
    mulligans: dict[str, RateModel]
    by_opponent: list[MatchupLineOut]
    leaks: list[LeakLineOut]
    deck_leaks: list[DeckLeaksOut]
    turning_points: list[TurningBucketOut]
    field: list[FieldLineOut]
    field_latest_event: str | None
    gaps: list[str]


class CoachModelOption(BaseModel):
    """One choice in the Coach tab's model dropdown — ``llm.client.
    REPORT_MODELS`` plus its own price, resolved server-side so the
    dashboard never has to know the pricing table."""

    id: str = Field(description="the model id to send back as CoachGenerateRequest.model")
    label: str = Field(description="display label, e.g. 'Opus 5.5'")
    input_per_mtok: float | None = Field(None, description="$/MTok input, None if unpriced")
    output_per_mtok: float | None = Field(None, description="$/MTok output, None if unpriced")


class CoachGenerateRequest(BaseModel):
    """``POST /api/coach/narrative``'s optional body — the dropdown's
    choice, or absent/``None`` to keep using the configured coach model."""

    model: str | None = Field(
        None, description="a REPORT_MODELS id, or None to use the configured coach model"
    )


class CoachReportSummary(BaseModel):
    """One row of report history — the Coach tab's list of past reports,
    each opening the full report on request rather than carrying it here."""

    id: int
    generated_at: str
    model: str
    effort: str | None
    cost_usd: float | None
    web_search_requests: int | None


class CoachResponse(BaseModel):
    """The Coach tab's free, local half: the evidence for its profile
    tables, and every report ever written. Always a 200 — an empty
    database and a database below the leak finder's minimum sample are
    both ordinary states for a brand-new install, not server errors."""

    sufficient: bool = Field(
        description="False below the leak finder's minimum sample of constructed matches — "
        "evidence is None in that case"
    )
    evidence: CoachEvidenceModel | None
    reports: list[CoachReportSummary] = Field(description="newest first")
    default_model: str | None = Field(
        None,
        description="the model a report is written with when the dropdown is left alone — the "
        "configured coach model, or None when no credential is configured",
    )
    models: list[CoachModelOption] = Field(
        default_factory=list, description="REPORT_MODELS, in order, for the model dropdown"
    )


class CoachSource(BaseModel):
    """One citation a stored report actually used — either a reading-list
    entry (``coach.canon.CANON``) or a web page ``llm.write_report``'s
    search tool visited."""

    kind: str = Field(description="reading | web")
    label: str = Field(description='"R3" for a reading-list entry, the page title for a web one')
    url: str
    title: str | None = Field(
        None, description="author and title for a reading entry, the page title for a web one"
    )
    cited_text: str | None = Field(None, description="web citations only")


class CoachNarrativeResponse(BaseModel):
    """The coach report's answer, or why there isn't one yet — same
    three-state shape as ``NarrativeResponse``, extended with the coach's
    own measured web-search cost and its resolved source list.

    ``status`` is ``'ok'`` once a report has been generated, ``'prompt'``
    when there is evidence but nothing stored yet, ``'no_report'`` when
    there isn't even enough evidence for a prompt. The GET routes are
    always a 200; only the POST route's missing-credential and
    insufficient-data cases are errors (503/404 — see
    ``api/routes/coach.py``).
    """

    status: str = Field(description="ok | prompt | no_report")
    id: int | None = Field(None, description="this stored report's id, once one exists")
    narrative: str | None = Field(None, description="the stored prose, once generated")
    prompt: str | None = Field(
        None,
        description="the full text to write the report from — pass it to POST on this same "
        "path to generate it with Claude (see docs/llm.md), or into an assistant you already "
        "pay for and store the answer through the CLI import path",
    )
    model: str | None = Field(None, description="what wrote the stored report")
    effort: str | None = Field(None, description="the reasoning effort the call used")
    generated_at: str | None = Field(None, description="when the stored report was written")
    cost_usd: float | None = Field(
        None, description="measured cost of the call that wrote it, including web search"
    )
    input_tokens: int | None = None
    output_tokens: int | None = None
    web_search_requests: int | None = None
    sources: list[CoachSource] = Field(
        default_factory=list, description="every citation the stored report actually used"
    )
    stale: bool = Field(
        False, description="the evidence has changed since this was written — only meaningful "
        "for the latest report"
    )
    error: str | None = Field(None, description="set when something could not be built")
