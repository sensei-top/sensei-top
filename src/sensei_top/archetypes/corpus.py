"""A second evidence source for naming the opponent's deck: what real
tournament decklists actually look like, from the metagame corpus
(``metagame/``) — the same 10,000-plus classified decks
``review/consensus.py`` aggregates into a card list.

``classify.py``'s rule engine (``choose()``) proves an archetype from a
handful of *specific* cards a definition names. That is exact when a
definition exists and lists the right cards, and it is silent otherwise: a
brand-new set's archetypes score zero on every rule until someone writes a
definition for them, and even a well-defined archetype's fit saturates fast
(``_fit_score``'s own docstring) because it counts *conditions*, not cards —
a fifth unlisted signature card revealed late in a match can't move a verdict
that a rule definition already considers "proved".

This module is deliberately a different kind of evidence, not a replacement:
a naive-Bayes score over *every* card the corpus has ever seen an archetype
run, weighted by how much more often that archetype runs it than the field
as a whole. It strengthens additively with every card revealed (log-odds
sum), it needs no hand-written definition — an archetype only has to appear
in enough classified corpus decks — and ``classify.py`` combines its verdict
with the rule engine's by confidence rank rather than letting either replace
the other outright (see that module's ``classify_matches``).

The governing asymmetry from ``classify.py`` carries over unchanged: a card
never revealed this match contributes nothing for or against any archetype.
``read_corpus`` only ever sums over cards actually seen; an archetype that
happens not to run a card we saw is simply not credited for it, never
penalized — there is no ``DoesNotContain`` here, because a corpus deck's
*absence* of a card is not the kind of fact this module observes (it counts
presence across decks, not one deck's true negative).

Ban-awareness is inherited, not reimplemented: ``guide/window.py`` already
detects a format reset from the corpus itself (a banned card's last
appearance) and can say which archetypes did not survive it
(``structural_change``). ``build_prior`` imports it at function scope,
never at module scope — ``guide/bundle.py`` imports ``review/``, which
imports ``archetypes.classify`` at module scope
(``review/consensus.py``'s ``from sensei_top.archetypes.classify import
normalize``), so importing ``guide`` at the top of this module would risk a
cycle the moment something imports ``archetypes`` before ``guide`` finishes
initializing. Verified with a cold ``python -c "import sensei_top.archetypes"``.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sensei_top.archetypes.classify import normalize

log = logging.getLogger(__name__)

# Corpus archetypes are classified with the same rule engine
# (metagame/classify_meta.py) but only ever for Standard — see that module's
# `by_format = {"Standard": ...}` restriction — so this is the one format
# the corpus can ever have an opinion about. Hardcoded rather than a
# parameter: nothing here is meant to generalise past what classify_meta_decks
# actually produces.
_FORMAT = "Standard"

# An archetype's corpus share has to rest on a real sample before its card
# frequencies mean anything — 7 decks of "Mono-Red" is still just 7 decks.
# Tunable, not derived, like every other floor in this package.
MIN_CORPUS_DECKS = 8


def _canon_card(name: str) -> str:
    """One stable dictionary key for a card, regardless of which of its
    legitimate written forms the corpus or Arena happens to use.

    ``normalize()`` already maps a split/adventure/DFC card's front face, its
    combined name and upstream's alternate separator all to the same set of
    forms (see that function's own docstring and
    ``review/consensus.py::_card_rows_by_name`` for the trap this avoids: a
    corpus decklist naming an adventure card by its front face alone, next
    to Arena's own combined name for the same card). The shortest form in
    that set is deterministic and, for every case this project has seen, is
    the front-face name common to both spellings — which is exactly what
    lets a corpus key and a `_match_seen_forms()` form meet as the same
    string without ever comparing raw text.
    """
    return min(normalize(name))


@dataclass(frozen=True, slots=True)
class CorpusPrior:
    """A snapshot of the Standard corpus's own archetype shares and card
    frequencies, built once per request/run and reused — rebuilding it per
    match would rescan the whole corpus for every opponent.

    All dictionaries are keyed on the *canonical* card form
    (``_canon_card``), and ``decks_by_key``/``card_counts`` only ever contain
    archetypes at or above ``MIN_CORPUS_DECKS`` — those are the only
    archetypes this prior is willing to name. ``global_counts`` and
    ``total_decks``, though, are computed over the *whole* accepted corpus
    (every non-gone, non-empty decklist) regardless of that floor: diluting
    the baseline card-frequency estimate by dropping thin archetypes would
    bias every score, not just the ones for archetypes near the floor.
    """

    total_decks: int
    global_counts: dict[str, int]
    decks_by_key: dict[str, int]
    card_counts: dict[str, dict[str, int]]
    labels: dict[str, str] = field(default_factory=dict)   # archetype_key -> archetype_name
    kinds: dict[str, str] = field(default_factory=dict)    # archetype_key -> 'archetype'/'fallback'
    display_names: dict[str, str] = field(default_factory=dict)  # canon -> a real spelling
    built_at: str = ""


def build_prior(conn: sqlite3.Connection) -> CorpusPrior | None:
    """Build a fresh prior from ``meta_deck``/``meta_deck_archetype``, or
    ``None`` when there isn't enough corpus to say anything — no classified
    Standard decks at all, or nothing clears ``MIN_CORPUS_DECKS`` for any
    single archetype. Callers must treat ``None`` exactly like "no corpus
    evidence" rather than raising: this is a downloaded, best-effort corpus
    (AGENTS.md rule 5), and a machine that has never run ``sensei-top
    meta`` has every right to keep working without it.
    """
    # Function-scoped import: see this module's own docstring for the cycle
    # this avoids.
    from sensei_top.guide.window import format_resets, structural_change

    # ORDER BY makes deck iteration order reproducible across runs — see the
    # comment further down on why order matters here at all (float addition
    # is not associative, and `labels`/`kinds`/`display_names` keep the
    # first row seen for a key).
    rows = conn.execute(
        """
        SELECT d.mainboard_json, a.archetype_key, a.archetype_name, a.method
          FROM meta_deck d
          JOIN meta_deck_archetype a ON a.event_id = d.event_id AND a.deck_ord = d.deck_ord
          JOIN meta_event e ON e.event_id = d.event_id
         WHERE e.format = ?
         ORDER BY d.event_id, d.deck_ord
        """,
        (_FORMAT,),
    ).fetchall()
    if not rows:
        return None

    # structural_change is keyed by archetype_name, not archetype_key (a
    # documented gotcha of guide/window.py) — resolved here, not carried
    # downstream, so nothing else in this module has to remember it.
    resets = format_resets(conn, fmt=_FORMAT)
    gone_names: set[str] = set()
    if resets:
        changes = structural_change(conn, resets[0], fmt=_FORMAT)
        gone_names = {name for name, change in changes.items() if change.verdict == "gone"}

    total_decks = 0
    global_counts: dict[str, int] = {}
    decks_by_key_all: dict[str, int] = {}
    card_counts_all: dict[str, dict[str, int]] = {}
    labels: dict[str, str] = {}
    kinds: dict[str, str] = {}
    display_names: dict[str, str] = {}

    for row in rows:
        if row["archetype_name"] in gone_names:
            continue
        try:
            mainboard = json.loads(row["mainboard_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        raw_names = {
            entry.get("name")
            for entry in mainboard
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        }
        if not raw_names:
            continue

        total_decks += 1
        key = row["archetype_key"]
        labels.setdefault(key, row["archetype_name"])
        kinds.setdefault(key, row["method"])
        decks_by_key_all[key] = decks_by_key_all.get(key, 0) + 1

        # sorted(), not the raw set: Python's string hash is randomized per
        # process (PYTHONHASHSEED), so a set's own iteration order — and
        # therefore the order display_names.setdefault(), global_counts and
        # card_counts accumulate in — would otherwise vary between two runs
        # over the exact same corpus. Float addition below is not
        # associative, so that would let a near-tie score in read_corpus
        # flip between runs on no real change to the data.
        canon_this_deck: set[str] = set()
        for name in sorted(raw_names):
            canon = _canon_card(name)
            canon_this_deck.add(canon)
            display_names.setdefault(canon, name)
        for canon in sorted(canon_this_deck):
            global_counts[canon] = global_counts.get(canon, 0) + 1
        bucket = card_counts_all.setdefault(key, {})
        for canon in sorted(canon_this_deck):
            bucket[canon] = bucket.get(canon, 0) + 1

    if total_decks == 0:
        return None

    decks_by_key = {key: n for key, n in decks_by_key_all.items() if n >= MIN_CORPUS_DECKS}
    if not decks_by_key:
        return None
    card_counts = {key: card_counts_all[key] for key in decks_by_key}

    return CorpusPrior(
        total_decks=total_decks,
        global_counts=global_counts,
        decks_by_key=decks_by_key,
        card_counts=card_counts,
        labels=labels,
        kinds=kinds,
        display_names=display_names,
        built_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def read_corpus(prior: CorpusPrior, seen_names: frozenset[str]) -> list[tuple[str, float]]:
    """Score every corpus-nameable archetype against what this match has
    revealed, best first: ``log P(archetype) + sum(log(P(card|archetype) /
    P(card)))`` over every card in ``seen_names`` that archetype's own corpus
    decks are on record as running.

    Laplace-smoothed (``+0.5``/``+1``) so a card no deck of an archetype has
    ever run does not zero out its odds outright — a corpus of a few dozen
    decks has not seen everything a real 60-card list could hold. A card
    never revealed this match — the overwhelming majority of any deck — never
    enters the sum at all: this mirrors ``classify.py``'s own governing
    asymmetry (absence proves nothing) applied to presence-only corpus data,
    where there is no ``DoesNotContain`` to make an absence meaningful in the
    first place.

    Ties (and the empty case) resolve deterministically by archetype key, the
    same discipline ``_rank_archetypes`` uses, so a repeat run over unchanged
    inputs always orders identically.

    Summed with ``math.fsum`` rather than a running ``+=``: float addition is
    not associative, and ``prior.card_counts[key]``'s own dict order follows
    whatever order ``build_prior`` happened to insert its cards in — fixed
    within one build (that function sorts for exactly this reason), but nothing
    stops two *different* callers from handing this a prior built in another
    order. ``fsum`` is exactly rounded regardless of summation order, so the
    score this returns depends only on the term values, never on the order
    they were collected in.
    """
    scored: list[tuple[str, float]] = []
    for key, n_key in prior.decks_by_key.items():
        terms = [math.log(n_key / prior.total_decks)]
        for canon, n_key_card in prior.card_counts[key].items():
            if canon not in seen_names:
                continue
            n_card = prior.global_counts.get(canon, 0)
            p_given_key = (n_key_card + 0.5) / (n_key + 1)
            p_overall = (n_card + 0.5) / (prior.total_decks + 1)
            terms.append(math.log(p_given_key / p_overall))
        scored.append((key, math.fsum(terms)))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return scored


def matched_cards(prior: CorpusPrior, key: str, seen_names: frozenset[str]) -> list[str]:
    """Which of ``key``'s own corpus cards this match actually revealed, as
    real card names (``prior.display_names``) rather than the canonical keys
    ``read_corpus`` scores over — for ``evidence_json`` and any caller that
    wants to say *why* a corpus verdict named what it named, not just the
    number."""
    if key not in prior.card_counts:
        return []
    return sorted(
        prior.display_names.get(canon, canon)
        for canon in prior.card_counts[key]
        if canon in seen_names
    )
