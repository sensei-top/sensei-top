"""The coach report's prompt — built here, sent from ``sensei_top.llm``
only when the user has opted in.

Unlike ``review/narrative.py`` (one match) or ``review/leaks_narrative.py``
(recurring patterns alone), this is the cross-deck view: every rollup
``coach/evidence.py`` computes over the player's whole recent history, plus
the reading list ``coach/canon.py`` offers and the player's own previous
report, all folded into one prompt.

Like every other Claude-facing module in this project, this one **never
makes the call itself** — only ``sensei_top.llm.client`` imports
``anthropic`` (AGENTS.md non-negotiable #5). ``build_coach_context``
assembles the evidence, ``full_prompt`` wraps it with ``system_prompt(fmt)``, and
``build_coach_prompt`` is the one entry point that turns a connection into a
complete, storable prompt — the API (a later phase) calls it for both a GET
(copy-this-prompt) and a POST (send it through ``llm.write_report``) route.

**Unknowns are stated, never guessed (rule 4).** Every rate goes through
``format_rate``, which reads "no data" at n=0 rather than a bare 0%; an
unclassified deck reads "unclassified" rather than a made-up archetype name;
a report's own gaps and the reader's permanently-untracked mechanics both get
their own named section, so the model is never left to assume silence means
"nothing happened".

**No third-party identifiers, ever.** ``CoachEvidence`` already carries none
except ``ExampleGame.match_id`` (kept only for the dashboard to link back to
a match; documented on the dataclass as the one exception) — this module
never renders it into a prompt.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from sensei_top.coach.canon import ALLOWED_DOMAINS, CanonEntry, entries_for
from sensei_top.coach.evidence import (
    CoachEvidence,
    LeakLine,
    build_coach_evidence,
    format_rate,
    metrics_snapshot,
    progress_since,
)
from sensei_top.coach.store import CoachReport, extract_focus_section, latest_coach_report
from sensei_top.review.narrative import UNTRACKED, _wrap_prompt
from sensei_top.review.narrative_store import context_hash as _context_hash

__all__ = [
    "HEADINGS",
    "SYSTEM_PROMPT",
    "CoachPrompt",
    "build_coach_context",
    "build_coach_prompt",
    "cited_ids",
    "clean_report",
    "full_prompt",
    "reading_list",
    "system_prompt",
    "web_sources",
]

log = logging.getLogger(__name__)

# Copied verbatim from the authored source — do not reword any of it here; a
# wording fix belongs in the prompt's own source, not a paraphrase introduced
# while wiring it up. The text is the original source's with the report's
# format substituted where it named Standard: ``{fmt}`` below, which
# ``system_prompt`` fills with the format's name exactly as ``formats.py``
# spells it. Built as a joined list of exact source lines, rather than one
# triple-quoted block, only so each physical line here stays under ruff's
# line-length limit.
_SYSTEM_PROMPT_LINES = [
    "You are coaching a competitive Magic: The Gathering player on their play across their "
    "whole recent history — not one match, not one deck. This report is about their {fmt} "
    "play. They play paper at a local game store and practise on Arena and MTGO; only their "
    "Arena and MTGO Constructed matches are in the evidence below. You know nothing about "
    "their paper results, so never speculate about them.",
    "",
    "The evidence is computed locally from their own completed matches, in two kinds of "
    "section, and the scope block names which is which:",
    "- {fmt} only, since the last {fmt} format reset: records per deck, per role the matchup "
    "cast them in (beatdown or control, read by comparing their list with the field's typical "
    "list for the opponent's archetype), and per opponent archetype — an archetype line can "
    "merge several colour variants, listed beside it; their current {fmt} decklists; and the "
    "field's top {fmt} archetypes from public MTGO and paper tournament results, which is not "
    "the Arena ladder they play on;",
    "- every Constructed format they played, because these are habits rather than format "
    "knowledge: the overall record; game 1 against post-sideboard games, on the play against "
    "on the draw, and kept seven against mulliganed hands; recurring patterns ranked by how "
    "much each one moves their win rate, overall and per deck, each with the win rate when "
    "the pattern showed up and when it did not; where their lost games turned — the player's "
    "own turn on which a position estimate over life, board, hand and mana dropped the most, "
    "by stage of the game and by size of the swing; and three example losses, turn by turn — "
    "each is one game, chosen because it shows the top losing pattern or because it is "
    "recent, and it illustrates a pattern rather than proving one.",
    "Every rate is shown as wins-losses with its percentage and 95% confidence interval. "
    "After the evidence comes a short reading list of Magic strategy writing, each entry "
    "tagged [R<n>].",
    "",
    "Write a coaching report in markdown with exactly these section headings, in this order, "
    "and no others:",
    "",
    "## Player profile",
    "Who this player is across decks, roles and matchups — strengths first, then weaknesses, "
    "each tied to a number from the evidence.",
    "",
    "## Since your last report",
    "Only when a previous report is included: for each of its focus areas, what the matches "
    "since then show. Say plainly when there are too few matches to tell. Omit this heading "
    "entirely on a first report.",
    "",
    "## Focus areas",
    "The 2-3 patterns most worth deliberate practice. For each: the evidence (record, sample "
    "size, interval), a specific turn from an example game when one illustrates it, and what "
    "doing it right looks like in a game. Prefer patterns that are both large and well "
    "supported. A wide interval or a small sample is not a finding: if nothing clears that "
    "bar, say so, and name the best-supported candidates as provisional.",
    "",
    "## Training plan",
    "At least one concrete drill per focus area for Arena and MTGO sessions: what to do, for "
    "how many games, and what to note after each game, so the next report can measure it.",
    "",
    "## At the LGS",
    "A short pre-match and between-games checklist for paper tournaments, drawn from the "
    "focus areas and the format notes.",
    "",
    "## Format notes",
    "The current {fmt} context that matters for this player's {fmt} decks and the archetypes "
    "they face there. Use web search for this section — current {fmt} bans, the top decks, "
    "and recent articles about these archetypes. Keep only what changes a decision.",
    "",
    "## Sources",
    "Every reading-list entry you cited, as [R<n>] and its title, and every web page you "
    "relied on.",
    "",
    "Rules:",
    "- Ground every claim in the evidence, the reading list or a web source, and cite it: "
    "numbers from the evidence exactly as given, [R<n>] for ideas from the reading list, the "
    "web source for format facts. Never invent a card, a match, a statistic, an article or a "
    "quote.",
    "- Never present a habit as {fmt}-specific, or a {fmt} record as a habit: say which kind "
    "of section a number comes from when it matters.",
    "- Anything marked anecdotal is an anecdote, not a pattern — never build a focus area "
    "on it alone. A pattern that shows up alongside losing is a correlation; say what it "
    "suggests, not that it caused the losses.",
    "- Refer to a turn the way the evidence does: \"your turn N\" is the player's own Nth "
    "turn, and \"turn N\" alone is the shared counter of both players' turns.",
    "- Use web search only for current-format facts. Never search for this player or their "
    "opponents.",
    "- The evidence never covers the stack, counters and other continuous effects, "
    "attachments, the exact phase or step, or which cards were in the opponent's hand. Never "
    "comment on any of them.",
    "- Address the player as \"you\". Be direct and specific; leave out advice that would "
    "apply to any player regardless of their evidence. 1,200-1,800 words.",
]
# The template, ``{fmt}`` unfilled: ``system_prompt(fmt)`` is the text a
# report is written from.
SYSTEM_PROMPT = "\n".join(_SYSTEM_PROMPT_LINES).strip()


def system_prompt(fmt: str) -> str:
    """``SYSTEM_PROMPT`` for a report on ``fmt``. A plain ``replace`` rather
    than ``str.format``, so no other brace in the authored text could ever
    be read as a field."""
    return SYSTEM_PROMPT.replace("{fmt}", fmt)


# The seven "## " section headings, in the order system_prompt requires them.
# The frontend (a later phase) splits a stored report's prose on these.
HEADINGS: tuple[str, ...] = (
    "## Player profile",
    "## Since your last report",
    "## Focus areas",
    "## Training plan",
    "## At the LGS",
    "## Format notes",
    "## Sources",
)


def clean_report(prose: str) -> str:
    """Drops any narration a report's own call left before its first
    section heading (``docs/coach.md``'s "narration can swallow the first
    heading"). Runs at read time only — stored prose stays verbatim
    (``coach/store.py`` never mutates a row once written), so both of the
    reports measured on 2026-09-22 get this fix with no data change.

    Finds the first occurrence of ``"## "`` immediately followed by one of
    ``HEADINGS``' own text, even glued mid-line to whatever narration came
    before it (one measured report opened
    ``"...this player faces.## Player profile"`` with no separator at all).
    Falls back to the first ``"## "`` that starts a line, for a heading a
    future prompt version names that this tuple doesn't yet know. Returns
    ``prose`` unchanged if neither is found.
    """
    earliest: int | None = None
    for heading in HEADINGS:
        idx = prose.find(heading)
        if idx != -1 and (earliest is None or idx < earliest):
            earliest = idx
    if earliest is not None:
        return prose[earliest:]

    match = re.search(r"(?:^|\n)(## .*)", prose)
    if match is not None:
        return match.group(1) + prose[match.end() :]
    return prose


_URL_RE = re.compile(r"https?://\S+")
_TRAILING_SEPARATOR_RE = re.compile(r"\s*[—:-]\s*$")


def web_sources(prose: str) -> list[dict]:
    """The web pages a report's own ``## Sources`` section named, read back
    from prose rather than ``sources_json`` — the API returned no
    ``web_search_result_location`` citation objects for either report
    measured on 2026-09-22, so ``sources_json`` holds reading ids only and
    every web page the model actually searched would otherwise be lost.

    Scans only the ``## Sources`` section of ``clean_report(prose)`` and
    takes each line carrying an ``http(s)://`` URL — the reading-list lines
    above it carry none, so no label is needed to tell the two apart, and
    this reads the same regardless of whether that section labels its own
    subheads ``"Web sources:"`` or ``"Web:"`` (both were seen on real
    reports). A URL is kept only when its host equals, or is a subdomain
    of, an entry in ``coach/canon.py::ALLOWED_DOMAINS`` — the search tool
    itself is restricted to that list, so any other URL came from the
    model's own memory, not a search result, and is dropped rather than
    shown as a source (rule 4: never present a guess as data).
    Dropped and duplicate URLs (keeping the first occurrence) are counted
    and logged once, not per line.
    """
    cleaned = clean_report(prose)
    start = cleaned.find("## Sources")
    if start == -1:
        return []
    body_start = start + len("## Sources")
    next_heading = cleaned.find("\n## ", body_start)
    section = cleaned[body_start:next_heading] if next_heading != -1 else cleaned[body_start:]

    result: list[dict] = []
    seen: set[str] = set()
    dropped = 0
    for line in section.splitlines():
        match = _URL_RE.search(line)
        if match is None:
            continue
        url = match.group().rstrip(").,;")
        host = (urlsplit(url).hostname or "").lower()
        if not any(host == domain or host.endswith(f".{domain}") for domain in ALLOWED_DOMAINS):
            dropped += 1
            continue
        if url in seen:
            continue
        seen.add(url)
        title = line[: match.start()].strip()
        if title.startswith("- "):
            title = title[2:]
        title = _TRAILING_SEPARATOR_RE.sub("", title).strip()
        result.append({"url": url, "title": title or None, "cited_text": None})

    if dropped:
        log.info(
            "coach report web_sources: dropped %d URL(s) outside ALLOWED_DOMAINS", dropped
        )
    return result


def reading_list(evidence: CoachEvidence) -> list[CanonEntry]:
    """The reading list this report's own evidence calls for: every
    ``CanonEntry`` whose topics intersect the ``Finding.code``s and leak
    codes this evidence actually surfaced, plus the broad tags the evidence
    sections below always or conditionally carry. ``entries_for`` folds in
    ``CORE_IDS`` (role, review method, variance) regardless.

    "tilt" is never derived: nothing in ``CoachEvidence`` measures a
    player's state of mind (no clock data, no consecutive-loss streak, no
    self-report) — a report can only ever pick up entry 14 or 15's "tilt"
    topic via their other topics ("tournament-prep", "review"), never
    because this function decided the player was tilting.
    """
    codes: set[str] = set()
    for leak in evidence.leaks:
        codes.add(leak.code)
    for deck_leaks in evidence.deck_leaks:
        for leak in deck_leaks.leaks:
            codes.add(leak.code)
    if any(bucket.games > 0 for bucket in evidence.turning_points):
        codes.add("turning_point")
    if any(role != "unknown" and rate.n > 0 for role, rate in evidence.by_role.items()):
        codes.add("role_assignment")

    mulliganed = evidence.mulligans.get("mulliganed")
    mulligan_taken = mulliganed is not None and mulliganed.n > 0
    if mulligan_taken:
        codes.add("mulligan_taken")

    tags: set[str] = {"review", "variance", "tournament-prep"}
    if evidence.post_board.n > 0:
        tags.add("sideboarding")
    if mulligan_taken:
        tags.add("mulligans")
    if evidence.on_play.n > 0 and evidence.on_draw.n > 0:
        tags.add("play-draw")
    if evidence.decklists:
        tags.add("deckbuilding")

    return entries_for(codes, tags)


_SOURCE_WORDS = {"all": "Arena and MTGO", "arena": "Arena", "mtgo": "MTGO"}

# "early" (your turns 1-3) / "mid" (4-6) / "late" (7+) — evidence.py's own
# _STAGES comment, repeated here as the phrasing this context renders.
_STAGE_LABELS = {"early": "your turns 1-3", "mid": "your turns 4-6", "late": "your turns 7+"}

# The role vocabulary frame.py's role_assignment finding actually produces
# (evidence.py::_match_role) — a fixed, meaningful display order rather than
# whatever order a dict scan happens to produce. Any future role this
# vocabulary doesn't anticipate still renders, sorted after these, rather
# than silently disappearing.
_ROLE_ORDER = ("beatdown", "control", "mixed", "unknown")


def _ordered_roles(by_role: dict) -> list[str]:
    ordered = [r for r in _ROLE_ORDER if r in by_role]
    ordered += sorted(r for r in by_role if r not in _ROLE_ORDER)
    return ordered


def _variant_suffix(variants: tuple[tuple[str, int], ...]) -> str:
    if len(variants) <= 1:
        return ""
    return " — includes: " + ", ".join(f"{name} {count}" for name, count in variants)


def _leak_line(leak: LeakLine) -> str:
    """One recurring pattern as a prompt line. The leak finder's own ``gap``
    is unsigned — it ranks patterns that move the win rate either way — so
    the sign here comes from the two rates: negative means the pattern shows
    up alongside losing, positive alongside winning."""
    if leak.present.rate is not None and leak.absent.rate is not None:
        delta = f"win rate {(leak.present.rate - leak.absent.rate) * 100:+.0f} points with it"
    else:
        delta = f"win rates differ by {leak.gap * 100:.0f} points"
    return (
        f"[{leak.category}] {leak.pattern} ({leak.code}): with it "
        f"{format_rate(leak.present)}; without it {format_rate(leak.absent)}; {delta}."
    )


def build_coach_context(
    evidence: CoachEvidence,
    entries: Sequence[CanonEntry],
    previous: CoachReport | None,
    progress: Sequence[str],
) -> str:
    """Serialize a coach's whole evidence, reading list, and prior report
    into the text ``full_prompt`` wraps. Every rate is rendered with
    ``format_rate`` and nowhere else, so "no data" and "anecdotal" phrasing
    can never drift between two blocks below.
    """
    lines: list[str] = []

    # 1. Scope.
    lines.append("Scope:")
    as_of_date = evidence.as_of[:10] if evidence.as_of else "unknown"
    source_words = _SOURCE_WORDS.get(evidence.source, "Arena and MTGO")
    lines.append(
        f"Evidence as of {as_of_date}: {evidence.population} completed constructed "
        f"matches, {source_words}."
    )
    fmt = evidence.fmt
    if evidence.window_start is not None:
        lines.append(
            f"Format sections ({fmt} only): records per deck, per role and per opponent "
            f"archetype, the decklists and the field — {evidence.format_population} matches "
            f"since {evidence.window_start} (the last {fmt} format change)."
        )
    else:
        lines.append(
            f"Format sections ({fmt} only): records per deck, per role and per opponent "
            f"archetype, the decklists and the field — {evidence.format_population} matches; "
            f"no {fmt} format change on file, so they cover all {fmt} history."
        )
    formats = ", ".join(f"{name} {count}" for name, count in evidence.format_counts)
    lines.append(
        f"Skill sections (every Constructed format played: {formats}): the overall record, "
        f"game 1 and post-board, play and draw, mulligans, patterns, turning points and "
        f"example games — {evidence.population} matches."
    )
    # Only when both clients contributed, so a one-client report never shows
    # a split of one.
    if evidence.by_source["arena"].n and evidence.by_source["mtgo"].n:
        lines.append(
            f"By client, same pooled population — Arena: "
            f"{format_rate(evidence.by_source['arena'])}; MTGO: "
            f"{format_rate(evidence.by_source['mtgo'])}. An MTGO match counts under the "
            f"format the player confirmed, else the one its revealed cards fit (MTGO records "
            f"no format), and carries a deck only when the player picked one, so an unpicked "
            f"match sits in every pooled section but no per-deck one. A gap between "
            f"the two rates may be the client's opposition as much as the player."
        )

    # 2. Overall.
    lines.append("Overall:")
    lines.append(f"Matches: {format_rate(evidence.overall)}.")
    lines.append(f"Games: {format_rate(evidence.overall_games)}.")

    # 3. Splits.
    lines.append("Splits:")
    lines.append(f"Game 1: {format_rate(evidence.g1)}.")
    lines.append(f"Post-sideboard games: {format_rate(evidence.post_board)}.")
    lines.append(f"On the play: {format_rate(evidence.on_play)}.")
    lines.append(f"On the draw: {format_rate(evidence.on_draw)}.")

    # 4. Mulligans.
    lines.append("Mulligans:")
    lines.append(f"Kept seven: {format_rate(evidence.mulligans['kept_seven'])}.")
    lines.append(f"Mulliganed: {format_rate(evidence.mulligans['mulliganed'])}.")

    # 5. By deck.
    if evidence.by_deck:
        lines.append("By deck:")
        for d in evidence.by_deck:
            archetype = d.archetype or "unclassified"
            lines.append(
                f"- {d.label} ({archetype}): matches {format_rate(d.matches)}; "
                f"game 1 {format_rate(d.g1)}; post-board {format_rate(d.post_board)}; "
                f"on the play {format_rate(d.on_play)}; on the draw {format_rate(d.on_draw)}."
            )

    # 6. By role.
    if evidence.by_role:
        lines.append("By role:")
        for role in _ordered_roles(evidence.by_role):
            lines.append(f"- {role}: {format_rate(evidence.by_role[role])}.")

    # 7. Against opponent archetypes (format window).
    if evidence.by_opponent:
        lines.append("Against opponent archetypes (format window):")
        for m in evidence.by_opponent:
            lines.append(f"- {m.archetype}{_variant_suffix(m.variants)} — {format_rate(m.rate)}.")

    # 8. Recurring patterns, all decks.
    if evidence.leaks:
        lines.append("Recurring patterns, all decks:")
        for leak in evidence.leaks:
            lines.append(_leak_line(leak))

    # 9. Recurring patterns, per deck.
    if evidence.deck_leaks:
        lines.append("Recurring patterns, per deck (every format the deck was played in):")
        for dl in evidence.deck_leaks:
            lines.append(f"{dl.deck_label}:")
            for leak in dl.leaks:
                lines.append(_leak_line(leak))

    # 10. Where lost games turned — all 6 buckets, including zeros.
    lines.append("Where lost games turned:")
    for bucket in evidence.turning_points:
        stage_label = _STAGE_LABELS.get(bucket.stage, bucket.stage)
        lines.append(f"- {stage_label} ({bucket.severity}): {bucket.games} game(s).")

    # 11. Example losses. Never render ExampleGame.match_id.
    if evidence.examples:
        lines.append("Example losses:")
        for i, ex in enumerate(evidence.examples, start=1):
            on_play_word = (
                "the play" if ex.on_play is True
                else "the draw" if ex.on_play is False
                else "unknown"
            )
            mulligan_word = (
                f"{ex.mulligans} mulligan(s)" if ex.mulligans is not None
                else "mulligans unknown"
            )
            if ex.chosen_for == "recent_loss":
                why = "a recent loss"
            else:
                matching = next(
                    (leak for leak in evidence.leaks if leak.code == ex.chosen_for), None
                )
                pattern = matching.pattern if matching is not None else ex.chosen_for
                why = f"shows the pattern '{pattern}' ({ex.chosen_for})"
            date_str = ex.date or "date unknown"
            lines.append(
                f"Example {i}: {date_str}, game {ex.game_number}, {ex.deck_label} vs "
                f"{ex.opponent}, on {on_play_word}, {mulligan_word} — why chosen: {why}."
            )
            if ex.turn_lines:
                lines.append("Turns:")
                lines.extend(ex.turn_lines)
            if ex.play_lines:
                lines.append("Plays:")
                lines.extend(ex.play_lines)
            if ex.finding_lines:
                lines.append("Findings:")
                lines.extend(ex.finding_lines)

    # 12. Current decklists.
    if evidence.decklists:
        lines.append("Current decklists:")
        for dl in evidence.decklists:
            lines.append(f"Decklist — {dl.label}:")
            lines.append("Main:")
            for count, name in dl.main:
                lines.append(f"{count} {name}")
            if dl.unnamed:
                lines.append(f"{dl.unnamed} unidentified card(s) — not tracked by name.")
            lines.append("Sideboard:")
            for count, name in dl.side:
                lines.append(f"{count} {name}")

    # 13. The field.
    if evidence.field:
        window_str = evidence.window_start or "the earliest tracked results"
        latest_event = evidence.field_latest_event or "unknown"
        lines.append(
            f"Top archetypes in public MTGO and paper {fmt} results since {window_str} "
            f"(latest event {latest_event}); not the Arena ladder:"
        )
        for f in evidence.field:
            lines.append(
                f"- {f.archetype}{_variant_suffix(f.variants)}: {f.share * 100:.0f}% of the "
                f"field; your record {format_rate(f.your_rate)}."
            )

    # 14. Previous report.
    if previous is not None:
        lines.append(
            f"Your previous {fmt} report ({previous.generated_at[:10]}) set these focus areas:"
        )
        lines.append(extract_focus_section(previous.prose))
        lines.append("Matches since then:")
        lines.extend(progress)
    else:
        lines.append(
            "This is the player's first report: omit the 'Since your last report' section."
        )

    # 15. Reading list.
    lines.append("Reading list (cite as [R<n>]):")
    for entry in entries:
        line = f'[{entry.label}] {entry.author}, "{entry.title}" ({entry.url}): {entry.summary}'
        if entry.note:
            line += f" ({entry.note})"
        lines.append(line)

    # 16. Gaps.
    if evidence.gaps:
        lines.append("Not evaluated, or partly evaluated — treat as unknown, not as evidence:")
        for g in evidence.gaps:
            lines.append(f"- {g}")

    # 17. The untracked sentence — shared verbatim with review/narrative.py.
    lines.append(UNTRACKED)

    return "\n".join(lines)


def full_prompt(context: str, fmt: str) -> str:
    """The complete text to hand an assistant: ``system_prompt(fmt)``
    framing, then the evidence itself."""
    return _wrap_prompt(system_prompt(fmt), context)


_CITATION_GROUP_RE = re.compile(r"\[R\d+(?:\s*[;,]\s*R\d+)*\]")
_ID_RE = re.compile(r"R(\d+)")


def cited_ids(prose: str, entries: Sequence[CanonEntry]) -> list[str]:
    """Every reading-list citation actually used in ``prose``, as its label
    (``"R3"``), in first-appearance order and deduplicated.

    Accepts a lone ``[R3]``, a group sharing one pair of brackets —
    ``[R3, R5]``, ``[R3; R5]`` — and adjacent brackets, ``[R3][R5]``. An id
    ``entries`` never offered is dropped and logged once at WARNING, not
    raised: a model citing an id it was never given is a prompt-following
    failure to flag, not a reason to fail whatever route called this.
    """
    known_ids = {entry.id for entry in entries}
    seen: set[str] = set()
    warned: set[int] = set()
    result: list[str] = []
    for group in _CITATION_GROUP_RE.finditer(prose):
        for num in _ID_RE.findall(group.group()):
            entry_id = int(num)
            if entry_id not in known_ids:
                if entry_id not in warned:
                    log.warning(
                        "coach report cited reading-list id R%d, which was not offered",
                        entry_id,
                    )
                    warned.add(entry_id)
                continue
            label = f"R{entry_id}"
            if label not in seen:
                seen.add(label)
                result.append(label)
    return result


@dataclass(frozen=True, slots=True)
class CoachPrompt:
    evidence: CoachEvidence
    entries: list[CanonEntry]
    previous: CoachReport | None
    context: str
    prompt: str
    metrics: dict
    context_hash: str


def build_coach_prompt(
    conn: sqlite3.Connection,
    *,
    fmt: str,
    source: str = "all",
    report_cache: dict | None = None,
) -> CoachPrompt | None:
    """The one entry point a coach-report route calls, for both a GET
    (copy-this-prompt) and a POST (send it through ``llm.write_report``), for
    a report on ``fmt``. Returns ``None`` exactly when
    ``build_coach_evidence`` does — too few matches to report on at all.
    ``report_cache`` is passed straight through to ``build_coach_evidence``
    (the API's cross-request cache, ``api/sql.py::_shared_report_cache``;
    ``None`` builds a fresh one).

    Progress is measured against the previous report of the same format
    (``latest_coach_report(conn, fmt)``). Its metrics must be version 2
    (``metrics_snapshot``): a version 1 report's skill sections counted
    Standard alone, so it gets a line saying progress can't be measured
    rather than a comparison across two different populations.
    """
    evidence = build_coach_evidence(conn, fmt=fmt, source=source, report_cache=report_cache)
    if evidence is None:
        return None

    entries = reading_list(evidence)
    previous = latest_coach_report(conn, fmt)

    progress: tuple[str, ...] = ()
    if previous is not None:
        version = previous.metrics.get("version")
        if version == 2:
            progress = tuple(progress_since(conn, previous.metrics, source=source))
        elif version == 1:
            progress = (
                f"The previous {fmt} report was written before reports covered every format, "
                f"so progress can't be measured against it.",
            )
        else:
            # Never guess (rule 4): a previous report whose metrics can't be
            # read as this schema's version 2 gets a plain, honest line
            # instead of a comparison that would silently be wrong.
            progress = ("The previous report's metrics are unreadable; progress can't be "
                        "measured.",)

    context = build_coach_context(evidence, entries, previous, progress)
    # Hashed over the evidence alone (previous=None, progress=()), never the
    # full context: the full context embeds "previous", so hashing it would
    # make a freshly-stored report register as stale the instant the next
    # build lists it as its own "previous". A report should read stale only
    # when new matches actually change the evidence, and only then. The
    # evidence names its format (the scope block), so a report on one format
    # never hashes the same as a report on another.
    evidence_only_context = build_coach_context(evidence, entries, None, ())

    return CoachPrompt(
        evidence=evidence,
        entries=entries,
        previous=previous,
        context=context,
        prompt=full_prompt(context, fmt),
        metrics=metrics_snapshot(evidence),
        context_hash=_context_hash(evidence_only_context),
    )
