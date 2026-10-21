"""The field's own numbers, from real MTGO and paper tournament results —
never Arena, which publishes no event results at all. See docs/metagame.md,
"The evidence tiers".

``source`` (fbettega's cache), ``mtgo_site`` and ``topdeck`` fetch and store
the corpus; ``dedup`` marks the twins the mirror ships under a second path;
``tiers`` decides what each event is licensed to say; ``classify_meta``
names each stored decklist's archetype; ``auto`` is one tick of the
server's corpus-refresh loop. This package imports neither ``reader`` nor
``projector`` and knows nothing about ``Player.log``.
"""

from sensei_top.metagame.auto import (
    RefreshState,
    followed_formats,
    reclassify_corpus,
    refresh_corpus,
)
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
    "RefreshState",
    "cache_age_seconds",
    "classify_meta_decks",
    "classify_tier",
    "followed_formats",
    "mark_duplicate_events",
    "ranked_field_matchup",
    "reclassify_corpus",
    "refresh_corpus",
    "refresh_metagame",
    "refresh_mtgo_site",
    "refresh_topdeck",
]
