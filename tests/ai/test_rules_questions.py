"""``ai/rules_questions.py`` and ``POST /api/rules-questions``: the questions a
feature asks the hosted coach, written from card rows by three templates and
three filters (phase 0's misses). The card rows have three sources: rows
copied from ``tests/fixtures/scryfall_*.jsonl`` (and Duress's text from
``tests/test_effects.py``); rows written from memory (Negate, Day of
Judgment, Mindbreak Trap, Skyclave Apparition); and made-up rows, whose names
begin with "Test" or which carry a comment saying so. Every expectation is
worked out by hand from the text and the rules in ``docs/llm.md``, never
copied from a run.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from sensei_top.ai import rules_notes, rules_questions
from sensei_top.ai.coach.evidence import DeckList
from sensei_top.ai.rules_questions import CardRow, build_questions, coach_cards, has_hook
from sensei_top.api.app import create_app
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

ANGEL = CardRow(
    "Dazzling Angel", "Creature — Angel",
    "Flying\nWhenever another creature you control enters, you gain 1 life.", ("Flying",),
)
MOTHER = CardRow(
    "Mother of Runes", "Creature — Human Cleric",
    "{T}: Target creature you control gains protection from the color of your choice "
    "until end of turn.",
)
BLOOM = CardRow(
    "Lotus Bloom", "Artifact",
    "Suspend 3—{0} (Rather than cast this card from your hand, pay {0} and exile it "
    "with three time counters on it. At the beginning of your upkeep, remove a time "
    "counter. When the last is removed, you may cast it without paying its mana cost.)"
    "\n{T}, Sacrifice this artifact: Add three mana of any one color.", ("Suspend",),
)
OPAL = CardRow(
    "Mox Opal", "Legendary Artifact",
    "Metalcraft — {T}: Add one mana of any color. Activate only if you control "
    "three or more artifacts.", ("Metalcraft",),
)
SCOUR = CardRow(
    "Thought Scour", "Instant", "Target player mills two cards.\nDraw a card.", ("Mill",),
)
AYLI = CardRow(
    "Ayli, Eternal Pilgrim", "Legendary Creature — Kor Cleric",
    "Deathtouch (Any amount of damage this deals to a creature is enough to destroy it.)\n"
    "{1}, Sacrifice another creature: You gain life equal to the sacrificed creature's "
    "toughness.\n{1}{W}{B}, Sacrifice another creature: Exile target nonland permanent. "
    "Activate only if you have at least 10 life more than your starting life total.",
    ("Deathtouch",),
)
SANGUINE = CardRow(
    "Sanguine Indulgence", "Sorcery",
    "This spell costs {3} less to cast if you've gained 3 or more life this turn.\n"
    "Return up to two target creature cards from your graveyard to your hand.",
)
ARENA = CardRow(
    "Phyrexian Arena", "Enchantment",
    "At the beginning of your upkeep, you draw a card and lose 1 life.",
)
RANGER = CardRow(
    "Beast-Kin Ranger", "Creature — Elf Ranger",
    "Trample (This creature can deal excess combat damage to the player or planeswalker "
    "it's attacking.)\nWhenever another creature you control enters, this creature gets "
    "+1/+0 until end of turn.", ("Trample",),
)
DRAKUSETH = CardRow(
    "Drakuseth, Maw of Flames", "Legendary Creature — Dragon",
    "Flying\nWhenever Drakuseth attacks, Drakuseth deals 4 damage to any target and 3 "
    "damage to each of up to two other targets.", ("Flying",),
)
# Written from memory, like Negate. Mindbreak Trap is abbreviated (it lacks its
# alternative-cost line) and so is Skyclave Apparition (it lacks its
# leaves-the-battlefield token ability).
DAY = CardRow("Day of Judgment", "Sorcery", "Destroy all creatures.")
TRAP = CardRow("Mindbreak Trap", "Instant", "Exile any number of target spells.")
SKYCLAVE = CardRow(
    "Skyclave Apparition", "Creature — Kor Wizard",
    "When this creature enters, exile up to one target nonland, nontoken permanent you "
    "don't control with mana value 4 or less.",
)
# Ayli's own cost clause, alone: "Sacrifice another creature" is not aimed at theirs.
COST = CardRow(
    "Ayli's Cost", "Creature — Kor Cleric",
    "{1}, Sacrifice another creature: You gain life equal to the sacrificed creature's "
    "toughness.",
)
NEGATE = CardRow("Negate", "Instant", "Counter target noncreature spell.")
# Made up, not a real card.
QUICK = CardRow("Quick One", "Creature — Elf", "Flash", ("Flash",))
MYSTERY = CardRow("Unknown Card")
TEACHINGS = CardRow("Waterlogged Teachings // Inundated Archive", "Instant // Land")


def _texts(questions):
    return [q.question for q in questions]


# --- the hook (filter 3) -------------------------------------------------


def test_a_pair_with_no_hook_is_dropped():
    assert not has_hook(ANGEL, ARENA)
    assert build_questions([ANGEL], [ARENA]) == []


def test_a_pair_where_one_targets_the_others_kind_is_kept_either_way():
    # Ayli exiles a "nonland permanent", which a Mox Opal is.
    assert has_hook(OPAL, AYLI) and has_hook(AYLI, OPAL)
    assert has_hook(MOTHER, AYLI)
    assert not has_hook(MOTHER, OPAL)


def test_a_card_without_text_is_no_pair_for_anything():
    bare = CardRow("Bare Creature", "Creature — Elf")
    assert not has_hook(bare, AYLI) and not has_hook(AYLI, bare)
    assert not has_hook(bare, NEGATE) and not has_hook(NEGATE, bare)


def test_this_artifact_is_not_a_hook():
    # "Sacrifice this artifact" on Lotus Bloom is about itself.
    assert not has_hook(BLOOM, OPAL)


def test_another_and_you_control_are_not_aimed_at_the_opponent():
    assert not has_hook(MOTHER, ANGEL)  # "target creature you control"
    assert not has_hook(COST, ANGEL)  # "Sacrifice another creature"
    assert not has_hook(RANGER, ANGEL)


def test_counter_is_a_hook_only_as_a_verb():
    noun = CardRow(
        "Counter Noun", "Enchantment",
        "Whenever you gain life, put a +1/+1 counter on each creature.",
    )
    assert not has_hook(noun, ANGEL)
    assert has_hook(NEGATE, SCOUR)


def test_returning_from_your_own_graveyard_is_not_a_hook():
    assert not has_hook(SANGUINE, ANGEL)


def test_every_non_type_phrase_is_blanked_not_only_the_first():
    land = CardRow("Test Land", "Land", "{T}: Add {C}.")
    assert not has_hook(SKYCLAVE, land)  # "nonland, nontoken permanent"
    assert has_hook(SKYCLAVE, OPAL) and has_hook(SKYCLAVE, ANGEL)


def test_damage_to_any_target_hooks_creatures_planeswalkers_and_battles():
    walker = CardRow("Test Walker", "Legendary Planeswalker — Test", "Static text.")
    battle = CardRow("Test Battle", "Battle — Siege", "Static text.")
    assert has_hook(DRAKUSETH, ANGEL)
    assert has_hook(DRAKUSETH, walker) and has_hook(DRAKUSETH, battle)
    assert not has_hook(DRAKUSETH, OPAL) and not has_hook(DRAKUSETH, ARENA)


def test_plural_kinds_match():
    assert has_hook(DAY, ANGEL)  # "creatures"
    assert has_hook(TRAP, SCOUR)  # "spells"
    # "Sweep" is made up, not a real card.
    assert has_hook(CardRow("Sweep", "Sorcery", "Exile all sorceries."), SANGUINE)


def test_noncreature_is_a_whole_word_and_never_a_creature():
    assert not has_hook(NEGATE, ANGEL)
    assert has_hook(NEGATE, SCOUR)
    assert has_hook(NEGATE, OPAL) and has_hook(NEGATE, ARENA)  # noncreature spells
    assert not has_hook(NEGATE, CardRow("Test Land", "Land"))


def test_a_card_without_text_or_type_has_no_hook():
    assert not has_hook(MYSTERY, AYLI)
    assert build_questions([MYSTERY], [CardRow("Other Unknown")]) == []


def test_text_in_reminder_parentheses_is_not_a_hook():
    # Bushwhack's reminder text names damage; only its rules text counts.
    bushwhack = CardRow(
        "Bushwhack", "Sorcery",
        "Choose one —\n• Search your library for a basic land card, reveal it, "
        "put it into your hand, then shuffle.\n• Target creature you control fights "
        "target creature you don't control. (Each deals damage equal to its power to the "
        "other.)",
        ("Fight",),
    )
    assert has_hook(bushwhack, ANGEL)
    assert not has_hook(bushwhack, OPAL)


# --- T2 (filter 1) and T3 (filter 2) --------------------------------------


def test_evergreen_keywords_get_no_question_set_mechanics_do():
    assert build_questions([ANGEL, RANGER, AYLI, SCOUR], []) == []
    assert _texts(build_questions([OPAL], [])) == ["How does metalcraft work on Mox Opal?"]


def test_no_in_response_question_for_a_sorcery():
    questions = build_questions([ANGEL], [DAY])
    assert [q.template for q in questions] == ["T1"]
    assert not any("in response" in q.question for q in questions)


def test_an_instant_or_a_flash_card_is_asked_in_response():
    # Made up, not a real card.
    flash = CardRow("Quick One", "Creature — Elf", "Flash", ("Flash",))
    assert _texts(build_questions([ANGEL], [SCOUR])) == [
        "What happens if my opponent casts Thought Scour in response to Dazzling Angel?"
    ]
    assert _texts(build_questions([ANGEL], [flash])) == [
        "What happens if my opponent casts Quick One in response to Dazzling Angel?"
    ]


def test_a_double_faced_card_is_named_by_its_front_face():
    assert _texts(build_questions([OPAL], [TEACHINGS])) == [
        "What happens if my opponent casts Waterlogged Teachings in response to Mox Opal?",
        "How does metalcraft work on Mox Opal?",
    ]


def test_a_land_is_never_the_card_cast_into():
    land = CardRow("Test Land", "Land")
    assert build_questions([land], [SCOUR]) == []


# --- selection --------------------------------------------------------------


MINE = [ANGEL, MOTHER, BLOOM, OPAL]
THEIRS = [SCOUR, AYLI, SANGUINE, ARENA]


def test_selection_order_cap_and_card_use():
    got = build_questions(MINE, THEIRS)
    assert _texts(got) == [
        "How does Dazzling Angel interact with Ayli, Eternal Pilgrim?",
        "How does Mother of Runes interact with Ayli, Eternal Pilgrim?",
        "What happens if my opponent casts Thought Scour in response to Dazzling Angel?",
        "How does suspend work on Lotus Bloom?",
    ]
    assert [q.template for q in got] == ["T1", "T1", "T3", "T2"]
    assert len(got) == 4


def test_the_same_input_gives_the_same_questions():
    assert build_questions(MINE, THEIRS) == build_questions(MINE, THEIRS)


def test_an_empty_slot_is_filled_from_the_other_templates():
    assert _texts(build_questions([BLOOM, OPAL], [])) == [
        "How does suspend work on Lotus Bloom?",
        "How does metalcraft work on Mox Opal?",
    ]


def test_a_card_is_in_at_most_two_questions():
    got = build_questions([ANGEL, MOTHER, BLOOM], [AYLI])
    assert _texts(got) == [
        "How does Dazzling Angel interact with Ayli, Eternal Pilgrim?",
        "How does Mother of Runes interact with Ayli, Eternal Pilgrim?",
        "How does suspend work on Lotus Bloom?",
    ]  # Ayli is full, so Lotus Bloom's own hook with it is not asked


def test_the_coach_gets_only_set_mechanic_questions(tmp_path):
    conn = open_database(tmp_path / "c.db")
    for i, card in enumerate([ANGEL, BLOOM], start=1):
        conn.execute(
            "INSERT INTO cards (grp_id, name, type_line, oracle_text, keywords) "
            "VALUES (?, ?, ?, ?, ?)",
            (i, card.name, card.type_line, card.oracle_text, json.dumps(list(card.keywords))),
        )
    decks = [DeckList("D", ((4, "Dazzling Angel"), (2, "Lotus Bloom")), ((3, "Lotus Bloom"),), 0)]
    cards = coach_cards(conn, decks)
    assert [c.name for c in cards.mine] == ["Lotus Bloom", "Dazzling Angel"]
    assert cards.theirs == ()
    assert _texts(build_questions(cards.mine, cards.theirs)) == [
        "How does suspend work on Lotus Bloom?"
    ]


# --- the route ---------------------------------------------------------------

FIXTURE = Path(__file__).parent.parent / "fixtures" / "match_session.log"
MATCH = "fd5624a4-d970-40eb-80aa-fba9d2ce17b3"
ARCHETYPE = "mardu_discard"
URL = "/api/rules-questions"


def _card(conn, grp_id, card):
    conn.execute(
        "INSERT OR REPLACE INTO cards (grp_id, name, type_line, oracle_text, keywords) "
        "VALUES (?, ?, ?, ?, ?)",
        (grp_id, card.name, card.type_line, card.oracle_text, json.dumps(list(card.keywords))),
    )


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "api.db"
    conn = open_database(path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    recent = (date.today() - timedelta(days=3)).isoformat()
    # Shares in the consensus: Thought Scour 6 of 6, Ayli 5 of 6, Quick One 4 of 6;
    # by name the order is the reverse (Ayli, Quick One, Thought Scour).
    _card(conn, 900001, AYLI)
    _card(conn, 900002, QUICK)
    _card(conn, 900003, SCOUR)
    for i in range(6):
        deck = [{"count": 4, "name": SCOUR.name}]
        if i < 5:
            deck.append({"count": 4, "name": AYLI.name})
        if i < 4:
            deck.append({"count": 4, "name": QUICK.name})
        conn.execute(
            "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
            "format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', ?, 'Standard', 'B')",
            (f"e{i}", recent),
        )
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, "
            "wins, losses) VALUES (?, 0, ?, '[]', 5, 0)",
            (f"e{i}", json.dumps(deck)),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) "
            "VALUES (?, 0, ?, 'Mardu Discard', 'Mardu Discard', 'archetype', 'now')",
            (f"e{i}", ARCHETYPE),
        )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def client(db_path, make_client):
    with make_client(create_app(db_path)) as c:
        yield c


def _db(client):
    conn = sqlite3.connect(client.app.state.database)
    conn.row_factory = sqlite3.Row
    return conn


def _post(client, **body):
    return client.post(URL, json=body)


def test_a_match_with_no_card_text_says_why(client):
    out = _post(client, feature="match", match_id=MATCH).json()
    assert out == {"questions": [], "reason": "no_card_text"}


def test_a_match_with_my_cards_and_no_opponent_cards_says_so(client):
    conn = _db(client)
    # the fixture match resolves grp 102774 twice on my side and nothing on theirs
    _card(conn, 102774, SANGUINE)
    conn.commit()
    conn.close()
    out = _post(client, feature="match", match_id=MATCH).json()
    assert out == {"questions": [], "reason": "no_opponent_cards"}


def _resolves(conn, seat, grp_id, times, seq):
    for _ in range(times):
        seq += 1
        conn.execute(
            "INSERT INTO card_events (match_id, game_number, seq, turn_number, category, "
            "grp_id, seat) VALUES (?, 1, ?, 2, 'Resolve', ?, ?)", (MATCH, seq, grp_id, seat),
        )
    return seq


def test_a_match_ranks_each_side_by_resolves_not_by_name(client):
    conn = _db(client)
    # Mine: Mother of Runes 3 resolves, the fixture's own card 2 (stand-in for Lotus Bloom),
    # Dazzling Angel 1; by name the order is the reverse. Theirs: Thought Scour 2, Ayli 1.
    _card(conn, 102774, BLOOM)
    _card(conn, 900010, MOTHER)
    _card(conn, 900011, ANGEL)
    me, them = conn.execute(
        "SELECT self_seat, opponent_seat FROM matches WHERE match_id = ?", (MATCH,)
    ).fetchone()
    seq = _resolves(conn, me, 900010, 3, 900)
    seq = _resolves(conn, me, 900011, 1, seq)
    seq = _resolves(conn, them, 900003, 2, seq)
    _resolves(conn, them, 900001, 1, seq)
    conn.commit()
    conn.close()
    out = _post(client, feature="match", match_id=MATCH).json()
    assert [(q["question"], q["template"]) for q in out["questions"]] == [
        ("How does Mother of Runes interact with Ayli, Eternal Pilgrim?", "T1"),
        ("How does Lotus Bloom interact with Ayli, Eternal Pilgrim?", "T1"),
        ("What happens if my opponent casts Thought Scour in response to Mother of Runes?",
         "T3"),
        ("How does suspend work on Lotus Bloom?", "T2"),
    ]
    assert out["reason"] is None
    assert [q["question_hash"] for q in out["questions"]] == [
        rules_notes.question_hash(q["question"]) for q in out["questions"]
    ]
    assert not any(q["answered"] for q in out["questions"])


def test_answered_follows_a_stored_note_and_the_rules_version(client):
    conn = _db(client)
    _card(conn, 102774, BLOOM)
    conn.commit()
    first = rules_questions.build_questions([BLOOM], [])[0]
    rules_notes.store(conn, [rules_notes.RulesNote(
        question=first.question, rules_version="2026-11-14", outcome="answered",
        answer={"verdict": "v"}, confidence="high", asked_at="2026-11-17T00:00:00Z",
    )])
    conn.commit()
    conn.close()

    def answered(**extra):
        out = _post(client, feature="match", match_id=MATCH, **extra).json()
        return [q["answered"] for q in out["questions"]]

    assert answered() == [True]
    assert answered(rules_version="2026-11-14") == [True]
    assert answered(rules_version="2027-01-01") == [False]


@pytest.fixture
def seeded(client):
    conn = _db(client)
    # Stand-ins for the fixture deck's own cards, which the capture names only by id:
    # 68738 (4 copies) is Mother of Runes, 79089 (2 copies) Dazzling Angel, so the order
    # by copies, Mother then Angel, is the reverse of the order by name.
    for grp_id, card in ((68738, MOTHER), (79089, ANGEL), (900004, BLOOM)):
        _card(conn, grp_id, card)
    conn.commit()
    conn.close()
    return client.get("/api/guide/decks").json()[0]["key"]


def test_the_deck_guide_ranks_by_copies_and_by_staple_share(client, seeded):
    out = _post(client, feature="guide", key=seeded).json()
    assert [q["question"] for q in out["questions"]] == [
        "How does Mother of Runes interact with Ayli, Eternal Pilgrim?",
        "How does Dazzling Angel interact with Ayli, Eternal Pilgrim?",
        "What happens if my opponent casts Thought Scour in response to Mother of Runes?",
        "What happens if my opponent casts Thought Scour in response to Dazzling Angel?",
    ]


def test_the_rcq_guide_reads_the_pasted_list(client, seeded):
    # Copies: Mother 4, Lotus Bloom 3, Angel 2; by name the order is the reverse.
    text = "Deck\n4 Mother of Runes\n2 Dazzling Angel\n\nSideboard\n3 Lotus Bloom\n"
    out = _post(
        client, feature="rcq", key=seeded, decklist=text, expected=[ARCHETYPE]
    ).json()
    assert [q["question"] for q in out["questions"]] == [
        "How does Mother of Runes interact with Ayli, Eternal Pilgrim?",
        "How does Lotus Bloom interact with Ayli, Eternal Pilgrim?",
        "What happens if my opponent casts Thought Scour in response to Mother of Runes?",
        "How does suspend work on Lotus Bloom?",
    ]


def test_the_coach_with_too_few_matches_has_no_evidence(client):
    out = _post(client, feature="coach").json()
    assert out == {"questions": [], "reason": "no_evidence"}


def test_unknown_match_and_deck_are_404(client):
    assert _post(client, feature="match", match_id="nope").status_code == 404
    assert _post(client, feature="guide", key="nope").status_code == 404
    assert _post(client, feature="rcq", key="nope", decklist="4 X").status_code == 404


def test_a_feature_missing_what_it_needs_is_422(client):
    assert _post(client, feature="match").status_code == 422
    assert _post(client, feature="guide").status_code == 422
    assert _post(client, feature="rcq", key="k").status_code == 422
    assert _post(client, feature="nope").status_code == 422


def test_post_without_the_client_header_is_403(db_path):
    from fastapi.testclient import TestClient

    bare = TestClient(create_app(db_path), base_url="http://127.0.0.1:8000")
    body = {"feature": "match", "match_id": MATCH}
    assert bare.post(URL, json=body).status_code == 403


def test_the_route_writes_nothing(client):
    _post(client, feature="match", match_id=MATCH)
    conn = _db(client)
    assert conn.execute("SELECT COUNT(*) FROM rules_note").fetchone()[0] == 0
    conn.close()
