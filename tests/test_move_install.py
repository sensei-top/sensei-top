"""scripts/move_install.py, on temporary directories holding real SQLite files
in WAL mode.

Every test builds its paths by hand (``InstallPaths``), so none depends on the
working directory or on this machine's ``XDG_CONFIG_HOME``; the one test of
the command line's own resolution points both at ``tmp_path``. The old names
are neutral stand-ins (``old.db``, ``old-app``, ``OLD_APP``): the script
takes the real ones as arguments only, so no old spelling enters a tracked
file. Expectations come from what each test wrote into its own database, never
from a run of the script.

A connection held by another process is a real child process, not a second
connection in this one: SQLite tracks its own connections per process, so only
a separate process reproduces what a running ``serve`` looks like from here.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import io
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "move_install.py"

ROWS = 7
VERSION = 45
CONFIG_MARKER = "QzxMoveInstallSecretMarker"
ENV_MARKER = "QzxMoveInstallEnvValue"
CONFIG_MODE = 0o600
IN_USE_NOTE = (
    "  The in-use check sees only a process that holds the database open at that\n"
    "  moment. Stop 'sensei-top serve' before --apply even when the check passes.\n"
)
# The exit codes the script documents: 0 moved (or a clean dry run), 3
# refused with nothing moved, 4 failed. 1 and 2 belong to Python and argparse.
EXIT_OK = 0
EXIT_REFUSED = 3
EXIT_FAILED = 4


@pytest.fixture(scope="module")
def mi():
    spec = importlib.util.spec_from_file_location("move_install_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["move_install_under_test"] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("move_install_under_test", None)


def _make_db(path: Path, rows: int = ROWS, version: int = VERSION) -> None:
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("CREATE TABLE raw_events (id INTEGER PRIMARY KEY, payload TEXT)")
        conn.execute("INSERT INTO schema_version (version) VALUES (1), (?)", (version,))
        for i in range(rows):
            conn.execute("INSERT INTO raw_events (payload) VALUES (?)", (f"event {i}",))
    finally:
        conn.close()


def _install(tmp_path: Path, mi, *, config: bool = True):
    """An old install under stand-in names: a database with backup slots
    beside it and a config directory holding a marker file."""
    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)
    config_root = tmp_path / "xdg"
    config_root.mkdir()
    old_db = data / "old.db"
    _make_db(old_db)
    if config:
        old_config = config_root / "old-app"
        old_config.mkdir()
        config_file = old_config / "config.toml"
        config_file.write_text(f'[llm]\napi_key = "{CONFIG_MARKER}"\n')
        config_file.chmod(CONFIG_MODE)
    paths = mi.InstallPaths(
        old_db=old_db,
        new_db=data / "new.db",
        old_config_dir=config_root / "old-app",
        new_config_dir=config_root / "new-app",
        old_backup_dir=backups,
        new_backup_dir=backups,
        backup_dir_source="default",
        env_prefix="OLD_APP",
    )
    return paths


def _run(mi, paths, *, apply: bool, environ: dict[str, str] | None = None) -> tuple[int, str]:
    out = io.StringIO()
    code = mi.run(paths, apply=apply, environ=environ or {}, out=out)
    return code, out.getvalue()


def _tree(root: Path) -> dict[str, tuple]:
    """Every entry under ``root`` with its mode, size, mtime and content hash:
    equal snapshots mean nothing on disk changed."""
    snapshot: dict[str, tuple] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            full = Path(dirpath) / name
            st = os.lstat(full)
            digest = hashlib.sha256(full.read_bytes()).hexdigest() if full.is_file() else None
            snapshot[str(full.relative_to(root))] = (st.st_mode, st.st_size, st.st_mtime_ns, digest)
    return snapshot


def _leave_side_files(db: Path) -> None:
    """What a read-only reader that has exited leaves: SQLite creates ``-wal``
    and ``-shm`` for it and cannot remove them on close."""
    conn = sqlite3.connect(Path(db).absolute().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()
    finally:
        conn.close()
    assert (db.parent / f"{db.name}-wal").exists()
    assert (db.parent / f"{db.name}-shm").exists()


def _figures_of(db: Path) -> tuple[int, int]:
    conn = sqlite3.connect(Path(db).absolute().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        return (
            conn.execute("SELECT MAX(rowid) FROM raw_events").fetchone()[0],
            conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0],
        )
    finally:
        conn.close()


def _assert_nothing_moved(paths) -> None:
    assert paths.old_db.is_file()
    assert not paths.new_db.exists()
    assert paths.old_config_dir.is_dir()
    assert not paths.new_config_dir.exists()


@pytest.mark.parametrize("side_files", [False, True], ids=["clean", "left-by-a-reader"])
def test_dry_run_changes_nothing(tmp_path, mi, side_files):
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    if side_files:
        _leave_side_files(paths.old_db)
    before = _tree(tmp_path)

    code, out = _run(mi, paths, apply=False)

    assert code == EXIT_OK
    assert _tree(tmp_path) == before
    assert "DRY RUN" in out
    assert "Would refuse: nothing." in out
    assert str(paths.new_db) in out
    assert str(paths.new_config_dir) in out
    assert f"schema_version {VERSION}" in out
    assert f"highest raw_events rowid {ROWS}" in out
    assert IN_USE_NOTE in out


def test_apply_moves_the_database_config_and_slots(tmp_path, mi):
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    (paths.old_backup_dir / "old.db.backup.1").write_bytes(b"slot 1")

    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_OK, out
    assert not paths.old_db.exists()
    assert _figures_of(paths.new_db) == (ROWS, VERSION)
    assert not paths.old_config_dir.exists()
    assert (paths.new_config_dir / "config.toml").is_file()
    assert (paths.old_backup_dir / "new.db.backup").read_bytes() == b"slot 0"
    assert (paths.old_backup_dir / "new.db.backup.1").read_bytes() == b"slot 1"
    assert not (paths.old_backup_dir / "old.db.backup").exists()
    assert "The figures match." in out
    assert IN_USE_NOTE in out
    for db in (paths.old_db, paths.new_db):
        for suffix in ("-wal", "-shm"):
            assert not (db.parent / f"{db.name}{suffix}").exists()


def test_config_file_bytes_and_mode_survive_the_move(tmp_path, mi):
    paths = _install(tmp_path, mi)
    old_file = paths.old_config_dir / "config.toml"
    content = old_file.read_bytes()
    mode = os.stat(old_file).st_mode

    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_OK, out
    new_file = paths.new_config_dir / "config.toml"
    assert new_file.read_bytes() == content
    assert os.stat(new_file).st_mode == mode
    if sys.platform != "win32":  # POSIX permission bits; Windows uses ACLs
        assert mode & 0o777 == CONFIG_MODE


@pytest.mark.parametrize(
    "target",
    ["new.db", "new.db-wal", "new.db-shm", "new-app", "new.db.backup"],
)
def test_each_existing_target_refuses_and_nothing_moves(tmp_path, mi, target):
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    existing = {
        "new.db": paths.new_db,
        "new.db-wal": paths.new_db.parent / "new.db-wal",
        "new.db-shm": paths.new_db.parent / "new.db-shm",
        "new-app": paths.new_config_dir,
        "new.db.backup": paths.new_backup_dir / "new.db.backup",
    }[target]
    if target == "new-app":
        existing.mkdir()
    else:
        existing.write_bytes(b"already here")
    before = _tree(tmp_path)

    for apply in (False, True):
        code, out = _run(mi, paths, apply=apply)
        assert code == EXIT_REFUSED
        assert f"{existing} already exists" in out
        assert _tree(tmp_path) == before


def _hold_open(db: Path, *, in_transaction: bool) -> subprocess.Popen:
    """Another process holding the database, the way a running server does:
    idle between queries, or inside a read transaction."""
    code = (
        "import sqlite3, sys\n"
        f"conn = sqlite3.connect({str(db)!r}, isolation_level=None)\n"
        "conn.execute('INSERT INTO raw_events (payload) VALUES (\\'held\\')')\n"
        + ("conn.execute('BEGIN')\n" if in_transaction else "")
        + "conn.execute('SELECT COUNT(*) FROM raw_events').fetchone()\n"
        "print('ready', flush=True)\n"
        "sys.stdin.read()\n"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    assert holder.stdout.readline().strip() == "ready"
    return holder


@pytest.mark.parametrize("in_transaction", [False, True], ids=["idle", "reading"])
def test_a_second_connection_refuses_and_nothing_moves(tmp_path, mi, in_transaction):
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    holder = _hold_open(paths.old_db, in_transaction=in_transaction)
    try:
        code, out = _run(mi, paths, apply=True)
    finally:
        holder.stdin.close()
        holder.wait(timeout=10)

    assert code == EXIT_REFUSED
    assert "Refusing, nothing moved:" in out
    assert "Stop 'sensei-top serve'" in out
    _assert_nothing_moved(paths)
    assert (paths.old_backup_dir / "old.db.backup").exists()
    assert not (paths.new_backup_dir / "new.db.backup").exists()


def test_side_files_left_by_an_exited_reader_are_cleared_and_the_move_proceeds(tmp_path, mi):
    paths = _install(tmp_path, mi)
    _leave_side_files(paths.old_db)

    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_OK, out
    assert "no side file remains" in out
    assert _figures_of(paths.new_db) == (ROWS, VERSION)
    for db in (paths.old_db, paths.new_db):
        for suffix in ("-wal", "-shm"):
            assert not (db.parent / f"{db.name}{suffix}").exists()


def test_frames_left_in_the_wal_skip_the_dry_run_figures_and_count_on_apply(tmp_path, mi):
    """A writer killed before it checkpointed leaves committed rows only in
    the ``-wal``, where an immutable read cannot see them."""
    paths = _install(tmp_path, mi)
    extra = 3
    code = (
        "import sqlite3, sys\n"
        f"conn = sqlite3.connect({str(paths.old_db)!r}, isolation_level=None)\n"
        "conn.execute('PRAGMA wal_autocheckpoint=0')\n"
        f"for _ in range({extra}):\n"
        "    conn.execute('INSERT INTO raw_events (payload) VALUES (\\'late\\')')\n"
        "print('ready', flush=True)\n"
        "sys.stdin.read()\n"
    )
    writer = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    assert writer.stdout.readline().strip() == "ready"
    writer.kill()
    writer.wait(timeout=10)
    assert (paths.old_db.parent / "old.db-wal").stat().st_size > 0
    before = _tree(tmp_path)

    code, out = _run(mi, paths, apply=False)
    assert code == EXIT_OK
    assert "Figures: skipped." in out
    assert "highest raw_events rowid" not in out
    assert _tree(tmp_path) == before

    code, out = _run(mi, paths, apply=True)
    assert code == EXIT_OK, out
    assert f"highest raw_events rowid {ROWS + extra}" in out
    assert _figures_of(paths.new_db) == (ROWS + extra, VERSION)


def test_slots_move_by_exact_name_only(tmp_path, mi):
    paths = _install(tmp_path, mi)
    backups = paths.old_backup_dir
    slots = ["old.db.backup", "old.db.backup.1", "old.db.backup.2"]
    strangers = [
        "other.db.backup",
        "old.db.backup.keepme",
        "old.db.backup.01",
        "old.db.backup.0",
        "old.db.backup.tmp.123",
        "xold.db.backup",
    ]
    for name in slots + strangers:
        (backups / name).write_bytes(name.encode())

    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_OK, out
    assert "3 found" in out
    for name in slots:
        assert not (backups / name).exists()
        renamed = backups / name.replace("old.db", "new.db", 1)
        assert renamed.read_bytes() == name.encode()
    for name in strangers:
        assert (backups / name).read_bytes() == name.encode()


def test_an_absent_config_directory_is_a_skip(tmp_path, mi):
    paths = _install(tmp_path, mi, config=False)

    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_OK, out
    assert f"skipped: {paths.old_config_dir} does not exist" in out
    assert _figures_of(paths.new_db) == (ROWS, VERSION)
    assert not paths.new_config_dir.exists()


def test_the_config_file_never_reaches_the_output(tmp_path, mi):
    paths = _install(tmp_path, mi)
    _, dry = _run(mi, paths, apply=False)
    _, applied = _run(mi, paths, apply=True)
    assert CONFIG_MARKER not in dry
    assert CONFIG_MARKER not in applied
    assert "config.toml" not in dry + applied


def test_old_environment_variables_are_named_never_valued(tmp_path, mi):
    paths = _install(tmp_path, mi)
    environ = {
        "OLD_APP_BACKUP_DIR": ENV_MARKER,
        "OLD_APP_BACKUP_KEEP": ENV_MARKER,
        "UNRELATED": ENV_MARKER,
    }

    for apply in (False, True):
        code, out = _run(mi, paths, apply=apply, environ=environ)
        assert code == EXIT_OK, out
        assert "OLD_APP_BACKUP_DIR" in out
        assert "OLD_APP_BACKUP_KEEP" in out
        assert "UNRELATED" not in out
        assert ENV_MARKER not in out
        assert "localStorage" in out
        assert "backup_state.last_path" in out


def test_a_prefix_matching_a_name_still_read_says_to_leave_it(tmp_path, mi):
    """``MTGA_LOG`` names Arena's own log and kept its spelling in the rename,
    so an old prefix that also matches it must not tell the
    user to rename it."""
    paths = dataclasses.replace(_install(tmp_path, mi), env_prefix="MTGA")
    code, out = _run(mi, paths, apply=False, environ={"MTGA_LOG": ENV_MARKER})
    assert code == EXIT_OK
    assert "MTGA_LOG matches the old prefix but is still read under that name" in out
    assert "No environment variable with the old prefix is set here." in out
    assert ENV_MARKER not in out


def test_a_failed_rename_puts_back_what_already_moved(tmp_path, mi, monkeypatch):
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    real_rename = os.rename

    def failing_rename(src, dst):
        if Path(src) == paths.old_config_dir:
            raise OSError("synthetic failure")
        real_rename(src, dst)

    monkeypatch.setattr(mi.os, "rename", failing_rename)
    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_FAILED
    assert "FAILED to move the config directory" in out
    assert "renamed back" in out
    _assert_nothing_moved(paths)
    assert (paths.old_backup_dir / "old.db.backup").read_bytes() == b"slot 0"
    assert not (paths.new_backup_dir / "new.db.backup").exists()
    assert _figures_of(paths.old_db) == (ROWS, VERSION)


def test_the_command_line_resolves_new_paths_from_the_package(tmp_path, mi, monkeypatch):
    """The new config directory and database are the product's own:
    ``sensei-top`` under the config root, ``data/sensei-top.db`` under the
    working directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)

    paths = mi.resolve_paths(
        old_db="data/old.db", old_config_dir="old-app", env_prefix="OLD_APP", backup_dir=None
    )

    assert paths.new_config_dir == tmp_path / "xdg" / "sensei-top"
    assert paths.old_config_dir == tmp_path / "xdg" / "old-app"
    assert paths.new_db == tmp_path / "data" / "sensei-top.db"
    assert paths.old_db == tmp_path / "data" / "old.db"
    assert paths.old_backup_dir == tmp_path / "data" / "backups"
    assert paths.backup_dir_source == "default"

    flagged = mi.resolve_paths(
        old_db="data/old.db", old_config_dir="old-app", env_prefix="OLD_APP",
        backup_dir=str(tmp_path / "elsewhere"),
    )
    assert flagged.old_backup_dir == flagged.new_backup_dir == tmp_path / "elsewhere"
    assert flagged.backup_dir_source == "flag"


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "../old-app"])
def test_the_old_config_directory_is_a_name_not_a_path(mi, name):
    with pytest.raises(ValueError, match="directory name"):
        mi.resolve_paths(old_db="old.db", old_config_dir=name, env_prefix="X", backup_dir=None)


