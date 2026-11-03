"""The prompt half of the i18n rule: **every prompt is English**, whatever
language the request asked for. Split from ``tests/test_i18n.py``, whose
docstring says how the marker catalogue works; these tests need ``ai/``,
which builds the prompts.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import polib
import pytest

from sensei_top import claude_config as llm_config
from sensei_top import i18n
from sensei_top.ai.brief import narrative as brief_narrative
from sensei_top.ai.coach import evidence as coach_evidence
from sensei_top.ai.coach import narrative as coach_narrative
from sensei_top.ai.guide import narrative as guide_narrative
from sensei_top.ai.guide import rcq_prompt as rcq_prompt_module
from sensei_top.ai.review import leaks_narrative, narrative
from sensei_top.ai.routes import guide as guide_ai_routes
from sensei_top.ai.routes import leaks as leaks_routes
from sensei_top.ai.routes import match_report as match_report_routes
from sensei_top.ai.routes import rcq as rcq_ai_routes
from sensei_top.api import create_app
from sensei_top.api.routes import guide as guide_routes
from sensei_top.api.routes import matches as matches_routes
from sensei_top.api.routes import rcq as rcq_routes
from sensei_top.api.routes import review as review_routes
from sensei_top.db import open_database
from sensei_top.guide import rcq as guide_rcq
from sensei_top.guide.deck import DeckIdentity, list_identities
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.review import leaks as review_leaks
from sensei_top.review.findings import Category, Confidence, Finding, Gap, Severity
from sensei_top.review.match_report import build_match_report

REPO = Path(__file__).resolve().parent.parent.parent
POT = REPO / "src" / "sensei_top" / "locale" / "sensei_top.pot"
FIXTURE = Path(__file__).parent.parent / "fixtures" / "match_session.log"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
PT_BR_PLURALS = "nplurals=2; plural=(n > 1);"

PROBE = "i18n test probe: this sentence is never in the product"
MARKER = "[pt-BR marker] "


def _write_po(locale_dir: Path, language: str, entries: list[polib.POEntry], *,
              plural_forms: str = PT_BR_PLURALS) -> Path:
    po = polib.POFile()
    po.metadata = {
        "Content-Type": "text/plain; charset=UTF-8",
        "Plural-Forms": plural_forms,
    }
    for entry in entries:
        po.append(entry)
    path = locale_dir / language / "LC_MESSAGES" / "sensei_top.po"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(po), encoding="utf-8")
    return path


@pytest.fixture
def catalogues(tmp_path):
    """Load catalogues from a ``locale`` directory under ``tmp_path``
    instead of the shipped one; the shipped set comes back afterwards."""
    locale_dir = tmp_path / "locale"
    locale_dir.mkdir()
    yield locale_dir
    i18n.load_catalogues()


@pytest.fixture
def marker_catalogue(catalogues):
    """A PT-BR catalogue translating every ``.pot`` msgid, and ``PROBE``, to
    ``MARKER`` + the English (the module docstring says why)."""
    entries = [polib.POEntry(msgid=PROBE, msgstr=MARKER + PROBE)]
    for template in polib.pofile(str(POT)):
        if template.msgid_plural:
            entries.append(polib.POEntry(
                msgid=template.msgid, msgid_plural=template.msgid_plural,
                msgstr_plural={0: MARKER + template.msgid, 1: MARKER + template.msgid_plural},
            ))
        else:
            entries.append(polib.POEntry(msgid=template.msgid, msgstr=MARKER + template.msgid))
    _write_po(catalogues, i18n.PT_BR, entries)
    i18n.load_catalogues(catalogues)
    with i18n.use_language("pt-BR"):
        assert i18n._(PROBE) == MARKER + PROBE, "the marker catalogue did not load"
    return catalogues

@pytest.fixture
def fixture_db(tmp_path):
    db_path = tmp_path / "api.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    return db_path


@pytest.fixture
def client(fixture_db, make_client):
    with make_client(create_app(fixture_db)) as c:
        yield c




# --- every prompt is English -------------------------------------------


class _Stop(BaseException):
    """Ends a builder at its first touch of an argument. A ``BaseException``
    so no ``except Exception`` inside a builder can swallow it."""


class _Spy:
    """Stands in for every argument a builder takes. The first time the
    builder touches one, it records what ``PROBE`` translates to *in the
    builder's own scope*, then stops the builder — which is all these tests
    need: whether that scope is English."""

    def __init__(self, seen: list[str]) -> None:
        object.__setattr__(self, "_seen", seen)

    def _touch(self, *_args, **_kwargs):
        self._seen.append(i18n._(PROBE))
        raise _Stop

    def __getattr__(self, name):
        return self._touch()

    __bool__ = __len__ = __iter__ = __str__ = __format__ = __getitem__ = __call__ = _touch


# Every prompt builder, with the arguments that reach its first touch.
BUILDERS = {
    "review.narrative.full_prompt": lambda s: narrative.full_prompt(s),
    "review.narrative.build_narrative_context":
        lambda s: narrative.build_narrative_context(s, s, field=None),
    "review.leaks_narrative.build_leaks_context": lambda s: leaks_narrative.build_leaks_context(s),
    "review.leaks_narrative.full_prompt": lambda s: leaks_narrative.full_prompt(s),
    "guide.narrative.build_guide_context": lambda s: guide_narrative.build_guide_context(s, conn=s),
    "guide.narrative.full_prompt": lambda s: guide_narrative.full_prompt(s, conn=s),
    "guide.rcq.rcq_prompt": lambda s: rcq_prompt_module.rcq_prompt(s, conn=s),
    "brief.narrative.build_brief_context":
        lambda s: brief_narrative.build_brief_context(s, s, "k", "Label"),
    "brief.narrative.full_multi_prompt":
        lambda s: brief_narrative.full_multi_prompt(s, s, [("k", "Label")]),
    "brief.narrative.full_prompt": lambda s: brief_narrative.full_prompt(s, s, "k", "Label"),
    "coach.narrative.build_coach_context":
        lambda s: coach_narrative.build_coach_context(s, s, s, s),
    "coach.narrative.full_prompt": lambda s: coach_narrative.full_prompt(s, "Standard"),
    "coach.narrative.build_coach_prompt":
        lambda s: coach_narrative.build_coach_prompt(s, fmt="Standard"),
    "coach.evidence._build_examples": lambda s: coach_evidence._build_examples(
        s, s, s, s, s, consensus_window=s, consensus_cache=s, colors_cache=s, view_cache=s,
    ),
}


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_every_prompt_builder_runs_in_english(marker_catalogue, name):
    seen: list[str] = []
    with i18n.use_language("pt-BR"), pytest.raises(_Stop):
        BUILDERS[name](_Spy(seen))
    assert seen == [PROBE]


def test_the_coach_system_prompt_is_english(marker_catalogue, monkeypatch):
    """``system_prompt`` takes only a format name, so ``_Spy`` cannot reach
    inside it; the template it fills can. Its ``replace`` records what
    ``PROBE`` translates to in ``system_prompt``'s own scope."""
    seen: list[str] = []

    class Recording(str):
        def replace(self, *args):
            seen.append(i18n._(PROBE))
            return str(self).replace(*args)

    monkeypatch.setattr(coach_narrative, "SYSTEM_PROMPT", Recording("Report on {fmt}."))
    with i18n.use_language("pt-BR"):
        assert coach_narrative.system_prompt("Standard") == "Report on Standard."
    assert seen == [PROBE]


