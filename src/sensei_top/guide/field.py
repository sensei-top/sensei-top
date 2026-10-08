"""The field, after a reset — the data behind the guide's "The field" section.

Two rules this module exists to enforce mechanically, both taken from real
mistakes an earlier hand-written guide made and then corrected:

* **The share denominator is every classified deck in the window, not the
  displayed top-N** — dividing by a truncated list inflated every share by
  about 6 points in that guide's first draft.
* **A pre-reset matchup rate is void, not merely stale, once the opponent
  archetype has changed** (``guide.window.ArchetypeChange``) — it must be
  rendered as absent, never as a number that looks current.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from sensei_top.guide.deck import DeckIdentity, identity_format
from sensei_top.guide.window import (
    ArchetypeChange,
    FormatReset,
    structural_change,
    window_start,
)
from sensei_top.review.snapshot import _classify_own_deck


@dataclass(frozen=True, slots=True)
class ArchetypeShare:
    archetype: str
    decks: int
    share: float
    share_before_reset: float | None
    movement: float | None  # share - share_before_reset


@dataclass(frozen=True, slots=True)
class PersonalRate:
    archetype: str
    matches: int
    wins: int
    losses: int
    carryable: bool  # False when the archetype changed/vanished at the reset


@dataclass(frozen=True, slots=True)
class DeckPerformance:
    decks: int
    wins: int
    losses: int
    win_rate: float | None


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    fmt: str | None  # None: the deck's format is unknown, and every field below is empty
    window_start: str | None  # None = the whole corpus, no reset in effect
    classified_decks: int
    shares: tuple[ArchetypeShare, ...]
    changes: dict[str, ArchetypeChange]
    personal_rates: tuple[PersonalRate, ...]
    own_performance: DeckPerformance | None
    corpus_fetched_at: str | None
    corpus_latest_event: str | None


def _classified_deck_total(conn: sqlite3.Connection, where: str, params: list) -> int:
    """The TRUE total classified-deck count for a windowed query — the
    denominator every share divides by, which must never be the truncated
    top_n sum. The single source for this query: ``brief/narrative.py``'s
    ``_archetype_share`` shares it rather than repeating it, since both
    guard against the exact same truncated-denominator bug. Their *count*
    queries stay separate — this one's caller groups by every archetype
    name up to ``top_n`` for display, that one filters to a single
    archetype_key with no truncation at all, so there is nothing left to
    share once the denominator is factored out.
    """
    return conn.execute(
        f"""
        SELECT COUNT(*) FROM meta_deck_archetype a JOIN meta_event e ON e.event_id = a.event_id
         WHERE {where} AND a.archetype_name IS NOT NULL
        """,
        params,
    ).fetchone()[0]


def field_window(fmt: str, since: str | None) -> tuple[str, list]:
    """The field's own window clause: ``e.format = ?``, plus ``e.event_date
    >= ?`` once a window start exists — assumes the caller's query aliases
    ``meta_event`` as ``e``. The one definition of "the field's window"
    shared by ``_shares_for_window`` and ``field_by_key`` here,
    ``brief/coverage.py``'s ``_field_counts``, ``brief/narrative.py``'s
    ``_archetype_share``, and ``coach/evidence.py``'s ``_build_field`` —
    five places that used to build this clause by hand.
    """
    clauses = ["e.format = ?"]
    params: list = [fmt]
    if since is not None:
        clauses.append("e.event_date >= ?")
        params.append(since)
    return " AND ".join(clauses), params


def field_by_key(
    conn: sqlite3.Connection, fmt: str, since: str | None
) -> tuple[dict[str, tuple[tuple[str, int], ...]], int]:
    """The classified field grouped by ``archetype_key``, never by display
    name: two keys can share one name (a "Midrange" label reused across
    colour pairs), and a name -> key lookup then hands one key's share to
    the other — measured on the real corpus before this was keyed properly.
    Each key maps to every name it has carried in the window, as
    ``(name, deck_count)`` pairs sorted by ``(-deck_count, name)`` — the
    first entry is always the key's most common name, lowest name on ties.

    No NULL filter: both columns are ``NOT NULL`` (``migrations/
    012_metagame.sql``), and an unclassified deck has no row here at all.

    Also returns the window's true classified-deck total
    (``_classified_deck_total``), the shared denominator every caller's
    share divides by.

    Shared by ``brief/coverage.py``'s ``_field_counts`` (a thin adapter that
    keeps only each key's top name and its summed count) and
    ``coach/evidence.py``'s ``_build_field`` (which keeps every variant,
    plus its own ``TOP_FIELD`` cut and sort).
    """
    where, params = field_window(fmt, since)
    total = _classified_deck_total(conn, where, params)
    rows = conn.execute(
        f"""
        SELECT a.archetype_key AS key, a.archetype_name AS name, COUNT(*) AS n
          FROM meta_deck_archetype a JOIN meta_event e ON e.event_id = a.event_id
         WHERE {where}
         GROUP BY a.archetype_key, a.archetype_name
        """,
        params,
    ).fetchall()
    by_key: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for row in rows:
        by_key[row["key"]].append((row["name"], row["n"]))
    return {
        key: tuple(sorted(name_counts, key=lambda nc: (-nc[1], nc[0])))
        for key, name_counts in by_key.items()
    }, total


def _shares_for_window(
    conn: sqlite3.Connection, fmt: str, since: str | None, *, top_n: int = 25
) -> tuple[list[tuple[str, int]], int]:
    """(archetype, deck_count) pairs, and the TRUE total classified deck
    count for the window — the denominator every share divides by, which
    must never be the truncated top_n sum."""
    where, params = field_window(fmt, since)

    total = _classified_deck_total(conn, where, params)

    presence = conn.execute(
        f"""
        SELECT a.archetype_name AS name, COUNT(*) AS n
          FROM meta_deck_archetype a JOIN meta_event e ON e.event_id = a.event_id
         WHERE {where}
         GROUP BY 1 ORDER BY n DESC LIMIT ?
        """,
        (*params, top_n),
    ).fetchall()
    return [(row["name"], row["n"]) for row in presence if row["name"]], total


def _personal_rate_rows(
    conn: sqlite3.Connection, deck_ids: tuple[str, ...]
) -> dict[str, tuple[int, int, int]]:
    """``(matches, wins, losses)`` per opponent archetype name this deck has
    actually faced — one grouped query, keyed on ``v_match_opponent.
    archetype_name`` (the classifier's own verdict, the same vocabulary
    ``structural_change``'s dict is keyed on). ``personal_rate`` below is the
    single-archetype read of this same result, for a caller that only wants
    one number (``brief/narrative.py``) rather than every archetype this
    deck has played against.
    """
    if not deck_ids:
        return {}
    rows = conn.execute(
        f"""
        SELECT v.archetype_name AS name, COUNT(*) AS matches,
               SUM(CASE WHEN m.result = 'win' THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) AS losses
          FROM matches m JOIN v_match_opponent v ON v.match_id = m.match_id
          JOIN v_match_deck md ON md.match_id = m.match_id
         WHERE md.deck_id IN ({','.join('?' for _ in deck_ids)})
           AND v.archetype_name IS NOT NULL AND m.result IN ('win', 'loss')
         GROUP BY 1
        """,
        deck_ids,
    ).fetchall()
    return {row["name"]: (row["matches"], row["wins"] or 0, row["losses"] or 0) for row in rows}


def archetype_key_by_name(conn: sqlite3.Connection) -> dict[str, str]:
    """The corpus display name -> ``archetype_key`` lookup the guide prompt
    and ``brief/from_guide.py`` share, so a matchup plan named in one is
    filed under the same key by the other.

    A name is not unique to a key: the corpus labels 290 decks "Dimir
    Midrange" under one key and a handful under two others. Each name maps
    to the key with the most decks behind it (ties by key), never whichever
    row a ``SELECT DISTINCT`` happened to return last — which is what this
    replaced, and it had been resolving the field's #3 archetype to a key too
    thin for a consensus, dropping it from every guide prompt.
    """
    best: dict[str, tuple[int, str]] = {}
    for row in conn.execute(
        """
        SELECT archetype_name AS name, archetype_key AS key, COUNT(*) AS n
          FROM meta_deck_archetype
         WHERE archetype_name IS NOT NULL AND archetype_key IS NOT NULL
         GROUP BY 1, 2
        """
    ):
        current = best.get(row["name"])
        if current is None or (-row["n"], row["key"]) < (-current[0], current[1]):
            best[row["name"]] = (row["n"], row["key"])
    return {name: key for name, (_, key) in best.items()}


def faced_archetypes(
    conn: sqlite3.Connection, deck_ids: tuple[str, ...], *, since: str | None = None
) -> dict[str, tuple[str | None, int]]:
    """``archetype_key -> (archetype_name, times_faced)`` for every archetype
    this deck has actually played against — win/loss decisions only, and
    only matches started on or after ``since`` when one is given (``None`` is
    full history). The one definition of "faced" shared by the guide's
    most-faced matchup list (``guide/narrative.py``, windowed) and brief
    coverage (``brief/coverage.py``, full history).

    Grouped on ``v_match_opponent``'s raw ``archetype_key``, never its display
    name, so a row needs no further lookup to know which consensus or brief
    it means. That column is the classifier's own verdict, never a manual
    override's: a match labelled only through ``opponent_deck_override`` has
    no classifier row and is absent here, the same line ``build_field``'s
    ``personal_rates`` draws below.
    """
    if not deck_ids:
        return {}
    clauses = [
        f"md.deck_id IN ({','.join('?' for _ in deck_ids)})",
        "v.archetype_key IS NOT NULL",
        "m.result IN ('win', 'loss')",
    ]
    params: list = list(deck_ids)
    if since is not None:
        clauses.append("m.started_at >= ?")
        params.append(since)
    rows = conn.execute(
        f"""
        SELECT v.archetype_key AS key, v.archetype_name AS name, COUNT(*) AS n
          FROM matches m JOIN v_match_opponent v ON v.match_id = m.match_id
          JOIN v_match_deck md ON md.match_id = m.match_id
         WHERE {' AND '.join(clauses)}
         GROUP BY 1, 2
        """,
        params,
    ).fetchall()
    # Summed per key, labelled with its most common name: a definitions
    # update can rename a key between matches, and one row per (key, name)
    # would otherwise keep whichever partial count came last.
    counts: dict[str, int] = {}
    best_name: dict[str, tuple[int, str | None]] = {}
    for row in rows:
        counts[row["key"]] = counts.get(row["key"], 0) + row["n"]
        if row["n"] > best_name.get(row["key"], (-1, None))[0]:
            best_name[row["key"]] = (row["n"], row["name"])
    return {key: (best_name[key][1], n) for key, n in counts.items()}


def personal_rate(
    conn: sqlite3.Connection, deck_ids: tuple[str, ...], archetype_name: str
) -> PersonalRate | None:
    """This deck's own record against one opponent archetype, by the
    classifier's own display name. ``None`` when the pairing has never
    happened — a real gap, not a zero. Has no reset context of its own, so
    ``carryable`` is always ``True`` here; ``build_field`` is the caller that
    knows about a reset and overrides it after the fact.
    """
    data = _personal_rate_rows(conn, deck_ids).get(archetype_name)
    if data is None:
        return None
    matches, wins, losses = data
    return PersonalRate(
        archetype=archetype_name, matches=matches, wins=wins, losses=losses, carryable=True,
    )


def build_field(
    conn: sqlite3.Connection,
    identity: DeckIdentity,
    *,
    reset: FormatReset | None,
    fmt: str | None = None,
    top_n: int = 25,
) -> FieldEvidence:
    """The field of ``fmt``, the deck's format; omitted, it is read from
    ``identity`` (``guide/deck.py``'s ``identity_format``, D15). A deck with
    no format has no field to read: the evidence comes back empty, with
    ``fmt`` ``None``, rather than borrowing another format's field.
    """
    if fmt is None:
        fmt = identity_format(conn, identity)
    fetched = conn.execute("SELECT fetched_at FROM meta_fetch LIMIT 1").fetchone()
    corpus_fetched_at = fetched["fetched_at"] if fetched else None
    if fmt is None:
        return FieldEvidence(
            fmt=None, window_start=None, classified_decks=0, shares=(), changes={},
            personal_rates=(), own_performance=None,
            corpus_fetched_at=corpus_fetched_at, corpus_latest_event=None,
        )

    since = None
    if reset is not None:
        since = window_start(reset)

    post, classified_decks = _shares_for_window(conn, fmt, since, top_n=top_n)
    pre_shares: dict[str, float] = {}
    if reset is not None:
        # decks through the reset date itself count as "before" — same
        # inclusive boundary guide.window.structural_change uses, since the
        # reset date is the LAST day the old list was actually played.
        pre_rows = conn.execute(
            """
            SELECT a.archetype_name AS name, COUNT(*) AS n
              FROM meta_deck_archetype a JOIN meta_event e ON e.event_id = a.event_id
             WHERE e.format = ? AND e.event_date <= ?
             GROUP BY 1
            """,
            (fmt, reset.date),
        ).fetchall()
        pre_total_scoped = conn.execute(
            """
            SELECT COUNT(*) FROM meta_deck_archetype a JOIN meta_event e ON e.event_id = a.event_id
             WHERE e.format = ? AND e.event_date <= ? AND a.archetype_name IS NOT NULL
            """,
            (fmt, reset.date),
        ).fetchone()[0]
        if pre_total_scoped:
            pre_shares = {
                row["name"]: row["n"] / pre_total_scoped for row in pre_rows if row["name"]
            }

    changes = structural_change(conn, reset, fmt) if reset is not None else {}

    shares = []
    for name, n in post:
        share = n / classified_decks if classified_decks else 0.0
        before = pre_shares.get(name)
        shares.append(ArchetypeShare(
            archetype=name, decks=n, share=share, share_before_reset=before,
            movement=(share - before) if before is not None else None,
        ))

    # Personal rate per opponent archetype, scoped to this deck's own
    # matches. Grouped on v_match_opponent.archetype_name — the classifier's
    # own verdict — rather than the label a manual override may carry,
    # because structural_change's dict is keyed on the same corpus
    # archetype_name vocabulary; a manually-labelled match with no matching
    # classifier verdict is simply absent from this breakdown, same as an
    # unclassified one.
    personal_rates = tuple(
        PersonalRate(
            archetype=name, matches=matches, wins=wins, losses=losses,
            carryable=changes.get(name).carryable if name in changes else True,
        )
        for name, (matches, wins, losses) in _personal_rate_rows(conn, identity.deck_ids).items()
    )

    # the deck's own archetype's corpus performance in the window
    own_performance = None
    verdict_key = None
    if identity.current_cards:
        current_deck_id = None
        for row in conn.execute(
            f"""
            SELECT md.deck_id FROM matches m
              JOIN v_match_deck md ON md.match_id = m.match_id
              JOIN decks d ON d.deck_id = md.deck_id
             WHERE md.deck_id IN ({','.join('?' for _ in identity.deck_ids)})
             GROUP BY md.deck_id ORDER BY MAX(m.started_at) DESC LIMIT 1
            """,
            identity.deck_ids,
        ):
            current_deck_id = row["deck_id"]
        if current_deck_id is not None:
            verdict, _ = _classify_own_deck(conn, current_deck_id, None, fmt=fmt)
            verdict_key = verdict.key if verdict else None

    if verdict_key is not None:
        field_clause, field_params = field_window(fmt, since)
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS decks, SUM(d.wins) AS w, SUM(d.losses) AS l
              FROM meta_deck_archetype a
              JOIN meta_deck d ON d.event_id = a.event_id AND d.deck_ord = a.deck_ord
              JOIN meta_event e ON e.event_id = a.event_id
             WHERE a.archetype_key = ? AND {field_clause}
            """,
            [verdict_key, *field_params],
        ).fetchone()
        if row and row["decks"]:
            w, losses = row["w"] or 0, row["l"] or 0
            own_performance = DeckPerformance(
                decks=row["decks"], wins=w, losses=losses,
                win_rate=round(w / (w + losses), 3) if (w + losses) else None,
            )

    # duplicate_of IS NULL: a republished twin (metagame/dedup.py) can carry
    # a later event_date than its own survivor, which would otherwise move
    # "latest" without the corpus actually having anything newer in it. The
    # format's own latest event: another format's newer event says nothing
    # about how current this field is.
    latest = conn.execute(
        "SELECT MAX(event_date) FROM meta_event WHERE duplicate_of IS NULL AND format = ?",
        (fmt,),
    ).fetchone()[0]

    return FieldEvidence(
        fmt=fmt,
        window_start=since,
        classified_decks=classified_decks,
        shares=tuple(shares),
        changes=changes,
        personal_rates=personal_rates,
        own_performance=own_performance,
        corpus_fetched_at=corpus_fetched_at,
        corpus_latest_event=latest,
    )
