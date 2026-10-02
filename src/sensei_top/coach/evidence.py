"""Coach evidence — the population every coaching report reasons over, and
a first layer of rollups on top of it.

``build_coach_evidence`` defines *the* population once — every rollup below
draws from the same filtered match set, so a number on one line of a report
can never silently disagree with another about which matches counted.
Arena and MTGO answer "is this Constructed?" from different evidence, so each
source has its own exclusion rules:

Arena, three exclusions:

* ``event_id IS NULL`` — a truncated session that never got one recorded.
  Genuinely rare on Arena; kept because ``event_id`` is otherwise trusted
  completely, and a future gap in it should read as a gap, not silently
  vanish.
* ``event_id`` in ``_EXCLUDED_EVENTS`` — events that are not a real ladder
  result (``DualColorPrecons``, a preconstructed-deck event).
* ``_is_limited_event(event_id)`` — a Limited queue (Quick, Premier,
  Traditional or Cube Draft), out of scope for a Constructed-focused report.

MTGO writes no ``event_id`` (``projector/mtgo/project.py`` always inserts
``NULL``), so it has no event to ask Arena's question of. Its
``matches.deck_id`` is ``NULL`` too, and MTGO's ``decks`` rows come from the
exported deck files (``projector/mtgo/decks.py``), reached only through the
user's own pick (``mtgo_match_pick``, read through ``v_match_deck``). Instead
of an event, ``match_formats`` (``archetypes/classify.py``) reads the match's
own revealed cards from both seats, and ``_population`` keeps an MTGO match
exactly when that verdict is ``"Standard"`` — excluding it otherwise into one
of five ``mtgo_*`` reasons (a revealed card not Standard-legal, one banned by
the time the match was played or with no ban date on file, one revealed card
whose name never resolved to a grp_id at all, one with no legality on file at
all, or too few distinct cards revealed to judge the format from). That
inference is only the fallback: a match whose pick confirms a format
(``v_match_deck.format``, the user's own answer) is read from the pick
instead — kept when it is Standard, excluded into ``mtgo_other_format`` when
it is any other of the seven formats — because the legality read cannot tell
Standard from a Modern deck built of new cards. A match with no confirmed
format (no pick, or a pick that names only a deck) stays on the inference.
A kept MTGO match carries ``deck_id = NULL`` until the user picks its deck: it counts in
``overall``/the skill splits/leaks/turning points but not in ``by_deck`` (rule
4 forbids inventing a deck identity for it), and ``gaps`` says so whenever at
least one such match is included. With a pick it counts under that deck like
an Arena match.

Every match that survives its source's own exclusions is the population.
Every exclusion reason that actually removed at least one match earns its
own line in ``gaps``, with a count — silence about an exclusion would look
like the report never noticed those matches existed.

Two windows sit on top of that one population, not two different
populations: the *skill* window (``overall``, ``overall_games``, ``by_deck``,
``by_role``, ``mulligans``) is the whole thing, because how you mulligan or
which role a matchup casts you in does not go stale the way a specific
opponent's metagame share does. The *format* window (``by_opponent``) is
restricted to ``started_at >= window_start(latest reset)`` — the same
never-window-across-a-ban rule ``guide/window.py`` exists to enforce,
applied here because an opponent-archetype rate from before the archetype
changed is void, not merely stale (``guide/field.py``'s own docstring).

``_build_match_reports`` returns a private ``match_id -> MatchReport`` map
rather than a field on ``CoachEvidence``: match ids must never appear on the
evidence at all (privacy), so they stay inside a private helper's return
value instead. A caller needing per-match reports again can call this same
helper over the same population and cache set rather than paying for a
second scan — the cross-module reuse of a leading-underscore helper already
has precedent here (``_classify_own_deck``, ``_card_colors_by_name``).

**The one exception to "match ids must never appear":**
``ExampleGame.match_id``. The report carries a handful of worked examples — real
games the report can point at — and the Coach tab needs a real match id to
link each one to its match page. That one field is the single place a match
id is allowed anywhere on this evidence; every other rollup still resolves
through a deck identity, an opponent archetype key, or a bare count. The
prompt builder (``coach/narrative.py``) must never render
``ExampleGame.match_id`` into a prompt — it exists for the UI link only, and
``tests/test_coach_evidence.py``'s privacy test asserts every other string on
the evidence contains no match id, opponent name, opponent user id, or deck
GUID, carving out only that one field.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass

from sensei_top.archetypes.classify import (
    _card_colors_by_name,
    match_format_reasons,
)
from sensei_top.guide.deck import DeckIdentity, list_identities
from sensei_top.guide.field import field_by_key
from sensei_top.guide.play import mulligan_split
from sensei_top.guide.window import format_resets, legality_known, window_start
from sensei_top.review.findings import MatchReport
from sensei_top.review.leaks import (
    MIN_SAMPLE,
    Leak,
    _mana_flags,
    _scope_clause,
    _wilson,
    find_leaks,
)
from sensei_top.review.match_report import build_match_report
from sensei_top.review.narrative import _finding_line, _play_lines, _turn_lines
from sensei_top.review.snapshot import _classify_own_deck, build_snapshot

# Arena's event-name prefix for each draft queue: "QuickDraft_SOS_20260831".
# Read off real captures when the draft assistant parsed them (archive/draft,
# projector/draft.py); an unrecognized prefix is not Limited.
_LIMITED_PREFIXES = frozenset({"QuickDraft", "PremierDraft", "TradDraft", "CubeDraft"})


def _is_limited_event(event_id: str) -> bool:
    parts = event_id.split("_")
    return len(parts) >= 2 and parts[0] in _LIMITED_PREFIXES


# Events that are not a real Constructed ladder result. Not Limited (that is
# _is_limited_event's job) and not "no event" (NULL is its own case) — just an
# event whose matches would misrepresent the population if left in.
_EXCLUDED_EVENTS = frozenset({"DualColorPrecons"})

TOP_DECKS = 8
TOP_OPPONENTS = 12
TOP_LEAKS = 8
TOP_DECK_LEAKS = 3
DECK_LEAK_MIN = 2 * MIN_SAMPLE  # a deck below this can never clear
                                 # _leak_from_counts' MIN_SAMPLE-per-side gate
TOP_DECKLISTS = 3
TOP_FIELD = 10
MAX_EXAMPLES = 3


@dataclass(frozen=True, slots=True)
class Rate:
    """One win rate, never shown without its own sample size and interval.

    ``rate`` is ``None`` at ``n == 0`` — never ``0.0``, which would read as
    "always loses" rather than "never happened" (rule 4). ``anecdotal`` flags
    every rate below ``MIN_SAMPLE`` the same way the leak finder already
    gates its own comparisons, so a caller rendering this can grey out or
    caveat a rate on sight rather than re-deriving the threshold itself.
    """

    wins: int
    n: int
    rate: float | None
    ci: tuple[float, float]
    anecdotal: bool


@dataclass(frozen=True, slots=True)
class DeckLine:
    label: str
    archetype: str | None
    matches: Rate
    g1: Rate
    post_board: Rate
    on_play: Rate
    on_draw: Rate


@dataclass(frozen=True, slots=True)
class MatchupLine:
    archetype: str
    rate: Rate
    # Every distinct opponent_label voted for this one opponent_key (a
    # rename, or a manual override wording an automatic classification's
    # archetype differently) — count desc, then label, so a caller can show
    # "also seen as ..." without re-deriving the vote _build_by_opponent
    # already took to pick `archetype` above.
    variants: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class LeakLine:
    """One ``review/leaks.py::Leak``, re-shaped through this package's own
    ``Rate`` so a coach report renders every number — leak or otherwise —
    through the same ``format_rate``. ``present``/``absent`` are rebuilt from
    ``Leak``'s own win-rate-and-n pair (``round(win_rate * n)`` for the win
    count Leak itself never stores, since it only ever kept the rate) rather
    than carrying ``Leak`` itself, so this package's public shape never leaks
    ``review/leaks.py``'s own dataclass to a caller that shouldn't need it.
    """

    code: str
    category: str
    pattern: str
    present: Rate
    absent: Rate
    gap: float


@dataclass(frozen=True, slots=True)
class DeckLeaks:
    deck_label: str
    leaks: tuple[LeakLine, ...]


@dataclass(frozen=True, slots=True)
class TurningBucket:
    """One (stage, severity) cell of the turning-point breakdown across every
    lost population game — always one of exactly 6 cells (3 stages x 2
    severities), even at ``games == 0``, so a caller can render a fixed grid
    rather than guess which cells exist this time (``mulligans``' own
    fixed-two-bucket precedent, extended to six)."""

    stage: str      # "early" (your turns 1-3) / "mid" (4-6) / "late" (7+)
    severity: str    # the turning_point finding's own Severity value
    games: int


@dataclass(frozen=True, slots=True)
class ExampleGame:
    """One worked example game, fully rendered — the only place a match id
    appears anywhere on ``CoachEvidence`` (module docstring). ``opponent`` is
    always the opponent's *deck label*, never a player name or handle."""

    match_id: str
    date: str | None
    game_number: int
    deck_label: str
    opponent: str
    on_play: bool | None
    mulligans: int | None
    chosen_for: str  # a Leak.code, or "recent_loss" when no leak qualified
    turn_lines: tuple[str, ...]
    play_lines: tuple[str, ...]
    finding_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeckList:
    """One kept ``by_deck`` identity's current 75, read the same way
    ``brief/narrative.py::_own_seventy_five_block`` reads its own deck's —
    ``(count, name)`` pairs, sorted by name. A grp_id with no matching
    ``cards`` row is counted in ``unnamed`` rather than rendered as ``"?"``
    (rule 4): the copy count is real, the name just isn't known yet."""

    label: str
    main: tuple[tuple[int, str], ...]
    side: tuple[tuple[int, str], ...]
    unnamed: int


