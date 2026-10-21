"""infer_formats() and narrowest_format() (archetypes/classify.py), and the
tables classify_matches() rebuilds from them (migrations/056_format_fit.sql).

Every card's legality is read from the fixture
tests/fixtures/scryfall_format_printings.jsonl: real Scryfall `default_cards`
objects whose `legalities` differ by format. The few cards no fixture line
carries (a Premodern-only card, a card not legal anywhere) are built here in
the same shape and say so. Every expected fit below is read off those
`legalities` objects, card by card:

  - the five Foundations rares (Drakuseth, Painful Quandary, Phyrexian Arena,
    Ayli, Loot) are legal in Standard, Pioneer, Modern, Legacy and Vintage,
    not_legal in Pauper; all but Phyrexian Arena are not_legal in Premodern;
  - the five Foundations commons (Crusader of Odric, Beast-Kin Ranger,
    Dazzling Angel, Sanguine Indulgence, Bushwhack) are legal everywhere but
    Premodern;
  - Mother of Runes is legal in Legacy, Vintage and Premodern only;
  - Mox Opal and Reckless Waif are legal in Modern, Legacy and Vintage only;
  - Birthing Pod is banned in Modern, legal in Legacy and Vintage;
  - True-Name Nemesis is legal in Legacy and Vintage only;
  - Thought Scour is legal in Modern, Pauper, Legacy and Vintage.

The schema is built directly rather than by ingesting a log, as
test_corpus_naming.py does: this needs projected rows, not a capture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sensei_top.archetypes.classify import (
    FORMAT_REASONS,
    FormatInference,
    classify_matches,
    infer_formats,
    narrowest_format,
)
from sensei_top.db import open_database
from sensei_top.formats import FORMATS

_FIXTURE = Path(__file__).parent / "fixtures" / "scryfall_format_printings.jsonl"

RARES = (
    "Drakuseth, Maw of Flames", "Painful Quandary", "Phyrexian Arena",
    "Ayli, Eternal Pilgrim", "Loot, Exuberant Explorer",
)
COMMONS = (
    "Crusader of Odric", "Beast-Kin Ranger", "Dazzling Angel", "Sanguine Indulgence",
    "Bushwhack",
)
OTHER_RARES = tuple(name for name in RARES if name != "Phyrexian Arena")
REAL_NAMES = (
    "Thought Scour", "Mother of Runes", "Mox Opal", "True-Name Nemesis",
    "Reckless Waif // Merciless Predator", "Birthing Pod", *RARES, *COMMONS,
)


def _premodern_only(name: str) -> dict:
    """A card no fixture line carries, in the fixture's shape: legal in
    Premodern and the two formats that contain it, not_legal elsewhere."""
    legal = {"premodern", "legacy", "vintage"}
    return {
        "name": name, "type_line": "Creature — Test",
        "legalities": {
            fmt.lower(): "legal" if fmt.lower() in legal else "not_legal" for fmt in FORMATS
        },
    }


def _legal_nowhere(name: str) -> dict:
    """A card not_legal in all seven formats, in the fixture's shape."""
    return {
        "name": name, "type_line": "Creature — Test",
        "legalities": {fmt.lower(): "not_legal" for fmt in FORMATS},
    }


def _fixture_cards() -> dict[str, dict]:
    """The fixture's objects by name, one per name: Thought Scour's two
    printings carry the same legalities, so the first stands for both."""
    cards: dict[str, dict] = {}
    for line in _FIXTURE.read_text().splitlines():
        if line.strip():
            card = json.loads(line)
            cards.setdefault(card["name"], card)
    return cards


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "match_formats.db")
    yield c
    c.close()


