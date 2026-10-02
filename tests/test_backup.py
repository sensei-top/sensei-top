"""Tests for ``src/sensei_top/backup/`` — the daily database backup
(one ``VACUUM INTO`` snapshot, refreshed at most once a day, taken by a
``backup`` subcommand and by ``serve``'s own background thread).

No fixtures needed. AGENTS.md non-negotiable #7 is "every *parsing rule*
needs a fixture-backed test"; this feature parses no log format at all — it
reads TOML and copies a SQLite file — so ``docs/testing.md``'s "every test is
fixture-backed or synthetic" is satisfied by synthetic databases built with
``open_database(tmp_path / ...)`` plus a handful of hand-inserted
``raw_events`` rows. CLI tests follow ``tests/test_cli_mtgo_status.py``'s
idiom: ``build_parser()`` -> ``parse_args([...])`` -> ``args.func(args)``,
``capsys`` for output, ``monkeypatch.setenv("XDG_CONFIG_HOME", ...)`` so no
test ever reads or writes a real ``~/.config/sensei-top/config.toml``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from sensei_top import cli as cli_module
from sensei_top import db
from sensei_top.backup import config as backup_config
from sensei_top.backup import run as backup_run
from sensei_top.backup.config import BACKUP_DIR_ENV, DEFAULT_KEEP, BackupConfig
from sensei_top.backup.schedule import BackupScheduler


def _isolate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(BACKUP_DIR_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def _write_backup_table(monkeypatch, tmp_path: Path, body: str) -> None:
    """Writes ``config.toml`` directly, in the exact quoted-string shape
    ``cli._write_config_tables`` emits for every scalar (``key = "value"``)
    — the shape ``_parse_keep`` has to tolerate for ``keep``."""
    config_dir = tmp_path / "config" / "sensei-top"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(f"[backup]\n{body}\n")


# --- backup/config.py: precedence and fail-soft parsing ---------------------


def test_defaults_to_a_backups_folder_beside_the_database(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    db_path = tmp_path / "data" / "sensei-top.db"

    cfg = backup_config.resolve(db_path)

    assert cfg == BackupConfig(
        directory=(db_path.parent / "backups").resolve(),
        keep=DEFAULT_KEEP,
        dir_source="default",
        keep_source="default",
    )


def test_config_file_sets_the_directory_and_keep(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    custom_dir = tmp_path / "elsewhere"
    _write_backup_table(monkeypatch, tmp_path, f'dir = "{custom_dir}"\nkeep = "3"')

    cfg = backup_config.resolve(tmp_path / "data" / "sensei-top.db")

    assert cfg.directory == custom_dir.resolve()
    assert cfg.dir_source == "config file"
    assert cfg.keep == 3
    assert cfg.keep_source == "config file"


def test_env_var_overrides_the_config_file_directory(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _write_backup_table(monkeypatch, tmp_path, f'dir = "{tmp_path / "from-file"}"')
    env_dir = tmp_path / "from-env"
    monkeypatch.setenv(BACKUP_DIR_ENV, str(env_dir))

    cfg = backup_config.resolve(tmp_path / "data" / "sensei-top.db")

    assert cfg.directory == env_dir.resolve()
    assert cfg.dir_source == f"${BACKUP_DIR_ENV}"


def test_flag_overrides_both_env_var_and_config_file(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _write_backup_table(monkeypatch, tmp_path, f'dir = "{tmp_path / "from-file"}"\nkeep = "5"')
    monkeypatch.setenv(BACKUP_DIR_ENV, str(tmp_path / "from-env"))
    flag_dir = tmp_path / "from-flag"

    cfg = backup_config.resolve(
        tmp_path / "data" / "sensei-top.db", dir_override=str(flag_dir), keep_override=7
    )

    assert cfg.directory == flag_dir.resolve()
    assert cfg.dir_source == "flag"
    assert cfg.keep == 7
    assert cfg.keep_source == "flag"


def test_malformed_toml_falls_back_to_the_default_not_an_exception(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    config_dir = tmp_path / "config" / "sensei-top"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("this is not { valid toml at all")

    cfg = backup_config.resolve(tmp_path / "data" / "sensei-top.db")

    assert cfg.dir_source == "default"
    assert cfg.keep_source == "default"


def test_a_file_with_no_backup_table_falls_back_to_the_default(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    config_dir = tmp_path / "config" / "sensei-top"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text('[claude]\napi_key = "x"\n')

    cfg = backup_config.resolve(tmp_path / "data" / "sensei-top.db")

    assert cfg.dir_source == "default"
    assert cfg.keep_source == "default"


def test_keep_round_trips_through_the_quoted_string_the_config_writer_emits(
    monkeypatch, tmp_path
):
    """Pins the trap named in backup/config.py's own module docstring: every
    scalar cli._write_config_tables emits is a quoted string (``keep =
    "3"``), never a bare TOML integer, so _parse_keep must accept both."""
    _isolate(monkeypatch, tmp_path)
    _write_backup_table(monkeypatch, tmp_path, 'keep = "3"')

    cfg = backup_config.resolve(tmp_path / "data" / "sensei-top.db")

    assert cfg.keep == 3
    assert cfg.keep_source == "config file"


@pytest.mark.parametrize("bad_keep", ['"0"', '"-1"', '"not-a-number"'])
def test_a_bad_keep_in_the_config_file_clamps_to_the_default(monkeypatch, tmp_path, bad_keep):
    _isolate(monkeypatch, tmp_path)
    _write_backup_table(monkeypatch, tmp_path, f"keep = {bad_keep}")

    cfg = backup_config.resolve(tmp_path / "data" / "sensei-top.db")

    assert cfg.keep == DEFAULT_KEEP
    assert cfg.keep_source == "default"


def test_slot_path_shapes(tmp_path):
    cfg = BackupConfig(directory=tmp_path, keep=3, dir_source="default", keep_source="default")
    db_path = Path("data/sensei-top.db")

    assert backup_config.slot_path(cfg, db_path, 0) == tmp_path / "sensei-top.db.backup"
    assert backup_config.slot_path(cfg, db_path, 1) == tmp_path / "sensei-top.db.backup.1"
    assert backup_config.slot_path(cfg, db_path, 2) == tmp_path / "sensei-top.db.backup.2"


def test_temp_path_lives_in_the_destination_directory(tmp_path):
    cfg = BackupConfig(directory=tmp_path, keep=1, dir_source="default", keep_source="default")
    temp = backup_config.temp_path(cfg, Path("data/sensei-top.db"))
    assert temp.parent == tmp_path
    assert temp.name.startswith("sensei-top.db.backup.tmp.")


# --- backup/run.py: the empirical gate ---------------------------------------
#
# This one test is run in isolation before any other run.py test is written
# (see the plan): it either confirms _vacuum_into's dedicated-connection
# design solves the problem the verified-behaviour table names, or it fails
# with "cannot VACUUM - SQL statements in progress" and says the fix belongs
# somewhere else. It is not weakened either way.


def test_vacuum_into_runs_on_a_connection_from_open_database(tmp_path):
    """An open, partly-consumed cursor on the CALLER's connection is exactly
    the shape that blocks VACUUM INTO outright when it runs on *that same*
    connection (measured: 'cannot VACUUM - SQL statements in progress').
    ``_vacuum_into`` opens its own connection instead, so this must succeed
    even with such a cursor left dangling on the caller's."""
    db_path = tmp_path / "source.db"
    conn = db.open_database(db_path)
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, payload) "
        "VALUES ('d', 'f', 'event', '{}')"
    )
    cursor = conn.execute("SELECT * FROM raw_events")
    cursor.fetchone()  # partly consumed, deliberately never exhausted

    temp = tmp_path / "out.db"
    backup_run._vacuum_into(db_path, temp, stop=None)

    assert temp.exists()
    out_conn = sqlite3.connect(f"file:{temp}?immutable=1", uri=True)
    assert out_conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 1
    out_conn.close()
    conn.close()


