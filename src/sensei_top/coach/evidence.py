"""Coach evidence: the one match population every coach report reasons
over, and the rollups on top of it. Every rollup draws from that same set,
so no two lines of a report can disagree about which matches counted.

The population and every exclusion from it: docs/coach.md, "Scope". Which
sections span all of it and which only the report format's window since its
latest reset: docs/coach.md, "The two windows". Each rollup:
docs/coach.md, "The evidence sections".

No opponent name, opponent user id or deck GUID appears anywhere on
``CoachEvidence``, and no match id except ``ExampleGame.match_id`` (see
``ExampleGame``): every rollup resolves through a deck identity, an
opponent archetype key or a count. That is why ``_build_match_reports``
returns its ``match_id -> MatchReport`` map rather than storing it on the
evidence.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from sensei_top.archetypes.classify import _card_colors_by_name
from sensei_top.guide.deck import DeckIdentity, identity_format, list_identities
from sensei_top.guide.field import field_by_key
from sensei_top.guide.play import mulligan_split
from sensei_top.guide.window import (
    consensus_window_resolver,
    format_resets,
    legality_known,
    window_start,
)
from sensei_top.i18n import _, english, ngettext
from sensei_top.review.findings import MatchReport
from sensei_top.review.leaks import (
    MIN_SAMPLE,
    Leak,
    ReportCache,
    _mana_flags,
    _scope_clause,
    _wilson,
    find_leaks,
    report_cache_key,
)
from sensei_top.review.match_report import build_match_report
from sensei_top.review.narrative import _finding_line, _play_lines, _turn_lines
from sensei_top.review.snapshot import _classify_own_deck, build_snapshot

# Arena's event-name prefix for each draft queue: "QuickDraft_SOS_20260831".
# Read off real captures, "PickTwoDraft" off a real event id (the one
# tests/test_table_queues.py records). An unrecognized prefix is not Limited.
_LIMITED_PREFIXES = frozenset({"QuickDraft", "PremierDraft", "TradDraft", "CubeDraft",
                                "PickTwoDraft"})


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
    every rate below ``MIN_SAMPLE``, the leak finder's own gate, so a caller
    can caveat a rate without re-deriving the threshold.
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
    ``Rate`` so every number renders through ``format_rate``.
    ``present``/``absent`` are rebuilt from ``Leak``'s win rate and n: the
    win count is ``round(win_rate * n)``, since ``Leak`` stores only the
    rate. ``Leak`` itself, with its match ids, never reaches a caller.
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
    rather than guess which cells exist this time."""

    stage: str      # "early" (your turns 1-3) / "mid" (4-6) / "late" (7+)
    severity: str    # the turning_point finding's own Severity value
    games: int


@dataclass(frozen=True, slots=True)
class ExampleGame:
    """One worked example game, fully rendered. ``match_id`` is the one match
    id anywhere on ``CoachEvidence``, kept only so the Coach page can link the
    example to its match: ``coach/narrative.py`` never renders it into a
    prompt, and ``tests/test_coach_evidence.py``'s privacy tests carve out
    this field alone. ``opponent`` is always the opponent's *deck label*,
    never a player name or handle."""

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
    """One kept identity's current 75 as ``(count, name)`` pairs, sorted by
    name, two printings of one card merged. A grp_id with no matching
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
    """

    source: str
    population: int
    format_population: int  # fmt's matches since window_start: the format sections' set
    window_start: str | None  # fmt's; None = no reset detected, every fmt match counts
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
    field_latest_event: str | None  # MAX(event_date) of an fmt meta_event
    gaps: tuple[str, ...]
    fmt: str
    # Every format in the population with its match count, most matches
    # first, then by name: the skill sections' scope.
    format_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class _PopMatch:
    """One population match's own fields, carried through every rollup below
    instead of re-querying ``matches`` per rollup.

    ``source`` and ``format`` default only for a direct construction (the
    tests build some); ``_population`` always passes both, from
    ``matches.source`` and ``v_match_format.format`` (never ``None`` for a
    population match).
    """

    match_id: str
    deck_id: str | None
    started_at: str | None
    result: str
    source: str = "arena"
    format: str | None = None


def _rate(wins: int, n: int) -> Rate:
    return Rate(wins=wins, n=n, rate=(wins / n if n else None), ci=_wilson(wins, n),
                anecdotal=n < MIN_SAMPLE)


def _build_by_source(population_rows: list[_PopMatch]) -> dict[str, Rate]:
    """The population split by ``matches.source``. Always both keys, even
    at ``n == 0``, so a caller renders a fixed two-row table rather than
    guessing which source this report actually has data for."""
    by_source: dict[str, list[_PopMatch]] = {"arena": [], "mtgo": []}
    for m in population_rows:
        by_source[m.source].append(m)
    return {
        src: _rate(sum(1 for m in rows if m.result == "win"), len(rows))
        for src, rows in by_source.items()
    }


# The match_format_inference reasons that leave an MTGO match without a
# format (archetypes/classify.py's FORMAT_REASONS, less "fit"), each its own
# exclusion bucket.
_INFERENCE_EXCLUSIONS = ("unresolved_cards", "unknown_legality", "no_fit", "too_few_cards",
                         "ambiguous")


