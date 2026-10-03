"""Tests for guide/rcq.py: the RCQ guide's evidence (``build_rcq``), its
prompt (``rcq_prompt``) and the answer's parser (``rcq_from_json``).

Every corpus row is synthetic and inserted here, the way the deck guide's
own tests build theirs; each expectation is read off those rows (counts,
dates, placements), never off the code's output.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from sensei_top.db import open_database
from sensei_top.guide.bundle import DeckGuide, build_deck_guide
from sensei_top.guide.field import archetype_key_by_name, faced_archetypes
from sensei_top.guide.list_diff import ListDiff
from sensei_top.guide.markdown import render
from sensei_top.guide.narrative import (
    MIN_TIMES_FACED,
    MOST_FACED_ARCHETYPES,
    TOP_ARCHETYPES_FOR_ORACLE_TEXT,
    _oracle_text_block,
    build_guide_context,
)
from sensei_top.guide.plans import PlanProblem
from sensei_top.guide.rcq import (
    RecentEvent,
    SourceFreshness,
    build_rcq,
    rcq_from_json,
    rcq_prompt,
)
from sensei_top.review.consensus import build_consensus

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
        "games_lost, completed_reason) VALUES (?, 'e', 'd1', 1, 2, 'u', 'n', ?, ?, ?, "
        "?, ?, 'concede')",
        (match_id, started_at, started_at, result,
         2 if result == "win" else 0, 0 if result == "win" else 2),
    )


def _faced(conn, key, n):
    """n lost matches of deck d1 against a classifier verdict for key."""
    for i in range(n):
        match_id = f"faced-{key}-{i}"
        _match(conn, match_id, f"2026-09-2{i}T12:00:00", "loss")
        conn.execute(
            "INSERT INTO opponent_archetype (match_id, format, archetype_key, "
            "archetype_name, colors, label, method, confidence, cards_seen, "
            "conditions_met, conditions_unknown, evidence_json, classified_at) VALUES "
            "(?, 'Standard', ?, ?, 'R', ?, 'archetype', 'high', 3, '[]', '[]', '{}', 'now')",
            (match_id, key, f"Arch {key}", f"Arch {key}"),
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
    assert (expected.key, expected.name, expected.wins, expected.losses) == (
        "a7", "Arch a7", 0, 0,
    )
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
    assert "Old Challenge" not in prompt
    assert "- 2026-10-02 Standard Challenge (MTGO, tier B, 4 decks); top 8: Arch B, Arch A, " \
        "(unclassified)" in prompt


def test_recent_shares_cover_the_last_fourteen_days_only(conn):
    """09-19 is the window's first day (14 back from 10-03): a1's 3 decks
    there count, a2's 2 decks on 09-18 do not."""
    _own_deck(conn)
    _corpus(conn, "a1", 3, event_date="2026-09-19")
    _corpus(conn, "a2", 2, event_date="2026-09-18")
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, [], today=TODAY)

    assert evidence.recent_classified_decks == 3
    assert [(s.archetype, s.decks, s.share) for s in evidence.recent_shares] == [
        ("Arch a1", 3, 1.0),
    ]


def test_unknown_deck_key_is_none(conn):
    conn.commit()
    assert build_rcq(conn, "deck:nope", PASTED, [], today=TODAY) is None


def test_build_guide_context_is_unchanged_by_the_section_refactor(conn):
    """The deck guide's own prompt context, byte for byte against the
    function as it stood before its section loop was shared with the RCQ
    guide (copied below), on a guide with top-share and most-faced
    sections and a staple's oracle text shared between two archetypes."""
    _own_deck(conn)
    _seven_archetypes(conn)
    for key in ("f1", "f2"):
        _card_row(conn, 300 + int(key[1]), f"Staple {key}", f"Staple {key} text.")
        _corpus(conn, key, 5)
    _faced(conn, "f1", 4)
    _faced(conn, "f2", 3)
    _faced(conn, "a1", 3)
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    expected = _pre_refactor_build_guide_context(guide, conn=conn)
    assert "-- Arch f1 (you faced it 4 times" in expected  # both passes exercised
    assert build_guide_context(guide, conn=conn) == expected


