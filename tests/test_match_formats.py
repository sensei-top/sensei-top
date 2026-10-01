"""match_formats()/match_format_reasons() (archetypes/classify.py).

Arena's own event stream already carries its format (format_key), so the
Arena branch is a thin delegation, covered by test_classify.py's existing
format_key tests plus one sanity check here that match_formats agrees with
it. MTGO writes neither event_id nor a decks row (decks.deck_id is always
NULL for an MTGO match — migrations/035_mtgo_source.sql), so every MTGO
verdict here has to be read off what the match itself revealed, from both
seats' card_events joined to cards. The fixture schema below is built
directly (no fixture log ingest), the same precedent test_corpus_naming.py's
own docstring cites from test_leaks.py: this needs a full projected schema,
not a full log capture.

Card names for the "revealed_cards" happy path are pulled from the real
MTGO fixture (tests/fixtures/mtgo_match_session.log, via scripts/mtgo_probe.py
per AGENTS.md rule 8) rather than invented, since a real name is free and
proves nothing about a name that happens to look plausible. Their legality
is hand-seeded here — the fixture itself carries no legality data, only card
identity.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.archetypes.classify import match_format_reasons, match_formats
from sensei_top.db import open_database
from sensei_top.guide.window import MIN_DECKS_FOR_LAST_APPEARANCE


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "match_formats.db")
    yield c
    c.close()


# --- schema helpers ----------------------------------------------------------


def _insert_mtgo_match(conn, match_id, *, started_at="2026-08-01T00:00:00Z"):
    conn.execute(
        "INSERT INTO matches (match_id, source, self_seat, opponent_seat, started_at) "
        "VALUES (?, 'mtgo', 1, 2, ?)",
        (match_id, started_at),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, turn_count, self_mulligans, "
        "opp_mulligans) VALUES (?, 1, 1, 6, 0, 0)",
        (match_id,),
    )


def _insert_arena_match(conn, match_id, deck_id=None, *, event_id="Traditional_Ladder"):
    """deck_id=None leaves matches.deck_id NULL, so format_key reads the
    format off event_id alone — the branch these tests want to exercise,
    rather than the deck's own recorded format short-circuiting first."""
    if deck_id is not None:
        conn.execute(
            "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
            "VALUES (?, 'Test Deck', 'Standard', '[]', 't', 't')",
            (deck_id,),
        )
    conn.execute(
        "INSERT INTO matches (match_id, source, event_id, deck_id, self_seat, opponent_seat) "
        "VALUES (?, 'arena', ?, ?, 1, 2)",
        (match_id, event_id, deck_id),
    )


def _card(conn, grp_id, name, legality, *, type_line="Creature — Test"):
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, standard_legality) VALUES (?, ?, ?, ?)",
        (grp_id, name, type_line, legality),
    )


def _card_event(conn, match_id, seat, grp_id, seq):
    conn.execute(
        "INSERT INTO card_events (match_id, game_number, seq, turn_number, seat, "
        "grp_id, category, zone_src, zone_dest) VALUES (?, 1, ?, 1, ?, ?, 'Zone', NULL, NULL)",
        (match_id, seq, seat, grp_id),
    )


def _store_deck(conn, event_id, deck_ord, mainboard, *, event_date, fmt="Standard"):
    """A meta_deck row for format_resets() to cluster into a FormatReset —
    adapted from test_corpus_naming.py's own helper of the same name."""
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


def _deck(*names: str) -> list[dict]:
    return [{"count": 4, "name": name} for name in names]


def _ban_with_reset(conn, name, grp_id, *, last_seen="2026-08-05"):
    """A banned card whose own reset format_resets() can actually detect:
    MIN_DECKS_FOR_LAST_APPEARANCE decks playing it on the same event_date,
    so that date becomes its last_appearance and window_start is the day
    after. Returns window_start (ISO date) for the caller's own assertions."""
    _card(conn, grp_id, name, "banned")
    for i in range(MIN_DECKS_FOR_LAST_APPEARANCE):
        _store_deck(conn, f"{name}-event-{i}", 0, _deck(name), event_date=last_seen)
    return "2026-08-06"  # last_seen + 1 day


# Real card names + grp_ids from tests/fixtures/mtgo_match_session.log
# (scripts/mtgo_probe.py), used for the "enough distinct legal cards"
# happy path — five is MIN_REVEALED.
_FIXTURE_CARDS = [
    (267652, "Leyline Axe"),
    (50288, "Plains"),
    (279646, "Dragonfire Blade"),
    (259498, "Fabled Passage"),
    (88490, "Cavern of Souls"),
]


def _seed_legal_fixture_cards(conn):
    for grp_id, name in _FIXTURE_CARDS:
        _card(conn, grp_id, name, "legal")
    return _FIXTURE_CARDS


def _reveal(conn, match_id, cards, *, seat=2, start_seq=1):
    for i, (grp_id, _name) in enumerate(cards):
        _card_event(conn, match_id, seat, grp_id, start_seq + i)


