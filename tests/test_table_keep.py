"""Tests for table/keep.py: the keep guide's land-odds distribution and its
degradation when the maindeck has cards the card table has never named.
"""

from __future__ import annotations

import json
import math

import pytest

from sensei_top.db import open_database
from sensei_top.guide.play import MulliganBucket, WLTally
from sensei_top.table.keep import _land_prefix_has_land, build_keep_guide


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_card(conn, grp_id, name, *, mana_cost, type_line, oracle_text=None):
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) "
        "VALUES (?, ?, ?, ?, ?)",
        (grp_id, name, mana_cost, type_line, oracle_text),
    )


def _insert_deck(conn, deck_id, maindeck):
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES (?, 'Test Deck', ?)",
        (deck_id, json.dumps({"maindeck": maindeck})),
    )


def test_land_odds_sum_to_one_and_match_hypergeometric_by_hand(conn):
    """17 lands (grp 1) in a 60-card deck: P(exactly k lands in an opening 7)
    computed here independently via math.comb, per AGENTS.md rule 8 (derive
    the expected answer, never copy the code's own output)."""
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    _insert_card(conn, 2, "Bear", mana_cost="{1}{G}", type_line="Creature — Bear",
                 oracle_text="Vanilla creature.")
    _insert_deck(conn, "d1", [1] * 17 + [2] * 43)
    conn.commit()

    guide = build_keep_guide(conn, "d1")
    assert guide is not None
    assert guide.unnamed_count == 0

    total_p = sum(p for _k, p in guide.land_odds)
    assert math.isclose(total_p, 1.0, abs_tol=1e-9)

    # P(exactly 2 lands in 7) = C(17,2) * C(43,5) / C(60,7), by hand.
    expected_p2 = math.comb(17, 2) * math.comb(43, 5) / math.comb(60, 7)
    actual_p2 = dict(guide.land_odds)[2]
    assert math.isclose(actual_p2, expected_p2, rel_tol=1e-9)

    assert sum(slot.count for slot in guide.ideal_hand) == 7

    # early_plays is the same number ideal_hand's "play(s) at 1-3 mana" slot
    # carries as a formatted label — exposed as a bare int too, since
    # table/opening_hand.py's verdict needs to compare against it directly.
    early_slot = next(s for s in guide.ideal_hand if "mana" in s.label)
    assert guide.early_plays == early_slot.count


def test_unnamed_cards_suppress_the_keepable_hand_band(conn):
    """A maindeck card missing from the `cards` table means the land count
    behind it can't be trusted (a land counted as unnamed would silently
    undercount `land_count`), so land_min/land_max/ideal_hand/land_odds must
    all come back empty rather than a number computed on a partial list."""
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    _insert_deck(conn, "d1", [1] * 17 + [99] * 43)  # grp_id 99 never named
    conn.commit()

    guide = build_keep_guide(conn, "d1")
    assert guide is not None
    assert guide.unnamed_count == 43
    assert guide.land_min is None
    assert guide.land_max is None
    assert guide.ideal_hand == ()
    assert guide.land_odds == ()
    assert guide.keep_rate is None
    assert guide.notes  # explains the gap rather than staying silent


def test_no_deck_id_returns_none(conn):
    assert build_keep_guide(conn, None) is None


def test_unknown_deck_id_returns_none(conn):
    assert build_keep_guide(conn, "does-not-exist") is None


# --- maindeck kwarg (the deck comes from the live replay's own connectResp,
# so a deck project() has never written a decks row for still gets a land
# band) --------------------------------------------------------------------
#
# v_deck_land_count's own SQL (migrations/011_review_views.sql) is mirrored
# by hand, not run and copied (rule 8): 'Land' is looked for only in the
# type_line prefix up to and including the first em dash (U+2014), or the
# whole string when there is none. Traced against SQLite's 1-based
# instr/substr semantics against three concrete type_lines:
#   "Basic Land — Island"   -> prefix "Basic Land —" contains "Land" -> True
#   "Creature — Elemental"  -> prefix "Creature —" has no "Land"     -> False
#   "Land"                  -> no dash at all, whole string is the prefix,
#                              contains "Land"                       -> True


def test_land_prefix_has_land_matches_the_view_sql_by_hand():
    assert _land_prefix_has_land("Basic Land — Island") is True
    assert _land_prefix_has_land("Creature — Elemental") is False
    assert _land_prefix_has_land("Land") is True
    # A land type appearing only *after* the dash (e.g. a back face naming
    # a land type on an Adventure/MDFC) must not count -- the view's own
    # instr() only ever looks at the prefix.
    assert _land_prefix_has_land("Sorcery — Adventure (Land Effect)") is False


