"""Tests for table/opening_hand.py: the pre-keep hand read.

Two sources of ground truth, matching docs/testing.md's split:

- tests/fixtures/mulligan_session.log for the replay integration itself
  (anchoring, card resolution, Arena's own land signal) — real captured
  data, same fixture test_projector_mulligan.py reads, with grp_ids/names
  cross-checked directly against ``data/sensei-top.db``'s real ``cards`` rows
  (Sleight of Hand, Steam Vents, etc.) rather than invented.
- Synthetic minimal decks/hands for the verdict logic itself (keep /
  mulligan / marginal / withheld), the same "edge cases the real log can't
  easily show" style test_table_keep.py already uses for its own land-band
  arithmetic — reusing that exact deck shape (17 lands / 43 cheap spells in
  a 60-card deck) so land_min=2, land_max=4 and early_plays=2 are already
  independently verified there, not re-derived here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.reader.ingest import ingest_file
from sensei_top.table.opening_hand import build_opening_hand_read

FIXTURE = Path(__file__).parent / "fixtures" / "mulligan_session.log"

# The second offer's 7 grp_ids in zone order, read from the fixture the same
# way test_projector_mulligan.py does (fixture_peek.py show --entry 7).
SECOND_OFFER_GRP_IDS = (102774, 68738, 102774, 86835, 102698, 91584, 102578)
# Real names/costs for those grp_ids, read from data/sensei-top.db's own `cards`
# table (SELECT name, mana_cost, type_line FROM cards WHERE grp_id IN (...)),
# not invented.
REAL_CARDS = {
    102774: ("Sleight of Hand", "{U}", "Sorcery"),
    68738: ("Steam Vents", None, "Land — Island Mountain"),
    86835: ("Hearth Elemental // Stoke Genius", "{5}{R} // {1}{R}",
            "Creature — Elemental // Sorcery — Adventure"),
    102698: ("Traumatic Critique", "{X}{U}{R}", "Instant"),
    91584: ("Eddymurk Crab", "{5}{U}{U}", "Creature — Elemental Crab"),
    102578: ("Impractical Joke", "{R}", "Sorcery"),
}


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _ingest_fixture(conn) -> None:
    ingest_file(conn, FIXTURE, locale_hint="mdy")


def _insert_card(conn, grp_id, name, *, mana_cost, type_line, produced_mana=None, oracle_text=None):
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, produced_mana, oracle_text) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            grp_id, name, mana_cost, type_line,
            json.dumps(produced_mana) if produced_mana else None, oracle_text,
        ),
    )


def _insert_deck(conn, deck_id, maindeck):
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES (?, 'Test Deck', ?)",
        (deck_id, json.dumps({"maindeck": maindeck})),
    )


# -- fixture-integration tests ------------------------------------------------


def test_no_match_at_all_returns_none(conn):
    assert build_opening_hand_read(conn, deck_id=None) is None


def test_no_decision_pending_returns_none(conn):
    """Every event in the fixture, including our final Accept — nothing is
    pending by the end of it."""
    _ingest_fixture(conn)
    assert build_opening_hand_read(conn, deck_id=None) is None


def test_hand_resolves_with_no_deck_at_all(conn):
    """The hand's own facts need no deck_id — this is what lets the read
    serve before project() has ever produced a matches row."""
    _ingest_fixture(conn)
    # Roll back to just the second offer (the fixture's 8th raw event) by
    # deleting what came after it, the same prefix test_projector_mulligan.py
    # uses to reach mid-sequence states.
    conn.execute("DELETE FROM raw_events WHERE id > 8")
    for grp_id, (name, mana_cost, type_line) in REAL_CARDS.items():
        _insert_card(conn, grp_id, name, mana_cost=mana_cost, type_line=type_line)
    conn.commit()

    read = build_opening_hand_read(conn, deck_id=None)
    assert read is not None
    assert read.seat == 1
    assert read.mulligan_count == 1
    assert tuple(c.grp_id for c in read.cards) == SECOND_OFFER_GRP_IDS
    assert read.land_count == 1  # only Steam Vents
    assert read.verdict is None  # no deck_id -> no band to judge against
    assert any("mulliganed" in c.lower() for c in read.caveats)
    assert any("land band" in c.lower() for c in read.caveats)


def test_arenas_own_card_type_finds_the_land_even_when_unnamed(conn):
    """land_count must not depend on the cards table at all — Steam Vents
    left unnamed here still counts, which v_deck_land_count's em-dash split
    over type_line could never do."""
    _ingest_fixture(conn)
    conn.execute("DELETE FROM raw_events WHERE id > 8")
    conn.commit()  # deliberately: no cards rows inserted at all

    read = build_opening_hand_read(conn, deck_id=None)
    assert read is not None
    assert read.land_count == 1
    steam_vents = next(c for c in read.cards if c.grp_id == 68738)
    assert steam_vents.is_land is True
    assert steam_vents.name is None  # honest gap — never named
    assert read.unnamed_count == len(SECOND_OFFER_GRP_IDS)  # none of the 7 are named


def test_on_the_play_reads_the_first_offers_turn_info(conn):
    """The first offer's turnInfo.activePlayer is 2 (the opponent) — see
    fixture_peek.py show --entry 4 — so we are on the draw."""
    _ingest_fixture(conn)
    conn.execute("DELETE FROM raw_events WHERE id > 5")
    conn.commit()

    read = build_opening_hand_read(conn, deck_id=None)
    assert read is not None
    assert read.mulligan_count == 0
    assert read.on_the_play is False


# -- anchor window (regression) ----------------------------------------------


def test_anchor_has_no_lookback_window(conn):
    """A regression test for the bug this fixed: the old anchor lookup only
    searched the newest 2000 raw_events rows, so a Bo3 whose earlier games
    pushed the match room's own opening event past that window went blind
    on a later game's mulligan — verified against a real database, where 8
    of 154 matches exceeded it. Insert enough filler between the room event
    and the offer to reproduce that shape, and confirm the offer still
    resolves regardless."""
    _insert_test_deck(conn)
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES ('room', 'Player.log', 'event', 'MatchGameRoomStateChangedEvent', ?)",
        (
            '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
            '"gameRoomConfig": {"matchId": "m1"}, '
            '"stateType": "MatchGameRoomStateType_Playing"}}}',
        ),
    )
    conn.executemany(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES (?, 'Player.log', 'event', 'Filler', '{}')",
        [(f"filler-{i}",) for i in range(2200)],
    )
    conn.commit()
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, SPELL_GRP, ["CardType_Creature"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, SPELL_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "late-offer", hand, room=False)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.verdict == "keep"


# -- verdict logic (synthetic — see module docstring) -------------------------

LAND_GRP = 1     # produces U
SPELL_GRP = 2    # {1}{U} creature, cheap
EXPENSIVE_GRP = 3  # {4}{U}{U}, needs more lands than any hand here has
UNNAMED_GRP = 4  # deliberately never inserted into `cards`
UNKNOWN_LAND_GRP = 5  # no produced_mana, oracle_text that is not a chosen-type clause
GENERIC_SPELL_GRP = 6  # {2} creature, no colored pip at all


def _insert_test_deck(conn, deck_id="d1"):
    """The exact land/curve shape test_table_keep.py's own first test
    verifies independently: 17 lands + 43 cheap (MV 2) spells in 60 cards
    gives land_min=2, land_max=4, early_plays=2 — not re-derived here."""
    _insert_card(conn, LAND_GRP, "Test Island", mana_cost=None,
                 type_line="Basic Land — Island", produced_mana=["U"])
    _insert_card(conn, SPELL_GRP, "Cheap Blue Creature", mana_cost="{1}{U}",
                 type_line="Creature — Bear")
    conn.execute(
        "UPDATE cards SET oracle_text = 'Vanilla creature.' WHERE grp_id = ?", (SPELL_GRP,)
    )
    _insert_deck(conn, deck_id, [LAND_GRP] * 17 + [SPELL_GRP] * 43)


def _insert_offer(conn, digest, hand, *, mulligan_count=0, active_player=None, room=True):
    """hand: list of (instance_id, grp_id, card_types) for OUR seat (1); the
    opponent's hand zone is included with ids but no matching gameObjects,
    exactly like a real capture (arena-log.md 11b)."""
    if room:
        conn.execute(
            "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
            "VALUES (?, 'Player.log', 'event', 'MatchGameRoomStateChangedEvent', ?)",
            (
                f"{digest}-room",
                '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
                '"gameRoomConfig": {"matchId": "m1"}, '
                '"stateType": "MatchGameRoomStateType_Playing"}}}',
            ),
        )
    players = [{"systemSeatNumber": 1, "pendingMessageType": "ClientMessageType_MulliganResp"}]
    if mulligan_count:
        players[0]["mulliganCount"] = mulligan_count
    turn_info = {"activePlayer": active_player} if active_player is not None else {}
    game_objects = [
        {"instanceId": iid, "grpId": grp, "zoneId": 31, "cardTypes": types}
        for iid, grp, types in hand
    ]
    zones = [
        {"zoneId": 31, "type": "ZoneType_Hand", "ownerSeatId": 1,
         "objectInstanceIds": [iid for iid, _, _ in hand]},
        {"zoneId": 35, "type": "ZoneType_Hand", "ownerSeatId": 2,
         "objectInstanceIds": [901, 902, 903, 904, 905, 906, 907]},
    ]
    gsm = {
        "type": "GameStateType_Diff", "gameStateId": 2,
        "players": players, "turnInfo": turn_info,
        "zones": zones, "gameObjects": game_objects,
    }
    payload = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": gsm}]}}
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES (?, 'Player.log', 'event', 'GreToClientEvent', ?)",
        (digest, json.dumps(payload)),
    )
    conn.commit()


def test_maindeck_kwarg_is_forwarded_to_build_keep_guide(conn):
    """build_opening_hand_read's own maindeck kwarg does no parsing
    itself -- it is forwarded verbatim to build_keep_guide, whose own tests
    (test_table_keep.py) cover the fallback arithmetic. This only proves the
    forwarding: the exact same land band that appears with a real decks row
    (_insert_test_deck) appears here from the maindeck kwarg alone, with no
    decks row inserted at all."""
    _insert_card(conn, LAND_GRP, "Test Island", mana_cost=None,
                 type_line="Basic Land — Island", produced_mana=["U"])
    _insert_card(conn, SPELL_GRP, "Cheap Blue Creature", mana_cost="{1}{U}",
                 type_line="Creature — Bear")
    conn.execute(
        "UPDATE cards SET oracle_text = 'Vanilla creature.' WHERE grp_id = ?", (SPELL_GRP,)
    )
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, SPELL_GRP, ["CardType_Creature"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, SPELL_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "maindeck-forwarded", hand)

    # No maindeck kwarg, no decks row for "d1" -> no band, same as ever.
    without = build_opening_hand_read(conn, deck_id="d1")
    assert without is not None
    assert without.verdict is None
    assert any("land band" in c.lower() for c in without.caveats)

    maindeck = [LAND_GRP] * 17 + [SPELL_GRP] * 43
    read = build_opening_hand_read(conn, deck_id="d1", maindeck=maindeck)
    assert read is not None
    assert read.land_min == 2 and read.land_max == 4
    assert read.verdict == "keep"
    assert read.keep_guide is not None
    assert read.keep_guide.maindeck_size == 60


def test_verdict_keep_when_lands_in_band_and_early_plays_castable(conn):
    _insert_test_deck(conn)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, SPELL_GRP, ["CardType_Creature"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, SPELL_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "keep", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.land_count == 2
    assert read.land_min == 2 and read.land_max == 4
    assert read.colors_known is True
    # {1}{U} off 2 Islands: 1 U pip + 1 generic, satisfied by turn 2.
    spells = [c for c in read.cards if not c.is_land]
    assert all(c.castable_turn == 2 for c in spells)
    assert read.verdict == "keep"


def test_verdict_mulligan_when_land_count_outside_band(conn):
    _insert_test_deck(conn)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, LAND_GRP, ["CardType_Land"]),
        (5, LAND_GRP, ["CardType_Land"]),
        (6, LAND_GRP, ["CardType_Land"]),
        (7, SPELL_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "flood", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.land_count == 6  # above land_max=4
    assert read.verdict == "mulligan"
    assert any("outside" in r for r in read.reasons)


def test_verdict_mulligan_when_nothing_castable_early(conn):
    _insert_test_deck(conn)
    _insert_card(conn, EXPENSIVE_GRP, "Big Blue Creature", mana_cost="{4}{U}{U}",
                 type_line="Creature — Giant")
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, EXPENSIVE_GRP, ["CardType_Creature"]),
        (4, EXPENSIVE_GRP, ["CardType_Creature"]),
        (5, EXPENSIVE_GRP, ["CardType_Creature"]),
        (6, EXPENSIVE_GRP, ["CardType_Creature"]),
        (7, EXPENSIVE_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "nothing-early", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.land_count == 2  # in band
    spells = [c for c in read.cards if not c.is_land]
    assert all(c.castable_turn is None for c in spells)  # 2 lands can never pay {4}{U}{U}
    assert read.verdict == "mulligan"


def test_verdict_marginal_when_in_band_but_under_the_early_target(conn):
    """early_plays is 2 for this deck; a hand with only 1 castable-by-turn-3
    spell (plus enough lands) is short of ideal without being unkeepable."""
    _insert_test_deck(conn)
    _insert_card(conn, EXPENSIVE_GRP, "Big Blue Creature", mana_cost="{4}{U}{U}",
                 type_line="Creature — Giant")
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, EXPENSIVE_GRP, ["CardType_Creature"]),
        (6, EXPENSIVE_GRP, ["CardType_Creature"]),
        (7, EXPENSIVE_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "marginal", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.land_count == 3  # in [2, 4]
    assert read.verdict == "marginal"


def test_verdict_withheld_when_bounds_disagree_on_an_unknown_lands_colors(conn):
    """A land in the cards table with no produced_mana at all, and no
    oracle_text either (so effects.chosen_basic_type_colors has nothing to
    read) — the honest gap migrations/021_produced_mana.sql documents. Its
    color is never resolved, so the read brackets it: pessimistic (both
    lands colorless) can never pay the {1}{U} filler's U pip, so nothing is
    castable early and the pessimistic verdict is "mulligan"; optimistic
    (the unknown land is any color) pays it by turn 2 off 2 lands, castable
    for all 5, which clears this deck's early_plays=2 target with no
    key_plays on file, landing on "keep". The two bounds disagree, so the
    published verdict is withheld with a caveat spelling out the condition —
    a real improvement over the old all-or-nothing withholding this
    replaces, but still not a guess (rule 4)."""
    _insert_card(conn, LAND_GRP, "Test Island", mana_cost=None,
                 type_line="Basic Land — Island", produced_mana=None)
    _insert_card(conn, SPELL_GRP, "Cheap Blue Creature", mana_cost="{1}{U}",
                 type_line="Creature — Bear")
    conn.execute(
        "UPDATE cards SET oracle_text = 'Vanilla creature.' WHERE grp_id = ?", (SPELL_GRP,)
    )
    _insert_deck(conn, "d1", [LAND_GRP] * 17 + [SPELL_GRP] * 43)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, SPELL_GRP, ["CardType_Creature"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, SPELL_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "no-colors", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.colors_known is False
    assert read.verdict is None
    assert read.reasons == ()  # no chosen-type land in this hand, so nothing survives
    # per-card fields always show the pessimistic (colorless) reading:
    spells = [c for c in read.cards if not c.is_land]
    assert all(c.castable_turn is None for c in spells)
    caveat = next(c for c in read.caveats if "Test Island" in c)
    assert "Keep if Test Island makes the colors this hand needs" in caveat
    assert "Mulligan if it doesn't" in caveat
    assert "no mana production on file" in caveat
    assert "scryfall" in caveat.lower()  # no oracle_text on file either
    # the evidence still renders even though the verdict is withheld:
    assert read.land_count == 2
    assert len(read.cards) == 7


def test_verdict_published_when_an_unknown_lands_color_cannot_matter(conn):
    """The bounds only ever disagree when the unresolved land's real color
    could change the call. Here every spell in hand costs a pure generic
    {2} — no colored pip at all — so 2 lands pay it by turn 2 whether the
    second (unresolved) land is read as colorless or as every color; both
    passes land on "keep". The caveat still names the gap (never silently
    drops it), but no longer withholds the call over a color that provably
    never mattered to this hand."""
    _insert_test_deck(conn)
    _insert_card(conn, UNKNOWN_LAND_GRP, "Test Unknown Land", mana_cost=None,
                 type_line="Land", oracle_text="This land enters tapped.")
    _insert_card(conn, GENERIC_SPELL_GRP, "Generic Creature", mana_cost="{2}",
                 type_line="Creature — Bear", oracle_text="Vanilla creature.")
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, UNKNOWN_LAND_GRP, ["CardType_Land"]),
        (3, GENERIC_SPELL_GRP, ["CardType_Creature"]),
        (4, GENERIC_SPELL_GRP, ["CardType_Creature"]),
        (5, GENERIC_SPELL_GRP, ["CardType_Creature"]),
        (6, GENERIC_SPELL_GRP, ["CardType_Creature"]),
        (7, GENERIC_SPELL_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "unknown-doesnt-matter", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.colors_known is False
    assert read.land_count == 2
    spells = [c for c in read.cards if not c.is_land]
    assert all(c.castable_turn == 2 for c in spells)  # {2} off any 2 lands, any color
    assert read.verdict == "keep"
    caveat = next(c for c in read.caveats if "Test Unknown Land" in c)
    assert "no mana production on file" in caveat
    assert "the call is the same whether or not it makes colored mana" in caveat
    assert "scryfall" not in caveat.lower()  # oracle_text is on file, it just doesn't match


# Real oracle text for Multiversal Passage (grp_id 97998), read read-only
# from data/sensei-top.db's own `cards` table since this land is not in any
# fixture: "As this land enters, choose a basic land type. Then you may pay
# 2 life. If you don't, it enters tapped.\nThis land is the chosen type."
_PASSAGE_STYLE_TEXT = (
    "As this land enters, choose a basic land type. Then you may pay 2 life. "
    "If you don't, it enters tapped.\nThis land is the chosen type."
)

PASSAGE_GRP = 30  # no produced_mana, but its own text names a real color set
RED_LAND_GRP = 31  # produces R
RED1_GRP = 32     # {R} creature
WHITE2_GRP = 33    # {1}{W} creature
FILLER_GRP = 34    # {1} creature, generic only


def test_verdict_not_withheld_for_a_chosen_basic_type_land(conn):
    """A Multiversal-Passage-style land has no produced_mana on file (Scryfall
    exports nothing for it — it has no fixed mana ability), but its own text
    still names a real color set: effects.chosen_basic_type_colors resolves
    it, so this hand has no unresolved land at all and colors_known is True.
    2 lands (Passage + a known red source) can pay the {R} 1-drop (Passage
    covers the pip) and the {1}{W} 2-drop (Passage covers W, the other land
    covers the generic) by turn 2; with the 3 generic fillers also castable
    turn 1, castable_early clears this deck's early_plays=2 target with no
    key_plays on file, landing on "keep" — not the None the old all-or-
    nothing withholding used to force onto every hand holding this land."""
    _insert_test_deck(conn)
    _insert_card(conn, PASSAGE_GRP, "Test Passage", mana_cost=None,
                 type_line="Land", produced_mana=None, oracle_text=_PASSAGE_STYLE_TEXT)
    _insert_card(conn, RED_LAND_GRP, "Test Mountain", mana_cost=None,
                 type_line="Basic Land — Mountain", produced_mana=["R"])
    _insert_card(conn, RED1_GRP, "Test Red One-Drop", mana_cost="{R}",
                 type_line="Creature — Goblin", oracle_text="Vanilla creature.")
    _insert_card(conn, WHITE2_GRP, "Test White Two-Drop", mana_cost="{1}{W}",
                 type_line="Creature — Soldier", oracle_text="Vanilla creature.")
    _insert_card(conn, FILLER_GRP, "Test Filler", mana_cost="{1}",
                 type_line="Creature — Bear", oracle_text="Vanilla creature.")
    hand = [
        (1, PASSAGE_GRP, ["CardType_Land"]),
        (2, RED_LAND_GRP, ["CardType_Land"]),
        (3, RED1_GRP, ["CardType_Creature"]),
        (4, WHITE2_GRP, ["CardType_Creature"]),
        (5, FILLER_GRP, ["CardType_Creature"]),
        (6, FILLER_GRP, ["CardType_Creature"]),
        (7, FILLER_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "chosen-type-land", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.colors_known is True
    assert read.land_count == 2
    assert read.verdict == "keep"
    assert any(
        r == "Test Passage counted as whichever basic type each spell needs — you choose it "
        "once, as it enters"
        for r in read.reasons
    )


def test_verdict_withheld_when_a_card_is_unnamed(conn):
    _insert_test_deck(conn)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, SPELL_GRP, ["CardType_Creature"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, UNNAMED_GRP, ["CardType_Sorcery"]),
    ]
    _insert_offer(conn, "unnamed", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.unnamed_count == 1
    assert read.verdict is None
    assert any("card table" in c.lower() for c in read.caveats)


# -- reduced_castable_turn (fuel-in-hand castability) -----------------------
#
# Real oracle text from the Spellementals fixtures (data/sensei-top.db, cards
# 91584/98392) — the two reduction clauses effects.cost_reduction()
# recognizes.
_CRAB_STYLE_TEXT = (
    "This spell costs {1} less to cast for each instant and sorcery card in your graveyard."
)
_SUNDERFLOCK_STYLE_TEXT = (
    "This spell costs {X} less to cast, where X is the greatest mana value "
    "among Elementals you control."
)

REDUCE_GRP = 10   # {3}{U} creature, Crab-style per-card graveyard reduction
INSTANT_GRP = 11  # {U} instant, the fuel
SUNDERFLOCK_GRP = 12  # {7}{U}{U} creature, board_elemental_mv reduction
ELEMENTAL_FRIEND_GRP = 13  # {1}{U} Elemental creature, no reduction of its own


def test_reduced_castable_turn_graveyard_fuel_beats_the_unreachable_printed_cost(conn):
    """3 lands can never pay this card's printed {3}{U} (needs 4): unreduced
    castable_turn is honestly None. But this same hand holds 3 cheap
    instants — by turn 2 all 3 are already castable off this hand's own
    lands (turn <= 1), so the {1}-less clause has already knocked the
    generic cost to 0 by then, leaving only the U pip a 2nd land pays."""
    _insert_card(conn, LAND_GRP, "Test Island", mana_cost=None,
                 type_line="Basic Land — Island", produced_mana=["U"])
    _insert_card(conn, INSTANT_GRP, "Test Cantrip", mana_cost="{U}", type_line="Instant")
    _insert_card(conn, REDUCE_GRP, "Test Reducer", mana_cost="{3}{U}",
                 type_line="Creature — Elemental", oracle_text=_CRAB_STYLE_TEXT)
    _insert_deck(conn, "d1", [LAND_GRP] * 17 + [INSTANT_GRP] * 43)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, INSTANT_GRP, ["CardType_Instant"]),
        (5, INSTANT_GRP, ["CardType_Instant"]),
        (6, INSTANT_GRP, ["CardType_Instant"]),
        (7, REDUCE_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "graveyard-fuel", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    reducer = next(c for c in read.cards if c.grp_id == REDUCE_GRP)
    assert reducer.castable_turn is None  # printed {3}{U} needs 4 lands; hand has 3
    assert reducer.reduced_castable_turn == 2


def test_reduced_castable_turn_withheld_with_no_fuel_in_hand(conn):
    """Same reducer, no instants in hand at all: nothing to feed it, so the
    reduced search finds the same (unreachable) answer as the printed cost."""
    _insert_card(conn, LAND_GRP, "Test Island", mana_cost=None,
                 type_line="Basic Land — Island", produced_mana=["U"])
    _insert_card(conn, REDUCE_GRP, "Test Reducer", mana_cost="{3}{U}",
                 type_line="Creature — Elemental", oracle_text=_CRAB_STYLE_TEXT)
    _insert_card(conn, SPELL_GRP, "Cheap Blue Creature", mana_cost="{1}{U}",
                 type_line="Creature — Bear")
    conn.execute(
        "UPDATE cards SET oracle_text = 'Vanilla creature.' WHERE grp_id = ?", (SPELL_GRP,)
    )
    _insert_deck(conn, "d1", [LAND_GRP] * 17 + [SPELL_GRP] * 43)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, REDUCE_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "no-fuel", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    reducer = next(c for c in read.cards if c.grp_id == REDUCE_GRP)
    assert reducer.castable_turn is None
    assert reducer.reduced_castable_turn is None


def test_reduced_castable_turn_board_elemental_fuel(conn):
    """Sunderflock-style reduction is a board-state lookup, not a per-card
    count: expressed only as 'the turn after another Elemental resolves'.
    The Elemental friend here needs 2 lands for its own {1}{U} (castable
    turn 2), so Sunderflock is expressed as castable turn 3 — one turn
    later — regardless of what the printed 9-mana cost alone would say."""
    _insert_card(conn, LAND_GRP, "Test Island", mana_cost=None,
                 type_line="Basic Land — Island", produced_mana=["U"])
    _insert_card(conn, ELEMENTAL_FRIEND_GRP, "Test Elemental Friend", mana_cost="{1}{U}",
                 type_line="Creature — Elemental")
    _insert_card(conn, SUNDERFLOCK_GRP, "Test Sunderflock", mana_cost="{7}{U}{U}",
                 type_line="Creature — Elemental", oracle_text=_SUNDERFLOCK_STYLE_TEXT)
    _insert_deck(conn, "d1", [LAND_GRP] * 17 + [ELEMENTAL_FRIEND_GRP] * 43)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, LAND_GRP, ["CardType_Land"]),
        (5, LAND_GRP, ["CardType_Land"]),
        (6, ELEMENTAL_FRIEND_GRP, ["CardType_Creature"]),
        (7, SUNDERFLOCK_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "board-elemental", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    friend = next(c for c in read.cards if c.grp_id == ELEMENTAL_FRIEND_GRP)
    sunderflock = next(c for c in read.cards if c.grp_id == SUNDERFLOCK_GRP)
    assert friend.castable_turn == 2
    assert sunderflock.castable_turn is None  # printed {7}{U}{U} needs 9 lands
    assert sunderflock.reduced_castable_turn == 3  # friend's turn 2, plus 1


def test_reduced_castable_turn_withheld_when_no_other_elemental_in_hand(conn):
    """The Sunderflock-style card alone, with only vanilla lands and a
    non-Elemental creature around it: nothing to feed the board lookup, so
    this is withheld rather than guessed at some default reduction."""
    _insert_card(conn, LAND_GRP, "Test Island", mana_cost=None,
                 type_line="Basic Land — Island", produced_mana=["U"])
    _insert_card(conn, SPELL_GRP, "Cheap Blue Creature", mana_cost="{1}{U}",
                 type_line="Creature — Bear")
    conn.execute(
        "UPDATE cards SET oracle_text = 'Vanilla creature.' WHERE grp_id = ?", (SPELL_GRP,)
    )
    _insert_card(conn, SUNDERFLOCK_GRP, "Test Sunderflock", mana_cost="{7}{U}{U}",
                 type_line="Creature — Elemental", oracle_text=_SUNDERFLOCK_STYLE_TEXT)
    _insert_deck(conn, "d1", [LAND_GRP] * 17 + [SPELL_GRP] * 43)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, SUNDERFLOCK_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "no-other-elemental", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    sunderflock = next(c for c in read.cards if c.grp_id == SUNDERFLOCK_GRP)
    assert sunderflock.reduced_castable_turn is None


def test_reduced_castable_turn_is_none_for_a_card_with_no_reduction_clause(conn):
    _insert_test_deck(conn)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, SPELL_GRP, ["CardType_Creature"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, SPELL_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "no-reduction", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert all(c.reduced_castable_turn is None for c in read.cards if not c.is_land)


def test_reduced_castable_turn_unparsed_shape_withholds_rather_than_guesses(conn):
    """A 'less to cast' clause of an unrecognized shape (effects.py's
    UNPARSED_REDUCTION) must not be treated as any specific fuel kind."""
    _insert_card(conn, LAND_GRP, "Test Island", mana_cost=None,
                 type_line="Basic Land — Island", produced_mana=["U"])
    _insert_card(conn, REDUCE_GRP, "Test Weird Reducer", mana_cost="{3}{U}",
                 type_line="Creature — Elemental",
                 oracle_text="This spell costs {2} less to cast if you control a Dragon.")
    _insert_deck(conn, "d1", [LAND_GRP] * 17 + [REDUCE_GRP] * 43)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, LAND_GRP, ["CardType_Land"]),
        (5, LAND_GRP, ["CardType_Land"]),
        (6, LAND_GRP, ["CardType_Land"]),
        (7, REDUCE_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "unparsed", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    reducer = next(c for c in read.cards if c.grp_id == REDUCE_GRP)
    assert reducer.castable_turn == 4  # printed {3}{U}, plenty of lands
    assert reducer.reduced_castable_turn is None


# -- pressure / mulligan brake (the deck's own evidence moves the verdict) --
#
# key_plays/mulligan_cost come from table/keep.py's own play evidence
# (tested independently in tests/test_table_keep.py), so these tests build
# just enough match/game/card_event history for build_keep_guide to produce
# them, reusing the same insert-row style tests/test_table_keep.py's own
# key_plays/mulligan_cost tests use.

THREAT_GRP = 20  # {2}{U} creature, >=3 copies -- this deck's own key play


def _insert_test_deck_with_threat(conn, deck_id="d1"):
    """Same land/curve shape as _insert_test_deck (17 lands, land_min=2,
    land_max=4, early_plays=2 -- see test_table_keep.py), with 3 of the 43
    nonland slots swapped from the cheap SPELL_GRP filler to a pricier
    THREAT_GRP creature so _choose_key_cards (highest mana value first,
    among >=3-copy cards) picks it as this deck's one key play."""
    _insert_card(conn, LAND_GRP, "Test Island", mana_cost=None,
                 type_line="Basic Land — Island", produced_mana=["U"])
    _insert_card(conn, SPELL_GRP, "Cheap Blue Creature", mana_cost="{1}{U}",
                 type_line="Creature — Bear")
    conn.execute(
        "UPDATE cards SET oracle_text = 'Vanilla creature.' WHERE grp_id = ?", (SPELL_GRP,)
    )
    _insert_card(conn, THREAT_GRP, "Test Threat", mana_cost="{2}{U}",
                 type_line="Creature — Elemental", oracle_text="Flying.")
    _insert_deck(conn, deck_id, [LAND_GRP] * 17 + [SPELL_GRP] * 40 + [THREAT_GRP] * 3)