def _rename_hook(mi, monkeypatch, before_rename):
    """Routes every ``os.rename`` through ``before_rename(src, dst)`` first,
    so a test can act at one precise point between the script's renames."""
    real_rename = os.rename

    def hooked(src, dst):
        before_rename(Path(src), Path(dst))
        real_rename(src, dst)

    monkeypatch.setattr(mi.os, "rename", hooked)


def test_a_process_opening_the_database_after_the_check_refuses_before_its_rename(
    tmp_path, mi, monkeypatch
):
    """A real process opens the database between the checkpoint-and-close
    check and the database's own rename: its side files appear beside the old
    name, and the script refuses with nothing moved: it never moves a
    database another process holds."""
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    holders: list[subprocess.Popen] = []
    real_figures = mi._figures

    def figures_then_open(db):
        result = real_figures(db)
        if db == paths.old_db and not holders:
            holders.append(_hold_open(paths.old_db, in_transaction=False))
        return result

    monkeypatch.setattr(mi, "_figures", figures_then_open)
    try:
        code, out = _run(mi, paths, apply=True)
    finally:
        for holder in holders:
            holder.stdin.close()
            holder.wait(timeout=10)

    assert holders
    assert code == EXIT_REFUSED
    assert "Refusing, nothing moved:\n" in out
    assert (
        f"  - old.db-wal and old.db-shm appeared beside {paths.old_db} after the checkpoint: "
        "another process\n    opened the database. Stop it, then run again.\n"
    ) in out
    _assert_nothing_moved(paths)
    assert (paths.old_backup_dir / "old.db.backup").read_bytes() == b"slot 0"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows refuses to rename a database another process holds open, so the "
    "script stops before moving anything and the race cannot be built",
)
def test_a_process_opening_the_database_during_the_move_renames_everything_back(
    tmp_path, mi, monkeypatch
):
    """The reviewer's race: a writer opens the database after the last check
    but before the database's rename, so its committed row lands in a -wal
    beside the old name. Renaming everything back puts the database beside
    the side files that belong to it, and the row survives there."""
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    holders: list[subprocess.Popen] = []

    def open_before_database_rename(src, dst):
        if src == paths.old_db and not holders:
            holders.append(_hold_open(paths.old_db, in_transaction=False))

    _rename_hook(mi, monkeypatch, open_before_database_rename)
    try:
        code, out = _run(mi, paths, apply=True)
    finally:
        for holder in holders:
            holder.stdin.close()
            holder.wait(timeout=10)

    assert holders
    assert code == EXIT_FAILED
    assert (
        f"FAILED: old.db-wal and old.db-shm appeared beside {paths.old_db} during the move: "
        "another process\nopened the database. Everything is renamed back, so the database sits\n"
        "beside its side files again. Stop that process, then run again.\n"
    ) in out
    assert "The figures match." not in out
    _assert_nothing_moved(paths)
    assert (paths.old_backup_dir / "old.db.backup").read_bytes() == b"slot 0"
    assert not (paths.new_backup_dir / "new.db.backup").exists()
    # The holder inserted one row before idling; its close checkpointed it home.
    assert _figures_of(paths.old_db) == (ROWS + 1, VERSION)


