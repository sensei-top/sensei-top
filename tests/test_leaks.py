"""Tests for review/leaks.py: the cross-match pattern rollup.

Ground truth for the Wilson interval comes from a known reference value
(7 wins of 10, verified independently), not from running the function and
copying its own output (rule 8). Sample-gating and the mana-leak
computation are exercised with synthetic data built directly against the
projected schema (turns/matches/decks), matching this project's own
precedent for a piece that does not need a full log capture.
"""

from __future__ import annotations

import pytest

import sensei_top.review.leaks as leaks_mod
from sensei_top.db import open_database
from sensei_top.review.findings import Category, Confidence, Finding, MatchReport, Severity
from sensei_top.review.leaks import MIN_SAMPLE, find_leaks, mana_flags, wilson


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def test_wilson_matches_a_known_reference_value():
    lo, hi = wilson(7, 10)
    assert lo == pytest.approx(0.3968, abs=0.001)
    assert hi == pytest.approx(0.8922, abs=0.001)


def test_wilson_of_zero_games_is_zero_not_a_crash():
    assert wilson(0, 0) == (0.0, 0.0)


def _insert_match(conn, match_id, result, self_seat=1, opponent_seat=2, deck_id=None,
                   started_at="t"):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, ?, ?, 'u', 'n', ?, 't', "
        "?, 1, 0, 'r')",
        (match_id, deck_id, self_seat, opponent_seat, started_at, result),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 6, 0, 0)",
        (match_id, result),
    )


def test_find_leaks_below_min_sample_returns_nothing(conn):
    """A pattern seen in only a couple of matches is noise, not a leak —
    the same sample-gating discipline PLAY_DRAW_MIN_GAMES already applies
    to a single match's own play/draw split."""
    for i in range(3):
        _insert_match(conn, f"m{i}", "win" if i == 0 else "loss")
        conn.execute(
            "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
            "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
            "opp_permanents) VALUES (?, 1, 1, 1, 20, 20, 7, 7, 1, 0, 0)",
            (f"m{i}",),
        )
    conn.commit()
    leaks = find_leaks(conn)
    assert leaks == []


def test_find_leaks_needs_at_least_min_sample_matches_total(conn):
    """Guards the mana-leak path specifically: with fewer than MIN_SAMPLE
    completed matches in the whole database, there cannot be enough on
    both sides of any comparison."""
    for i in range(MIN_SAMPLE - 1):
        _insert_match(conn, f"m{i}", "win")
        conn.execute(
            "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
            "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
            "opp_permanents) VALUES (?, 1, 1, 1, 20, 20, 7, 7, 4, 2, 0)",
            (f"m{i}",),
        )
    conn.commit()
    leaks = find_leaks(conn)
    assert not [leak for leak in leaks if leak.code in ("mana_screwed", "mana_flooded")]


def test_mana_screwed_is_detected_from_low_lands_by_turn_four(conn):
    """Verified against the threshold this module states explicitly
    (MANA_SCREW_LAND_TARGET=4 at self_turn_index>=4): a deck stuck on 2
    lands by its 4th turn, repeated enough times on both sides of the
    comparison, must surface as a leak."""
    for i in range(MIN_SAMPLE + 2):
        result = "loss" if i % 2 == 0 else "win"
        _insert_match(conn, f"screwed{i}", result)
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 2, 0, 0, ?2)",
                (f"screwed{i}", turn_number),
            )
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"fine{i}", "win")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 4, 2, 0, ?2)",
                (f"fine{i}", turn_number),
            )
    conn.commit()

    leaks = find_leaks(conn)
    screw = next((leak for leak in leaks if leak.code == "mana_screwed"), None)
    assert screw is not None
    assert screw.n_with == MIN_SAMPLE + 2
    assert len(screw.match_ids_with) == MIN_SAMPLE + 2
    assert all(mid.startswith("screwed") for mid in screw.match_ids_with)


# --- Finding.pattern is an opt-in gate, not every finding -------------------


