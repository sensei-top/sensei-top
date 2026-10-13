"""Naming the opponent's deck from the cards they revealed.

``source`` downloads the definitions; ``classify`` matches what a match showed
us against them. Split because only one of the two touches the network.
"""

from sensei_top.archetypes.classify import (
    FORMAT_REASONS,
    Candidate,
    FormatInference,
    SignatureCard,
    classify_matches,
    color_label,
    infer_formats,
    narrowest_format,
    opponent_source_breakdown,
    rank_candidates,
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
    "FORMAT_REASONS",
    "Candidate",
    "CorpusPrior",
    "FormatInference",
    "SignatureCard",
    "build_prior",
    "cache_age_seconds",
    "classify_matches",
    "color_label",
    "infer_formats",
    "narrowest_format",
    "opponent_source_breakdown",
    "rank_candidates",
    "read_corpus",
    "refresh_archetypes",
]
