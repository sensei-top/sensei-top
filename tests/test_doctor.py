"""``sensei-top doctor`` and ``diagnostics``.

``client_header.log`` is the first 40 lines of a real ``Player.log``; its
line 35 is ``DETAILED LOGS: ENABLED`` (found with ``grep -a -n`` on the file,
the one place a line is wanted, not an entry). The ``DISABLED`` spelling has
never been captured, so nothing here asserts it (docs/status.md).
"""

import json
import os
import sqlite3
import tomllib
import zipfile
from pathlib import Path

import pytest

from sensei_top import cli as cli_module
from sensei_top import secrets
from sensei_top.db import open_database
from sensei_top.llm.config import config_path

FIXTURES = Path(__file__).parent / "fixtures"
HEADER_LOG = FIXTURES / "client_header.log"

CLAUDE_KEY = "sk-ant-test-claude-0123456789"
TOPDECK_KEY = "td-test-topdeck-9876543210"


@pytest.fixture(autouse=True)
def _nothing_autodetected(monkeypatch):
    """No Arena install on the machine running the tests."""
    monkeypatch.setattr("sensei_top.arena_config.default_log_path", lambda: None)


def _doctor(tmp_path, capsys, *argv) -> dict:
    cli_module.main(["--db", str(tmp_path / "t.db"), "doctor", "--json", *argv])
    return json.loads(capsys.readouterr().out)


def _write_config(text: str) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_doctor_reports_detailed_logs_enabled_from_the_fixture_line(tmp_path, capsys):
    data = _doctor(tmp_path, capsys, "--file", str(HEADER_LOG))
    assert data["arena_log"] == {
        "path": str(HEADER_LOG),
        "source": "flag",
        "detailed_logs": "enabled",
    }


def test_doctor_reports_unknown_without_the_line(tmp_path, capsys):
    log = tmp_path / "Player.log"
    log.write_text("[UnityCrossThreadLogger]first line\nsecond line\n")
    data = _doctor(tmp_path, capsys, "--file", str(log))
    assert data["arena_log"]["detailed_logs"] == "unknown"


def test_doctor_reports_unknown_when_there_is_no_log(tmp_path, capsys):
    data = _doctor(tmp_path, capsys)
    assert data["arena_log"] == {"path": None, "source": "none", "detailed_logs": "unknown"}


