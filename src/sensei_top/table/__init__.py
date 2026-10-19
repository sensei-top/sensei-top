"""What is true at the table right now: reads for a game in progress, each
computed fresh on every request and never stored.

This is a sibling to ``review/`` (post-game) rather than a variant of it:
where ``review/`` only runs once a match is over, this package only runs
*during* one — it is the current-match analogue of the same architectural
rule (AGENTS.md non-negotiable #1: the reader knows files, the projector
knows Arena semantics, and neither learns the other's job). Nothing here
writes anything, so every route built on it stays in the API's read-only
majority (AGENTS.md non-negotiable #6).

Most of these are pure derivations over already-projected data. Two are a
deliberate, narrow exception: ``opening_hand.py`` (the pending mulligan
decision) and ``live.py`` (opponent counts, revealed cards, our own
remaining library) both read ``raw_events`` directly, because a full
``project()`` rebuild cannot land inside the window either one needs — a
5-second median mulligan decision, or a 1-second poll while a game is under
way (``projector/live_state.py``'s module docstring has the measurements:
~11.6 s for a rebuild's wall time against 0.03-0.08 s for one match's own
replay). This does not blur the reader/projector boundary: the code that
actually knows Arena's message shapes is ``projector/live_state.py``,
reusing the very same ``GameStateTracker`` ``project()`` uses; both files
here only call into it, exactly the relationship every other read has with
projected tables instead.

- ``keep.py`` — the keep guide: what a keepable opening hand looks like for
  the deck being played, from the maindeck's own curve. Valid for the whole
  game, including before the very first keep/mulligan decision.
- ``opening_hand.py`` — whether the specific 7 cards just dealt are worth
  keeping, read from the log before the decision is made.
- ``hand_read.py`` — what the opponent might still be holding, from the
  field's consensus decklist for their archetype minus what this game has
  already revealed and (when a live replay is available) minus lands and
  anything already confirmed in their hand.
- ``live.py`` — the fresh, request-time replay behind the two reads above
  and the tab's own remaining-library panel.
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
