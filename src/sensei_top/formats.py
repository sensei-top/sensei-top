"""The seven constructed formats, and the facts about them that more than one
module needs.

One home, so every module that needs them shares a tuple instead of keeping
a copy. It imports nothing from ``reader/``, ``projector/`` or
``archetypes/``, so any of them may import it.

``FORMATS`` is MTGO's spelling. ``SCRYFALL_KEYS`` maps each to the key in
Scryfall's ``legalities`` object. ``BROADER`` is the inclusion order: a
partial order, not a line. Standard, Pioneer, Modern, Legacy and Vintage nest;
Premodern sits inside Legacy; Pauper sits inside Vintage only. Inference over
it (the single narrowest fitting format) is not done here: see
docs/opponent-deck.md, "A match's format".
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

FORMATS: tuple[str, ...] = (
    "Standard",
    "Pioneer",
    "Modern",
    "Pauper",
    "Legacy",
    "Vintage",
    "Premodern",
)

SCRYFALL_KEYS: Mapping[str, str] = MappingProxyType({fmt: fmt.lower() for fmt in FORMATS})

# The immediate supersets of each format: every card legal in the key is
# legal (or at least not out of the pool) in each format listed.
_DIRECT_BROADER: dict[str, tuple[str, ...]] = {
    "Standard": ("Pioneer",),
    "Pioneer": ("Modern",),
    "Modern": ("Legacy",),
    "Legacy": ("Vintage",),
    "Vintage": (),
    "Premodern": ("Legacy",),
    "Pauper": ("Vintage",),
}


def _closure() -> dict[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}

    def broader(fmt: str) -> frozenset[str]:
        if fmt not in out:
            found: set[str] = set()
            for parent in _DIRECT_BROADER[fmt]:
                found.add(parent)
                found |= broader(parent)
            out[fmt] = frozenset(found)
        return out[fmt]

    for fmt in FORMATS:
        broader(fmt)
    return out


# Every format strictly broader than the key, transitively.
BROADER: Mapping[str, frozenset[str]] = MappingProxyType(_closure())


def is_within(narrow: str, broad: str) -> bool:
    """True when ``narrow`` is strictly inside ``broad`` in the inclusion order."""
    return broad in BROADER[narrow]


# Arena's format strings, exactly. `StandardBrawl` contains `Standard` and is a
# different format entirely, which is why this is a lookup and never a
# substring test.
_ARENA_FORMATS = {"standard": "Standard"}
_NOT_CONSTRUCTED_STANDARD = (
    "historic", "alchemy", "brawl", "timeless", "explorer", "pioneer", "limited", "draft", "sealed",
    "precon",
)


def arena_format(deck_format: str | None, event_id: str | None) -> str | None:
    """Which format an Arena match was, or None when we should not guess."""
    if deck_format:
        text = deck_format.lower().removeprefix("traditional")
        if text in _ARENA_FORMATS:
            return _ARENA_FORMATS[text]
        if any(word in text for word in _NOT_CONSTRUCTED_STANDARD):
            return None
    if event_id:
        text = event_id.lower()
        if any(word in text for word in _NOT_CONSTRUCTED_STANDARD):
            return None
        if "ladder" in text or "standard" in text:
            # Arena's unqualified ranked ladder is Standard.
            return "Standard"
    return None


def deck_format_name(deck_format: str | None) -> str | None:
    """A ``decks.format`` value as one of ``FORMATS``, or None.

    Arena's own spelling maps (``TraditionalStandard`` is Standard); the MTGO
    deck store's names are already the seven. Draft, and anything else that is
    not one of the seven, is None.
    """
    if not deck_format:
        return None
    text = deck_format.removeprefix("Traditional")
    return text if text in FORMATS else None
