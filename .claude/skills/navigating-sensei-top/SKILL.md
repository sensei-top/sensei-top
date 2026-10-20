---
name: navigating-sensei-top
description: Navigates and verifies the sensei-top repo without burning context. Generates a compact repo map (tree, line counts, symbols, API routes) instead of reading files wholesale; indexes and extracts single events from the very large log fixtures in tests/fixtures/ instead of reading them directly, routing to the right reader for each of the two formats there (Arena text captures, and the binary MTGO game log); runs the ruff/pytest/pnpm-lint loop with output bounded per line. Use before exploring this codebase or locating a function, route, analyzer, or migration; ALWAYS before reading anything under tests/fixtures/, since those files are hundreds of KB with single lines up to 50,000 characters and one of them is not text at all; and when running the "Before you finish" checks from AGENTS.md.
---

# Navigating sensei-top

Three scripts, each replacing a way of burning context with a script whose
*output* is cheap — plus one that already lives in the repo,
`scripts/mtgo_probe.py` (§2b), and one that measures what the sessions
themselves cost (§4). Run all of them with `uv run python` from the
repo root — `fixture_peek.py` imports `sensei_top` and needs it.

## 1. Repo map — before exploring

`tests/fixtures/*.log` aside, this repo's tracked text is about 8 MB, far
more than any context. The full map is about 90 KB (~22k tokens), so start
with `--path` on the directory you need (a few KB), and run the bare map
only when you don't know where to look.

    uv run python .claude/skills/navigating-sensei-top/scripts/repo_map.py
    uv run python .claude/skills/navigating-sensei-top/scripts/repo_map.py --path src/sensei_top/review
    uv run python .claude/skills/navigating-sensei-top/scripts/repo_map.py --max-symbols 12

Output is a tree with per-file line counts and top-level symbols (functions,
classes, SQL tables). Files under `src/sensei_top/api/routes/` get special
handling: instead of generic symbols they list every route (method, path,
response_model), because the route decorator and its Pydantic model often
sit far apart.

