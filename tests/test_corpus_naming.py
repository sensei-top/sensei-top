"""The corpus naming source (archetypes/corpus.py) and its combination with
the rule engine in classify_matches().

Two layers of fixture here, matching this project's own precedent for a
piece that does not need a full log capture (test_leaks.py's own module
docstring): ``corpus.py``'s own functions (``build_prior``/``read_corpus``/
``matched_cards``) are exercised directly against synthetic ``meta_deck``/
``meta_deck_archetype`` rows, the same shape ``test_guide_window.py``'s
``_store_deck``/``_ban`` helpers already use for ``format_resets``/
``structural_change`` (adapted here rather than duplicated, since
``build_prior`` calls exactly those two functions to drop a "gone"
archetype). ``classify_matches()`` itself is exercised against a synthetic
``matches``/``card_events``/``cards``/``archetypes`` schema built directly
(no fixture log ingest needed — the same precedent), because
``test_classify.py`` never touches a real connection at all: every rule
there is tested through ``evaluate()``/``choose()``/``confidence_of()``
directly, which is the right level for the rule engine alone but not for
proving how the two evidence sources combine.

The odds computed by hand below follow ``read_corpus``'s own documented
formula (Laplace-smoothed naive-Bayes log-odds) rather than being copied
from a run of the code (rule 8) — see each test's own comment for the
arithmetic.
"""

from __future__ import annotations

import json
import math

import pytest

from sensei_top.archetypes import classify_matches
from sensei_top.archetypes.classify import (
    CORPUS_MIN_CARDS,
    CORPUS_MIN_ODDS,
    _corpus_confidence,
    _seen_forms,
)
from sensei_top.archetypes.corpus import (
    MIN_CORPUS_DECKS,
    CorpusPrior,
    build_prior,
    matched_cards,
    read_corpus,
)
from sensei_top.db import open_database


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "corpus.db")
    yield c
    c.close()


# --- corpus fixtures ---------------------------------------------------------
# Adapted from test_guide_window.py's own _store_deck/_ban: that module needs
# these same meta_deck/meta_deck_archetype/cards rows to drive
# format_resets()/structural_change(), which build_prior() calls internally
# (see corpus.py's own docstring on the archetype_name-keyed "gone" lookup).


def _store_deck(conn, event_id, deck_ord, archetype_key, mainboard, *,
                 event_date, archetype_name=None, method="archetype", fmt="Standard"):
    archetype_name = archetype_name or archetype_key
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', ?, ?, 'B')",
        (event_id, event_date, fmt),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
        "VALUES (?, ?, ?, '[]')",
        (event_id, deck_ord, json.dumps(mainboard)),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, ?, ?, ?, ?, ?, 'now')",
        (event_id, deck_ord, archetype_key, archetype_name, archetype_name, method),
    )


def _ban(conn, name):
    conn.execute(
        "INSERT INTO cards (grp_id, name, standard_legality) VALUES (?, ?, 'banned')",
        (hash(name) % 1_000_000, name),
    )


def _deck(*names: str) -> list[dict]:
    return [{"count": 4, "name": name} for name in names]


# --- read_corpus / build_prior ------------------------------------------------


def test_a_card_unique_to_one_archetype_names_it_from_one_reveal(conn):
    for i in range(MIN_CORPUS_DECKS):
        _store_deck(conn, f"fireball{i}", 0, "ArchFireball", _deck("Fireball"),
                    event_date="2026-08-01")
    for i in range(MIN_CORPUS_DECKS):
        _store_deck(conn, f"counter{i}", 0, "ArchCounter", _deck("Counterspell"),
                    event_date="2026-08-01")
    conn.commit()

    prior = build_prior(conn)
    assert prior is not None
    ranked = read_corpus(prior, _seen_forms(["Fireball"]))
    assert ranked[0][0] == "ArchFireball"


def test_a_ubiquitous_card_names_nothing_however_often_it_appears(conn):
    """Both archetypes run the same card in every one of their decks, in
    equal numbers — its per-card log-odds term is identical for each, so the
    only thing left to break the tie is each archetype's own share of the
    corpus, which is also equal here. Odds of 1 never clears
    ``CORPUS_MIN_ODDS``, however many times the match has shown the card."""
    for i in range(MIN_CORPUS_DECKS):
        _store_deck(conn, f"a{i}", 0, "ArchWildsA", _deck("Evolving Wilds"),
                    event_date="2026-08-01")
    for i in range(MIN_CORPUS_DECKS):
        _store_deck(conn, f"b{i}", 0, "ArchWildsB", _deck("Evolving Wilds"),
                    event_date="2026-08-01")
    conn.commit()

    prior = build_prior(conn)
    assert prior is not None
    seen = _seen_forms(["Evolving Wilds"])
    ranked = read_corpus(prior, seen)
    top_key, top_score = ranked[0]
    second_score = ranked[1][1]
    odds = math.exp(top_score - second_score)
    assert odds == pytest.approx(1.0, abs=1e-9)
    matched = matched_cards(prior, top_key, seen)
    assert _corpus_confidence(odds, len(matched)) is None


