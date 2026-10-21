"""Check that every name a doc puts in backticks still exists in the tree.

A file moves, a function is renamed, a route or a flag goes, and the doc
that names it goes on naming it. `check_doc_links.py` covers references
from one doc to another; this script covers references from a doc to the
code. It reads the inline code spans of every doc (and the command lines in
its fenced blocks) and tests each name it can classify:

- a path (`web/src/shell/Rail.tsx`, `shell/Rail.tsx`, `migrations/NNN_*.sql`):
  a tracked file or folder ends with it; `<x>`, `{x}`, `NNN` and `*` match
  anything. Only a path that starts with a folder the tree has is tested,
  so a branch (`feature/<topic>`) or another program's folder is not, and
  a bare file name only with a source extension (`Rail.tsx`, not
  `Player.log`). A folder git ignores on purpose (`data/`, `dist/`)
  passes, and so does `module/file.symbol` when `module/file.py` has it;
- `path::symbol`: the path, and the symbol as an identifier in that file;
- a route (`/api/decks/{id}`, `GET …/rcq/markdown`): a path in
  `web/src/types/api.ts`, generated from the API's schema;
- a flag (`--watch`): written somewhere in the code, or one of `EXTERNAL`'s;
- an identifier that cannot be an English word, snake_case or camelCase
  (`key_card_timing`, `useDensity`, `CopyPromptCard`): an identifier
  somewhere in the code. Dotted and called forms (`shell.density`,
  `placeAt(pathname)`) are tested part by part.

"The code" is every tracked text file but the Markdown, the lockfiles and
the fixtures, with the comments and docstrings of Python and the `//` and
`/* */` comments of TypeScript and JavaScript blanked: a comment that names
a symbol does not make the symbol exist. String literals stay code (SQL,
JSON keys, route strings). A name that is missing on purpose (a doc saying
what was removed, a name in another program) goes in `ALLOW`, with its reason.

The same spans in the comments and docstrings of `src/`, `tests/`, `scripts/`
and `web/src` are read too, but only paths, `path::symbol` and routes are
checked there, not bare names: those are mostly another library's
(`model_validate`) or Arena's (`GameOver`), and a name that exists but is the
wrong one cannot be told from the right one. Both single and RST double
backticks open a span.

    uv run python scripts/check_doc_refs.py [PATH ...]

Prints `path:line: kind name - missing` per miss and a count; exits 1 on
any miss. Stdlib only.
"""

from __future__ import annotations

import ast
import fnmatch
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [
    "AGENTS.md",
    "README.md",
    "ROADMAP.md",
    "INSTALL.md",
    "CONTRIBUTING.md",
    "desktop/README.md",
    "web/README.md",
    "docs",
    ".claude/skills/navigating-sensei-top/SKILL.md",
]
# Folders and files the tree never tracks, but a doc names because the app or
# a build writes them.
IGNORED = {"data", "logs", "handoffs", "web_dist", "dist", "build", "release", ".venv",
           "node_modules", "openapi.json"}  # fmt: skip
