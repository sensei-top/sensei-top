"""The live matchup brief: what to play around against one opponent
archetype, and a game-2 board plan, for one of the player's decks — the
useful half of ``guide/``'s §6 matchup content, reachable while a game is
actually on the clock.

``guide/__init__.py`` states its own rule that the evidence bundle in that
package is never persisted, because a deck guide is a *derivation* of the current
database and a stored derivation could silently disagree with a rebuilt
projection. **A brief is different: it is an authored artifact with its own
provenance, not a derivation.** ``brief.store.Brief`` is stamped with the
75 it was written for (``list_hash``) and the corpus snapshot it reasoned
from (``corpus_commit``); a stored brief cannot go silently wrong the way a
stored guide could, because the two things that would make it wrong are
recorded beside it and checked before it is ever read back as current.
That is what licenses this package — and no other computed package in this
project — to persist its own output.

The other property this package depends on: **a brief is a function of two
decklists and the field, never of a game.** No board state, no turn, no
life total, no match id ever appears in a prompt this package builds — see
``brief/narrative.py``'s module docstring for the full argument and
``tests/test_brief_context.py`` for the test that pins it. That is what
makes the whole design work: it is cacheable per ``(deck, archetype)``
rather than per match, so most matches cost nothing at all, and one written brief keeps
paying off for as long as the deck and the archetype both stand still.

Modules, in dependency order:

* ``store.py`` — the cache, and the only module here that writes.
* ``narrative.py`` — the prompt to hand an assistant, and the JSON shape
  an answer must come back in.
* ``importer.py`` — parse, validate and store an authored brief. There is
  no background watcher, and unlike the match report and the deck guide
  (``docs/llm.md``), no generate button either: a brief arrives only by
  import, because generating a full guide already fills this cache for free
  (``from_guide.py`` below) — a standalone brief is for filling a gap the
  guide missed, not a second thing to press a button for.
* ``from_guide.py`` — backfills the same cache from a generated deck
  guide's own matchup plans, for free.
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
