"""Pydantic response models shared by more than one router: leaves that
appear inside a model defined in another ``api/models/`` file (``LeakOut``
in both ``guide.py`` and ``review.py``; ``BoardCardOut``/``PlanProblemOut``
in ``guide.py``'s own matchup plan), plus the handful of top-level models
(``Health``, ``LiveStatus``, ``Deck``, ``LLMStatus``, ``NarrativeResponse``)
with no router of their own worth a whole file.

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str
    database: str
    decks: int
    matches: int
    games: int
    turns: int


class LiveStatus(BaseModel):
    """Heartbeat for the dashboard's auto-refresh.

    Everything is read from the database, including ``watching``'s
    companion ``last_projection_at``: ``serve --watch`` runs the watcher in
    its own OS process now, not this one (``live.py``'s ``WatcherProcess`` —
    a rebuild sharing this process's GIL taxed every request ~5x), so
    nothing here can be read from in-memory watcher state. Only
    ``watching``, ``mtgo_watching`` and ``watcher_stopped`` are still asked
    of the watcher object directly (``is_alive()`` on the child process, the
    MTGO directory it was started with, and ``stopped_unexpectedly()``, which
    serve's own monitor thread sets), since none needs shared memory to
    answer. ``arena_log`` is the one field that is neither: the watcher's own
    path, or while it waits what the same resolver finds now.
    """

    watching: bool = Field(description="a watcher is running and reachable from this server")
    mtgo_watching: bool = Field(
        False,
        description="the running watcher has an MTGO game-log directory and stores each "
        "game from it once the game ends",
    )
    arena_log: str | None = Field(
        None,
        description="the Arena log the watcher reads or, while it waits, the one it will "
        "start reading at its next look (within 60 s); the home directory is written as ~; "
        "null with no watcher or nothing found",
    )
    watcher_stopped: bool = Field(
        False,
        description="the watcher child exited on its own after serve started it; "
        "nothing new is ingested until a restart",
    )
    last_ingest_at: str | None = Field(
        None,
        description="when new events last landed — not when the reader last looked",
    )
    last_checked_at: str | None = Field(None, description="when the reader last polled the log")
    last_event_at: str | None = Field(None, description="newest in-game timestamp seen")
    last_projection_at: str | None = Field(
        None,
        description="when project()'s full rebuild last completed — the actual freshness of "
        "turns/matches, which lags last_ingest_at by up to project_every plus the rebuild's own "
        "duration (read from projection_state, written by whichever process last ran project(); "
        "null before any watcher has ever completed a rebuild against this database).",
    )
    events: int
    matches: int
    games: int
    turns: int
    revision: str = Field(
        description="changes on every ingest tick while Arena is running (roughly once a "
        "second) — drives only the live badge/heartbeat, never a query refetch. See "
        "projection_revision for the one that should invalidate the dashboard's own queries."
    )
    projection_revision: str = Field(
        description="changes only when project()'s full rebuild commits — what the dashboard "
        "actually invalidates its queries on. Unlike revision, this does not move on every "
        "ingest tick, so an idle-but-connected dashboard does not refetch everything every few "
        "seconds just because Arena wrote a new raw event."
    )


class Deck(BaseModel):
    deck_id: str
    name: str | None = None
    format: str | None = Field(None, description="Arena's own spelling, e.g. 'TraditionalStandard'")
    matches_played: int = Field(description="every match, including one still in progress")
    matches_won: int
    last_played: str | None = None
    first_played: str | None = Field(
        None, description="when the deck's earliest match started, across every source"
    )
    first_seen: str | None = None
    last_seen: str | None = None


class LLMStatus(BaseModel):
    """Whether a Claude credential is resolved right now — never the key
    itself. The frontend reads this once to decide whether a narrative
    surface offers a generate button or falls back to ``CopyPromptCard``."""

    configured: bool
    model: str | None = Field(None, description="the model a generate call would use")


class NarrativeResponse(BaseModel):
    """The narrative's answer, or why there isn't one yet. Shared by the
    match-report and leak-finder narrative routes — both are "one prose
    blob over some evidence", so one shape serves them.

    ``status`` is ``'ok'`` once ``POST .../narrative`` has generated one,
    ``'prompt'`` when there is evidence but nothing stored yet, ``'no_report'``
    when there is nothing to narrate at all. The GET route is always a 200:
    'nothing to narrate' is an ordinary outcome for an opt-in feature, not a
    server error. A missing credential only matters to the POST route
    (503 there) — the GET route never needs one, since it only serves what
    is already stored plus the copyable prompt.
    """

    status: str = Field(description="ok | prompt | no_report")
    narrative: str | None = Field(
        None, description="the stored prose, once generated or (match report only) imported"
    )
    prompt: str | None = Field(
        None,
        description="the full text to write the narrative from — pass it to POST on this "
        "same path to generate it with Claude (see docs/llm.md), or into an assistant you "
        "already pay for and store the answer through the CLI import path",
    )
    model: str | None = Field(None, description="what wrote the stored narrative")
    generated_at: str | None = Field(None, description="when the stored narrative was written")
    cost_usd: float | None = Field(
        None, description="measured cost of the call that wrote it; null for a hand-written one"
    )
    stale: bool = Field(False, description="the evidence has changed since this was written")
    error: str | None = Field(None, description="set when something could not be built")


class LeakOut(BaseModel):
    """One recurring pattern from ``review/leaks.py``, ranked by how much it
    moves this player's own win rate — never a percentage without the
    sample size and interval behind it."""

    code: str
    category: str
    sample_title: str
    n_with: int
    win_rate_with: float
    ci_with: tuple[float, float]
    n_without: int
    win_rate_without: float
    ci_without: tuple[float, float]
    gap: float
    match_ids_with: list[str] = Field(
        description="matches this pattern appeared in, for drill-through"
    )


class BoardCardOut(BaseModel):
    card: str
    n: int


class PlanProblemOut(BaseModel):
    archetype: str
    message: str


# See brief/__init__.py for why this is the one computed package allowed to
# persist its own output, and brief/narrative.py for what is (and is never)
# sent — no board state, no game, ever, which is what makes it a function of
# two decklists rather than a description of play under AGENTS.md rule 5.


class PlayAroundOut(BaseModel):
    card: str
    why: str


class StapleOut(BaseModel):
    name: str
    copies: float
    share: float


class MatchupBriefOut(BaseModel):
    deck_key: str
    archetype_key: str
    archetype_label: str | None
    archetype_share: float | None = Field(
        description="this archetype's share of the classified field, 0..1"
    )
    personal_matches: int | None
    personal_wins: int | None
    personal_losses: int | None
    prose: str
    play_around: list[PlayAroundOut]
    board_in: list[BoardCardOut]
    board_out: list[BoardCardOut]
    staples: list[StapleOut]
    problems: list[PlanProblemOut] = Field(
        description="sideboard plan problems caught by guide.plans.validate_plans, never repaired"
    )
    model: str
    generated_at: str
    corpus_commit: str | None
    source: str = Field(description="'live' (this exact matchup) or 'guide' (backfilled)")


class MatchupBriefResponse(BaseModel):
    """The live brief's answer, or why there isn't one yet. Always a 200:
    no key configured, no live match, an unidentified opponent, and a brief
    the watcher hasn't written yet are all ordinary outcomes for an
    auto-firing, best-effort feature, not server errors.
    """

    status: str = Field(description="ok | prompt | unclassified | no_match | no_consensus | "
        "format_unknown (the deck has no format, so there is no field to read)")
    deck_key: str | None = Field(
        None, description="this match's deck identity — for the `brief --import` command line"
    )
    archetype_key: str | None = Field(None, description="the opponent's archetype key")
    brief: MatchupBriefOut | None = Field(
        None, description="the imported brief for this matchup, when one has been stored"
    )
    prompt: str | None = Field(
        None,
        description="the full text to write this brief from — copy it into an assistant you "
        "already pay for, then `sensei-top brief --deck KEY --archetype KEY --import FILE`",
    )
    stale: bool = Field(False, description="the corpus has moved since this brief was written")
    error: str | None = Field(None, description="set when something could not be built")


class PastedAnswerIn(BaseModel):
    """A pasted answer: the whole text the assistant gave back, header and
    all (``answers.read_answer``). Read, never sent anywhere: a ``PUT`` that
    takes this makes no model call."""

    answer: str = Field(
        description="the assistant's answer exactly as it gave it, from the prompt's "
        "answer contract; over 256 KB is a 413"
    )
