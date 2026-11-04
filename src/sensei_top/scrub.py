"""Text scrubbing: what a log, a diagnostics bundle or an error report may
carry once the identifiers are taken out. See docs/desktop.md, "Support
commands".

``scrub_text`` is pure and takes the names it must remove from the caller;
it reads no database and no config. Its test vectors
(``tests/fixtures/scrub_vectors.json``) are to be shared with the desktop
shell's own scrubber, once it exists, so a rule changes in both places or in neither.

Traps:

1. Order matters. The home directory goes first (a vector cannot pin it,
   it depends on the machine, so ``tests/test_scrub.py`` does), then the
   profile folders, then emails and tokens, then names.
2. A profile folder may hold spaces, but only when a separator follows
   within the same line; otherwise the first word is the folder, or
   ``... failed to read`` would vanish with it.
3. A name shorter than ``MIN_NAME`` characters is not substituted. Names
   match whole (no letter, digit or underscore either side), ignoring case.
   Single-word names are found in one pass over the text's words, by set
   lookup; only names with a separator or a space go through a regex. A
   name with a ``#NNNNN`` suffix also scrubs its part before the ``#``.
   Names ``_ARENA_ID`` already covers are dropped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sensei_top import logs

MASK = "<masked>"
MIN_NAME = 3

_SEP = r"(?:\\\\|\\|/)"
# A folder name: words joined by single spaces when a separator follows
# directly (trap 2), else the first word alone.
_WORD = r"[^\\/\s\"'<>|:*?]+"
_FOLDER = rf"(?:{_WORD}(?: {_WORD})*(?=[\\/])|{_WORD})"
_PROFILE_PATHS = (
    re.compile(
        rf"(?i)(\b[A-Z]:{_SEP}(?:Users|home|Documents and Settings){_SEP}){_FOLDER}"
    ),
    re.compile(rf"(?i)(\\\\+[^\\/\s]+{_SEP}Users{_SEP}){_FOLDER}"),
    re.compile(rf"(?<![\w.])(/(?:run/)?media/){_FOLDER}"),
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
_BEARER = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+")
_PREFIXED_KEY = re.compile(r"\b(?:sk-ant-|sk-|ghp_|gho_|xox[bap]-|AKIA)[A-Za-z0-9_-]{8,}")
_KEY_VALUE = re.compile(
    r"(?i)\b((?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password)"
    r"[\"']?\s*[=:]\s*[\"']?)[^\s\"',;&}]+"
)
# An Arena user ID: 26 upper-case letters and digits, at least one of each.
_ARENA_ID = re.compile(
    r"(?<![A-Za-z0-9])(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{26}(?![A-Za-z0-9])"
)

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


def mask_legacy_text(text: str) -> str:
    """``text`` with the player names ``_LEGACY_MTGO`` finds masked, line by
    line, only on lines that carry ``[mtgo]``."""
    if "[mtgo]" not in text:
        return text
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if "[mtgo]" in line:
            for pattern, replacement in _LEGACY_MTGO:
                line = pattern.sub(replacement, line)
            lines[i] = line
    return "".join(lines)


def mask_legacy_mtgo(data: bytes) -> bytes:
    """``data``, a log file's bytes, with the player names ``_LEGACY_MTGO``
    finds masked. Every other byte comes back as it was, undecodable ones
    included."""
    if b"[mtgo]" not in data:
        return data
    text = data.decode("utf-8", "surrogateescape")
    return mask_legacy_text(text).encode("utf-8", "surrogateescape")


_MARKER = r"<(?:user|email|token|id|name|masked)>"
_TOKEN = re.compile(rf"{_MARKER}|\w+(?:#\d+)?")


def _expand(names: Iterable[str]) -> tuple[set[str], list[str]]:
    """The names to scrub, split into single words (casefolded, for lookup)
    and the rest (for a regex), with each ``Name#NNNNN``'s bare part added."""
    words: set[str] = set()
    others: set[str] = set()
    for raw in names:
        name = raw.strip()
        candidates = [name]
        head, hash_, tail = name.partition("#")
        if hash_ and tail.isdigit() and head:
            candidates.append(head.strip())
        for cand in candidates:
            if len(cand) < MIN_NAME or _ARENA_ID.fullmatch(cand):
                continue
            if re.fullmatch(r"\w+(?:#\d+)?", cand):
                words.add(cand.casefold())
            else:
                others.add(cand)
    return words, sorted(others, key=len, reverse=True)


def _replace_names(text: str, names: Iterable[str]) -> str:
    words, others = _expand(names)
    if others:
        pattern = re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(n) for n in others) + r")(?!\w)",
            re.IGNORECASE,
        )
        text = pattern.sub("<name>", text)
    if not words:
        return text

    def token(m: re.Match[str]) -> str:
        tok = m.group(0)
        if tok.startswith("<"):
            return tok
        if tok.casefold() in words:
            return "<name>"
        head, hash_, _tail = tok.partition("#")
        if hash_ and head.casefold() in words:
            return "<name>" + hash_ + _tail
        return tok

    return _TOKEN.sub(token, text)


def scrub_text(text: str, names: Iterable[str] = ()) -> str:
    """``text`` with every identifier it may carry replaced by a marker:
    the home directory by ``~``, a profile folder (Windows, Wine, UNC,
    removable media) by ``<user>``, emails by ``<email>``, tokens and keys by
    ``<token>``, Arena user IDs by ``<id>``, the legacy MTGO warnings' names
    by ``<masked>`` and every entry of ``names`` by ``<name>`` (trap 3)."""
    text = logs.home_as_tilde(text)
    for pattern in _PROFILE_PATHS:
        text = pattern.sub(r"\g<1><user>", text)
    text = _EMAIL.sub("<email>", text)
    text = _JWT.sub("<token>", text)
    text = _BEARER.sub(r"\g<1><token>", text)
    text = _PREFIXED_KEY.sub("<token>", text)
    text = _KEY_VALUE.sub(r"\g<1><token>", text)
    text = _ARENA_ID.sub("<id>", text)
    text = mask_legacy_text(text)
    return _replace_names(text, names)