def test_maindeck_kwarg_gives_a_band_with_no_decks_row_at_all(conn):
    """The whole point of the maindeck kwarg: a deck_id the projector has
    never written a decks row for (so v_deck_land_count has no row either)
    still gets a land band when the live replay's own maindeck is passed
    in. Reuses the
    exact 17-land/43-cheap-spell/60-card shape
    test_land_odds_sum_to_one_and_match_hypergeometric_by_hand already
    verified independently (land_min=2, land_max=4) -- not re-derived here.
    Deliberately never calls _insert_deck: no decks row, no v_deck_land_count
    row, for "d1" at all."""
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    _insert_card(conn, 2, "Bear", mana_cost="{1}{G}", type_line="Creature — Bear",
                 oracle_text="Vanilla creature.")
    conn.commit()

    # Unchanged behaviour for every existing caller: no maindeck kwarg, no
    # decks row -> still None, same as test_unknown_deck_id_returns_none.
    assert build_keep_guide(conn, "d1") is None

    maindeck = [1] * 17 + [2] * 43
    guide = build_keep_guide(conn, "d1", maindeck=maindeck)
    assert guide is not None
    assert guide.deck_id == "d1"
    assert guide.maindeck_size == 60
    assert guide.land_count == 17
    assert guide.unnamed_count == 0
    assert guide.land_min == 2 and guide.land_max == 4
    assert guide.creature_count == 43
    # No matches reference this deck_id either way -- the empirical halves
    # degrade the same way they already do with a real decks row present
    # (test_key_plays_and_mulligan_cost_withheld_with_no_match_history).
    assert guide.mulligan_record == ()
    assert guide.key_plays == ()
    assert guide.mulligan_cost is None


def test_maindeck_kwarg_flags_unnamed_cards_the_same_way_the_view_does(conn):
    """The fallback's unnamed_count must match v_deck_land_count's own rule
    (c.name IS NULL) exactly: a grp_id with no cards row at all counts as
    unnamed, same as test_unnamed_cards_suppress_the_keepable_hand_band's
    projected-path equivalent."""
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    conn.commit()

    guide = build_keep_guide(conn, "d1", maindeck=[1] * 17 + [99] * 43)
    assert guide is not None
    assert guide.unnamed_count == 43
    assert guide.land_min is None
    assert guide.land_max is None
    assert guide.notes


def test_maindeck_kwarg_is_ignored_once_a_projected_row_exists(conn):
    """Once project() has written decks/v_deck_land_count for this deck_id,
    the projected numbers win -- a maindeck kwarg the caller happens to pass
    alongside (e.g. a stale live replay from a different list) must never
    override them."""
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    _insert_card(conn, 2, "Bear", mana_cost="{1}{G}", type_line="Creature — Bear",
                 oracle_text="Vanilla creature.")
    _insert_deck(conn, "d1", [1] * 17 + [2] * 43)
    conn.commit()

    without = build_keep_guide(conn, "d1")
    # A contradicting maindeck: all lands, wrong size entirely -- if this
    # were used at all, land_count/land_min would come out different.
    with_maindeck = build_keep_guide(conn, "d1", maindeck=[1] * 60)

    assert with_maindeck is not None and without is not None
    assert with_maindeck.maindeck_size == without.maindeck_size == 60
    assert with_maindeck.land_count == without.land_count == 17
    assert with_maindeck.land_min == without.land_min
    assert with_maindeck.land_max == without.land_max


def test_boarded_maindeck_wins_over_the_projected_row(conn):
    """Under ``boarded`` the passed list is the deck held after a sideboarding
    break and the decks row is game 1's: every list-derived number reads the
    list, while deck_id is kept for the mulligan record."""
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    _insert_card(conn, 2, "Bear", mana_cost="{1}{G}", type_line="Creature — Bear",
                 oracle_text="Vanilla creature.")
    _insert_deck(conn, "d1", [1] * 17 + [2] * 43)
    conn.execute("INSERT INTO matches (match_id, deck_id) VALUES ('m1', 'd1')")
    conn.execute(
        "INSERT INTO games (match_id, game_number, result, self_mulligans) "
        "VALUES ('m1', 1, 'loss', 2)"
    )
    conn.commit()

    guide = build_keep_guide(conn, "d1", maindeck=[1] * 20 + [2] * 40, boarded=True)
    assert guide is not None
    assert guide.deck_id == "d1"
    assert [(r.mulligans, r.games, r.wins) for r in guide.mulligan_record] == [(2, 1, 0)]
    assert guide.maindeck_size == 60
    assert guide.land_count == 20
    assert guide.creature_count == 40
    # boarded with no list falls back to the row, as without the flag
    plain = build_keep_guide(conn, "d1", boarded=True)
    assert plain is not None and plain.land_count == 17


