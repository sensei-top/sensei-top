"""Reading the pending mulligan decision straight from ``raw_events`` — not
the projection.

Arena logs the offered hand before the keep/mulligan decision, for our own
seat only. See docs/arena-log.md, "The traps", trap 14 and the instance-id
reuse trap after it, which every replay here must be anchored against. This
reads the offer diff itself; the *kept* hand's zone transfers arrive only
after the decision, which is why ``migrations/009_drop_opening_hand.sql``'s
reconstruction failed. Verified against 503 real mulligan decisions: every
offer resolves to exactly 7 cards.

A thin wrapper: the replay lives in ``projector/live_state.py``. Kept as
its own module because ``table/opening_hand.py`` and
``tests/test_projector_mulligan.py`` import from here by name; the names
in ``__all__`` are re-exported unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable

from sensei_top.projector.live_state import (
    PENDING_MULLIGAN,
    MulliganCard,
    MulliganOffer,
    replay_live_state,
)

__all__ = ["PENDING_MULLIGAN", "MulliganCard", "MulliganOffer", "replay_pending_offer"]


def replay_pending_offer(payloads: Iterable[str]) -> MulliganOffer | None:
    """Replay raw ``payload`` text in ascending id order and report whichever
    hand is currently offered to us for a decision, or ``None`` once the
    newest thing that happened was our own submitted decision.

    ``payloads`` must start at or before the current match's own room-start
    event — see docs/arena-log.md, "The traps", the instance-id reuse
    paragraph after trap 14. This function trusts its caller to have
    anchored the window; ``table/live.py`` is what enforces it for every
    reader built on this (``table/opening_hand.py`` included).
    """
    return replay_live_state(payloads).offer
