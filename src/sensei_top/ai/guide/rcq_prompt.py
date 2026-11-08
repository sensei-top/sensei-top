"""The RCQ guide's prompt, its answer's shape and the answer's reader.

Built on ``guide/rcq.py``'s evidence, which never makes a call. The prompt
(``rcq_prompt``) and the answer's parser (``rcq_from_json``) are shared by the
opt-in Claude call and a pasted answer. See docs/guide.md, "The RCQ guide".
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter
from dataclasses import dataclass

from sensei_top.ai.answers import rcq_for
from sensei_top.ai.guide.narrative import (
    BoardCard,
    _opponent_sections,
    _oracle_text_block,
    _parse_json_object,
    _wrap_json_prompt,
)
from sensei_top.ai.guide.plans import PlanProblem, validate_plans
from sensei_top.ai.review.narrative import NarrativeError
from sensei_top.archetypes.classify import normalize
from sensei_top.guide.decklist import ParsedList
from sensei_top.guide.markdown import render
from sensei_top.guide.rcq import (
    RECENT_EVENT_DAYS,
    RECENT_SHARE_DAYS,
    RcqEvidence,
    top8_name,
)
from sensei_top.i18n import english

__all__ = [
    "RCQ_SYSTEM_PROMPT",
    "FlexNote",
    "NarrativeError",
    "RcqMatchup",
    "RcqNarrative",
    "rcq_context",
    "rcq_from_json",
    "rcq_prompt",
]

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



def _share_text(share: float | None) -> str:
    return f"{share:.1%} of the field" if share is not None else "not in the field's window"


def _counts_block(title: str, counts: Counter) -> list[str]:
    lines = [f"{title} ({sum(counts.values())}):"]
    lines.extend(f"{n} {name}" for name, n in counts.items())
    return lines


def rcq_context(parsed: ParsedList, expected_keys) -> str:
    """The ``context`` an RCQ prompt carries and its answer copies back: a
    hash of the list's cards, both boards, and the expected archetypes, the
    inputs the guide is written against. Counts by name, casefolded (names
    that casefold alike merge their counts) and sorted, and the expected keys
    sorted, so a list retyped in another case or order, or the same chips
    picked in another order, is the same list; a card added, cut or moved
    between boards is another. The case it is for is an answer copied for one
    list and saved after an edit."""

    def board(cards) -> list:
        counts: dict[str, int] = {}
        for name, count in cards.items():
            key = name.casefold()
            counts[key] = counts.get(key, 0) + count
        return sorted(counts.items())

    payload = json.dumps(
        {
            "main": board(parsed.main),
            "side": board(parsed.side),
            "expected": sorted(expected_keys),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@english()
def rcq_prompt(evidence: RcqEvidence, *, conn, answer_contract: bool = True) -> str:
    """The complete text to hand an assistant: the framing, the evidence —
    the deck guide's own evidence, with the pasted 75 in place of the
    identity's current list — then the answer contract (``answers.py``)
    naming this deck's RCQ guide, with ``rcq_context`` as its ``context``,
    so a pasted answer says which list it was written for.
    ``answer_contract=False`` is the generate route's prompt, which puts the
    schema before the evidence and leaves the contract out."""
    guide = evidence.guide
    # The guide's note that the identity's own list went unclassified is
    # about that list, not the pasted 75: dropped by its flag, which says it
    # is the first gap (DeckGuide's docstring).
    gaps = list(guide.gaps[1:] if guide.own_unclassified else guide.gaps)
    if evidence.own_unclassified_reason is not None:
        gaps.append(evidence.own_unclassified_reason)
    elif evidence.list_diff is None and guide.field.fmt is not None:
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
    shown = dataclasses.replace(
        guide, list_diff=evidence.list_diff, gaps=tuple(gaps), gap_codes=(),
        own_unclassified=False,
    )

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
            top8 = f"; top 8: {', '.join(top8_name(n) for n in e.top8)}" if e.top8 else ""
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

    return _wrap_json_prompt(
        RCQ_SYSTEM_PROMPT, _RCQ_TOOL["input_schema"], "\n".join(lines),
        answer_for=rcq_for(deck.key) if answer_contract else None,
        written_for=(
            rcq_context(evidence.parsed, evidence.expected_keys) if answer_contract else None
        ),
    )


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