def test_below_corpus_min_cards_even_at_overwhelming_odds(conn):
    """Two cards exclusive to one archetype, seen against a corpus large
    enough to make that archetype's read a runaway favourite by hand-checked
    naive-Bayes arithmetic (see the comment below) — and yet still not
    enough *cards* to name anything, because CORPUS_MIN_CARDS is its own
    independent gate, not a function of how decisive the odds are.

    Hand-computed odds (n_key=8 for ArchTwin, n_key=8 for the ArchKiln decoy,
    n_filler=300, N=316, both signature cards run in all 8 of ArchTwin's
    decks and nowhere else): each card's log-odds term is
    ln((8.5/9)/(8.5/317)) = ln(35.22) ~= 3.56, so two cards sum to ~7.12;
    ArchTwin's own prior term is ln(8/316) ~= -3.68, for a total score of
    ~3.45. The runner-up is Filler (its sheer size beats the untouched
    ArchKiln decoy): ln(300/316) ~= -0.052. exp(3.45 - (-0.052)) ~= 33, well
    past CORPUS_MIN_ODDS (25).
    """
    for i in range(MIN_CORPUS_DECKS):
        _store_deck(conn, f"twin{i}", 0, "ArchTwin", _deck("Card R1", "Card R2"),
                    event_date="2026-08-01")
    for i in range(MIN_CORPUS_DECKS):
        _store_deck(conn, f"kiln{i}", 0, "ArchKiln", _deck("Kiln Fiend"),
                    event_date="2026-08-01")
    for i in range(300):
        _store_deck(conn, "filler", i, "Filler", _deck("Filler Card"),
                    event_date="2026-08-01")
    conn.commit()

    prior = build_prior(conn)
    assert prior is not None
    seen = _seen_forms(["Card R1", "Card R2"])
    ranked = read_corpus(prior, seen)
    top_key, top_score = ranked[0]
    assert top_key == "ArchTwin"
    second_score = ranked[1][1]
    odds = math.exp(top_score - second_score)
    matched = matched_cards(prior, top_key, seen)
    assert len(matched) == 2 < CORPUS_MIN_CARDS
    assert odds > CORPUS_MIN_ODDS
    assert _corpus_confidence(odds, len(matched)) is None


def test_a_reset_banned_card_contributes_zero_and_the_gone_archetype_is_absent(conn):
    """Adapted directly from test_guide_window.py's own
    test_archetype_with_zero_post_reset_decks_is_gone: 20 same-day decks all
    running a now-banned card, and nothing after — satisfies
    structural_change's MIN_PRE_RESET_DECKS (15) and format_resets'
    MIN_DECKS_FOR_LAST_APPEARANCE (2) in one fixture shape. A second,
    untouched archetype has to exist too: build_prior() skips a "gone"
    archetype's decks entirely (not just the banned card within them), and
    with nothing else in the corpus that would leave total_decks at 0 and
    the whole prior None — which would prove nothing about *this*
    exclusion specifically.
    """
    _ban(conn, "Stormchaser's Talent")
    for i in range(20):
        _store_deck(conn, f"pre{i}", 0, "IzzetProwess", _deck("Stormchaser's Talent"),
                    archetype_name="Izzet Prowess", event_date="2026-08-01")
    for i in range(MIN_CORPUS_DECKS + 2):
        _store_deck(conn, f"red{i}", 0, "MonoRed", _deck("Lightning Bolt"),
                    archetype_name="Mono Red", event_date="2026-08-01")
    conn.commit()

    prior = build_prior(conn)
    assert prior is not None
    assert "IzzetProwess" not in prior.decks_by_key
    assert "IzzetProwess" not in prior.labels
    assert "MonoRed" in prior.decks_by_key
    banned_canon = next(iter(_seen_forms(["Stormchaser's Talent"])))
    # Every form normalize() produces for the banned name is absent from the
    # global counts, not just the one this test happens to check first.
    for form in _seen_forms(["Stormchaser's Talent"]):
        assert form not in prior.global_counts or prior.global_counts.get(form, 0) == 0
    assert banned_canon not in prior.global_counts