def test_a_roll_back_never_overwrites_an_occupied_old_path(tmp_path, mi, monkeypatch):
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    real_rename = os.rename

    def occupy_then_fail(src, dst):
        if Path(src) == paths.old_config_dir:
            paths.old_db.write_bytes(b"occupier")
            raise OSError("synthetic failure")
        real_rename(src, dst)

    monkeypatch.setattr(mi.os, "rename", occupy_then_fail)
    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_FAILED
    assert (
        f"  NOT renamed back: {paths.old_db} is occupied, so the database stays at "
        f"{paths.new_db}.\n  Nothing was overwritten. Both paths need a look by hand.\n"
    ) in out
    assert paths.old_db.read_bytes() == b"occupier"
    assert _figures_of(paths.new_db) == (ROWS, VERSION)
    assert (paths.old_backup_dir / "old.db.backup").read_bytes() == b"slot 0"
    assert not (paths.new_backup_dir / "new.db.backup").exists()
    assert paths.old_config_dir.is_dir()
    assert not paths.new_config_dir.exists()


class _FailingOut(io.StringIO):
    """A stream that breaks like a closed pipe from the first line holding
    ``from_text`` onwards."""

    def __init__(self, *, from_text: str) -> None:
        super().__init__()
        self._from_text = from_text
        self._broken = False

    def write(self, text: str) -> int:
        if self._broken or self._from_text in text:
            self._broken = True
            raise BrokenPipeError("synthetic closed pipe")
        return super().write(text)


