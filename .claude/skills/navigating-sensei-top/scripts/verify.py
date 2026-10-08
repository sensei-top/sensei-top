#!/usr/bin/env python3
"""Run the AGENTS.md "Before you finish" checks with output bounded per line.

On a clean run, ruff + pytest -q + pnpm lint + pnpm test together print about a dozen lines —
already cheap. The problem is failures: this repo's tests are fixture-backed
against tests/fixtures/*.log, whose lines run up to ~50,000 characters, so a
single pytest assertion diff that renders a fixture-derived payload can dump
tens of thousands of characters into context. This script caps every output
line and writes the untruncated log to a temp file for follow-up.

    uv run python .claude/skills/navigating-sensei-top/scripts/verify.py
    uv run python .claude/skills/navigating-sensei-top/scripts/verify.py --full   # + build, drift

Runs, in order: `uv run ruff check .`, `uv run pytest -q`, `cd web && pnpm
lint`, `pnpm test`. `pnpm build` only under --full — it writes src/sensei_top/web_dist/ and
tsconfig.tsbuildinfo, so it's opt-in rather than run reflexively.

Also only under --full, after the build, CI's drift check: `pnpm gen:types`
(rewrites web/src/types/api.ts, and the gitignored web/openapi.json), then `git
diff --exit-code -- web/src/types/api.ts` from the repo root. A stale committed
api.ts fails here the way it fails CI's web job. web/openapi.json is gitignored,
so the diff covers api.ts only.

Exits non-zero if any command fails.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

MAX_LINE_CHARS = 300
MAX_LINES_SHOWN = 60

# Pre-existing, not a regression — see AGENTS.md and the census this skill
# was built from. Reported so it isn't mistaken for new breakage.
#
# The one entry this used to carry (a react(only-export-components) warning
# at src/components/ui.tsx:68) is gone, not just moved: the redesign split
# that file into components/ui/ with one component per file (Chip.tsx no
# longer also exports severityChipClass — that moved to its own severity.ts),
# which was the actual fix, not a relocation of the warning. `pnpm lint`
# is clean with zero warnings as of this change — confirmed by running it.
KNOWN_ISSUES: tuple[str, ...] = ()


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(out.stdout.strip())


STALE_TYPES_MESSAGE = (
    "api.ts is stale: run `cd web && pnpm gen:types` and commit web/src/types/api.ts"
)


def _run(name: str, cmd: list[str], cwd: Path) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    ok = proc.returncode == 0
    raw = (proc.stdout or "") + (proc.stderr or "")
    return ok, raw


def _bounded(raw: str) -> tuple[str, bool]:
    lines = raw.splitlines()
    truncated_lines = False
    out_lines = []
    for line in lines[:MAX_LINES_SHOWN]:
        if len(line) > MAX_LINE_CHARS:
            keep = MAX_LINE_CHARS - 24  # leaves room for the marker below the cap
            line = line[:keep] + f"...[+{len(line) - keep} chars]"
            truncated_lines = True
        out_lines.append(line)
    more = len(lines) - len(out_lines)
    if more > 0:
        out_lines.append(f"... [+{more} more lines truncated]")
    return "\n".join(out_lines), truncated_lines or more > 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "also run pnpm build (writes src/sensei_top/web_dist/), then pnpm gen:types and "
            "git diff --exit-code -- web/src/types/api.ts (CI's drift check; "
            "web/openapi.json is gitignored, so only api.ts is diffed)"
        ),
    )
    args = parser.parse_args()

    root = _repo_root()
    web = root / "web"

    # (name, command, cwd, message printed after the output of a failure)
    checks: list[tuple[str, list[str], Path, str | None]] = [
        ("ruff", ["uv", "run", "ruff", "check", "."], root, None),
        ("pytest", ["uv", "run", "pytest", "-q"], root, None),
        ("pnpm lint", ["pnpm", "lint"], web, None),
        ("pnpm test", ["pnpm", "test"], web, None),
    ]
    if args.full:
        checks.append(("pnpm build", ["pnpm", "build"], web, None))
        checks.append(("pnpm gen:types", ["pnpm", "gen:types"], web, None))
        checks.append(
            (
                "api.ts drift",
                ["git", "diff", "--exit-code", "--", "web/src/types/api.ts"],
                root,
                STALE_TYPES_MESSAGE,
            )
        )

    overall_ok = True
    log_dir = Path(tempfile.mkdtemp(prefix="verify-"))

    for name, cmd, cwd, hint in checks:
        ok, raw = _run(name, cmd, cwd)
        overall_ok &= ok
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {name}")

        log_path = log_dir / f"{name.replace(' ', '_')}.log"
        log_path.write_text(raw)

        if not ok:
            shown, was_truncated = _bounded(raw)
            print(shown)
            if was_truncated:
                print(f"  (full output: {log_path})")
            if hint:
                print(hint)

    if not args.full:
        print("\n(pnpm build and the api.ts drift check not run — pass --full to include them)")

    if KNOWN_ISSUES:
        print("\nKnown pre-existing issues (not checked, not regressions):")
        for issue in KNOWN_ISSUES:
            print(f"  {issue}")

    raise SystemExit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
