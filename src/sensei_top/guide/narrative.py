"""The deck guide's prompt, and the shape of the answer that comes back.
See docs/guide.md, "`narrative.py` — the prompt, and the shape of the
answer".

This module itself never makes a call: only ``sensei_top.llm.client``
imports ``anthropic`` (AGENTS.md non-negotiable #5). Every round trip
shares this module's context, prompt, schema and parser:
``POST /api/guide/{key}/narrative`` sends ``full_prompt`` via
``llm.write_json`` against ``_GUIDE_TOOL``'s schema; a pasted answer
(``PUT`` on the same path) and ``sensei-top guide --deck KEY --import
FILE`` pass ``answers.read_answer`` first, which checks the header the
copied prompt asks for (the CLI also takes a headerless answer, with a
warning) and unwraps the body. All three parse through
``guide_narrative_from_json`` and store the deck-level half in
``deck_narrative`` and every matchup plan in ``matchup_brief``.

**What the prompt carries** (``build_guide_context``): the whole evidence
bundle rendered as the same Markdown tables the exported document uses
(``guide/markdown.py``, with no narrative section — nothing here waits on
prose to describe the numbers), the player's current 75 with oracle text,
the top archetypes by field share — plus the ones this deck has actually
faced most — with their consensus staples and oracle text, the detected
reset and what it voided, and the bundle's own stated gaps. Every figure
in it is already visible elsewhere in the guide, so nothing in it is a
surprise to the person pasting — or the model reading — it.

**What comes back** is a structured shape, not free prose —
``GuideNarrative``. ``_GUIDE_TOOL``'s schema is the contract for the JSON
both the generate route's structured-output request and a pasted or
imported answer must supply. Requesting a shape rather than a document is
what lets ``guide/plans.py`` validate every sideboard plan against the
real 75 before it is ever shown.
"""


from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from sensei_top.answers import answer_format, guide_for
from sensei_top.guide.bundle import DeckGuide
from sensei_top.guide.field import archetype_key_by_name, faced_archetypes
from sensei_top.guide.list_diff import ListDiff
from sensei_top.guide.markdown import render
from sensei_top.guide.plans import PlanProblem, validate_plans
from sensei_top.i18n import english
from sensei_top.review.consensus import build_consensus
from sensei_top.review.narrative import NarrativeError

__all__ = [
    "BoardCard",
    "CardNote",
    "GuideNarrative",
    "MatchupPlan",
    "NarrativeError",
    "build_guide_context",
    "full_prompt",
    "guide_narrative_from_json",
]

TOP_ARCHETYPES_FOR_ORACLE_TEXT = 6
# The field's top archetypes by share are the ones a tournament faces; the
# ones this deck actually meets on the ladder are often different. Up to
# MOST_FACED_ARCHETYPES more, each faced at least MIN_TIMES_FACED times in
# the guide's window, so every guide also writes the briefs the Live page
# most often needs (brief/from_guide.py stores one per matchup plan).
MOST_FACED_ARCHETYPES = 5
MIN_TIMES_FACED = 3

SYSTEM_PROMPT = (
    "You are writing a deck and sideboard guide for a Magic: The Gathering Arena player, in "
    "the tradition of the game's own strategy writing. You are given the player's own play "
    "evidence, their current decklist compared against what winning tournament pilots of the "
    "same archetype register, the field's shares and how they moved across a detected format "
    "reset (a card or cards that were banned), and card oracle text. Explain how the deck's "
    "engine actually works from the card text given — this is reasoning, mark it as such. "
    "State the single biggest leak in the player's own play, grounded in the evidence given, "
    "never invented. For each opponent archetype given with its consensus staples — the "
    "field's top archetypes and the ones this player actually faces most — write sideboard "
    "advice, with the archetype named exactly as its heading gives it: what plays around "
    "what, and a concrete swap plan (cards named exactly as given, at exact counts) between "
    "the maindeck and sideboard the player actually has. A pre-reset matchup "
    "rate marked void must never be treated as current. Say when something is inferred from "
    "card text rather than measured, mark it (reasoned). Never invent a card, a number, or a "
    "sample size not in the data given to you."
)

