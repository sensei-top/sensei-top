"""``sensei-top diagnostics``: the zip a bug report carries. See
docs/desktop.md, "Support commands".

What goes in, and what never does:

- ``doctor.json``: ``doctor.report()``, its paths written with ``~`` for the
  home directory the way ``logs.py`` writes them.
- ``config.toml``: the config file with every ``api_key`` and ``[mtgo] handle``
  removed. Built from
  the parsed tables and written back out, never by text substitution, so a
  key cannot survive in a spelling a pattern missed. A key in the system
  keyring is not in the file and so is not here either.
- ``row_counts.json``: one row count per table of the database, read through
  a ``?mode=ro`` connection. The database itself never goes in.
- ``logs/``: the app's own log files beside the database, and the desktop
  shell's with ``--shell-log``, through ``scrub.scrub_text`` with the names
  ``known_names`` finds.
- ``Player.log``: only with ``--with-player-log``. It names the user's
  opponents and decks, so the shell's dialog asks first.

Missing inputs are left out, not invented (rule 4): no config file, no
database and no log files each mean one fewer entry.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sensei_top import doctor, logs, scrub
from sensei_top.arena_config import resolve_log
from sensei_top.config import config_path
from sensei_top.mtgo.config import load_handle

SECRET_KEY = "api_key"

MASK = scrub.MASK
LOG_TAIL_MAX_LINES = 2000

@dataclass(frozen=True)
class Entry:
    """One zip member: its name, its size, and its content (bytes already
    built, or a file to copy in when the zip is written)."""

    name: str
    size: int
    data: bytes | None = None
    path: Path | None = None


def _bytes(name: str, data: bytes) -> Entry:
    return Entry(name, len(data), data=data)


def _file(name: str, path: Path) -> Entry | None:
    try:
        return Entry(name, path.stat().st_size, path=path)
    except OSError:
        return None


def _scrubbed(data: bytes, names: list[str]) -> bytes:
    """``data`` through ``scrub_text``; undecodable bytes come back as they
    were."""
    text = data.decode("utf-8", "surrogateescape")
    return scrub.scrub_text(text, names).encode("utf-8", "surrogateescape")


def _log(name: str, path: Path, names: list[str]) -> Entry | None:
    try:
        return _bytes(name, _scrubbed(path.read_bytes(), names))
    except OSError:
        return None


def known_names(db_path: Path) -> list[str]:
    """Every name the user's data holds that a bundle must not carry: the
    configured MTGO handle, the Arena screen name and user id of the user's
    own sign-ins, and every opponent's name and id. Read through a
    ``?mode=ro`` connection; a missing database or table adds nothing."""
    found: list[str] = []
    handle = load_handle()  # fail-soft by contract
    if handle:
        found.append(handle)
    if not db_path.exists():
        return found
    try:
        conn = sqlite3.connect(db_path.absolute().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return found
    try:
        queries = (
            "SELECT opponent_name, opponent_user_id FROM matches",
            "SELECT json_extract(payload, '$.authenticateResponse.screenName'), "
            "json_extract(payload, '$.authenticateResponse.clientId') FROM raw_events "
            "WHERE label = 'AuthenticateResponse' AND json_valid(payload)",
        )
        for query in queries:
            try:
                for row in conn.execute(query):
                    found += [v for v in row if isinstance(v, str) and v]
            except sqlite3.Error:
                continue
    finally:
        conn.close()
    return sorted(set(found))


def log_tail(db_path: Path, lines: int, names: list[str]) -> str:
    """The last ``lines`` lines of the app's log, scrubbed, reading the
    rotated files (``.1`` is the newest backup) as far back as it takes.
    Empty when there is no log."""
    current = logs.log_path(db_path.resolve())
    files = [current] + [
        current.with_name(f"{current.name}.{i}") for i in range(1, logs.BACKUP_COUNT + 1)
    ]
    tail: list[str] = []  # newest line first
    for path in files:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        chunk = data.decode("utf-8", "surrogateescape").splitlines()
        tail.extend(reversed(chunk))
        if len(tail) >= lines:
            break
    newest_last = list(reversed(tail[:lines]))
    text = scrub.scrub_text("\n".join(newest_last), names)
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _strip_keys(value: object) -> object:
    """``value`` with every ``api_key`` removed, at any depth, tables inside
    arrays included."""
    if isinstance(value, dict):
        return {k: _strip_keys(v) for k, v in value.items() if k != SECRET_KEY}
    if isinstance(value, list):
        return [_strip_keys(v) for v in value]
    return value


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, dict):
        pairs = (f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items())
        return "{ " + ", ".join(pairs) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def _toml_lines(table: dict, prefix: str = "") -> list[str]:
    out = [
        f"{_toml_key(k)} = {_toml_value(v)}"
        for k, v in table.items()
        if not isinstance(v, dict)
    ]
    for key, sub in table.items():
        if isinstance(sub, dict):
            name = f"{prefix}{_toml_key(key)}"
            out += ["", f"[{name}]", *_toml_lines(sub, f"{name}.")]
    return out


def secret_free_config(path: Path) -> str | None:
    """The config file's tables without any ``api_key`` or ``[mtgo] handle``,
    as TOML text; ``None`` when there is no file or it cannot be parsed. The
    handle is the account name, an identifier; ``doctor.json``'s
    ``handle_set`` says whether one is set."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    mtgo = data.get("mtgo")
    if isinstance(mtgo, dict):
        mtgo.pop("handle", None)
    return "\n".join(_toml_lines(_strip_keys(data))).lstrip("\n") + "\n"  # type: ignore[arg-type]


