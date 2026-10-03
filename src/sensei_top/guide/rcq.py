"""The RCQ guide: one tournament-day document for the exact 75 a player is
about to register at a paper Regional Championship Qualifier.

Built on the deck guide rather than beside it. ``build_rcq`` takes the deck
identity's whole ``DeckGuide`` (its own play, leaks and field, unchanged:
every match played with the identity, never dropped by the reset window),
then swaps in the pasted 75 wherever a list is compared — the list diff,
plan validation, and the oracle text the prompt carries. To that it adds
what a tournament day needs and a ladder guide does not: the field over the
last 14 days, every event of the last 7, how fresh each corpus source is,
and the archetypes the player expects at the store.

Expected archetypes are a nudge, never evidence: each one gets a prompt
section and must get a plan, but none displaces a top-share section.

Like ``guide/narrative.py``, this module never makes a call. The prompt
(``rcq_prompt``) and the answer's parser (``rcq_from_json``) are shared by
the opt-in Claude call and a hand import.
"""

from __future__ import annotations

import dataclasses
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from sensei_top.archetypes.classify import (
    Verdict,
    _card_colors_by_name,
    _load_definitions,
    _seen_forms,
    choose,
    normalize,
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
from sensei_top.guide.markdown import render
from sensei_top.guide.narrative import (
    BoardCard,
    _opponent_sections,
    _oracle_text_block,
    _parse_json_object,
    _wrap_json_prompt,
)
from sensei_top.guide.plans import PlanProblem, validate_plans
from sensei_top.metagame.classify_meta import _colors_of
from sensei_top.review.narrative import NarrativeError

__all__ = [
    "RCQ_SYSTEM_PROMPT",
    "ExpectedArchetype",
    "FlexNote",
    "NarrativeError",
    "RcqEvidence",
    "RcqMatchup",
    "RcqNarrative",
    "RecentEvent",
    "SourceFreshness",
    "build_rcq",
    "classify_pasted",
    "rcq_from_json",
    "rcq_prompt",
]

RECENT_SHARE_DAYS = 14
RECENT_EVENT_DAYS = 7
TOP_PLACEMENTS = 8

RCQ_SYSTEM_PROMPT = (
    "You are preparing a Magic: The Gathering player for a paper Regional "
    "Championship Qualifier today. They have registered the exact 75 given below "
    "and cannot change it. You are given their own match history with this deck, "
    "the tournament field — its shares after any detected format reset, its "
    "shares over the last 14 days, and every event of the last 7 days — the "
    "consensus lists of the archetypes they may face, and card oracle text. "
    "Write a tournament-day guide. Explain the deck's game plan and what to "
    "mulligan toward, from the card text and their own evidence (mark reasoning "
    "as (reasoned)). Describe the field they should expect, weighting recent "
    "events most, and say plainly where the field evidence is thin. For every "
    "opponent archetype given a section, write sideboard advice under the "
    "archetype's exact heading name: what matters in the matchup, what changes "
    "on the play versus the draw, and a concrete IN/OUT plan using only cards in "
    "the registered 75, at exact counts, balanced. Name the flex slots of the 75 "
    "and which matchups they are for. A pre-reset matchup rate marked void must "
    "never be treated as current. Never invent a card, a number, an event, or a "
    "sample size not in the data given to you."
)

_EXPECTED_HEAD = (
    "Expected at the store (the player's own read of their local field, not evidence): "
)
_EXPECTED_RULE = (
    "Treat this as a prior, not a fact. Every archetype listed here has a "
    "section below and must get a plan. When two sideboard choices are close on "
    "the evidence, prefer the one that is better against these. Do not drop or "
    "weaken a plan for a high-share archetype to make room for them, and say so "
    "when the player's expectation disagrees with the field data."
)

_BOARD_CARDS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"card": {"type": "string"}, "n": {"type": "integer"}},
        "required": ["card", "n"],
    },
}