def _population(
    conn: sqlite3.Connection, source: str
) -> tuple[list[_PopMatch], dict[str, int]]:
    """Every completed match in scope, split into the population and a count
    per exclusion reason. Each match lands in exactly one bucket.

    An Arena match is first checked against ``event_id`` — for NULL before
    it is ever passed to ``_is_limited_event``, and an excluded-event match
    is never also charged to the Limited bucket. MTGO has no event, so it
    skips those three (``no_event_id`` stays an Arena-only reading). Then a
    match from either client with no ``v_match_format.format`` is excluded:
    an MTGO match into the bucket of the reason ``match_format_inference``
    gave it, when that reason is one of ``_INFERENCE_EXCLUSIONS``; any other
    (an Arena event that names no format, an MTGO match never inferred) into
    ``no_format``. Every format is kept, not only one: which sections a
    format reaches is ``build_coach_evidence``'s choice, not this one's.
    """
    scope_sql, scope_params = _scope_clause(None, None, source)
    # The deck is v_match_deck's (the user's pick for an MTGO match, else what
    # the log named), not matches.deck_id. Wrapped so _scope_clause's bare
    # column names stay unambiguous: the views repeat match_id and source.
    rows = conn.execute(
        f"SELECT match_id, source, event_id, deck_id, match_format, inference_reason, "
        f"started_at, result FROM ("
        f"SELECT m.match_id, m.source, m.event_id, md.deck_id, f.format AS match_format, "
        f"i.reason AS inference_reason, m.started_at, m.result "
        f"FROM matches m JOIN v_match_deck md ON md.match_id = m.match_id "
        f"JOIN v_match_format f ON f.match_id = m.match_id "
        f"LEFT JOIN match_format_inference i "
        f"ON i.match_id = m.match_id AND m.source = 'mtgo') "
        f"WHERE result IN ('win', 'loss'){scope_sql}",
        scope_params,
    ).fetchall()

    included: list[_PopMatch] = []
    excluded = {
        "no_event_id": 0, "excluded_event": 0, "limited": 0, "no_format": 0,
        **{reason: 0 for reason in _INFERENCE_EXCLUSIONS},
    }

    for row in rows:
        if row["source"] != "mtgo":
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
        if row["match_format"] is None:
            reason = row["inference_reason"]
            excluded[reason if reason in _INFERENCE_EXCLUSIONS else "no_format"] += 1
            continue
        included.append(_PopMatch(
            match_id=row["match_id"], deck_id=row["deck_id"],
            started_at=row["started_at"], result=row["result"],
            source="mtgo" if row["source"] == "mtgo" else "arena",
            format=row["match_format"],
        ))
    return included, excluded


def _format_counts(population_rows: list[_PopMatch]) -> tuple[tuple[str, int], ...]:
    """Every format in the population with its match count, most first, then
    by name so the order never depends on row order."""
    counts = Counter(m.format for m in population_rows if m.format is not None)
    return tuple(sorted(counts.items(), key=lambda fc: (-fc[1], fc[0])))


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
    conn: sqlite3.Connection, identity: DeckIdentity, colors_by_name: dict, fmt: str
) -> str | None:
    """This identity's own archetype, read the same way ``guide/field.py``'s
    ``build_field`` reads its own deck's: classify the most recently played
    ``deck_id`` under this identity from its full 60, event_id-less (rule 4 —
    an event-conditioned format guess is not this function's job), against
    ``fmt``'s definitions: ``by_deck`` keeps only identities whose own format
    (``identity_format``) is ``fmt``."""
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
    verdict, _ = _classify_own_deck(
        conn, row["deck_id"], None, colors_by_name=colors_by_name, fmt=fmt,
    )
    return verdict.name if verdict is not None else None


def _deck_candidates(
    rows: list[_PopMatch], identities: list[DeckIdentity]
) -> list[tuple[str, DeckIdentity, list[_PopMatch]]]:
    """Every identity with at least one of ``rows``, as ``(label, identity,
    its rows)``, by match count then label — never by last_played, so the
    order is stable regardless of query order."""
    by_deck_id: dict[str, list[_PopMatch]] = defaultdict(list)
    for m in rows:
        if m.deck_id is not None:
            by_deck_id[m.deck_id].append(m)

    candidates: list[tuple[str, DeckIdentity, list[_PopMatch]]] = []
    for identity in identities:
        deck_rows = [r for did in identity.deck_ids for r in by_deck_id.get(did, ())]
        if not deck_rows:
            continue
        # The sort keys on this English literal. The label put into DeckLine
        # and DeckLeaks is translated inline (identity.name or
        # _("Unnamed deck")), so the order cannot move with the language.
        candidates.append((identity.name or "Unnamed deck", identity, deck_rows))
    candidates.sort(key=lambda c: (-len(c[2]), c[0]))
    return candidates