def _assert_everything_moved(paths) -> None:
    assert not paths.old_db.exists()
    assert _figures_of(paths.new_db) == (ROWS, VERSION)
    assert not paths.old_config_dir.exists()
    assert paths.new_config_dir.is_dir()
    assert not (paths.old_backup_dir / "old.db.backup").exists()
    assert (paths.new_backup_dir / "new.db.backup").read_bytes() == b"slot 0"


def test_an_output_that_breaks_after_a_whole_move_still_returns_success(tmp_path, mi, capsys):
    """The exit code describes the files, not the output: a whole move with
    matching figures is a success even when stdout closed on its first
    report line, and the lines it could not write reach stderr."""
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")

    code = mi.run(paths, apply=True, environ={}, out=_FailingOut(from_text="Moved the"))

    assert code == EXIT_OK
    _assert_everything_moved(paths)
    err = capsys.readouterr().err
    assert f"Moved the database: {paths.old_db} -> {paths.new_db}\n" in err
    assert "The figures match.\n" in err


def test_an_output_that_breaks_on_a_failure_still_renames_back_and_reports_it(
    tmp_path, mi, monkeypatch, capsys
):
    """stdout closes on the very line saying a rename failed: the roll-back
    still runs, its lines reach stderr, and the exit code is the failure."""
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    real_rename = os.rename

    def failing_rename(src, dst):
        if Path(src) == paths.old_config_dir:
            raise OSError("synthetic failure")
        real_rename(src, dst)

    monkeypatch.setattr(mi.os, "rename", failing_rename)
    code = mi.run(paths, apply=True, environ={}, out=_FailingOut(from_text="FAILED to move"))

    assert code == EXIT_FAILED
    _assert_nothing_moved(paths)
    assert (paths.old_backup_dir / "old.db.backup").read_bytes() == b"slot 0"
    err = capsys.readouterr().err
    assert "FAILED to move the config directory" in err
    assert f"  renamed back: {paths.new_db} -> {paths.old_db}\n" in err


