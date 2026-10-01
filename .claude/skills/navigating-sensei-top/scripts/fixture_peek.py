#!/usr/bin/env python3
"""Index and extract single events from the large Arena log fixtures under
tests/fixtures/ — without ever printing the whole file.

tests/fixtures/match_session.log and combat_session.log are raw Arena
captures: a few dozen lines, but individual lines run up to ~50,000
characters (a single GreToClientEvent). Reading them directly, or even
`head`-ing them, pulls the entire multi-hundred-KB payload into context.
This script uses the project's own segmenter (the same one the reader uses
on a live log) to split a fixture into discrete entries, lets you list them
cheaply, and print exactly one at a time, capped.

Run with `uv run python` from the repo root so `sensei_top` is importable:

    uv run python .claude/skills/navigating-sensei-top/scripts/fixture_peek.py \\
        index tests/fixtures/match_session.log

    uv run python .claude/skills/navigating-sensei-top/scripts/fixture_peek.py \\
        show tests/fixtures/match_session.log --entry 11

    uv run python .claude/skills/navigating-sensei-top/scripts/fixture_peek.py \\
        grep tests/fixtures/combat_session.log --type GameStateMessage

Entry numbers are 0-based, matching `index` output. If sensei_top can't be
imported (e.g. run without `uv run`), this falls back to a cruder lexical
scan and says so on stderr — never a hard failure, per this repo's fail-soft
convention.

Arena fixtures only. tests/fixtures/ also holds mtgo_match_session.log, an
MTGO game log — a binary .NET string stream, not text — which this script
cannot read; `scripts/mtgo_probe.py` is its equivalent. See SKILL.md §2b.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from sensei_top.reader.segmenter import segment_lines

    _HAVE_SEGMENTER = True
except ImportError:
    _HAVE_SEGMENTER = False

# All three fixtures were captured under an M/D/Y system locale (see
# docs/arena-log.md); header timestamps are otherwise ambiguous.
_LOCALE_HINT = "mdy"

_REQ_RE = re.compile(r"^\[UnityCrossThreadLogger\]==>\s+(\S+)")
_JSON_START_RE = re.compile(r"^\s*\{")


class _FakeEntry:
    """Fallback entry shape mirroring the fields of segmenter.LogEntry."""

    __slots__ = ("kind", "label", "line_number", "logged_at", "payload")

    def __init__(
        self, kind: str, payload: str, label: str | None, logged_at: str | None, line_number: int
    ) -> None:
        self.kind = kind
        self.payload = payload
        self.label = label
        self.logged_at = logged_at
        self.line_number = line_number


def _read_lines(path: Path) -> list[str]:
    """Text lines of an Arena fixture — or a pointed error for one that isn't.

    tests/fixtures/ holds two formats behind the same `.log` extension, and
    this script understands only the first. Left alone, `read_text()` raises a
    UnicodeDecodeError on the MTGO fixture whose traceback says nothing about
    the right tool, and the obvious next move from a traceback is `cat` —
    exactly what this script exists to prevent.
    """
    try:
        return path.read_text().splitlines()
    except UnicodeDecodeError:
        sys.exit(
            f"fixture_peek: {path} is not a text fixture. It looks like MTGO's "
            "binary game log, which this script cannot read.\n"
            "  Use the MTGO probe instead (SKILL.md §2b):\n"
            f"    uv run python scripts/mtgo_probe.py {path} --force --lines 400"
        )


def _lexical_entries(path: Path) -> list[_FakeEntry]:
    """Best-effort fallback when sensei_top isn't importable.

    One entry per physical line that looks like a request or a JSON payload
    start; multi-line payloads are NOT reassembled. Strictly worse than the
    real segmenter — exists only so this script degrades instead of failing.
    """
    entries: list[_FakeEntry] = []
    for i, line in enumerate(_read_lines(path), start=1):
        m = _REQ_RE.match(line)
        if m:
            entries.append(_FakeEntry("request", line, m.group(1), None, i))
            continue
        if _JSON_START_RE.match(line):
            entries.append(_FakeEntry("event", line, None, None, i))
    return entries


def _entries(path: Path) -> list[Any]:
    if _HAVE_SEGMENTER:
        return segment_lines(_read_lines(path), locale_hint=_LOCALE_HINT)
    print(
        "fixture_peek: sensei_top not importable — falling back to a lexical "
        "regex index. Run with `uv run python` for the accurate segmenter-based index.",
        file=sys.stderr,
    )
    return _lexical_entries(path)


def cmd_index(args: argparse.Namespace) -> None:
    path = Path(args.fixture)
    entries = _entries(path)
    total_bytes = path.stat().st_size

    print(f"{'#':>4}  {'line':>6}  {'bytes':>7}  {'kind':<9} {'label':<32} timestamp")
    for i, e in enumerate(entries):
        label = (e.label or "-")[:32]
        ts = e.logged_at or "-"
        print(f"{i:>4}  {e.line_number:>6}  {len(e.payload):>7}  {e.kind:<9} {label:<32} {ts}")

    approx_tokens = total_bytes // 4
    print(
        f"\n{len(entries)} entries, {total_bytes} B total in {path.name} "
        f"(~{approx_tokens} tokens to read directly — use `show --entry N` instead)"
    )


def _truncate_json(obj: Any, max_depth: int, depth: int = 0) -> Any:
    """Collapse anything past max_depth, and long lists, to keep output bounded."""
    if depth >= max_depth:
        if isinstance(obj, dict):
            return f"{{...{len(obj)} keys}}"
        if isinstance(obj, list):
            return f"[...{len(obj)} items]"
        return obj
    if isinstance(obj, dict):
        return {k: _truncate_json(v, max_depth, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        max_items = 10
        out = [_truncate_json(v, max_depth, depth + 1) for v in obj[:max_items]]
        if len(obj) > max_items:
            out.append(f"... +{len(obj) - max_items} more")
        return out
    return obj


def cmd_show(args: argparse.Namespace) -> None:
    path = Path(args.fixture)
    entries = _entries(path)
    if not (0 <= args.entry < len(entries)):
        print(
            f"fixture_peek: entry {args.entry} out of range (0..{len(entries) - 1})",
            file=sys.stderr,
        )
        raise SystemExit(1)

    e = entries[args.entry]
    try:
        obj = json.loads(e.payload)
        text = json.dumps(_truncate_json(obj, args.max_depth), indent=2)
    except json.JSONDecodeError:
        text = e.payload  # not JSON (e.g. a bare response marker) — capped below like any text

    if len(text) > args.max_chars and not args.force:
        print(
            f"fixture_peek: entry {args.entry} is {len(text)} chars after truncation to "
            f"depth {args.max_depth}, over the {args.max_chars}-char cap.\n"
            f"Narrow further with a lower --max-depth, or pass --force to print anyway "
            f"(the raw entry is {len(e.payload)} B — that is the real cost of forcing it).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print(
        f"# entry {args.entry} — line {e.line_number}, kind={e.kind}, "
        f"label={e.label}, logged_at={e.logged_at}, raw={len(e.payload)} B"
    )
    print(text if args.force else text[: args.max_chars])


def _collect_types(obj: Any, found: set[str]) -> None:
    """Recursively collect every string value of a "type" key (GRE messages
    nest their message type several levels deep, e.g.
    greToClientEvent.greToClientMessages[].type)."""
    if isinstance(obj, dict):
        t = obj.get("type")
        if isinstance(t, str):
            found.add(t)
        for v in obj.values():
            _collect_types(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _collect_types(v, found)


def cmd_grep(args: argparse.Namespace) -> None:
    path = Path(args.fixture)
    entries = _entries(path)
    needle = args.type.lower()
    matches: list[tuple[int, Any, list[str]]] = []

    for i, e in enumerate(entries):
        if args.kind and e.kind != args.kind:
            continue
        types: set[str] = set()
        with contextlib.suppress(json.JSONDecodeError):
            _collect_types(json.loads(e.payload), types)
        haystacks = {e.label or ""} | types
        if any(needle in h.lower() for h in haystacks):
            matches.append((i, e, sorted(types)))

    if not matches:
        print(f"fixture_peek: no entries matching type~{args.type!r}", file=sys.stderr)
        raise SystemExit(1)

    for i, e, types in matches:
        print(
            f"{i:>4}  line {e.line_number:>6}  label={e.label or '-':<28} "
            f"types={','.join(types) or '-'}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="list every entry's size/kind/label — never the payload")
    p_index.add_argument("fixture")
    p_index.set_defaults(func=cmd_index)

    p_show = sub.add_parser("show", help="print one entry's JSON, capped and depth-truncated")
    p_show.add_argument("fixture")
    p_show.add_argument("--entry", type=int, required=True, help="0-based, from `index`")
    p_show.add_argument("--max-chars", type=int, default=4000)
    p_show.add_argument("--max-depth", type=int, default=4)
    p_show.add_argument("--force", action="store_true", help="print past the char cap")
    p_show.set_defaults(func=cmd_show)

    p_grep = sub.add_parser("grep", help="find entries by GRE message type or label substring")
    p_grep.add_argument("fixture")
    p_grep.add_argument(
        "--type", required=True, help="substring, matched against label and any nested type"
    )
    p_grep.add_argument("--kind", choices=["request", "response", "event"])
    p_grep.set_defaults(func=cmd_grep)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