def test_a_query_only_connection_cannot_back_up(tmp_path):
    """Pins the other half of the verified-behaviour table: a read-only
    connection can never take a backup, so this feature can never be an API
    route (the API's connections are all ``PRAGMA query_only=ON``, per
    AGENTS.md non-negotiable #6)."""
    db_path, conn = _make_db(tmp_path)
    conn.close()

    ro_conn = db.connect(db_path)
    ro_conn.execute("PRAGMA query_only=ON")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro_conn.execute("VACUUM INTO ?", (str(tmp_path / "out.db"),))
    ro_conn.close()


# --- backup/run.py: helpers ---------------------------------------------


def _make_db(
    tmp_path: Path, name: str = "sensei-top.db", rows: int = 2
) -> tuple[Path, sqlite3.Connection]:
    """A migrated, synthetic database with ``rows`` hand-inserted
    ``raw_events`` rows -- enough for run_backup's own invariants
    (schema_version, raw_events count) to check against something real."""
    db_path = tmp_path / name
    conn = db.open_database(db_path)
    for i in range(rows):
        conn.execute(
            "INSERT INTO raw_events (digest, source_file, kind, payload) "
            "VALUES (?, 'f', 'event', '{}')",
            (f"digest-{i}",),
        )
    return db_path, conn


def _cfg(tmp_path: Path, *, keep: int = 1, directory: Path | None = None) -> BackupConfig:
    return BackupConfig(
        directory=directory or (tmp_path / "backups"),
        keep=keep,
        dir_source="default",
        keep_source="default",
    )


# --- backup/run.py: the freshness gate, --force, and never-backed-up ----


def test_never_backed_up_reads_as_none_not_zero(tmp_path):
    _db_path, conn = _make_db(tmp_path)
    assert backup_run.read_state(conn) is None
    assert backup_run.last_backup_age_seconds(conn) is None
    conn.close()


