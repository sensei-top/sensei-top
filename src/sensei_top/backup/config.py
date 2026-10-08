"""Where the backup destination and retention count come from — the only
question this module answers, mirroring ``mtgo/config.py``'s shape for the
same reason: a small, independent owner of one ``config.toml`` table.

Resolution order, first match wins, evaluated independently per field:

Destination directory
    1. ``--dir`` on the command line.
    2. ``SENSEI_TOP_BACKUP_DIR`` in the environment.
    3. ``[backup]``'s ``dir`` in ``llm.config.config_path()`` (the same
       ``~/.config/sensei-top/config.toml`` every other table lives in).
    4. ``default_dir(db_path)`` — a ``backups`` folder beside the database.

Retention count (``keep``)
    1. ``--keep`` on the command line.
    2. ``[backup]``'s ``keep`` in the same config file.
    3. ``DEFAULT_KEEP``.

    ``SENSEI_TOP_BACKUP_KEEP`` deliberately does not exist: every other env
    override in this project points at a *thing* to find (``MTGA_LOG``,
    ``MTGO_LOG_DIR``, ``MTGO_HANDLE``, the two API keys) rather than a tuning
    number, and ``keep`` has no per-machine story the way a log path does.

Never raises. A missing file, a missing table, or a malformed value all
resolve the same way every other config reader here does: log a warning and
fall back, never an exception a backup run would have to catch. An invalid
``keep`` *in the file* (zero, negative, not a number) clamps to
``DEFAULT_KEEP`` with a warning, because a typo in ``config.toml`` must never
silently turn backups off. An invalid ``--keep`` on the command line is a
different case argparse rejects before this module ever sees it
(``cli._positive_int``) — the two are handled in different places on
purpose, matching ``docs/architecture.md``'s ``_resolve_watch_mtgo_dir`` rule
that an explicit flag naming something invalid is an error, not a fallback.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from sensei_top.llm.config import config_path

log = logging.getLogger(__name__)

DEFAULT_KEEP = 1
BACKUP_DIR_ENV = "SENSEI_TOP_BACKUP_DIR"


@dataclass(frozen=True, slots=True)
class BackupConfig:
    directory: Path   # absolute
    keep: int         # always >= 1
    dir_source: str   # 'flag' | '$SENSEI_TOP_BACKUP_DIR' | 'config file' | 'default'
    keep_source: str  # 'flag' | 'config file' | 'default'


def default_dir(db_path: Path) -> Path:
    """``<db parent>/backups`` — beside the database, never a fixed path.

    This is what keeps AGENTS.md's mandatory ``--db /tmp/check.db``
    verification runs harmless: a scratch database gets a scratch backup
    folder next to it, never anywhere near the real one beside
    ``data/sensei-top.db``."""
    return (db_path.parent / "backups").resolve()


def resolve(
    db_path: Path, *, dir_override: str | None = None, keep_override: int | None = None
) -> BackupConfig:
    """Precedence: flag > $SENSEI_TOP_BACKUP_DIR > [backup] > default. Never raises."""
    table = _load_table()

    if dir_override:
        directory = Path(dir_override).expanduser().resolve()
        dir_source = "flag"
    else:
        env_dir = os.environ.get(BACKUP_DIR_ENV)
        if env_dir:
            directory = Path(env_dir).expanduser().resolve()
            dir_source = f"${BACKUP_DIR_ENV}"
        else:
            file_dir = table.get("dir")
            if isinstance(file_dir, str) and file_dir:
                directory = Path(file_dir).expanduser().resolve()
                dir_source = "config file"
            else:
                directory = default_dir(db_path)
                dir_source = "default"

    if keep_override is not None:
        keep = keep_override if keep_override >= 1 else DEFAULT_KEEP
        keep_source = "flag"
    else:
        file_keep = table.get("keep")
        keep, ok = _parse_keep(file_keep)
        if file_keep is not None and not ok:
            log.warning(
                "%s's [backup] keep (%r) is invalid; using %d",
                config_path(), file_keep, DEFAULT_KEEP,
            )
        keep_source = "config file" if ok else "default"

    return BackupConfig(
        directory=directory, keep=keep, dir_source=dir_source, keep_source=keep_source
    )


def _parse_keep(raw: object) -> tuple[int, bool]:
    """``(keep, ok)`` — ``ok`` is False for anything absent, unparseable, or
    less than 1, in which case ``keep`` is already ``DEFAULT_KEEP``.

    ``raw`` arrives as a TOML integer when hand-edited but as a *string* when
    written by ``cli._write_backup_config`` — every value that writer emits
    is quoted (``keep = "3"``), since ``cli._write_config_tables`` has no
    integer case. Silently treating that string as "not configured" would be
    the single most likely bug in this feature (every backup would run with
    a default that doesn't match what the user asked for), so both the
    ``int`` and numeric-``str`` shapes are accepted here.
    """
    if raw is None:
        return DEFAULT_KEEP, False
    if isinstance(raw, bool):  # bool is an int subclass; TOML never means this
        return DEFAULT_KEEP, False
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            return DEFAULT_KEEP, False
    else:
        return DEFAULT_KEEP, False
    if value < 1:
        return DEFAULT_KEEP, False
    return value, True


def _load_table() -> dict[str, object]:
    """The ``[backup]`` table, read tolerantly; ``{}`` on a missing file, a
    missing table, or malformed TOML — same posture as
    ``mtgo/config.py``'s ``_load_file_handle``."""
    path = config_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return {}
    table = data.get("backup")
    if not isinstance(table, dict):
        return {}
    return table


def slot_path(cfg: BackupConfig, db_path: Path, index: int) -> Path:
    """Slot 0 is ``<db name>.backup``; n>0 is ``<db name>.backup.n`` — the
    exact shape ``run.py``'s rotation and pruning regex (``_SLOT_RE``) both
    depend on."""
    if index == 0:
        return cfg.directory / f"{db_path.name}.backup"
    return cfg.directory / f"{db_path.name}.backup.{index}"


def temp_path(cfg: BackupConfig, db_path: Path) -> Path:
    """``<db name>.backup.tmp.<pid>``, inside the destination directory —
    same filesystem as the final slot, so ``run.py``'s closing
    ``os.replace()`` is atomic rather than a cross-filesystem copy. The pid
    suffix keeps two concurrent runs (however unlikely once the claim in
    ``run.py`` is in place) from writing the same temp file."""
    return cfg.directory / f"{db_path.name}.backup.tmp.{os.getpid()}"
