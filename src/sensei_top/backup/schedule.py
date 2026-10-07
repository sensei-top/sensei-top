"""The background thread that gives ``serve`` an automatic daily backup,
without turning ``run_backup`` itself into something that only makes sense
inside a long-running process.

Mirrors ``live.LiveIngester``'s ``start()``/``stop(timeout)``/``is_alive()``
surface -- the same shape ``cli.cmd_serve`` already manages for the log
watcher -- so wiring this in is "one more thing with that surface", not a
new pattern. It runs on a background daemon thread rather than a separate
process the way ``live.WatcherProcess`` does: that split exists to get a
projection rebuild off the API's own GIL, and a backup spends its time
inside a dedicated SQLite connection and OS calls (``VACUUM INTO``,
``os.replace``) rather than holding the GIL the way a rebuild's Python-level
JSON parsing does, so there is no equivalent tax here to avoid.

``run_backup`` already owns the actual 24h freshness gate (see
``backup/run.py``); this scheduler's own ``check_interval`` is deliberately
much shorter (an hour, not a day) so that gate's boundary is caught
promptly rather than drifting up to a whole extra ``check_interval`` late,
and re-checking costs nothing when there is nothing to do -- ``run_backup``'s
gate is one indexed SELECT before anything else happens.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from sensei_top import db
from sensei_top.backup import config as backup_config
from sensei_top.backup.run import run_backup

log = logging.getLogger(__name__)


@dataclass
class BackupScheduler:
    db_path: Path
    dir_override: str | None = None
    keep_override: int | None = None
    # Long enough that a normal `serve` restart never makes a fresh backup
    # compete with the watcher's own startup work for I/O.
    startup_delay: float = 120.0
    check_interval: float = 3600.0

    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def _run_forever(self) -> None:
        if self._stop.wait(self.startup_delay):
            return  # stopped before the first check ever ran
        while not self._stop.is_set():
            try:
                self._check_once()
            except Exception as exc:  # a bad run must never end the schedule
                log.warning("scheduled backup raised: %s", exc)
            self._stop.wait(self.check_interval)

    def _check_once(self) -> None:
        # Config is re-resolved every iteration, not cached at construction
        # time, so an edit to config.toml (or `sensei-top config
        # --set-backup-dir`) while `serve` is running takes effect on the
        # very next hourly check rather than needing a restart.
        # connect(), not open_database(): migrations belong to serve's
        # startup (see that function), and this check runs hourly for as
        # long as serve does.
        conn = db.connect(self.db_path)
        try:
            cfg = backup_config.resolve(
                self.db_path,
                dir_override=self.dir_override,
                keep_override=self.keep_override,
            )
            result = run_backup(conn, self.db_path, cfg=cfg, stop=self._stop)
            if result.status == "failed":
                log.warning("scheduled backup failed: %s", result.error)
        finally:
            conn.close()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_forever, name="mtga-backup", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
