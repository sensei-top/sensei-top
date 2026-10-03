"""The stored RCQ guide as a Markdown document: game plan, expected field,
matchups in order of field share with IN/OUT tables, flex notes, checklist,
and a footer naming the newest corpus event and the generation date."""

from __future__ import annotations

from sensei_top.guide.narrative import BoardCard
from sensei_top.guide.rcq_authored import StoredRcq

__all__ = ["render_rcq"]


def _board_table(title: str, cards: tuple[BoardCard, ...]) -> list[str]:
    if not cards:
        return []
    return [f"**{title}**", "", "| Cards | Card |", "|---:|---|",
            *(f"| {c.n} | {c.card} |" for c in cards), ""]


def render_rcq(stored: StoredRcq, *, share_by_archetype: dict[str, float] | None = None) -> str:
    """``share_by_archetype`` orders the matchups (largest share first); a
    matchup it does not name keeps the order it was written in, after the
    named ones."""
    g = stored.guide
    shares = share_by_archetype or {}
    ordered = sorted(
        enumerate(g.matchups),
        key=lambda im: (0, -shares[im[1].archetype], im[0]) if im[1].archetype in shares
        else (1, 0.0, im[0]),
    )
    out = ["# RCQ guide", "", "## Game plan", "", g.game_plan, "",
           "## Expected field", "", g.expected_field, "", "## Matchups", ""]
    for _, m in ordered:
        out += [f"### {m.archetype}", "", m.prose, "", f"**Play or draw:** {m.play_draw}", ""]
        out += _board_table("IN", m.board_in)
        out += _board_table("OUT", m.board_out)
    if g.flex_notes:
        out += ["## Flex notes", "", "| Card | Role | Why |", "|---|---|---|",
                *(f"| {f.card} | {f.role} | {f.why} |" for f in g.flex_notes), ""]
    if g.checklist:
        out += ["## Checklist", "", *(f"- [ ] {item}" for item in g.checklist), ""]
    if g.problems:
        out += ["## Plan problems", "",
                *(f"- [{p.archetype}] {p.message}" for p in g.problems), ""]
    newest = stored.corpus_latest_event or "no event recorded"
    out += ["---", "",
            f"Newest tournament event in the corpus: {newest}. "
            f"Generated {stored.generated_at[:10]}."]
    return "\n".join(out) + "\n"
