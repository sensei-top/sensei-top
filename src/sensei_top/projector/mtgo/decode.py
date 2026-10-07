"""Decode MTGO's ``Match_GameLog_*.dat`` byte stream into the text strings it
carries.

Stage 2 only (AGENTS.md non-negotiable #1): this module knows about .NET's
binary string framing. It knows nothing about files, base64, or MTGO's game
grammar — ``parse.py`` owns the grammar, ``reader/mtgo.py`` owns the file.

This replaces ``scripts/mtgo_probe.py``'s ``_extract_dotnet_strings`` ASCII
scan, which that script's own docstring already calls "not a parser" — it
scans for runs of *printable ASCII* bytes, which corrupts any string
containing a multi-byte UTF-8 character (confirmed, real card:
``Kíli the Resourceful`` decoded as two fragments, ``K`` and
``li the Resourceful``, because ``í`` is UTF-8 ``\\xc3\\xad`` and both bytes
fall outside the ASCII scan range — see ``.claude/handoffs/mtgo-source.md``).

The real framing: a .NET ``BinaryWriter.Write(string)`` call prefixes each
string with its length as a **7-bit-encoded integer** (little-endian base-128
varint, high bit means "more bytes follow" — the same encoding
``BinaryReader.Read7BitEncodedInt`` reads back), followed by that many
**UTF-8** bytes. Reading that framing correctly (not scanning for ASCII) is
what fixes the ``Kíli`` split: a real UTF-8 decode treats ``\\xc3\\xad`` as
one character, not two out-of-range bytes.

The strings are not the *only* thing in the file — the surrounding bytes are
whatever .NET object-graph framing wraps them (unexplored; see the recon
note's ``mtgo_game_history`` finding, a much harder problem this decoder does
not need to solve). So a length-prefixed read anchored only at byte 0 would
walk off into that framing and produce garbage. Instead this is a
**self-synchronizing resync scanner**: try a length-prefixed read at *every*
byte position; accept it only if the length is plausible, the bytes decode as
strict UTF-8, and the result looks like real text; otherwise advance one byte
and try again. Real strings anchor themselves; framing noise fails the
UTF-8/printability check and gets skipped a byte at a time until the next
real string re-synchronizes the scan.

Validated against the real fixture (``tests/fixtures/mtgo_match_session.log``,
see ``tests/test_projector_mtgo.py``): decodes cleanly to exactly the 115
strings the recon pass's content analysis expected, with no leaked framing
bytes on any line (unlike the ASCII-scan heuristic, whose output visibly
includes stray prefix bytes — e.g. a leaked ``A`` before ``@PPlayer1 puts
...``) and the ``Kíli the Resourceful`` regression fixed.

If a real file's bytes don't resync into a plausible-looking transcript —
too few strings, or none — that is reported by the caller as a warning
(``project.py``), never silently swapped for the old ASCII heuristic
(AGENTS.md "Before you finish": a surprising result is information, not an
obstacle to route around).
"""

from __future__ import annotations

# A real string is expected to be at least this long. Matches the probe
# script's own MIN_LEN, which was tuned against the same real sample: shorter
# candidates are indistinguishable from framing noise that merely happens to
# decode as UTF-8.
_MIN_LEN = 4
# .NET's Read7BitEncodedInt caps at 5 bytes (32 bits fits in 5*7 bits); a
# longer run is not a valid length prefix.
_MAX_VARINT_BYTES = 5


def _read_7bit_encoded_int(data: bytes, pos: int) -> tuple[int, int] | None:
    """Read one 7-bit-encoded (varint) length prefix starting at ``pos``.

    Returns ``(value, next_pos)``, or ``None`` if the bytes at ``pos`` don't
    form a complete, in-range varint before running off the end of ``data``.
    """
    result = 0
    shift = 0
    start = pos
    n = len(data)
    while True:
        if pos >= n or pos - start >= _MAX_VARINT_BYTES:
            return None
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7


def _looks_like_text(s: str) -> bool:
    """Reject decode candidates that are technically valid UTF-8 but not
    plausible game-log text — the printability half of the resync check.
    Tab/CR/LF are allowed even though ``str.isprintable()`` rejects them;
    nothing in the real fixture needs them, but excluding whitespace
    controls that MTGO's own text might legitimately use would be exactly
    the kind of ASCII-centric assumption this module exists to avoid.
    """
    if not s:
        return False
    return all(ch.isprintable() or ch in "\t\r\n" for ch in s)


def decode_strings(data: bytes, *, min_len: int = _MIN_LEN) -> list[str]:
    """Resync-scan ``data`` for length-prefixed UTF-8 strings.

    Never raises: an unparseable region is simply skipped a byte at a time.
    An empty or implausibly short result is the caller's signal to warn, not
    this function's — decoding is mechanical, judging "did this look like a
    real log" belongs to whoever knows what a real log looks like.
    """
    out: list[str] = []
    i = 0
    n = len(data)
    while i < n:
        parsed = _read_7bit_encoded_int(data, i)
        if parsed is None:
            i += 1
            continue
        length, after_prefix = parsed
        if length < min_len or after_prefix + length > n:
            i += 1
            continue
        candidate = data[after_prefix : after_prefix + length]
        try:
            text = candidate.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            i += 1
            continue
        if not _looks_like_text(text):
            i += 1
            continue
        out.append(text)
        i = after_prefix + length
    return out
