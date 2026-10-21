"""The answer contract (``answers.py``): what every copied prompt asks an
assistant to send back, and the one reader of what comes back.

The expected wording is the approved English, written out here rather than
read off ``answer_format``; every other expectation comes from the answer
the test itself builds, or from the fixture-backed database the routes read.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sensei_top import cli
from sensei_top.answers import (
    Answer,
    AnswerError,
    answer_format,
    brief_for,
    check_length,
    coach_for,
    coverage_for,
    guide_for,
    match_for,
    prose_of,
    prose_schema,
    rcq_for,
    read_answer,
)
from sensei_top.api.app import create_app
from sensei_top.brief.narrative import _BRIEF_TOOL, _MULTI_BRIEF_TOOL
from sensei_top.brief.store import list_hash
from sensei_top.db import open_database
from sensei_top.guide.deck import list_identities
from sensei_top.guide.narrative import _GUIDE_TOOL
from sensei_top.guide.rcq import _RCQ_TOOL
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
HASH = "0123456789abcdef" * 4
OTHER_HASH = "fedcba9876543210" * 4
BODY = {"engine": "Cantrips are your mana.", "fix": "Deploy earlier."}
SCHEMA = {"type": "object", "properties": {"engine": {"type": "string"}}}


def _headed(for_: str, body: dict, context: str | None = HASH) -> dict:
    out: dict = {"for": for_}
    if context is not None:
        out["context"] = context
    out["answer"] = body
    return out


# --- answer_format -----------------------------------------------------------


def test_the_contract_with_a_context_is_the_approved_wording():
    """The approved text, line breaks included: the assistant copies the
    header back only if the prompt says so plainly, last, just before it
    answers."""
    expected = (
        "Answer with exactly one JSON object and nothing else: no text before or\n"
        "after it. The tracker this prompt came from reads the answer back, and its\n"
        "first two fields tell it which card the answer belongs to and which data it\n"
        "was written for, so copy them exactly as they are written here:\n"
        "\n"
        "{\n"
        '  "for": "guide:deck:d1",\n'
        f'  "context": "{HASH}",\n'
        '  "answer": {an object matching the schema below}\n'
        "}\n"
        "\n"
        'The schema for "answer":\n'
        "{\n"
        '  "type": "object",\n'
        '  "properties": {\n'
        '    "engine": {\n'
        '      "type": "string"\n'
        "    }\n"
        "  }\n"
        "}"
    )
    assert answer_format("guide:deck:d1", HASH, SCHEMA) == expected


def test_the_contract_without_a_context_asks_for_the_for_line_alone():
    expected = (
        "Answer with exactly one JSON object and nothing else: no text before or\n"
        "after it. The tracker this prompt came from reads the answer back, and its\n"
        "first field tells it which card the answer belongs to, so copy it exactly\n"
        "as it is written here:\n"
        "\n"
        "{\n"
        '  "for": "rcq:deck:d1",\n'
        '  "answer": {an object matching the schema below}\n'
        "}\n"
        "\n"
        'The schema for "answer":\n'
        "{\n"
        '  "type": "object",\n'
        '  "properties": {\n'
        '    "engine": {\n'
        '      "type": "string"\n'
        "    }\n"
        "  }\n"
        "}"
    )
    assert answer_format("rcq:deck:d1", None, SCHEMA) == expected


def test_a_prose_contract_says_how_to_write_the_text_inside_one_string():
    """The whole text sits in one JSON string, so the escaping is spelled out
    for the prose cards, and only for them."""
    text = answer_format("leaks", HASH, prose_schema("plain prose"))
    assert text.endswith(
        '\n\nPut the whole text in "prose" as a single JSON string: write each line\n'
        'break as \\n and each quotation mark as \\".'
    )
    assert '"description": "plain prose"' in text
    assert "Put the whole text" not in answer_format("leaks", HASH, SCHEMA)


def test_each_card_names_itself_as_the_plan_spells_it():
    assert guide_for("k") == "guide:k"
    assert brief_for("k", "a") == "brief:k:a"
    assert coverage_for("k") == "coverage:k"
    assert rcq_for("k") == "rcq:k"
    assert match_for("m") == "match:m"
    assert coach_for("Standard") == "coach:Standard"


# --- read_answer -------------------------------------------------------------


def test_a_bare_headed_answer_reads_its_body_and_context():
    raw = json.dumps(_headed("guide:k", BODY))
    assert read_answer(raw, "guide:k", require_header=True) == Answer(body=BODY, context=HASH)


def test_a_fenced_answer_reads():
    """Assistants wrap JSON in a ```json fence as a matter of course."""
    # The trailing ``{}`` makes the whole text, and its first ``{`` to its
    # last ``}``, unreadable as one object: only the fence step reads this.
    raw = (
        "```json\n" + json.dumps(_headed("guide:k", BODY), indent=2) + "\n```\n"
        "An empty one would look like {}."
    )
    assert read_answer(raw, "guide:k", require_header=True).body == BODY


def test_an_answer_with_text_around_it_reads():
    raw = (
        "Here is the guide you asked for:\n\n"
        + json.dumps(_headed("guide:k", BODY))
        + "\n\nLet me know if you want changes."
    )
    answer = read_answer(raw, "guide:k", require_header=True)
    assert answer.body == BODY
    assert answer.context == HASH


def test_something_that_is_not_one_object_is_refused():
    for raw in ("no json here", "[1, 2, 3]", "{not json at all"):
        with pytest.raises(AnswerError) as exc:
            read_answer(raw, "guide:k", require_header=True)
        assert str(exc.value) == (
            "The answer is not a JSON object. Paste the whole answer, "
            "from its first `{` to its last `}`."
        )
        assert exc.value.status == 422


def test_an_answer_for_another_kind_of_card_names_that_card():
    raw = json.dumps(_headed("match:m1", {"prose": "x"}))
    with pytest.raises(AnswerError) as exc:
        read_answer(raw, "guide:k", require_header=True)
    assert str(exc.value) == "This answer is for a match report, not this one. Paste it there."
    assert exc.value.belongs_to == "match"


@pytest.mark.parametrize(
    ("got", "expected", "sentence"),
    [
        ("guide:other", "guide:k",
         "This answer is for a deck guide of another deck. Paste it there."),
        ("brief:k:other", "brief:k:a",
         "This answer is for a matchup brief of another deck or opponent. Paste it there."),
        ("coverage:other", "coverage:k",
         "This answer is for a matchup coverage of another deck. Paste it there."),
        ("rcq:other", "rcq:k", "This answer is for an RCQ guide of another deck. Paste it there."),
        ("match:m2", "match:m1",
         "This answer is for a match report of another match. Paste it there."),
        ("coach:Modern", "coach:Standard",
         "This answer is for a coach report of another format. Paste it there."),
    ],
)
def test_an_answer_for_the_same_card_of_another_key_says_so(got, expected, sentence):
    raw = json.dumps(_headed(got, BODY))
    with pytest.raises(AnswerError) as exc:
        read_answer(raw, expected, require_header=True)
    assert str(exc.value) == sentence
    assert exc.value.belongs_to == got.split(":", 1)[0]


def test_the_for_line_is_checked_before_the_body():
    """Another card's answer is named as such even when its body is missing:
    the "for" check comes before anything else."""
    raw = json.dumps({"for": "leaks", "context": "edited"})
    with pytest.raises(AnswerError) as exc:
        read_answer(raw, "guide:k", require_header=True)
    assert str(exc.value) == "This answer is for the training plan, not this one. Paste it there."


def test_an_unrecognised_for_line_names_no_card():
    """A ``for`` this module does not know is never echoed back: the answer is
    refused as one with no telling where it belongs."""
    for got in ("<script>", 7):
        raw = json.dumps({"for": got, "answer": BODY})
        with pytest.raises(AnswerError) as exc:
            read_answer(raw, "guide:k", require_header=False)
        assert str(exc.value) == (
            'The answer has no "for" line, so there is no telling where it belongs. '
            "Copy the prompt here again and paste the new answer."
        )
        assert exc.value.belongs_to is None


@pytest.mark.parametrize(
    "context",
    ["abc", HASH.upper(), HASH + "0", HASH[:-1] + "g", 12, ["x"]],
)
def test_a_context_of_the_wrong_shape_is_refused(context):
    """It is stored as the hash the answer was written for, so anything that
    is not a 64-character lowercase hex digest was edited."""
    raw = json.dumps({"for": "guide:k", "context": context, "answer": BODY})
    with pytest.raises(AnswerError) as exc:
        read_answer(raw, "guide:k", require_header=True)
    assert str(exc.value) == (
        'The answer\'s "context" line was changed. It has to be copied back '
        "exactly as the prompt gave it."
    )


def test_a_card_with_no_context_reads_none():
    raw = json.dumps(_headed("rcq:k", BODY, context=None))
    assert read_answer(raw, "rcq:k", require_header=True) == Answer(body=BODY, context=None)
    # Its prompt asks for none, so one sent anyway is not stored.
    raw = json.dumps(_headed("rcq:k", BODY, context=HASH))
    assert read_answer(raw, "rcq:k", require_header=True).context is None


@pytest.mark.parametrize(
    "for_", ["guide:k", "brief:k:a", "coverage:k", "match:m1", "leaks", "coach:Standard"],
)
def test_a_headed_answer_without_its_context_is_refused(for_):
    """Every card but the RCQ guide stores its context as the hash the answer
    was written for; a header without one would leave that hash to be
    guessed (rule 4), so it is refused like an edited one. Only an answer
    with no header at all is read without it."""
    raw = json.dumps(_headed(for_, BODY, context=None))
    for require_header in (True, False):
        with pytest.raises(AnswerError) as exc:
            read_answer(raw, for_, require_header=require_header)
        assert str(exc.value) == (
            'The answer\'s "context" line was changed. It has to be copied back '
            "exactly as the prompt gave it."
        )
    assert read_answer(json.dumps(BODY), for_, require_header=False).context is None


def test_a_header_with_no_answer_object_is_refused():
    for obj in (
        {"for": "guide:k", "context": HASH},
        {"for": "guide:k", "context": HASH, "answer": "text"},
    ):
        with pytest.raises(AnswerError) as exc:
            read_answer(json.dumps(obj), "guide:k", require_header=True)
        assert str(exc.value) == (
            'The answer has its "for" line but no "answer" object after it.'
        )


def test_a_missing_header_is_refused_only_when_required():
    """The dashboard requires the header; the CLI imports read an answer
    saved before the contract as the body itself."""
    raw = json.dumps(BODY)
    with pytest.raises(AnswerError) as exc:
        read_answer(raw, "guide:k", require_header=True)
    assert str(exc.value).startswith('The answer has no "for" line')

    answer = read_answer(raw, "guide:k", require_header=False)
    assert answer == Answer(body=BODY, context=None, headerless=True)


def test_an_answer_over_256_kb_is_413():
    check_length("x" * (256 * 1024))
    with pytest.raises(AnswerError) as exc:
        check_length("x" * (256 * 1024 + 1))
    assert exc.value.status == 413
    # Bytes, not characters: "é" is two bytes in UTF-8, so this is half as
    # many characters as the limit and still one byte past it.
    with pytest.raises(AnswerError) as exc:
        check_length("é" * (128 * 1024 + 1))
    assert exc.value.status == 413
    assert str(exc.value) == (
        "The answer is longer than any answer here needs to be. "
        "Check that only the answer was pasted."
    )


def test_a_prose_answer_reads_its_text_and_refuses_an_empty_one():
    answer = read_answer(json.dumps(_headed("leaks", {"prose": "Line one.\nLine two."})),
                         "leaks", require_header=True)
    assert prose_of(answer) == "Line one.\nLine two."
    with pytest.raises(AnswerError) as exc:
        prose_of(Answer(body={"prose": "  \n"}, context=None))
    assert str(exc.value) == "The answer has no text in it."
    with pytest.raises(AnswerError) as exc:
        prose_of(Answer(body={"text": "x"}, context=None))
    assert str(exc.value).startswith("The answer could not be read: ")


def test_the_sentences_are_in_the_requests_language():
    from sensei_top import i18n

    raw = json.dumps(_headed("match:m1", BODY))
    with i18n.use_language("pt-BR"), pytest.raises(AnswerError) as exc:
        read_answer(raw, "guide:k", require_header=True)
    assert str(exc.value) == (
        "Esta resposta é para um relatório de partida, não para este quadro. Cole-a lá."
    )


# --- every copied prompt ends with the contract ------------------------------


def _seed_corpus(db_path: Path) -> None:
    """Six Standard decks of one archetype: enough for a field consensus, so
    the brief and coverage prompts have something to be written from."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO cards (grp_id, name, mana_cost, type_line, oracle_text) "
        "VALUES (990001, 'Marauding Mako', '{1}', 'Creature', 'Text.')"
    )
    for i in range(6):
        conn.execute(
            "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
            "format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', '2026-08-15', 'Standard', 'B')",
            (f"e{i}",),
        )
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, "
            "wins, losses) VALUES (?, 0, ?, '[]', 5, 0)",
            (f"e{i}", json.dumps([{"count": 4, "name": "Marauding Mako"}])),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES (?, 0, 'mardu_discard', "
            "'Mardu Discard', 'Mardu Discard', 'archetype', 'now')",
            (f"e{i}",),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "answers.db"
    conn = open_database(path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    _seed_corpus(path)
    return path


@pytest.fixture
def client(db_path, make_client):
    with make_client(create_app(db_path)) as c:
        yield c


@pytest.fixture
def identity(db_path):
    conn = open_database(db_path)
    try:
        return list_identities(conn)[0]
    finally:
        conn.close()


def test_the_guide_prompt_ends_with_its_contract(client, identity):
    body = client.get(f"/api/guide/{identity.key}/narrative").json()
    assert body["prompt"].endswith(
        "\n\n---\n\n" + answer_format(
            guide_for(identity.key), list_hash(identity.current_cards),
            _GUIDE_TOOL["input_schema"],
        )
    )


def test_the_brief_prompt_ends_with_its_contract(client, identity):
    body = client.get(f"/api/guide/{identity.key}/briefs/mardu_discard/prompt").json()
    assert body["status"] == "ok"
    assert body["prompt"].endswith(
        "\n\n---\n\n" + answer_format(
            brief_for(identity.key, "mardu_discard"), list_hash(identity.current_cards),
            _BRIEF_TOOL["input_schema"],
        )
    )


def test_the_coverage_prompt_ends_with_its_contract(client, identity):
    body = client.get(f"/api/guide/{identity.key}/coverage/prompt").json()
    assert body["status"] == "ok"
    assert body["prompt"].endswith(
        "\n\n---\n\n" + answer_format(
            coverage_for(identity.key), list_hash(identity.current_cards),
            _MULTI_BRIEF_TOOL["input_schema"],
        )
    )


def test_the_rcq_prompt_ends_with_its_contract_and_no_context(client, identity):
    """An RCQ guide records one pasted list and has no staleness hash, so its
    contract carries no ``context``."""
    body = client.get(
        f"/api/guide/{identity.key}/rcq/preview",
        params={"decklist": "Deck\n4 Alpha Card\n56 Mountain\n"},
    ).json()
    assert body["prompt"].endswith(
        "\n\n---\n\n" + answer_format(rcq_for(identity.key), None, _RCQ_TOOL["input_schema"])
    )


def test_the_schema_is_said_once_in_a_copied_prompt(client, identity):
    """The old "Answer as a single JSON object matching this schema" line
    before the evidence moved into the contract; it is not said twice."""
    prompt = client.get(f"/api/guide/{identity.key}/narrative").json()["prompt"]
    assert "Answer as a single JSON object matching this schema" not in prompt
    assert prompt.count("Answer with exactly one JSON object") == 1


# --- the CLI imports ---------------------------------------------------------


def _guide_answer(matchups: list | None = None) -> dict:
    return {"engine": "Cantrips are your mana.", "fix": "Deploy earlier.",
            "card_notes": [], "matchups": matchups or [], "checklist": []}


def test_a_headed_guide_import_stores_the_hash_it_was_written_for(db_path, identity, tmp_path):
    """An answer written for an older 75 is stored with that 75's hash, so the
    card's own staleness flags it."""
    answer = tmp_path / "answer.txt"
    matchup = {"archetype": "Mardu Discard", "prose": "Trade early.",
               "board_in": [], "board_out": []}
    body = _guide_answer([matchup])
    answer.write_text(
        "Here it is:\n```json\n"
        + json.dumps(_headed(guide_for(identity.key), body, context=OTHER_HASH))
        + "\n```\n"
    )
    cli.main(["--db", str(db_path), "guide", "--deck", identity.key, "--import", str(answer)])
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT deck_key, list_hash FROM deck_narrative").fetchall()
    # The matchup plans it carries become briefs written for the same 75.
    briefs = conn.execute(
        "SELECT archetype_key, list_hash, source FROM matchup_brief"
    ).fetchall()
    conn.close()
    assert rows == [(identity.key, OTHER_HASH)]
    assert briefs == [("mardu_discard", OTHER_HASH, "guide")]


