"""The leak finder's training-plan prompt — built here, sent from
``sensei_top.llm`` only when the user has opted in; this module never makes
the call itself. A separate prompt from ``review/narrative.py``'s, because
the leak finder reads across every match rather than one. How the prompt is
served, sent and stored: ``docs/review.md``, "The narrative
(`review/narrative.py`, `review/leaks_narrative.py`)".

What it describes is aggregate: pattern codes, sample sizes, win rates and
their Wilson intervals — never a specific match's turn-by-turn shape, since
the leak finder itself never carries one. Nothing here is about an opponent:
every leak is about this player's own patterns across their own matches.
"""


from __future__ import annotations

from sensei_top.answers import answer_format, prose_schema
from sensei_top.i18n import english
from sensei_top.review.leaks import Leak
from sensei_top.review.narrative import NarrativeError, _wrap_prompt

__all__ = [
    "NarrativeError",
    "build_leaks_context",
    "copied_prompt",
    "full_prompt",
]

SYSTEM_PROMPT = (
    "You are reviewing a Magic: The Gathering Arena player's recurring patterns across "
    "many of their own matches, ranked by how much each one actually moves their win rate, "
    "each with a sample size and a 95% confidence interval. Identify which 2-3 patterns are "
    "both large enough and well-supported enough (a narrow interval, a real sample) to be "
    "worth deliberate practice, and say what changing each one would look like in a game. "
    "Do not treat a wide interval or a small sample as a real finding — say so if nothing "
    "here clears that bar. Never invent a pattern, a card, or a match that is not in the "
    "data given to you. Plain prose, no headers, under 400 words."
)


@english()
def build_leaks_context(leaks: list[Leak]) -> str | None:
    """Serialize the leak finder's ranked output into the text a prompt
    sends. ``None`` when there is nothing to synthesize — an empty leak
    list, which only happens when no pattern anywhere cleared
    ``leaks.MIN_SAMPLE`` on both sides of its comparison.
    """
    if not leaks:
        return None

    lines: list[str] = ["Recurring patterns across this player's own completed matches, "
                         "ranked by how much each moves their win rate:"]
    for leak in leaks:
        lines.append(
            f"- [{leak.category}] {leak.sample_title} ({leak.code}): win rate "
            f"{leak.win_rate_with * 100:.0f}% in {leak.n_with} matches with this pattern "
            f"(95% interval {leak.ci_with[0] * 100:.0f}-{leak.ci_with[1] * 100:.0f}%) vs. "
            f"{leak.win_rate_without * 100:.0f}% in {leak.n_without} matches without it "
            f"(interval {leak.ci_without[0] * 100:.0f}-{leak.ci_without[1] * 100:.0f}%)."
        )
    return "\n".join(lines)


@english()
def full_prompt(context: str) -> str:
    """The complete text to hand an assistant: this module's framing, then
    the evidence."""
    return _wrap_prompt(SYSTEM_PROMPT, context)


@english()
def copied_prompt(context: str, *, answer_for: str, context_hash: str) -> str:
    """``full_prompt`` plus the answer contract, for the prompt the card
    offers to copy; the generate path keeps ``full_prompt``."""
    return (
        f"{full_prompt(context)}\n\n---\n\n"
        f"{answer_format(answer_for, context_hash, prose_schema('plain prose'))}"
    )