def _build_by_deck(
    conn: sqlite3.Connection,
    format_rows: list[_PopMatch],
    colors_by_name: dict[str, frozenset[str]],
    identities: list[DeckIdentity],
    fmt: str,
) -> tuple[tuple[DeckLine, ...], list[str], list[tuple[str, DeckIdentity, list[_PopMatch]]]]:
    """A format section: one line per deck whose own format
    (``guide/deck.py::identity_format``) is ``fmt``, over ``format_rows``
    (``fmt``'s matches since its window). A deck of another format gets no
    line even when some of its matches were played as ``fmt``; those
    matches still count in the other ``fmt`` records, and a gap line says
    how many.

    ``colors_by_name`` and ``identities`` are the caller's one scan of
    ``cards`` and of ``list_identities``, shared with the report builds and
    ``_build_examples`` rather than repeated here.

    Returns the kept ``(label, identity, rows)`` triples as a third value,
    for ``_build_decklists``. (``deck_leaks`` is a skill section and ranks
    its own decks over the whole population instead.)
    """
    candidates = []
    other_format_matches = 0
    for candidate in _deck_candidates(format_rows, identities):
        if identity_format(conn, candidate[1]) == fmt:
            candidates.append(candidate)
        else:
            other_format_matches += len(candidate[2])
    kept, overflow = candidates[:TOP_DECKS], candidates[TOP_DECKS:]

    lines = []
    for _label, identity, rows in kept:
        match_ids = tuple(r.match_id for r in rows)
        wins = sum(1 for r in rows if r.result == "win")
        g1, post_board, on_play, on_draw = _deck_game_split(conn, match_ids)
        lines.append(DeckLine(
            label=identity.name or _("Unnamed deck"),
            archetype=_own_archetype(conn, identity, colors_by_name, fmt),
            matches=_rate(wins, len(rows)),
            g1=g1, post_board=post_board, on_play=on_play, on_draw=on_draw,
        ))

    gaps = []
    if overflow:
        n_matches = sum(len(rows) for _label, _identity, rows in overflow)
        gaps.append(ngettext(
            "{n} deck(s) beyond the top {top} by sample size are not "
            "shown in the per-deck table ({matches} matches).",
            "{n} deck(s) beyond the top {top} by sample size are not "
            "shown in the per-deck table ({matches} matches).",
            len(overflow),
        ).format(n=len(overflow), top=TOP_DECKS, matches=n_matches))
    if other_format_matches:
        gaps.append(ngettext(
            "{n} {fmt} match(es) were played with a deck whose own "
            "format is another one, so they count in the {fmt} records but in no per-deck "
            "line.",
            "{n} {fmt} match(es) were played with a deck whose own "
            "format is another one, so they count in the {fmt} records but in no per-deck "
            "line.",
            other_format_matches,
        ).format(n=other_format_matches, fmt=fmt))
    return tuple(lines), gaps, kept


def _match_window(
    m: _PopMatch, consensus_window: Callable[[str], str | None]
) -> str | None:
    """The consensus window ``m``'s report is built under: its own format's,
    and none for a match with no format — exactly
    ``review/leaks.py::find_leaks``'s ``window_for``, so a report cached here
    is the one ``find_leaks`` looks up for the same match."""
    return consensus_window(m.format) if m.format is not None else None


def _build_match_reports(
    conn: sqlite3.Connection,
    rows: list[_PopMatch],
    *,
    consensus_window: Callable[[str], str | None],
    consensus_cache: dict,
    colors_cache: dict,
    view_cache: dict,
    report_cache: ReportCache,
) -> dict[str, MatchReport]:
    """Every population match's own post-game report, built once, keyed by
    match id. Private, and returned rather than stored on ``CoachEvidence``,
    because a match id must not appear on the evidence (module docstring).
    A second call over the same rows and caches builds nothing again.

    ``consensus_window`` maps a format to its consensus window
    (``guide/window.py::consensus_window_resolver``) and must be the *same*
    resolver passed to every other ``find_leaks``/``build_snapshot`` call
    this module makes. Each match is built under its own format's window
    (``_match_window``). It has no default, so a new call site cannot fall
    back to no window and read an opponent consensus across a reset.

    ``report_cache`` is keyed by ``review/leaks.py::report_cache_key``
    (match, window, language), the key ``find_leaks`` reads, so a later
    ``find_leaks(..., report_cache=...)`` over the same matches builds
    nothing twice, and a report a Portuguese page built is never what an
    English prompt gets.

    A ``None`` report (the match missing from ``matches``, which cannot
    happen for a row just read from it) is skipped, not raised.
    """
    reports: dict[str, MatchReport] = {}
    for m in rows:
        match_window = _match_window(m, consensus_window)
        cache_key = report_cache_key(m.match_id, match_window)
        if cache_key in report_cache:
            report = report_cache[cache_key]
        else:
            report = build_match_report(
                conn, m.match_id, consensus_since=match_window,
                consensus_cache=consensus_cache, colors_cache=colors_cache,
                view_cache=view_cache,
            )
            report_cache[cache_key] = report
        if report is not None:
            reports[m.match_id] = report
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
    # A role that never occurred is omitted, not shown at n=0: unlike
    # kept/mulliganed, the role vocabulary isn't a fixed split.
    return {role: _rate(wins, n) for role, (wins, n) in counts.items() if n > 0}


