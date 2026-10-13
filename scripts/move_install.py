"""Move an existing install from the project's old names to its new ones.

A one-time script, not a product feature: the product itself has no fallback
to an old path, so an install made under the old names is invisible to it
until its database, backup slots and config directory carry the new ones.

    uv run python scripts/move_install.py --old-db PATH \\
        --old-config-dir NAME --old-env-prefix PREFIX [--backup-dir PATH] [--apply]

**The old names are arguments**, never literals in this file, so no old
spelling enters a tracked file. The new names come from the package itself
(``llm.config.config_path()``, ``cli.DEFAULT_DB``, ``backup.config``'s
``default_dir`` and ``slot_path``), so this script cannot disagree with the
product about where anything lives. ``DEFAULT_DB`` is relative to the working
directory, exactly as in the product, and every path is printed absolute so a
dry run shows what it resolved.

**Dry run by default.** It prints every move with its size and every reason it
would refuse, and changes nothing on disk, side files included. That rules out
a plain ``mode=ro`` connection: SQLite creates a ``-wal`` and a 32 KB ``-shm``
for one and cannot remove them on close. The dry run reads the before figures
through ``immutable=1``, which creates nothing but ignores a WAL's content, so
it reads them only when there is no ``-wal`` or it is empty; a non-empty
``-wal`` means the figures are skipped and the output says why.

Exit codes: 0 moved, or a dry run that would refuse nothing; 3 refused,
nothing moved; 4 failed, read the output. 1 and 2 are left to Python
(an uncaught exception) and to argparse (a usage error).

**Traps this script exists to avoid:**

1. A database still open elsewhere. ``--apply`` runs
   ``PRAGMA wal_checkpoint(TRUNCATE)``, refuses if it reports busy, and closes.
   SQLite removes ``-wal`` and ``-shm`` when the *last* connection closes, so
   either file still being there afterwards means another process holds the
   database: refuse. Side files left by a reader that has exited are a normal
   state, which the checkpoint and close clear. A process can still open the
   database after that check, so the side files are looked for again just
   before the database's rename (refuse, nothing moved) and after the last
   rename (rename everything back: the database belongs beside them). If a
   new file sits at the old database path by then, nothing goes back: the
   install moved whole, and that file is not part of it.
2. A merge or an overwrite. Every target is checked absent before anything
   moves, and again immediately before its own rename, since ``os.rename``
   replaces an existing file without asking.
3. A copy dressed up as a move. Every pair must share a filesystem, so every
   move is an ``os.rename``; if one fails after another succeeded, the ones
   done are renamed back.
4. A glob eating somebody else's file. A backup slot moves only if its name
   is byte-for-byte what ``slot_path`` builds for the old database, the same
   rule ``backup/run.py``'s pruning follows.
5. The backup directory's own config. The product's resolver reads
   ``[backup] dir`` from the config file, which at move time still sits under
   the old directory name, where the resolver cannot see it. So this script
   never calls ``resolve``: it looks in ``--backup-dir``, else in the default
   beside the old database, and says which.
6. The API key. The config file is never opened, read or printed; renaming
   its directory keeps its bytes and mode bits.

The script writes nothing into the database, so ``backup_state.last_path``
keeps naming the old slot path until the next backup. Nothing opens that
path: ``sensei-top backup`` (when the last backup is fresh) and
``sensei-top config`` only print it.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from urllib.parse import quote

from sensei_top.backup.config import BACKUP_DIR_ENV, BackupConfig, default_dir, slot_path
from sensei_top.cli import DEFAULT_DB
from sensei_top.llm.config import config_path

SIDE_SUFFIXES = ("-wal", "-shm")
BUSY_TIMEOUT_S = 2.0

# Names the product still reads that an old prefix could also match: they name
# Arena's own log, not this project, so they kept their spelling in the rename.
STILL_READ_ENV = frozenset({"MTGA_LOG"})

EXIT_OK = 0
EXIT_REFUSED = 3
EXIT_FAILED = 4
EXIT_CODES = """\
Exit codes: 0 moved, or a dry run that would refuse nothing; 3 refused,
nothing moved; 4 failed, read the output. 1 and 2 are left to Python
(an uncaught exception) and to argparse (a usage error)."""

Say = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class InstallPaths:
    """Every path the move reads or writes, all absolute. The command line
    builds one from the package's own names; tests build one by hand."""

    old_db: Path
    new_db: Path
    old_config_dir: Path
    new_config_dir: Path
    old_backup_dir: Path
    new_backup_dir: Path
    backup_dir_source: str  # 'flag' | 'default'
    env_prefix: str