def test_a_headed_guide_import_without_its_context_is_refused(db_path, identity, tmp_path):
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(_headed(guide_for(identity.key), _guide_answer(), None)))
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "--db", str(db_path), "guide", "--deck", identity.key, "--import", str(answer),
        ])
    assert str(exc.value).endswith(
        'The answer\'s "context" line was changed. It has to be copied back '
        "exactly as the prompt gave it."
    )
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM deck_narrative").fetchone()[0] == 0
    conn.close()


def test_a_headerless_guide_import_is_read_with_a_warning(db_path, identity, tmp_path, capsys):
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(_guide_answer()))
    cli.main(["--db", str(db_path), "guide", "--deck", identity.key, "--import", str(answer)])
    assert (
        'This answer has no "for" line, so it was read as one saved before answers carried it.'
        in capsys.readouterr().err
    )
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT list_hash FROM deck_narrative").fetchall()
    conn.close()
    assert rows == [(list_hash(identity.current_cards),)]


def test_a_brief_import_for_another_archetype_is_refused(db_path, identity, tmp_path):
    answer = tmp_path / "answer.json"
    body = {"prose": "Trade early.", "play_around": [], "board_in": [], "board_out": []}
    answer.write_text(json.dumps(_headed(brief_for(identity.key, "izzet_control"), body)))
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "--db", str(db_path), "brief", "--deck", identity.key,
            "--archetype", "mardu_discard", "--import", str(answer),
        ])
    assert str(exc.value).endswith(
        "This answer is for a matchup brief of another deck or opponent. Paste it there."
    )
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM matchup_brief").fetchone()[0] == 0
    conn.close()


