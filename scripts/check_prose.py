"""Check the code's and the docs' prose for the three things a script can see.

A plan label goes stale when the plan is forgotten, a line number when the
file changes, and a long AGENTS.md is read in full by every session. This
script keeps those three out; what it cannot see (a comment that copies a
doc, a number copied from a measurement) is the reviewer's, see
`docs/conventions.md`, "Comments and docstrings".

- a plan or phase label (`plan 12`, `phase 3`, `brief §`) in a comment or
  docstring of a tracked `.py` under `src/`, `tests/` and `scripts/`, or in a
  comment of a `.ts`/`.tsx` under `web/src`. String literals are not read: a
  prompt or a log message may say "phase";
- a `path:line` reference to a tracked file of this repository, in any
  tracked text file but the fixtures, the changelog and the generated files.
  A path in another project's tree (`util/steam/config.py:216`) is not
  tracked here, so it is not flagged, nor is a bare name that more than one
  tracked file ends with;
- an AGENTS.md longer than `AGENTS_MAX_LINES`.

A hit that is there on purpose goes in `ALLOW`, with its reason.

    uv run python scripts/check_prose.py

Prints `path:line: kind text` per hit and a count; exits 1 on any hit.
Stdlib only.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_MAX_LINES = 250
# Hits that are there on purpose: text -> reason.
ALLOW: dict[str, str] = {
    "live.py:589": "the rule's own counter-example, docs/conventions.md",
}

LABEL = re.compile(r"\b(?:plan|phase) \d+\b|brief §", re.IGNORECASE)
LINE_REF = re.compile(r"([\w./-]+\.(?:py|ts|tsx|md|sql|css|html)):\d+")
PY_PROSE_DIRS = ("src/", "tests/", "scripts/")
NOT_SCANNED = re.compile(
    r"^tests/fixtures/|^scripts/check_prose\.py$|^tests/test_prose\.py$|"  # their examples must hit
    r"(^|/)CHANGELOG\.md$|^web/src/types/api\.ts$|^web/openapi\.json$"
    r"|(^|/)(uv\.lock|pnpm-lock\.yaml|package-lock\.json)$"
)


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return out.stdout.split("\n")[:-1]


def python_prose(text: str) -> list[tuple[int, str]]:
    """The (line, text) of every comment and docstring in Python source."""
    out: list[tuple[int, str]] = []
    try:
        tree = ast.parse(text)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, tokenize.TokenError):
        return out
    doc_starts = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                doc_starts.add((first.value.lineno, first.value.col_offset))
    for tok in tokens:
        if tok.type == tokenize.COMMENT or (
            tok.type == tokenize.STRING and tok.start in doc_starts
        ):
            out.extend((tok.start[0] + i, ln) for i, ln in enumerate(tok.string.split("\n")))
    return out


def ts_prose(text: str) -> list[tuple[int, str]]:
    """The (line, text) of every `//` and `/* */` comment in TypeScript source."""
    out: list[tuple[int, str]] = []
    i, line, n = 0, 1, len(text)
    quote = ""
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
            elif c == "\n":
                line += 1
                if quote != "`":
                    quote = ""
        elif c in "'\"`":
            quote = c
        elif text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append((line, text[i:end]))
            i = end - 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            for k, ln in enumerate(text[i:end].split("\n")):
                out.append((line + k, ln))
            line += text[i:end].count("\n")
            i = end - 1
        elif c == "\n":
            line += 1
        i += 1
    return out


def label_hits(prose: list[tuple[int, str]]) -> list[tuple[int, str]]:
    return [(n, m.group(0)) for n, ln in prose for m in LABEL.finditer(ln)]


def line_ref_hits(text: str, paths: set[str]) -> list[tuple[int, str]]:
    """References like `live.py:589` whose path is a tracked file here."""
    out = []
    for n, ln in enumerate(text.split("\n"), 1):
        for m in LINE_REF.finditer(ln):
            ref = m.group(1).removeprefix("./")
            ends = [p for p in paths if p == ref or p.endswith("/" + ref)]
            # A bare name two files share (`config.py`) is as likely another project's.
            if len(ends) == 1 or (ref in paths):
                out.append((n, m.group(0)))
    return out


def agents_hit(line_count: int) -> str | None:
    if line_count > AGENTS_MAX_LINES:
        return f"{line_count} lines, ceiling {AGENTS_MAX_LINES}"
    return None


def main() -> int:
    files = tracked()
    paths = set(files)
    hits: list[tuple[str, int, str, str]] = []
    for f in files:
        if NOT_SCANNED.search(f):
            continue
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if f.endswith(".py") and f.startswith(PY_PROSE_DIRS):
            hits += [(f, n, "label", t) for n, t in label_hits(python_prose(text))]
        elif f.startswith("web/src/") and f.endswith((".ts", ".tsx")):
            hits += [(f, n, "label", t) for n, t in label_hits(ts_prose(text))]
        hits += [(f, n, "line-ref", t) for n, t in line_ref_hits(text, paths)]
    agents = ROOT / "AGENTS.md"
    if agents.is_file():
        over = agents_hit(len(agents.read_text(encoding="utf-8").split("\n")) - 1)
        if over:
            hits.append(("AGENTS.md", 1, "length", over))
    shown = [h for h in hits if h[3] not in ALLOW]
    for f, n, kind, text in shown:
        print(f"{f}:{n}: {kind} {text}")
    print(f"{len(shown)} hit(s)")
    return 1 if shown else 0


if __name__ == "__main__":
    sys.exit(main())