def test_findings_without_a_pattern_never_reach_the_leak_ranking(conn, monkeypatch):
    """``Finding.pattern`` (findings.py) is each analyzer's own opt-in to
    this rollup — a finding with ``pattern=None`` must never surface as a
    leak, no matter how strongly it correlates with the result, or the
    ranking is back to measuring whatever an analyzer happened to report
    rather than a real recurring pattern (docs/review.md's own diagnosis:
    ``play_draw_split``, ``field_matchup_rate`` and ``still_live_staples``
    all used to leak in this way, firing whenever an analyzer *had data*)."""
    match_ids = [f"m{i}" for i in range(2 * MIN_SAMPLE)]
    reports: dict[str, MatchReport] = {}
    for i, mid in enumerate(match_ids):
        result = "win" if i % 2 == 0 else "loss"
        _insert_match(conn, mid, result)
        # Fires in every single match, correlating perfectly with the
        # alternating win/loss pattern below — the strongest possible signal
        # to rank, and still must never appear without a `pattern`.
        finding = Finding(
            code="no_pattern_here", analyzer="test", category=Category.BASELINE,
            severity=Severity.NOTE, confidence=Confidence.OBSERVED,
            title="irrelevant", detail="irrelevant",
        )
        reports[mid] = MatchReport(
            match_id=mid, deck_id=None, result=result, findings=(finding,)
        )
    conn.commit()

    monkeypatch.setattr(
        leaks_mod, "build_match_report", lambda conn, match_id, **kwargs: reports[match_id]
    )
    leaks = leaks_mod.find_leaks(conn)
    assert not [leak for leak in leaks if leak.code == "no_pattern_here"]


def test_cards_stranded_in_a_loss_never_reaches_the_leak_ranking(conn, monkeypatch):
    """``cards_stranded_in_a_loss`` only ever fires in a game already lost
    (resources.py) — a with/without win-rate comparison across it would
    measure the loss condition it is defined by, not a real leak. It
    deliberately carries no ``pattern`` for exactly this reason; this pins
    that choice down as a regression test rather than an easy-to-lose
    comment."""
    match_ids = [f"m{i}" for i in range(2 * MIN_SAMPLE)]
    reports: dict[str, MatchReport] = {}
    for i, mid in enumerate(match_ids):
        result = "win" if i % 2 == 0 else "loss"
        _insert_match(conn, mid, result)
        findings = ()
        if result == "loss":
            findings = (Finding(
                code="cards_stranded_in_a_loss", analyzer="resources",
                category=Category.RESOURCES, severity=Severity.NOTICE,
                confidence=Confidence.PARTIAL, title="Lost holding 4 cards",
                detail="irrelevant",
            ),)
        reports[mid] = MatchReport(match_id=mid, deck_id=None, result=result, findings=findings)
    conn.commit()

    monkeypatch.setattr(
        leaks_mod, "build_match_report", lambda conn, match_id, **kwargs: reports[match_id]
    )
    leaks = leaks_mod.find_leaks(conn)
    assert not [leak for leak in leaks if leak.code == "cards_stranded_in_a_loss"]


# --- unknown (no-evidence) matches: rule 4, never a guess -------------------


def test_mana_flags_is_unknown_not_false_with_no_turns_rows_at_all(conn):
    """The shape every MTGO match has (``projector/mtgo/project.py`` never
    writes ``turns``) must read both flags as unknown, never as clean —
    ``screwed`` because there are no self-turn rows to answer it from at
    all, ``flooded`` because there is no deck row here either."""
    _insert_match(conn, "no_turns", "loss")
    conn.commit()
    assert mana_flags(conn, "no_turns") == (None, None)


def test_mana_flags_is_unknown_when_no_own_turn_has_a_number(conn):
    """Own turns on 2 lands whose ``active_turn_number`` Arena never gave:
    there is no index to check, so ``screwed`` is unknown, not clean. Proven
    by salting the population with unnumbered losses: read as clean they
    would drag ``win_rate_without`` below the numbered wins' 100% and
    inflate ``n_without``."""
    def add_turns(match_id, lands, numbered):
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, ?3, 0, 0, ?4)",
                (match_id, turn_number, lands, turn_number if numbered else None),
            )

    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"screwed{i}", "loss" if i % 2 == 0 else "win")
        add_turns(f"screwed{i}", 2, True)
        _insert_match(conn, f"fine{i}", "win")
        add_turns(f"fine{i}", 4, True)
        _insert_match(conn, f"unnumbered{i}", "loss")
        add_turns(f"unnumbered{i}", 2, False)
    conn.commit()

    assert mana_flags(conn, "unnumbered0")[0] is None
    screw = next((leak for leak in find_leaks(conn) if leak.code == "mana_screwed"), None)
    assert screw is not None
    assert not any(mid.startswith("unnumbered") for mid in screw.match_ids_with)
    assert screw.n_without == MIN_SAMPLE + 2
    assert screw.win_rate_without == pytest.approx(1.0)