def test_read_corpus_score_is_order_independent_despite_float_non_associativity():
    """read_corpus sums each archetype's log-odds terms with math.fsum
    specifically because plain left-to-right float addition is not
    associative: the exact same card counts, inserted into card_counts[key]
    in a different order, can produce a different naive sum bit-for-bit —
    the same drift PYTHONHASHSEED's randomized dict/set iteration order
    could otherwise leak into a score that is supposed to depend only on
    the data (build_prior's own comment on this, and this module's own
    docstring on why the arithmetic here is hand-computed, not copied from
    a run of the code).

    Built directly, not through build_prior, so the two card_counts orders
    can be constructed by hand.

    n_key=40, total_decks=500, (n_key_card, n_card) pairs for twelve cards:
        (27, 47), (17, 278), (32, 239), (20, 264), (23, 321), (14, 272),
        (9, 153), (9, 395), (7, 323), (17, 482), (35, 396), (39, 500)
    Each term is ln(((n_key_card+0.5)/(n_key+1)) / ((n_card+0.5)/(total_decks+1))),
    and the first term summed is always the archetype's own prior,
    ln(n_key/total_decks) = ln(40/500) = -2.5257286443082556.

    Summing prior_term followed by the twelve card terms left-to-right with
    plain ``+=``, in the order listed above, gives -4.452092058133077;
    summing the same twelve terms in reverse gives -4.452092058133078 — one
    ULP apart. The precondition assertion below reproduces that with real
    Python float arithmetic (not a value copied from a prior run) before
    ever calling read_corpus, so a regression back to ``score += term``
    would make this test fail rather than pass by coincidence.
    """

    def term(n_key_card: int, n_key: int, n_card: int, total_decks: int) -> float:
        p_given_key = (n_key_card + 0.5) / (n_key + 1)
        p_overall = (n_card + 0.5) / (total_decks + 1)
        return math.log(p_given_key / p_overall)

    n_key = 40
    total_decks = 500
    counts = [
        (27, 47), (17, 278), (32, 239), (20, 264), (23, 321), (14, 272),
        (9, 153), (9, 395), (7, 323), (17, 482), (35, 396), (39, 500),
    ]
    names = [f"card{i}" for i in range(len(counts))]
    prior_term = math.log(n_key / total_decks)
    card_terms = [term(n_key_card, n_key, n_card, total_decks) for n_key_card, n_card in counts]

    # Precondition: naive left-to-right summation, in the same order
    # read_corpus's own loop builds it (the archetype's prior term first,
    # then the card terms in dict-iteration order), really does differ
    # between the forward and reversed card orderings.
    naive_forward = 0.0
    for t in [prior_term, *card_terms]:
        naive_forward += t
    naive_reversed = 0.0
    for t in [prior_term, *reversed(card_terms)]:
        naive_reversed += t
    assert naive_forward != naive_reversed

    global_counts = {
        name: n_card for name, (_n_key_card, n_card) in zip(names, counts, strict=True)
    }
    card_counts_forward = {
        name: n_key_card for name, (n_key_card, _n_card) in zip(names, counts, strict=True)
    }
    card_counts_reversed = dict(reversed(list(card_counts_forward.items())))
    assert list(card_counts_forward.items()) != list(card_counts_reversed.items())

    prior_forward = CorpusPrior(
        total_decks=total_decks,
        global_counts=global_counts,
        decks_by_key={"ArchDet": n_key},
        card_counts={"ArchDet": card_counts_forward},
    )
    prior_reversed = CorpusPrior(
        total_decks=total_decks,
        global_counts=global_counts,
        decks_by_key={"ArchDet": n_key},
        card_counts={"ArchDet": card_counts_reversed},
    )

    seen = frozenset(names)
    assert read_corpus(prior_forward, seen) == read_corpus(prior_reversed, seen)


# --- classify_matches: combining the two sources ------------------------------
# Built directly against the projected schema (matches/games/card_events/
# cards/archetypes), the same precedent test_leaks.py's own module docstring
# describes for a piece that does not need a full log capture — test_api.py's
# _teach fixture is the closer relative (it also drives classify_matches end
# to end) but ingests a whole fixture log first, which buys nothing here:
# every card and definition below is invented to hit a specific confidence
# tier, not read off a real match.


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
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, turn_count, self_mulligans, "
        "opp_mulligans) VALUES (?, 1, 1, 6, 0, 0)",
        (match_id,),
    )


def _reveal(conn, match_id, names, *, start_grp_id):
    """The opponent (seat 2) reveals `names`, each a distinct nonland card —
    colors '[]' (known-colourless, not unknown) so colour_factor never
    penalizes a definition for a colour we deliberately never told it about;
    see classify.py's own _card_colors_by_name docstring on that
    unknown-vs-colourless distinction."""
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


def _opponent_row(conn, match_id):
    return conn.execute(
        "SELECT * FROM opponent_archetype WHERE match_id = ?", (match_id,)
    ).fetchone()


