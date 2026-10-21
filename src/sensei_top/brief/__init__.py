"""The live matchup brief: what to play around against one opponent
archetype, and a game-2 board plan, for one of the player's decks — the
useful half of the deck guide's matchup content, reachable while a game is
actually on the clock.

**A brief is an authored artifact with its own provenance, not a
derivation,** so unlike the evidence bundles of ``guide/`` and ``review/``
it is persisted (``matchup_brief``): ``brief.store.Brief`` is stamped with
the 75 it was written for (``list_hash``) and the corpus snapshot it
reasoned from (``corpus_commit``), and both are checked before it is read
back as current. See docs/brief.md, "Why a brief is persisted".

**A brief is a function of two decklists and the field, never of a game.**
No board state, no turn, no life total, no match id ever appears in a
prompt this package builds — ``brief/narrative.py``'s module docstring, and
``tests/test_brief_context.py`` pins it. That is what makes it cacheable per
``(deck, archetype)`` rather than per match.

Modules, in dependency order:

* ``store.py`` — the cache, and the only module here that writes.
* ``narrative.py`` — the prompt to hand an assistant, and the JSON shape
  an answer must come back in.
* ``importer.py`` — parse, validate and store an authored brief. There is
  no background watcher and no generate button: a brief arrives by import
  or paste, or from a deck guide's narrative (``from_guide.py``). See
  docs/brief.md, "Prompt out, answer in — this feature has no generate button".
* ``coverage.py`` — which of the field this deck's stored briefs cover.
* ``from_guide.py`` — backfills the same cache from a deck guide's own
  matchup plans, for free.
"""

from __future__ import annotations

from sensei_top.brief.store import (
    Brief,
    PlayAround,
    Staple,
    briefs_for_deck,
    corpus_commit,
    read_brief,
)

__all__ = [
    "Brief",
    "PlayAround",
    "Staple",
    "briefs_for_deck",
    "corpus_commit",
    "read_brief",
]