def test_doctor_names_where_the_log_came_from(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sensei_top.arena_config.default_log_path", lambda: HEADER_LOG)
    assert _doctor(tmp_path, capsys)["arena_log"]["source"] == "autodetect"

    configured = tmp_path / "configured.log"
    configured.write_text("x\n")
    _write_config(f'[arena]\nlog = "{configured.as_posix()}"\n')
    data = _doctor(tmp_path, capsys)
    assert data["arena_log"]["source"] == "config"
    assert data["arena_log"]["path"] == str(configured)

    monkeypatch.setenv("MTGA_LOG", str(HEADER_LOG))
    assert _doctor(tmp_path, capsys)["arena_log"]["source"] == "environment"


def test_doctor_without_a_database_creates_none_and_reports_unknown(tmp_path, capsys):
    data = _doctor(tmp_path, capsys)
    assert not (tmp_path / "t.db").exists()
    assert data["cards"] == {"arena_ids": None, "rules_text": None}
    assert data["database"]["exists"] is False
    assert data["database"]["schema_version"] is None
    assert isinstance(data["database"]["code_version"], int)
    assert set(data) == {"arena_log", "mtgo", "cards", "database", "config_path", "keyring_backend"}
    assert set(data["mtgo"]) == {
        "log_dir", "log_dir_source", "deck_dir", "deck_dir_source", "handle_set", "discovered",
    }


def test_doctor_reports_the_discovered_mtgo_folder_absolute(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sensei_top.mtgo.discover.discover_log_folder", lambda: Path("found"))
    assert _doctor(tmp_path, capsys)["mtgo"]["discovered"] == str(tmp_path / "found")


def test_doctor_reports_no_discovered_mtgo_folder_as_null(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sensei_top.mtgo.discover.discover_log_folder", lambda: None)
    assert _doctor(tmp_path, capsys)["mtgo"]["discovered"] is None


def test_doctor_reads_an_existing_database_without_changing_it(tmp_path, capsys):
    db = tmp_path / "t.db"
    conn = open_database(db)
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (1, 'A'), (2, 'B')")
    conn.execute("UPDATE cards SET oracle_text = 'text' WHERE grp_id = 2")
    conn.commit()
    conn.close()
    before = db.stat().st_mtime_ns
    data = _doctor(tmp_path, capsys)
    assert data["cards"] == {"arena_ids": 2, "rules_text": 1}
    assert data["database"]["exists"] is True
    assert data["database"]["schema_version"] == data["database"]["code_version"]
    assert db.stat().st_mtime_ns == before


def test_doctor_reads_a_database_with_no_tables_as_unknown(tmp_path, capsys):
    sqlite3.connect(tmp_path / "t.db").close()
    data = _doctor(tmp_path, capsys)
    assert data["cards"] == {"arena_ids": None, "rules_text": None}
    assert data["database"]["schema_version"] is None


def test_doctor_prints_the_hint_only_for_a_found_log_that_does_not_say(tmp_path, capsys):
    log = tmp_path / "Player.log"
    log.write_text("nothing\n")
    cli_module.main(["--db", str(tmp_path / "t.db"), "doctor", "--file", str(log)])
    assert "Turn on Detailed Logs (Plugin Support)" in capsys.readouterr().out
    cli_module.main(["--db", str(tmp_path / "t.db"), "doctor", "--file", str(HEADER_LOG)])
    assert "Turn on Detailed Logs" not in capsys.readouterr().out
    cli_module.main(["--db", str(tmp_path / "t.db"), "doctor"])
    assert "Turn on Detailed Logs" not in capsys.readouterr().out


def test_doctor_prints_unknown_card_lines_without_a_database(tmp_path, capsys):
    cli_module.main(["--db", str(tmp_path / "t.db"), "doctor"])
    out = capsys.readouterr().out
    assert "Cards with an Arena id: unknown" in out
    assert "Cards with rules text (from Scryfall): unknown" in out


def test_doctor_file_is_reported_absolute(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel.log").write_text("x\n")
    data = _doctor(tmp_path, capsys, "--file", "rel.log")
    assert data["arena_log"]["path"] == str(tmp_path / "rel.log")


def test_the_card_database_follows_the_configured_arena_log(tmp_path):
    from sensei_top.cards import arena_card_database_path

    install = tmp_path / "Wizards/MTGA"
    card_db = install / "MTGA_Data/Downloads/Raw/Raw_CardDatabase_abc123.mtga"
    card_db.parent.mkdir(parents=True)
    card_db.write_text("")
    (install / "MTGA_Data/Managed").mkdir(parents=True)
    log = tmp_path / "elsewhere/Player.log"
    log.parent.mkdir()
    log.write_bytes(f"Mono path[0] = '{install.as_posix()}/MTGA_Data/Managed'\r\n".encode())
    _write_config(f'[arena]\nlog = "{log.as_posix()}"\n')
    assert arena_card_database_path() == card_db.resolve()


def _diagnostics(tmp_path, *argv):
    cli_module.main(["--db", str(tmp_path / "t.db"), "diagnostics", *argv])


def _members(zip_path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(zip_path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def test_a_configured_key_never_reaches_the_zip(tmp_path, memory_keyring):
    secrets.set(secrets.CLAUDE, CLAUDE_KEY)
    assert memory_keyring  # the in-memory backend holds one
    _write_config(
        f'[claude]\napi_key = "{CLAUDE_KEY}"\nmodel = "claude-test"\n\n'
        f'[claude.coach]\napi_key = "{CLAUDE_KEY}"\neffort = "high"\n\n'
        f'[topdeck]\napi_key = "{TOPDECK_KEY}"\n\n'
        '[mtgo]\nhandle = "someone"\n'
    )
    out = tmp_path / "d.zip"
    _diagnostics(tmp_path, "--out", str(out), "--with-player-log")
    members = _members(out)
    assert "config.toml" in members
    for name, data in members.items():
        assert CLAUDE_KEY.encode() not in data, name
        assert TOPDECK_KEY.encode() not in data, name
    config = members["config.toml"].decode()
    assert 'model = "claude-test"' in config
    assert 'effort = "high"' in config
    assert "api_key" not in config
    assert not any(name.endswith(".db") for name in members)


def test_player_log_is_absent_without_its_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("MTGA_LOG", str(HEADER_LOG))
    without = tmp_path / "without.zip"
    _diagnostics(tmp_path, "--out", str(without))
    assert "Player.log" not in _members(without)

    with_log = tmp_path / "with.zip"
    _diagnostics(tmp_path, "--out", str(with_log), "--with-player-log")
    assert _members(with_log)["Player.log"] == HEADER_LOG.read_bytes()


def test_the_zip_carries_doctor_counts_and_both_logs(tmp_path):
    open_database(tmp_path / "t.db").close()
    shell_log = tmp_path / "shell-src.log"
    shell_log.write_bytes(b"shell line\n")
    out = tmp_path / "d.zip"
    _diagnostics(tmp_path, "--out", str(out), "--shell-log", str(shell_log))
    members = _members(out)
    assert json.loads(members["doctor.json"])["database"]["exists"] is True
    assert "cards" in json.loads(members["row_counts.json"])
    assert members["logs/shell.log"] == b"shell line\n"
    assert "logs/sensei-top.log" in members


def test_list_prints_entries_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "d.zip"
    _diagnostics(tmp_path, "--list")
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("doctor.json\t") for line in lines)
    assert not out.exists()
    assert not list(tmp_path.glob("*.zip"))


def test_diagnostics_needs_out_or_list(tmp_path):
    with pytest.raises(SystemExit) as exc:
        _diagnostics(tmp_path)
    assert exc.value.code == "Pass --out FILE.zip, or --list to see what it would contain."


def test_diagnostics_refuses_an_existing_zip(tmp_path):
    out = tmp_path / "d.zip"
    out.write_bytes(b"keep")
    with pytest.raises(SystemExit) as exc:
        _diagnostics(tmp_path, "--out", str(out))
    assert exc.value.code == f"{out} already exists; choose another name."
    assert out.read_bytes() == b"keep"


def test_keys_inside_arrays_never_reach_the_zip(tmp_path):
    _write_config(
        f'[[extra]]\napi_key = "{CLAUDE_KEY}"\nname = "kept"\n\n'
        f'[other]\nitems = [{{ api_key = "{TOPDECK_KEY}", label = "inline" }}]\n'
    )
    out = tmp_path / "d.zip"
    _diagnostics(tmp_path, "--out", str(out))
    members = _members(out)
    for name, data in members.items():
        assert CLAUDE_KEY.encode() not in data, name
        assert TOPDECK_KEY.encode() not in data, name
    config = members["config.toml"].decode()
    assert "api_key" not in config
    assert "kept" in config and "inline" in config
    assert "{'" not in config  # never a Python dict's repr
    assert tomllib.loads(config)["other"]["items"] == [{"label": "inline"}]


def test_the_mtgo_handle_is_not_in_the_zip_config(tmp_path):
    _write_config('[mtgo]\nhandle = "SomeHandleName"\ndir = "/somewhere"\n')
    out = tmp_path / "d.zip"
    _diagnostics(tmp_path, "--out", str(out))
    members = _members(out)
    assert b"SomeHandleName" not in b"".join(members.values())
    assert tomllib.loads(members["config.toml"].decode())["mtgo"] == {"dir": "/somewhere"}
    assert json.loads(members["doctor.json"])["mtgo"]["handle_set"] is True


def test_the_home_directory_is_a_tilde_in_the_zipped_report_and_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "cfg"))
    _write_config(f'[arena]\nlog = "{(home / "Player.log").as_posix()}"\n')
    out = tmp_path / "d.zip"
    cli_module.main(["--db", str(tmp_path / "t.db"), "diagnostics", "--out", str(out)])
    members = _members(out)
    for name in ("doctor.json", "config.toml"):
        text = members[name].decode()
        assert "~" in text, name
        assert home.as_posix() not in text, name


def test_a_symlinked_db_still_gets_its_log_in_the_zip(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    open_database(real / "t.db").close()
    (real / "logs").mkdir(exist_ok=True)
    (real / "logs" / "sensei-top.log").write_text("a line\n")
    link = tmp_path / "link"
    link.mkdir()
    (link / "t.db").symlink_to(real / "t.db")
    out = tmp_path / "d.zip"
    cli_module.main(["--db", str(link / "t.db"), "diagnostics", "--out", str(out)])
    assert "logs/sensei-top.log" in _members(out)


def test_mtgo_warnings_from_0_7_0_reach_the_zip_without_player_names(tmp_path):
    """Each MTGO warning 0.7.0 wrote with a handle in it, spelled as its
    f-string in projector/mtgo/ formatted it then, with "Hero" as the user
    and "Villain" as the opponent. The last two lines name a card and come
    from no player, so they pass through as written; one line ends the way
    a log written on Windows does."""
    prefix = "2026-10-01T10:00:00.000Z 0a1b2c3d WARNING sensei_top.projector.mtgo.project: [mtgo] "
    source = "Match_GameLog_x.dat"
    legacy = [
        "card event handle 'Villain' matches neither configured player in match m1",
        f"{source}: configured handle 'Hero' does not resolve to exactly one "
        "opponent among ['Hero', 'Villain', 'Villain-'] for match m1",
        f"{source}: unrecognised mulligan count in 'Villain mulligans to umpteen cards.'",
        f"{source}: unrecognised hand size in "
        "'Villain begins the game with umpteen cards in hand.'",
        f"{source}: mulligan count mismatch for Villain: 'mulligans to' implied 1, "
        "'begins the game' implied 2 ('Villain begins the game with five cards in hand.')",
        f"{source}: game boundary inferred from 'Turn 1' with no preceding start "
        "block ('Turn 1: Villain')",
        f"{source}: card event before any game started: "
        "\"Villain casts @[Urza's Saga@:1,2:@].\"",
    ]
    kept = [
        "MTGO card name 'Urza's Saga' not found in cards.name",
        f"{source}: card event before any game started: CastSpell 'Opt'",
    ]
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    text = "".join(prefix + line + "\n" for line in legacy[:-1])
    text += prefix + legacy[-1] + "\r\n"
    text += "".join(prefix + line + "\n" for line in kept)
    (log_dir / "sensei-top.log").write_text(text, newline="")
    out = tmp_path / "d.zip"
    _diagnostics(tmp_path, "--out", str(out))
    zipped = _members(out)["logs/sensei-top.log"].decode()
    assert "Hero" not in zipped
    assert "Villain" not in zipped
    lines = zipped.splitlines(keepends=True)
    assert lines[1].endswith(
        "configured handle <masked> does not resolve to exactly one opponent "
        "among <masked> for match m1\n"
    )
    assert lines[4].endswith(
        "mismatch for <masked>: 'mulligans to' implied 1, 'begins the game' implied 2 (<masked>)\n"
    )
    assert lines[6].endswith("started: <masked>\r\n")
    # The command's own header line follows them.
    assert lines[7:9] == [prefix + line + "\n" for line in kept]


def test_a_relative_mtga_log_is_reported_absolute(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel.log").write_text("x\n")
    monkeypatch.setenv("MTGA_LOG", "rel.log")
    monkeypatch.setenv("MTGO_LOG_DIR", "mtgo-rel")
    data = _doctor(tmp_path, capsys)
    assert data["arena_log"]["path"] == str(tmp_path / "rel.log")
    assert data["mtgo"]["log_dir"] == str(tmp_path / "mtgo-rel")


def test_a_table_name_with_a_space_round_trips_in_the_zip_config(tmp_path):
    _write_config('["my table"]\nname = "kept"\n\n["my table"."sub part"]\nn = 1\n')
    out = tmp_path / "d.zip"
    _diagnostics(tmp_path, "--out", str(out))
    parsed = tomllib.loads(_members(out)["config.toml"].decode())
    assert parsed == {"my table": {"name": "kept", "sub part": {"n": 1}}}


def test_diagnostics_into_a_missing_folder_exits_with_a_message(tmp_path):
    out = tmp_path / "nope" / "d.zip"
    with pytest.raises(SystemExit) as exc:
        _diagnostics(tmp_path, "--out", str(out))
    assert exc.value.code == (
        f"{out.parent} does not exist. "
        "Create it, or pass an --out inside a folder that does."
    )


def _two_prefix_logs(monkeypatch, tmp_path) -> tuple[Path, Path]:
    from sensei_top.reader.ingest import default_log_path

    home = tmp_path / "fakehome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("MTGA_LOG", raising=False)
    monkeypatch.setattr("sensei_top.arena_config.default_log_path", default_log_path)
    logs = []
    for prefix, mtime in ((home / ".wine", 1_000_000), (tmp_path / "elsewhere/pfx", 2_000_000)):
        log = prefix / "drive_c/users/me/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
        log.parent.mkdir(parents=True)
        log.write_text("x\n")
        os.utime(log, (mtime, mtime))
        logs.append(log)
    lutris = Path(os.environ["XDG_CONFIG_HOME"]) / "lutris/games"
    lutris.mkdir(parents=True)
    (lutris / "g.yml").write_text(f"game:\n  prefix: {tmp_path / 'elsewhere/pfx'}\n")
    return logs[0], logs[1]


def test_doctor_lists_every_log_found_chosen_first(tmp_path, capsys, monkeypatch):
    """A support report should show a second prefix without a back-and-forth."""
    older, newer = _two_prefix_logs(monkeypatch, tmp_path)
    data = _doctor(tmp_path, capsys)
    assert data["arena_log"]["path"] == str(newer)
    assert data["arena_log"]["found"] == [str(newer), str(older)]
    cli_module.main(["--db", str(tmp_path / "t.db"), "doctor"])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"Arena log: {newer}")
    assert out[1] == f"  Also found: {older}"
    assert out[2].startswith("  Detailed Logs:")


def test_doctor_has_no_found_field_for_a_configured_log(tmp_path, capsys, monkeypatch):
    """When the user chose the log, doctor does not search."""
    _two_prefix_logs(monkeypatch, tmp_path)
    configured = tmp_path / "configured.log"
    configured.write_text("x\n")
    _write_config(f'[arena]\nlog = "{configured.as_posix()}"\n')
    assert "found" not in _doctor(tmp_path, capsys)["arena_log"]
