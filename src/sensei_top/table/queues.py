"""The event rule: which queues allow advice on the Live page while a game
is under way.

Advice — the keep verdict and keep guide, the opponent-hand estimate, the
matchup brief — shows in the casual queues and on the ranked ladder, and
stays off in events; between games the sideboard plan shows in every queue.
Why the line sits there, read from Magic's digital tournament documents:
docs/current-match.md, "The event rule (`table/queues.py`)".

The rule is an allowlist, not a list of events: an event id this module does
not know, or none at all, counts as an event (rule 4 — unknown is never read
as the permissive answer). Every id below was read off a real database's
``matches.event_id``, not from Arena's documentation. ``DirectGame`` is
deliberately absent: a Direct Challenge is how community tournaments are
played on Arena, and the log cannot tell one from a game with a friend. A
queue missing from this list costs only the advice in that queue until it is
added. MTGO matches carry no event id, so the rule reads every one as an
event.

The user can also turn advice off everywhere, from Settings; that switch is
the browser's own (``web/src/shell/liveAdvice.ts``) and never reaches this
module.
"""

from __future__ import annotations

ADVICE_QUEUES = frozenset(
    {
        "Play",  # unranked, best of one
        "Constructed_BestOf3",  # unranked, best of three
        "AIBotMatch",  # a game against Arena's bot
        "DualColorPrecons",  # the starter-deck queue
        "Ladder",  # ranked, best of one
        "Traditional_Ladder",  # ranked, best of three
    }
)


def allows_advice(event_id: str | None) -> bool:
    """True when ``event_id`` names a known casual or ladder queue."""
    return event_id in ADVICE_QUEUES