# --- key_plays / mulligan_cost (Layer 2: the deck's own play evidence) -----
#
# These reuse guide/play.py's key_card_timing and mulligan_record rather
# than reimplementing them, so the fixture helpers below mirror
# tests/test_guide_play.py's own (deck_id here plays the role that file's
# hard-coded "deckhash1" does; keep.build_keep_guide looks the identity up
# by deck_id via guide.deck.list_identities, an ungrouped deck_id with no
# deck_guids row, so it becomes its own one-deck_id identity).


def _insert_match(conn, match_id, deck_id):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, 1, 2, 'u', 'n', 't', 't', "
        "'win', 1, 0, 'r')",
        (match_id, deck_id),
    )


def _insert_game(conn, match_id, result, *, self_mulligans):
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 10, ?, 0)",
        (match_id, result, self_mulligans),
    )


def _insert_card_event(conn, match_id, turn_number, grp_id):
    conn.execute(
        "INSERT INTO card_events (match_id, game_number, seq, turn_number, seat, grp_id, "
        "category) VALUES (?, 1, 0, ?, 1, ?, 'Resolve')",
        (match_id, turn_number, grp_id),
    )


def test_key_plays_and_mulligan_cost_withheld_with_no_match_history(conn):
    """A deck with a stored maindeck but no matches played yet has no
    DeckIdentity at all (guide.deck.list_identities only returns identities
    with matches > 0) -- key_plays/mulligan_cost must come back empty/None,
    not raise on a missing identity."""
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    _insert_card(conn, 2, "Threat", mana_cost="{4}{U}", type_line="Creature — Elemental",
                 oracle_text="Flying.")
    _insert_deck(conn, "d1", [1] * 17 + [2] * 43)
    conn.commit()

    guide = build_keep_guide(conn, "d1")
    assert guide.key_plays == ()
    assert guide.mulligan_cost is None


def test_key_plays_and_mulligan_cost_withheld_below_the_minimum_game_count(conn):
    """9 decided games, one below _MIN_EVIDENCE_GAMES (10): both stay
    withheld, and a note explains why rather than reporting a split off a
    sample too small to mean anything."""
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    _insert_card(conn, 2, "Threat", mana_cost="{4}{U}", type_line="Creature — Elemental",
                 oracle_text="Flying.")
    _insert_deck(conn, "d1", [1] * 17 + [2] * 3 + [3] * 40)  # 3 copies of Threat
    _insert_card(conn, 3, "Filler", mana_cost="{1}{U}", type_line="Instant",
                 oracle_text="Draw a card.")
    for i in range(9):
        match_id = f"m{i}"
        _insert_match(conn, match_id, "d1")
        _insert_game(conn, match_id, "win" if i % 2 == 0 else "loss", self_mulligans=0)
    conn.commit()

    guide = build_keep_guide(conn, "d1")
    assert guide.key_plays == ()
    assert guide.mulligan_cost is None
    assert any("9 decided game" in n for n in guide.notes)


