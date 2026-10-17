"""Tests for the CLI's own loopback gate -- ``_require_loopback`` and its
wiring into ``cmd_serve`` (AGENTS.md non-negotiable #5: "Loopback binds
only ... this is why no part of this app needs an authentication story").

The CLI-level test never binds a real socket: it monkeypatches every
function ``cmd_serve`` would reach past ``_require_loopback`` (``_open``,
``_build_watcher_process``, ``_start_archetype_refresh``,
``_start_reference_refresh``, ``_start_corpus_refresh``, ``_start_backup``,
``_bind_listening_socket``, ``uvicorn.Server.run``) to raise if
called at all, so a regression that let a bad host slip past the gate would
fail loudly here rather than actually starting a server.
"""

from __future__ import annotations

import io
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
from pathlib import Path

import pytest
import uvicorn

# The serve-shutdown tests' process helpers (read /proc; Linux only).
from test_live import descendants, running

from sensei_top import cli as cli_module
from sensei_top.db import open_database

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
        "_bind_listening_socket",
    ):
        monkeypatch.setattr(cli_module, target, _refuse_to_start(target))
    monkeypatch.setattr(uvicorn.Server, "run", _refuse_to_start("uvicorn.Server.run"))

    # The database exists, so only the gate stands between this host and the
    # tripwires above; no other early exit can stand in for it.
    open_database(tmp_path / "t.db").close()
    parser = cli_module.build_parser()
    args = parser.parse_args(
        ["--db", str(tmp_path / "t.db"), "serve", "--host", "0.0.0.0"]
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_module.cmd_serve(args)
    assert str(exc_info.value).startswith("Refusing to bind 0.0.0.0")


def test_serve_with_an_ipv6_loopback_host_passes_the_gate(monkeypatch, tmp_path):
    """``::1`` must clear ``_require_loopback`` -- this test only proves the
    gate lets it through (the next thing ``cmd_serve`` does, since the
    database doesn't exist yet and ``--watch`` wasn't passed, is its own
    unrelated ``sys.exit`` -- never a bound socket)."""
    parser = cli_module.build_parser()
    monkeypatch.setattr(cli_module, "_bind_listening_socket", _refuse_to_start("bind"))
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


class _FakeSocket:
    """Stands in for the bound socket, so no test leaves a real one open."""

    def getsockname(self):
        return ("127.0.0.1", 1)


def _serve(monkeypatch, tmp_path, *flags: str) -> tuple[Path, list[Path]]:
    """``cmd_serve`` with every other background job off and no server
    bound; returns the database and each path the corpus refresh was
    started for."""
    db_path = tmp_path / "t.db"
    started: list[Path] = []
    monkeypatch.setattr(cli_module, "_start_corpus_refresh", started.append)
    monkeypatch.setattr(cli_module, "_build_watcher_process", lambda args, path: _Watcher())
    monkeypatch.setattr("sensei_top.api.create_app", lambda db_path, watcher=None: None)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets=None: None)
    monkeypatch.setattr(cli_module, "_bind_listening_socket", lambda host, port: _FakeSocket())
    args = cli_module.build_parser().parse_args([
        "--db", str(db_path), "serve", "--port", "0", "--no-archetype-refresh",
        "--no-reference-refresh", "--no-backup", *flags,
    ])
    cli_module.cmd_serve(args)
    return db_path, started