# --- backup/run.py: last_error_age_seconds / claim_age_seconds -----------
#
# Both mirror last_backup_age_seconds's own shape (None, never 0, until the
# column they read has ever been written) and power cmd_config's FAILED
# line and cmd_backup's busy message respectively.


def test_last_error_age_seconds_is_none_until_a_run_has_failed(tmp_path):
    _db_path, conn = _make_db(tmp_path)
    assert backup_run.last_error_age_seconds(conn) is None
    conn.close()


def test_last_error_age_seconds_measures_time_since_the_recorded_failure(tmp_path):
    _db_path, conn = _make_db(tmp_path)
    stale = (datetime.now(UTC) - timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO backup_state (id, last_error, last_error_at, updated_at) "
        "VALUES (1, 'disk full', ?, ?)",
        (stale, stale),
    )

    age = backup_run.last_error_age_seconds(conn)

    assert age is not None
    assert 85 <= age <= 95
    conn.close()


def test_claim_age_seconds_is_none_when_nothing_is_claimed(tmp_path):
    _db_path, conn = _make_db(tmp_path)
    assert backup_run.claim_age_seconds(conn) is None
    conn.close()


def test_claim_age_seconds_measures_time_since_the_claim_was_taken(tmp_path):
    _db_path, conn = _make_db(tmp_path)
    started = (datetime.now(UTC) - timedelta(seconds=41)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO backup_state (id, running_since, running_pid, updated_at) "
        "VALUES (1, ?, 12345, ?)",
        (started, started),
    )

    age = backup_run.claim_age_seconds(conn)

    assert age is not None
    assert 36 <= age <= 46
    conn.close()


def test_a_recent_backup_is_left_alone_without_force(tmp_path):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)

    first = backup_run.run_backup(conn, db_path, cfg=cfg)
    assert first.status == "ok"

    second = backup_run.run_backup(conn, db_path, cfg=cfg)
    assert second.status == "fresh"
    assert second.age_seconds is not None
    conn.close()


def test_force_overrides_the_freshness_gate(tmp_path):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)

    first = backup_run.run_backup(conn, db_path, cfg=cfg)
    assert first.status == "ok"

    second = backup_run.run_backup(conn, db_path, cfg=cfg, force=True)
    assert second.status == "ok"
    conn.close()


# --- backup/run.py: the claim --------------------------------------------


def test_a_claim_already_running_blocks_a_second_run_even_with_force(tmp_path):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)
    cfg.directory.mkdir(parents=True, exist_ok=True)
    now = backup_run._now_iso()
    conn.execute(
        "INSERT INTO backup_state (id, running_since, running_pid, updated_at) "
        "VALUES (1, ?, 999999, ?)",
        (now, now),
    )

    result = backup_run.run_backup(conn, db_path, cfg=cfg, force=True)

    assert result.status == "busy"
    assert result.running_pid == 999999
    conn.close()


def test_a_claim_older_than_the_stale_window_is_taken_over_with_a_warning(tmp_path, caplog):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)
    stale = (
        datetime.now(UTC) - timedelta(seconds=backup_run.CLAIM_STALE_SECONDS + 60)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO backup_state (id, running_since, running_pid, updated_at) "
        "VALUES (1, ?, 424242, ?)",
        (stale, stale),
    )

    with caplog.at_level(logging.WARNING):
        result = backup_run.run_backup(conn, db_path, cfg=cfg)

    assert result.status == "ok"
    assert any("424242" in message for message in caplog.messages)
    conn.close()


# --- backup/run.py: destination housekeeping -----------------------------


def test_destination_directory_is_created_if_missing(tmp_path):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)
    assert not cfg.directory.exists()

    result = backup_run.run_backup(conn, db_path, cfg=cfg)

    assert result.status == "ok"
    assert cfg.directory.is_dir()
    conn.close()


def test_insufficient_free_space_fails_before_any_write(tmp_path, monkeypatch):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(
        backup_run.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=0, used=0, free=1),
    )

    result = backup_run.run_backup(conn, db_path, cfg=cfg)

    assert result.status == "failed"
    assert "free" in result.error.lower()
    assert not backup_config.slot_path(cfg, db_path, 0).exists()
    conn.close()


# --- backup/run.py: the copy and its verification ------------------------


def test_a_backup_is_a_directly_openable_sqlite_file_with_the_same_rows(tmp_path):
    db_path, conn = _make_db(tmp_path, rows=3)
    cfg = _cfg(tmp_path)

    result = backup_run.run_backup(conn, db_path, cfg=cfg)

    assert result.status == "ok"
    assert result.path == backup_config.slot_path(cfg, db_path, 0)
    assert result.path.exists()

    out = sqlite3.connect(f"file:{result.path}?immutable=1", uri=True)
    assert out.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 3
    out.close()
    conn.close()