_GUIDE_TOOL = {
    "name": "emit_guide",
    "description": "Return the written sections of a deck and sideboard guide.",
    "input_schema": {
        "type": "object",
        "properties": {
            "engine": {
                "type": "string",
                "description": "How the deck's engine actually works, from the card text given.",
            },
            "fix": {
                "type": "string",
                "description": "The single biggest leak in the player's own play, and the fix.",
            },
            "card_notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "card": {"type": "string"},
                        "verdict": {
                            "type": "string",
                            "enum": ["correct", "add", "trim", "cut", "flex"],
                        },
                        "why": {"type": "string"},
                    },
                    "required": ["card", "verdict", "why"],
                },
            },
            "matchups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "archetype": {"type": "string"},
                        "prose": {"type": "string"},
                        "board_in": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "card": {"type": "string"}, "n": {"type": "integer"},
                                },
                                "required": ["card", "n"],
                            },
                        },
                        "board_out": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "card": {"type": "string"}, "n": {"type": "integer"},
                                },
                                "required": ["card", "n"],
                            },
                        },
                    },
                    "required": ["archetype", "prose", "board_in", "board_out"],
                },
            },
            "checklist": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short questions to ask between rounds.",
            },
        },
        "required": ["engine", "fix", "card_notes", "matchups", "checklist"],
    },
}


@dataclass(frozen=True, slots=True)
class BoardCard:
    card: str
    n: int


@dataclass(frozen=True, slots=True)
class CardNote:
    card: str
    verdict: str
    why: str


@dataclass(frozen=True, slots=True)
class MatchupPlan:
    archetype: str
    prose: str
    board_in: tuple[BoardCard, ...]
    board_out: tuple[BoardCard, ...]


@dataclass(frozen=True, slots=True)
class GuideNarrative:
    engine: str
    fix: str
    card_notes: tuple[CardNote, ...]
    matchups: tuple[MatchupPlan, ...]
    checklist: tuple[str, ...]
    problems: tuple[PlanProblem, ...] = ()


def _oracle_text_block(conn, grp_ids: list[int]) -> str:
    if not grp_ids:
        return ""
    lines = []
    for row in conn.execute(
        f"SELECT DISTINCT name, type_line, mana_cost, oracle_text FROM cards "
        f"WHERE grp_id IN ({','.join('?' for _ in grp_ids)}) AND oracle_text IS NOT NULL",
        grp_ids,
    ):
        lines.append(
            f"- {row['name']} ({row['type_line'] or '?'}, {row['mana_cost'] or '?'}): "
            f"{row['oracle_text']}"
        )
    return "\n".join(lines)


