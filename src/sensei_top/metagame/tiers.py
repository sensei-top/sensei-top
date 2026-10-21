"""Which claims one tournament event actually supports, and in what order
the dashboard, the brief and the match report reach for them. See
docs/metagame.md, "The evidence tiers", for the four tiers, the ranking and
the three event shapes this was verified against in real cache files on
2026-08-18.

A league dump contains no losses at all, so a win rate computed from one
would be 100% by construction. Every event is tagged at ingest time, not
query time, so that ``v_meta_winrate`` filters Tier C out in the view
definition, where no future query can accidentally include it
(``migrations/047_meta_event_tier_rank.sql``).
"""

from __future__ import annotations

from typing import Any

from sensei_top.i18n import N_, _

# A 64-player swiss is six or more rounds with a field wide enough to mean
# something — a judgement, not a value tuned to the real events this module
# was verified against.
MIN_LARGE_PAPER_PLAYERS = 64

# The only source whose standings are never a full swiss (MTGO publishes a
# challenge's top 32 standings, not the field that produced it) — everything
# else selected by metagame/source.py's SOURCES, plus TopDeck, is tabletop.
ONLINE_SOURCES = frozenset({"MTGO"})

# Rank order: the letters ARE the ranking, not an alphabetic accident.
TIERS = ("A", "B", "C", "D")

# The tiers with rounds at all — Tier C never populates meta_round_match —
# in the order a single quoted matchup number is walked.
MATCHUP_TIERS = ("A", "B", "D")

# What each tier's events are, for a sentence about them. English here, for
# a prompt (which is English, i18n.py trap 1); ``tier_words`` for a sentence
# a page shows.
TIER_WORDS = {
    "A": N_("paper tournaments of 64 or more players"),
    "B": N_("MTGO challenges"),
    "C": N_("MTGO leagues"),
    "D": N_("paper tournaments under 64 players"),
}


def tier_words(tier: str) -> str:
    """``TIER_WORDS[tier]`` in the reader's language."""
    return _(TIER_WORDS[tier])


def classify_tier(cache_item: dict[str, Any], source: str) -> str:
    """'A' large paper, 'B' MTGO challenge, 'C' MTGO league, 'D' small
    paper — standings presence and count decide it, with ``source``
    consulted only to tell an MTGO event with standings (always B, since
    MTGO never publishes a full swiss) from a paper one (A or D by size).
    Any source outside ``ONLINE_SOURCES`` counts as tabletop, so a new
    online source must be added there or its events land in A or D.
    """
    standings = cache_item.get("Standings") or []
    if not standings:
        return "C"
    if source in ONLINE_SOURCES:
        return "B"
    return "A" if len(standings) >= MIN_LARGE_PAPER_PLAYERS else "D"