def _assert_english_prompt(client, path: str) -> str:
    portuguese = client.get(path, headers={"Accept-Language": "pt-BR"})
    english = client.get(path)
    assert portuguese.status_code == english.status_code == 200, path
    prompt = portuguese.json()["prompt"]
    assert MARKER not in (prompt or ""), path
    assert prompt == english.json()["prompt"], path
    return prompt


def test_the_fixtures_prompts_are_english_after_its_pages_ran_in_portuguese(
    marker_catalogue, client,
):
    """Every page that shares an object or a cache with a prompt runs under
    PT-BR first, so a cache holding translated text would hand it on."""
    key = client.get("/api/guide/decks").json()[0]["key"]
    for page in (
        f"/api/matches/{MATCH_WIN}/report", "/api/review/leaks", f"/api/guide/{key}",
        f"/api/guide/{key}/markdown", f"/api/guide/{key}/coverage", "/api/coach",
    ):
        client.get(page, headers={"Accept-Language": "pt-BR"})

    for path in (
        f"/api/matches/{MATCH_WIN}/report/narrative",
        f"/api/guide/{key}/narrative",
        f"/api/guide/{key}/rcq/preview",
    ):
        assert _assert_english_prompt(client, path), path


def test_the_match_report_prompt_builds_its_report_in_english(
    marker_catalogue, client, monkeypatch,
):
    """The route builds the report itself, before the serializer runs, so
    the whole closure must be English. Positive control: the report page,
    under PT-BR, does see Portuguese."""
    seen: list[str] = []
    real = matches_routes.build_match_report

    def recording(*args, **kwargs):
        seen.append(i18n._(PROBE))
        return real(*args, **kwargs)

    monkeypatch.setattr(matches_routes, "build_match_report", recording)
    monkeypatch.setattr(match_report_routes, "build_match_report", recording)
    pt = {"Accept-Language": "pt-BR"}
    client.get(f"/api/matches/{MATCH_WIN}/report", headers=pt)
    client.get(f"/api/matches/{MATCH_WIN}/report/narrative", headers=pt)
    assert seen == [MARKER + PROBE, PROBE]