def test_mana_flags_numbers_own_turns_within_each_game_not_across_the_match(conn):
    """Self on the play: game 1's own turns 1-4 sit at shared turns 1,3,5,7
    on 4 lands, game 2's own turns 1-3 at shared turns 1,3,5 on 2 lands.
    The check's fourth turn is the own-turn number per game, so game 2 never
    reaches it, whatever the shared count or a rank across both games says."""
    _insert_match(conn, "two_games", "win")
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES ('two_games', 2, 1, 'win', "
        "NULL, 5, 0, 0)"
    )
    for game_number, own_turns, lands in ((1, 4, 4), (2, 3, 2)):
        for own in range(1, own_turns + 1):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES ('two_games', ?, ?, 1, 20, 20, 7, 7, ?, 0, 0, ?)",
                (game_number, 2 * own - 1, lands, own),
            )
    conn.commit()
    assert mana_flags(conn, "two_games")[0] is False


def test_mana_flags_flooded_is_none_with_no_deck_row_even_when_screwed_is_known(conn):
    """The two flags have independent evidence requirements: a match with
    real ``turns`` rows (so ``screwed`` reads a real ``True``/``False``) but
    no ``deck_id`` at all still can't answer ``flooded``, which needs the
    deck's own land ratio to compare against."""
    _insert_match(conn, "no_deck", "win")
    for turn_number in range(1, 5):
        conn.execute(
            "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
            "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
            "opp_permanents, active_turn_number) "
            "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 4, 2, 0, ?2)",
            ("no_deck", turn_number),
        )
    conn.commit()
    screwed, flooded = mana_flags(conn, "no_deck")
    assert screwed is False
    assert flooded is None


def test_mana_flags_flooded_is_none_with_an_unnamed_decklist(conn):
    """A decklist with any not-yet-downloaded card (``cards.name IS NULL``,
    so ``v_deck_land_count.unnamed_count`` is nonzero) must never feed a
    lands-seen ratio — a partial land count would misread as a real one.
    ``screwed`` is independently known here (real ``turns`` rows), proving
    the two flags really do have separate populations rather than one
    missing-evidence gate covering both."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('unnamed_deck', 'Unnamed', 'Standard', '{\"maindeck\": [999999]}', 't', 't')"
    )
    _insert_match(conn, "m1", "win", deck_id="unnamed_deck")
    for turn_number in range(1, 5):
        conn.execute(
            "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
            "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
            "opp_permanents, active_turn_number) "
            "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 4, 2, 0, ?2)",
            ("m1", turn_number),
        )
    conn.commit()
    screwed, flooded = mana_flags(conn, "m1")
    assert screwed is False
    assert flooded is None


def _flood_deck_and_turns(conn, deck_id, cards_json):
    """A two-card maindeck (one land, one creature: a land ratio of 0.5) and
    a game that drew 7 cards, 6 of them lands (0.857). That is above the
    ratio by more than MANA_FLOOD_MARGIN, so a complete decklist reads as
    flooded."""
    for grp_id, name, type_line in ((7001, "Test Plains", "Basic Land \u2014 Plains"),
                                    (7002, "Test Bear", "Creature \u2014 Bear")):
        conn.execute(
            "INSERT OR IGNORE INTO cards (grp_id, name, type_line) VALUES (?, ?, ?)",
            (grp_id, name, type_line),
        )
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, 'D', 'Standard', ?, 't', 't')",
        (deck_id, cards_json),
    )
    _insert_match(conn, f"{deck_id}-m", "win", deck_id=deck_id)
    for turn_number, library, lands in ((1, 40, 3), (2, 33, 6)):
        conn.execute(
            "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
            "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
            "opp_permanents, self_library, active_turn_number) "
            "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, ?3, 2, 0, ?4, ?2)",
            (f"{deck_id}-m", turn_number, lands, library),
        )
    conn.commit()


def test_mana_flags_flooded_is_none_with_unresolved_maindeck_copies(conn):
    """Every card the list holds is named, so ``unnamed_count`` is zero, but
    an MTGO deck that dropped copies it could not resolve
    (``unresolved_count`` above zero) has a land ratio computed from a
    partial list. The control deck, with the same list and nothing dropped,
    shows the same turns do read as flooded, so the guard is what turns the
    answer into unknown."""
    _flood_deck_and_turns(
        conn, "whole",
        '{"maindeck": [7001, 7002], "unresolved": {"maindeck": 0, "sideboard": 0}}',
    )
    _flood_deck_and_turns(
        conn, "short",
        '{"maindeck": [7001, 7002], "unresolved": {"maindeck": 2, "sideboard": 0}}',
    )
    assert mana_flags(conn, "whole-m") == (False, True)
    assert mana_flags(conn, "short-m") == (False, None)


def test_mana_leaks_excludes_no_turns_matches_from_the_known_population(conn):
    """A match with no ``turns`` rows at all (an MTGO match, or the stand-in
    used here rather than a full MTGO ingest) must never be read as "not
    screwed": it has to leave the population entirely, not fall into the
    "without" (clean) side as a guessed ``False``. Proven by salting the
    population with several no-turns matches that are all losses — if they
    leaked into "without" as clean, they would drag ``win_rate_without``
    below the "fine" population's own 100% and inflate ``n_without`` past
    the "fine" population's own size."""
    for i in range(MIN_SAMPLE + 2):
        result = "loss" if i % 2 == 0 else "win"
        _insert_match(conn, f"screwed{i}", result)
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 2, 0, 0, ?2)",
                (f"screwed{i}", turn_number),
            )
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"fine{i}", "win")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 4, 2, 0, ?2)",
                (f"fine{i}", turn_number),
            )
    # No `turns` rows at all, and all losses — a leaked `False` reading
    # would be visible immediately in `win_rate_without`.
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"unknown{i}", "loss")
    conn.commit()

    leaks = find_leaks(conn)
    screw = next((leak for leak in leaks if leak.code == "mana_screwed"), None)
    assert screw is not None
    assert not any(mid.startswith("unknown") for mid in screw.match_ids_with)
    assert screw.n_without == MIN_SAMPLE + 2
    assert screw.win_rate_without == pytest.approx(1.0)


