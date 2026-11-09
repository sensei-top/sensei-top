"""``scrub.scrub_text``, ``diagnostics.known_names`` and the log-tail route.

The vectors in ``fixtures/scrub_vectors.json`` are written by hand from the
rules in ``scrub.py``'s docstring, with synthetic identifiers; the desktop
shell's scrubber will read the same file once it exists.
"""

import json
import time
import zipfile
from pathlib import Path

import pytest

from sensei_top import cli as cli_module
from sensei_top import diagnostics, scrub
from sensei_top.api.app import create_app
from sensei_top.config import config_path
from sensei_top.db import open_database
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
VECTORS = json.loads((Path(__file__).parent / "fixtures" / "scrub_vectors.json").read_text())[
    "vectors"
]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["name"] for v in VECTORS])
def test_vector(vector):
    assert scrub.scrub_text(vector["input"], vector["names"]) == vector["expected"]


def test_home_directory_is_written_as_tilde(tmp_path, monkeypatch):
    home = tmp_path / "zorblax-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert scrub.scrub_text(f"read {home}/x/y.log") == "read ~/x/y.log"


def test_legacy_mtgo_bytes_keep_undecodable_bytes():
    data = b"\xff keep [mtgo] card event handle Zorblax matches neither x\n"
    out = scrub.mask_legacy_mtgo(data)
    assert out.startswith(b"\xff keep")
    assert b"Zorblax" not in out


def _db_with_names(tmp_path) -> Path:
    db_path = tmp_path / "t.db"
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO matches (match_id, opponent_name, opponent_user_id) VALUES (?, ?, ?)",
        ("m1", "Quuxling#12345", "ZZZZ9999ZZZZ9999ZZZZ9999ZZ"),
    )
    conn.commit()
    conn.close()
    return db_path


def test_known_names_reads_config_and_database(tmp_path):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[mtgo]\nhandle = "Wibblesnoot"\n')
    names = diagnostics.known_names(_db_with_names(tmp_path))
    assert {"Wibblesnoot", "Quuxling#12345", "ZZZZ9999ZZZZ9999ZZZZ9999ZZ"} <= set(names)


def test_known_names_without_a_database(tmp_path):
    assert diagnostics.known_names(tmp_path / "none.db") == []


def test_known_names_holds_the_fixture_sign_in(tmp_path):
    # screenName and clientId of match_session.log's AuthenticateResponse
    # (entry 3, read with fixture_peek.py).
    db_path = tmp_path / "t.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    conn.close()
    names = diagnostics.known_names(db_path)
    assert "SelfPlayer" in names
    assert "SELFCLIENTID0001" in names


def test_thousands_of_names_scrub_a_large_text_quickly():
    names = [f"Player{i}#{10000 + i}" for i in range(6000)]
    text = "\n".join(f"line {i} Player{i % 6000}#{10000 + i % 6000} played" for i in range(20000))
    start = time.monotonic()
    out = scrub.scrub_text(text, names)
    assert time.monotonic() - start < 2
    assert "Player" not in out
    assert "<name> played" in out


def test_expand_drops_an_arena_id():
    words, others = scrub._expand(["ZZZZ9999ZZZZ9999ZZZZ9999ZZ", "Wibblesnoot"])
    assert words == {"wibblesnoot"}
    assert others == []


def _write_logs(db_path: Path) -> None:
    folder = db_path.parent / "logs"
    folder.mkdir()
    (folder / "sensei-top.log").write_text("new1 Quuxling#12345\nnew2 mail me@example.invalid\n")
    (folder / "sensei-top.log.1").write_text("old1\nold2\n")


def test_log_tail_runs_across_rotation_and_scrubs(tmp_path, make_client):
    db_path = _db_with_names(tmp_path)
    _write_logs(db_path)
    with make_client(create_app(db_path)) as c:
        body = c.get("/api/diagnostics/log-tail", params={"lines": 3}).text
        assert body == "old2\nnew1 <name>\nnew2 mail <email>"
        everything = c.get("/api/diagnostics/log-tail").text
        assert everything.splitlines()[0] == "old1"
        assert c.get("/api/diagnostics/log-tail", params={"lines": 0}).status_code == 422


def test_log_tail_without_a_log_is_empty(tmp_path, make_client):
    db_path = _db_with_names(tmp_path)
    with make_client(create_app(db_path)) as c:
        res = c.get("/api/diagnostics/log-tail")
        assert res.status_code == 200
        assert res.text == ""


def test_the_bundle_scrubs_logs_and_keeps_its_shape(tmp_path):
    db_path = _db_with_names(tmp_path)
    _write_logs(db_path)
    out = tmp_path / "d.zip"
    cli_module.main(["--db", str(db_path), "diagnostics", "--out", str(out)])
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        log = zf.read("logs/sensei-top.log").decode()
    assert {"doctor.json", "row_counts.json", "logs/sensei-top.log"} <= names
    assert "Quuxling" not in log
    assert "example.invalid" not in log