def _build_mulligans(conn: sqlite3.Connection, match_ids: tuple[str, ...]) -> dict[str, Rate]:
    """Game-level, over this report's match population, with
    ``guide/play.py::mulligan_split``'s buckets (``self_mulligans == 0``
    vs. ``> 0``, games with no recorded count excluded). Both keys are
    always present, even at n=0: "no mulliganed games" is worth showing.
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

    Groups on ``v_match_opponent.opponent_key``, not ``archetype_name``
    (which only an automatic classification fills): a manual pick that named
    a real archetype (``api/routes/matches.py``'s ``set_opponent_deck``,
    which sets ``archetype_key`` from the chosen candidate) produces
    ``'archetype:' + archetype_key`` — the same key an automatic
    classification of the same archetype would produce — so the two merge.
    A manual pick with no archetype at all (the ``Rogue`` label) produces
    ``'manual:Rogue'``, which the ``LIKE 'archetype:%'`` filter below
    excludes, landing it in the unclassified gap line rather than being
    named — same treatment as a colour-only or fully unknown opponent.

    Returns a third value beyond the usual ``(lines, gaps)`` pair: every
    opponent_key's own ``(wins, n)``, not just the top ``TOP_OPPONENTS``,
    for ``_build_field``'s ``your_rate`` against any archetype the field
    names, including one this table cut for sample size.
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
        gaps.append(ngettext(
            "{n} match(es) in the format window have no classified opponent "
            "archetype and are not counted in the opponent-archetype table.",
            "{n} match(es) in the format window have no classified opponent "
            "archetype and are not counted in the opponent-archetype table.",
            unclassified,
        ).format(n=unclassified))

    full_counts: dict[str, tuple[int, int]] = {}
    variants_by_key: dict[str, tuple[tuple[str, int], ...]] = {}
    candidates = []
    for key, mids in match_ids_by_key.items():
        # The vote picks the label a rename left the majority on. A tie
        # (e.g. one automatic classification plus one manual override with
        # different wording) breaks alphabetically rather than by row
        # order, which SQLite does not guarantee for a query with no
        # ORDER BY.
        label = min(label_votes[key].items(), key=lambda kv: (-kv[1], kv[0]))[0]
        wins = sum(1 for mid in mids if results_by_id.get(mid) == "win")
        full_counts[key] = (wins, len(mids))
        # Every label this key has carried, with the vote's tie-break.
        variants_by_key[key] = tuple(
            sorted(label_votes[key].items(), key=lambda lv: (-lv[1], lv[0]))
        )
        candidates.append((key, label, len(mids), wins))

    candidates.sort(key=lambda c: (-c[2], c[1]))
    kept, overflow = candidates[:TOP_OPPONENTS], candidates[TOP_OPPONENTS:]
    if overflow:
        gaps.append(ngettext(
            "{n} opponent archetype(s) beyond the top {top} by sample "
            "size are not shown in the opponent-archetype table.",
            "{n} opponent archetype(s) beyond the top {top} by sample "
            "size are not shown in the opponent-archetype table.",
            len(overflow),
        ).format(n=len(overflow), top=TOP_OPPONENTS))

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
    consensus_window: Callable[[str], str | None],
    consensus_cache: dict,
    colors_cache: dict,
    view_cache: dict,
    report_cache: ReportCache,
) -> tuple[list[Leak], tuple[LeakLine, ...], list[str]]:
    """The population's own recurring patterns, top ``TOP_LEAKS`` of
    ``find_leaks``' gap-ranked list. ``consensus_window`` must be the one
    resolver (``_build_match_reports``).

    Returns the raw kept ``Leak`` objects too: ``_build_examples`` needs
    ``Leak.match_ids_with``, which stays off ``LeakLine`` (module docstring).
    """
    all_leaks = find_leaks(
        conn, match_ids=match_ids, source=source, consensus_window=consensus_window,
        consensus_cache=consensus_cache, colors_cache=colors_cache, view_cache=view_cache,
        report_cache=report_cache,
    )
    kept, overflow = all_leaks[:TOP_LEAKS], all_leaks[TOP_LEAKS:]
    gaps = []
    if overflow:
        gaps.append(ngettext(
            "{n} recurring pattern(s) beyond the top {top} by win-rate "
            "gap are not shown.",
            "{n} recurring pattern(s) beyond the top {top} by win-rate "
            "gap are not shown.",
            len(overflow),
        ).format(n=len(overflow), top=TOP_LEAKS))
    return kept, tuple(_leak_line(leak) for leak in kept), gaps


def _build_deck_leaks(
    conn: sqlite3.Connection,
    kept_decks: list[tuple[str, DeckIdentity, list[_PopMatch]]],
    *,
    source: str,
    consensus_window: Callable[[str], str | None],
    consensus_cache: dict,
    colors_cache: dict,
    view_cache: dict,
    report_cache: ReportCache,
) -> tuple[tuple[DeckLeaks, ...], list[str]]:
    """Per-deck leak rollups, a skill section: ``kept_decks`` is the top
    ``TOP_DECKS`` identities by whole-population match count (every format,
    not ``by_deck``'s format-only set). ``_leak_from_counts`` needs
    ``MIN_SAMPLE`` of the deck's own matches *with* a pattern and
    ``MIN_SAMPLE`` *without*, so a deck below ``DECK_LEAK_MIN`` can never
    clear it and is skipped rather than scanned for nothing.
    """
    lines = []
    below = 0
    for _label, identity, rows in kept_decks:
        if len(rows) < DECK_LEAK_MIN:
            below += 1
            continue
        deck_match_ids = tuple(r.match_id for r in rows)
        deck_leaks = find_leaks(
            conn, match_ids=deck_match_ids, source=source, consensus_window=consensus_window,
            consensus_cache=consensus_cache, colors_cache=colors_cache, view_cache=view_cache,
            report_cache=report_cache,
        )
        if not deck_leaks:
            continue
        kept = deck_leaks[:TOP_DECK_LEAKS]
        lines.append(DeckLeaks(
            deck_label=identity.name or _("Unnamed deck"),
            leaks=tuple(_leak_line(leak) for leak in kept),
        ))

    gaps = []
    if below:
        gaps.append(ngettext(
            "{n} deck(s) below {minimum} population matches are not broken out "
            "into their own leak table — too few of that deck's own matches to clear the "
            "leak finder's sample gate on both sides of a comparison.",
            "{n} deck(s) below {minimum} population matches are not broken out "
            "into their own leak table — too few of that deck's own matches to clear the "
            "leak finder's sample gate on both sides of a comparison.",
            below,
        ).format(n=below, minimum=DECK_LEAK_MIN))
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
    *match* — a match won 2-1 can still have dropped a game), placed by its
    ``turning_point`` finding's ``self_turn_index`` (never the shared
    ``turn_number``) and severity into the six ``TurningBucket`` cells.

    A lost game with no ``turning_point`` finding — ``never_behind`` fired
    instead, too few turns had a position index, or the match's report
    could not be built — is counted in the gap rather than guessed into a
    bucket (rule 4). A missing report is charged once, and only for a match
    lost overall: it cannot reveal a lost game inside a match won 2-1, so
    the gap undercounts that one shape.
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
        gaps.append(ngettext(
            "{n} lost game(s) have no turning_point finding to place in the "
            "turning-point breakdown (never behind, too few recorded turns, or a missing "
            "report) and are not counted in any bucket.",
            "{n} lost game(s) have no turning_point finding to place in the "
            "turning-point breakdown (never behind, too few recorded turns, or a missing "
            "report) and are not counted in any bucket.",
            no_turning_point,
        ).format(n=no_turning_point))
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
    this module can render turn by turn). Returns ``(match_id, chosen_for)``
    pairs, ``chosen_for`` a leak code or ``"recent_loss"``. The rule:
    docs/coach.md, "How the example games are chosen".
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


@english()
def _build_examples(
    conn: sqlite3.Connection,
    population_rows: list[_PopMatch],
    reports: dict[str, MatchReport],
    leaks: list[Leak],
    deck_label_by_id: dict[str, str],
    *,
    consensus_window: Callable[[str], str | None],
    consensus_cache: dict,
    colors_cache: dict,
    view_cache: dict,
) -> tuple[tuple[ExampleGame, ...], list[str]]:
    """Up to ``MAX_EXAMPLES`` fully-rendered worked examples
    (``ExampleGame``), plus the ``chosen_for`` of each one skipped.

    ``reports`` is ``build_coach_evidence``'s population-wide map, so no
    ``MatchReport`` is built twice; each selected match costs one fresh
    ``build_snapshot``, which nothing upstream caches. ``consensus_window``
    must be the one resolver (``_build_match_reports``), so an example is
    built under the same window as the report it is shown beside.
    """
    losses = [m for m in population_rows if m.result == "loss"]
    loss_ids = tuple(m.match_id for m in losses)
    has_turns: set[str] = set()
    if loss_ids:
        placeholders = ",".join("?" for _id in loss_ids)
        has_turns = {
            row["match_id"] for row in conn.execute(
                f"SELECT DISTINCT match_id FROM turns WHERE match_id IN ({placeholders})",
                loss_ids,
            )
        }
    recent_losses = tuple(m.match_id for m in losses if m.match_id in has_turns)
    started_at_by_id = {m.match_id: m.started_at for m in losses}
    deck_id_by_match = {m.match_id: m.deck_id for m in population_rows}
    row_by_id = {m.match_id: m for m in population_rows}

    selection = _select_examples(leaks, recent_losses, started_at_by_id)

    examples = []
    skipped: list[str] = []
    for match_id, chosen_for in selection:
        snap = build_snapshot(
            conn, match_id, consensus_since=_match_window(row_by_id[match_id], consensus_window),
            consensus_cache=consensus_cache, colors_cache=colors_cache, view_cache=view_cache,
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
            skipped.append(chosen_for)
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
    return tuple(examples), skipped


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
    """One kept identity's ``DeckList`` (see there for the unnamed rule).
    The second return value flags whether any grp_id went unnamed — the
    caller rolls every deck's flag into one shared gap line.
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
        # Two printings of one card are two grp_ids: merged by name.
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
    format-window match count. A kept identity with no format-window match
    is omitted: its list is not "current" by this report's window.
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
        gaps.append(_(
            "One or more decklists include a card with no matching row in the local card "
            "database; those copies are counted as unnamed rather than guessed at. Run "
            "`sensei-top cards --scryfall` to fill in the card database."
        ))
    return tuple(lines), gaps


def _build_field(
    conn: sqlite3.Connection,
    win_start: str | None,
    opponent_counts_by_key: dict[str, tuple[int, int]],
    fmt: str,
) -> tuple[tuple[FieldLine, ...], list[str]]:
    """The classified field in this report's format window, from
    ``guide/field.py::field_by_key``: grouped by ``archetype_key`` so a
    renamed archetype keeps one row (every name it carried as
    ``variants``), with the true classified-deck total as the share
    denominator, never the truncated top-N sum. ``your_rate`` joins through
    ``by_opponent``'s ``'archetype:' + archetype_key`` vocabulary; an
    unfaced key reads ``_rate(0, 0)``.
    """
    by_key, total = field_by_key(conn, fmt, win_start)
    if total == 0:
        return (), [_("No classified field corpus exists in this report's format window.")]

    candidates = [
        (key, variants, sum(n for _variant, n in variants)) for key, variants in by_key.items()
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
    conn: sqlite3.Connection,
    *,
    fmt: str,
    source: str = "all",
    report_cache: dict | None = None,
) -> CoachEvidence | None:
    """The full evidence base for the player-level coach report on ``fmt``
    (one of ``formats.FORMATS``), or ``None`` when there isn't enough of a
    population to say anything responsible (``review/leaks.py::MIN_SAMPLE``
    matches, every format counted) — the same gate every rollup in this
    package already applies before showing a rate. ``fmt`` has no default:
    every caller names the format it was asked for.

    The skill sections span the whole population, every format played; the
    format sections only ``fmt``'s matches since ``fmt``'s latest reset
    (docs/coach.md, "The two windows", names which is which).

    ``source`` reuses ``review/leaks.py::_scope_clause``'s vocabulary:
    ``"all"`` (the default here, unlike ``_scope_clause``'s ``"arena"``)
    or ``"arena"``/``"mtgo"``. An MTGO match counts under its
    ``v_match_format.format`` (a confirmed pick, else its inference), so
    ``"mtgo"`` still returns ``None`` on a database that has never run
    ``sensei-top cards --scryfall`` (no inference can fit a format without
    legality), unless MTGO matches carry a confirmed format, which needs no
    legality data.

    ``report_cache`` is the ``MatchReport`` cache ``find_leaks`` reads and
    writes (``_build_match_reports``); pass
    ``api/sql.py::_shared_report_cache(request, conn)`` from a route so a
    Leaks or Guide request in the same process can reuse these reports.
    ``None`` builds a dict that lives only as long as this one call.
    """
    population_rows, excluded = _population(conn, source)
    population = len(population_rows)
    if population < MIN_SAMPLE:
        return None

    gaps: list[str] = []
    if excluded["no_event_id"]:
        gaps.append(ngettext(
            "{n} Arena match(es) excluded: no event id was recorded, "
            "so the queue they were played in is unknown.",
            "{n} Arena match(es) excluded: no event id was recorded, "
            "so the queue they were played in is unknown.",
            excluded['no_event_id'],
        ).format(n=excluded['no_event_id']))
    if excluded["excluded_event"]:
        gaps.append(ngettext(
            "{n} match(es) excluded: played in an excluded event "
            "({events}).",
            "{n} match(es) excluded: played in an excluded event "
            "({events}).",
            excluded['excluded_event'],
        ).format(n=excluded['excluded_event'], events=", ".join(sorted(_EXCLUDED_EVENTS))))
    if excluded["limited"]:
        gaps.append(ngettext(
            "{n} match(es) excluded: played in a Limited queue, out of "
            "scope for this Constructed-focused report.",
            "{n} match(es) excluded: played in a Limited queue, out of "
            "scope for this Constructed-focused report.",
            excluded['limited'],
        ).format(n=excluded['limited']))
    if excluded["no_format"]:
        gaps.append(ngettext(
            "{n} match(es) excluded: none of the seven formats this app "
            "tracks is known for them (an Arena queue for another format, or an MTGO match "
            "with no confirmed or inferred format).",
            "{n} match(es) excluded: none of the seven formats this app "
            "tracks is known for them (an Arena queue for another format, or an MTGO match "
            "with no confirmed or inferred format).",
            excluded['no_format'],
        ).format(n=excluded['no_format']))
    if excluded["unresolved_cards"]:
        gaps.append(ngettext(
            "{n} MTGO match(es) excluded: revealed a card the "
            "local card database could not name, so its legality can't be read.",
            "{n} MTGO match(es) excluded: revealed a card the "
            "local card database could not name, so its legality can't be read.",
            excluded['unresolved_cards'],
        ).format(n=excluded['unresolved_cards']))
    if excluded["unknown_legality"]:
        gaps.append(ngettext(
            "{n} MTGO match(es) excluded: revealed a card "
            "with no legality on file (run `sensei-top cards --scryfall`).",
            "{n} MTGO match(es) excluded: revealed a card "
            "with no legality on file (run `sensei-top cards --scryfall`).",
            excluded['unknown_legality'],
        ).format(n=excluded['unknown_legality']))
    if excluded["no_fit"]:
        gaps.append(ngettext(
            "{n} MTGO match(es) excluded: no one of the seven formats this "
            "app tracks allows every card they revealed.",
            "{n} MTGO match(es) excluded: no one of the seven formats this "
            "app tracks allows every card they revealed.",
            excluded['no_fit'],
        ).format(n=excluded['no_fit']))
    if excluded["too_few_cards"]:
        gaps.append(ngettext(
            "{n} MTGO match(es) excluded: too few distinct "
            "cards revealed to judge the match's format at all.",
            "{n} MTGO match(es) excluded: too few distinct "
            "cards revealed to judge the match's format at all.",
            excluded['too_few_cards'],
        ).format(n=excluded['too_few_cards']))
    if excluded["ambiguous"]:
        gaps.append(ngettext(
            "{n} MTGO match(es) excluded: the revealed cards fit two or "
            "more formats, neither inside the other, and only a confirmed format can tell "
            "which.",
            "{n} MTGO match(es) excluded: the revealed cards fit two or "
            "more formats, neither inside the other, and only a confirmed format can tell "
            "which.",
            excluded['ambiguous'],
        ).format(n=excluded['ambiguous']))

    by_source = _build_by_source(population_rows)
    mtgo_deckless = sum(1 for m in population_rows if m.source == "mtgo" and m.deck_id is None)
    if mtgo_deckless:
        gaps.append(ngettext(
            "{n} MTGO match(es) are counted in the overall rate, the skill "
            "splits, leaks and turning points, but in no per-deck line: MTGO records no "
            "deck, and none was picked for them.",
            "{n} MTGO match(es) are counted in the overall rate, the skill "
            "splits, leaks and turning points, but in no per-deck line: MTGO records no "
            "deck, and none was picked for them.",
            mtgo_deckless,
        ).format(n=mtgo_deckless))

    match_ids = tuple(m.match_id for m in population_rows)
    results_by_id = {m.match_id: m.result for m in population_rows}

    as_of = max((m.started_at for m in population_rows if m.started_at), default=None)
    overall = _rate(sum(1 for m in population_rows if m.result == "win"), population)
    overall_games = _game_rate(conn, match_ids)
    g1, post_board, on_play, on_draw = _deck_game_split(conn, match_ids)

    # fmt's reset window, computed once before any report is built: it
    # scopes the format sections and seeds the one resolver every
    # build_match_report/build_snapshot/find_leaks call below must receive
    # (_build_match_reports), never a window a call computes for itself.
    resets = format_resets(conn, fmt)
    reset = resets[0] if resets else None
    win_start = window_start(reset) if reset is not None else None
    consensus_window = consensus_window_resolver(conn, {fmt: win_start})
    format_rows = [
        m for m in population_rows
        if m.format == fmt and (win_start is None or (m.started_at or "") >= win_start)
    ]
    if win_start is None:
        # No ban detected and no legality data to detect one from are
        # different claims (guide/bundle.py splits them the same way).
        if legality_known(conn, fmt):
            gaps.append(_(
                "No {fmt} format reset was detected — the format sections span every "
                "{fmt} match in this report rather than a post-reset window."
            ).format(fmt=fmt))
        else:
            gaps.append(_(
                "No {fmt} card legality data is present, so a format reset cannot be "
                "detected at all: the format sections span every {fmt} match in this "
                "report, which may pool across a ban. Run `sensei-top cards --scryfall` "
                "and rebuild this report before trusting them."
            ).format(fmt=fmt))
    if not format_rows:
        # The skill population cleared MIN_SAMPLE above, so the report is
        # still built; only its format sections are empty.
        if win_start is not None:
            gaps.append(_(
                "No {fmt} matches since {win_start} (the last {fmt} format change): the "
                "per-deck, per-role and per-opponent records and the decklists are empty. "
                "The skill sections still cover every format played, and the field section "
                "still shows the {fmt} field."
            ).format(fmt=fmt, win_start=win_start))
        else:
            gaps.append(_(
                "No {fmt} matches on file: the per-deck, per-role and per-opponent records "
                "and the decklists are empty. The skill sections still cover every format "
                "played, and the field section still shows the {fmt} field."
            ).format(fmt=fmt))

    # One cache set shared by by_deck's archetype classification and every
    # report build below, as guide/bundle.py does: a repeated opponent
    # archetype, the card-colour table and the view lookups cost one scan
    # each, not one per match.
    consensus_cache: dict = {}
    colors_cache: dict = {}
    colors_cache["colors_by_name"] = _card_colors_by_name(conn)
    view_cache: dict = {}
    if report_cache is None:
        report_cache = {}

    identities = list_identities(conn)
    by_deck, deck_gaps, kept_decks = _build_by_deck(
        conn, format_rows, colors_cache["colors_by_name"], identities, fmt,
    )
    gaps.extend(deck_gaps)
    deck_label_by_id: dict[str, str] = {
        did: (identity.name or "Unnamed deck")
        for identity in identities for did in identity.deck_ids
    }

    reports = _build_match_reports(
        conn, population_rows, consensus_window=consensus_window,
        consensus_cache=consensus_cache, colors_cache=colors_cache, view_cache=view_cache,
        report_cache=report_cache,
    )
    by_role = _build_by_role(format_rows, reports)

    mulligans = _build_mulligans(conn, match_ids)

    by_opponent, opponent_gaps, opponent_counts_by_key = _build_by_opponent(
        conn, format_rows, results_by_id
    )
    gaps.extend(opponent_gaps)

    leak_candidates, leaks, leak_gaps = _build_leaks(
        conn, match_ids, source=source, consensus_window=consensus_window,
        consensus_cache=consensus_cache, colors_cache=colors_cache, view_cache=view_cache,
        report_cache=report_cache,
    )
    gaps.extend(leak_gaps)

    deck_leaks, deck_leak_gaps = _build_deck_leaks(
        conn, _deck_candidates(population_rows, identities)[:TOP_DECKS], source=source,
        consensus_window=consensus_window, consensus_cache=consensus_cache,
        colors_cache=colors_cache, view_cache=view_cache, report_cache=report_cache,
    )
    gaps.extend(deck_leak_gaps)

    turning_points, turning_gaps = _build_turning_points(population_rows, reports)
    gaps.extend(turning_gaps)

    examples, skipped_examples = _build_examples(
        conn, population_rows, reports, leak_candidates, deck_label_by_id,
        consensus_window=consensus_window, consensus_cache=consensus_cache,
        colors_cache=colors_cache, view_cache=view_cache,
    )
    # _build_examples runs under english() (its examples are prompt-only), so
    # it hands back the codes of the examples it skipped, and the page's
    # sentence is written here, in the request language.
    for chosen_for in skipped_examples:
        gaps.append(_(
            "An example match chosen for \"{chosen_for}\" could not be rebuilt for "
            "display and was skipped."
        ).format(chosen_for=chosen_for))

    decklists, decklist_gaps = _build_decklists(conn, kept_decks, format_rows)
    gaps.extend(decklist_gaps)

    field, field_gaps = _build_field(conn, win_start, opponent_counts_by_key, fmt)
    gaps.extend(field_gaps)
    # duplicate_of IS NULL: a republished twin (metagame/dedup.py) can carry
    # a later event_date than its own survivor, which would otherwise move
    # "latest" without the corpus actually having anything newer in it.
    field_latest_event = conn.execute(
        "SELECT MAX(event_date) FROM meta_event WHERE duplicate_of IS NULL AND format = ?",
        (fmt,),
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
        fmt=fmt,
        format_counts=_format_counts(population_rows),
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
    """A compact snapshot of one report's headline numbers, stored
    (``coach/store.py``) and handed back into ``progress_since`` later. See
    docs/coach.md, "Progress".

    Every value is a plain ``dict``/``list``/``str``/``int``/``float``/
    ``None``: a tuple or a dataclass would come back reshaped from the
    ``json.dumps``/``json.loads`` round trip, which is this function's
    contract.

    Version 2: ``overall`` and ``leaks`` span every format played, and
    ``fmt`` names the report's format. A version 1 snapshot counted Standard
    alone, so ``coach/narrative.py::build_coach_prompt`` never diffs the two.
    """
    return {
        "version": 2,
        "fmt": evidence.fmt,
        "as_of": evidence.as_of,
        "population": evidence.population,
        "overall": {
            "wins": evidence.overall.wins, "n": evidence.overall.n, "rate": evidence.overall.rate,
        },
        # Stored, but read by nothing: progress_since never diffs by_source.
        # A stored report missing this key is still valid.
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
    a ``metrics_snapshot()`` dict saved at some earlier ``as_of`` — the lines
    ``build_coach_prompt`` sets under the previous report's focus areas.
    See docs/coach.md, "Progress".

    A previously-known leak ``code`` is checked for raw presence among the
    *new* matches alone, not re-run through ``find_leaks``, whose
    ``MIN_SAMPLE`` gate a handful of new matches will almost never clear.
    Which stored report ``metrics`` comes from (the previous one of the same
    format) is the caller's choice.
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
    report_cache: ReportCache = {}
    # Its own resolver, since this entry point shares none with
    # build_coach_evidence: build_match_report's None default would read
    # across a reset whenever one exists.
    reports = _build_match_reports(
        conn, new_rows, consensus_window=consensus_window_resolver(conn),
        consensus_cache=consensus_cache, colors_cache=colors_cache, view_cache=view_cache,
        report_cache=report_cache,
    )

    for code in old_codes:
        if code in ("mana_screwed", "mana_flooded"):
            flag_index = 0 if code == "mana_screwed" else 1
            flags_by_id = {mid: _mana_flags(conn, mid)[flag_index] for mid in new_match_ids}
            # Rule 4: a match with no turns rows (every MTGO match) is
            # unknown for this flag, not "clean": it must not swell the
            # denominator or the "not observed" reading below.
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
