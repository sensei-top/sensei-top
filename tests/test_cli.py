"""Tests for the CLI's own loopback gate -- ``_require_loopback`` and its
wiring into ``cmd_serve`` (AGENTS.md non-negotiable #5: "Loopback binds
only ... this is why no part of this app needs an authentication story").

The CLI-level test never binds a real socket: it monkeypatches every
function ``cmd_serve`` would reach past ``_require_loopback`` (``_open``,
``_build_watcher_process``, ``_start_archetype_refresh``,
``_start_reference_refresh``, ``_start_corpus_refresh``, ``_start_backup``,
``uvicorn.run``) to raise if
called at all, so a regression that let a bad host slip past the gate would
fail loudly here rather than actually starting a server.
"""

from __future__ import annotations

import io
import os
import sqlite3
import sys
from pathlib import Path

import pytest
import uvicorn

from sensei_top import cli as cli_module

# --- _require_loopback, direct ---------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_require_loopback_accepts_loopback_addresses(host):
    cli_module._require_loopback(host)  # must not raise


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.com"])
def test_require_loopback_rejects_everything_else(host):
    with pytest.raises(SystemExit):
        cli_module._require_loopback(host)


def test_require_loopback_message_names_the_offending_host_and_the_reason():
    with pytest.raises(SystemExit) as exc_info:
        cli_module._require_loopback("0.0.0.0")
    message = str(exc_info.value)
    assert "0.0.0.0" in message
    assert "loopback" in message
    assert "AGENTS.md non-negotiable #5" in message


# --- cmd_serve, CLI level ---------------------------------------------------


def _refuse_to_start(name: str):
    def _raise(*args, **kwargs):
        raise AssertionError(f"{name} must not be called: _require_loopback should exit first")
    return _raise


def test_serve_with_a_non_loopback_host_exits_before_anything_starts(monkeypatch, tmp_path):
    for target in (
        "_open", "_build_watcher_process", "_start_archetype_refresh",
        "_start_reference_refresh", "_start_corpus_refresh", "_start_backup",
    ):
        monkeypatch.setattr(cli_module, target, _refuse_to_start(target))
    monkeypatch.setattr(uvicorn, "run", _refuse_to_start("uvicorn.run"))

    parser = cli_module.build_parser()
    args = parser.parse_args(
        ["--db", str(tmp_path / "t.db"), "serve", "--host", "0.0.0.0"]
    )

    with pytest.raises(SystemExit):
        cli_module.cmd_serve(args)


def test_serve_with_an_ipv6_loopback_host_passes_the_gate(monkeypatch, tmp_path):
    """``::1`` must clear ``_require_loopback`` -- this test only proves the
    gate lets it through (the next thing ``cmd_serve`` does, since the
    database doesn't exist yet and ``--watch`` wasn't passed, is its own
    unrelated ``sys.exit`` -- never a bound socket)."""
    parser = cli_module.build_parser()
    args = parser.parse_args(
        ["--db", str(tmp_path / "t.db"), "serve", "--host", "::1"]
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_module.cmd_serve(args)
    assert "No database at" in str(exc_info.value)  # never reached the loopback message


# ui-copy.md §5, the startup line when --no-corpus-refresh is given.
NO_CORPUS_REFRESH = "Not downloading tournament results (--no-corpus-refresh)"


class _Watcher:
    """A watcher that watches nothing: ``cmd_serve`` only starts, reads and
    stops it here."""

    mtgo_dir = None
    mtgo_deck_dir = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def _serve(monkeypatch, tmp_path, *flags: str) -> tuple[Path, list[Path]]:
    """``cmd_serve`` with every other background job off and no server
    bound; returns the database and each path the corpus refresh was
    started for."""
    db_path = tmp_path / "t.db"
    started: list[Path] = []
    monkeypatch.setattr(cli_module, "_start_corpus_refresh", started.append)
    monkeypatch.setattr(cli_module, "_build_watcher_process", lambda args, path: _Watcher())
    monkeypatch.setattr("sensei_top.api.create_app", lambda db_path, watcher=None: None)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: None)
    args = cli_module.build_parser().parse_args([
        "--db", str(db_path), "serve", "--no-archetype-refresh", "--no-reference-refresh",
        "--no-backup", *flags,
    ])
    cli_module.cmd_serve(args)
    return db_path, started


@pytest.fixture
def empty_log(tmp_path) -> Path:
    log = tmp_path / "Player.log"
    log.write_text("", encoding="utf-8")
    return log