def test_verify_accepts_a_consistent_copy(tmp_path):
    db_path, conn = _make_db(tmp_path, rows=2)
    version = db.applied_version(conn)
    rows = conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
    conn.close()

    backup_run._verify(db_path, source_version=version, source_rows=rows, deep_verify=False)


def test_verify_rejects_a_file_whose_size_does_not_match_its_own_page_count(tmp_path):
    db_path, conn = _make_db(tmp_path, rows=1)
    version = db.applied_version(conn)
    conn.close()

    # Appending bytes past the legitimate content raises the file's size
    # without changing the page count SQLite's own header records -- the
    # exact shape of a short or truncated VACUUM INTO write.
    with open(db_path, "ab") as f:
        f.write(b"\x00" * 4096)

    with pytest.raises(backup_run.BackupError, match="page_count"):
        backup_run._verify(db_path, source_version=version, source_rows=1, deep_verify=False)


def test_verify_rejects_a_backup_whose_schema_version_disagrees(tmp_path):
    db_path, conn = _make_db(tmp_path, rows=1)
    conn.close()

    with pytest.raises(backup_run.BackupError, match="schema_version"):
        backup_run._verify(db_path, source_version=999, source_rows=1, deep_verify=False)


def test_verify_rejects_a_backup_with_fewer_rows_than_the_source_had(tmp_path):
    db_path, conn = _make_db(tmp_path, rows=1)
    version = db.applied_version(conn)
    conn.close()

    with pytest.raises(backup_run.BackupError, match="raw_events"):
        backup_run._verify(db_path, source_version=version, source_rows=5, deep_verify=False)


def test_verify_rejects_a_corrupt_file_only_under_deep_verify(tmp_path):
    """Flips one byte deep enough in the file to corrupt a b-tree page
    without breaking either of the three cheap invariants -- exactly the
    gap PRAGMA quick_check exists to close, at the cost this module's
    docstring names (67.7s measured on the real database), which is why it
    is opt-in rather than run on every backup."""
    db_path, conn = _make_db(tmp_path, rows=50)
    version = db.applied_version(conn)
    rows = conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
    conn.close()

    with open(db_path, "r+b") as f:
        f.seek(2 * 4096 + 100)
        b = f.read(1)
        f.seek(2 * 4096 + 100)
        f.write(bytes([(b[0] + 1) % 256]))

    # Not deep-verified: the corruption is invisible to the three cheap
    # invariants, so this passes.
    backup_run._verify(db_path, source_version=version, source_rows=rows, deep_verify=False)

    with pytest.raises(backup_run.BackupError, match="quick_check"):
        backup_run._verify(db_path, source_version=version, source_rows=rows, deep_verify=True)


# --- backup/run.py: the two central safety tests -------------------------


def test_a_failed_vacuum_leaves_the_previous_backup_untouched(tmp_path, monkeypatch):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)
    first = backup_run.run_backup(conn, db_path, cfg=cfg)
    assert first.status == "ok"
    original_bytes = first.path.read_bytes()

    def boom(db_path, temp, *, stop=None):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(backup_run, "_vacuum_into", boom)

    second = backup_run.run_backup(conn, db_path, cfg=cfg, force=True)

    assert second.status == "failed"
    assert first.path.read_bytes() == original_bytes
    assert not backup_config.temp_path(cfg, db_path).exists()

    state = backup_run.read_state(conn)
    assert state["last_error"] is not None
    assert state["last_path"] == str(first.path)
    assert state["last_bytes"] == first.bytes
    conn.close()


def test_a_failed_verification_leaves_the_previous_backup_untouched(tmp_path, monkeypatch):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)
    first = backup_run.run_backup(conn, db_path, cfg=cfg)
    assert first.status == "ok"
    original_bytes = first.path.read_bytes()

    def fail_verify(temp, *, source_version, source_rows, deep_verify):
        raise backup_run.BackupError("synthetic verification failure")

    monkeypatch.setattr(backup_run, "_verify", fail_verify)

    second = backup_run.run_backup(conn, db_path, cfg=cfg, force=True)

    assert second.status == "failed"
    assert "synthetic verification failure" in second.error
    assert first.path.read_bytes() == original_bytes
    assert not backup_config.temp_path(cfg, db_path).exists()

    state = backup_run.read_state(conn)
    assert state["last_path"] == str(first.path)
    conn.close()


# --- backup/run.py: rotation ----------------------------------------------