@dataclass(frozen=True, slots=True)
class FieldLine:
    archetype: str
    variants: tuple[tuple[str, int], ...]
    decks: int
    share: float
    your_rate: Rate


@dataclass(frozen=True, slots=True)
class CoachEvidence:
    """The cross-deck report's own evidence base — never persisted itself
    (``coach/store.py`` persists the *report* written from this, not this).
    ``gaps`` stays last so new fields land above it, matching
    ``guide/bundle.py``'s ``DeckGuide``/``Provenance`` precedent.
    """

    source: str
    population: int
    format_population: int
    window_start: str | None  # None = no reset detected; format window = whole population
    as_of: str | None  # MAX(started_at) over the population — progress_since's own baseline
    overall: Rate
    overall_games: Rate
    g1: Rate
    post_board: Rate
    on_play: Rate
    on_draw: Rate
    by_deck: tuple[DeckLine, ...]
    by_source: dict[str, Rate]  # "arena" / "mtgo", always both keys
    by_role: dict[str, Rate]
    mulligans: dict[str, Rate]
    by_opponent: tuple[MatchupLine, ...]
    leaks: tuple[LeakLine, ...]
    deck_leaks: tuple[DeckLeaks, ...]
    turning_points: tuple[TurningBucket, ...]
    examples: tuple[ExampleGame, ...]
    decklists: tuple[DeckList, ...]
    field: tuple[FieldLine, ...]
    field_latest_event: str | None  # MAX(event_date) of a Standard meta_event
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PopMatch:
    """One population match's own fields, carried through every rollup below
    instead of re-querying ``matches`` per rollup.

    ``source`` defaults to ``"arena"`` only so every pre-existing direct
    construction (mostly in tests, predating MTGO's own inclusion here)
    keeps working unchanged; ``_population`` below always passes it
    explicitly, from ``matches.source`` itself.
    """

    match_id: str
    deck_id: str | None
    started_at: str | None
    result: str
    source: str = "arena"


def _rate(wins: int, n: int) -> Rate:
    return Rate(wins=wins, n=n, rate=(wins / n if n else None), ci=_wilson(wins, n),
                anecdotal=n < MIN_SAMPLE)


def _build_by_source(population_rows: list[_PopMatch]) -> dict[str, Rate]:
    """The same population, split the other way from ``by_deck`` — by
    ``matches.source`` rather than by deck identity. Always both keys, even
    at ``n == 0``, so a caller renders a fixed two-row table rather than
    guessing which source this report actually has data for (``mulligans``'
    own fixed-bucket precedent)."""
    by_source: dict[str, list[_PopMatch]] = {"arena": [], "mtgo": []}
    for m in population_rows:
        by_source[m.source].append(m)
    return {
        src: _rate(sum(1 for m in rows if m.result == "win"), len(rows))
        for src, rows in by_source.items()
    }


def _population(
    conn: sqlite3.Connection, source: str
) -> tuple[list[_PopMatch], dict[str, int]]:
    """Every completed match in scope, split into the population and a count
    per exclusion reason. Each match lands in exactly one bucket.

    Arena and MTGO ask a different question here, because they answer "is
    this Constructed?" from different evidence (``match_formats``'s own
    docstring). An Arena match is checked against ``event_id`` — is checked
    for NULL before it is ever passed to ``_is_limited_event``, and an
    excluded-event match is never also charged to the Limited bucket, exactly
    as before this function knew MTGO existed. An MTGO match whose pick
    confirms a format (``v_match_deck.format``) is decided by that format
    alone: included when it is ``"Standard"``, excluded into
    ``mtgo_other_format`` otherwise; the legality inference is never
    consulted for it. An MTGO match without a confirmed format instead goes
    through ``match_format_reasons``: included when its reason is
    ``"revealed_cards"`` (Standard), excluded into one of five ``mtgo_*``
    buckets otherwise — never into ``no_event_id``, which stays an Arena-only
    reading now that MTGO has its own real reason to report instead of a
    blanket "no event id" that was never quite true (MTGO's absent event_id
    was never the actual reason a match should or shouldn't count). An Arena
    match never reads the pick: v_match_deck applies it to MTGO matches only.
    """
    scope_sql, scope_params = _scope_clause(None, None, source)
    # The deck is v_match_deck's (the user's pick for an MTGO match, else what
    # the log named), not matches.deck_id. Wrapped so _scope_clause's bare
    # column names stay unambiguous: v_match_deck repeats match_id and source.
    rows = conn.execute(
        f"SELECT match_id, source, event_id, deck_id, pick_format, started_at, result FROM ("
        f"SELECT m.match_id, m.source, m.event_id, md.deck_id, md.format AS pick_format, "
        f"m.started_at, m.result "
        f"FROM matches m JOIN v_match_deck md ON md.match_id = m.match_id) "
        f"WHERE result IN ('win', 'loss'){scope_sql}",
        scope_params,
    ).fetchall()

    included: list[_PopMatch] = []
    excluded = {
        "no_event_id": 0, "excluded_event": 0, "limited": 0,
        "mtgo_not_legal": 0, "mtgo_banned": 0, "mtgo_unresolved_cards": 0,
        "mtgo_unknown_legality": 0, "mtgo_too_few_cards": 0, "mtgo_other_format": 0,
    }

    # Only paid for when an MTGO row is actually in scope — match_formats/
    # match_format_reasons each scan the whole database once, same cost
    # classify_matches already accepts for the same reason. A match with a
    # confirmed pick format never reads it, so it is not paid for when every
    # MTGO row in scope has one.
    mtgo_reasons = (
        match_format_reasons(conn)
        if any(row["source"] == "mtgo" and row["pick_format"] is None for row in rows)
        else {}
    )

    for row in rows:
        if row["source"] == "mtgo":
            if row["pick_format"] is not None:
                if row["pick_format"] != "Standard":
                    excluded["mtgo_other_format"] += 1
                    continue
            elif mtgo_reasons[row["match_id"]] != "revealed_cards":
                reason = mtgo_reasons[row["match_id"]]
                excluded[f"mtgo_{reason}"] += 1
                continue
            included.append(_PopMatch(
                match_id=row["match_id"], deck_id=row["deck_id"],
                started_at=row["started_at"], result=row["result"], source="mtgo",
            ))
            continue

        event_id = row["event_id"]
        if event_id is None:
            excluded["no_event_id"] += 1
            continue
        if event_id in _EXCLUDED_EVENTS:
            excluded["excluded_event"] += 1
            continue
        if _is_limited_event(event_id):
            excluded["limited"] += 1
            continue
        included.append(_PopMatch(
            match_id=row["match_id"], deck_id=row["deck_id"],
            started_at=row["started_at"], result=row["result"], source="arena",
        ))
    return included, excluded


def _game_rate(conn: sqlite3.Connection, match_ids: tuple[str, ...]) -> Rate:
    if not match_ids:
        return _rate(0, 0)
    placeholders = ",".join("?" for _ in match_ids)
    row = conn.execute(
        f"SELECT SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins, "
        f"COUNT(*) AS n FROM games WHERE match_id IN ({placeholders}) "
        f"AND result IN ('win', 'loss')",
        match_ids,
    ).fetchone()
    return _rate(row["wins"] or 0, row["n"] or 0)