def test_mana_leaks_gates_min_sample_per_flag_independently(conn):
    """Screw and flood have their own known populations, each gated on
    ``MIN_SAMPLE`` independently — a deck with plenty of turns-based
    evidence for screw but an unnamed decklist (so flood is unknown for
    every match) must still surface a screw leak, with no flood leak at
    all rather than one built from a too-small or fabricated population."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('unnamed_deck', 'Unnamed', 'Standard', '{\"maindeck\": [999999]}', 't', 't')"
    )
    for i in range(MIN_SAMPLE + 2):
        result = "loss" if i % 2 == 0 else "win"
        _insert_match(conn, f"screwed{i}", result, deck_id="unnamed_deck")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 2, 0, 0, ?2)",
                (f"screwed{i}", turn_number),
            )
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"fine{i}", "win", deck_id="unnamed_deck")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 4, 2, 0, ?2)",
                (f"fine{i}", turn_number),
            )
    conn.commit()

    leaks = find_leaks(conn)
    assert any(leak.code == "mana_screwed" for leak in leaks)
    assert not any(leak.code == "mana_flooded" for leak in leaks)


# --- guide/'s deck- and date-scoping ----------------------------------------


def test_deck_ids_scopes_the_mana_leak_population(conn):
    """A deck-scoped guide's leak rollup must only see that deck's own
    matches — the default (no filter) reproduces today's pooled-across-
    every-deck behaviour exactly."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('deckA', 'A', 'Standard', '{}', 't', 't')"
    )
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('deckB', 'B', 'Standard', '{}', 't', 't')"
    )
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"screwed{i}", "loss" if i % 2 == 0 else "win", deck_id="deckA")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 2, 0, 0, ?2)",
                (f"screwed{i}", turn_number),
            )
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"fineA{i}", "win", deck_id="deckA")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 4, 2, 0, ?2)",
                (f"fineA{i}", turn_number),
            )
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"other{i}", "win", deck_id="deckB")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 4, 2, 0, ?2)",
                (f"other{i}", turn_number),
            )
    conn.commit()

    scoped = find_leaks(conn, deck_ids=("deckA",))
    screw = next((leak for leak in scoped if leak.code == "mana_screwed"), None)
    assert screw is not None
    assert all(mid.startswith("screwed") for mid in screw.match_ids_with)
    assert not any(mid.startswith("other") for mid in screw.match_ids_with)