def row_counts(db_path: Path) -> dict[str, int | None] | None:
    """Rows per table, or ``None`` when there is no database to ask. A table
    that cannot be counted reads as ``None``."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(db_path.absolute().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    counts: dict[str, int | None] = {}
    try:
        try:
            names = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
        except sqlite3.Error:
            return None
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            try:
                counts[name] = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            except sqlite3.Error:
                counts[name] = None
    finally:
        conn.close()
    return counts


def entries(
    db_path: Path, *, shell_log: Path | None = None, with_player_log: bool = False
) -> list[Entry]:
    """Everything that would go in the zip, in the order it is written."""
    found: list[Entry | None] = []
    names = known_names(db_path)
    report = json.dumps(doctor.report(db_path), indent=2, ensure_ascii=False)
    found.append(_bytes("doctor.json", scrub.scrub_text(report, names).encode("utf-8")))
    config = secret_free_config(config_path())
    if config is not None:
        found.append(_bytes("config.toml", scrub.scrub_text(config, names).encode("utf-8")))
    counts = row_counts(db_path)
    if counts is not None:
        found.append(_bytes("row_counts.json", json.dumps(counts, indent=2).encode("utf-8")))
    log_file = logs.log_path(db_path.resolve())
    if log_file.parent.is_dir():
        found += [
            _log(f"logs/{p.name}", p, names)
            for p in sorted(log_file.parent.glob(f"{logs.LOG_NAME}*"))
            if p.is_file()
        ]
    if shell_log is not None:
        found.append(_log("logs/shell.log", shell_log, names))
    if with_player_log:
        player, _source = resolve_log()
        if player is not None:
            found.append(_file("Player.log", player))
    return [e for e in found if e is not None]


def write_zip(out: Path, items: list[Entry]) -> None:
    """Write ``items`` to ``out``; refuses an existing file (``"x"`` mode)."""
    with out.open("xb") as raw, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            if item.data is not None:
                zf.writestr(item.name, item.data)
            elif item.path is not None:
                with item.path.open("rb") as src, zf.open(item.name, "w", force_zip64=True) as dst:
                    while chunk := src.read(io.DEFAULT_BUFFER_SIZE * 16):
                        dst.write(chunk)