def test_a_failed_rotation_leaves_the_previous_backup_untouched(tmp_path, monkeypatch):
    """os.replace raising mid-rotation (a permissions error, a full
    destination) must surface as BackupResult(status='failed') -- the same
    contract _rotate already promises _verify's own failures, via
    BackupError -- never a bare OSError escaping run_backup. _cfg's default
    keep=1 makes the oldest-first shift loop a no-op, so the failure below is
    the final publish, os.replace(temp, slot 0)."""
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)
    first = backup_run.run_backup(conn, db_path, cfg=cfg)
    assert first.status == "ok"
    original_bytes = first.path.read_bytes()

    def boom(src, dst):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(backup_run.os, "replace", boom)

    second = backup_run.run_backup(conn, db_path, cfg=cfg, force=True)

    assert second.status == "failed"
    assert "rotation failed" in second.error
    assert first.path.read_bytes() == original_bytes
    assert not backup_config.temp_path(cfg, db_path).exists()

    state = backup_run.read_state(conn)
    assert state["last_error"] is not None
    assert state["last_path"] == str(first.path)
    conn.close()


def test_rotation_never_deletes_an_unrelated_file(tmp_path):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path, keep=1)
    cfg.directory.mkdir(parents=True, exist_ok=True)

    notes = cfg.directory / "notes.txt"
    notes.write_text("do not touch")
    other_db = cfg.directory / "other.db.backup.1"
    other_db.write_text("do not touch")
    lookalike = cfg.directory / f"{db_path.name}.backup.keepme"
    lookalike.write_text("do not touch")

    result = backup_run.run_backup(conn, db_path, cfg=cfg)

    assert result.status == "ok"
    assert notes.read_text() == "do not touch"
    assert other_db.read_text() == "do not touch"
    assert lookalike.read_text() == "do not touch"
    conn.close()


def test_keep_three_rotates_the_oldest_out(tmp_path):
    """A distinct marker row inserted between runs, then contents (not
    names) are asserted per slot -- what actually proves the rename order
    the plan specifies (oldest first, then the atomic publish)."""
    db_path, conn = _make_db(tmp_path, rows=0)
    cfg = _cfg(tmp_path, keep=3)

    def mark(label: str) -> None:
        conn.execute(
            "INSERT INTO raw_events (digest, source_file, kind, payload) "
            "VALUES (?, 'f', 'event', ?)",
            (label, label),
        )

    def marker_of(path: Path) -> str:
        c = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
        row = c.execute("SELECT payload FROM raw_events ORDER BY id DESC LIMIT 1").fetchone()
        c.close()
        return row[0]

    for label in ("run-1", "run-2", "run-3", "run-4"):
        mark(label)
        result = backup_run.run_backup(conn, db_path, cfg=cfg, force=True)
        assert result.status == "ok"

    assert marker_of(backup_config.slot_path(cfg, db_path, 0)) == "run-4"
    assert marker_of(backup_config.slot_path(cfg, db_path, 1)) == "run-3"
    assert marker_of(backup_config.slot_path(cfg, db_path, 2)) == "run-2"
    assert not backup_config.slot_path(cfg, db_path, 3).exists()
    conn.close()


def test_shrinking_keep_prunes_surplus_slots(tmp_path):
    db_path, conn = _make_db(tmp_path)
    cfg3 = _cfg(tmp_path, keep=3)
    for _ in range(3):
        result = backup_run.run_backup(conn, db_path, cfg=cfg3, force=True)
        assert result.status == "ok"
    assert backup_config.slot_path(cfg3, db_path, 1).exists()
    assert backup_config.slot_path(cfg3, db_path, 2).exists()

    cfg1 = _cfg(tmp_path, keep=1)  # same directory, smaller keep
    result = backup_run.run_backup(conn, db_path, cfg=cfg1, force=True)

    assert result.status == "ok"
    assert backup_config.slot_path(cfg1, db_path, 0).exists()
    assert not backup_config.slot_path(cfg1, db_path, 1).exists()
    assert not backup_config.slot_path(cfg1, db_path, 2).exists()
    conn.close()


# --- backup/run.py: recording ---------------------------------------------


def test_a_successful_run_records_measured_facts(tmp_path):
    db_path, conn = _make_db(tmp_path, rows=4)
    cfg = _cfg(tmp_path)

    result = backup_run.run_backup(conn, db_path, cfg=cfg)

    assert result.status == "ok"
    state = backup_run.read_state(conn)
    assert state["last_backup_at"] is not None
    assert state["last_path"] == str(result.path)
    assert state["last_bytes"] == result.bytes
    assert state["last_schema_version"] == result.schema_version
    assert state["backups"] == 1
    assert state["last_error"] is None
    assert state["running_since"] is None
    assert state["running_pid"] is None
    conn.close()


def test_backups_counter_increments_across_successful_runs(tmp_path):
    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)
    backup_run.run_backup(conn, db_path, cfg=cfg)
    backup_run.run_backup(conn, db_path, cfg=cfg, force=True)

    state = backup_run.read_state(conn)
    assert state["backups"] == 2
    conn.close()


# --- backup/run.py: project() must never touch backup_state --------------


