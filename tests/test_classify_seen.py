"""``classify_seen`` — the per-match rule-engine/corpus/tie-break decision
pulled out of ``classify_matches``'s own loop (S3, sideboard-intermission
plan) — and the two "compute this at request time" companions it exists
for: ``rank_candidates(seen_names=...)`` and ``live_opponent_colors``. Both
let a live read (S4's break read, ``table/intermission.py``) name the
opponent from a name set built at request time — the live replay's revealed
zones unioned with ``card_events`` — without touching ``opponent_archetype``
or waiting for the next ``project()``.

Rule-engine scenarios reuse ``test_classify.py``'s own synthetic-``Definition``
style (that file's own docstring: "Definitions are synthetic so each rule is
isolated"). The corpus-branch scenarios build a ``CorpusPrior`` directly
rather than through ``corpus.build_prior(conn)`` — ``test_corpus_naming.py``
already covers ``build_prior`` itself and its odds arithmetic is reused
here unchanged (Laplace-smoothed naive-Bayes log-odds, ``corpus.py``'s own
docstring); this file's job is only to prove ``classify_seen`` wires that
score into the same tie-broken decision ``classify_matches`` used to make
inline, not to re-derive the corpus math.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.archetypes.classify import (
    Definition,
    SeenVerdict,
    _seen_forms,
    classify_seen,
    live_opponent_colors,
    rank_candidates,
)
from sensei_top.archetypes.corpus import CorpusPrior, _canon_card
from sensei_top.db import open_database


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "seen.db")
    yield c
    c.close()


def seen(*names: str):
    return _seen_forms(names)


def condition(type_: str, *cards: str) -> dict:
    return {"Type": type_, "Cards": list(cards)}


def archetype(key: str, name: str, *conditions: dict, color: bool = False) -> Definition:
    return Definition(key=key, name=name, kind="archetype", include_color=color,
                      conditions=list(conditions))


def defs(fmt: str, *, archetypes: list[Definition] = ()) -> dict:
    return {fmt: {"archetype": list(archetypes), "fallback": []}}


# --- classify_seen: rule engine only, no corpus prior ------------------------


def test_classify_seen_returns_none_with_no_names():
    """No names to classify is the same 'nothing to say' outcome
    classify_matches's own unclassified count treats an empty seen set as —
    classify_seen just doesn't count it, that stays the caller's job."""
    assert classify_seen(
        [], "", 0, fmt="Standard", definitions=defs("Standard"), colors_by_name={}, prior=None,
    ) is None


def test_classify_seen_degrades_to_none_for_a_format_with_no_definitions_loaded():
    """classify_matches never calls this for an fmt absent from its own
    `definitions` (its pre-loop skipped_format check runs first), but a
    direct caller (S4's live read) is not guaranteed to check that first —
    a missing format key must degrade to 'nothing to say', not a KeyError."""
    assert classify_seen(
        ["Anything"], "", 1, fmt="Historic", definitions={}, colors_by_name={}, prior=None,
    ) is None


def test_classify_seen_names_a_clearly_proved_archetype():
    """Six independent single-card conditions, all met: proof=1.0,
    support=1-0.5**6 (~0.984), colour=1.0 (colors_by_name empty, so nothing
    is checked against it) — the exact scenario
    test_corpus_naming.py::test_a_high_rule_verdict_is_not_displaced_by_a_medium_corpus_read
    hand-derives as 'high' (fit clears _HIGH_FIT, margin is inf with no
    rival, cards_seen=6 clears _HIGH_CARDS_SEEN); reused here to prove
    classify_seen reaches the identical verdict through the rule-only path.
    """
    cards = [f"High Card {i}" for i in range(1, 7)]
    high_arch = archetype(
        "HighArch", "High Deck", *[condition("InMainboard", c) for c in cards]
    )
    verdict = classify_seen(
        cards, "", 6,
        fmt="Standard", definitions=defs("Standard", archetypes=[high_arch]),
        colors_by_name={}, prior=None,
    )
    assert verdict == SeenVerdict(
        key="HighArch", label="High Deck", name="High Deck", confidence="high",
        method="archetype", evidence=json.dumps(sorted(cards)), met=6, unknown=0,
    )


def test_classify_seen_leaves_a_weak_lead_unclassified():
    """One condition met, one never seen: proof=0.5, support=0.5, fit=0.25 —
    below MIN_ARCHETYPE_FIT (0.20)? No: 0.25 clears MIN_ARCHETYPE_FIT but the
    margin gate still needs a real rival to beat, and with none present the
    margin is inf so this *would* be named — the point of this case is the
    opposite one: with a second, differently-labelled definition scoring the
    same fit, choose() reports a genuine tie and refuses to name either,
    exactly test_classify.py::test_a_full_tie_is_left_unclear_rather_than_broken_arbitrarily's
    own scenario, driven through classify_seen instead of choose() directly.
    """
    first = archetype("Alpha", "Alpha", condition("InMainboard", "Shared"))
    second = archetype("Beta", "Beta", condition("InMainboard", "Shared"))
    verdict = classify_seen(
        ["Shared"], "", 10,
        fmt="Standard", definitions=defs("Standard", archetypes=[first, second]),
        colors_by_name={}, prior=None,
    )
    assert verdict is None


# --- classify_seen: the corpus source and the tie rule ------------------------


def _single_archetype_prior(key: str, label: str, cards: list[str]) -> CorpusPrior:
    """A CorpusPrior naming exactly one archetype, running exactly `cards`.
    With only one archetype in `decks_by_key`, `read_corpus`'s own ranked
    list has a single element, so `second_score` is always None and the
    odds ratio is always infinite (`corpus.py`'s own documented arithmetic)
    regardless of the numeric scores below — what varies between the two
    scenarios that use this is only `len(cards)` against
    `_CORPUS_MEDIUM_CARDS`/`_CORPUS_HIGH_CARDS`.
    """
    canon = {c: _canon_card(c) for c in cards}
    return CorpusPrior(
        total_decks=8,
        global_counts={form: 8 for form in canon.values()},
        decks_by_key={key: 8},
        card_counts={key: {form: 8 for form in canon.values()}},
        labels={key: label},
        kinds={key: "archetype"},
        display_names={form: name for name, form in canon.items()},
    )


def test_classify_seen_lets_a_stronger_corpus_read_displace_a_weak_rule_verdict():
    """One rule condition met (Card X) and one never revealed (Card Q):
    fit=0.25, below _MEDIUM_FIT (0.30) — 'low' regardless of margin, the
    same arithmetic test_corpus_naming.py's own
    test_a_low_rule_verdict_is_displaced_by_a_medium_corpus_read documents.
    The corpus's only archetype runs all 4 revealed cards: matched_cards=4
    clears CORPUS_MIN_CARDS and _CORPUS_MEDIUM_CARDS, infinite odds (no
    rival in a one-archetype prior) clears _CORPUS_MEDIUM_ODDS but 4 is
    short of _CORPUS_HIGH_CARDS (8) — 'medium', rank 2, which beats the
    rule's rank 1 ('low')."""
    cards = ["Card X", "Corpus One", "Corpus Two", "Corpus Three"]
    low_arch = archetype(
        "LowArch", "Low Deck",
        condition("InMainboard", "Card X"), condition("InMainboard", "Card Q"),
    )
    prior = _single_archetype_prior("CorpusLow", "Corpus Low", cards)

    verdict = classify_seen(
        cards, "", 4,
        fmt="Standard", definitions=defs("Standard", archetypes=[low_arch]),
        colors_by_name={}, prior=prior,
    )
    assert verdict == SeenVerdict(
        key="CorpusLow", label="Colorless Corpus Low", name="Corpus Low",
        confidence="medium", method="corpus",
        evidence=json.dumps({"matched_cards": sorted(cards), "odds": None}),
        met=4, unknown=0,
    )


def test_classify_seen_keeps_the_rule_verdict_on_an_exact_confidence_tie():
    """Same 'low' rule verdict as above, but the corpus read is *also* only
    'low' this time — 3 matched cards clears CORPUS_MIN_CARDS (3) and
    infinite odds clears CORPUS_MIN_ODDS, but 3 is short of
    _CORPUS_MEDIUM_CARDS (4), so it never reaches 'medium'. Rank 1 vs rank
    1 is an exact tie, and classify_matches's own docstring says the rule
    engine wins it — 'the more legible answer of the two when both agree'.
    """
    cards = ["Card X", "Corpus One", "Corpus Two"]
    low_arch = archetype(
        "LowArch2", "Low Deck Two",
        condition("InMainboard", "Card X"), condition("InMainboard", "Card Q"),
    )
    prior = _single_archetype_prior("CorpusLowTie", "Corpus Low Tie", cards)

    verdict = classify_seen(
        cards, "", 3,
        fmt="Standard", definitions=defs("Standard", archetypes=[low_arch]),
        colors_by_name={}, prior=prior,
    )
    assert verdict is not None
    assert (verdict.method, verdict.key, verdict.confidence) == ("archetype", "LowArch2", "low")


# --- rank_candidates(seen_names=...) ------------------------------------------
# Built directly against the projected schema (matches/decks/card_events/
# cards/archetypes), the same precedent test_corpus_naming.py's own
# "classify_matches: combining the two sources" section describes: every
# card and definition below is invented to isolate seen_names's contract,
# not read off a real match.


def _insert_deck(conn, deck_id, fmt="Standard"):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, 'Test Deck', ?, '[]', 't', 't')",
        (deck_id, fmt),
    )


