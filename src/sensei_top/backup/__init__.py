"""A daily, verified ``VACUUM INTO`` snapshot of the whole database.

``config`` resolves where a backup goes and how many to keep; ``run`` is the
routine itself — freshness gate, claim, copy, verify, rotate, record, all
never raising past ``run_backup``'s own boundary; ``schedule`` is ``serve``'s
daily thread; ``restore`` puts a backup back. This package imports neither
``reader`` nor ``projector`` and knows nothing about ``Player.log`` or MTGO's
game logs: it writes only ``backup_state`` and copies the database file
underneath everything else. See docs/architecture.md, "Backups".
"""

from sensei_top.backup.config import (
    BACKUP_DIR_ENV,
    DEFAULT_KEEP,
    BackupConfig,
    default_dir,
    resolve,
    slot_path,
    temp_path,
)
from sensei_top.backup.restore import PartialRestoreError, RestoreError, check_backup, restore_files
from sensei_top.backup.run import (
    MAX_AGE_SECONDS,
    BackupError,
    BackupResult,
    claim_age_seconds,
    last_backup_age_seconds,
    last_error_age_seconds,
    read_state,
    run_backup,
)
from sensei_top.backup.schedule import BackupScheduler

__all__ = [
    "BACKUP_DIR_ENV",
    "DEFAULT_KEEP",
    "MAX_AGE_SECONDS",
    "BackupConfig",
    "BackupError",
    "BackupResult",
    "BackupScheduler",
    "PartialRestoreError",
    "RestoreError",
    "check_backup",
    "claim_age_seconds",
    "default_dir",
    "last_backup_age_seconds",
    "last_error_age_seconds",
    "read_state",
    "resolve",
    "restore_files",
    "run_backup",
    "slot_path",
    "temp_path",
]
