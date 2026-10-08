"""The deck guide: one deck's own play evidence, its current 75 against the
field's tournament consensus, and the field itself around any detected
format reset — a document once written by hand for one deck, now
regenerated from every game the player has played and the freshest corpus.
See ``docs/guide.md`` for the full design.

Built on ``review/`` (``build_match_report``, ``find_leaks``,
``build_consensus``) rather than duplicating it, and follows the same two
rules that package states for itself:

1. **It never imports from ``reader/`` and never reads the append-only log
   table the reader owns.** Every module here is a pure function of the
   projected database, or (``narrative.py``, ``markdown.py``) of an
   already-built ``DeckGuide``. (AGENTS.md non-negotiable #1.)
2. **Nothing here is ever persisted.** A deck guide depends on the
   tournament corpus, the card database and the player's own current
   decklist, all three of which change independently of any projector
   rebuild — the same reasoning ``review/__init__.py`` gives for why a
   stored report would read wrong, not merely stale.
"""

from sensei_top.guide.bundle import DeckGuide, Provenance, build_deck_guide
from sensei_top.guide.deck import DeckIdentity, list_identities, resolve

__all__ = [
    "DeckGuide",
    "DeckIdentity",
    "Provenance",
    "build_deck_guide",
    "list_identities",
    "resolve",
]