@pytest.mark.parametrize("watch", [False, True], ids=["read-only", "watch"])
def test_serve_starts_the_corpus_refresh_with_or_without_watch(
    watch, monkeypatch, tmp_path, empty_log, capsys
):
    """D13: the refresh runs whether or not serve watches the logs, and its
    start prints nothing (ui-copy.md §5)."""
    flags = ["--watch", "--file", str(empty_log), "--no-mtgo"] if watch else []
    if not watch:
        from sensei_top.db import open_database

        open_database(tmp_path / "t.db").close()

    db_path, started = _serve(monkeypatch, tmp_path, *flags)

    assert started == [db_path]
    assert NO_CORPUS_REFRESH not in capsys.readouterr().out


def test_serve_with_no_corpus_refresh_says_so_and_starts_no_thread(
    monkeypatch, tmp_path, capsys
):
    from sensei_top.db import open_database

    open_database(tmp_path / "t.db").close()

    _, started = _serve(monkeypatch, tmp_path, "--no-corpus-refresh")

    assert started == []
    assert NO_CORPUS_REFRESH in capsys.readouterr().out.splitlines()


GROUPING_FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_grouping_deck.xml"
DECK_FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_deck_sample.dek"


@pytest.fixture
def no_user_config(monkeypatch, tmp_path):
    """Nothing configured: no environment override, and the config file looked
    up under a temp directory, never the real one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.delenv("MTGO_DECK_DIR", raising=False)


def _deck_store_rows(db_path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT label, source_file FROM raw_events WHERE source = 'mtgo_deck' "
            "ORDER BY source_file"
        ).fetchall()
    finally:
        conn.close()


def _run_ingest_mtgo(tmp_path, *extra: str) -> Path:
    db_path = tmp_path / "t.db"
    args = cli_module.build_parser().parse_args(["--db", str(db_path), "ingest-mtgo", *extra])
    cli_module.cmd_ingest_mtgo(args)
    return db_path


def test_ingest_mtgo_with_only_the_log_dir_stores_its_groupings(
    no_user_config, tmp_path, monkeypatch, capsys
):
    share = tmp_path / "share"
    share.mkdir()
    (share / "grouping one.xml").write_bytes(GROUPING_FIXTURE.read_bytes())
    monkeypatch.setenv("MTGO_LOG_DIR", str(share))

    db_path = _run_ingest_mtgo(tmp_path)

    assert [label for label, _ in _deck_store_rows(db_path)] == ["MtgoDeckGrouping"]
    assert "grouping *.xml" in capsys.readouterr().out


def test_ingest_mtgo_with_a_dir_flag_stores_its_groupings(no_user_config, tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    (share / "grouping one.xml").write_bytes(GROUPING_FIXTURE.read_bytes())

    db_path = _run_ingest_mtgo(tmp_path, "--dir", str(share))

    assert [label for label, _ in _deck_store_rows(db_path)] == ["MtgoDeckGrouping"]


def test_ingest_mtgo_with_both_folders_reads_both(no_user_config, tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    (share / "grouping one.xml").write_bytes(GROUPING_FIXTURE.read_bytes())
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "exported.dek").write_bytes(DECK_FIXTURE.read_bytes())

    db_path = _run_ingest_mtgo(tmp_path, "--dir", str(share), "--deck-dir", str(exports))

    assert sorted(label for label, _ in _deck_store_rows(db_path)) == [
        "MtgoDeckFile",
        "MtgoDeckGrouping",
    ]


def test_ingest_mtgo_does_not_read_one_folder_twice(no_user_config, tmp_path, monkeypatch):
    share = tmp_path / "share"
    share.mkdir()
    (share / "grouping one.xml").write_bytes(GROUPING_FIXTURE.read_bytes())
    seen: list[Path] = []
    real = cli_module.ingest_deck_dir

    def spy(conn, directory, **kwargs):
        seen.append(Path(directory))
        return real(conn, directory, **kwargs)

    monkeypatch.setattr(cli_module, "ingest_deck_dir", spy)
    _run_ingest_mtgo(tmp_path, "--dir", str(share), "--deck-dir", str(share))

    assert seen == [share]


def test_ingest_mtgo_with_nothing_configured_still_exits(no_user_config, tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        _run_ingest_mtgo(tmp_path)
    assert "No MTGO log directory configured" in str(exc_info.value)


def test_meta_format_is_normalised_and_an_unknown_one_is_refused(capsys):
    parser = cli_module.build_parser()
    args = parser.parse_args(["meta", "--format", "pauper", "--format", "PREMODERN"])
    assert args.formats == ["Pauper", "Premodern"]
    with pytest.raises(SystemExit):
        parser.parse_args(["meta", "--format", "Commander"])
    err = capsys.readouterr().err
    for name in ("Standard", "Pioneer", "Modern", "Pauper", "Legacy", "Vintage", "Premodern"):
        assert name in err


def _one_pauper_event(db_path: Path) -> None:
    """A stored Pauper event with no decks: Pauper is followed from here on."""
    from sensei_top.db import open_database
    from sensei_top.metagame.source import ParsedEvent, store_events

    conn = open_database(db_path)
    store_events(conn, [ParsedEvent(
        event_id="e-pauper", source="MTGO", name="League", event_date="2026-09-20",
        format="Pauper", tier="C", standings_rows=0, uri=None, blob_sha="sha-pauper",
        decks=[],
    )])
    conn.close()


def test_meta_fetches_the_followed_formats_by_hand(monkeypatch, tmp_path, capsys):
    """D8: the formats serve's loop follows (Standard, Modern and every
    stored one, here Pauper), plus --format, in FORMATS order, from every
    source; mtgo.com and TopDeck run by hand, on a clock. With every source
    fresh, each prints its fresh line, and with no decks stored the
    reclassification counts none."""
    from sensei_top.metagame import mtgo_site, source, topdeck
    from sensei_top.metagame.source import RefreshResult

    db_path = tmp_path / "t.db"
    _one_pauper_event(db_path)
    calls: dict[str, dict] = {}

    def recorder(name: str, age_seconds: float):
        def run(conn, **kw):
            calls[name] = kw
            return RefreshResult(status="fresh", age_seconds=age_seconds)
        return run

    monkeypatch.setattr(source, "refresh_metagame", recorder("fbettega", 2 * 3600))
    monkeypatch.setattr(mtgo_site, "refresh_mtgo_site", recorder("mtgo", 1.2 * 3600))
    monkeypatch.setattr(topdeck, "refresh_topdeck", recorder("topdeck", 20 * 3600))
    args = cli_module.build_parser().parse_args(
        ["--db", str(db_path), "meta", "--format", "legacy"]
    )

    cli_module.cmd_meta(args)

    followed = ("Standard", "Modern", "Pauper", "Legacy")
    assert {name: kw["formats"] for name, kw in calls.items()} == {
        "fbettega": followed, "mtgo": followed, "topdeck": followed,
    }
    assert all(kw["force"] is True for kw in calls.values())  # --format implies it
    for name in ("mtgo", "topdeck"):
        assert calls[name]["by_hand"] is True
        assert calls[name]["now"]().tzinfo is not None
    assert capsys.readouterr().out.splitlines() == [
        "cache: corpus is 2h old; nothing to do.",
        "mtgo: corpus is 1.2h old; nothing to do.",
        "topdeck: corpus is 20h old; nothing to do.",
        "0 decks classified, 0 unidentified",
    ]


@pytest.mark.parametrize("source_flag", ["topdeck", "all"])
def test_meta_names_a_missing_topdeck_key_only_when_asked_for_topdeck(
    source_flag, monkeypatch, tmp_path, capsys
):
    """lines.md §1.3: the no-key line is printed only with --source topdeck;
    otherwise an unconfigured TopDeck is silent. No key is configured here
    (conftest), so TopDeck's own refresh answers without a request."""
    from sensei_top.metagame import mtgo_site, source
    from sensei_top.metagame.source import RefreshResult

    db_path = tmp_path / "t.db"
    _one_pauper_event(db_path)
    monkeypatch.setattr(
        source, "refresh_metagame", lambda conn, **kw: RefreshResult(status="fresh")
    )
    monkeypatch.setattr(
        mtgo_site, "refresh_mtgo_site", lambda conn, **kw: RefreshResult(status="fresh")
    )
    args = cli_module.build_parser().parse_args(
        ["--db", str(db_path), "meta", "--source", source_flag]
    )

    cli_module.cmd_meta(args)

    topdeck_lines = [
        line for line in capsys.readouterr().out.splitlines() if line.startswith("topdeck:")
    ]
    if source_flag == "topdeck":
        assert topdeck_lines == [
            "topdeck: no API key configured — run 'sensei-top config --set-topdeck-key KEY'."
        ]
    else:
        assert topdeck_lines == []