def test_serve_watch_with_no_arena_log_starts_and_live_says_null(
    monkeypatch, tmp_path, capsys, make_client
):
    """D10: nothing found anywhere is not a reason to exit, and /api/live
    reports arena_log as null. An explicit --file that is missing still exits."""
    from sensei_top.api import create_app

    monkeypatch.setattr("sensei_top.live.resolve_arena_log", lambda: None)
    monkeypatch.setattr("sensei_top.api.routes.meta.resolve_arena_log", lambda: None)
    built: list[Path | None] = []

    def build(args, path):
        built.append(path)
        return _Watcher()

    db_path, _ = _serve(monkeypatch, tmp_path, "--watch")
    monkeypatch.setattr(cli_module, "_build_watcher_process", build)
    cli_module.cmd_serve(cli_module.build_parser().parse_args([
        "--db", str(db_path), "serve", "--port", "0", "--no-archetype-refresh",
        "--no-reference-refresh", "--no-backup", "--no-corpus-refresh", "--watch",
    ]))
    assert built == [None]
    assert "No Arena log yet" in capsys.readouterr().out

    class Waiting(_Watcher):
        log_path = None

        def is_alive(self) -> bool:
            return True

    with make_client(create_app(db_path, watcher=Waiting())) as client:
        body = client.get("/api/live").json()
    assert body["watching"] is True
    assert body["arena_log"] is None

    with pytest.raises(SystemExit):
        _serve(monkeypatch, tmp_path, "--watch", "--file", str(tmp_path / "missing.log"))


def _empty(tmp_path) -> Path:
    log = tmp_path / "Player.log"
    log.write_text("", encoding="utf-8")
    return log


def test_live_writes_the_home_directory_as_a_tilde(monkeypatch, tmp_path, make_client):
    from sensei_top.api import create_app

    db_path, _ = _serve(monkeypatch, tmp_path, "--watch", "--file", str(_empty(tmp_path)))
    home = Path.home()

    class Reading(_Watcher):
        def is_alive(self) -> bool:
            return True

        log_path = home / "somewhere" / "Player.log"

    class Waiting(Reading):
        log_path = None

    with make_client(create_app(db_path, watcher=Reading())) as client:
        assert client.get("/api/live").json()["arena_log"] == "~/somewhere/Player.log"

    monkeypatch.setattr(
        "sensei_top.api.routes.meta.resolve_arena_log",
        lambda: home / "found" / "Player.log",
    )
    with make_client(create_app(db_path, watcher=Waiting())) as client:
        assert client.get("/api/live").json()["arena_log"] == "~/found/Player.log"


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


# --- serve's handshake with a parent process (the desktop shell) -------------