def test_a_headed_brief_import_stores_its_context(db_path, identity, tmp_path):
    answer = tmp_path / "answer.json"
    body = {"prose": "Trade early.", "play_around": [], "board_in": [], "board_out": []}
    answer.write_text(
        json.dumps(_headed(brief_for(identity.key, "mardu_discard"), body, context=OTHER_HASH))
    )
    cli.main([
        "--db", str(db_path), "brief", "--deck", identity.key,
        "--archetype", "mardu_discard", "--import", str(answer),
    ])
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT archetype_key, list_hash FROM matchup_brief").fetchall()
    conn.close()
    assert rows == [("mardu_discard", OTHER_HASH)]


def test_a_coverage_import_reads_the_coverage_header(db_path, identity, tmp_path):
    answer = tmp_path / "answer.json"
    item = {"archetype_key": "mardu_discard", "prose": "Trade early.",
            "play_around": [], "board_in": [], "board_out": []}
    answer.write_text(json.dumps(_headed(coverage_for(identity.key), {"briefs": [item]})))
    cli.main([
        "--db", str(db_path), "brief", "--deck", identity.key,
        "--missing", "--import", str(answer),
    ])
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT archetype_key, list_hash FROM matchup_brief").fetchall()
    conn.close()
    assert rows == [("mardu_discard", HASH)]