def test_project_does_not_delete_backup_state(tmp_path):
    from sensei_top.projector.matches import project

    db_path, conn = _make_db(tmp_path)
    cfg = _cfg(tmp_path)
    result = backup_run.run_backup(conn, db_path, cfg=cfg)
    assert result.status == "ok"

    project(conn)

    state = backup_run.read_state(conn)
    assert state is not None
    assert state["last_path"] == str(result.path)
    conn.close()


# --- backup/run.py: interruptibility --------------------------------------


def test_stop_returns_promptly_while_a_backup_is_in_flight(tmp_path, monkeypatch):
    db_path, seed_conn = _make_db(tmp_path)
    seed_conn.close()
    cfg = _cfg(tmp_path)

    stop = threading.Event()
    started = threading.Event()

    def fake_vacuum_into(db_path, temp, *, stop=None):
        started.set()
        stop.wait()
        raise sqlite3.OperationalError("interrupted")

    monkeypatch.setattr(backup_run, "_vacuum_into", fake_vacuum_into)

    outcome: dict[str, backup_run.BackupResult] = {}

    def go() -> None:
        conn = db.open_database(db_path)
        try:
            outcome["result"] = backup_run.run_backup(conn, db_path, cfg=cfg, stop=stop)
        finally:
            conn.close()

    thread = threading.Thread(target=go)
    thread.start()
    assert started.wait(timeout=2), "backup never reached the vacuum step"

    before = time.monotonic()
    stop.set()
    thread.join(timeout=2)
    elapsed = time.monotonic() - before

    assert not thread.is_alive()
    assert elapsed < 1.0
    assert outcome["result"].status == "interrupted"


# --- backup/schedule.py ----------------------------------------------------
#
# Deadline-polling idiom throughout, matching tests/test_live.py's
# test_start_and_stop_are_clean / test_a_failing_poll_does_not_end_the_watch:
# wait for an observable effect up to a deadline rather than a fixed sleep.


def test_start_and_stop_are_clean(tmp_path):
    db_path, conn = _make_db(tmp_path)
    conn.close()
    backup_dir = tmp_path / "backups"
    backup_path = backup_dir / f"{db_path.name}.backup"

    scheduler = BackupScheduler(
        db_path=db_path, dir_override=str(backup_dir), startup_delay=0.0, check_interval=0.02
    )
    scheduler.start()
    deadline = time.monotonic() + 5
    while not backup_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    scheduler.stop()

    assert backup_path.exists(), "scheduler never took a backup"
    assert scheduler.is_alive() is False
    assert scheduler._thread is None


