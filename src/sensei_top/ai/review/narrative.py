"""The match report's coaching prompt — built here, sent from
``sensei_top.ai.llm`` only when the user has opted in. How the prompt is
served, sent and stored: ``docs/review.md``, "The narrative
(`ai/review/narrative.py`, `ai/review/leaks_narrative.py`)".

**This module never makes the call itself.** The only module that imports
``anthropic`` is ``sensei_top.ai.llm.client`` (AGENTS.md non-negotiable #5);
this one stays a pure function of already-projected data, assembling an
honest, complete, inspectable prompt:

* **What it carries:** the position track turn by turn, both sides' play
  sequence, and the report's own findings and gaps together, so the
  coaching can point at a specific turn and argue with a specific decision.
  Never the raw zone-by-zone board state (no hands, no graveyards, no exile
  contents).
* **Unknowns are stated, never guessed (rule 4).** The context lists the
  report's own gaps as a named "not evaluated" section, and ends with what
  this reader never sees for any match at all (the stack, counters,
  attachments, exact phase/step, the opponent's hand) — so whoever writes
  the narrative is never left to assume silence means "nothing happened".
* **No third-party identifiers, ever.** ``MatchSnapshot`` never carries the
  opponent's Arena handle or user id in the first place, so there is nothing
  here to accidentally include — see ``snapshot.py``.

``FieldContext`` is the one addition beyond the game itself: one public
aggregate statistic about the opponent's own archetype, from real tournament
results (``metagame/``), added only when it exists for this match.
"""


from __future__ import annotations

import json
from dataclasses import dataclass

from sensei_top.ai.answers import answer_format
from sensei_top.ai.rules_notes import append_block
from sensei_top.i18n import english
from sensei_top.review.findings import Finding, MatchReport
from sensei_top.review.snapshot import MatchSnapshot

DEFAULT_MODEL = "claude-opus-5-5"
# A full structured review, not a footnote: the game itself is in the
# prompt, and effort/tokens have to match the depth the user asked this
# feature to reach.
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TOKENS = 8000

SYSTEM_PROMPT = (
    "You are reviewing one already-finished Magic: The Gathering Arena match for a player "
    "who wants to improve, in the tradition of the game's own strategy writing (Flores' "
    "role assignment, Duke's damage racing and tempo/card-advantage framing). You are given "
    "the match's turn-by-turn shape (life, hand size, board, lands for both sides), both "
    "sides' play sequence, and a local reader's own findings and gaps about the game. "
    "Assign the role explicitly (beatdown or control, and for which side) if the findings "
    "do not already settle it, in the games field. Name the turn the game actually turned "
    "on and say what changed there. State the single highest-leverage change for next time, "
    "specific enough "
    "that the player could argue with it. State your confidence. Never invent a play, a "
    "card, or an observation that is not in the findings or the turn-by-turn data given to "
    "you, and never comment on anything named in the gaps as unobserved, or on combat, the "
    "stack, or the opponent's hand contents — none of that is tracked here for any match. "
    "Fill each field of the answer's schema; plain sentences, no headings, no lists."
)

_SUMMARY_TOOL = {
    "name": "emit_summary",
    "description": "Return the four written parts of a match summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "games": {
                "type": "string",
                "description": "One or two sentences per game, in order: what decided it.",
            },
            "key_leak": {
                "type": "string",
                "description": "The one thing the player most controls and should change. "
                "Start with that thing in one sentence, then at most two sentences of why, "
                "citing the findings.",
            },
            "counter_argument": {
                "type": "string",
                "description": "The strongest reading that the result was not the player's "
                "doing, in two or three sentences.",
            },
            "confidence": {
                "type": "string",
                "description": "One sentence: how far the evidence supports the key leak, "
                "and what would change it.",
            },
        },
        "required": ["games", "key_leak", "counter_argument", "confidence"],
    },
}

# The fixed English headings the four parts are joined under into `prose`.
SECTION_HEADINGS = (
    ("games", "## Games"),
    ("key_leak", "## Key leak"),
    ("counter_argument", "## Counter-argument"),
    ("confidence", "## Confidence"),
)