# --- Arena branch --------------------------------------------------------------


def test_arena_match_delegates_to_format_key(conn):
    """An Arena match's verdict is exactly what format_key already says for
    it — match_formats adds nothing on this branch, only MTGO needs new
    logic."""
    _insert_arena_match(conn, "m1", event_id="Traditional_Ladder")
    conn.commit()

    assert match_formats(conn) == {"m1": "Standard"}
    assert match_format_reasons(conn) == {"m1": "arena"}


def test_arena_brawl_event_is_not_standard(conn):
    _insert_arena_match(conn, "m1", event_id="Brawl_Ladder")
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "arena"}


# --- MTGO: not_legal -----------------------------------------------------------


def test_mtgo_not_legal_card_excludes_the_match(conn):
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    _card(conn, 999001, "Ragavan, Nimble Pilferer", "not_legal")
    _reveal(conn, "m1", cards)
    _reveal(conn, "m1", [(999001, "Ragavan, Nimble Pilferer")], start_seq=10)
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "not_legal"}


def test_mtgo_not_legal_card_on_our_own_side_also_excludes(conn):
    """Unlike classify_matches's opponent-only names query, match_formats
    reads both seats — our own not_legal card rules the match's *format*
    out just as much as the opponent's would."""
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    _card(conn, 999002, "Oko, Thief of Crowns", "not_legal")
    _reveal(conn, "m1", cards, seat=2)
    _reveal(conn, "m1", [(999002, "Oko, Thief of Crowns")], seat=1, start_seq=10)
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "not_legal"}


# --- MTGO: banned, window_start ------------------------------------------------


def test_mtgo_banned_card_before_its_own_window_start_still_counts_legal(conn):
    """A banned card revealed in a match that predates its own ban's
    window_start was legal to play at the time — the coordinator's own rule:
    'a banned card counting as legal before its reset window_start.'"""
    window_start = _ban_with_reset(conn, "Invoke Despair", 999003, last_seen="2026-08-05")
    assert window_start == "2026-08-06"
    _insert_mtgo_match(conn, "m1", started_at="2026-08-05T12:00:00Z")  # pre-reset
    cards = _seed_legal_fixture_cards(conn)
    _reveal(conn, "m1", cards)
    _reveal(conn, "m1", [(999003, "Invoke Despair")], start_seq=10)
    conn.commit()

    assert match_formats(conn) == {"m1": "Standard"}
    assert match_format_reasons(conn) == {"m1": "revealed_cards"}


def test_mtgo_banned_card_on_or_after_window_start_excludes_the_match(conn):
    window_start = _ban_with_reset(conn, "Invoke Despair", 999003, last_seen="2026-08-05")
    assert window_start == "2026-08-06"
    _insert_mtgo_match(conn, "m1", started_at="2026-08-06T00:00:00Z")  # window_start itself
    cards = _seed_legal_fixture_cards(conn)
    _reveal(conn, "m1", cards)
    _reveal(conn, "m1", [(999003, "Invoke Despair")], start_seq=10)
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "banned"}


def test_mtgo_banned_card_with_no_detectable_reset_excludes_the_match(conn):
    """A card banned before the corpus begins has no reset to date it, so
    nothing proves the match came before its ban. It is never assumed legal:
    the match excludes as banned, however early it was played."""
    _card(conn, 999004, "Cori-Steel Cutter", "banned")
    _insert_mtgo_match(conn, "m1", started_at="2026-01-02T00:00:00Z")
    cards = _seed_legal_fixture_cards(conn)
    _reveal(conn, "m1", cards)
    _reveal(conn, "m1", [(999004, "Cori-Steel Cutter")], start_seq=10)
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "banned"}


# --- MTGO: unresolved card events -----------------------------------------------


def test_mtgo_unresolved_card_event_excludes_the_match(conn):
    """A card_events row whose own grp_id never resolved at all
    (`_resolve_grp_id` returned None) is its own exclusion reason —
    `unresolved_cards` — not folded into `unknown_legality`: `card_events`
    stores no name, so an unresolved token can't be told from an unresolved
    real card, and either way the match's own legality can't be fully read
    from what did resolve."""
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    _reveal(conn, "m1", cards)
    _card_event(conn, "m1", 2, None, 10)
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "unresolved_cards"}


def test_mtgo_not_legal_card_outranks_an_unresolved_card_event(conn):
    """`not_legal` is checked before `unresolved_cards` — a card that proves
    the match illegal outright is the stronger, more specific reason."""
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    _card(conn, 999007, "Ragavan, Nimble Pilferer", "not_legal")
    _reveal(conn, "m1", cards)
    _reveal(conn, "m1", [(999007, "Ragavan, Nimble Pilferer")], start_seq=10)
    _card_event(conn, "m1", 2, None, 11)
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "not_legal"}