Symbols come from regexes, not a parser — good for navigation, not analysis.
**Escalation ladder:** map first → `Read` the one file the map points at
(with an offset if it's large) → `grep` if you need every occurrence of
something specific. Read a section, never a whole doc or a whole large
module: `Read` with `offset`/`limit`, or a bounded `sed -n 'A,Bp'` when the
range is known. An unbounded `cat` or `sed` of a doc is the most common
waste measured (shell reads of `.md` were 28 % of main-session Bash output,
week of 2026-10-13).
Scope a grep before pulling full matching lines: `grep -l` or `-c` to find
which files matter, or pipe to `head`, then read only what you need.

    uv run python .claude/skills/navigating-sensei-top/scripts/repo_map.py --docs

Prints, for every `docs/*.md` file plus `AGENTS.md`, its line count and every
`##`/`###` heading with its 1-indexed line number — use it to `Read` a single
doc section with `offset`/`limit` instead of loading a whole doc (the largest run 65–77 KB).

A fixed set of generated/huge files never gets symbol-scanned; they show up
in the map as a name and line count tagged `[do-not-read]`
(`uv.lock`, `web/pnpm-lock.yaml`, `web/openapi.json`,
`web/src/types/api.ts`, `tests/fixtures/*.log`). Presence in the map is
useful; their contents are the hazard. The tag names the safe reader where
one exists — `fixture_peek.py` for an Arena fixture, `scripts/mtgo_probe.py`
for the MTGO one.

## 2. Fixture peek — ALWAYS, for tests/fixtures/*.log

`tests/fixtures/` holds **two formats behind the same `.log` extension**, and
they take different readers. Everything except `mtgo_match_session.log` is an
Arena text capture — use `fixture_peek.py`, below. `mtgo_match_session.log` is
an MTGO game log, an opaque .NET binary string stream that `fixture_peek.py`
**cannot read at all**; use `scripts/mtgo_probe.py` for that one, §2b. (Point
`fixture_peek.py` at it anyway and it exits with that pointer rather than a
`UnicodeDecodeError` traceback — the fix for a traceback is never `cat`.)

**Never `Read`, `cat`, or `head` either kind directly.** The Arena captures
are a few dozen lines, but individual lines run past 50,000 characters (a
single `GreToClientEvent`), so `head -20` still pulls in whichever multi-line
JSON payload those 20 lines happen to contain, which can be the whole
150k-token file. The MTGO fixture isn't text at all.

    uv run python .claude/skills/navigating-sensei-top/scripts/fixture_peek.py \
        index tests/fixtures/match_session.log

Lists every entry — line number, byte size, kind, label, timestamp — for a
few thousand bytes total. Then pull exactly one:

    uv run python .claude/skills/navigating-sensei-top/scripts/fixture_peek.py \
        show tests/fixtures/match_session.log --entry 11

    uv run python .claude/skills/navigating-sensei-top/scripts/fixture_peek.py \
        grep tests/fixtures/combat_session.log --type GameStateMessage

`show` depth-truncates nested JSON (`--max-depth`, default 4) and refuses to
print past `--max-chars` (default 4000) unless you pass `--force` — at which
point it tells you the real byte cost first. `grep` finds entries by GRE
message type (searched recursively — types nest inside
`greToClientEvent.greToClientMessages[].type`) or by label.

### 2b. MTGO probe — for tests/fixtures/mtgo_*.log

`scripts/mtgo_probe.py` lives in the repo rather than in this skill — it was
written as MTGO recon, to establish what that container format even was — but
it is the MTGO fixture's `fixture_peek.py`, and was built to the same
discipline on purpose (its own docstring says so). It decodes the .NET
`BinaryWriter` string stream and prints the transcript, bounded by default.

    uv run python scripts/mtgo_probe.py tests/fixtures/mtgo_match_session.log \
        --force --lines 400

Caps are `--lines` (80) and `--chars` (6000); `--force` lifts both. The whole
fixture is one ~7.8 KB match, so `--force --lines 400` is the invocation that
actually shows you a full transcript — safe here precisely *because* it is
small, which is not a licence to `--force` a bigger one.

Output is a format-detection header, then the decoded string stream one
string per line: prose like `Player1 chooses to play first.`,
`Turn 1: Player1`, with card names as `@[Card Name@:ID1,ID2:@]` and handles
as `@PHandle`. Stray length-prefix bytes leak in at the start of some lines
(`3@PPlayer1 begins the game…`) — that's the container framing, not content.
It prints no line numbers, so pipe it through `nl -ba` when you need stable
ones to cite the way you'd cite a `fixture_peek.py` entry number.

Both scripts are the mechanism behind AGENTS.md non-negotiable #8 ("derive
test expectations from the data"): read the fixture through the one that
matches its format — `fixture_peek.py` for Arena, `mtgo_probe.py` for MTGO —
never a direct file read, and never by running the parser and copying its
output into an assertion.

## 3. Verify — before finishing, and on any failure

A clean run of AGENTS.md's "Before you finish" loop is already cheap
(~11 lines). The risk is a *failing* run: pytest assertions here compare
against fixture-derived payloads, and an unbounded diff can dump tens of
thousands of characters.

    uv run python .claude/skills/navigating-sensei-top/scripts/verify.py
    uv run python .claude/skills/navigating-sensei-top/scripts/verify.py --full   # + pnpm build

Runs `ruff check .`, `pytest -q`, `pnpm lint`, `pnpm test` (and `pnpm build`
only under `--full`, since it writes `src/sensei_top/web_dist/`). Every output line is capped at 300
characters and each command's shown output at 60 lines; the untruncated log
for a failing command is written to a temp file whose path gets printed.
Exits non-zero on any failure. `pnpm lint` is expected clean:
`KNOWN_ISSUES` in `verify.py` is empty, so any warning is a regression.

This still doesn't replace judgment: read the actual failure, don't just
re-run until green.

## 4. Usage report — what the sessions themselves cost

    uv run python .claude/skills/navigating-sensei-top/scripts/usage_report.py --days 7 --project-dir all
    uv run python .claude/skills/navigating-sensei-top/scripts/usage_report.py --since 2026-10-06 --until 2026-10-13 --project-dir all

Reads this repo's local Claude Code transcripts and prints counts only:
calls and tokens per model, cost per main session and per subagent, the
context a session starts with, the average context per call, how many
sessions compacted, how long subagents ran, whether sessions past 120k
wrote a handoff first, and tool-result volume by source (Bash, `src/`,
`docs/`…). Without `--project-dir` it reads only the current folder;
`all` adds every folder this repo has had (its old names, and sessions
started from `web/`). Workflow agents count as subagents.
Cost is calls × context carried, so these are the numbers to watch, not the
size of a doc. The dollar figure is an API-equivalent at list prices, not a
bill.