def _handshake_serve(tmp_path, *flags: str) -> subprocess.Popen:
    """``serve`` as its own process on a temp database, every download off,
    stdin and stdout piped, so a test plays the part of the shell."""
    db_path = tmp_path / "handshake.db"
    open_database(db_path).close()
    log = tmp_path / "Player.log"
    log.write_text("", newline="")
    return subprocess.Popen(
        [
            sys.executable, "-m", "sensei_top.cli", "--db", str(db_path), "serve",
            "--file", str(log), "--port", "0", "--no-mtgo", "--no-backup",
            "--no-corpus-refresh", "--no-archetype-refresh", "--no-reference-refresh",
            *flags,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _read_ready_line(serve: subprocess.Popen) -> dict:
    """The first stdout line that is JSON; the prose lines before it are not
    a contract. A silent serve is killed at the deadline, which ends the
    blocking read."""
    timer = threading.Timer(60, serve.kill)
    timer.start()
    try:
        for line in serve.stdout:
            if line.startswith("{"):
                return json.loads(line)
    finally:
        timer.cancel()
    pytest.fail("serve printed no ready line")


def test_serve_with_port_zero_prints_one_ready_line_and_answers_on_that_port(tmp_path):
    serve = _handshake_serve(tmp_path, "--ready-line")
    try:
        ready = _read_ready_line(serve)
        assert list(ready) == ["listening"]
        port = ready["listening"]
        assert isinstance(port, int) and port > 0
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as reply:
            assert reply.status == 200
    finally:
        serve.kill()
        serve.wait()
        serve.stdin.close()
        serve.stdout.close()


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc")
def test_closing_stdin_under_exit_on_stdin_close_ends_serve_and_its_watcher(tmp_path):
    serve = _handshake_serve(tmp_path, "--watch", "--ready-line", "--exit-on-stdin-close")
    watchers: list[int] = []
    try:
        _read_ready_line(serve)
        watchers = descendants(serve.pid)
        assert watchers, "serve --watch started no watcher"

        serve.stdin.close()
        serve.wait(timeout=10)

        deadline = time.monotonic() + 10
        while any(running(pid) for pid in watchers) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert serve.returncode == 0
        assert [pid for pid in watchers if running(pid)] == []
    finally:
        if serve.poll() is None:
            serve.kill()
            serve.wait()
        for pid in watchers:
            if running(pid):
                os.kill(pid, signal.SIGKILL)
        serve.stdout.close()


def test_exit_on_stdin_close_leaves_the_watcher_free_to_ingest(tmp_path):
    # On Windows a pending stdin read once stalled the watcher child at startup.
    fixture = Path(__file__).parent / "fixtures" / "match_session.log"
    serve = _handshake_serve(
        tmp_path, "--watch", "--ready-line", "--exit-on-stdin-close", "--file", str(fixture)
    )
    try:
        port = _read_ready_line(serve)["listening"]
        deadline = time.monotonic() + 30
        body = ""
        ingested = False
        while time.monotonic() < deadline and not ingested:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/live", timeout=5
                ) as reply:
                    body = reply.read().decode()
                ingested = json.loads(body)["events"] > 0
            except OSError:
                pass
            if not ingested:
                time.sleep(0.25)
        assert ingested, f"watcher ingested nothing in 30 s; last /api/live: {body}"

        serve.stdin.close()
        assert serve.wait(timeout=10) == 0
    finally:
        if serve.poll() is None:
            serve.kill()
            serve.wait()
        serve.stdout.close()


@pytest.mark.skipif(sys.platform != "linux", reason="signals a process")
def test_sigint_with_stdin_held_open_ends_serve_cleanly(tmp_path):
    serve = _handshake_serve(tmp_path, "--ready-line", "--exit-on-stdin-close")
    try:
        _read_ready_line(serve)
        serve.send_signal(signal.SIGINT)
        # A serve that ignores SIGINT is killed at the deadline, ending the read.
        timer = threading.Timer(30, serve.kill)
        timer.start()
        try:
            output = serve.stdout.read()
        finally:
            timer.cancel()
        serve.wait(timeout=30)
        assert serve.returncode == 0, output[-2000:]
        assert "Traceback" not in output
        assert "Fatal Python error" not in output
    finally:
        if serve.poll() is None:
            serve.kill()
            serve.wait()
        serve.stdin.close()
        serve.stdout.close()


def test_serve_exits_nonzero_on_a_port_another_socket_holds(tmp_path):
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        open_database(tmp_path / "handshake.db").close()
        held = holder.getsockname()[1]
        result = subprocess.run(
            [
                sys.executable, "-m", "sensei_top.cli", "--db", str(tmp_path / "handshake.db"),
                "serve", "--port", str(held), "--no-backup", "--no-corpus-refresh",
                "--no-archetype-refresh", "--no-reference-refresh",
            ],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        )
    assert result.returncode != 0
    assert "Cannot listen" in result.stderr


# --- config: the settings the desktop shell drives (plan 6, S3) -------------
#
# Expectations come from S3 and D2-D4/D11: --json carries every value the
# Settings page shows and no key; a key goes to the keyring when one exists
# (here, conftest's in-memory one) and to the file otherwise; '-' reads it
# from stdin; an empty value clears a setting.

CLAUDE_KEY = "sk-dummy-claude-0123456789-not-a-real-key"
TOPDECK_KEY = "td-dummy-topdeck-9876543210-not-a-real-key"


def _config(tmp_path: Path, *argv: str) -> None:
    cli_module.main(["--db", str(tmp_path / "t.db"), "config", *argv])


def _config_json(tmp_path: Path, capsys) -> dict:
    capsys.readouterr()
    _config(tmp_path, "--json")
    return json.loads(capsys.readouterr().out)


def _config_file() -> str:
    from sensei_top.llm.config import config_path

    path = config_path()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _no_keyring() -> None:
    import keyring
    from keyring.backends import fail

    keyring.set_keyring(fail.Keyring())


def test_config_json_round_trips_every_setter(tmp_path, monkeypatch, capsys, memory_keyring):
    arena_log = tmp_path / "Player.log"
    arena_log.write_text("", encoding="utf-8")
    mtgo_dir = tmp_path / "mtgo"
    mtgo_dir.mkdir()
    decks = tmp_path / "decks"
    decks.mkdir()
    backups = tmp_path / "copies"

    monkeypatch.setattr(sys, "stdin", io.StringIO(CLAUDE_KEY + "\n"))
    _config(
        tmp_path,
        "--set-key", "-",
        "--set-topdeck-key", TOPDECK_KEY,
        "--set-arena-log", str(arena_log),
        "--set-date-order", "dmy",
        "--set-mtgo-handle", "Player1",
        "--set-mtgo-dir", str(mtgo_dir),
        "--set-mtgo-deck-dir", str(decks),
        "--set-backup-dir", str(backups),
        "--set-backup-keep", "3",
        "--set-model", "claude-sonnet-5",
        "--set-effort", "low",
    )
    body = _config_json(tmp_path, capsys)

    from sensei_top.llm.client import REPORT_MODELS
    from sensei_top.llm.config import config_path

    assert body == {
        "config_path": str(config_path()),
        "arena": {"log": str(arena_log.resolve()), "date_order": "dmy"},
        "mtgo": {"handle": "Player1", "dir": str(mtgo_dir.resolve()),
                 "deck_dir": str(decks.resolve())},
        "backup": {"dir": str(backups.resolve()), "keep": 3},
        "claude": {
            "key_set": True, "key_source": "keyring",
            "model": "claude-sonnet-5", "effort": "low",
        },
        "topdeck": {"key_set": True, "key_source": "keyring"},
        "models": [{"value": key, "label": label} for key, label in REPORT_MODELS.items()],
    }

    # An empty value clears each one; the keys have flags of their own.
    _config(
        tmp_path,
        "--clear-key", "--clear-topdeck-key",
        "--set-arena-log", "", "--set-date-order", "",
        "--set-mtgo-handle", "", "--set-mtgo-dir", "", "--set-mtgo-deck-dir", "",
        "--set-backup-dir", "", "--set-backup-keep", "",
        "--set-model", "", "--set-effort", "",
    )
    body = _config_json(tmp_path, capsys)
    assert body["arena"] == {"log": None, "date_order": "auto"}
    assert body["mtgo"] == {"handle": None, "dir": None, "deck_dir": None}
    assert body["backup"] == {"dir": str((tmp_path / "backups").resolve()), "keep": 1}
    assert body["claude"] == {
        "key_set": False, "key_source": None, "model": "claude-opus-5-5", "effort": "high",
    }
    assert body["topdeck"] == {"key_set": False, "key_source": None}
    assert memory_keyring == {}


def test_no_key_value_reaches_the_output_or_the_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(CLAUDE_KEY + "\n"))
    cli_module.main(["--db", str(tmp_path / "t.db"), "--verbose", "config", "--set-key", "-"])
    cli_module.main([
        "--db", str(tmp_path / "t.db"), "--verbose", "config", "--set-topdeck-key", TOPDECK_KEY,
    ])
    for argv in (["--json"], ["--show"], []):
        cli_module.main(["--db", str(tmp_path / "t.db"), "--verbose", "config", *argv])
    _no_keyring()
    cli_module.main(["--db", str(tmp_path / "t.db"), "--verbose", "config", "--json"])

    captured = capsys.readouterr()
    written = [path.read_text(encoding="utf-8") for path in (tmp_path / "logs").iterdir()]
    assert written
    for text in (captured.out, captured.err, *written):
        assert CLAUDE_KEY not in text
        assert TOPDECK_KEY not in text