def test_an_rcq_import_of_a_guide_answer_is_refused(db_path, identity, tmp_path):
    deck = tmp_path / "deck.txt"
    deck.write_text("Deck\n4 Alpha Card\n56 Mountain\n")
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(_headed(guide_for(identity.key), _guide_answer())))
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "--db", str(db_path), "rcq", "--deck", identity.key,
            "--decklist", str(deck), "--import", str(answer),
        ])
    assert str(exc.value).endswith(
        "This answer is for a deck guide, not this one. Paste it there."
    )


# --- the prose cards: the copied prompt asks for {"prose": ...}, the call does not

PROSE_TAIL_SENTENCE = (
    'Put the whole text in "prose" as a single JSON string: write each line\n'
    'break as \\n and each quotation mark as \\".'
)
CONTRACT_OPENING = "Answer with exactly one JSON object and nothing else"


def _fake_prose_writer(sent: list):
    from sensei_top.llm.client import Completion

    def write(prompt, *, cfg, label):
        sent.append(prompt)
        return Completion(
            text="Some prose.", model="claude-opus-5", input_tokens=1, output_tokens=1,
            cost_usd=0.001,
        )

    return write


def _assert_prose_contract(copied: str, sent: str, for_: str, context: str, description: str):
    """The copied prompt is the generate path's prompt, then ``---``, then the
    contract with this card's own header; the generate path's carries none."""
    assert CONTRACT_OPENING not in sent
    assert '"prose"' not in sent
    assert copied.startswith(sent + "\n\n---\n\n" + CONTRACT_OPENING)
    assert f'  "for": {json.dumps(for_)},\n  "context": "{context}",\n' in copied
    assert f'"description": "{description}"' in copied
    assert copied.count(CONTRACT_OPENING) == 1
    assert copied.endswith(PROSE_TAIL_SENTENCE)