def _deck_game_split(
    conn: sqlite3.Connection, match_ids: tuple[str, ...]
) -> tuple[Rate, Rate, Rate, Rate]:
    """(g1, post_board, on_play, on_draw), one query per deck line rather
    than four — the same four-way CASE-sum shape ``review/leaks.py``'s own
    aggregate queries use."""
    if not match_ids:
        empty = _rate(0, 0)
        return empty, empty, empty, empty
    placeholders = ",".join("?" for _ in match_ids)
    row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN game_number = 1 AND result IN ('win','loss') THEN 1 ELSE 0 END) AS g1_n,
            SUM(CASE WHEN game_number = 1 AND result = 'win' THEN 1 ELSE 0 END) AS g1_w,
            SUM(CASE WHEN game_number >= 2 AND result IN ('win','loss') THEN 1 ELSE 0 END) AS pb_n,
            SUM(CASE WHEN game_number >= 2 AND result = 'win' THEN 1 ELSE 0 END) AS pb_w,
            SUM(CASE WHEN on_play = 1 AND result IN ('win','loss') THEN 1 ELSE 0 END) AS play_n,
            SUM(CASE WHEN on_play = 1 AND result = 'win' THEN 1 ELSE 0 END) AS play_w,
            SUM(CASE WHEN on_play = 0 AND result IN ('win','loss') THEN 1 ELSE 0 END) AS draw_n,
            SUM(CASE WHEN on_play = 0 AND result = 'win' THEN 1 ELSE 0 END) AS draw_w
          FROM games WHERE match_id IN ({placeholders})
        """,
        match_ids,
    ).fetchone()
    return (
        _rate(row["g1_w"] or 0, row["g1_n"] or 0),
        _rate(row["pb_w"] or 0, row["pb_n"] or 0),
        _rate(row["play_w"] or 0, row["play_n"] or 0),
        _rate(row["draw_w"] or 0, row["draw_n"] or 0),
    )


def _own_archetype(
    conn: sqlite3.Connection, identity: DeckIdentity, colors_by_name: dict
) -> str | None:
    """This identity's own archetype, read the same way ``guide/field.py``'s
    ``build_field`` reads its own deck's: classify the most recently played
    ``deck_id`` under this identity from its full 60, event_id-less (rule 4 —
    an event-conditioned format guess is not this function's job)."""
    if not identity.deck_ids:
        return None
    placeholders = ",".join("?" for _ in identity.deck_ids)
    # Joined to v_match_deck on match_id, then filtered on its deck_id: no
    # index serves that view's COALESCE, so joining decks to it on deck_id
    # would scan the view once per deck (migration 050's header).
    row = conn.execute(
        f"""
        SELECT d.deck_id
          FROM matches m
          JOIN v_match_deck md ON md.match_id = m.match_id
          JOIN decks d ON d.deck_id = md.deck_id
         WHERE md.deck_id IN ({placeholders})
         GROUP BY d.deck_id ORDER BY MAX(m.started_at) DESC LIMIT 1
        """,
        identity.deck_ids,
    ).fetchone()
    if row is None:
        return None
    verdict, _ = _classify_own_deck(conn, row["deck_id"], None, colors_by_name=colors_by_name)
    return verdict.name if verdict is not None else None


def _build_by_deck(
    conn: sqlite3.Connection,
    population_rows: list[_PopMatch],
    colors_by_name: dict[str, frozenset[str]],
    identities: list[DeckIdentity],
) -> tuple[tuple[DeckLine, ...], str | None, list[tuple[str, DeckIdentity, list[_PopMatch]]]]:
    """``colors_by_name`` is ``_card_colors_by_name(conn)``'s own table,
    passed in rather than scanned here — the caller shares one scan of
    ``cards`` across this and every ``build_match_report`` call below.
    ``identities`` is likewise ``list_identities(conn)``'s own result,
    computed once by the caller: ``_build_examples`` needs every identity's
    label, not just the kept top-``TOP_DECKS`` ones, so ``build_coach_evidence``
    calls ``list_identities`` exactly once and shares it here rather than
    this function scanning ``v_deck_identity`` again for its own subset.

    Returns the kept ``(label, identity, rows)`` triples as a third value,
    beyond the usual ``(lines, gap)`` pair — ``_build_deck_leaks`` and
    ``_build_decklists`` both need the same top-``TOP_DECKS`` identities and
    their own population rows this function already computed, and
    recomputing the match-count sort a second time would just repeat this
    same work for a different caller.
    """
    by_deck_id: dict[str, list[_PopMatch]] = defaultdict(list)
    for m in population_rows:
        if m.deck_id is not None:
            by_deck_id[m.deck_id].append(m)

    candidates: list[tuple[str, DeckIdentity, list[_PopMatch]]] = []
    for identity in identities:
        rows = [r for did in identity.deck_ids for r in by_deck_id.get(did, ())]
        if not rows:
            continue
        candidates.append((identity.name or "Unnamed deck", identity, rows))

    # Top N by population match count, ties by label — never by last_played,
    # so this list is stable regardless of query order.
    candidates.sort(key=lambda c: (-len(c[2]), c[0]))
    kept, overflow = candidates[:TOP_DECKS], candidates[TOP_DECKS:]

    lines = []
    for label, identity, rows in kept:
        match_ids = tuple(r.match_id for r in rows)
        wins = sum(1 for r in rows if r.result == "win")
        g1, post_board, on_play, on_draw = _deck_game_split(conn, match_ids)
        lines.append(DeckLine(
            label=label,
            archetype=_own_archetype(conn, identity, colors_by_name),
            matches=_rate(wins, len(rows)),
            g1=g1, post_board=post_board, on_play=on_play, on_draw=on_draw,
        ))

    gap = None
    if overflow:
        n_matches = sum(len(rows) for _, _, rows in overflow)
        gap = (
            f"{len(overflow)} deck(s) beyond the top {TOP_DECKS} by sample size are not "
            f"shown in the per-deck table ({n_matches} matches)."
        )
    return tuple(lines), gap, kept


def _build_match_reports(
    conn: sqlite3.Connection,
    match_ids: tuple[str, ...],
    *,
    consensus_since: str | None,
    consensus_cache: dict,
    colors_cache: dict,
    view_cache: dict,
    report_cache: dict[tuple[str, str | None], MatchReport | None],
) -> dict[str, MatchReport]:
    """Every population match's own post-game report, built once. Private on
    purpose (see module docstring) — reusing this over the same population
    and cache pair costs nothing extra; a fresh call over a different
    population still shares the caches passed in.

    ``consensus_since`` is the format-reset window this module already
    computed (``format_resets``/``window_start`` — see ``build_coach_evidence``)
    and must be the *same* value passed to every other ``build_match_report``/
    ``build_snapshot``/``find_leaks`` call this module makes; it is required
    (no default) so a new call site here cannot silently forget it the way
    ``review/snapshot.py:632`` and ``api/sql.py:142`` once did.

    ``report_cache`` is filled here and reused across it: a caller pairing
    this with a later ``find_leaks(..., report_cache=...)`` call over the
    same matches builds nothing twice, since a ``MatchReport`` depends only
    on ``match_id``, ``consensus_since`` and the database, never on either
    caller's own scoping (``find_leaks``'s own docstring). The key is
    ``(match_id, consensus_since)`` to match ``find_leaks``'s own cache.

    ``build_match_report`` only returns ``None`` when the match itself is
    missing from ``matches`` (its own docstring) — unreachable for a
    match_id this module already read from that same table — but skipping a
    ``None`` here rather than raising keeps this defensive without pretending
    to explain an absence that cannot happen.
    """
    reports: dict[str, MatchReport] = {}
    for match_id in match_ids:
        cache_key = (match_id, consensus_since)
        if cache_key in report_cache:
            report = report_cache[cache_key]
        else:
            report = build_match_report(
                conn, match_id, consensus_since=consensus_since,
                consensus_cache=consensus_cache, colors_cache=colors_cache,
                view_cache=view_cache,
            )
            report_cache[cache_key] = report
        if report is not None:
            reports[match_id] = report
    return reports


def _match_role(report: MatchReport | None) -> str:
    """The role frame.py's ``role_assignment`` finding assigned this match,
    from its ``"role"`` Evidence — ``"unknown"`` whenever that finding never
    fired (own/opponent deck unclassified, too few tagged cards, no signal)
    or the report itself could not be built. Never guessed from anything
    else on the report (rule 4)."""
    if report is None:
        return "unknown"
    for finding in report.findings:
        if finding.code != "role_assignment":
            continue
        for ev in finding.evidence:
            if ev.key == "role":
                return str(ev.value)
    return "unknown"


def _build_by_role(
    population_rows: list[_PopMatch], reports: dict[str, MatchReport]
) -> dict[str, Rate]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # role -> [wins, n]
    for m in population_rows:
        bucket = counts[_match_role(reports.get(m.match_id))]
        bucket[1] += 1
        if m.result == "win":
            bucket[0] += 1
    # Unlike `mulligans` below, a role bucket that never occurred (e.g. no
    # "mixed" match in this population) is omitted rather than shown at
    # n=0 — the role vocabulary isn't a fixed two-way split the way kept/
    # mulliganed is, so an empty "control": Rate(n=0) line would just be
    # noise for whichever roles this population never produced.
    return {role: _rate(wins, n) for role, (wins, n) in counts.items() if n > 0}


def _build_mulligans(conn: sqlite3.Connection, match_ids: tuple[str, ...]) -> dict[str, Rate]:
    """Game-level, scoped to this report's own match population instead of
    one deck identity's ``deck_ids`` — ``guide/play.py``'s ``mulligan_split``
    bucket definitions (``self_mulligans == 0`` vs. ``> 0``, games with no
    recorded count excluded), the same definition ``mulligan_record`` itself
    now calls. Both keys are always present, even at n=0 — unlike ``by_role``
    above this is a fixed two-way split where "no mulliganed games in this
    population" is itself worth being able to show rather than omit.
    """
    empty = {"kept_seven": _rate(0, 0), "mulliganed": _rate(0, 0)}
    if not match_ids:
        return empty
    placeholders = ",".join("?" for _ in match_ids)
    split = mulligan_split(conn, f"m.match_id IN ({placeholders})", match_ids)
    return {bucket: _rate(wins, games) for bucket, (wins, games) in split.items()}


def _build_by_opponent(
    conn: sqlite3.Connection, format_rows: list[_PopMatch], results_by_id: dict[str, str]
) -> tuple[tuple[MatchupLine, ...], list[str], dict[str, tuple[int, int]]]:
    """Match-level rate per opponent archetype, over the format window only.

    Resolved from ``v_match_opponent.opponent_key``/``opponent_label`` —
    the same view ``v_matchup_winrate`` and ``guide/field.py``'s
    ``_personal_rate_rows`` are themselves built on — rather than
    re-deriving archetype resolution here. Unlike ``_personal_rate_rows``,
    which groups on ``archetype_name`` alone and so *deliberately* drops a
    manually-labelled match with no matching classifier verdict (its own
    docstring), this groups on ``opponent_key``: a manual pick that named a
    real archetype (``api/routes/matches.py``'s ``set_opponent_deck``, which
    sets ``archetype_key`` from the chosen candidate) produces
    ``'archetype:' + archetype_key`` — the same key an automatic
    classification of the same archetype would produce — so the two merge
    correctly. A manual pick with no archetype at all (the ``Rogue`` label)
    produces ``'manual:Rogue'``, which the ``LIKE 'archetype:%'`` filter
    below excludes, landing it in the unclassified gap line rather than
    being named — same treatment as a colour-only or fully unknown opponent.

    Returns a third value beyond the usual ``(lines, gaps)`` pair: every
    opponent_key's own ``(wins, n)``, not just the top ``TOP_OPPONENTS`` kept
    as ``MatchupLine``s. ``_build_field``'s own ``your_rate`` needs a rate
    for any archetype key the field corpus names — including one this
    report's opponent table itself cut for sample size — and an unfaced key
    needs to resolve to ``_rate(0, 0)`` rather than being missing entirely;
    recomputing this same scan a second time just to get it would repeat
    the exact grouping this function already did.
    """
    gaps: list[str] = []
    if not format_rows:
        return (), gaps, {}
    match_ids = tuple(m.match_id for m in format_rows)
    placeholders = ",".join("?" for _ in match_ids)
    rows = conn.execute(
        f"""
        SELECT match_id, opponent_key, opponent_label FROM v_match_opponent
         WHERE match_id IN ({placeholders}) AND opponent_key LIKE 'archetype:%'
        """,
        match_ids,
    ).fetchall()

    match_ids_by_key: dict[str, list[str]] = defaultdict(list)
    label_votes: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        match_ids_by_key[row["opponent_key"]].append(row["match_id"])
        label_votes[row["opponent_key"]][row["opponent_label"]] += 1

    classified = sum(len(mids) for mids in match_ids_by_key.values())
    unclassified = len(format_rows) - classified
    if unclassified:
        gaps.append(
            f"{unclassified} match(es) in the format window have no classified opponent "
            f"archetype and are not counted in the opponent-archetype table."
        )

    full_counts: dict[str, tuple[int, int]] = {}
    variants_by_key: dict[str, tuple[tuple[str, int], ...]] = {}
    candidates = []
    for key, mids in match_ids_by_key.items():
        # Every row sharing one opponent_key should already carry the same
        # opponent_label (same archetype_key names the same archetype
        # whether reached by manual pick or automatic classification); the
        # vote just picks the label a rename left the majority on. A tie
        # (e.g. one automatic classification plus one manual override with
        # different wording) breaks alphabetically rather than by row
        # order, which SQLite does not guarantee for a query with no
        # ORDER BY.
        label = min(label_votes[key].items(), key=lambda kv: (-kv[1], kv[0]))[0]
        wins = sum(1 for mid in mids if results_by_id.get(mid) == "win")
        full_counts[key] = (wins, len(mids))
        # Every distinct label this key has been given, count desc then
        # name — the same order-independent tie-break as the vote above,
        # just kept instead of collapsed to one winner.
        variants_by_key[key] = tuple(
            sorted(label_votes[key].items(), key=lambda lv: (-lv[1], lv[0]))
        )
        candidates.append((key, label, len(mids), wins))

    candidates.sort(key=lambda c: (-c[2], c[1]))
    kept, overflow = candidates[:TOP_OPPONENTS], candidates[TOP_OPPONENTS:]
    if overflow:
        gaps.append(
            f"{len(overflow)} opponent archetype(s) beyond the top {TOP_OPPONENTS} by sample "
            f"size are not shown in the opponent-archetype table."
        )

    lines = tuple(
        MatchupLine(archetype=label, rate=_rate(wins, n), variants=variants_by_key[key])
        for key, label, n, wins in kept
    )
    return lines, gaps, full_counts


def _leak_line(leak: Leak) -> LeakLine:
    present = _rate(round(leak.win_rate_with * leak.n_with), leak.n_with)
    absent = _rate(round(leak.win_rate_without * leak.n_without), leak.n_without)
    return LeakLine(
        code=leak.code, category=leak.category, pattern=leak.sample_title,
        present=present, absent=absent, gap=leak.gap,
    )


def _build_leaks(
    conn: sqlite3.Connection,
    match_ids: tuple[str, ...],
    *,
    source: str,
    consensus_since: str | None,
    consensus_cache: dict,
    colors_cache: dict,
    view_cache: dict,
    report_cache: dict[tuple[str, str | None], MatchReport | None],
) -> tuple[list[Leak], tuple[LeakLine, ...], list[str]]:
    """The population's own recurring patterns, ranked by win-rate gap —
    ``find_leaks`` already returns them in that order, so this only
    truncates to the top ``TOP_LEAKS``.

    ``consensus_since`` must be the same format-reset window value passed to
    ``_build_match_reports``/``_build_deck_leaks``/``_build_examples`` — see
    ``_build_match_reports``'s docstring; sharing ``report_cache`` across
    them only avoids rebuilding a report when every caller agrees on it.

    Returns the raw kept ``Leak`` objects too, beyond the rendered
    ``LeakLine`` tuple: ``_build_examples``' own selection needs
    ``Leak.match_ids_with`` and ``Leak.win_rate_with``/``win_rate_without``,
    neither of which survives into ``LeakLine`` (module docstring's privacy
    rule keeps a match id off every public shape but ``ExampleGame``).
    """
    all_leaks = find_leaks(
        conn, match_ids=match_ids, source=source, consensus_since=consensus_since,
        consensus_cache=consensus_cache, colors_cache=colors_cache, view_cache=view_cache,
        report_cache=report_cache,
    )
    kept, overflow = all_leaks[:TOP_LEAKS], all_leaks[TOP_LEAKS:]
    gaps = []
    if overflow:
        gaps.append(
            f"{len(overflow)} recurring pattern(s) beyond the top {TOP_LEAKS} by win-rate "
            f"gap are not shown."
        )
    return kept, tuple(_leak_line(leak) for leak in kept), gaps


def _build_deck_leaks(
    conn: sqlite3.Connection,
    kept_decks: list[tuple[str, DeckIdentity, list[_PopMatch]]],
    *,
    source: str,
    consensus_since: str | None,
    consensus_cache: dict,
    colors_cache: dict,
    view_cache: dict,
    report_cache: dict[tuple[str, str | None], MatchReport | None],
) -> tuple[tuple[DeckLeaks, ...], list[str]]:
    """Per-deck leak rollups, one per kept ``by_deck`` identity with enough
    of its own population sample to clear ``_leak_from_counts``'s per-side
    gate at all: that gate needs ``MIN_SAMPLE`` matches *with* a pattern and
    ``MIN_SAMPLE`` *without*, out of this deck's own matches, not the whole
    report's — a deck below ``DECK_LEAK_MIN`` (``2 * MIN_SAMPLE``) cannot
    clear it even in the best possible case (every one of its matches
    falling on one side of some future comparison), so it is skipped rather
    than scanned for nothing.
    """
    lines = []
    below = 0
    for label, _identity, rows in kept_decks:
        if len(rows) < DECK_LEAK_MIN:
            below += 1
            continue
        deck_match_ids = tuple(r.match_id for r in rows)
        deck_leaks = find_leaks(
            conn, match_ids=deck_match_ids, source=source, consensus_since=consensus_since,
            consensus_cache=consensus_cache, colors_cache=colors_cache, view_cache=view_cache,
            report_cache=report_cache,
        )
        if not deck_leaks:
            continue
        kept = deck_leaks[:TOP_DECK_LEAKS]
        lines.append(DeckLeaks(deck_label=label, leaks=tuple(_leak_line(leak) for leak in kept)))

    gaps = []
    if below:
        gaps.append(
            f"{below} deck(s) below {DECK_LEAK_MIN} population matches are not broken out "
            f"into their own leak table — too few of that deck's own matches to clear the "
            f"leak finder's sample gate on both sides of a comparison."
        )
    return tuple(lines), gaps


_STAGES = ("early", "mid", "late")   # your turns 1-3 / 4-6 / 7+
_SEVERITIES = ("decisive", "notice")  # trajectory.py's turning_point never emits NOTE or FLAG


def _turning_stage(self_turn_index: int) -> str:
    if self_turn_index <= 3:
        return "early"
    if self_turn_index <= 6:
        return "mid"
    return "late"


def _build_turning_points(
    population_rows: list[_PopMatch], reports: dict[str, MatchReport]
) -> tuple[tuple[TurningBucket, ...], list[str]]:
    """Every lost *game* in the population's own reports (not every lost
    *match* — a match won 2-1 can still have dropped its first game, and
    that game's own turning point belongs in this breakdown exactly as much
    as one from a match lost outright) gets its own ``turning_point``
    finding (Part 0's own fix: keyed on ``self_turn_index``, never the
    shared ``turn_number``), bucketed by which third of the game it fell in
    and how decisive it was.

    Always all 6 (stage, severity) cells, even at 0 (``mulligans``' own
    fixed-bucket precedent extended from two cells to six) — a caller
    renders a fixed grid, never a sparse list whose shape changes from one
    report to the next.

    A lost game with no ``turning_point`` finding at all — ``never_behind``
    fired instead, too few turns had a position index, or the match's
    report could not be built — is counted in the gap rather than guessed
    into a bucket (rule 4); ``never_behind`` in particular carries no
    ``self_turn_index``, so it is excluded by the same lookup that would
    otherwise have to special-case it. A missing report can only be charged
    against a match that was itself lost overall — a missing report for a
    won match makes no claim about any lost game at all, since there
    cannot be one to omit if the match was never dropped to begin with...
    except a game won 2-1 can still have one lost game inside it, which a
    missing report has no way to reveal either; this is therefore a
    slight undercount of the gap for exactly that one rare shape, stated
    here rather than silently absorbed.
    """
    no_turning_point = 0
    counts: dict[tuple[str, str], int] = defaultdict(int)

    for m in population_rows:
        report = reports.get(m.match_id)
        if report is None:
            if m.result == "loss":
                no_turning_point += 1
            continue
        for game in report.games:
            if game.result != "loss":
                continue
            finding = next(
                (f for f in report.findings
                 if f.code == "turning_point" and f.game_number == game.game_number),
                None,
            )
            if finding is None or finding.self_turn_index is None:
                no_turning_point += 1
                continue
            stage = _turning_stage(finding.self_turn_index)
            counts[(stage, str(finding.severity))] += 1

    buckets = tuple(
        TurningBucket(stage=stage, severity=severity, games=counts.get((stage, severity), 0))
        for stage in _STAGES for severity in _SEVERITIES
    )
    gaps = []
    if no_turning_point:
        gaps.append(
            f"{no_turning_point} lost game(s) have no turning_point finding to place in the "
            f"turning-point breakdown (never behind, too few recorded turns, or a missing "
            f"report) and are not counted in any bucket."
        )
    return buckets, gaps


def _recency_order(
    match_ids: list[str], started_at_by_id: dict[str, str | None]
) -> list[str]:
    """"Most recent first, ties broken by match_id ascending" without ever
    negating a date string: sort ascending by the tie-break key first, then
    a *stable* sort descending by the real key leaves ties in
    tie-break-ascending order — Python's own sort is documented stable even
    under ``reverse=True``."""
    ordered = sorted(match_ids)
    ordered.sort(key=lambda mid: started_at_by_id.get(mid) or "", reverse=True)
    return ordered


def _select_examples(
    leak_candidates: list[Leak],
    recent_losses: tuple[str, ...],
    started_at_by_id: dict[str, str | None],
) -> list[tuple[str, str]]:
    """Pure selection, no I/O — testable by hand (rule 8) with no database
    at all. ``leak_candidates`` is this report's own kept ``leaks``, already
    in gap-descending order; ``recent_losses`` is every population match
    with ``result = 'loss'`` and at least one ``turns`` row (the only losses
    this module can actually render a turn-by-turn account of).

    (1) Walk ``leak_candidates`` in order to the first whose pattern
    actually goes with losing (``win_rate_with < win_rate_without`` — a
    pattern that is even or winning-direction is skipped, never chosen, and
    only the first qualifying leak is ever used). Its own
    ``match_ids_with``, filtered to ``recent_losses``, are the candidates;
    ``chosen_for`` is that leak's own code.
    (2) Order those candidates most-recent-first (``started_at`` desc, then
    ``match_id`` asc) and keep up to ``MAX_EXAMPLES``.
    (3) If that yielded fewer than ``MAX_EXAMPLES`` (including none at all,
    when no leak qualified in the first place), fill the rest from every
    recent loss in the same order, skipping anything already chosen, with
    ``chosen_for="recent_loss"``.
    """
    eligible = set(recent_losses)
    chosen: list[tuple[str, str]] = []
    seen: set[str] = set()

    for leak in leak_candidates:
        if leak.win_rate_with >= leak.win_rate_without:
            continue
        for mid in _recency_order(
            [m for m in leak.match_ids_with if m in eligible], started_at_by_id
        ):
            if len(chosen) >= MAX_EXAMPLES:
                break
            if mid in seen:
                continue
            chosen.append((mid, leak.code))
            seen.add(mid)
        break  # only the first losing-direction leak is ever used

    if len(chosen) < MAX_EXAMPLES:
        for mid in _recency_order(list(recent_losses), started_at_by_id):
            if len(chosen) >= MAX_EXAMPLES:
                break
            if mid in seen:
                continue
            chosen.append((mid, "recent_loss"))
            seen.add(mid)

    return chosen


def _build_examples(
    conn: sqlite3.Connection,
    population_rows: list[_PopMatch],
    reports: dict[str, MatchReport],
    leaks: list[Leak],
    deck_label_by_id: dict[str, str],
    *,
    consensus_since: str | None,
    consensus_cache: dict,
    colors_cache: dict,
    view_cache: dict,
) -> tuple[tuple[ExampleGame, ...], list[str]]:
    """Up to ``MAX_EXAMPLES`` fully-rendered worked examples — the only
    place a match id appears anywhere on this evidence (module docstring).

    ``reports`` is the same population-wide map ``build_coach_evidence``
    already built via ``_build_match_reports``; nothing here builds a
    ``MatchReport`` a second time. A ``MatchSnapshot``, unlike a report, is
    never cached anywhere upstream of this call, so each of the (at most
    ``MAX_EXAMPLES``) selected matches costs one fresh ``build_snapshot`` —
    cheap on its own, and it shares every cache a repeated report build
    would have used anyway. ``consensus_since`` must be the same format-reset
    window value passed to ``_build_match_reports``/``_build_leaks``/
    ``_build_deck_leaks``, so the rendered example's own opponent consensus
    (if the analyzers ever surface one) agrees with the report it is shown
    alongside.
    """
    losses = [m for m in population_rows if m.result == "loss"]
    loss_ids = tuple(m.match_id for m in losses)
    has_turns: set[str] = set()
    if loss_ids:
        placeholders = ",".join("?" for _ in loss_ids)
        has_turns = {
            row["match_id"] for row in conn.execute(
                f"SELECT DISTINCT match_id FROM turns WHERE match_id IN ({placeholders})",
                loss_ids,
            )
        }
    recent_losses = tuple(m.match_id for m in losses if m.match_id in has_turns)
    started_at_by_id = {m.match_id: m.started_at for m in losses}
    deck_id_by_match = {m.match_id: m.deck_id for m in population_rows}

    selection = _select_examples(leaks, recent_losses, started_at_by_id)

    examples = []
    gaps: list[str] = []
    for match_id, chosen_for in selection:
        snap = build_snapshot(
            conn, match_id, consensus_since=consensus_since, consensus_cache=consensus_cache,
            colors_cache=colors_cache, view_cache=view_cache,
        )
        deciding = conn.execute(
            "SELECT MAX(game_number) AS game_number FROM games "
            "WHERE match_id = ? AND result = 'loss'",
            (match_id,),
        ).fetchone()
        game_number = deciding["game_number"] if deciding else None
        game = None
        if snap is not None and game_number is not None:
            game = next((g for g in snap.games if g.game_number == game_number), None)
        if snap is None or game_number is None or game is None:
            gaps.append(
                f"An example match chosen for \"{chosen_for}\" could not be rebuilt for "
                f"display and was skipped."
            )
            continue

        report = reports.get(match_id)
        finding_lines = tuple(
            _finding_line(f) for f in report.findings if f.game_number in (game_number, None)
        ) if report is not None else ()
        started_at = started_at_by_id.get(match_id)
        deck_id = deck_id_by_match.get(match_id)
        examples.append(ExampleGame(
            match_id=match_id,
            date=started_at[:10] if started_at else None,
            game_number=game_number,
            deck_label=(deck_label_by_id.get(deck_id) if deck_id else None) or "Unnamed deck",
            opponent=snap.opponent_label or "Unclassified",
            on_play=game.on_play,
            mulligans=game.self_mulligans,
            chosen_for=chosen_for,
            turn_lines=tuple(_turn_lines(snap, game_number)),
            play_lines=tuple(_play_lines(snap, game_number)),
            finding_lines=finding_lines,
        ))
    return tuple(examples), gaps


def _card_names(conn: sqlite3.Connection, grp_ids: list[int]) -> dict[int, str]:
    if not grp_ids:
        return {}
    placeholders = ",".join("?" for _ in grp_ids)
    return {
        row["grp_id"]: row["name"]
        for row in conn.execute(
            f"SELECT grp_id, name FROM cards WHERE grp_id IN ({placeholders})", grp_ids
        )
    }


def _deck_list_for(
    conn: sqlite3.Connection, label: str, identity: DeckIdentity
) -> tuple[DeckList, bool]:
    """One kept identity's ``DeckList``, read the same way ``brief/
    narrative.py``'s ``_own_seventy_five_block`` reads its own deck's —
    ``(count, name)`` pairs, sorted by name — except a grp_id with no
    matching ``cards`` row is counted in ``unnamed`` here rather than
    rendered as that function's ``"?"`` (rule 4: the copy count is real,
    the name just isn't known yet).

    The second return value flags whether this identity hid any such
    grp_id — the caller rolls every deck's own flag into one shared gap
    line instead of one per deck.
    """
    maindeck: list[int] = identity.current_cards.get("maindeck") or []
    sideboard: list[int] = identity.current_cards.get("sideboard") or []
    names = _card_names(conn, list({*maindeck, *sideboard}))
    unnamed = 0

    def block(grp_ids: list[int]) -> tuple[tuple[int, str], ...]:
        nonlocal unnamed
        counts: dict[int, int] = {}
        for grp_id in grp_ids:
            counts[grp_id] = counts.get(grp_id, 0) + 1
        # Two printings of one card are two grp_ids; merge them by name so
        # the list reads "3 Rest in Peace", not "1 ..." and "2 ..." lines.
        by_name: dict[str, int] = {}
        for grp_id, count in counts.items():
            name = names.get(grp_id)
            if name is None:
                unnamed += count
                continue
            by_name[name] = by_name.get(name, 0) + count
        return tuple(sorted(((count, name) for name, count in by_name.items()),
                            key=lambda cn: cn[1]))

    main = block(maindeck)
    side = block(sideboard)
    return DeckList(label=label, main=main, side=side, unnamed=unnamed), unnamed > 0


def _build_decklists(
    conn: sqlite3.Connection,
    kept_decks: list[tuple[str, DeckIdentity, list[_PopMatch]]],
    format_rows: list[_PopMatch],
) -> tuple[tuple[DeckList, ...], list[str]]:
    """The current 75 of up to ``TOP_DECKLISTS`` kept decks, ordered by
    format-window match count — the same window ``by_opponent`` uses, since
    a decklist from before the last reset is exactly as void as an opponent
    matchup rate from before it (``guide/field.py``'s own reasoning). A
    kept identity with zero format-window matches (all its population
    matches predate the reset) is omitted rather than shown as this
    report's "current" deck, which it is not.
    """
    format_counts: dict[str, int] = defaultdict(int)
    for m in format_rows:
        if m.deck_id is not None:
            format_counts[m.deck_id] += 1

    candidates = []
    for label, identity, _rows in kept_decks:
        count = sum(format_counts.get(did, 0) for did in identity.deck_ids)
        if count == 0:
            continue
        candidates.append((label, identity, count))
    candidates.sort(key=lambda c: (-c[2], c[0]))
    kept = candidates[:TOP_DECKLISTS]

    lines = []
    any_unnamed = False
    for label, identity, _count in kept:
        deck_list, had_unnamed = _deck_list_for(conn, label, identity)
        lines.append(deck_list)
        any_unnamed = any_unnamed or had_unnamed

    gaps = []
    if any_unnamed:
        gaps.append(
            "One or more decklists include a card with no matching row in the local card "
            "database; those copies are counted as unnamed rather than guessed at. Run "
            "`sensei-top cards --scryfall` to fill in the card database."
        )
    return tuple(lines), gaps


def _build_field(
    conn: sqlite3.Connection,
    win_start: str | None,
    opponent_counts_by_key: dict[str, tuple[int, int]],
    fmt: str = "Standard",
) -> tuple[tuple[FieldLine, ...], list[str]]:
    """The classified field itself, in this report's own format window —
    the same window ``guide/field.py``'s ``field_window`` builds (``e.format
    = 'Standard'`` plus ``e.event_date >= window_start`` once a reset
    exists), grouped by ``archetype_key`` with the true classified-deck
    total as the share denominator via ``guide/field.py``'s ``field_by_key``
    (reused rather than recomputed — never the truncated top-N sum, the
    exact bug that module's own docstring exists to prevent).

    Grouped one level up from ``_shares_for_window`` itself: that groups on
    ``archetype_name`` (a display string) for one format guide's own
    consensus diff, this on ``archetype_key`` (the classifier's stable
    identifier) so a renamed archetype still gets one row here, with every
    name it has carried kept as ``variants``. ``your_rate`` joins this
    report's own population through the exact vocabulary ``by_opponent``
    already resolves opponents into (``'archetype:' + archetype_key``); an
    unfaced key correctly reads ``_rate(0, 0)`` from
    ``opponent_counts_by_key``'s own default rather than being absent.
    """
    by_key, total = field_by_key(conn, fmt, win_start)
    if total == 0:
        return (), ["No classified field corpus exists in this report's format window."]

    candidates = [
        (key, variants, sum(n for _, n in variants)) for key, variants in by_key.items()
    ]
    candidates.sort(key=lambda c: (-c[2], c[1][0][0]))
    kept = candidates[:TOP_FIELD]

    lines = tuple(
        FieldLine(
            archetype=variants[0][0],
            variants=variants,
            decks=decks,
            share=decks / total,
            your_rate=_rate(*opponent_counts_by_key.get("archetype:" + key, (0, 0))),
        )
        for key, variants, decks in kept
    )
    return lines, []


def build_coach_evidence(
    conn: sqlite3.Connection, *, source: str = "all", report_cache: dict | None = None,
) -> CoachEvidence | None:
    """The full evidence base for the player-level coach report, or ``None``
    when there isn't enough of a population to say anything responsible
    (``review/leaks.py::MIN_SAMPLE`` matches) — the same gate every rollup in
    this package already applies before showing a rate.

    ``source`` reuses ``review/leaks.py::_scope_clause``'s own vocabulary:
    ``"all"`` (the default here, unlike that module's own ``"arena"``
    default — a player-level coach has no reason to default away from MTGO)
    or ``"arena"``/``"mtgo"``. A confirmed pick format decides an MTGO match
    (Standard is kept, any other format excluded); without a confirmed
    format, ``match_formats`` decides it from its own revealed cards, as
    ``_population``'s own docstring says. ``"mtgo"`` therefore still returns
    ``None`` on a database that has never run ``sensei-top cards --scryfall``
    (every legality read is NULL, so every MTGO match reads
    ``unknown_legality`` and is excluded), unless MTGO matches carry a
    confirmed Standard pick, which needs no legality data.

    ``report_cache`` is the ``(match_id, consensus_since)``-keyed
    ``MatchReport`` cache ``review/leaks.py::find_leaks`` reads and writes;
    pass ``api/sql.py::_shared_report_cache(request, conn)`` from a route so
    a report this coach report builds can be reused by a Leaks or Guide
    request in the same process, instead of the fresh, call-scoped dict
    below. ``None`` (this function's default) keeps today's behaviour
    exactly: a dict that lives only as long as this one call.
    """
    population_rows, excluded = _population(conn, source)
    population = len(population_rows)
    if population < MIN_SAMPLE:
        return None

    gaps: list[str] = []
    if excluded["no_event_id"]:
        gaps.append(
            f"{excluded['no_event_id']} match(es) excluded: no event id was recorded "
            f"(MTGO never writes one, so an MTGO match can never be assumed Constructed)."
        )
    if excluded["excluded_event"]:
        gaps.append(
            f"{excluded['excluded_event']} match(es) excluded: played in an excluded event "
            f"({', '.join(sorted(_EXCLUDED_EVENTS))})."
        )
    if excluded["limited"]:
        gaps.append(
            f"{excluded['limited']} match(es) excluded: played in a Limited queue, out of "
            f"scope for this Constructed-focused report."
        )
    if excluded["mtgo_not_legal"]:
        gaps.append(
            f"{excluded['mtgo_not_legal']} MTGO match(es) excluded: revealed a card that is not "
            f"Standard-legal (another format's deck, or a card since rotated out)."
        )
    if excluded["mtgo_banned"]:
        gaps.append(
            f"{excluded['mtgo_banned']} MTGO match(es) excluded: revealed a card banned in "
            f"Standard, played after its ban or with no ban date on file."
        )
    if excluded["mtgo_unresolved_cards"]:
        gaps.append(
            f"{excluded['mtgo_unresolved_cards']} MTGO match(es) excluded: revealed a card the "
            f"local card database has no entry for (a card Arena never carried, so its Standard "
            f"legality can't be read)."
        )
    if excluded["mtgo_unknown_legality"]:
        gaps.append(
            f"{excluded['mtgo_unknown_legality']} MTGO match(es) excluded: revealed a card "
            f"with no Standard legality on file (run `sensei-top cards --scryfall`)."
        )
    if excluded["mtgo_too_few_cards"]:
        gaps.append(
            f"{excluded['mtgo_too_few_cards']} MTGO match(es) excluded: too few distinct "
            f"cards revealed to judge the match's format at all."
        )
    if excluded["mtgo_other_format"]:
        gaps.append(
            f"{excluded['mtgo_other_format']} MTGO match(es) excluded: confirmed as a format "
            f"other than Standard, which this report does not cover."
        )

    by_source = _build_by_source(population_rows)
    mtgo_deckless = sum(1 for m in population_rows if m.source == "mtgo" and m.deck_id is None)
    if mtgo_deckless:
        gaps.append(
            f"{mtgo_deckless} MTGO match(es) are counted in the overall rate, the skill "
            f"splits, leaks and turning points, but in no per-deck line: MTGO records no "
            f"deck, and none was picked for them."
        )

    match_ids = tuple(m.match_id for m in population_rows)
    results_by_id = {m.match_id: m.result for m in population_rows}

    as_of = max((m.started_at for m in population_rows if m.started_at), default=None)
    overall = _rate(sum(1 for m in population_rows if m.result == "win"), population)
    overall_games = _game_rate(conn, match_ids)
    g1, post_board, on_play, on_draw = _deck_game_split(conn, match_ids)

    # One cache set shared across by_deck's own archetype classification and
    # every build_match_report call below — guide/bundle.py's own precedent
    # for why a repeated opponent archetype, the classifier's card-colour
    # table, and build_snapshot's own repeated view lookups should cost one
    # scan each, not one per match (or, short of sharing it here, one scan
    # for by_deck plus a second for the report loop). report_cache is handed
    # to _build_match_reports so any later find_leaks(..., report_cache=...)
    # over these same matches reuses these reports instead of rebuilding them.
    consensus_cache: dict = {}
    colors_cache: dict = {}
    colors_cache["colors_by_name"] = _card_colors_by_name(conn)
    view_cache: dict = {}
    if report_cache is None:
        report_cache = {}

    identities = list_identities(conn)
    by_deck, deck_gap, kept_decks = _build_by_deck(
        conn, population_rows, colors_cache["colors_by_name"], identities,
    )
    if deck_gap:
        gaps.append(deck_gap)
    deck_label_by_id: dict[str, str] = {
        did: (identity.name or "Unnamed deck")
        for identity in identities for did in identity.deck_ids
    }

    # The format-reset window — computed once, here, before any report is
    # built, and threaded as `consensus_since` into every build_match_report/
    # build_snapshot/find_leaks call below (this module's own docstring's
    # "never window metagame data across a ban" rule, guide/window.py). Every
    # one of those calls must receive this exact value, never a second one it
    # computes for itself (review/snapshot.py:632 and api/sql.py:142 used to
    # skip this and silently aggregate an opponent consensus across a reset).
    resets = format_resets(conn, "Standard")
    reset = resets[0] if resets else None
    win_start = window_start(reset) if reset is not None else None
    if win_start is not None:
        format_rows = [m for m in population_rows if (m.started_at or "") >= win_start]
    else:
        format_rows = list(population_rows)
        # Same two-answer split guide/bundle.py's own "no reset" gap uses:
        # genuinely no ban detected vs. no legality data to detect one from
        # at all are different claims, and only the first says the corpus
        # has no reset in it.
        if legality_known(conn):
            gaps.append(
                "No format reset was detected — the opponent-archetype table spans this "
                "report's whole population rather than a post-reset window."
            )
        else:
            gaps.append(
                "No card legality data is present, so a format reset cannot be detected at "
                "all: the opponent-archetype table spans this report's whole population, "
                "which may pool across a ban. Run `sensei-top cards --scryfall` and "
                "rebuild this report before trusting it."
            )

    reports = _build_match_reports(
        conn, match_ids, consensus_since=win_start, consensus_cache=consensus_cache,
        colors_cache=colors_cache, view_cache=view_cache, report_cache=report_cache,
    )
    by_role = _build_by_role(population_rows, reports)

    mulligans = _build_mulligans(conn, match_ids)

    by_opponent, opponent_gaps, opponent_counts_by_key = _build_by_opponent(
        conn, format_rows, results_by_id
    )
    gaps.extend(opponent_gaps)

    leak_candidates, leaks, leak_gaps = _build_leaks(
        conn, match_ids, source=source, consensus_since=win_start, consensus_cache=consensus_cache,
        colors_cache=colors_cache, view_cache=view_cache, report_cache=report_cache,
    )
    gaps.extend(leak_gaps)

    deck_leaks, deck_leak_gaps = _build_deck_leaks(
        conn, kept_decks, source=source, consensus_since=win_start, consensus_cache=consensus_cache,
        colors_cache=colors_cache, view_cache=view_cache, report_cache=report_cache,
    )
    gaps.extend(deck_leak_gaps)

    turning_points, turning_gaps = _build_turning_points(population_rows, reports)
    gaps.extend(turning_gaps)

    examples, example_gaps = _build_examples(
        conn, population_rows, reports, leak_candidates, deck_label_by_id,
        consensus_since=win_start, consensus_cache=consensus_cache, colors_cache=colors_cache,
        view_cache=view_cache,
    )
    gaps.extend(example_gaps)

    decklists, decklist_gaps = _build_decklists(conn, kept_decks, format_rows)
    gaps.extend(decklist_gaps)

    field, field_gaps = _build_field(conn, win_start, opponent_counts_by_key)
    gaps.extend(field_gaps)
    # duplicate_of IS NULL: a republished twin (metagame/dedup.py) can carry
    # a later event_date than its own survivor, which would otherwise move
    # "latest" without the corpus actually having anything newer in it.
    field_latest_event = conn.execute(
        "SELECT MAX(event_date) FROM meta_event WHERE duplicate_of IS NULL"
    ).fetchone()[0]

    return CoachEvidence(
        source=source,
        population=population,
        format_population=len(format_rows),
        window_start=win_start,
        as_of=as_of,
        overall=overall,
        overall_games=overall_games,
        g1=g1,
        post_board=post_board,
        on_play=on_play,
        on_draw=on_draw,
        by_deck=by_deck,
        by_source=by_source,
        by_role=by_role,
        mulligans=mulligans,
        by_opponent=by_opponent,
        leaks=leaks,
        deck_leaks=deck_leaks,
        turning_points=turning_points,
        examples=examples,
        decklists=decklists,
        field=field,
        field_latest_event=field_latest_event,
        gaps=tuple(gaps),
    )


def format_rate(rate: Rate) -> str:
    """The one rendering every rate on this evidence goes through — no
    caller formats a percentage or a confidence interval itself, so the
    "no data" and "anecdotal" phrasing can never drift between two call
    sites. ``n == 0`` reads as "no data" rather than a bare 0%, which would
    read as "always loses" (rule 4)."""
    if rate.n == 0 or rate.rate is None:
        return "no data (n=0)"
    pct = rate.rate * 100
    lo, hi = rate.ci[0] * 100, rate.ci[1] * 100
    text = f"{pct:.0f}% ({rate.wins}/{rate.n}, 95% CI {lo:.0f}–{hi:.0f}%)"  # noqa: RUF001
    if rate.anecdotal:
        text += " — anecdotal, below the sample floor"
    return text


def metrics_snapshot(evidence: CoachEvidence) -> dict:
    """A compact, JSON-safe snapshot of one report's headline numbers,
    meant to be stored (``coach/store.py``) and handed back into
    ``progress_since`` at some later ``as_of`` — never reconstructed into a
    ``CoachEvidence`` itself, so it only needs to carry what a later "since
    last time" comparison actually reads.

    Every value here is a plain ``dict``/``list``/``str``/``int``/``float``/
    ``None`` — nothing here is a tuple or a dataclass, both of which would
    come back reshaped (a tuple as a list, a dataclass not at all) after a
    ``json.dumps``/``json.loads`` round trip. That round trip is this
    function's own contract, not an incidental property of it.
    """
    return {
        "version": 1,
        "as_of": evidence.as_of,
        "population": evidence.population,
        "overall": {
            "wins": evidence.overall.wins, "n": evidence.overall.n, "rate": evidence.overall.rate,
        },
        # Not read by progress_since (it never diffs by_source across
        # reports, only the plain fields above) — carried here only so a
        # caller rendering the *current* snapshot's prompt has it without a
        # second build_coach_evidence call. Purely additive: an older stored
        # report missing this key is still a valid version 1 (schema below
        # is unchanged for every field progress_since actually reads).
        "by_source": {
            src: {"wins": rate.wins, "n": rate.n, "rate": rate.rate}
            for src, rate in evidence.by_source.items()
        },
        "leaks": [
            {"code": leak.code, "gap": leak.gap, "pattern": leak.pattern}
            for leak in evidence.leaks
        ],
    }


def progress_since(
    conn: sqlite3.Connection, metrics: dict, *, source: str = "all",
) -> list[str]:
    """Prose progress lines comparing a fresh read of the population against
    a ``metrics_snapshot()`` dict saved at some earlier ``as_of`` — the
    Coach tab's own "since last time" panel.

    Pure prose, not a dataclass: ``metrics_snapshot()``'s dict is the one
    persisted shape, so a caller diffs that stored dict against a fresh
    database read directly rather than rebuilding a second full
    ``CoachEvidence`` and diffing two of those, which would pay for every
    other rollup in this module just to answer "what changed".

    A previously-known leak ``code`` is checked for raw presence among the
    *new* matches alone (not re-run through ``find_leaks``, whose own
    ``MIN_SAMPLE`` gate a handful of new matches will almost never clear) —
    every resulting rate is expected to read ``anecdotal`` most of the time,
    and is labelled as such rather than presented with false confidence.
    """
    as_of = metrics.get("as_of")
    population_rows, _ = _population(conn, source)
    new_rows = (
        [m for m in population_rows if (m.started_at or "") > as_of]
        if as_of is not None else list(population_rows)
    )

    if not new_rows:
        return ["No new matches recorded since the last report."]

    wins = sum(1 for m in new_rows if m.result == "win")
    new_rate = _rate(wins, len(new_rows))
    lines = [f"{len(new_rows)} new match(es) since the last report: {format_rate(new_rate)}."]

    old_codes = sorted({leak["code"] for leak in metrics.get("leaks", ())})
    if not old_codes:
        return lines

    new_match_ids = tuple(m.match_id for m in new_rows)
    results_by_id = {m.match_id: m.result for m in new_rows}
    consensus_cache: dict = {}
    colors_cache: dict = {"colors_by_name": _card_colors_by_name(conn)}
    view_cache: dict = {}
    report_cache: dict[tuple[str, str | None], MatchReport | None] = {}
    # Same format-reset window build_coach_evidence computes, derived the
    # same way (format_resets/window_start) — this is an independent entry
    # point with its own fresh caches, not a continuation of that call, so it
    # has no shared win_start to reuse and must compute its own rather than
    # falling back to build_match_report's None default, which would be the
    # pre-reset-inclusive (wrong) answer whenever a reset exists.
    resets = format_resets(conn, "Standard")
    reset = resets[0] if resets else None
    win_start = window_start(reset) if reset is not None else None
    reports = _build_match_reports(
        conn, new_match_ids, consensus_since=win_start, consensus_cache=consensus_cache,
        colors_cache=colors_cache, view_cache=view_cache, report_cache=report_cache,
    )

    for code in old_codes:
        if code in ("mana_screwed", "mana_flooded"):
            flag_index = 0 if code == "mana_screwed" else 1
            flags_by_id = {mid: _mana_flags(conn, mid)[flag_index] for mid in new_match_ids}
            # Rule 4: a match with no turns rows at all (every MTGO match) is
            # unknown for this flag, not "clean" -- it must not silently swell
            # either the denominator or the "not observed" reading below.
            known_ids = [mid for mid, flag in flags_by_id.items() if flag is not None]
            if not known_ids:
                lines.append(f'"{code}" could not be measured in any new match (no turn data).')
                continue
            with_ids = [mid for mid in known_ids if flags_by_id[mid]]
            denominator = len(known_ids)
        else:
            with_ids = [
                mid for mid, report in reports.items()
                if any(f.code == code for f in report.findings)
            ]
            denominator = len(new_rows)
        if not with_ids:
            lines.append(f'"{code}" was not observed in any new match.')
            continue
        wins_with = sum(1 for mid in with_ids if results_by_id.get(mid) == "win")
        rate = _rate(wins_with, len(with_ids))
        lines.append(
            f'"{code}" recurred in {len(with_ids)} of {denominator} new match(es): '
            f"{format_rate(rate)}."
        )
    return lines