def test_the_leaks_prompt_builds_its_leaks_in_english(marker_catalogue, client, monkeypatch):
    """Same shape as the match report: ``find_leaks`` writes each leak's
    text inside the route's closure."""
    seen: list[str] = []

    def recording(*_args, **_kwargs):
        seen.append(i18n._(PROBE))
        return []

    monkeypatch.setattr(review_routes, "find_leaks", recording)
    monkeypatch.setattr(leaks_routes, "find_leaks", recording)
    pt = {"Accept-Language": "pt-BR"}
    client.get("/api/review/leaks", headers=pt)
    client.get("/api/review/leaks/narrative", headers=pt)
    assert seen == [MARKER + PROBE, PROBE]


def _insert_ladder_match(
    conn, match_id: str, result: str, started_at: str, deck_id: str | None = None,
) -> None:
    """The minimal shape the coach's population query reads (as in
    tests/ai/test_coach_api.py): a ladder event and one game."""
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, source, format) VALUES (?, 'Traditional_Ladder', ?, "
        "1, 2, 'OPPCLIENTID0001', 'OppPlayerOne', ?, ?, ?, 1, 0, 'r', 'arena', 'Standard')",
        (match_id, deck_id, started_at, started_at, result),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 6, 0, 0)",
        (match_id, result),
    )


def test_the_coach_prompt_is_english_after_its_page_ran_in_portuguese(
    marker_catalogue, tmp_path, make_client,
):
    """Ten matches: the coach's ``MIN_SAMPLE`` floor, below which there is
    no prompt at all."""
    db_path = tmp_path / "coach.db"
    conn = open_database(db_path)
    for i in range(10):
        _insert_ladder_match(
            conn, f"m{i}", "win" if i % 2 == 0 else "loss", f"2026-0{1 + i % 9}-0{1 + i % 9}",
        )
    conn.commit()
    conn.close()

    with make_client(create_app(db_path)) as client:
        for page in ("/api/coach", "/api/review/leaks"):
            client.get(page, headers={"Accept-Language": "pt-BR"})
        assert _assert_english_prompt(client, "/api/coach/narrative")


def _probing_report(*args, **kwargs):
    """``build_match_report`` with ``PROBE`` where an analyzer's prose would
    be: a gap on every report, and on a loss a leak-candidate finding for
    the whole match — so the leak finder ranks it (every loss has it, no
    win does), the leak prompts quote its ``pattern`` and the coach's
    worked example its title and detail."""
    report = build_match_report(*args, **kwargs)
    if report is None:
        return None
    findings = report.findings
    if report.result == "loss":
        findings += (Finding(
            code="i18n_probe", analyzer="i18n_probe", category=Category.BASELINE,
            severity=Severity.FLAG, confidence=Confidence.OBSERVED,
            title=i18n._(PROBE), detail=i18n._(PROBE), pattern=i18n._(PROBE),
        ),)
    gaps = (*report.gaps, Gap(analyzer="i18n_probe", reason=i18n._(PROBE)))
    return dataclasses.replace(report, findings=findings, gaps=gaps)