@dataclass(frozen=True, slots=True)
class Move:
    label: str
    src: Path
    dst: Path
    size: int


@dataclass(frozen=True, slots=True)
class Figures:
    size: int
    max_raw_event: int | None
    schema_version: int | None


@dataclass(slots=True)
class Survey:
    moves: list[Move]
    refusals: list[str]
    side_files: list[tuple[Path, int]]
    slots_found: int
    config_present: bool
    old_env: list[str]
    still_read_env: list[str]


def resolve_paths(
    *, old_db: str, old_config_dir: str, env_prefix: str, backup_dir: str | None
) -> InstallPaths:
    """The command line's paths: old ones from the arguments, new ones from
    the package. ``old_config_dir`` is a bare directory name, a sibling of the
    new config directory under the same config root."""
    name = old_config_dir
    if not name or name in (".", "..") or os.sep in name or (os.altsep and os.altsep in name):
        raise ValueError(f"--old-config-dir takes a directory name, not a path: {name!r}")
    new_config_dir = _absolute(config_path().parent)
    old = _absolute(Path(old_db).expanduser())
    new = _absolute(DEFAULT_DB)
    if backup_dir:
        directory = _absolute(Path(backup_dir).expanduser())
        old_backups, new_backups, source = directory, directory, "flag"
    else:
        old_backups, new_backups, source = default_dir(old), default_dir(new), "default"
    return InstallPaths(
        old_db=old,
        new_db=new,
        old_config_dir=new_config_dir.parent / name,
        new_config_dir=new_config_dir,
        old_backup_dir=old_backups,
        new_backup_dir=new_backups,
        backup_dir_source=source,
        env_prefix=env_prefix,
    )


def survey(paths: InstallPaths, environ: Mapping[str, str]) -> Survey:
    """Everything a dry run reports, from ``stat`` and directory listings
    alone. Opens no file."""
    result = Survey(
        moves=[], refusals=[], side_files=[], slots_found=0,
        config_present=False, old_env=[], still_read_env=[],
    )
    refuse = result.refusals.append

    old, new = paths.old_db, paths.new_db
    if not old.is_file():
        refuse(f"no database at {old}")
    elif old == new:
        refuse(f"the old and the new database are the same path: {old}")
    else:
        result.moves.append(Move("database", old, new, old.stat().st_size))
        _check_target(new, old, refuse)
    for suffix in SIDE_SUFFIXES:
        side = _side(new, suffix)
        if os.path.lexists(side):
            refuse(f"{side} already exists beside the new database")
        beside_old = _side(old, suffix)
        if beside_old.exists():
            result.side_files.append((beside_old, beside_old.stat().st_size))

    for src, dst in _slots(paths):
        result.slots_found += 1
        result.moves.append(Move("backup slot", src, dst, src.stat().st_size))
        _check_target(dst, src, refuse)

    cfg_old, cfg_new = paths.old_config_dir, paths.new_config_dir
    if os.path.lexists(cfg_old):
        result.config_present = True
        if not cfg_old.is_dir():
            refuse(f"{cfg_old} is not a directory")
        elif cfg_old == cfg_new:
            refuse(f"the old and the new config directory are the same path: {cfg_old}")
        else:
            result.moves.append(Move("config directory", cfg_old, cfg_new, _tree_bytes(cfg_old)))
            _check_target(cfg_new, cfg_old, refuse)

    prefix = paths.env_prefix
    if prefix:
        names = sorted(n for n in environ if n.startswith(prefix))
        result.old_env = [n for n in names if n not in STILL_READ_ENV]
        result.still_read_env = [n for n in names if n in STILL_READ_ENV]
    return result