def test_deck_ids_scope_follows_an_mtgo_pick(conn):
    """An MTGO match has no ``matches.deck_id``; it is in a deck's scoped
    population only through the user's pick (``v_match_deck``), and only when
    the caller asks for MTGO's source."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('deckA', 'A', 'Standard', '{}', 't', 't')"
    )

    def add_turns(match_id, lands):
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, ?3, 0, 0, ?2)",
                (match_id, turn_number, lands),
            )

    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"screwed{i}", "loss" if i % 2 == 0 else "win", deck_id="deckA")
        add_turns(f"screwed{i}", 2)
        _insert_match(conn, f"fine{i}", "win", deck_id="deckA")
        add_turns(f"fine{i}", 4)
    # Two MTGO matches, neither with a deck_id of its own; only one is picked.
    # (turns rows are synthetic here: the site under test is the scope, and a
    # match with no turns would drop out of the screw population regardless.)
    for match_id in ("mtgo-picked", "mtgo-unpicked"):
        _insert_match(conn, match_id, "win")
        conn.execute("UPDATE matches SET source = 'mtgo' WHERE match_id = ?", (match_id,))
        add_turns(match_id, 4)
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) "
        "VALUES ('mtgo-picked', 'deckA', 'Modern')"
    )
    conn.commit()

    def screw(**kwargs):
        return next(
            leak for leak in find_leaks(conn, deck_ids=("deckA",), **kwargs)
            if leak.code == "mana_screwed"
        )

    # Arena only (the default): the two MTGO matches are out whatever the pick.
    assert screw().n_without == MIN_SAMPLE + 2
    # Both clients: the picked match joins the deck's population, the unpicked
    # one stays out of it.
    assert screw(source="all").n_without == MIN_SAMPLE + 3


def test_since_scopes_out_matches_before_the_date(conn):
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"old{i}", "loss" if i % 2 == 0 else "win",
                       started_at="2026-01-01")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 2, 0, 0, ?2)",
                (f"old{i}", turn_number),
            )
    conn.commit()

    leaks = find_leaks(conn, since="2026-06-01")
    assert not [leak for leak in leaks if leak.code == "mana_screwed"]


# --- coach/evidence.py's exact-set scoping ----------------------------------


def test_match_ids_scopes_the_mana_leak_population_to_an_exact_set(conn):
    """``match_ids`` (added for coach/evidence.py, which already knows its
    own population and needs no deck/date filter to express it) must scope
    exactly like ``deck_ids`` does above -- everything in the set counts,
    everything outside it is invisible to the comparison, regardless of
    which deck or date it carries."""
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"screwed{i}", "loss" if i % 2 == 0 else "win")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 2, 0, 0, ?2)",
                (f"screwed{i}", turn_number),
            )
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"fine{i}", "win")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 4, 2, 0, ?2)",
                (f"fine{i}", turn_number),
            )
    conn.commit()

    # Scope to every "screwed" match plus only half of "fine" -- fewer than
    # MIN_SAMPLE on the "without" side, so the leak must vanish even though
    # the unscoped population above would have surfaced it.
    scoped_ids = tuple(f"screwed{i}" for i in range(MIN_SAMPLE + 2)) + tuple(
        f"fine{i}" for i in range(MIN_SAMPLE // 2)
    )
    scoped = find_leaks(conn, match_ids=scoped_ids)
    assert not [leak for leak in scoped if leak.code == "mana_screwed"]

    # The full "fine" set restores both sides above MIN_SAMPLE.
    full_ids = tuple(f"screwed{i}" for i in range(MIN_SAMPLE + 2)) + tuple(
        f"fine{i}" for i in range(MIN_SAMPLE + 2)
    )
    full = find_leaks(conn, match_ids=full_ids)
    screw = next((leak for leak in full if leak.code == "mana_screwed"), None)
    assert screw is not None
    assert set(screw.match_ids_with) == {f"screwed{i}" for i in range(MIN_SAMPLE + 2)}


def test_match_ids_none_leaves_every_existing_caller_unaffected(conn):
    """``match_ids=None`` (the default) must reproduce the exact same result
    as omitting the argument entirely -- every caller that predates this
    parameter is unaffected."""
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"screwed{i}", "loss" if i % 2 == 0 else "win")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 2, 0, 0, ?2)",
                (f"screwed{i}", turn_number),
            )
    for i in range(MIN_SAMPLE + 2):
        _insert_match(conn, f"fine{i}", "win")
        for turn_number in range(1, 5):
            conn.execute(
                "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
                "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
                "opp_permanents, active_turn_number) "
                "VALUES (?1, 1, ?2, 1, 20, 20, 7, 7, 4, 2, 0, ?2)",
                (f"fine{i}", turn_number),
            )
    conn.commit()

    assert find_leaks(conn) == find_leaks(conn, match_ids=None)


def test_equal_gap_leaks_tie_break_alphabetically_by_code(conn, monkeypatch):
    """Two codes that fire on the exact same match subset produce identical
    with/without counts and therefore an identical ``gap`` — bit-for-bit
    equal, not just close, since both leaks are computed from the same
    ``with_ids``/wins/totals. With no tie-break, Python's stable sort would
    leave them in whatever order ``by_code`` happened to encounter them
    (here, ``b_code`` before ``a_code``, since that is the order each
    report's own ``findings`` tuple puts them in, and ``m0`` is the first
    match ``find_leaks`` processes). The ``leak.code`` secondary sort key
    must put ``a_code`` first regardless of that encounter order, so "the
    top leak" a user sees doesn't depend on match insertion order alone."""
    match_ids = [f"m{i}" for i in range(2 * MIN_SAMPLE)]
    reports: dict[str, MatchReport] = {}
    for i, mid in enumerate(match_ids):
        result = "win" if i % 2 == 0 else "loss"
        _insert_match(conn, mid, result)
        findings: tuple[Finding, ...] = ()
        if i < MIN_SAMPLE:
            # Both codes fire on exactly the same 10 matches (n_with=10,
            # n_without=10 -- both exactly at MIN_SAMPLE) so their gap
            # values are computed from identical counts.
            findings = (
                Finding(
                    code="b_code", analyzer="test", category=Category.BASELINE,
                    severity=Severity.NOTE, confidence=Confidence.OBSERVED,
                    title="irrelevant", detail="irrelevant", pattern="B pattern",
                ),
                Finding(
                    code="a_code", analyzer="test", category=Category.BASELINE,
                    severity=Severity.NOTE, confidence=Confidence.OBSERVED,
                    title="irrelevant", detail="irrelevant", pattern="A pattern",
                ),
            )
        reports[mid] = MatchReport(
            match_id=mid, deck_id=None, result=result, findings=findings
        )
    conn.commit()

    monkeypatch.setattr(
        leaks_mod, "build_match_report", lambda conn, match_id, **kwargs: reports[match_id]
    )
    leaks = leaks_mod.find_leaks(conn)
    tied = [leak for leak in leaks if leak.code in ("a_code", "b_code")]
    assert len(tied) == 2
    assert tied[0].gap == tied[1].gap
    assert [leak.code for leak in tied] == ["a_code", "b_code"]