def test_a_page_in_portuguese_never_hands_its_reports_to_a_prompt(
    marker_catalogue, fixture_db, make_client, monkeypatch,
):
    """The Leaks, Guide and Coach pages share one ``MatchReport`` cache with
    their prompts (``api/sql.py::_shared_report_cache``). Loaded under PT-BR
    first, they fill it with Portuguese findings; each prompt afterwards
    must be the one a fresh, English-only server writes, context hash
    included. Twenty matches: the fixture's two plus nine of each result on
    the same deck, so the leak finder's ``MIN_SAMPLE`` of ten holds on both
    sides and the fixture's loss, the one with ``turns`` rows, is a coach
    example."""
    for module in (review_leaks, coach_evidence, matches_routes, match_report_routes):
        monkeypatch.setattr(module, "build_match_report", _probing_report)
    conn = open_database(fixture_db)
    [deck_id] = conn.execute(
        "SELECT deck_id FROM matches WHERE match_id = ?", (MATCH_WIN,),
    ).fetchone()
    for i in range(18):
        _insert_ladder_match(
            conn, f"i18n-{i:02d}", "loss" if i % 2 else "win",
            f"2026-08-{1 + i // 2:02d}T1{i % 2}:00:00", deck_id=deck_id,
        )
    conn.commit()

    pt = {"Accept-Language": "pt-BR"}
    with make_client(create_app(fixture_db)) as fresh:
        key = fresh.get("/api/guide/decks").json()[0]["key"]
        prompts = (
            "/api/coach/narrative", "/api/review/leaks/narrative", f"/api/guide/{key}/narrative",
        )
        baseline = {path: fresh.get(path).json()["prompt"] for path in prompts}
    assert all(PROBE in prompt for prompt in baseline.values()), "the probe never reached a prompt"
    english = coach_narrative.build_coach_prompt(conn, fmt="Standard", report_cache={})

    with make_client(create_app(fixture_db)) as client:
        for page in ("/api/coach", "/api/review/leaks", f"/api/guide/{key}"):
            assert client.get(page, headers=pt).status_code == 200, page
        warmed = dict(client.app.state.report_cache[1])
        # Positive control: the pages did leave Portuguese reports behind.
        assert any(
            gap.reason == MARKER + PROBE
            for report in warmed.values() if report is not None for gap in report.gaps
        )
        after = coach_narrative.build_coach_prompt(conn, fmt="Standard", report_cache=warmed)
        assert (after.prompt, after.context_hash) == (english.prompt, english.context_hash)
        for path in prompts:
            assert client.get(path, headers=pt).json()["prompt"] == baseline[path], path
            assert client.get(path).json()["prompt"] == baseline[path], path
    conn.close()


def test_the_markdown_exports_are_english(marker_catalogue, client, monkeypatch):
    """The guide and RCQ exports are prompt input, so they render in
    English under any request language. The RCQ export needs a stored
    guide; a stand-in is enough, since ``render_rcq`` is the recorder."""
    seen: list[str] = []

    def recording(*_args, **_kwargs):
        seen.append(i18n._(PROBE))
        return "markdown"

    monkeypatch.setattr(guide_routes, "render_guide_markdown", recording)
    monkeypatch.setattr(rcq_ai_routes, "render_rcq", recording)
    monkeypatch.setattr(rcq_ai_routes, "latest_rcq", lambda *_args: object())
    key = client.get("/api/guide/decks").json()[0]["key"]
    pt = {"Accept-Language": "pt-BR"}
    for path in (f"/api/guide/{key}/markdown", f"/api/guide/{key}/rcq/markdown"):
        assert client.get(path, headers=pt).json() == {"markdown": "markdown"}, path
    assert seen == [PROBE, PROBE]


