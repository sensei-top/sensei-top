"""Cross-match pattern rollup — the leak finder.

Reruns every completed match's own report (the same ``build_match_report``
the per-match panel calls) and ranks which finding codes move the win rate,
each gated on ``MIN_SAMPLE`` on both sides and shown with a Wilson score
interval, never a bare rate. Mana flood and screw live here and only here,
as rates across many games. Only a finding whose analyzer set
``Finding.pattern`` enters the ranking (``find_leaks``). See
``docs/review.md``, "The leak finder (`review/leaks.py`)".
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace

from sensei_top.i18n import ENGLISH, _, current_language
from sensei_top.review.findings import MatchReport
from sensei_top.review.match_report import build_match_report

# A shared ``MatchReport`` cache (``report_cache`` below, ``coach/evidence.py``,
# ``api/sql.py::_shared_report_cache``) and its key — see ``report_cache_key``.
ReportCacheKey = tuple[str, str | None] | tuple[str, str | None, str]
ReportCache = dict[ReportCacheKey, MatchReport | None]


def report_cache_key(match_id: str, window: str | None) -> ReportCacheKey:
    """The key a ``MatchReport`` is cached under: its match, the consensus
    window it was built under, and the language it was built in.

    The language is in the key because a report's findings and gaps are
    prose, written in whatever language the request asked for (``i18n.py``),
    and one cache is shared across requests: a Leaks or Coach page loaded in
    Portuguese fills it, and the prompts — built under ``i18n.english()`` —
    read it next. Keyed by language, a prompt only ever gets a report built
    in English. Read here, where the cache is read and filled, not by the
    route: the route hands the cache in before the prompt builder enters
    ``english()``.

    English keeps the two-part ``(match_id, window)`` key, so an English-only
    caller (a test) can build one by hand; any other language adds itself as
    a third part.
    """
    language = current_language()
    return (match_id, window) if language == ENGLISH else (match_id, window, language)


MIN_SAMPLE = 10  # matches needed on *each* side of a comparison, with/without

MANA_SCREW_LAND_TARGET = 4
MANA_SCREW_SELF_TURN_INDEX = 4
MANA_FLOOD_MARGIN = 0.15


@dataclass(frozen=True, slots=True)
class Leak:
    """One recurring pattern, and how much it actually moves your win rate.

    ``code`` is a real ``Finding.code`` for a pattern-rollup leak, or one of
    this module's own two synthetic codes (``mana_screwed``/``mana_flooded``)
    for the deckbuilding signals no per-match analyzer emits at all.
    """

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
    match_ids_with: tuple[str, ...]


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval — stable at small n, unlike a normal
    approximation, which is why it is the standard choice for a win rate
    computed from a few dozen matches rather than a few thousand."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom))


def _leak_from_counts(
    code: str, category: str, sample_title: str,
    with_ids: list[str], with_wins: int, total_n: int, total_wins: int,
) -> Leak | None:
    n_with = len(with_ids)
    n_without = total_n - n_with
    if n_with < MIN_SAMPLE or n_without < MIN_SAMPLE:
        return None
    wins_without = total_wins - with_wins
    rate_with = with_wins / n_with
    rate_without = wins_without / n_without
    return Leak(
        code=code, category=category, sample_title=sample_title,
        n_with=n_with, win_rate_with=rate_with, ci_with=wilson(with_wins, n_with),
        n_without=n_without, win_rate_without=rate_without,
        ci_without=wilson(wins_without, n_without),
        gap=abs(rate_with - rate_without),
        match_ids_with=tuple(with_ids),
    )


# ``matches`` with its deck as the user has it (``v_match_deck``: the pick for
# an MTGO match, else what the log named), wrapped so ``scope_clause``'s bare
# column names stay unambiguous — the view repeats ``match_id`` and ``source``.
# Joined on ``match_id``; no index serves the view's COALESCEd ``deck_id``
# (migration 050's header), so a deck filter is a scan of ``matches``, which
# this module already does once per population.
_MATCHES_WITH_DECK = (
    "(SELECT m.match_id, m.source, md.deck_id, m.started_at, m.result "
    "FROM matches m JOIN v_match_deck md ON md.match_id = m.match_id)"
)

# The same rows with each match's read-time format (``v_match_format``),
# which picks the consensus window ``find_leaks`` builds that match's report
# under. Wrapped once more for the same reason: ``v_match_format`` repeats
# ``match_id`` too.
_MATCHES_WITH_FORMAT = (
    f"(SELECT p.*, f.format AS match_format FROM {_MATCHES_WITH_DECK} p "
    "JOIN v_match_format f ON f.match_id = p.match_id)"
)


def scope_clause(
    deck_ids: tuple[str, ...] | None,
    since: str | None,
    source: str = "arena",
    *,
    match_ids: tuple[str, ...] | None = None,
) -> tuple[str, list]:
    """The WHERE fragment (beyond ``result IN (...)``) and its params shared
    by every match-population query below; ``None`` leaves that filter off.

    ``source`` defaults to ``'arena'``: every finding was tuned against Arena
    matches alone. ``'all'`` drops the filter.

    ``match_ids`` scopes to that exact set of matches. An explicit empty
    tuple scopes to no match at all, for a caller whose own candidate set is
    genuinely empty rather than "unscoped"."""
    clauses: list[str] = []
    params: list = []
    if deck_ids:
        clauses.append(f"deck_id IN ({','.join('?' for _ in deck_ids)})")
        params.extend(deck_ids)
    if since is not None:
        clauses.append("started_at >= ?")
        params.append(since)
    if source != "all":
        clauses.append("source = ?")
        params.append(source)
    if match_ids is not None:
        if match_ids:
            clauses.append(f"match_id IN ({','.join('?' for _ in match_ids)})")
            params.extend(match_ids)
        else:
            clauses.append("1 = 0")
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def mana_flags(conn, match_id: str) -> tuple[bool | None, bool | None]:
    """One match's own ``(screwed, flooded)`` flags — the per-match body
    ``_mana_leaks`` rolls up into a population-wide rate, and the one place
    the rule lives: no analyzer emits either as a ``Finding.code``, and
    ``coach/evidence.py`` calls this for a leak's rate before and after a
    date rather than re-deriving it.

    Either flag is ``None`` — unknown, never ``False`` — when its own match
    has no evidence to answer it from (rule 4: unknown is ``NULL``, not a
    guess). ``screwed`` is ``None`` when the match has no self-turn row
    with an own-turn number (every MTGO match, since
    ``projector/mtgo/project.py`` never writes ``turns``, and an Arena match
    whose turns Arena never numbered); a short game, or one partly numbered,
    that never shows the check's own turn index stays ``False``, not unknown.
    ``flooded`` is ``None`` whenever its own narrower evidence is missing: no
    deck row, an unnamed/empty decklist, an MTGO deck with maindeck copies it
    could not resolve to a card (a partial list), or no usable first/last
    ``turns`` rows to compute a lands-seen ratio from.
    """
    self_turn_rows = conn.execute(
        """
        SELECT self_turn_index, self_lands
          FROM v_self_turns
         WHERE match_id = ? AND self_turn_index IS NOT NULL
         ORDER BY game_number, turn_number
        """,
        (match_id,),
    ).fetchall()
    screwed: bool | None
    if not self_turn_rows:
        screwed = None
    else:
        screwed = any(
            r["self_turn_index"] >= MANA_SCREW_SELF_TURN_INDEX
            and r["self_lands"] is not None
            and r["self_lands"] < MANA_SCREW_LAND_TARGET
            for r in self_turn_rows
        )

    flooded: bool | None = None
    deck_row = conn.execute(
        "SELECT d.deck_id, v.maindeck_size, v.land_count, v.unnamed_count, "
        "v.unresolved_count "
        "FROM matches m JOIN v_match_deck md ON md.match_id = m.match_id "
        "JOIN decks d ON d.deck_id = md.deck_id "
        "LEFT JOIN v_deck_land_count v ON v.deck_id = d.deck_id WHERE m.match_id = ?",
        (match_id,),
    ).fetchone()
    if (
        deck_row is not None
        and not deck_row["unnamed_count"]
        and not deck_row["unresolved_count"]
        and deck_row["maindeck_size"]
    ):
        last_turn = conn.execute(
            "SELECT self_library, self_lands FROM turns WHERE match_id = ? "
            "ORDER BY turn_number DESC LIMIT 1",
            (match_id,),
        ).fetchone()
        first_turn = conn.execute(
            "SELECT self_library FROM turns WHERE match_id = ? ORDER BY turn_number LIMIT 1",
            (match_id,),
        ).fetchone()
        if (
            last_turn and first_turn
            and last_turn["self_library"] is not None
            and last_turn["self_lands"] is not None
        ):
            cards_seen = (first_turn["self_library"] or 0) - last_turn["self_library"]
            if cards_seen > 0:
                deck_ratio = deck_row["land_count"] / deck_row["maindeck_size"]
                seen_ratio = last_turn["self_lands"] / cards_seen
                flooded = seen_ratio - deck_ratio >= MANA_FLOOD_MARGIN
            # else: cards_seen <= 0 (degenerate turn history) — no usable
            # ratio to compute; flooded stays unknown, not False.

    return screwed, flooded


def _mana_leaks(
    conn,
    *,
    deck_ids: tuple[str, ...] | None = None,
    since: str | None = None,
    source: str = "arena",
    match_ids: tuple[str, ...] | None = None,
) -> list[Leak]:
    """Screw/flood rates, from ``mana_flags`` once per match in the
    population.

    A match whose flag is unknown (``None``: every MTGO match's ``screwed``)
    is *excluded* from that flag's population, never counted as clean. Screw
    and flood keep their own separate known populations (a match can be
    missing evidence for one and not the other, e.g. a decklist with unnamed
    cards still has ``turns`` rows), each gated on ``MIN_SAMPLE``
    independently — a comparison rate is only ever computed over matches
    that actually answered the question, per rule 4.
    """
    scope_sql, scope_params = scope_clause(deck_ids, since, source, match_ids=match_ids)
    rows = conn.execute(
        f"SELECT match_id, result FROM {_MATCHES_WITH_DECK} "
        f"WHERE result IN ('win', 'loss'){scope_sql}",
        scope_params,
    ).fetchall()
    match_results = {r["match_id"]: r["result"] for r in rows}
    if len(match_results) < MIN_SAMPLE:
        # Fast path only: every flag's own known population is a subset of
        # this one, so it can never clear MIN_SAMPLE when this doesn't.
        return []

    screwed_ids: list[str] = []
    screwed_known_ids: list[str] = []
    flooded_ids: list[str] = []
    flooded_known_ids: list[str] = []
    for match_id in match_results:
        screwed, flooded = mana_flags(conn, match_id)
        if screwed is not None:
            screwed_known_ids.append(match_id)
            if screwed:
                screwed_ids.append(match_id)
        if flooded is not None:
            flooded_known_ids.append(match_id)
            if flooded:
                flooded_ids.append(match_id)

    leaks = []
    for code, ids, known_ids, label in (
        ("mana_screwed", screwed_ids, screwed_known_ids,
         _("Stuck on lands by your 4th turn")),
        ("mana_flooded", flooded_ids, flooded_known_ids,
         _("Lands running heavy relative to your deck's own ratio")),
    ):
        known_n = len(known_ids)
        if known_n < MIN_SAMPLE:
            continue
        known_wins = sum(1 for mid in known_ids if match_results[mid] == "win")
        wins = sum(1 for mid in ids if match_results[mid] == "win")
        leak = _leak_from_counts("deck", label, label, ids, wins, known_n, known_wins)
        if leak is not None:
            leaks.append(replace(leak, code=code, category="deckbuilding"))
    return leaks


def find_leaks(
    conn,
    *,
    deck_ids: tuple[str, ...] | None = None,
    since: str | None = None,
    match_ids: tuple[str, ...] | None = None,
    consensus_since: str | None = None,
    consensus_window: Callable[[str], str | None] | None = None,
    consensus_cache: dict | None = None,
    colors_cache: dict | None = None,
    view_cache: dict | None = None,
    report_cache: ReportCache | None = None,
    source: str = "arena",
) -> list[Leak]:
    """Every recurring finding code, ranked by how much it actually moves
    your win rate — largest gap first, ties by code. Costs one
    ``build_match_report`` per completed match, the same computation the
    per-match panel pays for one match at a time; cheap enough to redo
    wholesale, like ``classify_matches``.

    ``deck_ids``/``since`` scope the population to one deck's matches (or a
    date window); ``None`` leaves it unscoped.

    ``consensus_window`` and ``consensus_since`` are unrelated to ``since``
    above — ``since`` scopes *which matches* this call ranks; these choose
    the format-reset window each ``build_match_report`` call's own
    opponent-consensus lookup is built under (see
    ``review/snapshot.py::build_snapshot``'s docstring). Pass one of them,
    never both:

    - ``consensus_window`` measures each match against its own format's
      window: it maps a format to that format's window, and is asked once
      per format the population holds, under the match's
      ``v_match_format.format``. A match with no format is never asked
      about and gets no window: its report has no consensus to window
      (``build_consensus`` answers ``None`` for it), and it must not borrow
      another format's. ``review/`` cannot resolve a window itself
      (``guide.window`` would be a package cycle), so the caller supplies
      the resolver: ``api/routes/review.py::_leaks_consensus_window`` from
      the Leaks routes, ``guide/window.py::consensus_window_resolver`` from
      ``guide/bundle.py`` and ``coach/evidence.py``.
    - ``consensus_since`` is one window for every match, whatever its
      format. No caller passes it.

    Neither (the default) builds every report with no window, which is only
    correct when the caller knows no corpus it reads can cross a reset.

    ``match_ids`` scopes to an exact set of matches instead of deriving one
    from ``deck_ids``/``since``: ``coach/evidence.py``'s own population, or
    one kept deck's subset of it, which no deck/date filter can express
    (``docs/coach.md``, "Scope"). Composable with the other three scope
    arguments (every non-``None`` one becomes an additional ``AND`` clause);
    an empty tuple scopes to no match (``scope_clause``).

    ``consensus_cache``/``colors_cache``/``view_cache``, when given, are
    threaded through to every ``build_match_report`` call so a repeated
    opponent archetype, the classifier's card-colour table, or one of
    ``build_snapshot``'s own four repeated view lookups costs one scan
    across the whole call rather than one per match — pass the same dicts
    across a scoped and an unscoped call in the same request
    (``guide/bundle.py`` does exactly this) to share the cache between them.
    A caller with none to share may omit them; fresh ones are created for
    the duration of this call regardless, since even one call commonly
    repeats a handful of popular archetypes across its matches.

    ``report_cache``, unlike the other three, is *not* created when omitted
    — one call already builds every report exactly once. When given, a
    ``MatchReport`` already present under its ``report_cache_key`` (the
    match, the window that match's report was built under, and the current
    language) is reused instead of rebuilt, and every report this call
    builds is stored back into it. A ``MatchReport`` depends only on
    ``match_id``, that window and the database (the match's format is read
    from the database, so it is the match's own whatever the window), never
    on this function's own scoping (``deck_ids``/``since``/``source``), so
    the same dict stays valid across a scoped and an unscoped call, across a
    per-format and a single-window caller, or across a caller that already
    built some of these reports itself (``coach/evidence.py`` builds its
    population's own reports, under the same resolver, before calling this).
    A report built under one window, or in another language, is never handed
    to a caller asking under another, because both are in the key.
    """
    if consensus_window is not None and consensus_since is not None:
        raise ValueError("pass consensus_window or consensus_since, not both")
    windows_by_format: dict[str, str | None] = {}

    def window_for(match_format: str | None) -> str | None:
        if consensus_window is None:
            return consensus_since
        if match_format is None:
            return None  # no format, no consensus: never another format's window
        if match_format not in windows_by_format:
            windows_by_format[match_format] = consensus_window(match_format)
        return windows_by_format[match_format]

    if consensus_cache is None:
        consensus_cache = {}
    if colors_cache is None:
        colors_cache = {}
    if view_cache is None:
        view_cache = {}
    scope_sql, scope_params = scope_clause(deck_ids, since, source, match_ids=match_ids)
    matches = conn.execute(
        f"SELECT match_id, result, match_format FROM {_MATCHES_WITH_FORMAT} "
        f"WHERE result IN ('win', 'loss'){scope_sql}",
        scope_params,
    ).fetchall()
    match_results = {row["match_id"]: row["result"] for row in matches}
    match_formats = {row["match_id"]: row["match_format"] for row in matches}
    total_n = len(matches)
    total_wins = sum(1 for result in match_results.values() if result == "win")

    by_code: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for match_id in match_results:
        match_window = window_for(match_formats[match_id])
        cache_key = report_cache_key(match_id, match_window)
        if report_cache is not None and cache_key in report_cache:
            report = report_cache[cache_key]
        else:
            report = build_match_report(
                conn, match_id, consensus_since=match_window,
                consensus_cache=consensus_cache, colors_cache=colors_cache,
                view_cache=view_cache,
            )
            if report_cache is not None:
                report_cache[cache_key] = report
        if report is None:
            continue
        # Only findings an analyzer opted into pattern-hood ever reach this rollup
        # (Finding.pattern is None by default) — a finding that fires whenever an
        # analyzer merely *had data* (an archetype resolved, a corpus covered the
        # pairing) is not a recurring pattern in what was played, and a code
        # conditioned on the very outcome being measured (a hand-size finding that
        # only exists in losses) would leak its own definition into the win-rate
        # gap. See docs/review.md, "The leak finder (`review/leaks.py`)".
        seen_this_match: dict[str, tuple[str, str]] = {}
        for f in report.findings:
            if f.pattern is None:
                continue
            seen_this_match.setdefault(f.code, (str(f.category), f.pattern))
        for code, (category, pattern) in seen_this_match.items():
            by_code[code].append((match_id, category, pattern))

    leaks: list[Leak] = []
    for code, occurrences in by_code.items():
        with_ids = [mid for mid, _, _ in occurrences]
        wins_with = sum(1 for mid in with_ids if match_results[mid] == "win")
        category = occurrences[0][1]
        # `pattern` is each code's own static label (never a per-match number),
        # so every occurrence carries the same one.
        pattern = occurrences[0][2]
        leak = _leak_from_counts(
            code, category, pattern, with_ids, wins_with, total_n, total_wins
        )
        if leak is not None:
            leaks.append(leak)

    leaks.extend(_mana_leaks(conn, deck_ids=deck_ids, since=since, source=source,
                              match_ids=match_ids))
    # Tie-break by code: an equal gap otherwise keeps encounter order, which
    # shifts as matches are added, so "the top leak" could change with no
    # change to any of its own numbers.
    leaks.sort(key=lambda leak: (-leak.gap, leak.code))
    return leaks
