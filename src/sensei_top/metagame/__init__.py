"""The field's own numbers, from real MTGO and paper tournament results —
never Arena, which publishes no event results at all.

``source`` downloads and stores the corpus; ``dedup`` marks the republished
twins the mirror sometimes ships under a second path so they stop being
counted twice; ``tiers`` decides what each event is licensed to say;
``classify_meta`` names each stored decklist's archetype, reusing
``archetypes.classify`` in its ``complete=True`` mode so the personal and
field sides of a matchup share one vocabulary. This package imports neither
``reader`` nor ``projector`` and knows nothing about ``Player.log``.
"""

from sensei_top.metagame.classify_meta import classify_meta_decks
from sensei_top.metagame.dedup import mark_duplicate_events
from sensei_top.metagame.matchup import RankedMatchup, ranked_field_matchup
from sensei_top.metagame.mtgo_site import refresh_mtgo_site
from sensei_top.metagame.source import (
    SOURCES,
    cache_age_seconds,
    refresh_metagame,
)
from sensei_top.metagame.tiers import TIERS, classify_tier
from sensei_top.metagame.topdeck import refresh_topdeck

__all__ = [
    "SOURCES",
    "TIERS",
    "RankedMatchup",
    "cache_age_seconds",
    "classify_meta_decks",
    "classify_tier",
    "mark_duplicate_events",
    "ranked_field_matchup",
    "refresh_metagame",
    "refresh_mtgo_site",
    "refresh_topdeck",
]