def test_key_plays_and_mulligan_cost_at_the_minimum_game_count(conn):
    """10 decided games (== _MIN_EVIDENCE_GAMES): key_plays and
    mulligan_cost both appear, matching guide/play.py's own
    key_card_timing/mulligan_record exactly -- every number below is
    derived by hand from the fixture, not by running the code (rule 8).

    Games 1-3: win, Threat resolves turn_number 8 -> player turn (8+1)//2=4
      -> "by T4".
    Games 4-5: loss, Threat resolves turn_number 8 -> "by T4".
      => "by T4": WLTally(w=3, l=2), 5 games.
    Games 6-7: win, Threat never resolves.
    Game 8: loss, Threat never resolves.
      => "never resolved": WLTally(w=2, l=1), 3 games.
    Game 9: win, Threat resolves turn_number 20 -> player turn (20+1)//2=10
      -> "T9+".
    Game 10: loss, Threat resolves turn_number 20 -> "T9+".
      => "T9+": WLTally(w=1, l=1), 2 games.
    Total decided games: 5 + 3 + 2 = 10.

    Neither "by T4" (n=5) nor "T9+" (n=2) clears _MIN_EVIDENCE_GAMES (10),
    so _best_key_play_band falls back to comparing all real bands by raw
    win rate: "by T4" 3/5 = 0.6 beats "T9+" 1/2 = 0.5, so "by T4" wins.

    Games 1-8 are kept at seven (self_mulligans=0): wins 3+2=5, losses 2+1=3.
    Games 9-10 are mulliganed to six (self_mulligans=1): wins 1, losses 1.
    """
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    _insert_card(conn, 2, "Threat", mana_cost="{4}{U}", type_line="Creature — Elemental",
                 oracle_text="Flying.")
    _insert_deck(conn, "d1", [1] * 17 + [2] * 3 + [3] * 40)
    _insert_card(conn, 3, "Filler", mana_cost="{1}{U}", type_line="Instant",
                 oracle_text="Draw a card.")

    for i in range(1, 4):  # games 1-3: win, resolves by T4
        _insert_match(conn, f"m{i}", "d1")
        _insert_game(conn, f"m{i}", "win", self_mulligans=0)
        _insert_card_event(conn, f"m{i}", 8, 2)
    for i in range(4, 6):  # games 4-5: loss, resolves by T4
        _insert_match(conn, f"m{i}", "d1")
        _insert_game(conn, f"m{i}", "loss", self_mulligans=0)
        _insert_card_event(conn, f"m{i}", 8, 2)
    for i in range(6, 8):  # games 6-7: win, never resolves
        _insert_match(conn, f"m{i}", "d1")
        _insert_game(conn, f"m{i}", "win", self_mulligans=0)
    _insert_match(conn, "m8", "d1")  # game 8: loss, never resolves
    _insert_game(conn, "m8", "loss", self_mulligans=0)
    _insert_match(conn, "m9", "d1")  # game 9: win, resolves T9+
    _insert_game(conn, "m9", "win", self_mulligans=1)
    _insert_card_event(conn, "m9", 20, 2)
    _insert_match(conn, "m10", "d1")  # game 10: loss, resolves T9+
    _insert_game(conn, "m10", "loss", self_mulligans=1)
    _insert_card_event(conn, "m10", 20, 2)
    conn.commit()

    guide = build_keep_guide(conn, "d1")

    assert len(guide.key_plays) == 1
    threat = guide.key_plays[0]
    assert threat.card == "Threat"
    assert threat.best_band == "by T4"
    assert threat.best_band_record == WLTally(w=3, l=2)
    assert threat.never_resolved == WLTally(w=2, l=1)
    assert threat.n == 10

    assert guide.mulligan_cost is not None
    assert guide.mulligan_cost.kept_seven == MulliganBucket(games=8, wins=5, losses=3)
    assert guide.mulligan_cost.mulliganed == MulliganBucket(games=2, wins=1, losses=1)


def test_best_key_play_band_prefers_a_well_sampled_band_over_a_small_sample_spike(conn):
    """A card that resolved once at "by T4" for a lucky 1-0 must not out-rank
    a "T5-6" band sampled 19 times at a worse-but-real win rate -- the same
    failure mode the plan's own Sunderflock numbers named (5-1 n=6 vs.
    39-20 n=59): _best_key_play_band restricts "best" to bands with at
    least _MIN_EVIDENCE_GAMES games whenever one qualifies."""
    _insert_card(conn, 1, "Island", mana_cost=None, type_line="Basic Land — Island")
    _insert_card(conn, 2, "Threat", mana_cost="{4}{U}", type_line="Creature — Elemental",
                 oracle_text="Flying.")
    _insert_deck(conn, "d1", [1] * 17 + [2] * 3 + [3] * 40)
    _insert_card(conn, 3, "Filler", mana_cost="{1}{U}", type_line="Instant",
                 oracle_text="Draw a card.")

    _insert_match(conn, "m0", "d1")  # the single lucky by-T4 resolve
    _insert_game(conn, "m0", "win", self_mulligans=0)
    _insert_card_event(conn, "m0", 8, 2)  # player turn 4 -> "by T4"

    for i in range(1, 20):  # 19 games resolving at "T5-6" (turn_number 9 -> player turn 5)
        match_id = f"m{i}"
        _insert_match(conn, match_id, "d1")
        _insert_game(conn, match_id, "win" if i <= 10 else "loss", self_mulligans=0)
        _insert_card_event(conn, match_id, 9, 2)
    conn.commit()

    guide = build_keep_guide(conn, "d1")
    threat = next(p for p in guide.key_plays if p.card == "Threat")
    assert threat.best_band == "T5-6"
    assert threat.best_band_record == WLTally(w=10, l=9)
