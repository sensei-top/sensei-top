"""Render one ``DeckGuide`` (and, optionally, its ``GuideNarrative``) as a
Markdown document: a per-deck guide regenerated from every game played and
the freshest corpus, not hand-written.

One renderer, two callers: the export route (``GET /api/guide/{key}/
markdown``) and ``guide/narrative.py``'s own prompt, which sends this
document's evidence-only form (``narrative=None``) as the numeric spine of
what it asks Claude to write prose around — so the model is never asked to
re-derive a number the reader can already see rendered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sensei_top.guide.bundle import DeckGuide
from sensei_top.guide.play import BoardCurvePoint

if TYPE_CHECKING:
    from sensei_top.guide.narrative import GuideNarrative


def _pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "?"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_No data._"
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _render_scope(guide: DeckGuide) -> str:
    p = guide.provenance
    deck = p.deck
    lines = ["## Scope", ""]
    lines.append(
        f"**{deck.name or deck.key}** — {deck.matches} matches "
        f"({deck.match_wins}-{deck.match_losses}), {deck.first_played} → {deck.last_played}"
    )
    if p.reset is not None:
        lines.append(
            f"\n> Format reset detected: **{p.reset.date}** "
            f"({', '.join(p.reset.cards)}). "
            f"{p.matches_before_reset} of your {deck.matches} matches predate it."
        )
    with_text, total = p.oracle_coverage
    lines.append(
        f"\nCorpus: {p.classified_decks} classified decks"
        + (f", fetched {p.corpus_fetched_at}" if p.corpus_fetched_at else "")
        + (f", through {p.corpus_latest_event}" if p.corpus_latest_event else "")
        + f". Oracle text: {with_text}/{total} of your cards."
    )
    if guide.gaps:
        lines.append("\n**Gaps:**")
        for gap in guide.gaps:
            lines.append(f"- {gap}")
    return "\n".join(lines)


def _render_engine(narrative: GuideNarrative | None) -> str:
    if narrative is None:
        return "## How it works\n\n_Not generated yet._"
    return f"## How it works\n\n{narrative.engine}"


def _board_curve_cells(point: BoardCurvePoint | None) -> list[str]:
    if point is None:
        return ["", "", "", ""]
    return [str(point.n), str(point.hand), str(point.life), str(point.opp_permanents)]


def _render_play(guide: DeckGuide, narrative: GuideNarrative | None) -> str:
    lines = ["## Your play", ""]

    bc = guide.play.board_curve
    if bc:
        lines.append("### Board state by your own turn (median)")
        turns = sorted({t for by_result in bc.values() for t in by_result}, key=int)
        headers = ["Turn", "Win n", "Win hand", "Win life", "Win opp perms",
                   "Loss n", "Loss hand", "Loss life", "Loss opp perms"]
        rows = []
        for t in turns:
            w = bc.get("win", {}).get(t)
            loss = bc.get("loss", {}).get(t)
            rows.append([t, *_board_curve_cells(w), *_board_curve_cells(loss)])
        lines.append(_table(headers, rows))
        lines.append("")

    zc = guide.play.zone_curve
    if zc:
        lines.append("### Resource curve (biggest win/loss divergence)")
        for combo, split in zc.items():
            lines.append(f"**{combo}**")
            turns = sorted({*split.win, *split.loss}, key=int)
            headers = ["Turn", "Win", "Loss"]
            rows = [
                [t, str(split.win.get(t, "")), str(split.loss.get(t, ""))]
                for t in turns
            ]
            lines.append(_table(headers, rows))
            lines.append("")

    kt = guide.play.key_card_timing
    if kt:
        lines.append("### Key card timing (win-loss by turn first resolved)")
        headers = ["Card", "by T4", "T5-6", "T7-8", "T9+", "never resolved"]
        rows = []
        for card, buckets in kt.items():
            row = [card]
            for bucket in ("by T4", "T5-6", "T7-8", "T9+", "never resolved"):
                b = buckets.get(bucket)
                row.append(f"{b.w}-{b.l}" if b else "-")
            rows.append(row)
        lines.append(_table(headers, rows))
        lines.append("")

    mr = guide.play.mulligan_record
    if mr:
        kept, mull = mr.get("kept_seven"), mr.get("mulliganed")
        lines.append(
            f"### Mulligans\n\nKept seven: {kept.wins if kept else 0}-"
            f"{kept.losses if kept else 0} in {kept.games if kept else 0} games. "
            f"Mulliganed: {mull.wins if mull else 0}-{mull.losses if mull else 0} "
            f"in {mull.games if mull else 0} games."
        )
        lines.append("")

    gl = guide.play.game_length
    if gl:
        w, loss = gl.get("win"), gl.get("loss")
        lines.append(
            f"### Game length\n\nWins: median {w.median_turns if w else '?'} turns "
            f"({w.games if w else 0} games). Losses: median "
            f"{loss.median_turns if loss else '?'} turns ({loss.games if loss else 0} games)."
        )
        lines.append("")

    lines.append("### Your leak, and the fix")
    lines.append("")
    if narrative is not None:
        lines.append(narrative.fix)
        lines.append("")
    if not guide.leaks:
        lines.append("_No pattern in this deck's own matches cleared a real sample size yet._")
    for leak in guide.leaks:
        lines.append(
            f"- **{leak.sample_title}** ({leak.category}): "
            f"{_pct(leak.win_rate_with)} in {leak.n_with} matches with this pattern vs. "
            f"{_pct(leak.win_rate_without)} in {leak.n_without} without (gap {_pct(leak.gap)})"
        )
    if guide.leaks_all_decks:
        lines.append("\n#### Across all of your decks")
        for leak in guide.leaks_all_decks:
            lines.append(
                f"- **{leak.sample_title}** ({leak.category}): "
                f"{_pct(leak.win_rate_with)} in {leak.n_with} matches vs. "
                f"{_pct(leak.win_rate_without)} in {leak.n_without} (gap {_pct(leak.gap)})"
            )

    return "\n".join(lines)


def _render_list(guide: DeckGuide, narrative: GuideNarrative | None) -> str:
    diff = guide.list_diff
    if diff is None:
        return "## The list\n\n_Your deck could not be classified against the field._"
    lines = [
        "## The list",
        "",
        f"Consensus from {diff.winning_decks} winning post-reset lists "
        f"(≥{diff.min_wins} wins), archetype **{diff.archetype_name}**.",
        "",
    ]
    note_by_card = {n.card: n.why for n in narrative.card_notes} if narrative else {}
    for board, cards in (("Maindeck", diff.maindeck), ("Sideboard", diff.sideboard)):
        lines.append(f"### {board}")
        headers = ["Card", "Yours", "Consensus copies", "Share", "Verdict", "Why"]
        rows = [
            [c.card, str(c.yours),
             f"{c.consensus_copies:.1f}" if c.consensus_copies is not None else "-",
             _pct(c.consensus_share), c.verdict, note_by_card.get(c.card, "")]
            for c in cards
        ]
        lines.append(_table(headers, rows))
        lines.append("")
    if diff.duplicate_warnings:
        lines.append("### Possible duplicate cards")
        for w in diff.duplicate_warnings:
            lines.append(f"- {w}")
    return "\n".join(lines)


def _render_field(guide: DeckGuide) -> str:
    f = guide.field
    lines = ["## The field", ""]
    if f.own_performance is not None:
        p = f.own_performance
        lines.append(
            f"Your archetype's post-reset corpus record: {p.wins}-{p.losses} "
            f"across {p.decks} decks ({_pct(p.win_rate)})."
        )
    lines.append("")
    headers = ["Archetype", "Share", "Before reset", "Move", "Verdict", "Your record"]
    rows = []
    personal_by_arch = {r.archetype: r for r in f.personal_rates}
    for s in f.shares:
        change = f.changes.get(s.archetype)
        verdict = change.verdict if change else "-"
        personal = personal_by_arch.get(s.archetype)
        record = (
            f"{personal.wins}-{personal.losses}" + ("" if personal.carryable else " (void)")
            if personal else "-"
        )
        rows.append([
            s.archetype, _pct(s.share), _pct(s.share_before_reset), _pct(s.movement),
            verdict, record,
        ])
    lines.append(_table(headers, rows))
    return "\n".join(lines)


def _render_matchups(narrative: GuideNarrative | None) -> str:
    if narrative is None or not narrative.matchups:
        return "## Matchups\n\n_Not generated yet._"
    lines = ["## Matchups", ""]
    for plan in narrative.matchups:
        lines.append(f"### {plan.archetype}")
        lines.append(plan.prose)
        in_str = ", ".join(f"+{c.n} {c.card}" for c in plan.board_in) or "-"
        out_str = ", ".join(f"-{c.n} {c.card}" for c in plan.board_out) or "-"
        lines.append(f"\n**IN:** {in_str}  \n**OUT:** {out_str}")
        problems = [p for p in narrative.problems if p.archetype == plan.archetype]
        for problem in problems:
            lines.append(f"\n> ⚠ {problem.message}")
        lines.append("")
    return "\n".join(lines)


def _render_checklist(narrative: GuideNarrative | None) -> str:
    if narrative is None or not narrative.checklist:
        return "## Between rounds\n\n_Not generated yet._"
    lines = ["## Between rounds", ""]
    for i, item in enumerate(narrative.checklist, start=1):
        lines.append(f"{i}. {item}")
    return "\n".join(lines)


def render(guide: DeckGuide, narrative: GuideNarrative | None = None) -> str:
    deck = guide.provenance.deck
    sections = [
        f"# {deck.name or deck.key} — Deck & Sideboard Guide",
        "",
        _render_scope(guide),
        "",
        _render_engine(narrative),
        "",
        _render_play(guide, narrative),
        "",
        _render_list(guide, narrative),
        "",
        _render_field(guide),
        "",
        _render_matchups(narrative),
        "",
        _render_checklist(narrative),
    ]
    return "\n".join(sections)
