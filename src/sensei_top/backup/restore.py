"""Putting a backup back: the first four steps of ``sensei-top restore``.

The caller (``cli.cmd_restore``) does the fifth -- ``open_database()`` and
``project()`` -- because this package imports neither ``reader`` nor
``projector``. Every refusal is raised before anything moves, so it leaves each
file where it was: a missing or unusable FILE, FILE being the database itself,
a schema newer than this code, a ``-wal`` beside FILE, and a live database
whose checkpoint reports busy. Any
failure after the first move -- a move, the copy -- puts the moved files back
in reverse order; if some cannot be put back, ``PartialRestoreError`` names
each one still aside, and the message never claims nothing changed.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path

from sensei_top import db

#: The sidecar files SQLite keeps beside the database. A stale ``-wal`` left
#: beside a restored ``.db`` is the one way to corrupt it, so they move too.
SIDECARS = ("", "-wal", "-shm")


class RestoreError(Exception):
    """A refusal; the message is the whole user-facing text."""


class PartialRestoreError(RestoreError):
    """The rollback could not put everything back; ``aside`` lists what is
    still under a ``.replaced`` name as (replaced, original) pairs."""

    exit_code = 3

    def __init__(self, detail: str, aside: list[tuple[Path, Path]]) -> None:
        lines = [
            f"Restore stopped partway and could not put everything back ({detail}).",
            "Do not start serve until these files are renamed back:",
            *(f"  {r.name} -> {o.name}" for r, o in aside),
        ]
        super().__init__("\n".join(lines))
        self.aside = aside


def check_backup(file: Path, db_path: Path, say: Callable[[str], None]) -> int:
    """Steps 1 and 2: open ``file`` read-only, vet it, return its schema version.

    Raises ``RestoreError`` for a missing file, the database itself, a
    non-empty ``-wal`` beside ``file`` (it alone is not the whole database), a
    file that is not a usable database, and a schema newer than this code
    ships. The connection is closed before this returns.
    """
    if not file.exists():
        raise RestoreError(f"{file} does not exist.")
    if db_path.exists() and os.path.samefile(file, db_path):
        raise RestoreError(
            f"{file} is the database itself. Pass a backup copy. Nothing was changed."
        )
    say(f"Checking {file}...")
    wal = Path(f"{file}-wal")
    if wal.exists() and wal.stat().st_size > 0:
        raise RestoreError(
            f"{file}-wal sits beside it, so {file} alone is not the whole database. "
            "Restore a copy 'sensei-top backup' wrote, or close whatever has "
            f"{file} open. Nothing was changed."
        )
    try:
        # immutable=1, as backup/run.py's verify: read exactly the bytes copied.
        conn = sqlite3.connect(file.absolute().as_uri() + "?immutable=1", uri=True)
    except sqlite3.Error as e:
        raise RestoreError(f"{file} is not a usable database ({e}). Nothing was changed.") from e
    try:
        try:
            verdict = conn.execute("PRAGMA quick_check").fetchone()[0]
            if verdict != "ok":
                raise RestoreError(
                    f"{file} is not a usable database ({verdict}). Nothing was changed."
                )
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone()
            if has_table is None:
                raise RestoreError(
                    f"{file} is not a usable database (no schema_version table). "
                    "Nothing was changed."
                )
            version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
        except sqlite3.Error as e:
            raise RestoreError(
                f"{file} is not a usable database ({e}). Nothing was changed."
            ) from e
    finally:
        conn.close()
    shipped = max(v for v, _ in db.discover_migrations())
    say(f"Backup schema version {version} (this code ships {shipped}).")
    if version > shipped:
        raise RestoreError(
            f"{file} was written by a newer version of Sensei Top "
            f"(schema {version}; this code ships {shipped}). "
            "Update Sensei Top, then restore it. Nothing was changed."
        )
    return version


def _replaced_suffix(db_path: Path) -> str:
    """The first ``.replaced`` / ``.replaced.N`` that no sidecar already has,
    so one suffix names the whole set and nothing is ever overwritten."""
    n = 0
    while True:
        suffix = ".replaced" if n == 0 else f".replaced.{n}"
        if not any(Path(f"{db_path}{s}{suffix}").exists() for s in SIDECARS):
            return suffix
        n += 1


def _checkpoint_live(db_path: Path) -> None:
    """Fold the live ``-wal`` into the ``.db`` so the ``.replaced`` copy is
    complete on its own. Only when the ``.db`` exists: connecting to a missing
    one would create an empty database and delete an orphaned ``-wal``.
    Refuses when a reader or writer keeps the checkpoint busy."""
    busy = RestoreError(
        f"{db_path} is in use. Is serve still running? Stop it and try again. "
        "Nothing was changed."
    )
    try:
        conn = sqlite3.connect(db_path, timeout=1)
    except sqlite3.OperationalError as e:
        raise busy from e
    try:
        try:
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.OperationalError as e:
            raise busy from e
        except sqlite3.DatabaseError:
            return  # not a database at all: the very thing a restore replaces
        if row[0] == 1:
            raise busy
    finally:
        conn.close()


def restore_files(file: Path, db_path: Path, say: Callable[[str], None] = print) -> None:
    """Steps 1-4: check ``file``, move the live database aside, copy it in.

    A running ``serve`` is only noticed when it keeps the live database's
    checkpoint busy; one that holds it open without a transaction keeps the
    moved file's handle.
    """
    check_backup(file, db_path, say)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Never connect to a missing or 0-byte file: SQLite would treat it as a new
    # database and delete the real -wal beside it.
    if db_path.exists() and db_path.stat().st_size > 0:
        _checkpoint_live(db_path)

    suffix = _replaced_suffix(db_path)
    moved: list[tuple[Path, Path]] = []
    temp = db_path.with_name(f"{db_path.name}.restore.tmp.{os.getpid()}")

    def undo() -> list[tuple[Path, Path]]:
        """Put the moved files back, last first, stopping at the first failure
        so a ``.db`` never goes back without its ``-wal``. Returns the
        (replaced, original) pairs still aside, then drops the temp file."""
        left = list(reversed(moved))
        while left:
            dst, src = left[0][1], left[0][0]
            try:
                os.replace(dst, src)
            except OSError:
                break
            left.pop(0)
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
        return [(dst, src) for src, dst in left]

    try:
        for sidecar in SIDECARS:
            src = Path(f"{db_path}{sidecar}")
            if not src.exists():
                continue
            dst = Path(f"{src}{suffix}")
            try:
                os.replace(src, dst)
            except OSError as e:
                aside = undo()
                if aside:
                    raise PartialRestoreError(f"could not move {src.name} aside: {e}", aside) from e
                raise RestoreError(
                    f"Could not move {src.name} aside ({e}). Is serve still running? "
                    "Stop it and try again. Nothing was changed."
                ) from e
            moved.append((src, dst))
            say(f"Moved {src.name} aside to {dst.name}.")

        say(f"Copying {file} into {db_path}...")
        shutil.copyfile(file, temp)
        os.replace(temp, db_path)
    except RestoreError:
        raise
    except BaseException as e:
        aside = undo()
        if aside:
            raise PartialRestoreError(f"copying failed: {e}", aside) from e
        raise
