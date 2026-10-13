"""Which claims one tournament event actually supports, and in what order
the dashboard, the brief and the match report reach for them.

``fbettega/MTG_decklistcache`` mixes three shapes under one ``CacheItem``
schema. Verified against real files on 2026-08-18 (see the input findings
document this package implements):

* A Melee swiss event (``summer-wind-championship-standard-447528``) carried
  9 full rounds, 132 matches, and complete standings for 40 players.
* An MTGO challenge (``modern-challenge-64-2026-08-1712851686``) carried full
  standings but only 3 rounds — the published top-8 bracket, not the swiss
  that produced it.
* An MTGO league (``standard-league-2026-08-1711015``) carried zero standings
  and zero rounds; every deck's ``Result`` was literally ``"5-0"``.

That last shape is the load-bearing one: a league dump contains no losses at
all, so a win rate computed from it would be 100% by construction, not an
approximation. Tagging every event at ingest time — not query time — is what
lets ``v_meta_winrate`` filter Tier C out in the view definition, where no
future query can accidentally include it (see
``migrations/047_meta_event_tier_rank.sql``).

The ranking is the user's call, made on 2026-09-29: a real tabletop event of
tournament size first, then the online events, then everything smaller.
``TIERS`` is in that order — the letters *are* the rank, not an alphabetic
accident:

* **A** — a paper (Melee or TopDeck) event with 64 or more standings rows: a
  swiss wide enough to mean something.
* **B** — an MTGO challenge: any MTGO event with standings at all. MTGO never
  publishes a challenge's full swiss, only its top-32 bracket, so player
  count can't separate a small challenge from a large one the way it can on
  paper — every MTGO event with standings ranks the same.
* **C** — an MTGO league: no standings published at all. The most
  conservative tier, for a file that carries no record to count.
* **D** — a paper event under 64 standings rows: a genuine swiss, just a
  small one.

Round count no longer decides anything: the old rule (5+ rounds is a swiss,
fewer is a bracket) couldn't tell a twelve-player store championship from an
MTGO challenge by shape alone, and a small paper swiss is not a better read
on the format than a challenge just because its rounds are complete. Size
does the separating for paper now, so ``source`` is consulted for exactly one
thing: whether an event with standings is MTGO (B) or paper (A or D). Melee
and TopDeck are both treated as paper; Melee hosts a handful of online events
that can't be told apart from its paper ones, and at their sizes they land in
D anyway.
"""

from __future__ import annotations

from typing import Any

from sensei_top.i18n import N_, _

# A 64-player swiss is six or more rounds with a field wide enough to mean
# something (the user's own reasoning, 2026-09-29) — not a value tuned to
# either real event this module was verified against.
MIN_LARGE_PAPER_PLAYERS = 64

# The only source whose standings are never a full swiss (MTGO publishes a
# challenge's top-32 bracket, not the field that produced it) — everything
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
