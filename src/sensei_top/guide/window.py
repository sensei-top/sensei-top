"""Format resets, detected from the tournament corpus itself — no
hand-maintained ban date.

Replaces a hand-kept ban date and banned-card list with a real computation:
a card's ``card_legality`` row for the format (``migrations/053``,
from Scryfall's own ``legalities``) tells us it is banned; the
corpus tells us *when* it stopped being played. Pooling data across an
undetected reset was an earlier hand-written guide's worst bug — it named
two top decks that no longer existed. This module is what makes that mistake
structurally impossible rather than merely documented.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sensei_top.i18n import _

CHANGED_THRESHOLD = 0.30
MIN_PRE_RESET_DECKS = 15
MIN_DECKS_FOR_LAST_APPEARANCE = 2
CLUSTER_WINDOW_DAYS = 5


@dataclass(frozen=True, slots=True)
class FormatReset:
    date: str  # ISO date; the analysis window starts the day after this
    cards: tuple[str, ...]
    detected_from: str


def window_start(reset: FormatReset) -> str:
    """The first day the analysis window may draw from: the day after
    ``reset.date``, since the reset day itself is still pre-reset data. The
    one place this +1-day arithmetic lives; every window computed from a
    detected reset goes through here."""
    return (date.fromisoformat(reset.date) + timedelta(days=1)).isoformat()


@dataclass(frozen=True, slots=True)
class ArchetypeChange:
    archetype: str
    pre_reset_decks: int
    fraction_playing_a_banned_card: float
    banned_cards: tuple[str, ...]
    post_reset_decks: int
    verdict: str  # "intact" | "changed" | "gone"

    @property
    def carryable(self) -> bool:
        return self.verdict == "intact"


def deck_cards(row: sqlite3.Row, field: str, canon: Callable[[str], str] = str) -> Counter:
    """Canonicalised {card: copies} for one corpus decklist. Corpus JSON is
    ``[{"count": int, "name": str}, ...]``; tolerate bare strings too."""
    counts: Counter = Counter()
    try:
        entries = json.loads(row[field] or "[]")
    except json.JSONDecodeError:
        return counts
    for entry in entries:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("card")
            qty = entry.get("count") or entry.get("quantity") or 1
            if name:
                counts[canon(name)] += int(qty)
        elif isinstance(entry, str):
            counts[canon(entry)] += 1
    return counts


def _date_only(value: str | None) -> str | None:
    """meta_event.event_date is sometimes a bare date, sometimes an ISO
    timestamp — normalise to the date component for comparison."""
    if not value:
        return None
    return value[:10]


def legality_known(conn: sqlite3.Connection, fmt: str = "Standard") -> bool:
    """Whether the local card table carries Scryfall legality for ``fmt`` at all.

    ``format_resets`` returns an empty list for two very different reasons:
    the format genuinely has no banned card, or nothing on this machine
    knows what a banned card *is*. The installed-client card database
    carries no legality column (``cards.read_arena_cards``), so a machine
    that has only ever run ``sensei-top cards`` — and not
    ``cards --scryfall`` — has 'banned' for nothing, and every reset goes
    undetected no matter how plainly the corpus shows one.

    The first case is a fact about the format; the second is a hole in the
    local data. Reporting them the same way is what let a real guide pool a
    Standard corpus across a ban and open with a 20.7% share for an
    archetype that had already fallen out of the field. Callers must say
    which one they are in.
    """
    return conn.execute(
        "SELECT 1 FROM card_legality WHERE format = ? LIMIT 1", (fmt,)
    ).fetchone() is not None


def format_resets(conn: sqlite3.Connection, fmt: str = "Standard") -> list[FormatReset]:
    """Every detected reset for ``fmt``, newest first. An empty list is a
    valid, common answer — no banned card, no reset window found, or no
    legality data to judge by at all (``legality_known`` separates that last
    case out, and callers must not report it as "no reset")."""
    banned_names = {
        row["name"] for row in conn.execute(
            """
            SELECT DISTINCT c.name
              FROM card_legality cl JOIN cards c ON c.grp_id = cl.grp_id
             WHERE cl.format = ? AND cl.legality = 'banned'
            """,
            (fmt,),
        )
    }
    if not banned_names:
        return []

    # One pass over the whole corpus rather than one pass per banned card —
    # Scryfall's bulk export carries every card ever banned in Standard's
    # history, most of them irrelevant to this format's own corpus, so
    # scanning per-card here would cost O(banned cards x corpus size)
    # instead of O(corpus size).
    per_card_date: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in conn.execute(
        """
        SELECT e.event_date, d.mainboard_json, d.sideboard_json
          FROM meta_deck d JOIN meta_event e ON e.event_id = d.event_id
         WHERE e.format = ?
        """,
        (fmt,),
    ):
        d = _date_only(row["event_date"])
        if not d:
            continue
        names = set(deck_cards(row, "mainboard_json")) | set(deck_cards(row, "sideboard_json"))
        for name in names & banned_names:
            per_card_date[name][d] += 1

    # For each banned card: the last event_date on which it appeared in
    # enough decks to be real evidence, not a data error.
    last_appearance: dict[str, str] = {}
    for name, per_date in per_card_date.items():
        qualifying = [d for d, n in per_date.items() if n >= MIN_DECKS_FOR_LAST_APPEARANCE]
        if qualifying:
            last_appearance[name] = max(qualifying)

    if not last_appearance:
        return []

    # Cluster cards whose last-appearance dates fall within CLUSTER_WINDOW_DAYS
    # of each other — bans ship together.
    ordered = sorted(last_appearance.items(), key=lambda kv: kv[1])
    clusters: list[list[tuple[str, str]]] = []
    for name, last_date in ordered:
        if clusters:
            cluster_max = max(date.fromisoformat(d) for _name, d in clusters[-1])
            if date.fromisoformat(last_date) - cluster_max <= timedelta(days=CLUSTER_WINDOW_DAYS):
                clusters[-1].append((name, last_date))
                continue
        clusters.append([(name, last_date)])

    resets = []
    for cluster in clusters:
        cluster_date = max(d for _name, d in cluster)
        cards = tuple(sorted(name for name, _date in cluster))
        resets.append(FormatReset(
            date=cluster_date,
            cards=cards,
            # The card names are a plain list (", "), and the format a code:
            # only the words around them are translated.
            detected_from=_(
                "{cards} last appeared in the {fmt} corpus on {date}"
            ).format(cards=", ".join(cards), fmt=fmt, date=cluster_date),
        ))
    resets.sort(key=lambda r: r.date, reverse=True)
    return resets


def consensus_window_resolver(
    conn: sqlite3.Connection, known: dict[str, str | None] | None = None
) -> Callable[[str], str | None]:
    """The one per-format window resolver outside the API routes: a format
    maps to the ``window_start`` of its latest reset, or ``None`` when none is
    detected. It is the resolver ``review/leaks.py::find_leaks`` takes as
    ``consensus_window``. Each format is resolved once per resolver, because
    ``format_resets`` scans the whole corpus. ``known`` seeds formats whose
    window the caller has already computed (a copy is taken)."""
    windows: dict[str, str | None] = dict(known or {})

    def consensus_window(fmt: str) -> str | None:
        if fmt not in windows:
            found = format_resets(conn, fmt)
            windows[fmt] = window_start(found[0]) if found else None
        return windows[fmt]

    return consensus_window


def structural_change(
    conn: sqlite3.Connection, reset: FormatReset, fmt: str = "Standard"
) -> dict[str, ArchetypeChange]:
    """Per archetype: did its pre-reset lists rely on a card the reset
    banned, and does it still exist post-reset? This is what decides
    whether a pre-reset matchup rate may be carried forward."""
    # reset.date is the LAST day the banned card was actually seen played, so
    # "pre-reset" includes that day itself — the day after is where the new
    # list starts (mirrors the post-reset query's own +1 day below).
    pre = list(conn.execute(
        """
        SELECT a.archetype_name AS arch, d.mainboard_json, d.sideboard_json
          FROM meta_deck d
          JOIN meta_deck_archetype a ON a.event_id = d.event_id AND a.deck_ord = d.deck_ord
          JOIN meta_event e ON e.event_id = d.event_id
         WHERE e.format = ? AND e.event_date <= ?
        """,
        (fmt, reset.date),
    ))
    banned = set(reset.cards)
    total: Counter = Counter()
    hit: Counter = Counter()
    which: dict[str, Counter] = defaultdict(Counter)
    for row in pre:
        if not row["arch"]:
            continue
        total[row["arch"]] += 1
        names = set(deck_cards(row, "mainboard_json")) | set(deck_cards(row, "sideboard_json"))
        overlap = names & banned
        if overlap:
            hit[row["arch"]] += 1
            which[row["arch"]].update(overlap)

    post = {
        row["archetype_name"]: row["n"]
        for row in conn.execute(
            """
            SELECT a.archetype_name, COUNT(*) AS n
              FROM meta_deck_archetype a JOIN meta_event e ON e.event_id = a.event_id
             WHERE e.format = ? AND e.event_date >= ?
             GROUP BY 1
            """,
            (fmt, window_start(reset)),
        )
    }

    out: dict[str, ArchetypeChange] = {}
    for arch, n in total.items():
        if n < MIN_PRE_RESET_DECKS:
            continue
        fraction = hit[arch] / n
        post_decks = post.get(arch, 0)
        if post_decks == 0:
            verdict = "gone"
        elif fraction >= CHANGED_THRESHOLD:
            verdict = "changed"
        else:
            verdict = "intact"
        out[arch] = ArchetypeChange(
            archetype=arch,
            pre_reset_decks=n,
            fraction_playing_a_banned_card=round(fraction, 3),
            banned_cards=tuple(sorted(which[arch])),
            post_reset_decks=post_decks,
            verdict=verdict,
        )
    return out
