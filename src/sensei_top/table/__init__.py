"""What is true at the table right now: reads for a game in progress, each
computed fresh on every request and never stored. The sibling of
``review/`` (post-game). This package writes nothing (AGENTS.md
non-negotiable #6): docs/current-match.md, "Why this exists".

Most of these derive from projected data. ``opening_hand.py`` and
``live.py`` read ``raw_events`` instead, through ``projector/live_state.py``'s
replay (the code that knows Arena's message shapes stays in the projector),
because a full ``project()`` rebuild cannot land inside a mulligan decision
or a 1-second poll: docs/current-match.md, "The live replay (`table/live.py`,
`projector/live_state.py`)".

- ``keep.py`` — the keep guide: what a keepable opening hand looks like for
  the deck being played, from the maindeck's own curve. Valid for the whole
  game, including before the very first keep/mulligan decision.
- ``opening_hand.py`` — whether the specific 7 cards just dealt are worth
  keeping, read from the log before the decision is made.
- ``hand_read.py`` — what the opponent might still be holding, from the
  field's consensus decklist for their archetype, lands excluded, minus
  what this game has already revealed, their hand included.
- ``live.py`` — the fresh, request-time replay behind the two reads above
  and the Live page's remaining-library panel.
- ``intermission.py`` — the break read: the sideboard plan between games of
  a Bo3, with ``boarding.py``'s sideboard diff behind its past boarding.
- ``queues.py`` — the event rule: which queues allow the advice above on
  the page while a game is under way.
"""

from sensei_top.table.hand_read import HandCard, HandRead, RevealedCard, build_hand_read
from sensei_top.table.keep import HandSlot, KeepGuide, MulliganRecord, build_keep_guide
from sensei_top.table.live import LibraryCard, build_library_remaining, build_live_state
from sensei_top.table.opening_hand import (
    OpeningHandCard,
    OpeningHandRead,
    build_opening_hand_read,
)
from sensei_top.table.queues import allows_advice

__all__ = [
    "HandCard",
    "HandRead",
    "HandSlot",
    "KeepGuide",
    "LibraryCard",
    "MulliganRecord",
    "OpeningHandCard",
    "OpeningHandRead",
    "RevealedCard",
    "allows_advice",
    "build_hand_read",
    "build_keep_guide",
    "build_library_remaining",
    "build_live_state",
    "build_opening_hand_read",
]
