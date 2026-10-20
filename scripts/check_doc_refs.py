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
the fixtures. A name that is missing on purpose (a doc saying what was
removed, a name in another program) goes in `ALLOW`, with its reason.

    uv run python scripts/check_doc_refs.py [PATH ...]

Prints `path:line: kind name - missing` per miss and a count; exits 1 on
any miss. Stdlib only.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
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
    "png", "webp", "ico",
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
    "application_settings": "a file MTGO writes on Windows",
    "LICENSES.chromium.html": "a file electron-builder writes into the build",
    "BxMidrange": "an archetype key in the downloaded corpus",
    "GenericTron": "an archetype key in the downloaded corpus",
    "RubyStorm": "an archetype key in the downloaded corpus",
    "GoryoReanimator": "an archetype key in the downloaded corpus",
    "toLocaleString": "a browser API",
    "SetConsoleCtrlHandler": "a Windows API",
    "open_osfhandle": "a Windows C runtime call",
    "ClaudeBot": "a crawler's user agent, in robots.txt terms",
    "snake_case": "the naming style, not a name",
    "NNN_short_name.sql": "the pattern a migration's file name follows",
}

CODE_SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
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


class Tree:
    def __init__(self) -> None:
        self.files = tracked()
        folders = {
            "/".join(f.split("/")[:i]) for f in self.files for i in range(1, f.count("/") + 1)
        }
        self.paths = set(self.files) | folders
        self.folder_names = {p.rsplit("/", 1)[-1] for p in folders}
        self.text: dict[str, str] = {}
        idents: set[str] = set()
        flags: set[str] = set()
        for f in self.files:
            if NOT_CODE.search(f):
                continue
            try:
                body = (ROOT / f).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            self.text[f] = body
            idents.update(IDENT.findall(body))
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


def main() -> int:
    tree = Tree()
    misses = 0
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