# The pre-refactor guide/narrative.py::build_guide_context, verbatim but for
# its name — the reference the test above compares against.
def _pre_refactor_build_guide_context(guide: DeckGuide, *, conn) -> str | None:
    """Serialize a deck guide into the text a prompt sends. ``None`` when
    there is nothing to write about — a deck with no matches at all.
    """
    if guide.provenance.deck.matches == 0:
        return None

    lines: list[str] = [
        f"Deck: {guide.provenance.deck.name or guide.provenance.deck.key}",
        render(guide),
        "",
        "Card oracle text for your own maindeck and sideboard:",
    ]
    own_grp_ids = list({
        *(guide.provenance.deck.current_cards.get("maindeck") or []),
        *(guide.provenance.deck.current_cards.get("sideboard") or []),
    })
    lines.append(_oracle_text_block(conn, own_grp_ids))

    diff: ListDiff | None = guide.list_diff
    own_name = diff.archetype_name if diff is not None else None
    own_key = diff.archetype_key if diff is not None else None
    key_by_name = archetype_key_by_name(conn)
    since = guide.provenance.window_start
    # Oracle text is printed once per card across every opponent section —
    # and not at all for a card already given with the player's own 75 —
    # since the same staples recur across archetypes and each repeat is pure
    # prompt cost.
    shown_grp_ids: set[int] = set(own_grp_ids)

    def section(heading: str, archetype_key: str) -> bool:
        consensus = build_consensus(conn, archetype_key, since=since)
        if consensus is None:
            return False
        staples = consensus.staples()
        lines.append(heading)
        for card in staples:
            lines.append(f"  {card.copies:.1f}x {card.name} ({card.share:.0%} of decks)")
        grp_ids = [
            c.grp_id for c in staples
            if c.grp_id is not None and c.grp_id not in shown_grp_ids
        ]
        shown_grp_ids.update(grp_ids)
        text = _oracle_text_block(conn, grp_ids)
        if text:
            lines.append(text)
        return True

    lines.append("")
    lines.append(
        f"Consensus staples and oracle text for the top {TOP_ARCHETYPES_FOR_ORACLE_TEXT} "
        f"opponent archetypes by field share (a card's oracle text is given once, the first "
        f"time it appears):"
    )
    shown_keys: set[str] = set()
    for share in guide.field.shares:
        if len(shown_keys) >= TOP_ARCHETYPES_FOR_ORACLE_TEXT:
            break
        if share.archetype == own_name:
            continue
        archetype_key = key_by_name.get(share.archetype)
        if archetype_key is None or archetype_key in shown_keys:
            continue
        if section(
            f"-- {share.archetype} ({share.share:.1%} of the field) --", archetype_key,
        ):
            shown_keys.add(archetype_key)

    share_by_name = {s.archetype: s.share for s in guide.field.shares}
    faced = sorted(
        (
            (key, name, n)
            for key, (name, n) in faced_archetypes(
                conn, guide.provenance.deck.deck_ids, since=since,
            ).items()
            # key_by_name.get(name) == key: brief/from_guide.py stores each
            # plan under key_by_name[plan.archetype], so a name that maps to
            # another key would file this matchup's plan under the wrong one.
            if n >= MIN_TIMES_FACED and key not in shown_keys and key != own_key
            and key_by_name.get(name) == key
        ),
        key=lambda t: (-t[2], t[0]),
    )
    faced_lines_at = len(lines)
    shown_faced = 0
    for key, name, n in faced:
        if shown_faced >= MOST_FACED_ARCHETYPES:
            break
        share = share_by_name.get(name)
        share_text = (
            f"{share:.1%} of the field" if share is not None
            else "not among the field's top archetypes"
        )
        window_text = "since the reset" if since is not None else "in your history"
        if section(f"-- {name} (you faced it {n} times {window_text}; {share_text}) --", key):
            shown_faced += 1
    if shown_faced:
        lines.insert(faced_lines_at, "")
        lines.insert(
            faced_lines_at + 1,
            f"Consensus staples and oracle text for the archetypes you have actually faced "
            f"most (at least {MIN_TIMES_FACED} times each), not already listed above:",
        )

    return "\n".join(lines)

