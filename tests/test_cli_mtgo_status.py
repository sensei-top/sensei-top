"""Tests for ``sensei-top mtgo-status`` -- the CLI diagnostic that makes the
"no handle configured" / "stale directory" failure modes legible, where
otherwise they show only as zero MTGO matches rows.

Every test isolates ``XDG_CONFIG_HOME`` and clears ``MTGO_HANDLE`` so this
suite never reads or depends on a real ``~/.config/sensei-top/config.toml``.
Most pass ``--dir`` explicitly; the ones exercising directory *resolution*
itself don't, but nothing on the machine can leak in regardless — there is
no autodetection to fall back to, and ``conftest.py``'s autouse fixture
already clears ``MTGO_LOG_DIR`` and isolates ``XDG_CONFIG_HOME`` for every
test in the suite.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from sensei_top import cli as cli_module
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.mtgo import ingest_mtgo_dir

FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_match_session.log"


def _isolate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def _run_status(db_path: Path, mtgo_dir: Path | None) -> None:
    """Build args the way argparse would and call the subcommand directly,
    same pattern ``test_llm.py`` uses for ``cmd_config``. ``mtgo_dir=None``
    omits ``--dir`` entirely, exercising the same config/env resolution a
    real invocation with no flag would go through."""
    parser = cli_module.build_parser()
    argv = ["--db", str(db_path), "mtgo-status"]
    if mtgo_dir is not None:
        argv += ["--dir", str(mtgo_dir)]
    args = parser.parse_args(argv)
    args.func(args)


def test_reports_cleanly_with_nothing_configured_and_an_empty_directory(
    monkeypatch, tmp_path, capsys
):
    _isolate(monkeypatch, tmp_path)
    empty_dir = tmp_path / "share"
    empty_dir.mkdir()

    _run_status(tmp_path / "t.db", empty_dir)

    out = capsys.readouterr().out
    assert "Handle:    not configured" in out
    assert "0 Match_GameLog_*.dat" in out
    assert "0 raw_events" in out
    assert "0 matches" in out
    assert "no MTGO handle configured" in out  # the verdict line names the first blocker


def test_does_not_raise_on_a_directory_that_does_not_exist(monkeypatch, tmp_path, capsys):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    missing_dir = tmp_path / "does-not-exist"

    _run_status(tmp_path / "t.db", missing_dir)  # must not raise

    out = capsys.readouterr().out
    assert "does not exist" in out
    assert "from --dir" in out
    assert "(from --dir) not found" in out  # the verdict line, not just "Directory:"


def test_reports_the_configured_handle_files_and_row_counts_after_ingest(
    monkeypatch, tmp_path, capsys
):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("MTGO_HANDLE", "Player1")

    share = tmp_path / "share"
    share.mkdir()
    (share / "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat").write_bytes(
        FIXTURE.read_bytes()
    )

    db_path = tmp_path / "t.db"
    conn = open_database(db_path)
    stats = ingest_mtgo_dir(conn, share)
    conn.close()
    assert stats.rows_inserted == 1  # sanity: the setup actually stored a row

    _run_status(db_path, share)

    out = capsys.readouterr().out
    assert "Handle:    Player1 (from $MTGO_HANDLE)" in out
    assert "1 Match_GameLog_*.dat" in out
    assert "1 raw_events" in out
    assert "0 matches" in out  # ingested but not yet projected


def test_reports_a_projected_match_once_project_has_run(monkeypatch, tmp_path, capsys):
    """With a handle configured, the two
    MTGO raw_events rows already on disk project into a real match, and
    mtgo-status reports that count rather than the fail-soft zero pinned by
    test_projector_mtgo.py::test_no_handle_configured_projects_nothing_but_warns_once.
    """
    _isolate(monkeypatch, tmp_path)
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

    _run_status(db_path, share)

    out = capsys.readouterr().out
    assert "1 matches" in out


def test_reports_directory_not_configured(monkeypatch, tmp_path, capsys):
    """No --dir, no $MTGO_LOG_DIR, and no config.toml [mtgo] dir: mtgo-status
    must say so plainly -- never a resolved-looking path -- and point at the
    fix, the same shape as the handle-not-configured case just above it."""
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("MTGO_HANDLE", "Player1")  # isolate the directory axis

    _run_status(tmp_path / "t.db", None)

    out = capsys.readouterr().out
    assert "Directory: not configured" in out
    assert "--set-mtgo-dir" in out
    assert "no MTGO log directory configured" in out  # the verdict line itself


def test_reports_a_configured_directory_that_does_not_exist_via_env(monkeypatch, tmp_path, capsys):
    """$MTGO_LOG_DIR pointing at a path that isn't there yet (the share not
    mounted yet, not a --dir typo) must still name its source, not just
    print a bare 'does not exist' the way an unconfigured --dir would."""
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("MTGO_HANDLE", "Player1")  # isolate the directory axis
    missing_dir = tmp_path / "not-mounted-yet"
    monkeypatch.setenv("MTGO_LOG_DIR", str(missing_dir))

    _run_status(tmp_path / "t.db", None)

    out = capsys.readouterr().out
    assert "does not exist" in out
    assert "from $MTGO_LOG_DIR" in out
    assert "(from $MTGO_LOG_DIR) not found" in out  # the verdict line, not just "Directory:"


def test_resolve_watch_mtgo_dir_warns_once_on_a_configured_but_missing_directory(
    monkeypatch, tmp_path, caplog
):
    """``_resolve_watch_mtgo_dir`` is ``serve --watch``'s and ``ingest --watch``'s
    fail-soft path (unlike ``_resolve_mtgo_dir``, which ``sys.exit``s on the same input): a
    directory named by ``$MTGO_LOG_DIR`` or config.toml that isn't there yet
    must not silently look identical to "nothing configured" -- this warning
    is the only signal a watch session gets that it's the former, not the
    latter. No existing suite calls ``_resolve_watch_mtgo_dir`` directly, so
    this lives here alongside its sibling ``_resolve_mtgo_dir``'s coverage.
    """
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    missing_dir = tmp_path / "not-mounted-yet"
    monkeypatch.setenv("MTGO_LOG_DIR", str(missing_dir))
    args = SimpleNamespace(no_mtgo=False, mtgo_dir=None)

    with caplog.at_level(logging.WARNING):
        result = cli_module._resolve_watch_mtgo_dir(args)

    assert result is None
    assert len(caplog.messages) == 1
    assert str(missing_dir) in caplog.messages[0]
    assert "$MTGO_LOG_DIR" in caplog.messages[0]


# --- _resolve_mtgo_dir: ingest-mtgo's/mtgo-status's own sys.exit messages ---


def test_resolve_mtgo_dir_exits_naming_the_fix_when_nothing_is_configured(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        cli_module._resolve_mtgo_dir(None)

    assert "--set-mtgo-dir" in excinfo.value.code


def test_resolve_mtgo_dir_exits_naming_the_env_source_for_a_missing_directory(
    monkeypatch, tmp_path
):
    _isolate(monkeypatch, tmp_path)
    missing_dir = tmp_path / "not-mounted-yet"
    monkeypatch.setenv("MTGO_LOG_DIR", str(missing_dir))

    with pytest.raises(SystemExit) as excinfo:
        cli_module._resolve_mtgo_dir(None)

    assert excinfo.value.code == f"Directory not found: {missing_dir} (from $MTGO_LOG_DIR)"


def test_resolve_mtgo_dir_exits_with_no_source_suffix_for_an_explicit_missing_argument(
    monkeypatch, tmp_path
):
    _isolate(monkeypatch, tmp_path)
    missing_dir = tmp_path / "does-not-exist"

    with pytest.raises(SystemExit) as excinfo:
        cli_module._resolve_mtgo_dir(str(missing_dir))

    assert excinfo.value.code == f"Directory not found: {missing_dir}"
    assert "(from" not in excinfo.value.code