class Seeder:
    """Writes `cards` and `card_legality` rows from Scryfall-shaped objects
    and hands out one grp_id per name."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self.fixture = _fixture_cards()
        self.ids: dict[str, int] = {}

    def card(self, obj: dict) -> int:
        name = obj["name"]
        if name in self.ids:
            return self.ids[name]
        grp_id = 900001 + len(self.ids)
        self.conn.execute(
            "INSERT INTO cards (grp_id, name, type_line) VALUES (?, ?, ?)",
            (grp_id, name, obj["type_line"]),
        )
        for fmt in FORMATS:
            self.conn.execute(
                "INSERT INTO card_legality (grp_id, format, legality) VALUES (?, ?, ?)",
                (grp_id, fmt, obj["legalities"][fmt.lower()]),
            )
        self.ids[name] = grp_id
        return grp_id

    def named(self, *names: str) -> list[int]:
        return [self.card(self.fixture[name]) for name in names]


@pytest.fixture
def seed(conn):
    return Seeder(conn)


def _mtgo_match(conn, match_id: str, result: str | None = "win") -> None:
    conn.execute(
        "INSERT INTO matches (match_id, source, self_seat, opponent_seat, started_at, result) "
        "VALUES (?, 'mtgo', 1, 2, '2026-08-01T00:00:00Z', ?)",
        (match_id, result),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, turn_count, self_mulligans, "
        "opp_mulligans) VALUES (?, 1, 1, 6, 0, 0)",
        (match_id,),
    )


def _reveal(conn, match_id: str, grp_ids, *, seat: int = 2) -> None:
    start = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM card_events WHERE match_id = ?", (match_id,)
    ).fetchone()[0]
    for i, grp_id in enumerate(grp_ids, start=start + 1):
        conn.execute(
            "INSERT INTO card_events (match_id, game_number, seq, turn_number, seat, grp_id, "
            "category, zone_src, zone_dest) VALUES (?, 1, ?, 1, ?, ?, 'Zone', NULL, NULL)",
            (match_id, i, seat, grp_id),
        )


def _reveal_unresolved(conn, match_id: str, names) -> None:
    """Card events MTGO's projector could not resolve: grp_id NULL, the
    transcript's name in mtgo_name (migration 060)."""
    start = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM card_events WHERE match_id = ?", (match_id,)
    ).fetchone()[0]
    for i, name in enumerate(names, start=start + 1):
        conn.execute(
            "INSERT INTO card_events (match_id, game_number, seq, turn_number, seat, grp_id, "
            "category, mtgo_name) VALUES (?, 1, ?, 1, 2, NULL, 'Zone', ?)",
            (match_id, i, name),
        )


def _infer(conn, match_id: str) -> FormatInference:
    return infer_formats(conn)[match_id]


def test_five_foundations_rares_give_standard(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", seed.named(*RARES))

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Standard", "Pioneer", "Modern", "Legacy", "Vintage"}), "Standard", "fit"
    )


def test_five_foundations_commons_are_ambiguous_between_standard_and_pauper(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", seed.named(*COMMONS))

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Standard", "Pioneer", "Modern", "Pauper", "Legacy", "Vintage"}),
        None, "ambiguous",
    )


def test_mother_of_runes_with_premodern_cards_gives_premodern(conn, seed):
    _mtgo_match(conn, "m1")
    built = [seed.card(_premodern_only(f"Premodern Test Card {n}")) for n in range(3)]
    _reveal(conn, "m1", [*seed.named("Mother of Runes", "Phyrexian Arena"), *built])

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Premodern", "Legacy", "Vintage"}), "Premodern", "fit"
    )


def test_mother_of_runes_with_foundations_rares_gives_legacy(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", seed.named("Mother of Runes", *OTHER_RARES))

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Legacy", "Vintage"}), "Legacy", "fit"
    )


def test_a_card_legal_nowhere_gives_no_fit(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", [*seed.named(*COMMONS[:4]), seed.card(_legal_nowhere("Nowhere Card"))])

    assert _infer(conn, "m1") == FormatInference(frozenset(), None, "no_fit")


def test_mox_opal_and_reckless_waif_with_rares_give_modern(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", seed.named("Mox Opal", "Reckless Waif // Merciless Predator", *RARES[:3]))

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Modern", "Legacy", "Vintage"}), "Modern", "fit"
    )


def test_a_card_banned_in_modern_still_fits_modern(conn, seed):
    """Scryfall's ban list is today's, so a ban never rules a format out."""
    _mtgo_match(conn, "m1")
    _reveal(
        conn, "m1",
        seed.named("Birthing Pod", "Reckless Waif // Merciless Predator", *RARES[:3]),
    )

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Modern", "Legacy", "Vintage"}), "Modern", "fit"
    )


def test_true_name_nemesis_with_modern_cards_gives_legacy(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(
        conn, "m1",
        seed.named("True-Name Nemesis", "Mox Opal", "Reckless Waif // Merciless Predator",
                   *RARES[:2]),
    )

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Legacy", "Vintage"}), "Legacy", "fit"
    )


def test_thought_scour_with_commons_is_ambiguous_between_modern_and_pauper(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", seed.named("Thought Scour", *COMMONS[:4]))

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Modern", "Pauper", "Legacy", "Vintage"}), None, "ambiguous"
    )


