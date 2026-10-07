"""Assembly: one deck guide, everything else in this package pulled
together for one deck, under the deck's own format (plan 13, D15).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from sensei_top.guide.deck import DeckIdentity, identity_format, resolve
from sensei_top.guide.field import FieldEvidence, build_field
from sensei_top.guide.list_diff import ListDiff, build_list_diff
from sensei_top.guide.play import (
    BoardCurvePoint,
    GameLengthBucket,
    MulliganBucket,
    WLTally,
    ZoneCurveSplit,
    board_curve,
    game_length,
    key_card_timing,
    mulligan_record,
    zone_curve,
)
from sensei_top.guide.window import (
    FormatReset,
    consensus_window_resolver,
    format_resets,
    legality_known,
)
from sensei_top.guide.window import window_start as _window_start
from sensei_top.review.leaks import Leak, find_leaks

# The format_unknown note (plan 13, S8), verbatim.
FORMAT_UNKNOWN_GAP = (
    "This deck's format is unknown: its deck record names no constructed format, and "
    "none of its matches has one from the log, a pick or inference. Without a format "
    "there is no field to compare it against, so the field shares, consensus list and "
    "matchup rates are left out. On MTGO, confirm the format on one of its matches and "
    "rebuild this guide."
)


@dataclass(frozen=True, slots=True)
class PlayEvidence:
    board_curve: dict[str, dict[str, BoardCurvePoint]]
    zone_curve: dict[str, ZoneCurveSplit]
    key_card_timing: dict[str, dict[str, WLTally]]
    mulligan_record: dict[str, MulliganBucket]
    game_length: dict[str, GameLengthBucket]


@dataclass(frozen=True, slots=True)
class Provenance:
    deck: DeckIdentity
    reset: FormatReset | None
    window_start: str | None
    matches_before_reset: int
    corpus_fetched_at: str | None
    corpus_latest_event: str | None
    classified_decks: int
    oracle_coverage: tuple[int, int]  # (cards with text, cards in your 75)


@dataclass(frozen=True, slots=True)
class DeckGuide:
    provenance: Provenance
    play: PlayEvidence
    leaks: tuple[Leak, ...]
    leaks_all_decks: tuple[Leak, ...]
    list_diff: ListDiff | None
    field: FieldEvidence
    gaps: tuple[str, ...]


def _oracle_coverage(conn: sqlite3.Connection, identity: DeckIdentity) -> tuple[int, int]:
    maindeck = identity.current_cards.get("maindeck") or []
    sideboard = identity.current_cards.get("sideboard") or []
    grp_ids = list({*maindeck, *sideboard})
    if not grp_ids:
        return (0, 0)
    with_text = conn.execute(
        f"SELECT COUNT(*) FROM cards WHERE grp_id IN ({','.join('?' for _ in grp_ids)}) "
        f"AND oracle_text IS NOT NULL",
        grp_ids,
    ).fetchone()[0]
    return (with_text, len(grp_ids))


def build_deck_guide(
    conn: sqlite3.Connection, key: str, *, report_cache: dict | None = None,
) -> DeckGuide | None:
    """One deck's whole guide bundle, under the deck's format
    (``guide/deck.py``'s ``identity_format``, D15): its resets, its field and
    its own archetype are that format's. A deck with no format gets no field
    block, no list diff and no reset, and the ``FORMAT_UNKNOWN_GAP`` note in
    their place; its own play evidence and leaks are still built.

    ``report_cache`` is the
    ``(match_id, window)``-keyed ``MatchReport`` cache
    ``review/leaks.py::find_leaks`` reads and writes; pass
    ``api/sql.py::_shared_report_cache(request, conn)`` from a route so a
    report this guide builds can be reused by a Leaks or Coach request in
    the same process rather than rebuilt from scratch, instead of the fresh,
    request-scoped dict below. ``None`` (the CLI ``guide`` command's own
    call, and this function's default) keeps today's behaviour exactly: a
    dict that lives only as long as this one call.
    """
    identity = resolve(conn, key)
    if identity is None:
        return None

    fmt = identity_format(conn, identity)
    resets = format_resets(conn, fmt) if fmt is not None else []
    reset = resets[0] if resets else None

    window_start = None
    matches_before_reset = identity.matches
    if reset is not None:
        window_start = _window_start(reset)
        # Through v_match_deck, not matches.deck_id: an MTGO match's deck is
        # its pick, and matches.deck_id is NULL for every one of them.
        matches_before_reset = sum(
            1 for row in conn.execute(
                f"SELECT m.started_at FROM matches m "
                f"JOIN v_match_deck md ON md.match_id = m.match_id "
                f"WHERE md.deck_id IN ({','.join('?' for _ in identity.deck_ids)})",
                identity.deck_ids,
            )
            if (row["started_at"] or "") <= reset.date
        )

    play = PlayEvidence(
        board_curve=board_curve(conn, identity),
        zone_curve=zone_curve(conn, identity),
        key_card_timing=key_card_timing(conn, identity),
        mulligan_record=mulligan_record(conn, identity),
        game_length=game_length(conn, identity),
    )

    # One cache set shared across both calls: the deck-scoped population is
    # a subset of the all-decks one, so most opponent archetypes, the
    # classifier's card-colour table, and build_snapshot's own repeated view
    # lookups all recur between them (find_leaks/build_consensus/
    # build_snapshot docstrings) — and a match reported in both populations
    # (report_cache) needs its MatchReport built only once, since the cache
    # is keyed by (match_id, window), never by find_leaks's own scoping, and
    # both calls give a match the same window. report_cache
    # itself may be the caller's shared, cross-request dict (see this
    # function's own docstring) rather than one scoped to this call alone.
    consensus_cache: dict = {}
    colors_cache: dict = {}
    view_cache: dict = {}
    if report_cache is None:
        report_cache = {}
    # Both calls measure each match against its own format's consensus
    # window (plan 13, S8c): the opponent consensus a finding is measured
    # against must not be aggregated across that format's reset. The all-decks
    # rollup spans every format; this deck's own matches are mostly in its
    # format, whose window is already known above.
    consensus_window = consensus_window_resolver(
        conn, {fmt: window_start} if fmt is not None else None,
    )

    leaks = tuple(find_leaks(
        conn, deck_ids=identity.deck_ids, consensus_window=consensus_window,
        consensus_cache=consensus_cache, colors_cache=colors_cache,
        view_cache=view_cache, report_cache=report_cache,
    ))
    leaks_all_decks = tuple(find_leaks(
        conn, consensus_window=consensus_window,
        consensus_cache=consensus_cache, colors_cache=colors_cache,
        view_cache=view_cache, report_cache=report_cache,
    ))

    diff = build_list_diff(conn, identity, reset=reset, fmt=fmt) if fmt is not None else None
    field = build_field(conn, identity, reset=reset, fmt=fmt)

    oracle_coverage = _oracle_coverage(conn, identity)

    gaps: list[str] = []
    if fmt is None:
        gaps.append(FORMAT_UNKNOWN_GAP)
    elif diff is None:
        gaps.append(
            "Your own deck could not be classified against the field's archetype "
            "definitions — the list-vs-consensus comparison is unavailable."
        )
    with_text, total_cards = oracle_coverage
    if total_cards and with_text < total_cards:
        gaps.append(
            f"Rules text is missing for {total_cards - with_text} of your {total_cards} "
            f"cards — run `sensei-top cards --scryfall` to fill this in."
        )
    if fmt is not None and reset is None:
        # Two different answers, and the difference matters: with no legality
        # data a ban cannot be detected at all, so "no reset" would be a
        # claim about the corpus that nothing here is in a position to make.
        if legality_known(conn, fmt):
            gaps.append(
                "No format reset was detected in the tournament corpus — every number below "
                "spans its full available history."
            )
        else:
            gaps.append(
                "No card legality data is present, so a format reset cannot be detected at "
                "all: every field share, consensus list and matchup rate below may pool "
                "across a ban. Run `sensei-top cards --scryfall` and rebuild this guide "
                "before trusting them."
            )
    if not identity.deck_ids:
        gaps.append("This deck has no recorded matches.")

    provenance = Provenance(
        deck=identity,
        reset=reset,
        window_start=window_start,
        matches_before_reset=matches_before_reset,
        corpus_fetched_at=field.corpus_fetched_at,
        corpus_latest_event=field.corpus_latest_event,
        classified_decks=field.classified_decks,
        oracle_coverage=oracle_coverage,
    )

    return DeckGuide(
        provenance=provenance,
        play=play,
        leaks=leaks,
        leaks_all_decks=leaks_all_decks,
        list_diff=diff,
        field=field,
        gaps=tuple(gaps),
    )
