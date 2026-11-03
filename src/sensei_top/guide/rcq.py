"""The RCQ guide: one tournament-day document for the exact 75 a player is
about to register at a paper Regional Championship Qualifier.

Built on the deck guide rather than beside it. ``build_rcq`` takes the deck
identity's whole ``DeckGuide`` (its own play, leaks and field, unchanged:
every match played with the identity, never dropped by the reset window),
then swaps in the pasted 75 wherever a list is compared — the list diff,
plan validation, and the oracle text the prompt carries. To that it adds
what a tournament day needs and a ladder guide does not: the field over the
last ``RECENT_SHARE_DAYS`` days, every event of the last
``RECENT_EVENT_DAYS``, how fresh each corpus source is, and the archetypes
the player expects at the store. See docs/guide.md, "The RCQ guide".

Expected archetypes are a nudge, never evidence: each one gets a prompt
section and must get a plan, but none displaces a top-share section.

This module is evidence only and never makes a call; the prompt built on it
and the answer's parser are ``ai/guide/rcq_prompt.py``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from sensei_top.archetypes.classify import (
    Verdict,
    card_colors_by_name,
    choose,
    load_definitions,
    seen_forms,
)
from sensei_top.guide.bundle import DeckGuide, build_deck_guide
from sensei_top.guide.decklist import ParsedList, ResolvedList, parse_decklist, resolve_names
from sensei_top.guide.field import (
    ArchetypeShare,
    PersonalRate,
    _shares_for_window,
    field_by_key,
)
from sensei_top.guide.list_diff import ListDiff, build_list_diff
from sensei_top.i18n import N_, _
from sensei_top.metagame.classify_meta import _colors_of
from sensei_top.metagame.source import placement_of

__all__ = [
    "ExpectedArchetype",
    "RcqEvidence",
    "RecentEvent",
    "SourceFreshness",
    "build_rcq",
    "classify_pasted",
    "top8_name",
    "unclassified_reason",
]

RECENT_SHARE_DAYS = 14
RECENT_EVENT_DAYS = 7
TOP_PLACEMENTS = 8

# A top-8 deck the corpus never classified. A sentinel in
# ``RecentEvent.top8``, beside archetype names (never translated:
# docs/i18n.md, "What is never translated"), so it stays this English text
# there; ``top8_name`` writes it in the reader's language.
UNCLASSIFIED = N_("(unclassified)")

# Why the pasted 75 has no archetype to compare against
# (``RcqEvidence.own_unclassified``): codes, written as a sentence by
# ``unclassified_reason`` in the language of whoever reads it.
UNKNOWN_PICK = "unknown_pick"
FORMAT_UNKNOWN = "format_unknown"
NO_FIT = "no_fit"


@dataclass(frozen=True, slots=True)
class RecentEvent:
    date: str | None
    name: str
    source: str
    tier: str
    decks: int
    top8: tuple[str, ...]  # archetype names by placement; () when none recorded


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    source: str
    newest_event: str | None
    fetched_at: str | None


@dataclass(frozen=True, slots=True)
class ExpectedArchetype:
    key: str
    name: str
    share: float | None
    record: PersonalRate | None  # this deck's own record against it; None if never faced


@dataclass(frozen=True, slots=True)
class _PickedArchetype:
    """The player's own pick of their archetype (``own=``): the two fields
    ``build_list_diff`` reads from a ``Verdict``, and nothing it would have
    to invent."""
    key: str
    name: str


def unclassified_reason(code: str | None, own: str | None) -> str | None:
    """The sentence for an ``RcqEvidence.own_unclassified`` code, in the
    current language; ``own`` is the player's pick, which ``UNKNOWN_PICK``
    names. ``None`` for no code."""
    if code == UNKNOWN_PICK:
        return _("No archetype with key {key} is in the tournament corpus.").format(
            key=repr(own),
        )
    if code == FORMAT_UNKNOWN:
        return _(
            "The deck's format is unknown, so this 75 was not classified: "
            "archetype definitions are kept per format."
        )
    if code == NO_FIT:
        return _(
            "The archetype definitions name no archetype this 75 clearly fits; "
            "pick one to compare it against."
        )
    return None


def top8_name(name: str) -> str:
    """A ``RecentEvent.top8`` entry as the reader sees it: an archetype
    name as it is, ``UNCLASSIFIED`` in the current language."""
    return _(UNCLASSIFIED) if name == UNCLASSIFIED else name


@dataclass(frozen=True, slots=True)
class RcqEvidence:
    """Built in one language and read in another: the RCQ preview builds it
    in English for its prompt and hands the page its fields. So the text the
    page shows is kept as data here (``own_unclassified``, ``parsed``'s
    source text, ``list_diff.duplicates``, the ``UNCLASSIFIED`` sentinel) and
    written in whatever language is current when it is read."""

    guide: DeckGuide
    parsed: ParsedList
    resolved: ResolvedList
    own_verdict_key: str | None
    own_verdict_name: str | None
    own_unclassified: str | None  # UNKNOWN_PICK | FORMAT_UNKNOWN | NO_FIT
    own_pick: str | None  # build_rcq's own=
    list_diff: ListDiff | None
    recent_shares: tuple[ArchetypeShare, ...]
    recent_shares_since: str
    recent_classified_decks: int
    recent_events: tuple[RecentEvent, ...]
    recent_events_since: str
    freshness: tuple[SourceFreshness, ...]
    expected: tuple[ExpectedArchetype, ...]
    unknown_expected: tuple[str, ...]  # expected keys no corpus deck carries; dropped
    decklist_text: str
    expected_keys: tuple[str, ...]

    @property
    def own_unclassified_reason(self) -> str | None:
        """Why the pasted 75 has no archetype, in the current language."""
        return unclassified_reason(self.own_unclassified, self.own_pick)



def classify_pasted(
    conn: sqlite3.Connection, resolved: ResolvedList, parsed: ParsedList, *,
    fmt: str | None,
) -> Verdict | None:
    """The pasted 75's archetype, by the ``complete=True`` path
    ``metagame/classify_meta.py`` runs over a corpus decklist: a pasted list
    is a whole list, so a card's absence is real evidence. Names come from
    the paste itself, as a corpus list's do, so ``resolved`` is not needed
    to classify. ``None`` when nothing leads clearly, never a guess."""
    definitions = load_definitions(conn)
    if fmt is None or fmt not in definitions or not parsed.main:
        return None
    main_names = list(parsed.main)
    side_names = list(parsed.side)
    colors_by_name = card_colors_by_name(conn)
    return choose(
        definitions[fmt]["archetype"], definitions[fmt]["fallback"], seen_forms(main_names),
        _colors_of(main_names, colors_by_name), colors_by_name, cards_seen=len(main_names),
        complete=True, sideboard_seen=seen_forms(side_names),
    )


def _corpus_name_for_key(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        """
        SELECT archetype_name AS name, COUNT(*) AS n FROM meta_deck_archetype
         WHERE archetype_key = ? GROUP BY 1 ORDER BY n DESC, name LIMIT 1
        """,
        (key,),
    ).fetchone()
    return row["name"] if row else None


def _window_since(days: int, today: date, reset_since: str | None) -> str:
    """``days`` back from ``today``, never across the guide's reset: a
    recent window still must not pool decks from before a ban."""
    since = (today - timedelta(days=days)).isoformat()
    if reset_since is not None and reset_since > since:
        return reset_since
    return since


def _recent_events(conn: sqlite3.Connection, fmt: str, since: str) -> tuple[RecentEvent, ...]:
    events = conn.execute(
        """
        SELECT e.event_id, e.event_date, e.name, e.source, e.tier,
               (SELECT COUNT(*) FROM meta_deck d WHERE d.event_id = e.event_id) AS decks
          FROM meta_event e
         WHERE e.duplicate_of IS NULL AND e.format = ? AND e.event_date >= ?
         ORDER BY e.event_date DESC, e.name, e.event_id
        """,
        (fmt, since),
    ).fetchall()
    out = []
    for event in events:
        placed: list[tuple[int, int, str]] = []
        for row in conn.execute(
            """
            SELECT d.deck_ord, d.result, a.archetype_name AS name FROM meta_deck d
              LEFT JOIN meta_deck_archetype a
                ON a.event_id = d.event_id AND a.deck_ord = d.deck_ord
             WHERE d.event_id = ?
            """,
            (event["event_id"],),
        ):
            # Decks[].Result is a placement string ("1st Place") wherever an
            # event has standings (docs/metagame.md); a league's "5-0" is not.
            place = placement_of(row["result"])
            if place is not None and place <= TOP_PLACEMENTS:
                placed.append((place, row["deck_ord"], row["name"] or UNCLASSIFIED))
        out.append(RecentEvent(
            date=event["event_date"], name=event["name"], source=event["source"],
            tier=event["tier"], decks=event["decks"],
            top8=tuple(name for _place, _ord, name in sorted(placed)),
        ))
    return tuple(out)


def _freshness(conn: sqlite3.Connection) -> tuple[SourceFreshness, ...]:
    """Newest event per ``meta_event.source`` (republished twins excluded,
    as ``build_field``'s own "latest" does) and ``fetched_at`` per
    ``meta_fetch_source.source``. The two tables name sources in different
    vocabularies (an event's ``"Topdeck"``, its fetch's ``"topdeck"``); a
    name the two share case-insensitively is one row, any other stays its
    own row with the half it has."""
    rows: dict[str, list] = {}
    for row in conn.execute(
        "SELECT source, MAX(event_date) AS newest FROM meta_event "
        "WHERE duplicate_of IS NULL GROUP BY source"
    ):
        rows[row["source"].casefold()] = [row["source"], row["newest"], None]
    for row in conn.execute("SELECT source, fetched_at FROM meta_fetch_source"):
        entry = rows.setdefault(row["source"].casefold(), [row["source"], None, None])
        entry[2] = row["fetched_at"]
    return tuple(
        SourceFreshness(source=s, newest_event=newest, fetched_at=fetched)
        for s, newest, fetched in sorted(rows.values(), key=lambda r: r[0].casefold())
    )


def _expected(
    conn: sqlite3.Connection, guide: DeckGuide, keys: tuple[str, ...]
) -> tuple[tuple[ExpectedArchetype, ...], tuple[str, ...]]:
    """Each expected key with its label, share and this deck's record, and
    separately every key no corpus deck carries: a key with no name is
    dropped, never labelled with itself (rule 4)."""
    if guide.field.fmt is None:
        by_key, total = {}, 0
    else:
        by_key, total = field_by_key(conn, guide.field.fmt, guide.field.window_start)
    rates = {r.archetype: r for r in guide.field.personal_rates}
    out = []
    unknown = []
    for key in keys:
        names = by_key.get(key)
        name = names[0][0] if names else _corpus_name_for_key(conn, key)
        if name is None:
            unknown.append(key)
            continue
        share = sum(n for _, n in names) / total if names and total else None
        out.append(ExpectedArchetype(key=key, name=name, share=share, record=rates.get(name)))
    return tuple(out), tuple(unknown)


def build_rcq(
    conn: sqlite3.Connection,
    key: str,
    text: str,
    expected: list[str],
    own: str | None = None,
    *,
    report_cache: dict | None = None,
    today: date | None = None,
) -> RcqEvidence | None:
    """The RCQ guide's evidence for deck identity ``key`` and the pasted
    decklist ``text``. ``None`` for an unknown deck key.

    ``expected`` is a list of corpus archetype keys; ``own`` is the player's
    pick of their own archetype key, used instead of the classifier.
    ``today`` anchors the recent windows (the local date when omitted).
    """
    guide = build_deck_guide(conn, key, report_cache=report_cache)
    if guide is None:
        return None
    if today is None:
        today = date.today()

    parsed = parse_decklist(text)
    resolved = resolve_names(conn, parsed)

    verdict = None
    unclassified = None
    if own is not None:
        name = _corpus_name_for_key(conn, own)
        if name is None:
            unclassified = UNKNOWN_PICK
        else:
            verdict = _PickedArchetype(key=own, name=name)
    else:
        verdict = classify_pasted(conn, resolved, parsed, fmt=guide.field.fmt)
        if guide.field.fmt is None:
            unclassified = FORMAT_UNKNOWN
        elif verdict is None:
            unclassified = NO_FIT

    diff = None
    if verdict is not None and guide.field.fmt is not None:
        diff = build_list_diff(
            conn, guide.provenance.deck, reset=guide.provenance.reset,
            cards={"maindeck": resolved.main_grp_ids, "sideboard": resolved.side_grp_ids},
            verdict=verdict, fmt=guide.field.fmt,
        )

    reset_since = guide.provenance.window_start
    shares_since = _window_since(RECENT_SHARE_DAYS, today, reset_since)
    if guide.field.fmt is None:
        pairs, recent_total = (), 0
    else:
        pairs, recent_total = _shares_for_window(conn, guide.field.fmt, shares_since)
    recent_shares = tuple(
        ArchetypeShare(
            archetype=name, decks=n, share=n / recent_total if recent_total else 0.0,
            share_before_reset=None, movement=None,
        )
        for name, n in pairs
    )
    events_since = _window_since(RECENT_EVENT_DAYS, today, reset_since)

    expected_keys = tuple(dict.fromkeys(expected))
    expected_rows, unknown_expected = _expected(conn, guide, expected_keys)
    return RcqEvidence(
        guide=guide,
        parsed=parsed,
        resolved=resolved,
        own_verdict_key=verdict.key if verdict is not None else None,
        own_verdict_name=verdict.name if verdict is not None else None,
        own_unclassified=unclassified,
        own_pick=own,
        list_diff=diff,
        recent_shares=recent_shares,
        recent_shares_since=shares_since,
        recent_classified_decks=recent_total,
        recent_events=(
            _recent_events(conn, guide.field.fmt, events_since)
            if guide.field.fmt is not None else ()
        ),
        recent_events_since=events_since,
        freshness=_freshness(conn),
        expected=expected_rows,
        unknown_expected=unknown_expected,
        decklist_text=text,
        expected_keys=expected_keys,
    )