def test_report_cache_reuses_a_built_report_instead_of_rebuilding_it(conn, monkeypatch):
    """A MatchReport depends only on match_id and the database (find_leaks's
    own docstring) -- given a report_cache, a second find_leaks call sharing
    it must reuse every report the first call already built instead of
    calling build_match_report again, and the leaks produced must be
    unaffected either way."""
    match_ids = [f"m{i}" for i in range(2 * MIN_SAMPLE)]
    for i, mid in enumerate(match_ids):
        _insert_match(conn, mid, "win" if i % 2 == 0 else "loss")
    conn.commit()

    calls = []
    real_build_match_report = leaks_mod.build_match_report

    def counting_build_match_report(conn, match_id, **kwargs):
        calls.append(match_id)
        return real_build_match_report(conn, match_id, **kwargs)

    monkeypatch.setattr(leaks_mod, "build_match_report", counting_build_match_report)

    without_cache = find_leaks(conn)

    report_cache: dict = {}
    calls.clear()
    first = find_leaks(conn, report_cache=report_cache)
    assert sorted(calls) == sorted(match_ids)
    assert first == without_cache

    calls.clear()
    second = find_leaks(conn, report_cache=report_cache)
    assert calls == []
    assert second == first


def test_consensus_since_is_forwarded_to_build_match_report_and_keys_the_report_cache(
    conn, monkeypatch,
):
    """find_leaks must pass its own consensus_since straight through to every
    build_match_report call (review/snapshot.py's opponent-consensus window),
    and report_cache's key must include it -- otherwise a report built under
    one format-reset window could be handed back to a caller asking under a
    different one, silently mixing an opponent consensus from the wrong side
    of a ban into an unrelated call's report."""
    match_ids = [f"m{i}" for i in range(2 * MIN_SAMPLE)]
    for i, mid in enumerate(match_ids):
        _insert_match(conn, mid, "win" if i % 2 == 0 else "loss")
    conn.commit()

    seen_windows = []
    real_build_match_report = leaks_mod.build_match_report

    def recording_build_match_report(conn, match_id, *, consensus_since=None, **kwargs):
        seen_windows.append(consensus_since)
        return real_build_match_report(
            conn, match_id, consensus_since=consensus_since, **kwargs
        )

    monkeypatch.setattr(leaks_mod, "build_match_report", recording_build_match_report)

    report_cache: dict = {}
    find_leaks(conn, consensus_since="2026-08-11", report_cache=report_cache)
    assert seen_windows and all(w == "2026-08-11" for w in seen_windows)
    assert all(key[1] == "2026-08-11" for key in report_cache)

    # A second call sharing the same report_cache but a different window must
    # rebuild every report rather than reusing the first call's entries.
    seen_windows.clear()
    find_leaks(conn, consensus_since=None, report_cache=report_cache)
    assert seen_windows and all(w is None for w in seen_windows)
    assert {key[1] for key in report_cache} == {"2026-08-11", None}