NOT_CODE = re.compile(
    r"(\.md|\.lock|pnpm-lock\.yaml|\.(png|webp|jpg|ico|woff2?|ttf|dat|db|mo|pdf|svg|gif))$"
    r"|^tests/fixtures/"
    r"|^tests/test_doc_refs\.py$"  # its made-up names must stay missing
)
SOURCE = ("py", "ts", "tsx", "mjs", "js", "sql", "css", "html", "spec")
EXTENSIONS = (
    "py", "ts", "tsx", "mjs", "js", "json", "sql", "md", "toml", "css", "html", "yml",
    "yaml", "spec", "txt", "pot", "po", "log", "db", "sh", "ps1", "cfg", "ini", "svg",
    "png", "webp", "ico", "xml", "jsonl", "dek",
)  # fmt: skip
# Flags of other programs a doc quotes: git, pnpm, uv, pytest, the browser.
EXTERNAL = {
    "--no-ff", "--force", "--global", "--dir", "--frozen", "--frozen-lockfile", "--help",
    "--version", "--collect-only", "--history",
    "--no-sandbox", "--appimage-extract-and-run",  # Electron and the AppImage runtime
}  # fmt: skip
# Names a doc gives on purpose although the code has none: name -> reason.
REMOVED = "named as what was removed or replaced"
ARENA = "a name in Arena's log that no fixture carries"
ALLOW: dict[str, str] = {
    "docs/draft.md": "at the archive/draft tag, in the pre-public history",
    "projector/draft.py": "at the archive/draft tag, in the pre-public history",
    "advisor.py": REMOVED,
    "HintsPanel": REMOVED,
    "HintsPanel.tsx": REMOVED,
    "NextDrawsCard.tsx": REMOVED,
    "table/history.py": REMOVED,
    "RecentOpponentsCard": REMOVED,
    "RecentOpponentsCard.tsx": REMOVED,
    "AskClaudeCard": REMOVED,
    "useDraft": REMOVED,
    "site/help/tour/": "planned, not built (docs/status.md)",
    "site/pt-br/help/tour/": "planned, not built (docs/status.md)",
    "gameObject": ARENA,
    "EnterSideboardingReq": ARENA,
    "SubmitDeckReq": ARENA,
    "CardPool": ARENA,
    "CourseDeckSummary": ARENA,
    "QuestGetQuests": ARENA,
    "PeriodicRewardsGetStatus": ARENA,
    "TimerStateMessage": ARENA,
    "QueuedGameStateMessage": ARENA,
    "EventEnterPairing": ARENA,
    "ZoneTransfer": "an Arena annotation type, carried in the log as AnnotationType_ZoneTransfer",
    "SubmitDeckConfirmation": ARENA,
    "GameComplete": ARENA,
    "MatchComplete": ARENA,
    "MatchCompleted": ARENA,
    "IntermissionReq": ARENA,
    "ConnectResp": ARENA,
    "SingleElimination": ARENA,
    "CardsRealm": "a source that was never evaluated, named for why it is absent",
    "CacheItem": "the shape of another program's cache, which TopDeck's response is rewritten into",
    "application_settings": "a file MTGO writes on Windows",
    "mtgo_game_history": "a file MTGO writes on Windows",
    "LICENSES.chromium.html": "a file electron-builder writes into the build",
    "BxMidrange": "an archetype key in the downloaded corpus",
    "GenericTron": "an archetype key in the downloaded corpus",
    "RubyStorm": "an archetype key in the downloaded corpus",
    "GoryoReanimator": "an archetype key in the downloaded corpus",
    "toLocaleString": "a browser API",
    "SetConsoleCtrlHandler": "a Windows API",
    "open_osfhandle": "a Windows C runtime call",
    "ClaudeBot": "a crawler's user agent, in robots.txt terms",
    "docs/AUTHORS": "a made-up path, the example of a file that gets no exemption",
    "path::symbol": "the form of a reference, not a name",
    "snake_case": "the naming style, not a name",
    "NNN_short_name.sql": "the pattern a migration's file name follows",
}

CODE_SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
PROSE_SPAN = re.compile(r"``([^`\n]+)``|(?<!`)`([^`\n]+)`(?!`)")
PROSE_DIRS = ("src/", "tests/", "scripts/", "web/src/")
PROSE_KINDS = {"path", "symbol", "route"}
GENERATED = {"web/src/types/api.ts"}
# Files whose prose quotes names on purpose: this script's own examples.
PROSE_EXEMPT = {"scripts/check_doc_refs.py"}
# A span a path, symbol or route can start with: not `[::1]`, `::`, `http://...`.
PROSE_START = re.compile(r"[A-Za-z_./~*<{…-]")
METHOD = re.compile(r"^(?:GET|POST|PUT|PATCH|DELETE) +")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
COMMAND = re.compile(r"(?:^|\s)(?:uv run )?(?:sensei-top|python scripts/|scripts/|pnpm shots)")


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return out.stdout.split("\n")[:-1]


def docs(paths: list[str] | None) -> Iterator[Path]:
    for name in paths or DOCS:
        p = ROOT / name if not Path(name).is_absolute() else Path(name)
        yield from [p] if p.is_file() else sorted(p.rglob("*.md"))


def is_name(word: str) -> bool:
    """True when a word cannot be English: snake_case, or camelCase/PascalCase."""
    if len(word) < 4 or word.isupper():
        return False
    if re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)+", word):
        return True
    return bool(re.fullmatch(r"[A-Za-z][a-z0-9]+(?:[A-Z][a-z0-9]+)+", word))


def glob_of(text: str) -> str:
    text = text.replace("**/", "*")
    text = re.sub(r"<[^>]*>|\{[^}]*\}|NNN(?=_|\b)|\bX\.Y\.Z\b|…|\.\.\.", "*", text)
    return re.sub(r"\*+", "*", text)


