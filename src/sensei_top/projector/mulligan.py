"""Reading the pending mulligan decision straight from ``raw_events`` — not
the projection.

Contrary to what ``migrations/009_drop_opening_hand.sql`` concluded, Arena
does log the opening hand before the keep/mulligan decision: a
``GameStateMessage`` diff sets ``pendingMessageType:
"ClientMessageType_MulliganResp"`` on a player and, in the same or a later
diff, includes that seat's hand as real ``gameObjects`` (``grpId``
included) — but only for our own seat; the opponent's hand zone always
carries ids with no matching objects (``docs/arena-log.md``'s 11b, "Arena
never sends the opponent's decklist", extended here to mulligans: their
hand is exactly as hidden pre-keep as it is at every other point in the
game). What 009 got right is narrower than it reads: the *kept* hand's zone
transfers really do arrive only after the decision, which is why that
reconstruction failed. This module reads a different message entirely — the
offer diff itself, before any decision.

Verified against every one of 503 real mulligan decisions captured in a live
session: every offer resolves to exactly 7 cards (Magic's own London
mulligan rule — always see 7, bottom cards only after keeping), with zero
failures, once the replay is anchored to the *current match's own start*
(``docs/arena-log.md``'s anchoring trap: Arena reuses small instance ids and
``gameStateId`` counters game to game, even match to match).

This module is now a thin wrapper: the actual replay — resolving seats,
tracking the pending mulligan state, walking ``GameStateMessage`` diffs via
``GameStateTracker.apply()`` — lives in ``projector/live_state.py``, the
general form of the same technique extended to the whole board state, not
only the mulligan offer (see its module docstring for the numbers that
motivated generalizing this). Kept as its own module, rather than folded
away, because ``table/opening_hand.py`` and its tests import
``MulliganOffer``/``MulliganCard``/``replay_pending_offer`` from here by
name; those names are re-exported unchanged.
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
    event — see the module docstring's anchoring trap. This function trusts
    its caller to have anchored the window; ``table/live.py`` is what
    enforces it for every reader built on this (``table/opening_hand.py``
    included).
    """
    return replay_live_state(payloads).offer
