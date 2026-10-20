"""``scripts/demo_db.py``: the screenshot database.

Ground truth is the fixtures, read with ``fixture_peek.py`` and
``scripts/mtgo_probe.py`` (AGENTS.md non-negotiable #8), never this script's
output. ``match_session.log``'s ``AuthenticateResponse`` names the user as
``SelfPlayer`` with client id ``SELFCLIENTID0001``; its two completed best-of-
three matches are against ``OppPlayerOne`` (``AAAAAAAAAAAAAAA1``, match
``fd5624a4-...``) and ``OppPlayerTwo`` (``BBBBBBBBBBBBBBB2``, match
``fa7a4d16-...``), both in ``Traditional_Ladder``, the ranked ladder.
``mtgo_match_session.log`` is one match between ``Player1`` and
``Player2000``. The tests read the same names back through SQL and check
that the SQL found what the fixture holds.

The ladder allows advice (``table/queues.py``), so both are ``--live``
candidates; no fixture holds an event's match, so the refusal test renames
the queue in the stored payloads to an event id read off a real database.

The pseudonym shape is ``<given name>#<5 digits>``, and the user is
``Deshi``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sqlite3
import subprocess
import sys
from base64 import b64decode
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.reader.mtgo import read_game_log, store_game_log
from sensei_top.table.queues import ADVICE_QUEUES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "demo_db.py"
FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
MTGO_FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_match_session.log"

LADDER_MATCH = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
NARRATIVE_MATCH = "fd5624a4-d970-40eb-80aa-fba9d2ce17b3"
FIXTURE_NAMES = {
    "SelfPlayer",
    "SELFCLIENTID0001",
    "OppPlayerOne",
    "OppPlayerTwo",
    "AAAAAAAAAAAAAAA1",
    "BBBBBBBBBBBBBBB2",
    "Player1",
    "Player2000",
}
PSEUDONYM = re.compile(r"\b[A-Z][a-z]+#\d{5}\b")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


def _identifiers(conn: sqlite3.Connection) -> set[str]:
    """What the user and their opponents are called in the source, read
    through SQL: the self identity from the login response, the opponents
    from the projected matches."""
    found: set[str] = set()
    for name, client_id in conn.execute(
        "SELECT json_extract(payload, '$.authenticateResponse.screenName'), "
        "json_extract(payload, '$.authenticateResponse.clientId') "
        "FROM raw_events WHERE label = 'AuthenticateResponse' AND json_valid(payload)"
    ):
        found |= {name, client_id}
    for name, user_id in conn.execute("SELECT opponent_name, opponent_user_id FROM matches"):
        found |= {name, user_id}
    found.discard(None)
    return found


@pytest.fixture
def source_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, set[str]]:
    """Both fixtures ingested and projected, with the MTGO user's handle set
    the way the config would set it, and one authored narrative naming an
    opponent. Closed and checkpointed before the script sees it."""
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    path = tmp_path / "source.db"
    conn = open_database(path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    store_game_log(conn, read_game_log(MTGO_FIXTURE))
    project(conn)
    conn.execute(
        "INSERT INTO match_narrative (match_id, prose, prompt, model, generated_at, context_hash) "
        "VALUES (?, ?, ?, 'demo-model', '2026-10-13T00:00:00Z', 'hash')",
        (
            NARRATIVE_MATCH,
            "OppPlayerOne kept seven and SelfPlayer mulliganed.",
            "Review the match against oppplayerone.",
        ),
    )
    names = _identifiers(conn) | {"Player1"}
    conn.close()
    assert names >= FIXTURE_NAMES, "the SQL read missed a name the fixtures hold"
    return path, names


def _texts(path: Path) -> list[str]:
    """Every text value in every table, MTGO payloads base64-decoded too."""
    conn = sqlite3.connect(path)
    texts: list[str] = []
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            for column in [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]:
                texts += [
                    value
                    for (value,) in conn.execute(f'SELECT "{column}" FROM "{table}"')
                    if isinstance(value, str)
                ]
        for (payload,) in conn.execute(
            "SELECT payload FROM raw_events WHERE source IN ('mtgo', 'mtgo_deck')"
        ):
            texts.append(b64decode(payload).decode("utf-8", errors="replace"))
    finally:
        conn.close()
    return texts


def _count(path: Path, sql: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def test_every_identifier_is_rewritten(source_db, tmp_path):
    source, names = source_db
    target = tmp_path / "demo.db"
    before = _sha256(source)

    home = str(Path.home()).lower()
    if REPO_ROOT.is_relative_to(Path.home()):
        # ingest_state keeps the fixtures' absolute paths, so the home
        # directory is in the source for the copy to lose.
        assert any(home in text.lower() for text in _texts(source))

    result = _run("--from", str(source), "--to", str(target))

    assert result.returncode == 0, result.stderr
    assert _sha256(source) == before
    lowered = [text.lower() for text in _texts(target)]
    for name in names:
        hits = sum(name.lower() in text for text in lowered)
        assert hits == 0, f"a fixture identifier survives in {hits} values"
    assert not any(home in text for text in lowered)
    for output in (result.stdout, result.stderr):
        assert not any(name.lower() in output.lower() for name in names)
        assert home not in output.lower()

    count = "SELECT COUNT(*) FROM matches"
    assert _count(target, count) == _count(source, count) == 3
    mtgo = "SELECT COUNT(*) FROM matches WHERE source = 'mtgo'"
    assert _count(target, mtgo) == _count(source, mtgo) == 1


def test_pseudonyms_follow_d6(source_db, tmp_path):
    source, _names = source_db
    target = tmp_path / "demo.db"
    assert _run("--from", str(source), "--to", str(target)).returncode == 0

    conn = sqlite3.connect(target)
    try:
        opponents = {
            row[0]
            for row in conn.execute("SELECT opponent_name FROM matches WHERE source = 'arena'")
        }
        prose, prompt = conn.execute(
            "SELECT prose, prompt FROM match_narrative WHERE match_id = ?", (NARRATIVE_MATCH,)
        ).fetchone()
        (screen_name,) = conn.execute(
            "SELECT json_extract(payload, '$.authenticateResponse.screenName') "
            "FROM raw_events WHERE label = 'AuthenticateResponse'"
        ).fetchone()
    finally:
        conn.close()

    assert len(opponents) == 2
    assert all(PSEUDONYM.fullmatch(name) for name in opponents)
    # The planted narrative names the same opponent its match does.
    (opponent,) = [name for name in opponents if prose.startswith(name)]
    assert opponent in prompt
    assert "Deshi mulliganed" in prose
    assert screen_name.startswith("Deshi")


def _opponents(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT opponent_name FROM matches ORDER BY match_id")
        return [row[0] for row in rows]
    finally:
        conn.close()


def test_the_seed_decides_the_pseudonyms(source_db, tmp_path):
    source, _names = source_db
    first, second, other = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "c.db"
    assert _run("--from", str(source), "--to", str(first)).returncode == 0
    assert _run("--from", str(source), "--to", str(second)).returncode == 0
    assert _run("--from", str(source), "--to", str(other), "--seed", "1").returncode == 0

    names = _opponents(first)
    assert len(names) == 3
    assert all(PSEUDONYM.fullmatch(name) for name in names)
    assert _opponents(second) == names
    assert _opponents(other) != names


def test_a_match_the_source_never_projected_is_rewritten(tmp_path, monkeypatch):
    """The source's ``matches`` can lag its raw events (a match in
    progress, or one inside the watcher's projection gate). Here the Arena
    log is ingested after the last projection, so ``matches`` holds only the
    MTGO match while ``raw_events`` holds both Arena opponents."""
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    source = tmp_path / "source.db"
    conn = open_database(source)
    store_game_log(conn, read_game_log(MTGO_FIXTURE))
    project(conn)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    assert conn.execute("SELECT COUNT(*) FROM matches WHERE source = 'arena'").fetchone()[0] == 0
    conn.close()
    target = tmp_path / "demo.db"

    result = _run("--from", str(source), "--to", str(target))

    assert result.returncode == 0, result.stderr
    lowered = [text.lower() for text in _texts(target)]
    for name in ("OppPlayerOne", "OppPlayerTwo", "AAAAAAAAAAAAAAA1", "BBBBBBBBBBBBBBB2"):
        assert not any(name.lower() in text for text in lowered)


def test_an_existing_target_is_refused(source_db, tmp_path):
    source, _names = source_db
    target = tmp_path / "exists.db"
    target.write_bytes(b"not a database")

    result = _run("--from", str(source), "--to", str(target))

    assert result.returncode == 3
    assert target.read_bytes() == b"not a database"


def test_the_source_as_target_is_refused(source_db):
    source, _names = source_db
    before = _sha256(source)

    result = _run("--from", str(source), "--to", str(source))

    assert result.returncode == 3
    assert _sha256(source) == before


def test_a_tracked_place_in_the_repository_is_refused(source_db):
    source, _names = source_db
    # Not *.db: .gitignore covers every *.db anywhere, so this name is one
    # git would track.
    target = REPO_ROOT / "docs" / "demo-refusal-check.sqlite"
    assert not target.exists()

    result = _run("--from", str(source), "--to", str(target))

    assert result.returncode == 3
    assert not target.exists()


def test_data_is_refused_before_anything_is_written(tmp_path):
    """In process, through the path check alone, so no run of the script
    is ever pointed at ``data/``."""
    module = _load_script()
    source = tmp_path / "source.db"
    source.write_bytes(b"")
    with pytest.raises(module.RefusedError, match="data/"):
        module.check_paths(source, REPO_ROOT / "data" / "demo-refusal-check.db")


def test_live_refuses_an_event_match(source_db, tmp_path):
    source, _names = source_db
    conn = open_database(source)
    conn.execute(
        "UPDATE raw_events SET payload = replace(payload, "
        "'\"Traditional_Ladder\"', '\"Traditional_Cons_Event_2026\"')"
    )
    conn.commit()
    project(conn)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    target = tmp_path / "demo.db"

    result = _run("--from", str(source), "--to", str(target), "--live", LADDER_MATCH)

    assert result.returncode == 3
    assert "event" in result.stderr
    assert not target.exists()


def test_live_refuses_an_unknown_match(source_db, tmp_path):
    source, _names = source_db
    target = tmp_path / "demo.db"

    result = _run("--from", str(source), "--to", str(target), "--live", "no-such-match")

    assert result.returncode == 3
    assert not target.exists()


def test_live_cut_needs_live(source_db, tmp_path):
    source, _names = source_db
    target = tmp_path / "demo.db"

    result = _run("--from", str(source), "--to", str(target), "--live-cut", "5")

    assert result.returncode == 3
    assert not target.exists()


def test_live_leaves_one_match_in_progress(source_db, tmp_path, make_client):
    source, _names = source_db
    conn = sqlite3.connect(source)
    try:
        placeholders = ",".join("?" * len(ADVICE_QUEUES))
        candidates = conn.execute(
            "SELECT m.match_id FROM matches m WHERE m.source = 'arena' "
            f"AND m.event_id IN ({placeholders}) AND m.result != 'incomplete' "
            "AND (SELECT COUNT(*) FROM games g WHERE g.match_id = m.match_id) >= 2",
            sorted(ADVICE_QUEUES),
        ).fetchall()
    finally:
        conn.close()
    if not candidates:
        pytest.skip(
            "match_session.log has no completed best-of-three Arena match in a queue that "
            "allows advice; "
            "--live is checked against a real database copy in phase 3"
        )
    from sensei_top.api.app import create_app

    match_id = candidates[0][0]
    target = tmp_path / "demo.db"
    result = _run("--from", str(source), "--to", str(target), "--live", match_id)
    assert result.returncode == 0, result.stderr

    incomplete = "SELECT COUNT(*) FROM matches WHERE source = 'arena' AND result = 'incomplete'"
    assert _count(target, incomplete) == 1
    conn = sqlite3.connect(target)
    try:
        assert [row[0] for row in conn.execute("SELECT match_id FROM v_current_match")] == [
            match_id
        ]
    finally:
        conn.close()
    assert make_client(create_app(target)).get("/api/current-match").json() is not None


def _load_script():
    spec = importlib.util.spec_from_file_location("demo_db", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_db"] = module
    spec.loader.exec_module(module)
    return module


def test_a_term_left_behind_deletes_the_copy(source_db, tmp_path, monkeypatch, capsys):
    """Fail closed: a rewrite that misses a term must cost the copy, and the
    message must carry categories, never the term."""
    source, names = source_db
    module = _load_script()
    monkeypatch.setattr(module.Matcher, "rewrite", lambda self, text: text)
    target = tmp_path / "demo.db"

    code = module.main(["--from", str(source), "--to", str(target)])

    assert code == 2
    assert not target.exists()
    out = capsys.readouterr()
    for output in (out.out, out.err):
        assert not any(name.lower() in output.lower() for name in names)
    assert "opponent" in out.err