def blank(text: str, spans: list[tuple[int, int]]) -> str:
    """The text with each [start, end) offset range spaced out, newlines kept."""
    out = list(text)
    for a, b in spans:
        for i in range(a, b):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def py_prose(body: str) -> list[tuple[int, int, int]] | None:
    """The (line, start, end) of each comment and docstring, or None if it won't parse."""
    try:
        module = ast.parse(body)
        tokens = list(tokenize.generate_tokens(io.StringIO(body).readline))
    except (SyntaxError, tokenize.TokenError, IndentationError):
        return None
    starts = [0]
    for line in body.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    docs_at = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            first = node.body[0] if node.body else None
            value = getattr(first, "value", None)
            is_str = isinstance(value, ast.Constant) and isinstance(value.value, str)
            if isinstance(first, ast.Expr) and is_str:
                docs_at.add((first.lineno, first.col_offset))
    found = []
    for tok in tokens:
        is_doc = tok.type == tokenize.STRING and tok.start in docs_at
        if tok.type == tokenize.COMMENT or is_doc:
            a = starts[tok.start[0] - 1] + tok.start[1]
            b = starts[tok.end[0] - 1] + tok.end[1]
            found.append((tok.start[0], a, b))
    return found


def js_prose(body: str) -> list[tuple[int, int, int]]:
    """The (line, start, end) of each `//` and `/* */` comment, strings skipped."""
    found = []
    i, line, n = 0, 1, len(body)
    while i < n:
        c = body[i]
        if c == "\n":
            line += 1
        elif c in "'\"`":
            j = i + 1
            while j < n and body[j] != c and not (c != "`" and body[j] == "\n"):
                if body[j] == "\\":
                    j += 1
                line += body[j : j + 1] == "\n"
                j += 1
            i = j
        elif body.startswith("//", i):
            j = body.find("\n", i)
            j = n if j < 0 else j
            found.append((line, i, j))
            i = j - 1
        elif body.startswith("/*", i):
            j = body.find("*/", i + 2)
            j = n if j < 0 else j + 2
            found.append((line, i, j))
            line += body.count("\n", i, j)
            i = j - 1
        i += 1
    return found


def prose_of(path: str, body: str) -> list[tuple[int, int, int]]:
    """Where a file's comments and docstrings are; empty for a kind it cannot read."""
    if path.endswith(".py"):
        return py_prose(body) or []
    if path.endswith((".ts", ".tsx", ".js", ".mjs")):
        return js_prose(body)
    return []


def code_only(path: str, body: str) -> str:
    """The file's text with its comments and docstrings blanked."""
    if path.endswith(".py"):
        found = py_prose(body)
        return body if found is None else blank(body, [(a, b) for _, a, b in found])
    return blank(body, [(a, b) for _, a, b in prose_of(path, body)])


def prose_lines(path: str, body: str) -> Iterator[tuple[int, str]]:
    """(line number, text) for each line of a file's comments and docstrings."""
    for line, a, b in prose_of(path, body):
        for k, text in enumerate(body[a:b].split("\n")):
            yield line + k, text


class Tree:
    def __init__(self) -> None:
        self.files = tracked()
        folders = {
            "/".join(f.split("/")[:i]) for f in self.files for i in range(1, f.count("/") + 1)
        }
        self.paths = set(self.files) | folders
        self.folder_names = {p.rsplit("/", 1)[-1] for p in folders}
        self.text: dict[str, str] = {}  # code only: comments and docstrings blanked
        self.prose: dict[str, str] = {}  # the same files, whole
        idents: set[str] = set()
        flags: set[str] = set()
        for f in self.files:
            if NOT_CODE.search(f):
                continue
            try:
                body = (ROOT / f).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            self.prose[f] = body
            code = code_only(f, body)
            self.text[f] = code
            idents.update(IDENT.findall(code))
            flags.update(FLAG.findall(body))
        # The client's own names (message types, fields) are in its logs.
        for f in self.files:
            if f.startswith("tests/fixtures/") and f.endswith(".log"):
                text = (ROOT / f).read_text(encoding="utf-8", errors="replace")
                idents.update(IDENT.findall(text))
        self.idents = idents
        self.flags = flags
        types = (ROOT / "web/src/types/api.ts").read_text(encoding="utf-8")
        paths = re.findall(r'^    "(/api/[^"]+)": \{', types, re.M)
        self.routes = [re.sub(r"\{[^}]*\}", "*", r) for r in paths]

    def checked(self, name: str) -> bool:
        """True when a path is one this tree should have."""
        head = name.split("/")[0]
        if "/" not in name.rstrip("/"):
            return name.rsplit(".", 1)[-1] in SOURCE or name.rstrip("/") in self.folder_names
        return head in self.folder_names or head in {"src", "web", "tests", "docs", "site"}

    def path(self, name: str) -> bool:
        name = re.sub(r":\d+(?:-\d+)?$", "", name).removeprefix("./").rstrip("/")
        if IGNORED & set(name.split("/")):
            return True
        stem, _, attr = name.rpartition(".")
        if "/" in name and stem and "/" not in attr and attr not in EXTENSIONS:
            # `guide/play.key_card_timing` or `rcq/PreviewCard`: a module and a name in it
            return any(self.symbol(f"{stem}.{x}", attr) for x in SOURCE)
        if "." not in name.rsplit("/", 1)[-1] and not self.find(name):
            return any(self.find(f"{name}.{x}") for x in SOURCE)
        return self.find(name)

    def find(self, name: str) -> bool:
        pat = glob_of(name)
        if "*" not in pat:
            return name in self.paths or any(p.endswith("/" + name) for p in self.paths)
        return any(fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, "*/" + pat) for p in self.paths)

    def symbol(self, path: str, sym: str) -> bool:
        hits = [f for f in self.text if f == path or f.endswith("/" + path)]
        words = IDENT.findall(sym)
        return any(all(re.search(rf"\b{w}\b", self.text[f]) for w in words) for f in hits)

    def route(self, name: str) -> bool:
        pat = glob_of(re.sub(r":\w+", "*", name.split("?")[0]).rstrip("/"))
        return any(fnmatch.fnmatch(r, pat) or fnmatch.fnmatch(r, "*" + pat) for r in self.routes)