def test_each_match_is_measured_against_its_own_formats_consensus_window(
    conn, monkeypatch,
):
    """With ``consensus_window``, a Modern match's report is built under
    Modern's reset window, not Standard's, and a match no source names a
    format for gets no window at all rather than borrowing one. The formats
    come from the rows below, through ``v_match_format``: the Arena match's
    ``matches.format``, the MTGO match's pick."""
    _insert_match(conn, "standard-arena", "win")
    conn.execute("UPDATE matches SET format = 'Standard' WHERE match_id = 'standard-arena'")
    _insert_match(conn, "modern-mtgo", "loss")
    conn.execute("UPDATE matches SET source = 'mtgo' WHERE match_id = 'modern-mtgo'")
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) "
        "VALUES ('modern-mtgo', NULL, 'Modern')"
    )
    _insert_match(conn, "no-format-arena", "win")
    conn.commit()

    windows = {"Standard": "2026-08-11", "Modern": "2026-03-02"}
    asked: list[str] = []

    def consensus_window(fmt):
        asked.append(fmt)
        return windows[fmt]

    seen: dict[str, str | None] = {}
    real_build_match_report = leaks_mod.build_match_report

    def recording_build_match_report(conn, match_id, *, consensus_since=None, **kwargs):
        seen[match_id] = consensus_since
        return real_build_match_report(
            conn, match_id, consensus_since=consensus_since, **kwargs
        )

    monkeypatch.setattr(leaks_mod, "build_match_report", recording_build_match_report)

    report_cache: dict = {}
    find_leaks(
        conn, source="all", consensus_window=consensus_window, report_cache=report_cache
    )

    assert seen == {
        "standard-arena": "2026-08-11",
        "modern-mtgo": "2026-03-02",
        "no-format-arena": None,
    }
    # Asked once per format present; never asked about the match with none.
    assert sorted(asked) == ["Modern", "Standard"]
    assert set(report_cache) == {
        ("standard-arena", "2026-08-11"),
        ("modern-mtgo", "2026-03-02"),
        ("no-format-arena", None),
    }

    # A single Standard window for every match keys the Modern match's report
    # apart, so the per-format report above is never handed back for it.
    seen.clear()
    find_leaks(conn, source="all", consensus_since="2026-08-11", report_cache=report_cache)
    assert seen == {"modern-mtgo": "2026-08-11", "no-format-arena": "2026-08-11"}


def test_consensus_window_and_consensus_since_are_never_both_given(conn):
    with pytest.raises(ValueError):
        find_leaks(conn, consensus_since="2026-08-11", consensus_window=lambda fmt: None)