def run(
    paths: InstallPaths,
    *,
    apply: bool,
    environ: Mapping[str, str],
    out: TextIO,
) -> int:
    """Survey, print, and (with ``apply``) move. Returns the exit code, which
    describes the files, never the output.

    Once the moves have started, a write to ``out`` that fails (a closed
    pipe) sends that line and every later one to stderr instead: the lines
    saying what moved and what went back are the ones that must not be lost.
    Before that point a failing write raises, and nothing has moved.
    """
    sink: list[TextIO | None] = [out]
    moves_started = False

    def say(line: str = "") -> None:
        while sink[0] is not None:
            try:
                print(line, file=sink[0], flush=True)
                return
            except (OSError, ValueError):
                if not moves_started:
                    raise
                sink[0] = sys.stderr if sink[0] is out else None

    found = survey(paths, environ)
    mode = "APPLY" if apply else "DRY RUN: nothing on disk changes; --apply acts"
    say(f"Moving the install to its new names ({mode})")
    say()
    _print_moves(paths, found, say)

    if not apply:
        unreadable = _print_dry_run_figures(paths.old_db, found, say)
        if unreadable:
            found.refusals.append(unreadable)
    say()
    if found.refusals:
        say("Refusing, nothing moved:" if apply else "Would refuse:")
        for reason in found.refusals:
            say(f"  - {reason}")
        say()
        _print_not_moved(found, apply=False, say=say)
        return EXIT_REFUSED
    if not apply:
        say("Would refuse: nothing.")
        say()
        _print_not_moved(found, apply=False, say=say)
        return EXIT_OK

    reason = _release(paths.old_db)
    before = None if reason else _figures(paths.old_db)
    if before is not None and not _complete(before):
        reason = _unreadable(paths.old_db)
    if reason is not None or before is None:
        say("Refusing, nothing moved:")
        say(f"  - {reason}")
        return EXIT_REFUSED
    say(f"Checkpointed and closed {paths.old_db}; no side file remains.")
    say(f"Before: {_describe(before)}")

    lines: list[str] = []
    moves_started = True
    try:
        outcome = _move_all(found.moves, paths.old_db, lines)
    except BaseException:
        for line in lines:
            say(line)
        raise
    for line in lines:
        say(line)
    if not outcome.moved_whole:
        return outcome.code if outcome.code is not None else EXIT_FAILED

    after = _figures(paths.new_db)
    say(f"After:  {_describe(after)}")
    if after != before:
        say(
            "FAILED: the figures read through the new path differ from those read "
            "before the move."
        )
        say("Every file has moved and nothing was renamed back. Do not start the app")
        say("before the Before and After lines above are explained.")
        return EXIT_FAILED
    say("The figures match.")
    if outcome.code is not None:
        return outcome.code
    say()
    _print_not_moved(found, apply=True, say=say)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Move an existing install from the project's old names to its new ones.",
        epilog=EXIT_CODES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--old-db", required=True, help="the database under its old name")
    parser.add_argument(
        "--old-config-dir", required=True,
        help="the old config directory's name, a sibling of the new one",
    )
    parser.add_argument(
        "--old-env-prefix", required=True,
        help="prefix of the old environment variables, to list any still set",
    )
    parser.add_argument(
        "--backup-dir",
        help="where the backup slots are, when a [backup] dir or the backup "
        "environment variable put them somewhere other than beside the old database",
    )
    parser.add_argument("--apply", action="store_true", help="move; without it, a dry run")
    args = parser.parse_args(argv)
    try:
        paths = resolve_paths(
            old_db=args.old_db,
            old_config_dir=args.old_config_dir,
            env_prefix=args.old_env_prefix,
            backup_dir=args.backup_dir,
        )
    except ValueError as exc:
        parser.error(str(exc))
    code = run(paths, apply=args.apply, environ=os.environ, out=sys.stdout)
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        # A closed stdout would fail again in the interpreter's own flush at
        # exit and replace ``code`` with 120; point it at /dev/null instead.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return code


def _absolute(path: Path) -> Path:
    """Absolute and normalised, symlinks left alone: renaming a symlink moves
    the link, which is what the product would find under the name."""
    return Path(os.path.abspath(path))


def _side(db: Path, suffix: str) -> Path:
    return db.with_name(db.name + suffix)