def test_mtgo_banned_card_outranks_an_unresolved_card_event(conn):
    """`banned` is checked before `unresolved_cards` too — same reasoning as
    the `not_legal` ordering above."""
    window_start = _ban_with_reset(conn, "Invoke Despair", 999003, last_seen="2026-08-05")
    assert window_start == "2026-08-06"
    _insert_mtgo_match(conn, "m1", started_at="2026-08-06T00:00:00Z")  # on window_start
    cards = _seed_legal_fixture_cards(conn)
    _reveal(conn, "m1", cards)
    _reveal(conn, "m1", [(999003, "Invoke Despair")], start_seq=10)
    _card_event(conn, "m1", 2, None, 11)
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "banned"}


# --- MTGO: unknown legality ------------------------------------------------------


def test_mtgo_unknown_legality_card_excludes_the_match(conn):
    """A card with no legality on file at all: rule 4 says unknown is never
    assumed legal, and this is where 'unknown means we cannot say Standard'
    actually happens — not a NULL-standard_legality token row, which is
    the token test below."""
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (999004, 'Some New Card', "
        "'Creature — Test')"
    )
    _reveal(conn, "m1", cards)
    _reveal(conn, "m1", [(999004, "Some New Card")], start_seq=10)
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "unknown_legality"}


def test_mtgo_grp_id_missing_from_cards_entirely_counts_as_unknown(conn):
    """A card_events row whose grp_id was never even written to cards (the
    LEFT JOIN's other NULL case) is exactly as unknown as a row with a NULL
    standard_legality — never treated as legal by omission."""
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    _reveal(conn, "m1", cards)
    _card_event(conn, "m1", 2, 424242, 10)  # no matching cards row at all
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "unknown_legality"}


# --- MTGO: tokens are skipped, never "unknown" ------------------------------------


def test_mtgo_token_with_null_legality_does_not_make_the_match_unknown(conn):
    """cards.py's name backfill deliberately leaves an Arena/MTGO token's
    standard_legality NULL forever (Scryfall's own Treasure/Spirit objects
    share the name but are not the token). match_formats must skip it
    entirely, not read it as 'unknown legality' — the coordinator's own
    required case: 'a match reveals a token plus legal cards and is still
    Standard.'"""
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    _card(conn, 999005, "Treasure", None, type_line="Token Artifact")
    _reveal(conn, "m1", cards)
    _reveal(conn, "m1", [(999005, "Treasure")], start_seq=10)
    conn.commit()

    assert match_formats(conn) == {"m1": "Standard"}
    assert match_format_reasons(conn) == {"m1": "revealed_cards"}


def test_mtgo_token_whose_subtype_says_token_is_not_mistaken_for_one(conn):
    """A card whose TYPE is not Token but whose subtype happens to mention
    it (e.g. a hypothetical 'Creature — Token Soldier' card design) must not
    be excluded from consideration by the token skip — matches the
    pre-em-dash-only check classify_matches's own opponent-cards query
    already uses."""
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    _card(conn, 999006, "Faux Token Creature", "not_legal",
          type_line="Creature — Token Soldier")
    _reveal(conn, "m1", cards)
    _reveal(conn, "m1", [(999006, "Faux Token Creature")], start_seq=10)
    conn.commit()

    # Not skipped: its type (before the dash) is "Creature", not "Token", so
    # its not_legal legality is real evidence and excludes the match.
    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "not_legal"}


# --- MTGO: happy path + too few cards ---------------------------------------------


def test_mtgo_clean_match_with_enough_legal_cards_is_standard(conn):
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    _reveal(conn, "m1", cards)
    conn.commit()

    assert match_formats(conn) == {"m1": "Standard"}
    assert match_format_reasons(conn) == {"m1": "revealed_cards"}


def test_mtgo_too_few_distinct_cards_is_not_standard(conn):
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)[:4]  # one short of MIN_REVEALED
    _reveal(conn, "m1", cards)
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "too_few_cards"}


def test_mtgo_match_with_no_revealed_cards_is_too_few(conn):
    _insert_mtgo_match(conn, "m1")
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "too_few_cards"}


def test_mtgo_distinct_count_is_by_name_not_by_card_event_row(conn):
    """The same card revealed on two zone transfers (e.g. drawn, then cast)
    must not be double-counted toward MIN_REVEALED."""
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)[:4]
    _reveal(conn, "m1", cards, start_seq=1)
    _reveal(conn, "m1", [cards[0]], start_seq=20)  # same grp_id again
    conn.commit()

    assert match_formats(conn) == {"m1": None}
    assert match_format_reasons(conn) == {"m1": "too_few_cards"}


# --- mixed Arena + MTGO --------------------------------------------------------


def test_mixed_arena_and_mtgo_matches_get_independent_verdicts(conn):
    _insert_arena_match(conn, "a1", event_id="Traditional_Ladder")
    _insert_mtgo_match(conn, "m1")
    cards = _seed_legal_fixture_cards(conn)
    _reveal(conn, "m1", cards)
    conn.commit()

    assert match_formats(conn) == {"a1": "Standard", "m1": "Standard"}
    assert match_format_reasons(conn) == {"a1": "arena", "m1": "revealed_cards"}