def _opponent_sections(
    lines: list[str],
    guide: DeckGuide,
    *,
    conn,
    own_name: str | None,
    own_key: str | None,
    shown_grp_ids: set[int],
    extra: Sequence[tuple[str, str]] = (),
    extra_intro: str = "",
) -> None:
    """Append the opponent sections a prompt carries: the field's top
    archetypes by share, then ``extra`` (``(archetype_key, heading)`` pairs,
    each given a section even with no consensus on file — the RCQ guide's
    expected archetypes, ``guide/rcq.py``) under ``extra_intro``, then the
    archetypes this deck has faced most. A key already shown is never shown
    twice, and ``shown_grp_ids`` is updated in place, so oracle text stays
    de-duplicated across every section. ``extra`` empty, this is exactly the
    deck guide's own opponent half."""
    key_by_name = archetype_key_by_name(conn)
    since = guide.provenance.window_start

    def section(heading: str, archetype_key: str, *, always: bool = False) -> bool:
        consensus = build_consensus(conn, archetype_key, fmt=guide.field.fmt, since=since)
        if consensus is None:
            if always:
                lines.append(heading)
                if guide.field.fmt is None:
                    lines.append("  (no consensus list: the deck's format is unknown)")
                else:
                    lines.append("  (too few decklists on file for a consensus list)")
                return True
            return False
        staples = consensus.staples()
        lines.append(heading)
        for card in staples:
            lines.append(f"  {card.copies:.1f}x {card.name} ({card.share:.0%} of decks)")
        grp_ids = [
            c.grp_id for c in staples
            if c.grp_id is not None and c.grp_id not in shown_grp_ids
        ]
        shown_grp_ids.update(grp_ids)
        text = _oracle_text_block(conn, grp_ids)
        if text:
            lines.append(text)
        return True

    lines.append("")
    lines.append(
        f"Consensus staples and oracle text for the top {TOP_ARCHETYPES_FOR_ORACLE_TEXT} "
        f"opponent archetypes by field share (a card's oracle text is given once, the first "
        f"time it appears):"
    )
    shown_keys: set[str] = set()
    for share in guide.field.shares:
        if len(shown_keys) >= TOP_ARCHETYPES_FOR_ORACLE_TEXT:
            break
        if share.archetype == own_name:
            continue
        archetype_key = key_by_name.get(share.archetype)
        if archetype_key is None or archetype_key in shown_keys:
            continue
        if section(
            f"-- {share.archetype} ({share.share:.1%} of the field) --", archetype_key,
        ):
            shown_keys.add(archetype_key)

    extra_lines_at = len(lines)
    shown_extra = 0
    for archetype_key, heading in extra:
        if archetype_key in shown_keys:
            continue
        if section(heading, archetype_key, always=True):
            shown_keys.add(archetype_key)
            shown_extra += 1
    if shown_extra:
        lines.insert(extra_lines_at, "")
        lines.insert(extra_lines_at + 1, extra_intro)

    share_by_name = {s.archetype: s.share for s in guide.field.shares}
    faced = sorted(
        (
            (key, name, n)
            for key, (name, n) in faced_archetypes(
                conn, guide.provenance.deck.deck_ids, since=since,
            ).items()
            # key_by_name.get(name) == key: brief/from_guide.py stores each
            # plan under key_by_name[plan.archetype], so a name that maps to
            # another key would file this matchup's plan under the wrong one.
            if n >= MIN_TIMES_FACED and key not in shown_keys and key != own_key
            and key_by_name.get(name) == key
        ),
        key=lambda t: (-t[2], t[0]),
    )
    faced_lines_at = len(lines)
    shown_faced = 0
    for key, name, n in faced:
        if shown_faced >= MOST_FACED_ARCHETYPES:
            break
        share = share_by_name.get(name)
        share_text = (
            f"{share:.1%} of the field" if share is not None
            else "not among the field's top archetypes"
        )
        window_text = "since the reset" if since is not None else "in your history"
        if section(f"-- {name} (you faced it {n} times {window_text}; {share_text}) --", key):
            shown_faced += 1
    if shown_faced:
        lines.insert(faced_lines_at, "")
        lines.insert(
            faced_lines_at + 1,
            f"Consensus staples and oracle text for the archetypes you have actually faced "
            f"most (at least {MIN_TIMES_FACED} times each), not already listed above:",
        )


@english()
def build_guide_context(guide: DeckGuide, *, conn) -> str | None:
    """Serialize a deck guide into the text a prompt sends. ``None`` when
    there is nothing to write about — a deck with no matches at all.
    """
    if guide.provenance.deck.matches == 0:
        return None

    lines: list[str] = [
        f"Deck: {guide.provenance.deck.name or guide.provenance.deck.key}",
        render(guide),
        "",
        "Card oracle text for your own maindeck and sideboard:",
    ]
    own_grp_ids = list({
        *(guide.provenance.deck.current_cards.get("maindeck") or []),
        *(guide.provenance.deck.current_cards.get("sideboard") or []),
    })
    lines.append(_oracle_text_block(conn, own_grp_ids))

    diff: ListDiff | None = guide.list_diff
    _opponent_sections(
        lines, guide, conn=conn,
        own_name=diff.archetype_name if diff is not None else None,
        own_key=diff.archetype_key if diff is not None else None,
        # Oracle text is printed once per card across every opponent
        # section — and not at all for a card already given with the
        # player's own 75 — since the same staples recur across archetypes
        # and each repeat is pure prompt cost.
        shown_grp_ids=set(own_grp_ids),
    )

    return "\n".join(lines)


def _plan_from(raw: dict) -> MatchupPlan:
    return MatchupPlan(
        archetype=raw["archetype"],
        prose=raw["prose"],
        board_in=tuple(BoardCard(c["card"], c["n"]) for c in raw.get("board_in", [])),
        board_out=tuple(BoardCard(c["card"], c["n"]) for c in raw.get("board_out", [])),
    )


