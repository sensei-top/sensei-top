#!/usr/bin/env python3
"""Deterministic repo map: tree, line counts, top-level symbols — a cheap
substitute for reading files to find out where things live.

Reading every tracked source file in this repo costs roughly 245k tokens.
This script's output costs a few thousand. Use it first; open individual
files (or use `Read` with an offset) only once the map tells you which ones
matter.

    uv run python .claude/skills/navigating-sensei-top/scripts/repo_map.py
    uv run python .claude/skills/navigating-sensei-top/scripts/repo_map.py --path src
    uv run python .claude/skills/navigating-sensei-top/scripts/repo_map.py --max-symbols 12

Symbols are regex matches, not a real parser — good enough to navigate by,
not to analyze by. File list comes from `git ls-files`, so it's exact and
automatically excludes .venv/, node_modules/, data/, and anything gitignored.

A fixed set of files never gets symbol-scanned or content-read by this
script — they're huge, generated, or (for the fixtures) raw captures a naive
scan would choke on. They still appear in the map, by name and line count,
marked [do-not-read] alongside the reader that *is* safe for them. The
fixtures take two different readers: fixture_peek.py for Arena's captures,
scripts/mtgo_probe.py for the binary MTGO one — see SKILL.md.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

EXCLUDE_GLOBS = (
    "uv.lock",
    "web/pnpm-lock.yaml",
    "web/openapi.json",
    "web/src/types/api.ts",
    "tests/fixtures/*.log",
)

FIXTURE_GLOB = "tests/fixtures/*.log"
# Two formats share that one extension. Arena's fixtures are text captures;
# `mtgo_match_session.log` is an MTGO game log — an opaque .NET binary string
# stream — and fixture_peek.py's `read_text()` raises on it before it parses
# anything. Naming the wrong reader here is not a style nit: following the
# annotation lands you at a traceback, and the obvious next move from there is
# `cat`, which is exactly what [do-not-read] exists to prevent.
MTGO_FIXTURE_GLOB = "tests/fixtures/mtgo_*.log"

_PY_SYMBOL_RE = re.compile(r"^(?:async\s+)?def\s+(\w+)|^class\s+(\w+)", re.MULTILINE)
_TS_SYMBOL_RE = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)"
    r"|^export\s+(?:default\s+)?const\s+(\w+)"
    r"|^export\s+(?:default\s+)?class\s+(\w+)"
    r"|^export\s+interface\s+(\w+)"
    r"|^export\s+type\s+(\w+)",
    re.MULTILINE,
)
_SQL_SYMBOL_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"']?(\w+)|ALTER\s+TABLE\s+[\"']?(\w+)",
    re.IGNORECASE,
)
_APP_METHOD_RE = re.compile(r"@(?:app|router)\.(get|post|put|delete|patch)\(")


def _is_excluded(rel: str) -> bool:
    return any(fnmatch(rel, pat) for pat in EXCLUDE_GLOBS)


def _do_not_read_hint(rel: str) -> str:
    """Which safe reader to send someone to for an excluded file."""
    if fnmatch(rel, MTGO_FIXTURE_GLOB):
        return "see scripts/mtgo_probe.py / AGENTS.md"
    if fnmatch(rel, FIXTURE_GLOB):
        return "see fixture_peek.py / AGENTS.md"
    # Lockfiles and generated types have no peek tool — there is nothing in
    # them worth extracting, which is the whole reason they're on the list.
    return "see AGENTS.md"


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(out.stdout.strip())


def _tracked_files(root: Path, scope: str | None) -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=root, check=True)
    files = out.stdout.splitlines()
    if scope:
        prefix = scope.rstrip("/") + "/"
        files = [f for f in files if f.startswith(prefix) or f == scope]
    return sorted(files)


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _extract_routes(text: str) -> list[str]:
    """Special case for api/routes/*.py: HTTP method + path + response_model,
    since the census showed answering an API question needs both the route
    and its (distant) Pydantic model — this puts both in one line.

    These used to all live in ``api/app.py`` as ``@app.get(...)``; the
    architecture-remediation split moved them into one ``APIRouter`` per
    file, so the decorator is ``@router.get(...)`` now and the special case
    keys on the directory rather than that single filename."""
    routes = []
    for m in _APP_METHOD_RE.finditer(text):
        method = m.group(1).upper()
        tail_start = m.end()
        def_m = re.search(r"\n\s*(?:async\s+)?def\s+", text[tail_start:])
        window = text[tail_start : tail_start + (def_m.start() if def_m else 400)]
        path_m = re.search(r'["\']([^"\']+)["\']', window)
        path = path_m.group(1) if path_m else "?"
        resp_m = re.search(r"response_model=([^\n,]+?)(?:,\s*\n|\s*,\s*tags|\s*\))", window)
        resp = resp_m.group(1).strip() if resp_m else ""
        routes.append(f"{method:6} {path}" + (f"  -> {resp}" if resp else ""))
    return routes


def _symbols(rel: str, text: str, max_symbols: int) -> list[str]:
    if rel.endswith(".py"):
        matches = _PY_SYMBOL_RE.findall(text)
        names = [a or b for a, b in matches]
    elif rel.endswith((".ts", ".tsx")):
        matches = _TS_SYMBOL_RE.findall(text)
        names = [next(g for g in groups if g) for groups in matches]
    elif rel.endswith(".sql"):
        matches = _SQL_SYMBOL_RE.findall(text)
        names = [a or b for a, b in matches]
    else:
        return []
    out = names[:max_symbols]
    if len(names) > max_symbols:
        out.append(f"... +{len(names) - max_symbols} more")
    return out


def _format_file(root: Path, rel: str, max_symbols: int) -> str:
    path = root / rel
    name = Path(rel).name
    lines = _count_lines(path)

    if _is_excluded(rel):
        return f"{name:<28} {lines:>5} L  [do-not-read] {_do_not_read_hint(rel)}"

    try:
        text = path.read_text(errors="replace")
    except OSError:
        return f"{name:<28} {lines:>5} L"

    if rel.startswith("src/sensei_top/api/routes/"):
        routes = _extract_routes(text)
        if routes:
            header = f"{name:<28} {lines:>5} L  | {len(routes)} routes:"
            body = "\n".join(f"    {r}" for r in routes)
            return f"{header}\n{body}"

    symbols = _symbols(rel, text, max_symbols)
    suffix = f"  | {', '.join(symbols)}" if symbols else ""
    return f"{name:<28} {lines:>5} L{suffix}"


_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*)")


def _docs_files(root: Path) -> list[str]:
    docs = sorted(p.name for p in (root / "docs").glob("*.md"))
    return [f"docs/{name}" for name in docs] + ["AGENTS.md"]


def _print_docs_outline(root: Path, rel: str) -> None:
    path = root / rel
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        print(f"{rel}  (missing)")
        return

    print(f"{rel} — {len(lines)} L")
    in_fence = False
    for lineno, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if m:
            indent = "  " * (len(m.group(1)) - 2)
            print(f"{indent}{lineno}: {m.group(2).strip()}")


def _build_tree(files: list[str]) -> dict:
    root: dict = {}
    for f in files:
        parts = f.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault(None, []).append(parts[-1])
    return root


def _print_tree(
    root: Path, tree: dict, max_symbols: int, prefix: str = "", rel_prefix: str = ""
) -> None:
    dirs = sorted(k for k in tree if k is not None)
    for d in dirs:
        print(f"{prefix}{d}/")
        _print_tree(root, tree[d], max_symbols, prefix + "  ", f"{rel_prefix}{d}/")
    for fname in sorted(tree.get(None, [])):
        rel = f"{rel_prefix}{fname}"
        line = _format_file(root, rel, max_symbols)
        for part in line.split("\n"):
            print(f"{prefix}{part}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--path", default=None, help="scope to a tracked subdirectory, e.g. src")
    parser.add_argument("--max-symbols", type=int, default=8)
    parser.add_argument(
        "--docs",
        action="store_true",
        help="print a heading outline of docs/*.md + AGENTS.md instead of the repo tree",
    )
    args = parser.parse_args()

    root = _repo_root()

    if args.docs:
        for rel in _docs_files(root):
            _print_docs_outline(root, rel)
        return

    files = _tracked_files(root, args.path)
    if not files:
        print(f"repo_map: no tracked files under {args.path!r}", file=sys.stderr)
        raise SystemExit(1)

    tree = _build_tree(files)
    label = args.path or "."
    print(f"Repo map: {label} — {len(files)} tracked files\n")
    _print_tree(root, tree, args.max_symbols)


if __name__ == "__main__":
    main()