def _check_target(dst: Path, src: Path, refuse: Say) -> None:
    if os.path.lexists(dst):
        refuse(f"{dst} already exists (never a merge, never an overwrite)")
        return
    parent = dst.parent
    if not parent.is_dir():
        refuse(f"{parent} does not exist, so {src.name} cannot move into it")
        return
    if not _same_filesystem(src, parent):
        refuse(f"{src} and {parent} are on different filesystems, so the move would be a copy")


def _same_filesystem(src: Path, directory: Path) -> bool:
    return os.lstat(src).st_dev == directory.stat().st_dev


def _slots(paths: InstallPaths) -> list[tuple[Path, Path]]:
    """``(old slot, new slot)`` pairs, found by listing the directory and kept
    only when the name is exactly what ``slot_path`` builds for that index."""
    directory = paths.old_backup_dir
    if not directory.is_dir():
        return []
    old_cfg = BackupConfig(directory=directory, keep=1, dir_source="", keep_source="")
    new_cfg = BackupConfig(
        directory=paths.new_backup_dir, keep=1, dir_source="", keep_source=""
    )
    stem = slot_path(old_cfg, paths.old_db, 0).name
    pairs: list[tuple[Path, Path]] = []
    for candidate in sorted(directory.iterdir()):
        if candidate.name == stem:
            index = 0
        elif candidate.name.startswith(stem + "."):
            digits = candidate.name[len(stem) + 1 :]
            if not (digits.isascii() and digits.isdigit()):
                continue
            index = int(digits)
            if index == 0:
                continue
        else:
            continue
        if candidate != slot_path(old_cfg, paths.old_db, index) or not candidate.is_file():
            continue
        pairs.append((candidate, slot_path(new_cfg, paths.new_db, index)))
    return pairs


def _tree_bytes(directory: Path) -> int:
    """Total size from ``lstat`` alone: no file under the directory is opened."""
    total = 0
    for root, dirs, files in os.walk(directory):
        for name in dirs + files:
            total += os.lstat(os.path.join(root, name)).st_size
    return total


def _uri(db: Path, params: str) -> str:
    return f"file:{quote(str(db))}?{params}"


def _release(db: Path) -> str | None:
    """Checkpoint and close; ``None`` when nothing else holds the database,
    otherwise the reason to refuse."""
    try:
        conn = sqlite3.connect(
            _uri(db, "mode=rw"), uri=True, isolation_level=None, timeout=BUSY_TIMEOUT_S
        )
        try:
            busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return f"could not checkpoint {db}: {exc}"
    if busy:
        return (
            "the checkpoint reported busy: another connection is using the database. "
            "Stop 'sensei-top serve' and any 'ingest --watch', then run again."
        )
    left = _side_names(db)
    if left:
        return (
            f"{left} still there after the checkpoint and close: another "
            "process has the database open. Stop 'sensei-top serve' and any "
            "'ingest --watch', then run again."
        )
    return None


def _figures(db: Path) -> Figures:
    """Read through ``immutable=1``, which creates no side file. Exact only
    when no ``-wal`` holds frames: callers make sure of that first."""
    size = db.stat().st_size
    try:
        conn = sqlite3.connect(_uri(db, "mode=ro&immutable=1"), uri=True, isolation_level=None)
    except sqlite3.Error:
        return Figures(size, None, None)
    try:
        return Figures(
            size,
            _scalar(conn, "SELECT MAX(rowid) FROM raw_events"),
            _scalar(conn, "SELECT MAX(version) FROM schema_version"),
        )
    finally:
        conn.close()


def _scalar(conn: sqlite3.Connection, sql: str) -> int | None:
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else row[0]


def _describe(figures: Figures) -> str:
    rowid = "unreadable" if figures.max_raw_event is None else f"{figures.max_raw_event:,}"
    version = "unreadable" if figures.schema_version is None else str(figures.schema_version)
    return (
        f"{figures.size:,} bytes, highest raw_events rowid {rowid}, "
        f"schema_version {version}"
    )


@dataclass(frozen=True, slots=True)
class MoveOutcome:
    """``code`` is ``None`` when nothing went wrong; ``moved_whole`` says
    every file sits under its new name, so the figures can still be read."""

    code: int | None
    moved_whole: bool