def _insert_match(conn, match_id, deck_id, event_id="Traditional_Ladder"):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat) "
        "VALUES (?, ?, ?, 1, 2)",
        (match_id, event_id, deck_id),
    )


def _insert_game(conn, match_id, game_number=1):
    """card_events carries FOREIGN KEY (match_id, game_number) REFERENCES
    games — a row here first, same as the projector always has one before
    it ever writes a card_events row."""
    conn.execute(
        "INSERT INTO games (match_id, game_number) VALUES (?, ?)",
        (match_id, game_number),
    )


def _reveal(conn, match_id, names, *, start_grp_id):
    """The opponent (seat 2) reveals `names`, each a distinct nonland card —
    colors '[]' (known-colourless, not unknown) so colour_factor never
    penalizes a definition for a colour never deliberately told to it."""
    for i, name in enumerate(names):
        grp_id = start_grp_id + i
        conn.execute(
            "INSERT INTO cards (grp_id, name, type_line, rarity, colors) "
            "VALUES (?, ?, 'Creature — Test', 'common', '[]')",
            (grp_id, name),
        )
        conn.execute(
            "INSERT INTO card_events (match_id, game_number, seq, turn_number, seat, "
            "grp_id, category, zone_src, zone_dest) VALUES (?, 1, ?, 1, 2, ?, 'Zone', "
            "NULL, NULL)",
            (match_id, i + 1, grp_id),
        )


