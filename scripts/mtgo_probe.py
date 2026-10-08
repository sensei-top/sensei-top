"""Recon tool for MTGO's own log files — decode one, report what it is.

Not a parser and not wired into the pipeline: MTGO writes ``Match_GameLog_*.dat``
(and friends) in a format no public source fully documents. This script's only
job is to answer, with evidence rather than a guess, what container format a
given file actually uses and whether the decoded text looks like a usable game
log — the reconnaissance step that has to happen before any real ``reader/``
or ``projector/`` code gets written for a second source.

    uv run python scripts/mtgo_probe.py <file> [<file> ...]
    uv run python scripts/mtgo_probe.py --lines 200 --force <file>

Bounded output by default, same discipline as the navigating-sensei-top
skill's fixture_peek.py: a decoded game log is prose of unknown length, and an
unbounded dump is exactly the failure mode that skill exists to avoid.
"""

from __future__ import annotations

import argparse
import gzip
import zlib
from pathlib import Path

DEFAULT_LINE_LIMIT = 80
DEFAULT_CHAR_LIMIT = 6000

# Signatures checked against the first bytes of the *raw* file, before any
# decode attempt — this is what tells us which decode attempt is worth trying.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x1f\x8b", "gzip"),
    (b"\x78\x9c", "zlib (default compression)"),
    (b"\x78\x01", "zlib (fastest compression)"),
    (b"\x78\xda", "zlib (best compression)"),
    (b"PK\x03\x04", "zip"),
    (b"\xff\xfe", "UTF-16LE BOM"),
    (b"\xfe\xff", "UTF-16BE BOM"),
    (b"\xef\xbb\xbf", "UTF-8 BOM"),
    (b"\x00\x01\x00\x00\x00\xff\xff\xff\xff", ".NET BinaryFormatter header"),
]

# A byte-for-byte copy is the only case where a BOM finding means anything
# about the *source* file. Anything that passed through PowerShell's
# Out-File/Export-Csv (Windows PowerShell 5.1 default: UTF-16LE with BOM)
# will show this signature regardless of what the original bytes were.
_BOM_CAVEAT = (
    "note: a BOM here is only evidence about the *source* format if this file "
    "was copied byte-for-byte (Copy-Item). Out-File/Export-Csv in Windows "
    "PowerShell 5.1 default to UTF-16LE-with-BOM regardless of the original "
    "content — if this file passed through either, the BOM tells you about "
    "PowerShell, not about MTGO."
)

# Fields a real MTGO game log would be expected to carry, per the third-party
# tools' documented output (MTGO-Tracker's data dictionary, mtgo_utils).
# Checked against decoded text with simple substring/keyword heuristics —
# good enough to report "looks promising" or "looks wrong", not to parse.
_CONTENT_SIGNALS: dict[str, tuple[str, ...]] = {
    "turn markers": ("turn", "Turn "),
    "mulligan": ("mulligan", "Mulligan"),
    "life total change": ("life",),
    "draw a card": ("draws a card", "draws a "),
    "casts/plays a card": ("casts ", "plays "),
    "game/match boundary": ("wins game", "wins the match", "Game 1", "Game 2"),
}


def _detect_signature(data: bytes) -> str | None:
    for magic, name in _SIGNATURES:
        if data.startswith(magic):
            return name
    return None


def _attempt(attempts: list[tuple[str, str]], label: str, fn) -> bytes | None:
    """Run ``fn()``, recording (label, decoded text) on success. Returns the
    raw bytes on success (so a caller can chain a further decode over them),
    or None — a failed attempt is silently absent from the report, not an
    error: most decode/decompress guesses are expected to fail.
    """
    try:
        result = fn()
    except Exception:
        return None
    if isinstance(result, bytes):
        return result
    attempts.append((label, result))
    return None


def _try_decode(data: bytes) -> list[tuple[str, str]]:
    """Every decode attempt that produced *something*, as (method, text) pairs.

    Order matters for the report but not for correctness: we try all of them
    and let the caller judge which text looks like a real game log, rather
    than betting on one guess and stopping.
    """
    attempts: list[tuple[str, str]] = []

    for method, decompress in (
        ("gzip", gzip.decompress),
        ("zlib", zlib.decompress),
        ("zlib (raw, no header)", lambda b: zlib.decompress(b, -15)),
    ):
        decompressed = _attempt(attempts, method, lambda d=decompress: d(data))
        if decompressed is None:
            continue
        _attempt(attempts, f"{method} -> utf-8", lambda b=decompressed: b.decode("utf-8"))
        _attempt(attempts, f"{method} -> utf-16le", lambda b=decompressed: b.decode("utf-16le"))

    for method, encoding in (
        ("utf-16le", "utf-16le"),
        ("utf-16be", "utf-16be"),
        ("utf-8", "utf-8"),
        ("utf-8-sig", "utf-8-sig"),
        ("latin-1", "latin-1"),  # never fails; last resort, listed last
    ):
        _attempt(attempts, method, lambda e=encoding: data.decode(e))

    attempts.append(
        (
            "length-prefixed UTF-8 strings (.NET BinaryWriter style)",
            _extract_dotnet_strings(data),
        )
    )

    return attempts