def _move_all(moves: list[Move], old_db: Path, lines: list[str]) -> MoveOutcome:
    """Every rename or none; what happened goes into ``lines``.

    Nothing is printed here: a write to a closed pipe between two renames
    would leave the install half-moved, so the caller prints ``lines`` only
    once no rename is pending. Any exception, ``KeyboardInterrupt``
    included, renames back what already moved before it propagates. Each
    move is recorded *before* its rename, so an interrupt raised as a rename
    returns still leaves the roll-back knowing about it.
    """
    done: list[Move] = []
    try:
        for move in moves:
            if move.label == "database":
                # The database is always the first move (``survey`` lists it
                # first), so nothing has moved when this refuses.
                appeared = _side_names(old_db)
                if appeared:
                    lines.append("Refusing, nothing moved:")
                    lines.append(
                        f"  - {appeared} appeared beside {old_db} after the checkpoint: "
                        "another process"
                    )
                    lines.append("    opened the database. Stop it, then run again.")
                    return MoveOutcome(EXIT_REFUSED, moved_whole=False)
            if os.path.lexists(move.dst):
                raise FileExistsError(f"{move.dst} appeared after the checks")
            done.append(move)
            os.rename(move.src, move.dst)
            lines.append(f"Moved the {move.label}: {move.src} -> {move.dst}")
    except OSError as exc:
        lines.append(f"FAILED to move the {move.label} {move.src}: {exc}")
        if not any(os.path.lexists(m.dst) for m in done):
            lines.append("  nothing had moved yet.")
        undone, problems = _roll_back(done)
        lines.extend(undone + problems)
        return MoveOutcome(EXIT_FAILED, moved_whole=False)
    except BaseException:
        undone, problems = _roll_back(done)
        lines.extend(undone + problems)
        raise

    # A process that opened the database between the check above and its
    # rename writes its -wal and -shm under the old name, beside nothing.
    appeared = _side_names(old_db)
    if appeared and os.path.lexists(old_db):
        # A new database under the old name: renaming back would half-move an
        # install that moved whole, since the database could not go back.
        lines.append(
            f"FAILED: {appeared} and a new file at {old_db} appeared during the move: another"
        )
        lines.append("process created a database under the old name. Nothing was renamed back:")
        lines.append("the install moved whole, and the file at the old path is not part of it.")
        lines.append(f"Stop that process, then look at {old_db} by hand before deleting it.")
        return MoveOutcome(EXIT_FAILED, moved_whole=True)
    if appeared:
        undone, problems = _roll_back(done)
        lines.extend(undone)
        lines.append(
            f"FAILED: {appeared} appeared beside {old_db} during the move: another process"
        )
        if problems:
            lines.append("opened the database.")
            lines.extend(problems)
        else:
            lines.append("opened the database. Everything is renamed back, so the database sits")
            lines.append("beside its side files again. Stop that process, then run again.")
            return MoveOutcome(EXIT_FAILED, moved_whole=False)
        lines.append("Stop that process, then run again.")
        return MoveOutcome(EXIT_FAILED, moved_whole=False)
    return MoveOutcome(None, moved_whole=True)


def _roll_back(done: list[Move]) -> tuple[list[str], list[str]]:
    """Renames back, newest first, never onto an occupied path. Returns the
    lines for what went back and the lines for what could not.

    A recorded move whose new path is absent is skipped: its rename never
    happened (moves are recorded before their rename)."""
    undone: list[str] = []
    problems: list[str] = []
    for move in reversed(done):
        if not os.path.lexists(move.dst):
            continue
        if os.path.lexists(move.src):
            problems.append(
                f"  NOT renamed back: {move.src} is occupied, so the {move.label} "
                f"stays at {move.dst}."
            )
            problems.append("  Nothing was overwritten. Both paths need a look by hand.")
            continue
        try:
            os.rename(move.dst, move.src)
        except OSError as exc:
            problems.append(f"  FAILED to rename back {move.dst} -> {move.src}: {exc}")
            continue
        undone.append(f"  renamed back: {move.dst} -> {move.src}")
    return undone, problems


