#!/usr/bin/env python3
"""Measure what this repo's Claude Code sessions cost, from their transcripts.

Cost follows the shape of a session, not the size of the repo: every model
call re-reads the whole context, so spend is (number of calls) x (context
carried). This script reads the local session transcripts and prints the
figures that show that shape: calls and tokens per model, the context a
session starts with, how often a session compacts, and how long subagents
run.

    uv run python .claude/skills/navigating-sensei-top/scripts/usage_report.py
    uv run python .claude/skills/navigating-sensei-top/scripts/usage_report.py --days 7
    uv run python .claude/skills/navigating-sensei-top/scripts/usage_report.py --since 2026-09-28

Read-only. Prints counts and sums only, never a transcript's text or a path;
the one identifier it prints is the first 8 characters of a session id, for
the main sessions that passed the handoff threshold without writing a handoff
note, so a reader can check them by hand. The transcript directory is derived from the repo root, so
nothing here names a home directory.

The dollar figure is an API-equivalent from list prices, not a bill: a
subscription is not charged per token. A model missing from PRICES is
counted in tokens and left out of the dollar sum, never priced by guess.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

# US$ per million tokens: (input, output, cache read). Cache writes cost
# 1.25x input for the 5-minute tier and 2x for the 1-hour tier. Matched by
# prefix against the transcript's model id, longest prefix first.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.25),
    "claude-sonnet-5": (2.0, 10.0, 0.10),
}
PRICES_AS_OF = "2026-06-24"

# The targets the 2026-09-28 review set, printed next to the measurement.
TARGET_AVG_CONTEXT = 85_000
TARGET_SUBAGENT_MEDIAN = 60
TARGET_SUBAGENT_MAX = 150

# AGENTS.md, "Working style": a session writes a handoff note once its
# context passes this, before auto-compaction (near 167k) does it for them.
HANDOFF_THRESHOLD = 120_000
HANDOFF_DIR = "/.claude/handoffs/"
HANDOFF_TOOLS = ("Write", "Edit")


@dataclass
class Transcript:
    is_subagent: bool
    session: str = ""
    contexts: list[int] = field(default_factory=list)
    compactions: int = 0
    # A Write or Edit under .claude/handoffs/ before the first compaction.
    handoff_written: bool = False


@dataclass
class ModelTotals:
    calls: int = 0
    input: int = 0
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    output: int = 0


def _transcript_dir() -> Path:
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return Path.home() / ".claude" / "projects" / root.replace("/", "-")


def _price(model: str) -> tuple[float, float, float] | None:
    for prefix in sorted(PRICES, key=len, reverse=True):
        if model.startswith(prefix):
            return PRICES[prefix]
    return None


def _timestamp(row: dict) -> datetime | None:
    raw = row.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _writes_handoff(message: dict) -> bool:
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") in HANDOFF_TOOLS
            and isinstance(block.get("input"), dict)
            and HANDOFF_DIR in str(block["input"].get("file_path", ""))
        ):
            return True
    return False


def _read(
    path: Path, since: datetime, totals: dict[tuple[str, str], ModelTotals], seen: set[str]
) -> Transcript:
    transcript = Transcript(is_subagent=path.parent.name == "subagents", session=path.stem)
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            when = _timestamp(row)
            if when is None or when < since:
                continue
            if row.get("subtype") == "compact_boundary":
                transcript.compactions += 1
                continue
            message = row.get("message")
            if row.get("type") != "assistant" or not isinstance(message, dict):
                continue
            # Before the dedup below: a response's tool_use block is its own
            # row, and the text block ahead of it has already claimed the id.
            if transcript.compactions == 0 and _writes_handoff(message):
                transcript.handoff_written = True
            usage = message.get("usage")
            model = message.get("model")
            if not isinstance(usage, dict) or not isinstance(model, str) or model == "<synthetic>":
                continue
            # One response is written as several rows (one per content
            # block), each repeating the same usage.
            message_id = message.get("id")
            if isinstance(message_id, str):
                if message_id in seen:
                    continue
                seen.add(message_id)

            fresh = usage.get("input_tokens") or 0
            read = usage.get("cache_read_input_tokens") or 0
            written = usage.get("cache_creation_input_tokens") or 0
            tiers = usage.get("cache_creation")
            if isinstance(tiers, dict):
                written_1h = tiers.get("ephemeral_1h_input_tokens") or 0
                written_5m = tiers.get("ephemeral_5m_input_tokens") or 0
            else:
                written_1h, written_5m = 0, written

            # Keyed by role too, so the cost splits between main sessions and subagents.
            total = totals[("subagent" if transcript.is_subagent else "main", model)]
            total.calls += 1
            total.input += fresh
            total.cache_read += read
            total.cache_write_5m += written_5m
            total.cache_write_1h += written_1h
            total.output += usage.get("output_tokens") or 0
            transcript.contexts.append(fresh + read + written)
    return transcript


def _cost(model: str, total: ModelTotals) -> float | None:
    price = _price(model)
    if price is None:
        return None
    per_input, per_output, per_read = price
    return (
        total.input * per_input
        + total.cache_write_5m * per_input * 1.25
        + total.cache_write_1h * per_input * 2.0
        + total.cache_read * per_read
        + total.output * per_output
    ) / 1_000_000


def _millions(tokens: int) -> str:
    return f"{tokens / 1_000_000:,.1f}M"


def _report_group(name: str, group: list[Transcript]) -> None:
    group = [t for t in group if t.contexts]
    if not group:
        print(f"{name}: none in the window")
        return
    calls = [len(t.contexts) for t in group]
    every_context = [c for t in group for c in t.contexts]
    print(f"{name}: {len(group)}")
    print(f"  calls per transcript   median {statistics.median(calls):.0f}, max {max(calls)}")
    print(
        f"  context at first call  median "
        f"{statistics.median(t.contexts[0] for t in group):,.0f} tokens"
    )
    print(f"  context per call       average {statistics.fmean(every_context):,.0f} tokens")
    peak = statistics.median(max(t.contexts) for t in group)
    print(f"  peak context           median {peak:,.0f}")
    compacted = sum(1 for t in group if t.compactions)
    more_than_once = sum(1 for t in group if t.compactions > 1)
    print(
        f"  compacted              {compacted} of {len(group)} "
        f"({more_than_once} more than once, max {max(t.compactions for t in group)})"
    )


def _report_handoff_rule(sessions: list[Transcript]) -> None:
    sessions = [t for t in sessions if t.contexts]
    over = [t for t in sessions if max(t.contexts) > HANDOFF_THRESHOLD]
    wrote = [t for t in over if t.handoff_written]
    print("Handoff rule (main sessions):")
    print(f"  peak context over {HANDOFF_THRESHOLD:,}      {len(over)} of {len(sessions)}")
    print(f"  wrote a handoff first    {len(wrote)} of {len(over)}")
    print(f"  Target: every session over {HANDOFF_THRESHOLD // 1000}k wrote one.")
    missed = [t for t in over if not t.handoff_written]
    if missed:
        print("  without one (session, peak context):")
        for t in sorted(missed, key=lambda t: -max(t.contexts)):
            print(f"    {t.session[:8]}  {max(t.contexts):,}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--days", type=int, default=7, help="look back this many days (default 7)")
    window.add_argument("--since", help="count from this date, YYYY-MM-DD (UTC)")
    args = parser.parse_args()

    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    else:
        since = datetime.now(UTC) - timedelta(days=args.days)

    directory = _transcript_dir()
    if not directory.is_dir():
        print("No transcripts found for this repo.")
        return 1

    totals: dict[tuple[str, str], ModelTotals] = defaultdict(ModelTotals)
    seen: set[str] = set()
    transcripts = [_read(path, since, totals, seen) for path in sorted(directory.rglob("*.jsonl"))]

    print(f"Window: since {since.date().isoformat()} (UTC)")
    print()
    print(
        f"{'role':<10}{'model':<28}{'calls':>8}{'cache read':>13}{'cache write':>13}"
        f"{'output':>10}{'US$':>10}"
    )
    dollars = 0.0
    by_role: dict[str, float] = defaultdict(float)
    unpriced: list[str] = []
    rows = sorted(totals.items(), key=lambda item: (item[0][0], -item[1].calls))
    for (role, model), total in rows:
        cost = _cost(model, total)
        if cost is None:
            unpriced.append(model)
        else:
            dollars += cost
            by_role[role] += cost
        print(
            f"{role:<10}{model:<28}{total.calls:>8,}{_millions(total.cache_read):>13}"
            f"{_millions(total.cache_write_5m + total.cache_write_1h):>13}"
            f"{_millions(total.output):>10}"
            f"{('n/a' if cost is None else f'{cost:,.0f}'):>10}"
        )
    print(f"API-equivalent at list prices of {PRICES_AS_OF}: US$ {dollars:,.0f}")
    print(f"  main sessions US$ {by_role['main']:,.0f}, subagents US$ {by_role['subagent']:,.0f}")
    if unpriced:
        print(f"Not priced, left out of the sum: {', '.join(sorted(set(unpriced)))}")
    print()

    _report_group("Main sessions", [t for t in transcripts if not t.is_subagent])
    print()
    _report_group("Subagents", [t for t in transcripts if t.is_subagent])
    print()
    print(
        "Targets (2026-09-28 review): context per call under "
        f"{TARGET_AVG_CONTEXT:,}; subagent calls median under {TARGET_SUBAGENT_MEDIAN}, "
        f"max under {TARGET_SUBAGENT_MAX}; fewer than 1 main session in 4 compacting "
        "more than once."
    )
    print()
    _report_handoff_rule([t for t in transcripts if not t.is_subagent])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
