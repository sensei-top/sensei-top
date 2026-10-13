"""Orchestration: build one match's snapshot, run every analyzer over it, and
assemble the result into a ``MatchReport``.
"""

from __future__ import annotations

import sqlite3

from sensei_top.i18n import _
from sensei_top.review.analyzers import ANALYZERS
from sensei_top.review.consensus import ArchetypeConsensus
from sensei_top.review.findings import Finding, Gap, MatchReport
from sensei_top.review.snapshot import build_snapshot


def build_match_report(
    conn: sqlite3.Connection,
    match_id: str,
    *,
    consensus_since: str | None = None,
    consensus_cache: dict[tuple[str | None, str | None, str | None], ArchetypeConsensus | None]
    | None = None,
    colors_cache: dict[str, dict[str, frozenset[str]]] | None = None,
    view_cache: dict | None = None,
) -> MatchReport | None:
    """The post-game report for one match, computed fresh from already
    -projected data — never stored, so it is always current with respect to
    `cards` and `decks`, which the projector does not own (see
    ``review/__init__.py``). Returns ``None`` when the match itself does not
    exist, matching ``build_snapshot``.

    ``consensus_since``/``consensus_cache``/``colors_cache``/``view_cache``
    pass straight through to ``build_snapshot`` — see its own docstring for
    what each means, in particular that ``consensus_since=None`` is only
    correct when the caller knows this format's corpus cannot cross a
    reset; a caller rebuilding many matches' reports in one request
    (``review/leaks.py``) should pass one dict of each cache, shared across
    calls, and each match the window of that match's own format (plan 13,
    S8c) — the caches key on the format and the window, so matches of
    different formats can share them.
    """
    snap = build_snapshot(
        conn, match_id, consensus_since=consensus_since, consensus_cache=consensus_cache,
        colors_cache=colors_cache, view_cache=view_cache,
    )
    if snap is None:
        return None

    if snap.self_seat is None:
        # self/opp columns are meaningless without a resolved seat (the same
        # rule turns rows follow — docs/conventions.md), so every analyzer
        # here would find nothing at all. One clear gap beats each of the
        # eight analyzers separately reporting the same absence.
        return MatchReport(
            match_id=snap.match_id,
            deck_id=snap.deck_id,
            result=snap.result,
            games=snap.games,
            findings=(),
            gaps=(
                Gap(
                    analyzer="match_report",
                    reason=_("This match never resolved which seat was yours, so nothing about "
                             "your own turns could be measured."),
                    game_number=None,
                ),
            ),
            opponent_label=snap.opponent_label,
        )

    findings: list[Finding] = []
    gaps: list[Gap] = []
    for analyze in ANALYZERS:
        result = analyze(snap)
        findings.extend(result.findings)
        gaps.extend(result.gaps)

    # A stable order, not registry order-of-arrival: two runs over the same
    # data must produce byte-identical output (tested directly).
    findings.sort(key=lambda f: (f.game_number or 0, f.turn_number or 0, f.code))
    gaps.sort(key=lambda g: (g.game_number or 0, g.analyzer))

    return MatchReport(
        match_id=snap.match_id,
        deck_id=snap.deck_id,
        result=snap.result,
        games=snap.games,
        findings=tuple(findings),
        gaps=tuple(gaps),
        opponent_label=snap.opponent_label,
    )