def test_scheduler_does_not_repeat_within_the_freshness_window(tmp_path):
    db_path, conn = _make_db(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_path = backup_dir / f"{db_path.name}.backup"

    scheduler = BackupScheduler(
        db_path=db_path, dir_override=str(backup_dir), startup_delay=0.0, check_interval=0.02
    )
    scheduler.start()
    deadline = time.monotonic() + 5
    while not backup_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert backup_path.exists()

    time.sleep(0.2)  # several more check_interval ticks
    scheduler.stop()

    state = backup_run.read_state(conn)
    assert state["backups"] == 1, "run_backup's own freshness gate should have blocked a repeat"
    conn.close()


def test_scheduler_never_migrates(tmp_path, monkeypatch):
    """The check runs hourly for as long as serve does, so a migration file
    that appeared in the working tree since startup would go live on the
    user's database, under code that doesn't know the new schema, if this
    check opened with open_database(). Measured: 047 was applied that way,
    uncommitted, two minutes after it was written."""
    db_path, conn = _make_db(tmp_path)
    conn.close()
    backup_dir = tmp_path / "backups"
    backup_path = backup_dir / f"{db_path.name}.backup"

    calls = {"n": 0}
    real_migrate = db.migrate

    def recording_migrate(*args, **kwargs):
        calls["n"] += 1
        return real_migrate(*args, **kwargs)

    monkeypatch.setattr(db, "migrate", recording_migrate)

    scheduler = BackupScheduler(
        db_path=db_path, dir_override=str(backup_dir), startup_delay=0.0, check_interval=0.02
    )
    scheduler.start()
    deadline = time.monotonic() + 5
    while not backup_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    scheduler.stop()

    assert backup_path.exists(), "scheduler never took a backup"
    assert calls["n"] == 0


def test_scheduler_survives_a_failing_run(tmp_path, monkeypatch):
    """One bad run must never stop the schedule -- same rule live.py's
    poll loop follows for a bad poll."""
    db_path, conn = _make_db(tmp_path)
    conn.close()
    backup_dir = tmp_path / "backups"

    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr("sensei_top.backup.schedule.run_backup", boom)

    scheduler = BackupScheduler(
        db_path=db_path, dir_override=str(backup_dir), startup_delay=0.0, check_interval=0.02
    )
    scheduler.start()
    deadline = time.monotonic() + 5
    while calls["n"] < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    scheduler.stop()

    assert calls["n"] >= 2, "scheduler stopped after the first failure"


def test_stop_returns_promptly_during_the_startup_delay(tmp_path):
    db_path, conn = _make_db(tmp_path)
    conn.close()

    scheduler = BackupScheduler(
        db_path=db_path,
        dir_override=str(tmp_path / "backups"),
        startup_delay=30.0,
        check_interval=30.0,
    )
    scheduler.start()
    started = time.monotonic()
    scheduler.stop(timeout=2)
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
    assert scheduler.is_alive() is False


def test_config_is_re_resolved_every_check(tmp_path, monkeypatch):
    """The scheduler must not cache a BackupConfig at construction time --
    a config.toml edit (or `sensei-top config --set-backup-dir`) while
    `serve` is running should take effect on the very next hourly check."""
    _isolate(monkeypatch, tmp_path)
    db_path, conn = _make_db(tmp_path)
    conn.close()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    scheduler = BackupScheduler(
        db_path=db_path, dir_override=str(first_dir), startup_delay=0.0, check_interval=0.02
    )
    scheduler.start()
    first_backup = first_dir / f"{db_path.name}.backup"
    deadline = time.monotonic() + 5
    while not first_backup.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert first_backup.exists()

    # Force a second run despite the freshness gate: rewrite backup_state's
    # last_backup_at to look like yesterday, then repoint the scheduler's
    # own directory the way editing config.toml would.
    yesterday = (datetime.now(UTC) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn2 = db.connect(db_path)
    conn2.execute("UPDATE backup_state SET last_backup_at = ? WHERE id = 1", (yesterday,))
    conn2.close()
    scheduler.dir_override = str(second_dir)

    second_backup = second_dir / f"{db_path.name}.backup"
    deadline = time.monotonic() + 5
    while not second_backup.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    scheduler.stop()

    assert second_backup.exists(), "scheduler kept using the directory from construction time"


# --- cli.py: cmd_backup -----------------------------------------------------
#
# CLI idiom from tests/test_cli_mtgo_status.py: build_parser() ->
# parse_args([...]) -> args.func(args), capsys for output. _isolate() (above)
# keeps XDG_CONFIG_HOME and SENSEI_TOP_BACKUP_DIR from leaking config.toml or an
# env var into these -- every test passes --dir explicitly instead.


def _backup_cmd(monkeypatch, tmp_path: Path, argv: list[str]) -> None:
    _isolate(monkeypatch, tmp_path)
    parser = cli_module.build_parser()
    args = parser.parse_args(argv)
    args.func(args)


def test_backup_command_prints_the_ok_summary_and_returns_cleanly(tmp_path, monkeypatch, capsys):
    db_path, conn = _make_db(tmp_path, rows=3)
    conn.close()
    backup_dir = tmp_path / "backups"

    _backup_cmd(monkeypatch, tmp_path, ["--db", str(db_path), "backup", "--dir", str(backup_dir)])

    out = capsys.readouterr().out
    expected_path = backup_dir / f"{db_path.name}.backup"
    assert f"Backed up {db_path} -> {expected_path}" in out
    assert "verified" in out
    assert "Keeping:   1 (current slot only)" in out


def test_backup_command_reports_fresh_and_names_the_current_slot(tmp_path, monkeypatch, capsys):
    db_path, conn = _make_db(tmp_path, rows=1)
    conn.close()
    backup_dir = tmp_path / "backups"

    _backup_cmd(monkeypatch, tmp_path, ["--db", str(db_path), "backup", "--dir", str(backup_dir)])
    capsys.readouterr()  # discard the first run's own output

    _backup_cmd(monkeypatch, tmp_path, ["--db", str(db_path), "backup", "--dir", str(backup_dir)])

    out = capsys.readouterr().out
    assert "nothing to do (--force to run anyway)" in out
    assert f"Current:   {backup_dir / (db_path.name + '.backup')}" in out


def test_backup_command_busy_branch_prints_and_returns_zero(tmp_path, monkeypatch, capsys):
    """Exit 0 even with --force: a held claim is the one case --force does
    not override (plan's failure-mode table)."""
    db_path, conn = _make_db(tmp_path, rows=1)
    now = backup_run._now_iso()
    conn.execute(
        "INSERT INTO backup_state (id, running_since, running_pid, updated_at) "
        "VALUES (1, ?, 424242, ?)",
        (now, now),
    )
    conn.close()
    backup_dir = tmp_path / "backups"

    _backup_cmd(
        monkeypatch, tmp_path,
        ["--db", str(db_path), "backup", "--dir", str(backup_dir), "--force"],
    )  # must not raise SystemExit

    out = capsys.readouterr().out
    assert "pid 424242) is still running; nothing to do." in out


def test_backup_command_exits_non_zero_and_names_the_untouched_backup_on_failure(
    tmp_path, monkeypatch, capsys
):
    db_path, conn = _make_db(tmp_path, rows=1)
    conn.close()
    backup_dir = tmp_path / "backups"

    _backup_cmd(monkeypatch, tmp_path, ["--db", str(db_path), "backup", "--dir", str(backup_dir)])
    capsys.readouterr()

    monkeypatch.setattr(
        backup_run.shutil, "disk_usage",
        lambda path: SimpleNamespace(total=0, used=0, free=1),
    )

    with pytest.raises(SystemExit) as excinfo:
        _backup_cmd(
            monkeypatch, tmp_path,
            ["--db", str(db_path), "backup", "--dir", str(backup_dir), "--force"],
        )

    message = str(excinfo.value.code)
    assert "Backup failed:" in message
    assert "untouched" in message


def test_backup_command_exits_with_a_message_when_the_database_is_missing(tmp_path, monkeypatch):
    missing = tmp_path / "does-not-exist.db"

    with pytest.raises(SystemExit) as excinfo:
        _backup_cmd(monkeypatch, tmp_path, ["--db", str(missing), "backup"])

    assert "No database at" in str(excinfo.value.code)


def test_backup_command_rejects_keep_zero_at_the_argparse_level(capsys):
    parser = cli_module.build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["backup", "--keep", "0"])

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "must be at least 1" in err


# --- cli.py: cmd_config's backup display block ------------------------------


def _isolate_credentials(monkeypatch) -> None:
    """cmd_config's output also carries the Claude/TopDeck/MTGO blocks above
    the backup one; clearing these keeps a test from depending on whatever
    the shell running the suite happens to have exported."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)


def _run_config(monkeypatch, tmp_path: Path, db_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    _isolate_credentials(monkeypatch)
    parser = cli_module.build_parser()
    args = parser.parse_args(["--db", str(db_path), "config"])
    args.func(args)


def test_config_with_no_flags_never_creates_the_database_it_reports_on(
    tmp_path, monkeypatch, capsys
):
    """The backup block reads through a read-only URI connection specifically
    so this holds: a plain sqlite3.connect on a missing path creates it, and
    an empty database renders identically to "no games yet"
    (docs/conventions.md) -- so with no database at all, nothing is opened
    and nothing is guessed about "Last". It still says so out loud, rather
    than printing a destination with silence under it: the same doc calls for
    an explicit empty state over printing nothing."""
    db_path = tmp_path / "does-not-exist.db"

    _run_config(monkeypatch, tmp_path, db_path)

    assert not db_path.exists()
    out = capsys.readouterr().out
    assert "Backup destination:" in out
    assert f"Last:   no database at {db_path} yet" in out


def test_config_shows_never_backed_up_when_no_backup_row_exists_yet(
    tmp_path, monkeypatch, capsys
):
    db_path, conn = _make_db(tmp_path, rows=0)
    conn.close()

    _run_config(monkeypatch, tmp_path, db_path)

    out = capsys.readouterr().out
    assert "Last:   never — run 'sensei-top backup', or leave 'serve' running" in out


def test_config_shows_the_last_successful_backups_age_and_path(tmp_path, monkeypatch, capsys):
    db_path, conn = _make_db(tmp_path, rows=1)
    cfg = _cfg(tmp_path)
    result = backup_run.run_backup(conn, db_path, cfg=cfg)
    assert result.status == "ok"
    conn.close()

    _run_config(monkeypatch, tmp_path, db_path)

    out = capsys.readouterr().out
    assert f"{result.bytes:,} bytes at {result.path}" in out
    assert "FAILED" not in out


def test_config_shows_a_failed_attempt_more_recent_than_the_last_success(
    tmp_path, monkeypatch, capsys
):
    db_path, conn = _make_db(tmp_path, rows=1)
    cfg = _cfg(tmp_path)
    result = backup_run.run_backup(conn, db_path, cfg=cfg)
    assert result.status == "ok"
    # A few seconds after the success, not just _now_iso() again: both
    # columns share one-second resolution, so a same-second write would
    # compare equal rather than greater under the plain string comparison
    # cmd_config uses to decide which is newer.
    later = (datetime.now(UTC) + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE backup_state SET last_error = ?, last_error_at = ? WHERE id = 1",
        ("No space left on device", later),
    )
    conn.close()

    _run_config(monkeypatch, tmp_path, db_path)

    out = capsys.readouterr().out
    assert f"{result.bytes:,} bytes" in out
    assert "most recent attempt FAILED" in out
    assert "No space left on device" in out


def test_config_shows_never_succeeded_with_a_failed_attempt(tmp_path, monkeypatch, capsys):
    db_path, conn = _make_db(tmp_path, rows=1)
    now = backup_run._now_iso()
    conn.execute(
        "INSERT INTO backup_state (id, last_error, last_error_at, updated_at) "
        "VALUES (1, 'disk full', ?, ?)",
        (now, now),
    )
    conn.close()

    _run_config(monkeypatch, tmp_path, db_path)

    out = capsys.readouterr().out
    assert "Last:   never — most recent attempt FAILED" in out
    assert "disk full" in out