def test_set_key_dash_reads_the_key_from_a_real_stdin(tmp_path):
    """A child process, as the shell runs it: the key arrives on a pipe, never
    on argv, and the child has no keyring (conftest), so it lands in the file."""
    result = subprocess.run(
        [sys.executable, "-m", "sensei_top.cli", "--db", str(tmp_path / "t.db"),
         "config", "--set-key", "-"],
        input=CLAUDE_KEY + "\n", capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "no system keyring was found" in result.stdout
    assert CLAUDE_KEY not in result.stdout + result.stderr
    assert f'api_key = "{CLAUDE_KEY}"' in _config_file()


def test_an_empty_key_is_refused_rather_than_cleared(tmp_path, monkeypatch, memory_keyring):
    memory_keyring[("sensei-top", "claude")] = CLAUDE_KEY
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
    with pytest.raises(SystemExit) as exc_info:
        _config(tmp_path, "--set-key", "-")
    assert "--clear-key" in str(exc_info.value)
    assert memory_keyring == {("sensei-top", "claude"): CLAUDE_KEY}


def test_set_key_goes_to_the_keyring_and_takes_the_file_copy_out(tmp_path, memory_keyring):
    from sensei_top.llm import config as llm_config

    cli_module._write_llm_config(api_key="old-file-key", model="claude-sonnet-5", effort=None)
    cli_module._write_topdeck_config(api_key="old-topdeck-key")

    _config(tmp_path, "--set-key", CLAUDE_KEY, "--set-topdeck-key", TOPDECK_KEY)

    assert memory_keyring == {
        ("sensei-top", "claude"): CLAUDE_KEY,
        ("sensei-top", "topdeck"): TOPDECK_KEY,
    }
    text = _config_file()
    assert "api_key" not in text
    assert 'model = "claude-sonnet-5"' in text
    assert llm_config.load().api_key == CLAUDE_KEY
    assert llm_config.key_source() == "keyring"


def test_with_no_keyring_set_key_writes_the_file_and_says_why(tmp_path, capsys):
    _no_keyring()
    _config(tmp_path, "--set-key", CLAUDE_KEY, "--set-topdeck-key", TOPDECK_KEY)

    out = capsys.readouterr().out
    assert out.count("no system keyring was found") == 2
    text = _config_file()
    assert f'api_key = "{CLAUDE_KEY}"' in text
    assert f'api_key = "{TOPDECK_KEY}"' in text
    body = _config_json(tmp_path, capsys)
    assert body["claude"]["key_source"] == "file"
    assert body["topdeck"]["key_source"] == "file"


def test_key_source_reports_env_over_keyring_over_file(tmp_path, monkeypatch, capsys,
                                                       memory_keyring):
    cli_module._write_llm_config(api_key="file-key", model=None, effort=None)
    cli_module._write_topdeck_config(api_key="file-topdeck-key")
    sources = lambda body: (body["claude"]["key_source"], body["topdeck"]["key_source"])  # noqa: E731

    assert sources(_config_json(tmp_path, capsys)) == ("file", "file")
    memory_keyring[("sensei-top", "claude")] = "keyring-key"
    memory_keyring[("sensei-top", "topdeck")] = "keyring-topdeck-key"
    assert sources(_config_json(tmp_path, capsys)) == ("keyring", "keyring")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setenv("TOPDECK_API_KEY", "env-topdeck-key")
    assert sources(_config_json(tmp_path, capsys)) == ("env", "env")


def test_the_summary_names_the_keyring_not_the_file(tmp_path, capsys, memory_keyring):
    from sensei_top.llm.config import config_path

    cli_module._write_mtgo_config(handle="Player1")  # so the file exists
    memory_keyring[("sensei-top", "claude")] = CLAUDE_KEY
    memory_keyring[("sensei-top", "topdeck")] = TOPDECK_KEY

    _config(tmp_path, "--show")

    lines = capsys.readouterr().out.splitlines()
    for prefix in ("Claude credential source:", "TopDeck.gg key source:"):
        line = next(line for line in lines if line.startswith(prefix))
        assert "system keyring" in line
        assert str(config_path()) not in line


def test_clear_key_removes_it_from_the_keyring_and_the_file(tmp_path, capsys, memory_keyring):
    cli_module._write_llm_config(api_key="file-key", model="claude-sonnet-5", effort=None)
    memory_keyring[("sensei-top", "claude")] = CLAUDE_KEY

    _config(tmp_path, "--clear-key")

    assert memory_keyring == {}
    text = _config_file()
    assert "api_key" not in text
    assert 'model = "claude-sonnet-5"' in text
    assert _config_json(tmp_path, capsys)["claude"]["key_set"] is False


def test_nothing_moves_a_file_key_without_being_asked(tmp_path, capsys, memory_keyring):
    cli_module._write_llm_config(api_key="file-key", model=None, effort=None)

    _config(tmp_path)
    _config(tmp_path, "--json")
    _config(tmp_path, "--set-model", "claude-sonnet-5")

    assert memory_keyring == {}
    assert 'api_key = "file-key"' in _config_file()


def test_move_keys_to_keyring_moves_both_on_request(tmp_path, capsys, memory_keyring):
    cli_module._write_llm_config(api_key="file-key", model="claude-sonnet-5", effort=None)
    cli_module._write_topdeck_config(api_key="file-topdeck-key")

    _config(tmp_path, "--move-keys-to-keyring")

    assert memory_keyring == {
        ("sensei-top", "claude"): "file-key",
        ("sensei-top", "topdeck"): "file-topdeck-key",
    }
    text = _config_file()
    assert "api_key" not in text
    assert 'model = "claude-sonnet-5"' in text
    assert "file-key" not in capsys.readouterr().out


def test_move_keys_to_keyring_keeps_a_different_keyring_key(tmp_path, memory_keyring):
    """Overwriting would change which key is in force, so neither copy moves."""
    cli_module._write_llm_config(api_key="file-key", model=None, effort=None)
    memory_keyring[("sensei-top", "claude")] = "keyring-key"

    with pytest.raises(SystemExit) as exc_info:
        _config(tmp_path, "--move-keys-to-keyring")
    assert "already holds a different Claude key" in str(exc_info.value)
    assert memory_keyring == {("sensei-top", "claude"): "keyring-key"}
    assert 'api_key = "file-key"' in _config_file()


def test_move_keys_to_keyring_with_no_keyring_leaves_the_file_alone(tmp_path):
    cli_module._write_llm_config(api_key="file-key", model=None, effort=None)
    _no_keyring()

    with pytest.raises(SystemExit) as exc_info:
        _config(tmp_path, "--move-keys-to-keyring")
    assert "No system keyring was found" in str(exc_info.value)
    assert 'api_key = "file-key"' in _config_file()


def test_config_json_refuses_a_setter_beside_it(tmp_path):
    with pytest.raises(SystemExit):
        _config(tmp_path, "--json", "--set-mtgo-handle", "Player1")
    assert _config_file() == ""


def _arena_log_config(path: Path) -> None:
    cli_module._write_arena_config(log=str(path))


def test_resolve_log_honours_arena_after_mtga_log(tmp_path, monkeypatch):
    """D11: --file, then $MTGA_LOG, then [arena] log, then autodetection."""
    autodetected = tmp_path / "autodetected" / "Player.log"
    configured = tmp_path / "configured" / "Player.log"
    from_env = tmp_path / "env" / "Player.log"
    explicit = tmp_path / "explicit" / "Player.log"
    for path in (autodetected, configured, from_env, explicit):
        path.parent.mkdir()
        path.write_text("", encoding="utf-8")
    monkeypatch.setattr("sensei_top.live.default_log_path", lambda: autodetected)

    assert cli_module._resolve_log(None) == autodetected
    _arena_log_config(configured)
    assert cli_module._resolve_log(None) == configured
    monkeypatch.setenv("MTGA_LOG", str(from_env))
    assert cli_module._resolve_log(None) == from_env
    assert cli_module._resolve_log(str(explicit)) == explicit


def test_a_configured_arena_log_that_is_missing_is_passed_over(tmp_path, monkeypatch):
    monkeypatch.setattr("sensei_top.live.default_log_path", lambda: None)
    _arena_log_config(tmp_path / "gone" / "Player.log")

    with pytest.raises(SystemExit) as exc_info:
        cli_module._resolve_log(None)
    assert "--set-arena-log" in str(exc_info.value)


@pytest.mark.parametrize("command", ["ingest", "serve"])
def test_the_date_order_comes_from_arena_unless_locale_is_given(command, tmp_path):
    parser = cli_module.build_parser()

    args = parser.parse_args([command])
    cli_module._resolve_locale(args)
    assert args.locale == "auto"

    cli_module._write_arena_config(date_order="dmy")
    args = parser.parse_args([command])
    cli_module._resolve_locale(args)
    assert args.locale == "dmy"

    args = parser.parse_args([command, "--locale", "mdy"])
    cli_module._resolve_locale(args)
    assert args.locale == "mdy"

    args = parser.parse_args([command, "--locale", "auto"])
    cli_module._resolve_locale(args)
    assert args.locale == "auto"


def test_the_mtgo_setters_keep_a_hand_written_deck_dir(tmp_path, capsys):
    """A deck_dir written by hand survives the other two setters."""
    decks = str(tmp_path / "decks")
    mtgo_dir = tmp_path / "mtgo"
    mtgo_dir.mkdir()
    cli_module._write_config_tables({"mtgo": {"deck_dir": decks}})

    _config(tmp_path, "--set-mtgo-handle", "Player1")
    assert _config_json(tmp_path, capsys)["mtgo"]["deck_dir"] == decks
    _config(tmp_path, "--set-mtgo-dir", str(mtgo_dir))
    assert _config_json(tmp_path, capsys)["mtgo"]["deck_dir"] == decks


def test_set_mtgo_deck_dir_writes_and_clears_it(tmp_path, capsys):
    decks = tmp_path / "decks"
    decks.mkdir()
    _config(tmp_path, "--set-mtgo-deck-dir", str(decks))
    assert _config_json(tmp_path, capsys)["mtgo"]["deck_dir"] == str(decks.resolve())
    _config(tmp_path, "--set-mtgo-deck-dir", "")
    assert _config_json(tmp_path, capsys)["mtgo"]["deck_dir"] is None


def test_the_mtgo_setters_keep_each_others_fields(tmp_path, capsys):
    mtgo_dir = tmp_path / "mtgo"
    mtgo_dir.mkdir()
    decks = tmp_path / "decks"
    decks.mkdir()
    _config(tmp_path, "--set-mtgo-handle", "Player1")
    _config(tmp_path, "--set-mtgo-dir", str(mtgo_dir))
    _config(tmp_path, "--set-mtgo-deck-dir", str(decks))
    mtgo = _config_json(tmp_path, capsys)["mtgo"]
    assert mtgo["handle"] == "Player1"
    assert mtgo["dir"] == str(mtgo_dir.resolve())
    assert mtgo["deck_dir"] == str(decks.resolve())


def test_a_keyring_that_refuses_the_write_sends_the_key_to_the_file(tmp_path, capsys):
    import keyring
    from keyring.backend import KeyringBackend
    from keyring.errors import PasswordSetError

    class _Refusing(KeyringBackend):
        priority = 1

        def get_password(self, service, username):
            return None

        def set_password(self, service, username, password):
            raise PasswordSetError("locked")

        def delete_password(self, service, username):
            raise NotImplementedError

    keyring.set_keyring(_Refusing())
    cli_module.main(
        ["--db", str(tmp_path / "t.db"), "--verbose", "config", "--set-key", CLAUDE_KEY]
    )

    captured = capsys.readouterr()
    assert "the system keyring did not take it (the log says why)" in captured.out
    assert f'api_key = "{CLAUDE_KEY}"' in _config_file()
    written = [path.read_text(encoding="utf-8") for path in (tmp_path / "logs").iterdir()]
    for text in (captured.out, captured.err, *written):
        assert CLAUDE_KEY not in text


def test_version_flag_prints_the_pyproject_version(capsys):
    """The frozen build's smoke test compares ``--version`` to pyproject."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    with pytest.raises(SystemExit) as exit_info:
        cli_module.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == expected