def test_the_match_report_prompt_asks_for_prose_and_the_call_does_not(
    monkeypatch, client, db_path,
):
    from sensei_top.llm import client as llm_client_module
    from sensei_top.llm import config as llm_config_module
    from sensei_top.llm.config import LLMConfig
    from sensei_top.review.narrative_store import read_match_narrative

    match_id = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
    sent: list = []
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(llm_client_module, "write_prose", _fake_prose_writer(sent))
    assert client.post(f"/api/matches/{match_id}/report/narrative").status_code == 200

    conn = open_database(db_path)
    try:
        stored = read_match_narrative(conn, match_id)
    finally:
        conn.close()
    body = client.get(f"/api/matches/{match_id}/report/narrative").json()
    assert body["stale"] is False
    _assert_prose_contract(
        body["prompt"], sent[0], match_for(match_id), stored.context_hash, "plain prose",
    )
    # What the POST stored is what it sent: no contract in it either.
    assert stored.prompt == sent[0]


def test_the_leak_plan_prompt_asks_for_prose_and_the_call_does_not(
    monkeypatch, client, db_path,
):
    from sensei_top.api.routes import review as review_routes
    from sensei_top.llm import client as llm_client_module
    from sensei_top.llm import config as llm_config_module
    from sensei_top.llm.config import LLMConfig
    from sensei_top.review.leaks import Leak
    from sensei_top.review.leaks_store import read_leaks_narrative

    fake_leak = Leak(
        code="mana_screwed", category="deckbuilding", sample_title="Stuck on lands",
        n_with=15, win_rate_with=0.3, ci_with=(0.15, 0.5),
        n_without=40, win_rate_without=0.55, ci_without=(0.4, 0.7),
        gap=0.25, match_ids_with=("m1",),
    )
    monkeypatch.setattr(review_routes, "find_leaks", lambda conn, **kwargs: [fake_leak])
    sent: list = []
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(llm_client_module, "write_prose", _fake_prose_writer(sent))
    assert client.post("/api/review/leaks/narrative").status_code == 200

    conn = open_database(db_path)
    try:
        stored = read_leaks_narrative(conn)
    finally:
        conn.close()
    body = client.get("/api/review/leaks/narrative").json()
    assert body["stale"] is False
    _assert_prose_contract(body["prompt"], sent[0], "leaks", stored.context_hash, "plain prose")
    assert stored.prompt == sent[0]


