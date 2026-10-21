"""Check BACKLOG.md's register and every reference to one of its items.

An item is a heading `### BL-NNN · <title>` (middle dot) and, as the next
non-blank line, a label line `type: X · priority: P · status: S · area: a b`.
The vocabularies below are the ones BACKLOG.md's head documents; `area` holds
one or more values. The head carries `Next ID: BL-NNN`, which must be greater
than every item's ID.

- an ID that is malformed or used twice;
- a missing, incomplete or unknown label line;
- a `Next ID` that is missing or not above every ID;
- a `BL-NNN` in a tracked text file that names no item. Exempt: the
  changelog, BACKLOG.md's own `Next ID` line, this script and its test (their
  examples must hit).

A hit that is there on purpose goes in `ALLOW`, with its reason.

    uv run python scripts/check_backlog.py

Prints `path:line: kind text` per hit and a count; exits 1 on any hit.
Stdlib only.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "BACKLOG.md"
# Hits that are there on purpose: text -> reason.
ALLOW: dict[str, str] = {}

VOCAB: dict[str, frozenset[str]] = {
    "type": frozenset({"feat", "fix", "perf", "refactor", "docs", "chore"}),
    "priority": frozenset({"P1", "P2", "P3"}),
    "status": frozenset({"ready", "needs-decision", "needs-data", "blocked", "in-progress"}),
    "area": frozenset(
        [
            "reader",
            "projector",
            "mtgo",
            "table",
            "api",
            "web",
            "desktop",
            "site",
            "review",
            "guide",
            "brief",
            "coach",
            "archetypes",
            "metagame",
            "cards",
            "llm",
            "i18n",
            "backup",
            "docs",
            "release",
            "legal",
            "cli",
        ]
    ),
}
HEADING = re.compile(r"^### (BL-\d{3}) · \S")
ANY_ITEM_HEADING = re.compile(r"^### BL-")
NEXT_ID = re.compile(r"^Next ID: BL-(\d{3})\s*$")
REF = re.compile(r"\bBL-\d{3}\b")
NOT_SCANNED = re.compile(
    r"^tests/fixtures/|^scripts/check_backlog\.py$|^tests/test_backlog\.py$"
    r"|(^|/)CHANGELOG\.md$|^web/src/types/api\.ts$|^web/openapi\.json$"
    r"|(^|/)(uv\.lock|pnpm-lock\.yaml|package-lock\.json)$"
)

Hit = tuple[int, str, str]


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return out.stdout.split("\n")[:-1]


def label_problem(line: str) -> str | None:
    """Why a label line is wrong, or None."""
    seen: dict[str, str] = {}
    for part in line.split(" · "):
        key, sep, value = part.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or key not in VOCAB:
            return f"unknown key in {part!r}"
        if key in seen:
            return f"repeated key {key}"
        values = value.split()
        if not values:
            return f"empty {key}"
        if key != "area" and len(values) != 1:
            return f"{key} takes one value"
        for v in values:
            if v not in VOCAB[key]:
                return f"unknown {key} {v!r}"
        seen[key] = value
    missing = [k for k in VOCAB if k not in seen]
    return f"missing {', '.join(missing)}" if missing else None


def register_hits(text: str) -> tuple[list[Hit], set[str]]:
    """The hits in a register's own text, and the IDs it defines."""
    lines = text.split("\n")
    hits: list[Hit] = []
    ids: dict[str, int] = {}
    for i, ln in enumerate(lines):
        n = i + 1
        if not ANY_ITEM_HEADING.match(ln):
            continue
        m = HEADING.match(ln)
        if not m:
            hits.append((n, "heading", ln))
            continue
        if m.group(1) in ids:
            hits.append((n, "duplicate-id", m.group(1)))
        ids.setdefault(m.group(1), n)
        nxt = next((x for x in lines[i + 1 :] if x.strip()), "")
        if not nxt or nxt.startswith("#"):
            hits.append((n, "label", f"{m.group(1)} has no label line"))
        elif (why := label_problem(nxt)) is not None:
            hits.append((n, "label", f"{m.group(1)}: {why}"))
    nexts = [(i + 1, NEXT_ID.match(ln)) for i, ln in enumerate(lines) if ln.startswith("Next ID")]
    if not nexts:
        hits.append((1, "next-id", "no `Next ID: BL-NNN` line"))
    for n, m in nexts:
        if m is None:
            hits.append((n, "next-id", lines[n - 1]))
        elif ids and int(m.group(1)) <= max(int(x[3:]) for x in ids):
            hits.append((n, "next-id", f"{lines[n - 1]} is not above {max(ids)}"))
    return hits, set(ids)


def dangling_hits(text: str, ids: set[str], *, register: bool = False) -> list[Hit]:
    """Each `BL-NNN` in `text` that names no item; `register` exempts `Next ID` lines."""
    out = []
    for n, ln in enumerate(text.split("\n"), 1):
        if register and ln.startswith("Next ID"):
            continue
        out += [(n, "dangling", m.group(0)) for m in REF.finditer(ln) if m.group(0) not in ids]
    return out


def collect(register: Path, files: dict[str, str]) -> list[tuple[str, int, str, str]]:
    """Every hit, given the register's path and {path: text} of the files to scan."""
    reg_text = register.read_text(encoding="utf-8")
    rhits, ids = register_hits(reg_text)
    hits = [(register.name, n, k, t) for n, k, t in rhits]
    hits += [(register.name, n, k, t) for n, k, t in dangling_hits(reg_text, ids, register=True)]
    for path, text in files.items():
        if path == register.name or NOT_SCANNED.search(path):
            continue
        hits += [(path, n, k, t) for n, k, t in dangling_hits(text, ids)]
    return hits


def tree_files() -> dict[str, str]:
    out = {}
    for f in tracked():
        try:
            out[f] = (ROOT / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return out


def main() -> int:
    if not REGISTER.is_file():
        print("BACKLOG.md: missing the register")
        return 1
    hits = collect(REGISTER, tree_files())
    shown = [h for h in hits if h[3] not in ALLOW]
    for f, n, kind, text in shown:
        print(f"{f}:{n}: {kind} {text}")
    print(f"{len(shown)} hit(s)")
    return 1 if shown else 0


if __name__ == "__main__":
    sys.exit(main())