def _side_names(db: Path) -> str:
    """The side files beside ``db``, joined for a message; empty when none."""
    return " and ".join(
        _side(db, s).name for s in SIDE_SUFFIXES if os.path.lexists(_side(db, s))
    )


def _print_moves(paths: InstallPaths, found: Survey, say: Say) -> None:
    db_moves = [m for m in found.moves if m.label == "database"]
    say("Database")
    for move in db_moves:
        say(f"  move  {move.src}  ({move.size:,} bytes)")
        say(f"    to  {move.dst}")
    if not db_moves:
        say(f"  (nothing: see the refusals) {paths.old_db} -> {paths.new_db}")
    if found.side_files:
        listed = ", ".join(f"{p.name} ({size:,} bytes)" for p, size in found.side_files)
        say(f"  beside it: {listed}.")
        say("    --apply checkpoints the database and closes it, which removes them when")
        say("    no other process has it open, then refuses if either is still there.")
    say("  The in-use check sees only a process that holds the database open at that")
    say("  moment. Stop 'sensei-top serve' before --apply even when the check passes.")
    say()

    source = (
        "from --backup-dir"
        if paths.backup_dir_source == "flag"
        else "the default, beside the old database"
    )
    say("Backup slots")
    say(f"  looked in {paths.old_backup_dir} ({source}): {found.slots_found} found")
    for move in (m for m in found.moves if m.label == "backup slot"):
        say(f"  move  {move.src.name}  ({move.size:,} bytes)")
        say(f"    to  {move.dst}")
    if paths.backup_dir_source != "flag":
        say(f"  A [backup] dir or ${BACKUP_DIR_ENV} (or its old-named predecessor) that")
        say("  put the slots elsewhere needs --backup-dir.")
    say()

    say("Config directory")
    config_moves = [m for m in found.moves if m.label == "config directory"]
    if not found.config_present:
        say(f"  skipped: {paths.old_config_dir} does not exist")
    for move in config_moves:
        say(f"  move  {move.src}  ({move.size:,} bytes; renamed whole, no file in it is read)")
        say(f"    to  {move.dst}")


def _print_dry_run_figures(db: Path, found: Survey, say: Say) -> str | None:
    """Prints the before figures when an immutable read gives them exactly;
    returns a refusal when they cannot be read at all."""
    if not any(m.label == "database" for m in found.moves):
        return None
    wal = next((size for p, size in found.side_files if p.name.endswith("-wal")), 0)
    say()
    if wal:
        say(f"Figures: skipped. The -wal holds {wal:,} bytes, which an immutable read would")
        say("  ignore, so its numbers could be stale. --apply reads them after its checkpoint.")
        return None
    figures = _figures(db)
    say("Figures, read with immutable=1 (creates no side file; with no -wal content they")
    say(f"  are exact): {_describe(figures)}")
    return None if _complete(figures) else _unreadable(db)


def _complete(figures: Figures) -> bool:
    return figures.max_raw_event is not None and figures.schema_version is not None


def _unreadable(db: Path) -> str:
    return f"could not read raw_events or schema_version from {db}; is it this project's database?"


def _print_not_moved(found: Survey, *, apply: bool, say: Say) -> None:
    say("Not moved by this script:")
    if found.old_env:
        say("  - Environment variables with the old prefix, set here (names only). The")
        say("    product reads none of them now; the backup directory's is now")
        say(f"    ${BACKUP_DIR_ENV}. Set here:")
        for name in found.old_env:
            say(f"      {name}")
    else:
        say("  - No environment variable with the old prefix is set here.")
    for name in found.still_read_env:
        say(f"  - {name} matches the old prefix but is still read under that name; leave it.")
    say("  - The dashboard's density preference lives in the browser's localStorage under")
    say("    the old key; pick it again once.")
    verb = "still names" if apply else "will still name"
    say(f"  - The database's backup_state.last_path {verb}")
    say("    the old slot path, since this script writes nothing into the database.")
    say("    Nothing opens that path: 'sensei-top backup' (when the last backup is")
    say("    fresh) and 'sensei-top config' only print it. It corrects itself at the")
    say("    next backup, once the last one is a day old, or now with")
    say("    'sensei-top backup --force'.")


if __name__ == "__main__":
    sys.exit(main())