def test_an_interrupt_as_a_rename_returns_puts_that_move_back_too(tmp_path, mi, monkeypatch):
    """A move is recorded before its rename, so an interrupt that lands after
    the rename itself but before the script records anything still sees the
    roll-back take that file back."""
    paths = _install(tmp_path, mi)
    slot = paths.old_backup_dir / "old.db.backup"
    slot.write_bytes(b"slot 0")
    new_slot = paths.new_backup_dir / "new.db.backup"
    real_rename = os.rename

    def rename_then_interrupt(src, dst):
        real_rename(src, dst)
        if Path(src) == slot:
            raise KeyboardInterrupt

    monkeypatch.setattr(mi.os, "rename", rename_then_interrupt)
    out = io.StringIO()
    with pytest.raises(KeyboardInterrupt):
        mi.run(paths, apply=True, environ={}, out=out)

    _assert_nothing_moved(paths)
    assert slot.read_bytes() == b"slot 0"
    assert not new_slot.exists()
    assert f"  renamed back: {new_slot} -> {slot}\n" in out.getvalue()
    assert _figures_of(paths.old_db) == (ROWS, VERSION)


def _create_and_hold(db: Path) -> subprocess.Popen:
    """Another process creating a fresh WAL database at ``db`` and holding it
    open, the way a server started under the old name would."""
    code = (
        "import sqlite3, sys\n"
        f"conn = sqlite3.connect({str(db)!r}, isolation_level=None)\n"
        "conn.execute('PRAGMA journal_mode=WAL')\n"
        "conn.execute('CREATE TABLE stray (x INTEGER)')\n"
        "conn.execute('INSERT INTO stray (x) VALUES (1)')\n"
        "print('ready', flush=True)\n"
        "sys.stdin.read()\n"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    assert holder.stdout.readline().strip() == "ready"
    return holder


def test_a_new_database_at_the_old_path_during_the_move_renames_nothing_back(
    tmp_path, mi, monkeypatch
):
    """A process creates a database under the old name once the real one has
    moved. The install moved whole, so nothing goes back, and the stray file
    is left for a look by hand; the figures are still read and compared, and
    the exit is the failure whatever they say."""
    paths = _install(tmp_path, mi)
    slot = paths.old_backup_dir / "old.db.backup"
    slot.write_bytes(b"slot 0")
    holders: list[subprocess.Popen] = []

    def create_after_the_database(src, dst):
        if src == slot and not holders:
            holders.append(_create_and_hold(paths.old_db))

    _rename_hook(mi, monkeypatch, create_after_the_database)
    try:
        code, out = _run(mi, paths, apply=True)
    finally:
        for holder in holders:
            holder.stdin.close()
            holder.wait(timeout=10)

    assert holders
    assert code == EXIT_FAILED
    assert (
        f"FAILED: old.db-wal and old.db-shm and a new file at {paths.old_db} appeared during "
        "the move: another\n"
        "process created a database under the old name. Nothing was renamed back:\n"
        "the install moved whole, and the file at the old path is not part of it.\n"
        f"Stop that process, then look at {paths.old_db} by hand before deleting it.\n"
    ) in out
    assert "After:  " in out
    assert "The figures match.\n" in out
    assert "  renamed back: " not in out
    assert _figures_of(paths.new_db) == (ROWS, VERSION)
    assert not paths.old_config_dir.exists()
    assert paths.new_config_dir.is_dir()
    assert not slot.exists()
    assert (paths.new_backup_dir / "new.db.backup").read_bytes() == b"slot 0"
    stray_uri = Path(paths.old_db).absolute().as_uri() + "?mode=ro&immutable=1"
    stray = sqlite3.connect(stray_uri, uri=True)
    try:
        tables = {r[0] for r in stray.execute("SELECT name FROM sqlite_master")}
    finally:
        stray.close()
    assert tables == {"stray"}


def test_same_filesystem_tells_two_real_filesystems_apart(tmp_path, mi):
    """The device comparison behind the cross-filesystem refusal, on two real
    filesystems rather than a stub."""
    shm = Path("/dev/shm")
    if not shm.is_dir():
        pytest.skip("no /dev/shm on this machine to stand for a second filesystem")
    if shm.stat().st_dev == tmp_path.stat().st_dev:
        pytest.skip("/dev/shm and tmp_path share one filesystem here")
    src = tmp_path / "old.db"
    src.write_bytes(b"x")

    assert mi._same_filesystem(src, tmp_path)
    assert not mi._same_filesystem(src, shm)


def test_an_interrupt_mid_move_renames_everything_back(tmp_path, mi, monkeypatch):
    paths = _install(tmp_path, mi)
    slot = paths.old_backup_dir / "old.db.backup"
    slot.write_bytes(b"slot 0")

    def interrupt_on_the_slot(src, dst):
        if src == slot:
            raise KeyboardInterrupt

    _rename_hook(mi, monkeypatch, interrupt_on_the_slot)
    with pytest.raises(KeyboardInterrupt):
        _run(mi, paths, apply=True)

    _assert_nothing_moved(paths)
    assert slot.read_bytes() == b"slot 0"
    assert not (paths.new_backup_dir / "new.db.backup").exists()
    assert _figures_of(paths.old_db) == (ROWS, VERSION)


def test_a_figure_mismatch_after_the_move_fails_and_leaves_the_files_moved(
    tmp_path, mi, monkeypatch
):
    """Any difference between the before and after figures is a failure,
    and a mismatch rolls nothing back."""
    paths = _install(tmp_path, mi)
    (paths.old_backup_dir / "old.db.backup").write_bytes(b"slot 0")
    real_figures = mi._figures

    def short_after_the_move(db):
        result = real_figures(db)
        if db == paths.new_db:
            return dataclasses.replace(result, max_raw_event=result.max_raw_event - 1)
        return result

    monkeypatch.setattr(mi, "_figures", short_after_the_move)
    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_FAILED
    assert (
        "FAILED: the figures read through the new path differ from those read before the move.\n"
        "Every file has moved and nothing was renamed back. Do not start the app\n"
        "before the Before and After lines above are explained.\n"
    ) in out
    assert "The figures match." not in out
    _assert_everything_moved(paths)


def test_a_target_that_appears_during_the_move_is_never_overwritten(tmp_path, mi, monkeypatch):
    """``os.rename`` replaces an existing file without asking, so each target
    is checked again just before its own rename."""
    paths = _install(tmp_path, mi)
    slot = paths.old_backup_dir / "old.db.backup"
    slot.write_bytes(b"slot 0")
    new_slot = paths.new_backup_dir / "new.db.backup"

    def appear_after_the_database(src, dst):
        if src == slot:
            return
        if src == paths.old_db:
            new_slot.write_bytes(b"appeared")

    _rename_hook(mi, monkeypatch, appear_after_the_database)
    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_FAILED
    assert f"{new_slot} appeared after the checks" in out
    assert new_slot.read_bytes() == b"appeared"
    assert slot.read_bytes() == b"slot 0"
    _assert_nothing_moved(paths)
    assert _figures_of(paths.old_db) == (ROWS, VERSION)


def test_slots_follow_the_database_to_its_new_directory(tmp_path, mi, monkeypatch):
    """Without --backup-dir, slots are looked for beside the old database and
    land beside the new one (``default_dir``), under the new database's name:
    ``data/sensei-top.db`` makes ``data/backups/sensei-top.db.backup``."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "backups").mkdir(parents=True)
    (tmp_path / "data" / "backups").mkdir(parents=True)
    _make_db(elsewhere / "old.db")
    (elsewhere / "backups" / "old.db.backup").write_bytes(b"slot 0")
    (elsewhere / "backups" / "old.db.backup.1").write_bytes(b"slot 1")

    paths = mi.resolve_paths(
        old_db=str(elsewhere / "old.db"), old_config_dir="old-app",
        env_prefix="OLD_APP", backup_dir=None,
    )
    code, out = _run(mi, paths, apply=True)

    assert code == EXIT_OK, out
    new_backups = tmp_path / "data" / "backups"
    assert (new_backups / "sensei-top.db.backup").read_bytes() == b"slot 0"
    assert (new_backups / "sensei-top.db.backup.1").read_bytes() == b"slot 1"
    assert list((elsewhere / "backups").iterdir()) == []
    assert _figures_of(tmp_path / "data" / "sensei-top.db") == (ROWS, VERSION)


def test_a_move_across_filesystems_refuses(tmp_path, mi, monkeypatch):
    """Every move must be a rename, so a pair on two filesystems refuses."""
    paths = _install(tmp_path, mi)
    monkeypatch.setattr(mi, "_same_filesystem", lambda src, directory: False)
    before = _tree(tmp_path)

    for apply in (False, True):
        code, out = _run(mi, paths, apply=apply)
        assert code == EXIT_REFUSED
        assert (
            f"{paths.old_db} and {paths.new_db.parent} are on different filesystems" in out
        )
        assert _tree(tmp_path) == before


def test_a_missing_database_refuses(tmp_path, mi):
    paths = dataclasses.replace(_install(tmp_path, mi), old_db=tmp_path / "data" / "absent.db")
    before = _tree(tmp_path)

    for apply in (False, True):
        code, out = _run(mi, paths, apply=apply)
        assert code == EXIT_REFUSED
        assert f"no database at {paths.old_db}" in out
        assert _tree(tmp_path) == before