_RCQ_TOOL = {
    "name": "emit_rcq_guide",
    "description": "Return the written sections of a tournament-day RCQ guide.",
    "input_schema": {
        "type": "object",
        "properties": {
            "game_plan": {
                "type": "string",
                "description": "How the 75 wins and what to mulligan for.",
            },
            "expected_field": {
                "type": "string",
                "description": "The field to expect at the store.",
            },
            "matchups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "archetype": {"type": "string"},
                        "prose": {"type": "string"},
                        "play_draw": {
                            "type": "string",
                            "description": "What changes on the play versus the draw.",
                        },
                        "board_in": _BOARD_CARDS,
                        "board_out": _BOARD_CARDS,
                    },
                    "required": ["archetype", "prose", "play_draw", "board_in", "board_out"],
                },
            },
            "flex_notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "card": {"type": "string"},
                        "role": {"type": "string", "enum": ["core", "flex", "risk"]},
                        "why": {"type": "string"},
                    },
                    "required": ["card", "role", "why"],
                },
            },
            "checklist": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short questions to ask between rounds.",
            },
        },
        "required": ["game_plan", "expected_field", "matchups", "flex_notes", "checklist"],
    },
}

_PLACEMENT = re.compile(r"^\s*(\d+)(?:st|nd|rd|th)\s+place\s*$", re.IGNORECASE)


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


@dataclass(frozen=True, slots=True)
class RcqEvidence:
    guide: DeckGuide
    parsed: ParsedList
    resolved: ResolvedList
    own_verdict_key: str | None
    own_verdict_name: str | None
    own_unclassified_reason: str | None
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


@dataclass(frozen=True, slots=True)
class RcqMatchup:
    archetype: str
    prose: str
    play_draw: str
    board_in: tuple[BoardCard, ...]
    board_out: tuple[BoardCard, ...]


@dataclass(frozen=True, slots=True)
class FlexNote:
    card: str
    role: str  # "core" | "flex" | "risk"
    why: str


@dataclass(frozen=True, slots=True)
class RcqNarrative:
    game_plan: str
    expected_field: str
    matchups: tuple[RcqMatchup, ...]
    flex_notes: tuple[FlexNote, ...]
    checklist: tuple[str, ...]
    problems: tuple[PlanProblem, ...] = ()


