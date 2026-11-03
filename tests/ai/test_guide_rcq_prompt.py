"""Tests for ai/guide/rcq_prompt.py: the RCQ guide's prompt (``rcq_prompt``)
and the answer's parser (``rcq_from_json``), over ``build_rcq``'s evidence.

Every corpus row is synthetic and inserted here, the way the deck guide's
own tests build theirs; each expectation is read off those rows (counts,
dates, placements), never off the code's output.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from sensei_top.ai.guide.plans import PlanProblem
from sensei_top.ai.guide.rcq_prompt import NarrativeError, rcq_from_json, rcq_prompt
from sensei_top.db import open_database
from sensei_top.guide.bundle import FORMAT_UNKNOWN_GAP
from sensei_top.guide.rcq import RecentEvent, SourceFreshness, build_rcq

TODAY = date(2026, 10, 3)
PASTED = """Deck
4 Own Card (ABC) 1
56 Mountain (ABC) 2

Sideboard
2 Side Card (ABC) 3
1 Front Face (ABC) 4
"""


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _card_row(conn, grp_id, name, oracle):
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text, type_line, mana_cost) VALUES "
        "(?, ?, ?, 'Instant', '{R}')",
        (grp_id, name, oracle),
    )


def _event(conn, event_id, event_date, *, name="e", source="MTGO", duplicate_of=None):
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, format, "
        "tier, duplicate_of) VALUES (?, 'p', 's', ?, ?, ?, 'Standard', 'B', ?)",
        (event_id, source, name, event_date, duplicate_of),
    )


def _deck(conn, event_id, deck_ord, card, *, key=None, name=None, result=None):
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, result, mainboard_json, sideboard_json, "
        "wins) VALUES (?, ?, ?, ?, '[]', 3)",
        (event_id, deck_ord, result, json.dumps([{"count": 4, "name": card}])),
    )
    if key is not None:
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES (?, ?, ?, ?, ?, "
            "'archetype', 'now')",
            (event_id, deck_ord, key, name, name),
        )


def _corpus(conn, key, n, *, event_date="2026-09-20"):
    """n classified decks of archetype key ("Arch <key>"), one event each,
    every deck playing 4x "Staple <key>" — a consensus once n >= 5."""
    for i in range(n):
        _event(conn, f"{key}-{i}", event_date)
        _deck(conn, f"{key}-{i}", 0, f"Staple {key}", key=key, name=f"Arch {key}")


def _own_deck(conn):
    """Deck d1 and one won match with it, so build_deck_guide resolves it."""
    _card_row(conn, 1, "Own Card", "Own card text.")
    _card_row(conn, 2, "Mountain", None)
    _card_row(conn, 3, "Side Card", "Side card text.")
    _card_row(conn, 4, "Front Face // Back Face", "Double-faced text.")
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Standard', ?, 't', 't')",
        (json.dumps({"maindeck": [1] * 4 + [2] * 56, "sideboard": [3, 3]}),),
    )
    _match(conn, "m-own", "2026-09-28T12:00:00", "win")


def _match(conn, match_id, started_at, result):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, format) VALUES (?, 'e', 'd1', 1, 2, 'u', 'n', ?, ?, "
        "?, ?, ?, 'concede', 'Standard')",
        (match_id, started_at, started_at, result,
         2 if result == "win" else 0, 0 if result == "win" else 2),
    )


# Seven archetypes with 10, 9, 8, 7, 6, 6 and 5 decks: 51 classified decks,
# so the top six by share are a1..a6 and a7 (5/51 = 9.8%) sits outside them.
_SEVEN = {"a1": 10, "a2": 9, "a3": 8, "a4": 7, "a5": 6, "a6": 6, "a7": 5}
_SEVEN_TOTAL = 51


def _seven_archetypes(conn):
    for grp_id, (key, n) in enumerate(_SEVEN.items(), start=100):
        _card_row(conn, grp_id, f"Staple {key}", f"Staple {key} text.")
        _corpus(conn, key, n)


def _top_six_headings(total=_SEVEN_TOTAL):
    return [
        f"-- Arch {key} ({n / total:.1%} of the field) --"
        for key, n in list(_SEVEN.items())[:6]
    ]



def _teach_own_archetype(conn):
    """One Standard definition, "Burn", that needs Own Card in the
    maindeck (the shape tests/test_metagame.py::_teach_meta stores), and
    five corpus Burn decks with 3 wins each — the consensus floor
    build_list_diff reads (min_decks=5, min_wins=3). The corpus lists
    play Own Card and Mountain, never Side Card."""
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, "
        "fetched_at) VALUES ('Standard', 'archetype', 'Burn', 'Burn', 0, ?, "
        "'2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Burn",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Own Card"]}]}),),
    )
    for i in range(5):
        _event(conn, f"burn-{i}", "2026-09-20")
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins) "
            "VALUES (?, 0, ?, '[]', 3)",
            (f"burn-{i}", json.dumps([{"count": 4, "name": "Own Card"},
                                      {"count": 56, "name": "Mountain"}])),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES (?, 0, 'Burn', 'Burn', "
            "'Burn', 'archetype', 'now')",
            (f"burn-{i}",),
        )


def test_an_expected_archetype_outside_the_top_six_gets_its_own_section(conn):
    _own_deck(conn)
    _seven_archetypes(conn)
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, ["a7"], today=TODAY)
    prompt = rcq_prompt(evidence, conn=conn)

    for heading in _top_six_headings():
        assert heading in prompt
    assert "-- Arch a7 (you expect it at the store; 9.8% of the field) --" in prompt
    assert "Staple a7 text." in prompt
    assert (
        "Expected at the store (the player's own read of their local field, not evidence): "
        "Arch a7 (9.8% of the field)"
    ) in prompt
    assert "Treat this as a prior, not a fact." in prompt
    [expected] = evidence.expected
    assert (expected.key, expected.name) == ("a7", "Arch a7")
    assert expected.record is None  # d1 has never faced a7
    assert expected.share == pytest.approx(5 / 51)


def test_an_expected_archetype_already_in_the_top_six_is_not_shown_twice(conn):
    _own_deck(conn)
    _seven_archetypes(conn)
    conn.commit()

    prompt = rcq_prompt(build_rcq(conn, "deck:d1", PASTED, ["a1"], today=TODAY), conn=conn)

    for heading in _top_six_headings():
        assert prompt.count(heading) == 1
    assert "you expect it at the store" not in prompt
    assert "-- Arch a7" not in prompt


def test_an_expected_archetype_with_no_consensus_still_gets_a_section(conn):
    """Two decks are below build_consensus's five-deck floor, so there is no
    consensus list — the heading still appears, with that gap stated."""
    _own_deck(conn)
    _seven_archetypes(conn)
    _card_row(conn, 200, "Staple thin", "Staple thin text.")
    _corpus(conn, "thin", 2)
    conn.commit()

    prompt = rcq_prompt(build_rcq(conn, "deck:d1", PASTED, ["thin"], today=TODAY), conn=conn)

    for heading in _top_six_headings(total=_SEVEN_TOTAL + 2):
        assert heading in prompt
    heading = "-- Arch thin (you expect it at the store; 3.8% of the field) --"  # 2 / 53
    assert heading in prompt
    after = prompt[prompt.index(heading):].splitlines()
    assert after[1] == "  (too few decklists on file for a consensus list)"


def test_an_expected_archetype_with_no_format_says_the_format_is_unknown(conn):
    """A deck with no format has no consensus for any archetype, however many
    decks the corpus holds: the section's gap names the unknown format, not a
    shortage of decklists."""
    _own_deck(conn)
    _seven_archetypes(conn)
    _card_row(conn, 200, "Staple full", "Staple full text.")
    _corpus(conn, "full", 5)
    conn.execute("UPDATE decks SET format = NULL")
    conn.execute("UPDATE matches SET format = NULL")
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, ["full"], today=TODAY)
    assert evidence.guide.field.fmt is None
    assert [x.key for x in evidence.expected] == ["full"]
    prompt = rcq_prompt(evidence, conn=conn)

    heading = next(
        line for line in prompt.splitlines() if line.startswith("-- Arch full (you expect it")
    )
    after = prompt[prompt.index(heading):].splitlines()
    assert after[1] == "  (no consensus list: the deck's format is unknown)"


def test_the_pasted_75_replaces_the_current_list_in_the_prompt(conn):
    _own_deck(conn)
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, [], today=TODAY)
    prompt = rcq_prompt(evidence, conn=conn)

    assert "Maindeck (60):\n4 Own Card\n56 Mountain" in prompt
    assert "Sideboard (3):\n2 Side Card\n1 Front Face" in prompt
    assert "Double-faced text." in prompt  # resolved by its front face
    assert "Expected at the store" not in prompt
    assert evidence.resolved.unresolved == ()


def test_a_plan_boarding_in_a_card_not_in_the_pasted_sideboard_is_a_problem(conn):
    _own_deck(conn)
    conn.commit()
    evidence = build_rcq(conn, "deck:d1", PASTED, [], today=TODAY)

    raw = {
        "game_plan": "g", "expected_field": "f", "flex_notes": [], "checklist": ["c"],
        "matchups": [
            {"archetype": "Arch one", "prose": "p", "play_draw": "pd",
             "board_in": [{"card": "Not In Side", "n": 1}],
             "board_out": [{"card": "Own Card", "n": 1}]},
            # the full double-faced name counts against the pasted front face
            {"archetype": "Arch two", "prose": "p", "play_draw": "pd",
             "board_in": [{"card": "Side Card", "n": 2},
                          {"card": "Front Face // Back Face", "n": 1}],
             "board_out": [{"card": "Own Card", "n": 3}]},
        ],
    }
    narrative = rcq_from_json(json.dumps(raw), evidence)

    assert PlanProblem(
        "Arch one", "brings in 1x Not In Side, but the sideboard only has 0.",
    ) in narrative.problems
    assert not [p for p in narrative.problems if p.archetype == "Arch two"]
    assert narrative.matchups[1].play_draw == "pd"


def test_a_plan_is_checked_against_the_pasted_counts_not_the_identitys(conn):
    """The identity's own list has no Front Face; the pasted 75 has one, and
    only one — so 2 in is a problem and 1 in was not (test above)."""
    _own_deck(conn)
    conn.commit()
    evidence = build_rcq(conn, "deck:d1", PASTED, [], today=TODAY)
    raw = {
        "game_plan": "g", "expected_field": "f", "flex_notes": [], "checklist": [],
        "matchups": [
            {"archetype": "Arch one", "prose": "p", "play_draw": "pd",
             "board_in": [{"card": "Front Face", "n": 2}],
             "board_out": [{"card": "Own Card", "n": 2}]},
        ],
    }
    problems = rcq_from_json(raw, evidence).problems
    assert PlanProblem(
        "Arch one", "brings in 2x Front Face, but the sideboard only has 1.",
    ) in problems


def test_an_expected_archetype_without_a_plan_is_a_problem(conn):
    _own_deck(conn)
    _seven_archetypes(conn)
    conn.commit()
    evidence = build_rcq(conn, "deck:d1", PASTED, ["a7"], today=TODAY)
    raw = {"game_plan": "g", "expected_field": "f", "flex_notes": [], "checklist": [],
           "matchups": []}
    assert PlanProblem(
        "Arch a7", "no plan was written for an archetype you expect at the store.",
    ) in rcq_from_json(raw, evidence).problems


def test_recent_events_drop_duplicates_and_anything_older_than_seven_days(conn):
    """TODAY is 2026-10-03, so the window opens 2026-09-26. new (10-02) and
    edge (09-26) are in; old (09-25) is out; twin (10-03) republishes new
    and is out. new's placements 1st/2nd/3rd are its top 8, in that order;
    9th is not. edge is a league ("5-0"), so it records no placements."""
    _own_deck(conn)
    _event(conn, "new", "2026-10-02", name="Standard Challenge")
    _deck(conn, "new", 0, "X", key="ka", name="Arch A", result="2nd Place")
    _deck(conn, "new", 1, "X", key="kb", name="Arch B", result="1st Place")
    _deck(conn, "new", 2, "X", key="ka", name="Arch A", result="9th Place")
    _deck(conn, "new", 3, "X", result="3rd Place")  # never classified
    _event(conn, "edge", "2026-09-26", name="Standard League")
    _deck(conn, "edge", 0, "X", key="ka", name="Arch A", result="5-0")
    _event(conn, "old", "2026-09-25", name="Old Challenge")
    _deck(conn, "old", 0, "X", key="ka", name="Arch A", result="1st Place")
    _event(conn, "twin", "2026-10-03", name="Standard Challenge", source="MTGmelee",
           duplicate_of="new")
    _deck(conn, "twin", 0, "X", key="ka", name="Arch A", result="1st Place")
    conn.execute(
        "INSERT INTO meta_fetch_source (source, ref, fetched_at, events) "
        "VALUES ('fbettega', 'r', '2026-10-03T08:00:00Z', 4)"
    )
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, [], today=TODAY)

    assert evidence.recent_events == (
        RecentEvent(date="2026-10-02", name="Standard Challenge", source="MTGO", tier="B",
                    decks=4, top8=("Arch B", "Arch A", "(unclassified)")),
        RecentEvent(date="2026-09-26", name="Standard League", source="MTGO", tier="B",
                    decks=1, top8=()),
    )
    # the twin's later date moves no source's "newest event"
    assert evidence.freshness == (
        SourceFreshness(source="fbettega", newest_event=None,
                        fetched_at="2026-10-03T08:00:00Z"),
        SourceFreshness(source="MTGO", newest_event="2026-10-02", fetched_at=None),
    )
    prompt = rcq_prompt(evidence, conn=conn)
    assert "- fbettega: fetched 2026-10-03T08:00:00Z\n" in prompt
    assert "- MTGO: newest event 2026-10-02\n" in prompt
    assert "none" not in prompt and "never recorded" not in prompt
    assert "Old Challenge" not in prompt
    assert "- 2026-10-02 Standard Challenge (MTGO, tier B, 4 decks); top 8: Arch B, Arch A, " \
        "(unclassified)" in prompt


def test_an_expected_key_no_corpus_deck_carries_is_dropped_with_a_gap(conn):
    _own_deck(conn)
    _seven_archetypes(conn)
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, ["a7", "nowhere"], today=TODAY)
    prompt = rcq_prompt(evidence, conn=conn)

    assert [x.key for x in evidence.expected] == ["a7"]
    assert evidence.unknown_expected == ("nowhere",)
    assert (
        "Left out of the expected archetypes, since no tournament deck carries the key: "
        "nowhere."
    ) in prompt
    assert "-- nowhere" not in prompt


def test_a_wrongly_typed_plan_is_a_narrative_error(conn):
    _own_deck(conn)
    conn.commit()
    evidence = build_rcq(conn, "deck:d1", PASTED, [], today=TODAY)
    raw = {
        "game_plan": "g", "expected_field": "f", "flex_notes": [], "checklist": [],
        "matchups": [
            {"archetype": "Arch one", "prose": "p", "play_draw": "pd",
             "board_in": [{"card": 7, "n": "two"}], "board_out": []},
        ],
    }
    with pytest.raises(NarrativeError):
        rcq_from_json(raw, evidence)


def test_a_no_format_deck_with_an_own_pick_has_no_diff_and_no_too_few_line(conn):
    _own_deck(conn)
    _teach_own_archetype(conn)
    conn.execute("UPDATE decks SET format = NULL")
    conn.execute("UPDATE matches SET format = NULL")
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, [], own="Burn", today=TODAY)
    prompt = rcq_prompt(evidence, conn=conn)

    assert evidence.own_verdict_key == "Burn"
    assert evidence.list_diff is None
    assert FORMAT_UNKNOWN_GAP in prompt
    assert "Too few winning decklists" not in prompt
