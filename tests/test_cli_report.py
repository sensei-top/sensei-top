"""Tests for ``sensei-top report`` over matches with no deck.

An MTGO match has no ``deck_id`` until the user confirms a pick, and an
unpicked one keeps none after it, so ``COALESCE(name, substr(deck_id, 1, 8))``
is ``NULL`` for such a match: the report labels it ``(no deck)`` rather than
crashing on a ``NULL`` label.

The expectations are the fixture's own two games, as
``test_projector_mtgo.py::test_game_one_facts``/``test_game_two_facts`` read
them: Player1 on the play in game 1 and on the draw in game 2, winning both,
in 9 and 8 player-turns.
"""

from __future__ import annotations

from pathlib import Path

from sensei_top import cli as cli_module
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.mtgo import ingest_mtgo_dir

FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_match_session.log"


def _report(monkeypatch, tmp_path: Path, capsys) -> str:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("MTGO_HANDLE", "Player1")

    share = tmp_path / "share"
    share.mkdir()
    (share / "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat").write_bytes(
        FIXTURE.read_bytes()
    )
    db_path = tmp_path / "t.db"
    conn = open_database(db_path)
    ingest_mtgo_dir(conn, share)
    project(conn)
    conn.close()
    capsys.readouterr()

    args = cli_module.build_parser().parse_args(["--db", str(db_path), "report"])
    args.func(args)  # must not raise
    return capsys.readouterr().out


def test_play_draw_labels_a_match_with_no_deck(monkeypatch, tmp_path, capsys):
    out = _report(monkeypatch, tmp_path, capsys)
    assert f"{'(no deck)':<22} {'on the play':<12} 1/1 games 100.0%" in out
    assert f"{'(no deck)':<22} {'on the draw':<12} 1/1 games 100.0%" in out


def test_game_length_labels_a_match_with_no_deck(monkeypatch, tmp_path, capsys):
    out = _report(monkeypatch, tmp_path, capsys)
    assert f"{'(no deck)':<22} turn   8   1/1 games 100.0%" in out
    assert f"{'(no deck)':<22} turn   9   1/1 games 100.0%" in out
    assert f"{'(no deck)':<22} avg length 8.5 turns (2 games)" in out