def classify_pasted(
    conn: sqlite3.Connection, resolved: ResolvedList, parsed: ParsedList, *,
    fmt: str = "Standard",
) -> Verdict | None:
    """The pasted 75's archetype, by the ``complete=True`` path
    ``metagame/classify_meta.py`` runs over a corpus decklist: a pasted list
    is a whole list, so a card's absence is real evidence. Names come from
    the paste itself, as a corpus list's do, so ``resolved`` is not needed
    to classify. ``None`` when nothing leads clearly, never a guess."""
    definitions = _load_definitions(conn)
    if fmt not in definitions or not parsed.main:
        return None
    main_names = list(parsed.main)
    side_names = list(parsed.side)
    colors_by_name = _card_colors_by_name(conn)
    return choose(
        definitions[fmt]["archetype"], definitions[fmt]["fallback"], _seen_forms(main_names),
        _colors_of(main_names, colors_by_name), colors_by_name, cards_seen=len(main_names),
        complete=True, sideboard_seen=_seen_forms(side_names),
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
            match = _PLACEMENT.match(row["result"] or "")
            if match and int(match[1]) <= TOP_PLACEMENTS:
                placed.append((int(match[1]), row["deck_ord"], row["name"] or "(unclassified)"))
        out.append(RecentEvent(
            date=event["event_date"], name=event["name"], source=event["source"],
            tier=event["tier"], decks=event["decks"],
            top8=tuple(name for _, _, name in sorted(placed)),
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
    reason = None
    if own is not None:
        name = _corpus_name_for_key(conn, own)
        if name is None:
            reason = f"No archetype with key {own!r} is in the tournament corpus."
        else:
            verdict = _PickedArchetype(key=own, name=name)
    else:
        verdict = classify_pasted(conn, resolved, parsed, fmt=guide.field.fmt)
        if verdict is None:
            reason = (
                "The archetype definitions name no archetype this 75 clearly fits; "
                "pick one to compare it against."
            )

    diff = None
    if verdict is not None:
        diff = build_list_diff(
            conn, guide.provenance.deck, reset=guide.provenance.reset,
            cards={"maindeck": resolved.main_grp_ids, "sideboard": resolved.side_grp_ids},
            verdict=verdict,
        )

    reset_since = guide.provenance.window_start
    shares_since = _window_since(RECENT_SHARE_DAYS, today, reset_since)
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
        own_unclassified_reason=reason,
        list_diff=diff,
        recent_shares=recent_shares,
        recent_shares_since=shares_since,
        recent_classified_decks=recent_total,
        recent_events=_recent_events(conn, guide.field.fmt, events_since),
        recent_events_since=events_since,
        freshness=_freshness(conn),
        expected=expected_rows,
        unknown_expected=unknown_expected,
        decklist_text=text,
        expected_keys=expected_keys,
    )


def _share_text(share: float | None) -> str:
    return f"{share:.1%} of the field" if share is not None else "not in the field's window"


def _counts_block(title: str, counts: Counter) -> list[str]:
    lines = [f"{title} ({sum(counts.values())}):"]
    lines.extend(f"{n} {name}" for name, n in counts.items())
    return lines


def rcq_prompt(evidence: RcqEvidence, *, conn) -> str:
    """The complete text to hand an assistant: the framing, the schema, then
    the evidence — the deck guide's own evidence, with the pasted 75 in
    place of the identity's current list."""
    guide = evidence.guide
    gaps = [g for g in guide.gaps if not g.startswith("Your own deck could not be classified")]
    if evidence.own_unclassified_reason is not None:
        gaps.append(evidence.own_unclassified_reason)
    elif evidence.list_diff is None:
        gaps.append(
            f"Too few winning decklists of {evidence.own_verdict_name} are on file for a "
            f"consensus — the list-vs-consensus comparison is unavailable."
        )
    if evidence.unknown_expected:
        gaps.append(
            "Left out of the expected archetypes, since no tournament deck carries the key: "
            + ", ".join(evidence.unknown_expected) + "."
        )
    if evidence.resolved.unresolved:
        gaps.append(
            "Not found in the card database, so no oracle text is given for: "
            + ", ".join(evidence.resolved.unresolved) + "."
        )
    shown = dataclasses.replace(guide, list_diff=evidence.list_diff, gaps=tuple(gaps))

    deck = guide.provenance.deck
    lines: list[str] = [
        f"Deck: {deck.name or deck.key}",
        "",
        "The registered 75 (this replaces the deck's current list everywhere a list is "
        "compared below):",
        *_counts_block("Maindeck", evidence.parsed.main),
        *_counts_block("Sideboard", evidence.parsed.side),
    ]
    if evidence.parsed.warnings:
        lines.append("Decklist warnings:")
        lines.extend(f"- {w}" for w in evidence.parsed.warnings)
    lines.extend(["", render(shown), "", "Card oracle text for the registered 75:"])
    own_grp_ids = list({*evidence.resolved.main_grp_ids, *evidence.resolved.side_grp_ids})
    lines.append(_oracle_text_block(conn, own_grp_ids))

    lines.append("")
    lines.append(
        f"Field shares over the last {RECENT_SHARE_DAYS} days (events since "
        f"{evidence.recent_shares_since}; {evidence.recent_classified_decks} classified decks):"
    )
    if evidence.recent_shares:
        lines.extend(
            f"- {s.archetype}: {s.decks} decks ({s.share:.1%})" for s in evidence.recent_shares
        )
    else:
        lines.append("- No classified decks in this window.")

    lines.append("")
    lines.append(
        f"Every event of the last {RECENT_EVENT_DAYS} days (since "
        f"{evidence.recent_events_since}), newest first:"
    )
    if evidence.recent_events:
        for e in evidence.recent_events:
            top8 = f"; top 8: {', '.join(e.top8)}" if e.top8 else ""
            lines.append(
                f"- {e.date} {e.name} ({e.source}, tier {e.tier}, {e.decks} decks){top8}"
            )
    else:
        lines.append("- No events in this window.")

    lines.append("")
    lines.append("Corpus freshness, per source:")
    for f in evidence.freshness:
        halves = []
        if f.newest_event is not None:
            halves.append(f"newest event {f.newest_event}")
        if f.fetched_at is not None:
            halves.append(f"fetched {f.fetched_at}")
        lines.append(f"- {f.source}: {', '.join(halves)}")

    if evidence.expected:
        lines.append("")
        lines.append(
            _EXPECTED_HEAD
            + ", ".join(f"{x.name} ({_share_text(x.share)})" for x in evidence.expected)
        )
        lines.append(_EXPECTED_RULE)

    _opponent_sections(
        lines, guide, conn=conn,
        own_name=evidence.own_verdict_name,
        own_key=evidence.own_verdict_key,
        shown_grp_ids=set(own_grp_ids),
        extra=tuple(
            (x.key, f"-- {x.name} (you expect it at the store; {_share_text(x.share)}) --")
            for x in evidence.expected
        ),
        extra_intro=(
            "Consensus staples and oracle text for the archetypes you expect at the store, "
            "not already listed above:"
        ),
    )

    return _wrap_json_prompt(RCQ_SYSTEM_PROMPT, _RCQ_TOOL["input_schema"], "\n".join(lines))


def _canonical_names(parsed: ParsedList) -> dict[str, str]:
    """Every written form of each pasted name (``normalize``) -> the name as
    pasted, so a plan naming a card by its full ``A // B`` name (the oracle
    text block's spelling) is checked against the same pasted entry as its
    front face."""
    lookup: dict[str, str] = {}
    for name in (*parsed.main, *parsed.side):
        for form in normalize(name):
            lookup.setdefault(form, name)
    return lookup


def _as_pasted(card: BoardCard, lookup: dict[str, str]) -> BoardCard:
    for form in sorted(normalize(card.card), key=lambda f: (-len(f), f)):
        if form in lookup:
            return BoardCard(lookup[form], card.n)
    return card


def rcq_from_json(raw: str | dict, evidence: RcqEvidence) -> RcqNarrative:
    """Parse an authored RCQ guide and validate every sideboard plan against
    the **pasted** 75 by name — never the consensus's recommended counts.
    Raises ``NarrativeError`` on anything malformed. A plan the author got
    wrong is surfaced in ``problems``, never repaired."""
    raw = _parse_json_object(raw)
    try:
        matchups = tuple(
            RcqMatchup(
                archetype=m["archetype"],
                prose=m["prose"],
                play_draw=m["play_draw"],
                board_in=tuple(BoardCard(c["card"], c["n"]) for c in m.get("board_in", [])),
                board_out=tuple(BoardCard(c["card"], c["n"]) for c in m.get("board_out", [])),
            )
            for m in raw.get("matchups", [])
        )
        flex_notes = tuple(
            FlexNote(c["card"], c["role"], c["why"]) for c in raw.get("flex_notes", [])
        )
        game_plan = raw["game_plan"]
        expected_field = raw["expected_field"]
        checklist = tuple(raw.get("checklist", []))

        lookup = _canonical_names(evidence.parsed)
        checked = tuple(
            dataclasses.replace(
                m,
                board_in=tuple(_as_pasted(c, lookup) for c in m.board_in),
                board_out=tuple(_as_pasted(c, lookup) for c in m.board_out),
            )
            for m in matchups
        )
        problems = validate_plans(evidence.parsed.main, evidence.parsed.side, checked)
        planned = {m.archetype for m in matchups}
        problems.extend(
            PlanProblem(x.name, "no plan was written for an archetype you expect at the store.")
            for x in evidence.expected if x.name not in planned
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise NarrativeError(f"missing or malformed field: {exc}") from exc

    return RcqNarrative(
        game_plan=game_plan,
        expected_field=expected_field,
        matchups=matchups,
        flex_notes=flex_notes,
        checklist=checklist,
        problems=tuple(problems),
    )