def _extract_dotnet_strings(data: bytes) -> str:
    """Pull out runs of printable text, treating the data as a byte stream.

    .NET's BinaryWriter.Write(string) prefixes each string with a 7-bit
    encoded length (not a fixed-width int) — this doesn't decode that
    faithfully, it just scans for spans of bytes that decode as printable
    UTF-8 of length >= 4 and joins them with newlines, on the theory that
    real text will survive this even if the framing around it doesn't.
    """
    out = []
    buf = bytearray()
    for byte in data:
        if 0x20 <= byte < 0x7F or byte in (0x09,):
            buf.append(byte)
        else:
            if len(buf) >= 4:
                out.append(buf.decode("ascii"))
            buf = bytearray()
    if len(buf) >= 4:
        out.append(buf.decode("ascii"))
    return "\n".join(out)


def _score_signals(text: str) -> dict[str, bool]:
    return {
        signal: any(kw in text for kw in keywords)
        for signal, keywords in _CONTENT_SIGNALS.items()
    }


def _printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
    return printable / len(text)


def _clip(text: str, *, chars: int, lines: int, force: bool) -> tuple[str, bool]:
    """Truncate for display, reporting whether truncation happened.

    Compared against the full text rejoined from *all* its lines, not the raw
    string — a trailing "\\r\\n" that splitlines() drops would otherwise read
    as truncation when nothing was actually cut.
    """
    all_lines = text.splitlines()
    full_rejoined = "\n".join(all_lines)
    if force:
        return full_rejoined, False
    line_clipped = "\n".join(all_lines[:lines])
    if len(line_clipped) > chars:
        return line_clipped[:chars], True
    return line_clipped, len(line_clipped) < len(full_rejoined)


def probe_file(path: Path, *, line_limit: int, char_limit: int, force: bool) -> None:
    print(f"=== {path} ===")
    if not path.exists():
        print("  does not exist\n")
        return

    data = path.read_bytes()
    print(f"  size: {len(data)} bytes")
    print(f"  first 32 bytes (hex): {data[:32].hex(' ')}")

    sig = _detect_signature(data)
    if sig:
        print(f"  signature match: {sig}")
        if "BOM" in sig:
            print(f"  {_BOM_CAVEAT}")
    else:
        print("  signature match: none of the known magic bytes")

    print()
    best: tuple[str, str, float] | None = None
    for method, text in _try_decode(data):
        if not text.strip():
            continue
        ratio = _printable_ratio(text)
        marker = " <-- most printable so far" if best is None or ratio > best[2] else ""
        print(f"  [{method}] printable ratio {ratio:.2f}, {len(text)} chars{marker}")
        if best is None or ratio > best[2]:
            best = (method, text, ratio)

    if best is None:
        print("\n  No decode attempt produced non-empty text. Report this — do not "
              "force an interpretation. Next step: mtgo_utils' file_parser as a "
              "reference implementation, not a guess at the byte layout.")
        print()
        return

    method, text, ratio = best
    print(f"\n  Best candidate: [{method}] (printable ratio {ratio:.2f})")

    signals = _score_signals(text)
    print("  content signals found:")
    for signal, found in signals.items():
        print(f"    {'yes' if found else 'no ':<3} {signal}")

    clipped, truncated = _clip(text, chars=char_limit, lines=line_limit, force=force)
    print(f"\n  decoded text ({'first ' + str(line_limit) + ' lines' if not force else 'full'}"
          f"{', truncated at ' + str(char_limit) + ' chars' if truncated and not force else ''}):")
    print("  " + "-" * 70)
    for line in clipped.splitlines():
        print(f"  {line}")
    print("  " + "-" * 70)
    if truncated and not force:
        print(f"  (truncated — pass --force to see the rest; full text is "
              f"{len(text)} chars)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--lines", type=int, default=DEFAULT_LINE_LIMIT,
                         help=f"max lines to print per file (default {DEFAULT_LINE_LIMIT})")
    parser.add_argument("--chars", type=int, default=DEFAULT_CHAR_LIMIT,
                         help=f"max characters to print per file (default {DEFAULT_CHAR_LIMIT})")
    parser.add_argument("--force", action="store_true",
                         help="ignore the char/line caps and print everything")
    args = parser.parse_args()

    for path in args.files:
        probe_file(path, line_limit=args.lines, char_limit=args.chars, force=args.force)


if __name__ == "__main__":
    main()
