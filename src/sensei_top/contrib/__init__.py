"""What a contributed game sends: one record per finished game, built from
the projected tables at request time, served by ``GET /api/contrib/games``
and ``GET /api/contrib/records``. Core, never ``sensei_top.ai``; it reads
the database and calls nothing outside the machine (the shell's main process
does the upload).
"""

from sensei_top.contrib.record import SCHEMA_VERSION, build_records, finished_game_keys

__all__ = ["SCHEMA_VERSION", "build_records", "finished_game_keys"]
