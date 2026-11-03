"""The leak finder's own cross-match output — ``/api/review/leaks``
(``docs/review.md``); its narrative routes are ``ai/routes/leaks.py``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from fastapi import APIRouter, Request

from sensei_top.api.convert import _leak_out
from sensei_top.api.deps import Conn, DeckFilter, SourceFilter
from sensei_top.api.models.review import LeaksOut
from sensei_top.api.sql import _consensus_window, _shared_report_cache
from sensei_top.review.leaks import find_leaks

router = APIRouter()


def _leaks_consensus_window(conn: sqlite3.Connection) -> Callable[[str], str | None]:
    """The resolver ``find_leaks`` takes as its ``consensus_window``: each
    match is measured against its own format's reset window. Uncached, like
    the match report and the guide, so a reset a ``cards --scryfall`` run
    reveals reaches Leaks on the next request; ``find_leaks`` asks once per
    format its population holds. The report cache stays shared with the
    guide, the RCQ guide and the coach, since it is keyed on the window each
    report was built under."""

    def window(fmt: str) -> str | None:
        return _consensus_window(conn, fmt)

    return window


@router.get("/api/review/leaks", response_model=LeaksOut, tags=["review"])
def review_leaks(
    request: Request, conn: Conn, deck_id: DeckFilter = None, source: SourceFilter = "arena"
) -> LeaksOut:
    """Recurring patterns across every completed match, ranked by how
    much each moves this player's own win rate — see
    ``review/leaks.py``'s module docstring for the sample-gating and
    the Wilson interval every rate here carries. Computed fresh on
    every request, same reasoning as the per-match report: it depends
    on ``cards``, which the projector does not own — but the
    ``MatchReport`` each leak is built from is shared across requests
    (``api/sql.py::_shared_report_cache``), not rebuilt from scratch here.

    ``deck_id`` scopes the population to one deck's own matches, the same
    computation the deck guide runs for one deck.
    """
    deck_ids = (deck_id,) if deck_id else None
    leaks = find_leaks(
        conn, deck_ids=deck_ids, source=source,
        consensus_window=_leaks_consensus_window(conn),
        report_cache=_shared_report_cache(request, conn),
    )
    return LeaksOut(
        leaks=[_leak_out(leak) for leak in leaks],
        narrative_available=True,
    )
