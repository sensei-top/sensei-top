"""The event rule: which queues allow advice on the Live page while a game
is under way.

Advice — the keep verdict and keep guide, the opponent-hand estimate, the
matchup brief — shows in the casual queues and on the ranked ladder, and
stays off in events. The line follows what Magic's digital rules cover. The
ladder is not a tournament, so neither the Digital Tournament Rules nor the
Digital Infraction Procedure Guide reach it; what does, Wizards' Terms §2.2,
treats every tracker alike, whatever it shows. Events are where those
documents apply, and DIPG 2.2's philosophy counts "any strategy advice, play
advice, or construction advice from an external source" as outside
assistance, even as it allows deck tracking software that shows no private
information. In an event the page shows only what that sentence allows: the
remaining library and its draw odds, the opponent's revealed cards, the
archetype read. Between games the sideboard plan shows in every queue, as a
player's own written notes may (DTR 2.10). The reading, and the link to each
document, is in ``docs/current-match.md``, "The event rule".

The rule is an allowlist, not a list of events: an event id this module does
not know, or none at all, counts as an event (rule 4 — unknown is never read
as the permissive answer). Every id below was read off a real database's
``matches.event_id``, not from Arena's documentation. ``DirectGame`` is
deliberately absent: a Direct Challenge is how community tournaments are
played on Arena, and the log cannot tell one from a game with a friend (the
user's decision, 2026-10-01). A queue missing from this list costs only the
advice in that queue until it is added.

MTGO never reaches the Live page (``migrations/040_arena_only_current_match.sql``)
and its matches carry no event id, so the rule reads every MTGO match as an
event too: leagues and challenges are exactly what it is for.

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
