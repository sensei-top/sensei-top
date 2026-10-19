"""Check that every `docs/<name>.md, "<Section>"` reference still resolves.

A doc is split or a section renamed, and the sentence elsewhere that says
"see docs/<name>.md, 'Y'" quietly points nowhere. Plan 22 (D3) keeps section
titles verbatim when text moves, so a mover only changes the file name, and
this script is the check that says it did.

A reference is a file name followed within 12 characters by a quoted title
(the quote may open on the next line, after comment markers), or a
`file.md#anchor` link. It is a miss when the file is missing, the anchor
matches no heading, or the title is a section reference that does not
resolve. A title that equals or prefixes a heading of any doc is a section reference: it
must equal or prefix a heading of the doc it names, so a title that moved to
another doc is caught. Only a title that is a heading nowhere falls back to
"the phrase occurs in that doc's text", because many quotes are rules or
phrases rather than sections ("one hue for nominal categories").

    uv run python scripts/check_doc_links.py [PATH ...]

Prints `path:line: docs/<name>.md "title" - not found` per miss and a count;
exits 1 on any miss. Stdlib only.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"node_modules", "web_dist", "dist", "release", "__pycache__"}
SCAN = [  # (path, glob patterns)
    ("CLAUDE.md", None),
    (".gitignore", None),
    ("docs", ["*.md"]),
    ("src", ["*.py", "*.sql"]),
    ("web/src", ["*.ts", "*.tsx"]),
    ("scripts", ["*"]),
    ("site", ["*.html", "*.css", "*.js"]),
    ("tests", ["*.py"]),
    ("desktop/README.md", None),
    ("desktop/src", ["*"]),
    ("desktop/server", ["*.spec"]),
    (".claude/skills", ["*"]),
    (".claude/agents", ["*"]),
]
REF = re.compile(r"(?:docs/|(?<![\w/.-]))([\w-]+)\.md(?:#([\w-]+))?")
COMMENT = re.compile(r"^[\s>*#/-]+")
QUOTES = '"“”'


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "")).strip().lower()


def slug(heading: str) -> str:
    s = re.sub(r"[^\w\s-]", "", heading.replace("`", "").lower())
    return re.sub(r"\s", "-", s.strip())


def files(paths: list[str] | None) -> Iterator[Path]:
    if paths:
        for p in paths:
            q = Path(p)
            yield from [q] if q.is_file() else sorted(x for x in q.rglob("*") if x.is_file())
        return
    for name, pats in SCAN:
        base = ROOT / name
        if pats is None:
            if base.is_file():
                yield base
            continue
        for pat in pats:
            yield from sorted(x for x in base.rglob(pat) if x.is_file())


Doc = tuple[str, list[str], set[str]]  # normalized text, normalized headings, slugs


def target(name: str, cache: dict[str, Doc | None]) -> Doc | None:
    if name not in cache:
        p = ROOT / "docs" / f"{name}.md"
        if not p.is_file():
            cache[name] = None
        else:
            text = p.read_text(encoding="utf-8", errors="replace")
            heads = [m.group(1) for m in re.finditer(r"^#{1,6} +(.+?)\s*$", text, re.M)]
            cache[name] = (norm(text), [norm(h) for h in heads], {slug(h) for h in heads})
    return cache[name]


def all_headings() -> set[str]:
    out: set[str] = set()
    for p in (ROOT / "docs").rglob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"^#{1,6} +(.+?)\s*$", text, re.M):
            out.add(norm(m.group(1)))
    return out


def title_ok(title: str, doc: Doc, every_heading: set[str]) -> bool:
    t = norm(title)
    text, heads, _ = doc
    if any(h.startswith(t) for h in every_heading):
        return any(h.startswith(t) for h in heads)
    return t in text


def read_title(lines: list[str], i: int, rest: str) -> str | None:
    """The quoted title that follows a reference, or None when none does."""
    q = re.match(
        rf"(?:(?![.!?]\s)[^{QUOTES}\\\n]){{1,12}}[{QUOTES}]([^{QUOTES}]*)([{QUOTES}]?)", rest
    )
    nxt = i + 1 < len(lines)
    if q is None and nxt and re.fullmatch(rf"[^{QUOTES}\\\w]{{0,12}}", re.sub(r"^`?'s", "", rest)):
        # the file name ends the line and the title opens the next one
        cand = COMMENT.sub("", lines[i + 1])
        q = re.match(rf"[{QUOTES}]([^{QUOTES}]*)([{QUOTES}]?)", cand)
        if q is None:
            return None
        i += 1
        nxt = i + 1 < len(lines)
    if q is None:
        return None
    title = q.group(1)
    if not q.group(2) and nxt:
        title = re.split(rf"[{QUOTES}]", title + " " + COMMENT.sub("", lines[i + 1]))[0]
    return title.strip()


def main() -> int:
    cache: dict[str, Doc | None] = {}
    every_heading = all_headings()
    misses: list[str] = []

    def miss(shown: Path, i: int, what: str) -> None:
        print(f"{shown}:{i + 1}: {what}")
        misses.append(what)

    for path in files(sys.argv[1:] or None):
        if SKIP & set(path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
        except (UnicodeDecodeError, OSError):
            continue
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        for i, line in enumerate(lines):
            for m in REF.finditer(line):
                name = m.group(1)
                if (
                    not m.group(0).startswith("docs/")
                    and not (ROOT / "docs" / f"{name}.md").is_file()
                ):
                    continue  # a bare name only counts when it is a doc
                title = read_title(lines, i, line[m.end() :]) or ""
                if not title and not m.group(2):
                    continue  # no title and no anchor: nothing to check
                label = f"docs/{name}.md"
                doc = target(name, cache)
                if doc is None:
                    miss(shown, i, f'{label} "{title}" - missing file')
                elif m.group(2) and m.group(2) not in doc[2]:
                    miss(shown, i, f"{label}#{m.group(2)} - not found")
                elif title and not title_ok(title, doc, every_heading):
                    miss(shown, i, f'{label} "{title}" - not found')

    print(f"{len(misses)} miss(es)")
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