def test_brief_for_a_deck_with_no_format_exits_before_building_a_prompt(tmp_path):
    from sensei_top.db import open_database

    db_path = tmp_path / "t.db"
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Draft', '{}', 't', 't')"
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, format) VALUES ('m1', 'e', 'd1', 1, 2, 'u', 'n', "
        "'2026-09-28T12:00:00', '2026-09-28T12:00:00', 'win', 2, 0, 'concede', NULL)"
    )
    conn.commit()
    conn.close()

    args = cli_module.build_parser().parse_args(
        ["--db", str(db_path), "brief", "--deck", "deck:d1", "--archetype", "x", "--prompt"]
    )
    with pytest.raises(SystemExit) as exc:
        cli_module.cmd_brief(args)
    assert exc.value.code == (
        "This deck's format is unknown, so there is no field to write a brief from. "
        "On MTGO, confirm the format on one of its matches, then run this again."
    )


# --- console encoding --------------------------------------------------------


def test_main_writes_utf8_to_a_console_whose_default_is_not(monkeypatch, tmp_path):
    """``mtgo-status`` with a directory that does not exist always prints an
    em dash. A stream opened with an ASCII default (Windows' ANSI code page,
    redirected) must still receive it as UTF-8."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(
        sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="backslashreplace")
    )

    cli_module.main(
        ["--db", str(tmp_path / "scratch.db"), "mtgo-status", "--dir", str(tmp_path / "absent")]
    )
    stream.flush()

    assert "—" in raw.getvalue().decode("utf-8")


# --- MTGO folder suggestion wiring (release plan 3, D8) ----------------------


@pytest.fixture
def discovered(monkeypatch, tmp_path) -> Path:
    """A folder discovery "finds", holding a game log newer than anything else."""
    folder = tmp_path / "found"
    folder.mkdir()
    log = folder / "Match_GameLog_20260101abc.dat"
    log.write_bytes(b"x")
    os.utime(log, (2_000_000_000, 2_000_000_000))
    monkeypatch.setattr(cli_module, "discover_log_folder", lambda: folder)
    return folder


def _case_a(folder: Path) -> list[str]:
    return [
        "MTGO writes its game logs to a folder that isn't configured yet. To read them, run:",
        f'  sensei-top config --set-mtgo-dir "{folder}"',
    ]


def _case_b(configured: Path, folder: Path) -> list[str]:
    return [
        f"MTGO's newest game logs are in a different folder from {configured}: "
        "it moves the folder when it updates. To read them, run:",
        f'  sensei-top config --set-mtgo-dir "{folder}"',
    ]


def _write_mtgo_dir_config(tmp_path: Path, directory: Path) -> None:
    config = tmp_path / "xdg" / "sensei-top" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'[mtgo]\ndir = "{directory.as_posix()}"\n')


def test_ingest_mtgo_with_nothing_configured_ends_with_case_a(
    no_user_config, tmp_path, discovered
):
    with pytest.raises(SystemExit) as exc_info:
        _run_ingest_mtgo(tmp_path)
    lines = str(exc_info.value).splitlines()
    assert "No MTGO log directory configured" in lines[0]
    assert lines[-2:] == _case_a(discovered)


def test_ingest_mtgo_with_the_env_var_behind_points_the_variable_before_ingesting(
    no_user_config, tmp_path, monkeypatch, discovered, capsys
):
    old = tmp_path / "old"
    old.mkdir()
    monkeypatch.setenv("MTGO_LOG_DIR", str(old))
    _run_ingest_mtgo(tmp_path)
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == [
        f"MTGO's newest game logs are in a different folder from {old}: it moves the folder "
        "when it updates. To read them, point MTGO_LOG_DIR at:",
        f"  {discovered}",
    ]
    assert lines[2].startswith(str(old))


def test_ingest_mtgo_with_a_missing_configured_folder_ends_with_case_b(
    no_user_config, tmp_path, discovered
):
    gone = tmp_path / "gone"
    _write_mtgo_dir_config(tmp_path, gone)
    with pytest.raises(SystemExit) as exc_info:
        _run_ingest_mtgo(tmp_path)
    lines = str(exc_info.value).splitlines()
    assert lines[0].startswith(f"Directory not found: {gone}")
    assert lines[-2:] == _case_b(gone, discovered)


def test_ingest_mtgo_with_a_dir_flag_prints_no_suggestion(
    no_user_config, tmp_path, discovered, capsys
):
    old = tmp_path / "old"
    old.mkdir()
    _run_ingest_mtgo(tmp_path, "--dir", str(old))
    assert "sensei-top config --set-mtgo-dir" not in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc_info:
        _run_ingest_mtgo(tmp_path, "--dir", str(tmp_path / "gone"))
    assert "set-mtgo-dir" not in str(exc_info.value)


def test_serve_with_nothing_configured_prints_case_a_after_the_not_reading_line(
    no_user_config, monkeypatch, tmp_path, empty_log, discovered, capsys
):
    _serve(monkeypatch, tmp_path, "--watch", "--file", str(empty_log))
    lines = capsys.readouterr().out.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("Not reading MTGO logs (no dir"))
    assert lines[at + 1 : at + 3] == _case_a(discovered)


def test_serve_with_a_missing_configured_folder_prints_case_b_after_its_line(
    no_user_config, monkeypatch, tmp_path, empty_log, discovered, capsys
):
    gone = tmp_path / "gone"
    _write_mtgo_dir_config(tmp_path, gone)
    _serve(monkeypatch, tmp_path, "--watch", "--file", str(empty_log))
    lines = capsys.readouterr().out.splitlines()
    at = next(i for i, line in enumerate(lines) if "the configured directory doesn't exist" in line)
    assert lines[at + 1 : at + 3] == _case_b(gone, discovered)
