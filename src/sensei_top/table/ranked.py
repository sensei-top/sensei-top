"""The ranked-play rule: which queues keep advice off the Live page while a
game is under way.

Wizards' Terms §2.2 forbids unauthorized third-party tools, and trackers
survive on tolerance; real-time coaching during ranked or competitive play
is the line no tracker in this field crosses. So during a ranked game the
Live page shows only what every tracker shows — the remaining library and
its draw odds, the opponent's revealed cards, the archetype read — and the
advice (the keep verdict and keep guide, the opponent-hand estimate, the
matchup brief) waits for an unranked game or the break between games.

The rule is an allowlist of casual queues, not a list of ranked ones: an
event id this module does not know, or none at all, counts as ranked (rule
4 — unknown is never read as the permissive answer). Every id below was read
off a real database's ``matches.event_id``, not from Arena's documentation.
``DirectGame`` is deliberately absent: a Direct Challenge is how community
tournaments are played on Arena, and the log cannot tell one from a game
with a friend (the user's decision, 2026-10-01). A casual queue missing from
this list costs only the advice in that queue until it is added.

MTGO never reaches the Live page (``migrations/040_arena_only_current_match.sql``)
and its matches carry no event id, so the rule reads every MTGO match as
ranked too: leagues and challenges are exactly what it is for.
"""

from __future__ import annotations

UNRANKED_EVENTS = frozenset(
    {
        "Play",  # unranked, best of one
        "Constructed_BestOf3",  # unranked, best of three
        "AIBotMatch",  # a game against Arena's bot
        "DualColorPrecons",  # the starter-deck queue
    }
)


def is_ranked(event_id: str | None) -> bool:
    """True unless ``event_id`` names a known casual queue."""
    return event_id not in UNRANKED_EVENTS