class NarrativeError(Exception):
    """A narrative could not be built or parsed — malformed input, never a
    network failure (that's ``llm.LLMError``, raised by
    ``sensei_top.ai.llm.client`` and mapped to a 502 by the generate routes).
    Every caller of this one fails soft on it."""


SYSTEM_PROMPT_HEADING = "System prompt (paste this above the evidence):"

# Shared with ``ai/coach/narrative.py``, which ends its own context with the
# same sentence — this reader never sees any of this for any match, so both
# prompts state it identically rather than each writing their own wording.
UNTRACKED = (
    "Not tracked by this reader at all, for any match: the stack, counters and other "
    "continuous effects, attachments, the exact phase or step, and which specific cards "
    "were in the opponent's hand at any point."
)


def _wrap_prompt(system_prompt: str, context: str) -> str:
    """The framing-then-evidence shape: the system prompt, a divider, then
    the evidence. Shared with ``ai/review/leaks_narrative.py`` and
    ``ai/coach/narrative.py``, each with its own system prompt."""
    return f"{system_prompt}\n\n---\n\n{context}"


@english()
def full_prompt(context: str, *, notes_block: str = "") -> str:
    """The complete text the generate path (``POST``) sends: the framing,
    the schema, then the evidence ``build_narrative_context`` returns, then
    ``notes_block`` (``rules_notes.render_block``) when it is not empty. The
    copyable prompt is ``copied_prompt``."""
    framed = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Answer as a single JSON object matching this schema, and nothing else:\n"
        f"{json.dumps(_SUMMARY_TOOL['input_schema'], indent=2)}\n\n---\n\n{context}"
    )
    return append_block(framed, notes_block)


@english()
def copied_prompt(
    context: str, *, answer_for: str, context_hash: str, notes_block: str = ""
) -> str:
    """The framing and evidence plus the answer contract
    (``answers.answer_format``, with ``_SUMMARY_TOOL``'s schema), for the
    prompt the card offers to copy. The schema is said once, in the
    contract; the generate path's ``full_prompt`` says it before the
    evidence instead."""
    return (
        f"{append_block(_wrap_prompt(SYSTEM_PROMPT, context), notes_block)}\n\n---\n\n"
        f"{answer_format(answer_for, context_hash, _SUMMARY_TOOL['input_schema'])}"
    )


@dataclass(frozen=True, slots=True)
class MatchSummary:
    games: str
    key_leak: str
    counter_argument: str
    confidence: str

    @property
    def prose(self) -> str:
        """The four parts under ``SECTION_HEADINGS``: what ``match_narrative.prose``
        holds, so every reader of a plain string keeps working."""
        return "\n\n".join(
            f"{heading}\n{getattr(self, name)}" for name, heading in SECTION_HEADINGS
        )

    def sections_json(self) -> str:
        return json.dumps(
            {name: getattr(self, name) for name, _ in SECTION_HEADINGS}, ensure_ascii=False
        )