def _insert_match_row(conn, match_id, deck_id="d1"):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, 1, 2, 'u', 'n', 't', 't', "
        "'win', 1, 0, 'r')",
        (match_id, deck_id),
    )


def _insert_game_row(conn, match_id, result, *, self_mulligans):
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 10, ?, 0)",
        (match_id, result, self_mulligans),
    )


def _insert_card_event_row(conn, match_id, turn_number, grp_id):
    conn.execute(
        "INSERT INTO card_events (match_id, game_number, seq, turn_number, seat, grp_id, "
        "category) VALUES (?, 1, 0, ?, 1, ?, 'Resolve')",
        (match_id, turn_number, grp_id),
    )


def test_verdict_pressure_present_keeps_the_keep_call(conn):
    """In band, early plays met (2 cheap creatures), and the hand also holds
    this deck's one key play, castable off it -- stays "keep", now with a
    reason naming the threat and its measured record."""
    _insert_test_deck_with_threat(conn)
    for i in range(10):  # 10 decided games, >= _MIN_EVIDENCE_GAMES: Threat always
        match_id = f"m{i}"  # resolves turn_number 8 (player turn 4 -> "by T4"), always wins
        _insert_match_row(conn, match_id)
        _insert_game_row(conn, match_id, "win", self_mulligans=0)
        _insert_card_event_row(conn, match_id, 8, THREAT_GRP)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, LAND_GRP, ["CardType_Land"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, THREAT_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "pressure-present", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.land_count == 4  # in [2, 4]
    threat = next(c for c in read.cards if c.grp_id == THREAT_GRP)
    assert threat.castable_turn == 3  # {2}{U}, 3 total mana off 3 of the 4 lands
    assert read.verdict == "keep"
    assert any("Test Threat" in r and "10-0" in r for r in read.reasons)


def test_verdict_pressure_absent_downgrades_keep_to_marginal(conn):
    """Same deck and the same measured key play, but this hand never drew
    it: lands in band, early plays met by cheap creatures alone -- what used
    to be an unconditional "keep" now drops to "marginal" for lack of any
    evidence-backed threat, per the plan's own rule."""
    _insert_test_deck_with_threat(conn)
    for i in range(10):
        match_id = f"m{i}"
        _insert_match_row(conn, match_id)
        _insert_game_row(conn, match_id, "win", self_mulligans=0)
        _insert_card_event_row(conn, match_id, 8, THREAT_GRP)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, SPELL_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "pressure-absent", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.land_count == 3  # in [2, 4]
    assert read.verdict == "marginal"
    assert any("no threat like Test Threat" in r for r in read.reasons)


def test_mulligan_brake_holds_a_marginal_hand_rather_than_shipping_it(conn):
    """20 decided games: kept-seven at 60% (6-4), mulliganed at 30% (3-7) --
    a 30-point gap, clearing _MULLIGAN_BRAKE_POINTS (13). A hand with only 1
    of 2 needed early plays and no reachable key play would, on the plain
    land-band/early-play rule, be "marginal" already -- the brake's job here
    is keeping it there rather than letting the missing pressure push it
    further down to "mulligan"."""
    _insert_test_deck_with_threat(conn)
    _insert_card(conn, EXPENSIVE_GRP, "Big Blue Creature", mana_cost="{4}{U}{U}",
                 type_line="Creature — Giant")
    for i in range(10):  # kept at seven: 6 wins, 4 losses; Threat resolves every time
        match_id = f"kept{i}"
        _insert_match_row(conn, match_id)
        _insert_game_row(conn, match_id, "win" if i < 6 else "loss", self_mulligans=0)
        _insert_card_event_row(conn, match_id, 8, THREAT_GRP)
    for i in range(10):  # mulliganed to six: 3 wins, 7 losses; Threat never resolves
        match_id = f"mull{i}"
        _insert_match_row(conn, match_id)
        _insert_game_row(conn, match_id, "win" if i < 3 else "loss", self_mulligans=1)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, EXPENSIVE_GRP, ["CardType_Creature"]),
        (6, EXPENSIVE_GRP, ["CardType_Creature"]),
        (7, EXPENSIVE_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "brake-holds", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.land_count == 3  # in [2, 4]
    assert read.verdict == "marginal"
    assert any("13 points" in r for r in read.reasons)


def test_no_mulligan_brake_lets_a_pressureless_marginal_hand_slide_to_mulligan(conn):
    """Same hand shape as the brake test, but kept-seven and mulliganed win
    at the same 50% rate -- no gap for the brake to cite, so the missing
    pressure is free to push this hand down to "mulligan"."""
    _insert_test_deck_with_threat(conn)
    _insert_card(conn, EXPENSIVE_GRP, "Big Blue Creature", mana_cost="{4}{U}{U}",
                 type_line="Creature — Giant")
    for i in range(10):  # kept at seven: 5-5
        match_id = f"kept{i}"
        _insert_match_row(conn, match_id)
        _insert_game_row(conn, match_id, "win" if i < 5 else "loss", self_mulligans=0)
        _insert_card_event_row(conn, match_id, 8, THREAT_GRP)
    for i in range(10):  # mulliganed to six: 5-5, same rate
        match_id = f"mull{i}"
        _insert_match_row(conn, match_id)
        _insert_game_row(conn, match_id, "win" if i < 5 else "loss", self_mulligans=1)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, EXPENSIVE_GRP, ["CardType_Creature"]),
        (6, EXPENSIVE_GRP, ["CardType_Creature"]),
        (7, EXPENSIVE_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "no-brake", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.land_count == 3  # in [2, 4]
    assert read.verdict == "mulligan"
    assert not any("points" in r for r in read.reasons)


def test_no_key_plays_leaves_the_pre_layer_3_verdict_unchanged(conn):
    """Below _MIN_EVIDENCE_GAMES (no matches played at all here): thin
    evidence means the pressure/brake machinery never engages, and the
    land-band/early-play verdict stands exactly as
    test_verdict_keep_when_lands_in_band_and_early_plays_castable pins it."""
    _insert_test_deck_with_threat(conn)
    hand = [
        (1, LAND_GRP, ["CardType_Land"]),
        (2, LAND_GRP, ["CardType_Land"]),
        (3, LAND_GRP, ["CardType_Land"]),
        (4, SPELL_GRP, ["CardType_Creature"]),
        (5, SPELL_GRP, ["CardType_Creature"]),
        (6, SPELL_GRP, ["CardType_Creature"]),
        (7, SPELL_GRP, ["CardType_Creature"]),
    ]
    _insert_offer(conn, "no-evidence", hand)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.verdict == "keep"
    assert not any("Test Threat" in r for r in read.reasons)


def test_mulligan_note_names_how_many_times_and_that_its_still_a_fresh_seven(conn):
    _insert_test_deck(conn)
    hand = [(i, SPELL_GRP, ["CardType_Creature"]) for i in range(1, 6)] + [
        (6, LAND_GRP, ["CardType_Land"]), (7, LAND_GRP, ["CardType_Land"]),
    ]
    _insert_offer(conn, "mull2", hand, mulligan_count=2)

    read = build_opening_hand_read(conn, deck_id="d1")
    assert read is not None
    assert read.mulligan_count == 2
    assert len(read.cards) == 7  # London mulligan: always a fresh 7
    note = read.caveats[0]
    assert "2 times" in note
    assert "bottom 2 cards" in note