def test_each_format_is_judged_on_its_own_legality_rows(conn, seed):
    """Mox Opal is not_legal in Standard and legal in Vintage. Its Standard
    row alone must rule the match out of Standard, and its Vintage row must
    not rule it out of Vintage: neither row stands in for another format's."""
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", seed.named(*RARES))
    _reveal(conn, "m1", seed.named("Mox Opal"), seat=1)

    inference = _infer(conn, "m1")
    assert "Standard" not in inference.fit
    assert "Pioneer" not in inference.fit
    assert "Vintage" in inference.fit
    assert inference.format == "Modern"


def test_fewer_than_five_distinct_cards_is_too_few_and_keeps_the_fit(conn, seed):
    _mtgo_match(conn, "m1")
    grp_ids = seed.named(*RARES[:4])
    _reveal(conn, "m1", grp_ids)
    _reveal(conn, "m1", grp_ids[:1])

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Standard", "Pioneer", "Modern", "Legacy", "Vintage"}),
        None, "too_few_cards",
    )


def test_a_match_with_no_revealed_cards_is_too_few(conn):
    _mtgo_match(conn, "m1")

    assert _infer(conn, "m1") == FormatInference(frozenset(FORMATS), None, "too_few_cards")


def test_an_unresolved_card_event_is_unresolved_cards(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", [*seed.named(*RARES), None])

    assert _infer(conn, "m1") == FormatInference(frozenset(), None, "unresolved_cards")


def test_an_unresolved_token_is_left_out_of_the_fit(conn, seed):
    """MTGO's token spellings "Map Token" and "Wizard Token" were observed
    unresolved in a real MTGO history. A token says nothing
    about the format, resolved or not, so the five rares decide it."""
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", seed.named(*RARES))
    _reveal_unresolved(conn, "m1", ["Map Token", "Wizard Token"])

    assert _infer(conn, "m1") == FormatInference(
        frozenset({"Standard", "Pioneer", "Modern", "Legacy", "Vintage"}), "Standard", "fit"
    )


@pytest.mark.parametrize("marker", ["The Initiative", "Undercity"])
def test_an_unresolved_game_marker_is_left_out_of_the_fit(conn, seed, marker):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", seed.named(*RARES))
    _reveal_unresolved(conn, "m1", [marker])

    assert _infer(conn, "m1").reason == "fit"


def test_an_unresolved_card_name_still_blocks_beside_a_token(conn, seed):
    """Mox Opal, unresolved (as when the card db lacks it), could rule
    Standard out; it blocks the match whatever else is set aside. A name
    that merely contains "Token" is not MTGO's token spelling."""
    _mtgo_match(conn, "card")
    _reveal(conn, "card", seed.named(*RARES))
    _reveal_unresolved(conn, "card", ["Map Token", "Mox Opal"])
    _mtgo_match(conn, "not_suffix")
    _reveal(conn, "not_suffix", seed.named(*RARES))
    _reveal_unresolved(conn, "not_suffix", ["Token Test Card"])

    inferences = infer_formats(conn)
    assert inferences["card"] == FormatInference(frozenset(), None, "unresolved_cards")
    assert inferences["not_suffix"].reason == "unresolved_cards"


def test_unresolved_tokens_alone_are_too_few_cards(conn):
    """Left out of the fit means left out of the count too: a match whose
    only events are unresolved tokens has revealed no card."""
    _mtgo_match(conn, "m1")
    _reveal_unresolved(conn, "m1", ["Map Token"])

    assert _infer(conn, "m1") == FormatInference(frozenset(FORMATS), None, "too_few_cards")


def test_a_card_missing_one_formats_row_is_unknown_legality(conn, seed):
    """Six of seven rows on file is still unknown: the missing format could
    be the one that rules the match out."""
    _mtgo_match(conn, "m1")
    grp_ids = seed.named(*RARES)
    conn.execute(
        "DELETE FROM card_legality WHERE grp_id = ? AND format = 'Premodern'", (grp_ids[0],)
    )
    _reveal(conn, "m1", grp_ids)

    assert _infer(conn, "m1") == FormatInference(frozenset(), None, "unknown_legality")


def test_a_grp_id_with_no_cards_row_is_unknown_legality(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", [*seed.named(*RARES), 424242])

    assert _infer(conn, "m1") == FormatInference(frozenset(), None, "unknown_legality")


def test_the_reasons_are_checked_in_s0s_order(conn, seed):
    """unresolved_cards, unknown_legality, no_fit, too_few_cards, then fit or
    ambiguous: each match below carries every later problem as well as the
    one it reports."""
    assert FORMAT_REASONS == (
        "unresolved_cards", "unknown_legality", "no_fit", "too_few_cards", "fit", "ambiguous",
    )
    nowhere = seed.card(_legal_nowhere("Nowhere Card"))
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (800001, 'No Rows', 'Instant')"
    )

    _mtgo_match(conn, "unresolved")
    _reveal(conn, "unresolved", [None, 800001, nowhere])
    _mtgo_match(conn, "unknown")
    _reveal(conn, "unknown", [800001, nowhere])
    _mtgo_match(conn, "no_fit")
    _reveal(conn, "no_fit", [nowhere])
    _mtgo_match(conn, "too_few")
    _reveal(conn, "too_few", seed.named(*COMMONS[:4]))

    reasons = {match_id: i.reason for match_id, i in infer_formats(conn).items()}
    assert reasons == {
        "unresolved": "unresolved_cards", "unknown": "unknown_legality",
        "no_fit": "no_fit", "too_few": "too_few_cards",
    }


def test_a_token_is_skipped_and_a_token_subtype_is_not(conn, seed):
    """A token row has no legality on purpose (cards.py's backfill), so it
    must not read as unknown. A creature whose subtype says Token is a card,
    and its legality counts."""
    _mtgo_match(conn, "token")
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (800002, 'Treasure', "
        "'Token Artifact — Treasure')"
    )
    _reveal(conn, "token", [*seed.named(*RARES), 800002])
    _mtgo_match(conn, "subtype")
    faux = seed.card({**_legal_nowhere("Faux Token Creature"),
                      "type_line": "Creature — Token Soldier"})
    _reveal(conn, "subtype", [*seed.named(*RARES), faux])

    inferences = infer_formats(conn)
    assert (inferences["token"].format, inferences["token"].reason) == ("Standard", "fit")
    assert inferences["subtype"].reason == "no_fit"


def test_arena_matches_are_not_inferred(conn):
    conn.execute(
        "INSERT INTO matches (match_id, source, event_id, format) "
        "VALUES ('a1', 'arena', 'Traditional_Ladder', 'Standard')"
    )

    assert infer_formats(conn) == {}


def test_narrowest_format_follows_the_inclusion_order():
    assert narrowest_format({"Standard", "Pioneer", "Modern", "Legacy", "Vintage"}) == "Standard"
    assert narrowest_format({"Premodern", "Legacy", "Vintage"}) == "Premodern"
    assert narrowest_format({"Pauper", "Vintage"}) == "Pauper"
    assert narrowest_format({"Legacy", "Pauper", "Vintage"}) is None
    assert narrowest_format({"Modern", "Pauper", "Legacy", "Vintage"}) is None
    assert narrowest_format(()) is None


def test_classify_matches_rebuilds_the_fit_and_inference_tables(conn, seed):
    _mtgo_match(conn, "m1")
    _reveal(conn, "m1", seed.named("Thought Scour", *COMMONS[:4]))
    _mtgo_match(conn, "m2")
    _reveal(conn, "m2", [None])
    conn.execute("INSERT INTO match_format_fit VALUES ('stale', 'Modern')")

    classify_matches(conn)

    fit = conn.execute("SELECT match_id, format FROM match_format_fit").fetchall()
    assert sorted(tuple(r) for r in fit) == sorted(
        ("m1", fmt) for fmt in ("Modern", "Pauper", "Legacy", "Vintage")
    )
    inference = conn.execute(
        "SELECT match_id, format, reason FROM match_format_inference ORDER BY match_id"
    ).fetchall()
    assert [tuple(r) for r in inference] == [
        ("m1", None, "ambiguous"), ("m2", None, "unresolved_cards"),
    ]


def test_v_match_format_reads_the_log_then_the_pick_then_the_inference(conn, seed):
    conn.execute(
        "INSERT INTO matches (match_id, source, event_id, format) "
        "VALUES ('arena', 'arena', 'Traditional_Ladder', 'Standard')"
    )
    _mtgo_match(conn, "inferred")
    _reveal(conn, "inferred", seed.named(*RARES))
    _mtgo_match(conn, "picked")
    _reveal(conn, "picked", seed.named(*RARES))
    conn.execute("INSERT INTO mtgo_match_pick (match_id, format) VALUES ('picked', 'Pioneer')")
    _mtgo_match(conn, "unknown")
    _reveal(conn, "unknown", seed.named(*COMMONS))
    # A pick for an Arena match is never applied (v_match_deck).
    conn.execute("INSERT INTO mtgo_match_pick (match_id, format) VALUES ('arena', 'Modern')")

    classify_matches(conn)

    rows = conn.execute(
        "SELECT match_id, format, format_source FROM v_match_format ORDER BY match_id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("arena", "Standard", "log"),
        ("inferred", "Standard", "inferred"),
        ("picked", "Pioneer", "pick"),
        ("unknown", None, None),
    ]