def test_the_guide_and_rcq_prompts_build_their_evidence_in_english(
    marker_catalogue, client, monkeypatch,
):
    """The deck guide and the RCQ evidence are built in the route, before
    the prompt builder runs, and the prompt quotes them. The recorders
    stop each route at a 404 — before any credential is looked up for the
    two POSTs. Positive control: the guide page, under PT-BR, sees
    Portuguese."""
    seen: list[str] = []

    def recording(*_args, **_kwargs):
        seen.append(i18n._(PROBE))

    monkeypatch.setattr(guide_routes, "build_deck_guide", recording)
    monkeypatch.setattr(guide_ai_routes, "build_deck_guide", recording)
    monkeypatch.setattr(rcq_routes, "build_rcq", recording)
    monkeypatch.setattr(rcq_ai_routes, "build_rcq", recording)
    pt = {"Accept-Language": "pt-BR"}
    assert client.get("/api/guide/k", headers=pt).status_code == 404
    assert client.get("/api/guide/k/narrative", headers=pt).status_code == 404
    assert client.post("/api/guide/k/narrative", headers=pt).status_code == 404
    rcq = client.post(
        "/api/guide/k/rcq/narrative", headers=pt, json={"decklist": "", "expected": []},
    )
    assert rcq.status_code == 404
    assert seen == [MARKER + PROBE, PROBE, PROBE, PROBE]


def test_the_rcq_preview_writes_its_page_in_portuguese_and_its_prompt_in_english(
    marker_catalogue, client,
):
    """``rcq_preview`` hands one evidence object to its page and its prompt:
    built in English for the prompt, with the page's sentences written from
    its data in the request's language. The paste carries a
    line that is not a card and a four-card maindeck, so ``parse_decklist``
    owes two warnings (its own rules: an unreadable line is left out, a
    maindeck under 60 is flagged), and ``own`` names a key no corpus deck
    carries, so the 75 is not classified and says why. The prompt quotes
    all three, in English."""
    key = client.get("/api/guide/decks").json()[0]["key"]
    path = f"/api/guide/{key}/rcq/preview"
    params = {"decklist": "4 Lightning Strike\nnot a card line", "own": "no-such-archetype"}
    unreadable = 'Could not read this line, so it was left out: "not a card line"'
    short = "The maindeck has 4 cards, fewer than 60."
    reason = "No archetype with key 'no-such-archetype' is in the tournament corpus."

    portuguese = client.get(path, params=params, headers={"Accept-Language": "pt-BR"})
    english = client.get(path, params=params)
    assert portuguese.status_code == english.status_code == 200
    pt, en = portuguese.json(), english.json()

    assert en["warnings"] == [unreadable, short]
    assert en["own_unclassified_reason"] == reason
    assert pt["warnings"] == [MARKER + unreadable, MARKER + short]
    assert pt["own_unclassified_reason"] == MARKER + reason

    assert MARKER not in pt["prompt"]
    assert pt["prompt"] == en["prompt"]
    for sentence in (unreadable, short, reason):
        assert sentence in pt["prompt"], sentence


def test_the_brief_prompts_are_english(marker_catalogue, tmp_path):
    """The brief reads everything it needs from the connection, so calling
    it directly is the whole path: six corpus decks of one archetype, two
    cards with rules text."""
    conn = open_database(tmp_path / "brief.db")
    conn.executemany(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) "
        "VALUES (?, ?, ?, ?, ?)",
        [(1, "Marauding Mako", "{1}{B}", "Creature", "Menace."),
         (2, "Erode", "{B}", "Instant", "Destroy target creature.")],
    )
    mainboard = '[{"count": 4, "name": "Marauding Mako"}, {"count": 4, "name": "Erode"}]'
    for i in range(6):
        conn.execute(
            "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
            "format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', '2026-08-15', 'Standard', 'B')",
            (f"e{i}",),
        )
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins, "
            "losses) VALUES (?, 0, ?, '[]', 5, 0)",
            (f"e{i}", mainboard),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) "
            "VALUES (?, 0, 'mardu_discard', 'Mardu Discard', 'Mardu Discard', 'archetype', 'now')",
            (f"e{i}",),
        )
    conn.commit()
    identity = DeckIdentity(
        key="guid:x", arena_deck_id="x", name="My Deck", format="Standard",
        deck_ids=(), matches=0, match_wins=0, match_losses=0, games_won=0,
        games_lost=0, first_played=None, last_played=None,
        current_cards={"maindeck": [], "sideboard": []},
    )

    def both():
        return (
            brief_narrative.full_prompt(conn, identity, "mardu_discard", "Mardu Discard"),
            brief_narrative.full_multi_prompt(
                conn, identity, [("mardu_discard", "Mardu Discard")],
            ),
        )

    english = both()
    with i18n.use_language("pt-BR"):
        portuguese = both()
    conn.close()
    assert english[0] is not None and english[1] is not None
    assert portuguese == english
    assert MARKER not in repr(portuguese)