def looks_like_path(span: str) -> bool:
    if span.startswith(("/", "~", "http", "$", "%")) or "\\" in span or ":/" in span:
        return False
    if "/" in span and re.fullmatch(r"[\w.*<>{}/@+-]+(?::\d+(?:-\d+)?)?", span):
        return True
    return bool(re.fullmatch(rf"[\w.*<>{{}}-]+\.(?:{'|'.join(EXTENSIONS)})", span))


def check(span: str, tree: Tree) -> list[tuple[str, str]]:
    """The (kind, name) pairs in one code span that the tree does not have."""
    span = span.strip()
    if span in ALLOW:
        return []
    route = METHOD.sub("", span)
    if route.startswith(("/api/", "…/", ".../")) and route != "/api/":
        return [] if tree.route(route) else [("route", route)]
    if "::" in span and " " not in span:
        path, sym = span.split("::", 1)
        if not tree.path(path):
            return [("path", path)]
        return [] if tree.symbol(path, sym) else [("symbol", span)]
    if looks_like_path(span):
        return [] if not tree.checked(span) or tree.path(span) else [("path", span)]
    if FLAG.fullmatch(span.split("=")[0].split(" ")[0]) and " " not in span:
        flag = span.split("=")[0]
        return [] if flag in tree.flags or flag in EXTERNAL else [("flag", flag)]
    if COMMAND.search(span):
        return command(span, tree)
    call = re.fullmatch(r"([\w.]+)\(.*\)", span)
    word = call.group(1) if call else span
    if re.fullmatch(r"[\w.]+", word):
        return [("name", w) for w in word.split(".") if is_name(w) and w not in tree.idents]
    return []


def command(line: str, tree: Tree) -> list[tuple[str, str]]:
    out = [("flag", f) for f in FLAG.findall(line) if f not in tree.flags and f not in EXTERNAL]
    for word in line.split():
        if word.startswith("scripts/") and not tree.path(word):
            out.append(("path", word))
    return out


def prose_misses(tree: Tree) -> Iterator[tuple[str, int, str, str]]:
    """(path, line, kind, name) for each stale path, symbol or route in code prose."""
    for f, body in tree.prose.items():
        if not f.startswith(PROSE_DIRS) or f in GENERATED or f in PROSE_EXEMPT:
            continue
        for line, text in prose_lines(f, body):
            for a, b in PROSE_SPAN.findall(text):
                span = (a or b).strip()
                if not PROSE_START.match(span) or span.startswith("http") or "://" in span:
                    continue
                for kind, name in check(span, tree):
                    if kind == "route" and not name.startswith("/api/"):
                        continue  # an elided `…/x` is a message or a file there, not a route
                    if kind in PROSE_KINDS and name not in ALLOW:
                        yield f, line, kind, name


def main() -> int:
    tree = Tree()
    misses = 0
    if not sys.argv[1:]:
        for f, line, kind, name in prose_misses(tree):
            print(f"{f}:{line}: {kind} {name} - missing")
            misses += 1
    for doc in docs(sys.argv[1:] or None):
        shown = doc.relative_to(ROOT) if doc.is_relative_to(ROOT) else doc
        fenced = False
        for i, line in enumerate(doc.read_text(encoding="utf-8").split("\n")):
            if line.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if fenced or line.startswith("    "):
                found = command(line, tree) if COMMAND.search(line) else []
            else:
                found = [m for span in CODE_SPAN.findall(line) for m in check(span, tree)]
            for kind, name in found:
                if name in ALLOW:
                    continue
                print(f"{shown}:{i + 1}: {kind} {name} - missing")
                misses += 1
    print(f"{misses} miss(es)")
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
