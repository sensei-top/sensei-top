"""Naming the opponent's deck from the cards they revealed.

``source`` downloads the definitions; ``classify`` matches what a match showed
us against them. Split because only one of the two touches the network.
"""

from sensei_top.archetypes.classify import (
    Candidate,
    SignatureCard,
    classify_matches,
    color_label,
    format_key,
    match_format_reasons,
    match_formats,
    rank_candidates,
    standard_opponent_source_breakdown,
)
from sensei_top.archetypes.corpus import (
    CorpusPrior,
    build_prior,
    read_corpus,
)
from sensei_top.archetypes.source import (
    ARCHIVE_URL,
    cache_age_seconds,
    refresh_archetypes,
)

__all__ = [
    "ARCHIVE_URL",
    "Candidate",
    "CorpusPrior",
    "SignatureCard",
    "build_prior",
    "cache_age_seconds",
    "classify_matches",
    "color_label",
    "format_key",
    "match_format_reasons",
    "match_formats",
    "rank_candidates",
    "read_corpus",
    "refresh_archetypes",
    "standard_opponent_source_breakdown",
]