def _insert_archetype(conn, key, name, conditions):
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, "
        "fetched_at) VALUES ('Standard', 'archetype', ?, ?, 0, ?, '2026-01-01T00:00:00Z')",
        (key, name, json.dumps({"Name": name, "Conditions": conditions})),
    )


def test_rank_candidates_seen_names_agrees_with_the_card_events_query(conn):
    """seen_names replaces _match_seen_forms's card_events query with an
    already-gathered name set — same contract as the existing opponent_cards
    override. Feeding it the exact names that were, in fact, written to
    card_events for this match must produce the identical candidate list as
    the default card_events-driven path, since _seen_forms(these names) and
    _match_seen_forms(conn, match_id) resolve to the same normalized set."""
    _insert_deck(conn, "d1")
    _insert_match(conn, "m1", "d1")
    names = ["Momo, Friendly Flier", "Stock Up"]
    _insert_game(conn, "m1")
    _reveal(conn, "m1", names, start_grp_id=1)
    _insert_archetype(conn, "Momo", "Momo", [
        {"Type": "InMainboard", "Cards": ["Momo, Friendly Flier"]},
    ])
    conn.commit()

    via_db = rank_candidates(conn, "m1")
    via_names = rank_candidates(conn, "m1", seen_names=names)
    assert via_db  # sanity: the scenario actually produced candidates
    assert via_names == via_db


