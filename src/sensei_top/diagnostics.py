"""``sensei-top diagnostics``: the zip a bug report carries (plan 6, D16).

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
  shell's with ``--shell-log``, as written except for the player names the
  MTGO warnings of 0.7.0 and earlier carried, which are masked
  (``_LEGACY_MTGO``). A log keeps those lines until it rotates them away.
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

from sensei_top import doctor, logs
from sensei_top.arena_config import resolve_log
from sensei_top.llm.config import config_path

SECRET_KEY = "api_key"

MASK = "<masked>"

# The MTGO warnings 0.7.0 and earlier wrote with a player's handle in them, or
# a transcript line that names one. They are written without since
# (projector/mtgo/parse.py, ParsedMatch.warnings), and none of these shapes
# matches a line written since. `[^\r\n]` rather than `.`: a log written on
# Windows ends its lines with `\r\n`.
_LEGACY_MTGO: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(card event handle ).*?( matches neither )"), rf"\g<1>{MASK}\g<2>"),
    (
        re.compile(
            r"(configured handle ).*?( does not resolve to exactly one opponent among )"
            r"[^\r\n]*?( for match )"
        ),
        rf"\g<1>{MASK}\g<2>{MASK}\g<3>",
    ),
    (re.compile(r"(unrecognised (?:mulligan count|hand size) in )[^\r\n]*"), rf"\g<1>{MASK}"),
    (
        re.compile(
            r"(mulligan count mismatch for ).*?"
            r"(: 'mulligans to' implied \d+, 'begins the game' implied \d+ )[^\r\n]*"
        ),
        rf"\g<1>{MASK}\g<2>({MASK})",
    ),
    (re.compile(r"(no preceding start block )\(['\"][^\r\n]*"), rf"\g<1>({MASK})"),
    (re.compile(r"(card event before any game started: )['\"][^\r\n]*"), rf"\g<1>{MASK}"),
)


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


def mask_legacy_mtgo(data: bytes) -> bytes:
    """``data``, a log file's bytes, with the player names ``_LEGACY_MTGO``
    finds masked. Every other byte comes back as it was, undecodable ones
    included."""
    if b"[mtgo]" not in data:
        return data
    lines = data.decode("utf-8", "surrogateescape").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if "[mtgo]" in line:
            for pattern, replacement in _LEGACY_MTGO:
                line = pattern.sub(replacement, line)
            lines[i] = line
    return "".join(lines).encode("utf-8", "surrogateescape")


def _log(name: str, path: Path) -> Entry | None:
    try:
        return _bytes(name, mask_legacy_mtgo(path.read_bytes()))
    except OSError:
        return None


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
    except (OSError, tomllib.TOMLDecodeError):
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
    report = json.dumps(doctor.report(db_path), indent=2, ensure_ascii=False)
    found.append(_bytes("doctor.json", logs.home_as_tilde(report).encode("utf-8")))
    config = secret_free_config(config_path())
    if config is not None:
        found.append(_bytes("config.toml", logs.home_as_tilde(config).encode("utf-8")))
    counts = row_counts(db_path)
    if counts is not None:
        found.append(_bytes("row_counts.json", json.dumps(counts, indent=2).encode("utf-8")))
    log_file = logs.log_path(db_path.resolve())
    if log_file.parent.is_dir():
        found += [
            _log(f"logs/{p.name}", p)
            for p in sorted(log_file.parent.glob(f"{logs.LOG_NAME}*"))
            if p.is_file()
        ]
    if shell_log is not None:
        found.append(_log("logs/shell.log", shell_log))
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