def test_an_empty_corpus_yields_none_and_todays_rule_verdict_is_unchanged(conn):
    """No meta_deck/meta_deck_archetype rows at all: build_prior() returns
    None (its own documented "no corpus" case), and classify_matches must
    behave exactly as it did before this feature existed — a machine that
    has never run `sensei-top meta` keeps working (build_prior's own
    docstring, AGENTS.md rule 5)."""
    _insert_deck(conn, "d1")
    _insert_match(conn, "m1", "d1")
    _reveal(conn, "m1", ["Card A", "Card B"], start_grp_id=1)
    _insert_archetype(conn, "RuleArch", "Rule Deck", [
        {"Type": "InMainboard", "Cards": ["Card A"]},
        {"Type": "InMainboard", "Cards": ["Card B"]},
    ])
    conn.commit()

    counts = classify_matches(conn)
    assert counts["corpus"] == 0

    row = _opponent_row(conn, "m1")
    assert row["method"] == "archetype"
    assert row["archetype_key"] == "RuleArch"


def test_a_high_rule_verdict_is_not_displaced_by_a_medium_corpus_read(conn):
    """Six single-card conditions, all met, no rival definition: proof=1.0,
    support=1-0.5**6 (~0.984), colour=1.0 (include_color=0), margin=inf, and
    6 cards_seen clears _HIGH_CARDS_SEEN — confidence_of reads this 'high'
    by the same arithmetic test_classify.py's own
    test_confidence_needs_fit_margin_and_a_look_at_the_deck checks directly.

    The corpus's own top (only) archetype runs all 6 of the same cards, so
    matched_cards is 6 — enough to clear CORPUS_MIN_CARDS and, with no rival
    archetype at all in this corpus, an infinite odds ratio — but 6 is still
    short of _CORPUS_HIGH_CARDS (8), so _corpus_confidence caps this at
    'medium' however large the odds get. Rank 2 does not beat rank 3: the
    rule verdict must stand.
    """
    cards = [f"High Card {i}" for i in range(1, 7)]
    _insert_deck(conn, "d1")
    _insert_match(conn, "m1", "d1")
    _reveal(conn, "m1", cards, start_grp_id=100)
    _insert_archetype(conn, "HighArch", "High Deck",
                       [{"Type": "InMainboard", "Cards": [c]} for c in cards])
    for i in range(MIN_CORPUS_DECKS):
        _store_deck(conn, "high", i, "CorpusHigh", _deck(*cards), event_date="2026-08-01")
    conn.commit()

    classify_matches(conn)
    row = _opponent_row(conn, "m1")
    assert row["method"] == "archetype"
    assert row["archetype_key"] == "HighArch"
    assert row["confidence"] == "high"


def test_a_low_rule_verdict_is_displaced_by_a_medium_corpus_read(conn):
    """One condition met (Card X) and one never revealed (Card Q): proof=0.5,
    support=1-0.5**1=0.5, fit=0.25 — below _MEDIUM_FIT (0.30), so
    confidence_of reads this 'low' regardless of margin (no rival exists
    here either, so margin is inf and still doesn't rescue it).

    The corpus's only archetype runs all 4 revealed cards (Card X plus three
    that the rule definition never mentions), so matched_cards is 4: clears
    CORPUS_MIN_CARDS and _CORPUS_MEDIUM_CARDS, and with no rival in this
    corpus the odds ratio is infinite, clearing _CORPUS_MEDIUM_ODDS too (but
    not _CORPUS_HIGH_CARDS's separate 8-card floor) — 'medium', rank 2. Rank
    2 beats the rule's rank 1 ('low'): the corpus verdict must win.
    """
    cards = ["Card X", "Corpus One", "Corpus Two", "Corpus Three"]
    _insert_deck(conn, "d1")
    _insert_match(conn, "m1", "d1")
    _reveal(conn, "m1", cards, start_grp_id=200)
    _insert_archetype(conn, "LowArch", "Low Deck", [
        {"Type": "InMainboard", "Cards": ["Card X"]},
        {"Type": "InMainboard", "Cards": ["Card Q"]},
    ])
    for i in range(MIN_CORPUS_DECKS):
        _store_deck(conn, "low", i, "CorpusLow", _deck(*cards), event_date="2026-08-01")
    conn.commit()

    classify_matches(conn)
    row = _opponent_row(conn, "m1")
    assert row["method"] == "corpus"
    assert row["archetype_key"] == "CorpusLow"
    assert row["confidence"] == "medium"


def test_a_candidates_odds_are_a_figure_up_to_a_thousand_and_a_floor_past_it():
    """exp() of a log-odds gap of 40 is about 2.4e17, which printed whole is
    a figure of eighteen digits in the picker's reason."""
    from sensei_top.archetypes.classify import _odds_text

    assert _odds_text(math.inf) == "no rival"
    assert _odds_text(237.4) == "237x the next best"
    assert _odds_text(999.4) == "999x the next best"
    assert _odds_text(1000.0) == "over 1,000x the next best"
    assert _odds_text(math.exp(40)) == "over 1,000x the next best"