def test_rank_candidates_seen_names_replaces_an_empty_card_events_query(conn):
    """A match with nothing in card_events yet — the live read's own case,
    where the projector has not caught up to what the live replay has
    already shown — returns no candidates through the default path, but
    seen_names supplies a name set gathered some other way and candidates
    are ranked from that instead."""
    _insert_deck(conn, "d1")
    _insert_match(conn, "m1", "d1")
    _insert_archetype(conn, "Momo", "Momo", [
        {"Type": "InMainboard", "Cards": ["Momo, Friendly Flier"]},
    ])
    conn.commit()

    assert rank_candidates(conn, "m1") == []
    live_candidates = rank_candidates(conn, "m1", seen_names=["Momo, Friendly Flier"])
    assert any(c.key == "Momo" for c in live_candidates)


# --- live_opponent_colors ------------------------------------------------------


def test_live_opponent_colors_agrees_with_the_view(conn):
    """The strongest proof this reproduces v_opponent_cards: a
    match with card_events mixing a land, a token and two nonland reveals,
    checked against the view's own SQL row for that match_id — not a
    hand-derived expectation, the view's own answer for data this test
    controls end to end."""
    _insert_deck(conn, "d1")
    _insert_match(conn, "m1", "d1")
    _insert_game(conn, "m1")
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?, ?, ?, ?, ?)",
        (1, "White Guy", "Creature — Human", "common", json.dumps(["W"])),
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?, ?, ?, ?, ?)",
        (2, "Blue Guy", "Creature — Human", "common", json.dumps(["U"])),
    )
    # A land Arena reports as colourless — excluded from both colours and
    # the count, even though it was genuinely revealed.
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?, ?, ?, ?, ?)",
        (3, "Some Land", "Land", "common", json.dumps([])),
    )
    # A token — excluded the same way _match_seen_forms excludes it.
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?, ?, ?, ?, ?)",
        (4, "Some Token", "Token Creature — Spirit", "common", json.dumps(["G"])),
    )
    for grp_id in (1, 2, 3, 4):
        conn.execute(
            "INSERT INTO card_events (match_id, game_number, seq, turn_number, seat, "
            "grp_id, category, zone_src, zone_dest) VALUES ('m1', 1, ?, 1, 2, ?, 'Zone', "
            "NULL, NULL)",
            (grp_id, grp_id),
        )
    conn.commit()

    view_row = conn.execute(
        "SELECT colors, cards_seen FROM v_opponent_cards WHERE match_id = 'm1'"
    ).fetchone()

    colors, cards_seen = live_opponent_colors(
        conn, ["White Guy", "Blue Guy", "Some Land", "Some Token"]
    )
    assert (colors, cards_seen) == (view_row["colors"], view_row["cards_seen"])
    assert (colors, cards_seen) == ("WU", 2)


def test_live_opponent_colors_ignores_a_name_cards_has_never_heard_of(conn):
    """A name absent from `cards` entirely (never downloaded, or a spelling
    mismatch) is silently excluded from both the count and the colours —
    rule 4, never a guess."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?, ?, ?, ?, ?)",
        (1, "Known Card", "Creature — Human", "common", json.dumps(["R"])),
    )
    conn.commit()
    colors, cards_seen = live_opponent_colors(conn, ["Known Card", "Never Downloaded"])
    assert (colors, cards_seen) == ("R", 1)


def test_live_opponent_colors_of_an_empty_name_set_is_colourless_and_zero(conn):
    assert live_opponent_colors(conn, []) == ("", 0)


def test_live_opponent_colors_counts_a_reprinted_name_once(conn):
    """A bare name set has no printing to pick, so two printings of one name
    (different grp_id and type-line text, as a reprint can carry) are one card
    seen, not two."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?, ?, ?, ?, ?)",
        (1, "Reprinted Guy", "Creature — Human", "rare", json.dumps(["B"])),
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?, ?, ?, ?, ?)",
        (2, "Reprinted Guy", "Creature — Human Warrior", "mythic", json.dumps(["B"])),
    )
    conn.commit()
    assert live_opponent_colors(conn, ["Reprinted Guy"]) == ("B", 1)