def test_the_coach_prompt_asks_for_prose_and_the_call_does_not(
    monkeypatch, tmp_path, make_client,
):
    from sensei_top.coach.store import latest_coach_report
    from sensei_top.llm import client as llm_client_module
    from sensei_top.llm import config as llm_config_module
    from sensei_top.llm.client import Completion
    from sensei_top.llm.config import LLMConfig

    path = tmp_path / "coach.db"
    conn = open_database(path)
    for i in range(10):
        started = f"2026-0{1 + i % 9}-0{1 + i % 9}T00:00:00"
        result = "win" if i % 2 == 0 else "loss"
        conn.execute(
            "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
            "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
            "games_lost, completed_reason, source, format) VALUES (?, 'Traditional_Ladder', "
            "NULL, 1, 2, 'OPPCLIENTID0001', 'OppPlayerOne', ?, ?, ?, 1, 0, 'r', 'arena', "
            "'Standard')",
            (f"m{i}", started, started, result),
        )
        conn.execute(
            "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
            "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 6, 0, 0)",
            (f"m{i}", result),
        )
    conn.commit()
    conn.close()

    sent: list = []

    def write_report(prompt, *, cfg, label, allowed_domains, max_searches=8):
        sent.append(prompt)
        return Completion(
            text="## Focus areas\nReport.", model="claude-opus-5", input_tokens=1,
            output_tokens=1, cost_usd=0.001, citations=(), web_search_requests=0,
        )

    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(llm_client_module, "write_report", write_report)
    with make_client(create_app(path)) as c:
        # Before the POST: a stored report would be listed as the "previous"
        # one in the next prompt, so the two would no longer share a prefix.
        body = c.get("/api/coach/narrative").json()
        posted = c.post("/api/coach/narrative")
        assert posted.status_code == 200
        after = c.get("/api/coach/narrative").json()

    conn = open_database(path)
    try:
        stored = latest_coach_report(conn, "Standard")
    finally:
        conn.close()
    assert body["status"] == "prompt"
    _assert_prose_contract(
        body["prompt"], sent[0], coach_for("Standard"), stored.context_hash,
        "markdown with the headings named above",
    )
    # The POST returns and stores the prompt it sent, without the contract.
    assert posted.json()["prompt"] == sent[0]
    assert stored.prompt == sent[0]
    # With a report stored the GET still serves the copyable prompt, written
    # for the evidence alone: the stored hash, not stale.
    assert after["status"] == "ok"
    assert after["stale"] is False
    assert f'  "context": "{stored.context_hash}",\n' in after["prompt"]
    assert after["prompt"].count(CONTRACT_OPENING) == 1
    assert after["prompt"].endswith(PROSE_TAIL_SENTENCE)