def test_the_rcq_prompt_drops_the_guides_own_unclassified_note_and_nothing_else(fixture_db):
    """The deck guide's note that the identity's own list went unclassified
    is about that list, not the pasted 75, so ``rcq_prompt`` leaves it out
    — by ``DeckGuide.own_unclassified``, not by its sentence. The fixture's
    deck has a format (Standard, from the log) and no corpus to compare it
    with, so the guide carries the note. No card in it has rules text (only
    the log was read, never a card database) and there is no card legality
    data, so the gaps after the note say so (``guide/bundle.py``'s rules),
    and the prompt must keep both."""
    own_note = (
        "Your own deck could not be classified against the field's archetype definitions"
    )
    no_text = "Rules text is missing for "
    no_legality = "No card legality data is present, so a format reset cannot be detected"
    conn = open_database(fixture_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM meta_deck").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM card_legality").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM cards WHERE oracle_text IS NOT NULL"
        ).fetchone()[0] == 0
        evidence = guide_rcq.build_rcq(conn, list_identities(conn)[0].key, "", [])
        assert evidence.guide.field.fmt is not None
        assert evidence.guide.own_unclassified
        assert evidence.guide.gaps[0].startswith(own_note)
        assert evidence.guide.provenance.oracle_coverage[1] > 0
        prompt = rcq_prompt_module.rcq_prompt(evidence, conn=conn)
    finally:
        conn.close()
    assert own_note not in prompt
    assert no_text in prompt
    assert no_legality in prompt



@pytest.fixture
def coach_client(marker_catalogue, tmp_path, make_client):
    """Ten ladder matches: the coach's ``MIN_SAMPLE`` floor."""
    db_path = tmp_path / "coach-details.db"
    conn = open_database(db_path)
    for i in range(10):
        _insert_ladder_match(
            conn, f"m{i}", "win" if i % 2 == 0 else "loss", f"2026-0{1 + i % 9}-0{1 + i % 9}",
        )
    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c, db_path


def test_the_coach_skip_gap_is_written_in_the_request_language_and_its_prompt_stays_english(
    coach_client, monkeypatch,
):
    _client, db_path = coach_client
    monkeypatch.setattr(coach_evidence, "_build_examples", lambda *a, **k: ((), ["recent_loss"]))
    sentence = (
        'An example match chosen for "recent_loss" could not be rebuilt for display and '
        "was skipped."
    )
    conn = open_database(db_path)
    try:
        with i18n.use_language("pt-BR"):
            evidence = coach_evidence.build_coach_evidence(conn, fmt="Standard")
            prompt_pt = coach_narrative.build_coach_prompt(conn, fmt="Standard")
        prompt_en = coach_narrative.build_coach_prompt(conn, fmt="Standard")
    finally:
        conn.close()
    assert MARKER + sentence in evidence.gaps
    assert prompt_pt.prompt == prompt_en.prompt
    assert MARKER not in prompt_pt.prompt
    assert sentence in prompt_en.prompt


def test_every_coach_gap_on_the_page_is_written_in_the_request_language(coach_client):
    client, _db = coach_client
    body = client.get("/api/coach", headers={"Accept-Language": "pt-BR"}).json()
    assert body["evidence"]["gaps"]
    assert all(g.startswith(MARKER) for g in body["evidence"]["gaps"])


@pytest.mark.parametrize("path", ["/api/coach/narrative", "/api/review/leaks/narrative"])
def test_the_no_credential_503_is_written_in_the_request_language(
    coach_client, monkeypatch, path,
):
    client, _db = coach_client
    monkeypatch.setattr(llm_config, "load", lambda: None)
    monkeypatch.setattr(llm_config, "load_coach", lambda: None)
    response = client.post(path, headers={"Accept-Language": "pt-BR"})
    assert response.status_code == 503
    assert response.json()["detail"] == (
        MARKER + "No Claude credential configured. Run 'sensei-top config --set-key'."
    )
    english = client.post(path)
    assert english.json()["detail"] == (
        "No Claude credential configured. Run 'sensei-top config --set-key'."
    )