def summary_from_json(raw: str | dict) -> MatchSummary:
    """Parse the object ``_SUMMARY_TOOL``'s schema describes — the generate
    path's reply and a pasted answer's body. ``NarrativeError`` on anything
    else, including a plain-prose answer (``{"prose": ...}``) from an older
    copied prompt: it is refused, never stored as one paragraph."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NarrativeError(f"not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise NarrativeError("expected a single JSON object at the top level.")
    parts = {}
    for name, _heading in SECTION_HEADINGS:
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip():
            raise NarrativeError(f'expected a non-empty "{name}" string.')
        parts[name] = value.strip()
    return MatchSummary(**parts)


def _anchor(f: Finding) -> str:
    if f.game_number is None:
        return ""
    if f.self_turn_index is not None:
        return f" (game {f.game_number}, your turn {f.self_turn_index})"
    return f" (game {f.game_number})"


def finding_line(f: Finding) -> str:
    """One finding, rendered without its caveats — shared with
    ``ai/coach/evidence.py``'s worked examples (``ExampleGame.finding_lines``)
    so the two never drift out of formatting sync. Caveats stay this
    function's caller's job: the narrative prompt renders them as their own
    indented line right after, but an example game's compact finding list
    has no room for them."""
    return f"- [{f.category}/{f.severity}] {f.title}{_anchor(f)}: {f.detail}"


@dataclass(frozen=True, slots=True)
class FieldContext:
    """Public aggregate tournament data about the opponent's own archetype —
    never anything about this match, this player, or their deck. Built by the
    API route from ``v_meta_winrate`` (Tier A/B/D tournament results, never
    Arena) and passed in only when a figure actually exists for this match's
    classified opponent. This is public data about the format, never
    anything closer to raw board state.
    """

    archetype_label: str
    matches: int
    winrate: float
    # The format-reset window this was counted from (docs/metagame.md, "The
    # format-reset boundary"), or None when it wasn't windowed.
    since: str | None = None


def turn_lines_of(snap: MatchSnapshot, game_number: int) -> list[str]:
    lines = []
    for t in snap.turns_in(game_number):
        parts = [f"turn {t.turn_number}" if t.self_turn_index is None
                 else f"turn {t.turn_number} (your turn {t.self_turn_index})"]
        if t.self_life is not None and t.opp_life is not None:
            parts.append(f"life {t.self_life}-{t.opp_life}")
        if t.self_hand is not None and t.opp_hand is not None:
            parts.append(f"hand {t.self_hand}-{t.opp_hand}")
        if t.self_permanents is not None and t.opp_permanents is not None:
            parts.append(f"board {t.self_permanents}-{t.opp_permanents}")
        if t.self_power is not None and t.opp_power is not None:
            parts.append(f"power {t.self_power}-{t.opp_power}")
        if t.self_lands is not None and t.opp_lands is not None:
            parts.append(f"lands {t.self_lands}-{t.opp_lands}")
        lines.append("  " + ", ".join(parts))
    return lines


def play_lines_of(snap: MatchSnapshot, game_number: int) -> list[str]:
    plays = sorted(
        [(p.turn_number, "you", p) for p in snap.self_plays if p.game_number == game_number]
        + [(p.turn_number, "opponent", p) for p in snap.opponent_plays
           if p.game_number == game_number],
        key=lambda triple: triple[0],
    )
    lines = []
    for turn_number, side, play in plays:
        if play.category != "Resolve":
            continue
        name = play.card_name or "an unidentified card"
        lines.append(f"  turn {turn_number}: {side} resolved {name}")
    return lines


@english()
def build_narrative_context(
    report: MatchReport, snap: MatchSnapshot, *, field: FieldContext | None = None
) -> str | None:
    """Serialize a match report and its snapshot into the text a narrative
    prompt sends.

    Returns ``None`` when there is nothing to narrate at all — a match with
    no findings and no gaps, which only happens when nothing about it could
    be read in the first place. A match with no findings but a real
    ``FieldContext`` still returns ``None``: field data augments a
    narrative, it never becomes the only reason to send one.
    """
    if not report.findings and not report.gaps:
        return None

    lines: list[str] = [f"Match result: {report.result or 'unknown'}."]

    if field is not None:
        since_clause = f" since {field.since}" if field.since else ""
        lines.append(
            f"Field context (public tournament data, not about this player or match): "
            f"{field.archetype_label} has won {field.winrate * 100:.0f}% of its "
            f"{field.matches} tracked real-tournament matches{since_clause} "
            f"(MTGO/paper, never Arena)."
        )

    for game in report.games:
        turn_lines = turn_lines_of(snap, game.game_number)
        play_lines = play_lines_of(snap, game.game_number)
        if not turn_lines and not play_lines:
            continue
        lines.append(f"Game {game.game_number} ({game.result or 'unknown'}), turn by turn "
                      f"(your side first in every pair):")
        lines.extend(turn_lines)
        if play_lines:
            lines.append(f"Game {game.game_number} spells resolved, in order:")
            lines.extend(play_lines)

    if report.findings:
        lines.append("Findings:")
        for f in report.findings:
            lines.append(finding_line(f))
            for caveat in f.caveats:
                lines.append(f"    caveat: {caveat}")

    if report.gaps:
        lines.append("Not evaluated for this match — treat as unknown, not as evidence that")
        lines.append("nothing happened:")
        for g in report.gaps:
            lines.append(f"- {g.reason}")

    lines.append(UNTRACKED)
    return "\n".join(lines)