def _guide_narrative_from_tool_input(raw: dict, guide: DeckGuide) -> GuideNarrative:
    matchups = tuple(_plan_from(m) for m in raw.get("matchups", []))
    problems: tuple[PlanProblem, ...] = ()
    if guide.list_diff is not None:
        recommended_main = Counter({
            c.card: c.recommended for c in guide.list_diff.maindeck if c.recommended
        })
        recommended_side = Counter({
            c.card: c.recommended for c in guide.list_diff.sideboard if c.recommended
        })
        problems = tuple(validate_plans(recommended_main, recommended_side, matchups))

    return GuideNarrative(
        engine=raw["engine"],
        fix=raw["fix"],
        card_notes=tuple(
            CardNote(c["card"], c["verdict"], c["why"]) for c in raw.get("card_notes", [])
        ),
        matchups=matchups,
        checklist=tuple(raw.get("checklist", [])),
        problems=problems,
    )


def _wrap_json_prompt(
    system_prompt: str, schema: dict, context: str, *,
    answer_for: str | None = None, written_for: str | None = None,
) -> str:
    """The shape every JSON-schema-flavoured ``full_prompt`` in this project
    uses. Shared with ``brief/narrative.py`` and ``guide/rcq.py`` — the same
    idiom, a different ``SYSTEM_PROMPT`` and tool schema.

    With ``answer_for`` (a copied prompt): framing, ``---``, evidence,
    ``---``, then ``answers.answer_format``'s contract, last, where the
    assistant reads it just before answering; ``written_for`` is the
    staleness hash the answer copies back. Without it (the generate path,
    whose structured-output request already fixes the shape): framing, the
    schema, then the evidence."""
    if answer_for is not None:
        return (
            f"{system_prompt}\n\n---\n\n{context}\n\n---\n\n"
            f"{answer_format(answer_for, written_for, schema)}"
        )
    return (
        f"{system_prompt}\n\n"
        f"Answer as a single JSON object matching this schema, and nothing else:\n"
        f"{json.dumps(schema, indent=2)}\n\n---\n\n{context}"
    )


def _parse_json_object(raw: str | dict) -> dict:
    """The str -> json -> dict ladder every JSON-schema-flavoured narrative
    parser in this project starts with, raising ``NarrativeError`` rather
    than a raw ``json`` exception. Shared with ``brief/narrative.py`` and
    ``guide/rcq.py``."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NarrativeError(f"not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise NarrativeError("expected a single JSON object at the top level.")
    return raw


@english()
def full_prompt(guide: DeckGuide, *, conn, answer_contract: bool = True) -> str | None:
    """The complete text to hand an assistant: the framing, then the
    evidence, then the answer contract (``answers.py``) naming this deck's
    guide and the 75 it is written for. ``answer_contract=False`` is the
    generate route's prompt, which leaves the contract out. ``None`` when
    there is nothing to write about, same as ``build_guide_context``."""
    context = build_guide_context(guide, conn=conn)
    if context is None:
        return None
    if not answer_contract:
        return _wrap_json_prompt(SYSTEM_PROMPT, _GUIDE_TOOL["input_schema"], context)
    # Imported here: brief/store.py imports this module.
    from sensei_top.brief.store import list_hash

    deck = guide.provenance.deck
    return _wrap_json_prompt(
        SYSTEM_PROMPT, _GUIDE_TOOL["input_schema"], context,
        answer_for=guide_for(deck.key), written_for=list_hash(deck.current_cards),
    )


def guide_narrative_from_json(raw: str | dict, guide: DeckGuide) -> GuideNarrative:
    """Parse an authored narrative and validate its sideboard plans against
    the real 75 before handing it back.

    Accepts the JSON object ``_GUIDE_TOOL``'s schema describes. Raises
    ``NarrativeError`` on anything malformed, so the caller can say what was
    wrong rather than storing a half-parsed guide. A plan the author got wrong is *caught and
    surfaced*, never silently repaired: see ``guide/plans.py``.
    """
    raw = _parse_json_object(raw)
    try:
        return _guide_narrative_from_tool_input(raw, guide)
    except (KeyError, TypeError) as exc:
        raise NarrativeError(f"missing or malformed field: {exc}") from exc
