"""The deck guide: one deck's own play evidence, its current 75 against the
field's tournament consensus, and the field itself around any detected
format reset, regenerated from every game the player has played and the
freshest corpus. See docs/guide.md, "The modules, in dependency order".

Built on ``review/`` (``build_match_report``, ``find_leaks``,
``build_consensus``) rather than duplicating it, and follows the same two
rules that package states for itself:

1. **It never imports from ``reader/`` and never reads the append-only log
   table the reader owns.** Every module here is a pure function of the
   projected database, or (``narrative.py``, ``markdown.py``) of an
   already-built ``DeckGuide``. (AGENTS.md non-negotiable #1.)
2. **The evidence bundle is never persisted.** A deck guide depends on
   the tournament corpus and the card database, which change independently
   of any projector rebuild, and reads a match's deck through
   ``v_match_deck``, which the user's MTGO pick changes with no rebuild at
   all — the same reasoning ``review/__init__.py`` gives for why a stored
   report would read wrong, not merely stale. The authored narratives are
   persisted: ``deck_narrative`` (``authored.py``) and ``rcq_guide``
   (``rcq_authored.py``).
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
