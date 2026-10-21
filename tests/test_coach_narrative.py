"""Tests for coach/narrative.py — the coach report's prompt assembly.

Every ``CoachEvidence`` here is hand-built directly from the dataclasses
(the same precedent ``tests/test_coach_evidence.py`` established for a piece
that needs no full log capture), and every expectation is computed from
those inputs rather than from running ``build_coach_context`` and copying
its output (rule 8): a rate assertion always compares against
``format_rate(that_same_rate_object)``, never a literal percentage string
typed by hand.

The one exception is ``_EXPECTED_SYSTEM_PROMPT`` below: it is a standalone
transcription of the authored prompt text, with Modern written in where the
template says ``{fmt}``, not imported from ``coach/narrative.py`` itself
(which would make the comparison test nothing but the module agreeing with
itself).
"""

from __future__ import annotations

import dataclasses
import logging

import pytest

from sensei_top.coach.canon import CANON, entries_for
from sensei_top.coach.evidence import (
    CoachEvidence,
    DeckLeaks,
    DeckLine,
    DeckList,
    ExampleGame,
    FieldLine,
    LeakLine,
    MatchupLine,
    Rate,
    TurningBucket,
    format_rate,
)
from sensei_top.coach.narrative import (
    HEADINGS,
    SYSTEM_PROMPT,
    build_coach_context,
    build_coach_prompt,
    cited_ids,
    clean_report,
    reading_list,
    system_prompt,
    web_sources,
)
from sensei_top.coach.store import CoachReport, write_coach_report
from sensei_top.db import open_database
from sensei_top.review.narrative import UNTRACKED

# --- SYSTEM_PROMPT / HEADINGS ------------------------------------------------

_EXPECTED_SYSTEM_PROMPT = "\n".join([
    "You are coaching a competitive Magic: The Gathering player on their play across their "
    "whole recent history — not one match, not one deck. This report is about their Modern "
    "play. They play paper at a local game store and practise on Arena and MTGO; only their "
    "Arena and MTGO Constructed matches are in the evidence below. You know nothing about "
    "their paper results, so never speculate about them.",
    "",
    "The evidence is computed locally from their own completed matches, in two kinds of "
    "section, and the scope block names which is which:",
    "- Modern only, since the last Modern format reset: records per deck, per role the "
    "matchup cast them in (beatdown or control, read by comparing their list with the "
    "field's typical list for the opponent's archetype), and per opponent archetype — an "
    "archetype line can merge several colour variants, listed beside it; their current "
    "Modern decklists; and the field's top Modern archetypes from public MTGO and paper "
    "tournament results, which is not the Arena ladder they play on;",
    "- every Constructed format they played, because these are habits rather than format "
    "knowledge: the overall record; game 1 against post-sideboard games, on the play against "
    "on the draw, and kept seven against mulliganed hands; recurring patterns ranked by how "
    "much each one moves their win rate, overall and per deck, each with the win rate when "
    "the pattern showed up and when it did not; where their lost games turned — the "
    "player's own turn on which a position estimate over life, board, hand and mana dropped "
    "the most, by stage of the game and by size of the swing; and three example losses, "
    "turn by turn — each is one game, chosen because it shows the top losing pattern or "
    "because it is recent, and it illustrates a pattern rather than proving one.",
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
    "The current Modern context that matters for this player's Modern decks and the "
    "archetypes they face there. Use web search for this section — current Modern bans, the "
    "top decks, and recent articles about these archetypes. Keep only what changes a "
    "decision.",
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
    "- Never present a habit as Modern-specific, or a Modern record as a habit: say which "
    "kind of section a number comes from when it matters.",
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
]).strip()


def test_system_prompt_matches_the_authored_text():
    assert system_prompt("Modern") == _EXPECTED_SYSTEM_PROMPT


def test_system_prompt_names_only_the_report_format():
    """Every format mention is the report's own: no Standard survives in a
    Modern prompt, and the template carries no unfilled placeholder."""
    assert "Standard" not in system_prompt("Modern")
    assert "{fmt}" not in system_prompt("Pauper")
    assert system_prompt("Pauper").count("Pauper") == SYSTEM_PROMPT.count("{fmt}")


def test_system_prompt_contains_each_heading_in_order():
    positions = [system_prompt("Standard").index(h) for h in HEADINGS]
    assert positions == sorted(positions)
    assert len(positions) == len(HEADINGS) == 7


# --- clean_report -------------------------------------------------------------


def test_clean_report_drops_narration_glued_mid_line():
    """Report 2's measured shape: no separator at all between the model's
    own narration and its first heading."""
    prose = (
        "I'll start by gathering the current-format facts for the Format "
        "notes section.Now the current metagame and the specific archetypes "
        "this player faces.## Player profile\n\nYou are a 50% player overall."
    )
    assert clean_report(prose) == "## Player profile\n\nYou are a 50% player overall."


def test_clean_report_drops_narration_and_an_unrequested_h1_title():
    """Report 1's measured shape: narration glued to an unrequested ``# ``
    title, itself properly separated from ``## Player profile``."""
    prose = (
        "I'll check the current Standard format context before writing the "
        "report.# MTG Coaching Report — evidence through 2026-09-19\n\n"
        "## Player profile\n\nAcross 245 matches..."
    )
    assert clean_report(prose) == "## Player profile\n\nAcross 245 matches..."


def test_clean_report_with_no_heading_at_all_returns_prose_unchanged():
    prose = "Just some narration with no section headings in it at all."
    assert clean_report(prose) == prose


def test_clean_report_prose_already_starting_on_a_heading_is_unchanged():
    prose = "## Player profile\n\nAcross 245 matches..."
    assert clean_report(prose) == prose


def test_clean_report_falls_back_to_first_line_start_heading_when_unrecognised():
    """A heading this HEADINGS tuple doesn't know about still gets found,
    as long as it starts a line."""
    prose = "Some narration.\n## A Future Heading\n\nBody text."
    assert clean_report(prose) == "## A Future Heading\n\nBody text."


# --- web_sources ----------------------------------------------------------


def _sources_prose(sources_block: str) -> str:
    return (
        "## Player profile\n\nBody.\n\n"
        "## Format notes\n\nBody.\n\n"
        "## Sources\n\n" + sources_block
    )


def test_web_sources_reads_the_web_sources_label_shape():
    """Report 1's measured shape: a bare reading list, then a ``Web
    sources:`` label."""
    prose = _sources_prose(
        '- [R1] Mike Flores, "Who\'s The Beatdown?"\n'
        "Web sources:\n"
        '- Wizards of the Coast, "Banned and Restricted Announcement" — '
        "https://magic.wizards.com/en/news/announcements/banned-and-restricted\n"
    )
    result = web_sources(prose)
    assert result == [{
        "url": "https://magic.wizards.com/en/news/announcements/banned-and-restricted",
        "title": 'Wizards of the Coast, "Banned and Restricted Announcement"',
        "cited_text": None,
    }]


def test_web_sources_reads_the_web_label_shape():
    """Report 2's measured shape: a ``Reading list:`` label, then a bare
    ``Web:`` label."""
    prose = _sources_prose(
        "Reading list:\n"
        '- [R1] Mike Flores, "Who\'s The Beatdown?"\n'
        "Web:\n"
        '- mtgdecks.net, "MTG Standard top decks" — https://mtgdecks.net/Standard\n'
    )
    result = web_sources(prose)
    assert result == [{
        "url": "https://mtgdecks.net/Standard",
        "title": 'mtgdecks.net, "MTG Standard top decks"',
        "cited_text": None,
    }]


def test_web_sources_drops_a_non_allowlisted_url(caplog):
    prose = _sources_prose(
        "Web:\n"
        '- Some Blog, "Not On The List" — https://example.com/article\n'
        '- mtgdecks.net, "On The List" — https://mtgdecks.net/Standard\n'
    )
    caplog.set_level(logging.INFO)
    result = web_sources(prose)
    assert [r["url"] for r in result] == ["https://mtgdecks.net/Standard"]
    assert any("dropped 1" in record.message for record in caplog.records)


def test_web_sources_dedupes_by_url_keeping_the_first():
    prose = _sources_prose(
        "Web:\n"
        '- mtgdecks.net, "First Title" — https://mtgdecks.net/Standard\n'
        '- mtgdecks.net, "Second Title" — https://mtgdecks.net/Standard\n'
    )
    result = web_sources(prose)
    assert len(result) == 1
    assert result[0]["title"] == 'mtgdecks.net, "First Title"'


def test_web_sources_strips_trailing_punctuation_off_the_url():
    prose = _sources_prose(
        "Web:\n"
        '- mtgdecks.net, "Standard metagame" — https://mtgdecks.net/Standard).\n'
    )
    result = web_sources(prose)
    assert result == [{
        "url": "https://mtgdecks.net/Standard",
        "title": 'mtgdecks.net, "Standard metagame"',
        "cited_text": None,
    }]


def test_web_sources_strips_a_trailing_colon_off_the_title():
    """Report 3's measured shape: the title ends in a colon before the URL,
    not a dash."""
    prose = _sources_prose(
        "Web:\n"
        '- MTGGoldfish, "Banned and Restricted Announcement – August 10, 2026": '  # noqa: RUF001
        "https://www.mtggoldfish.com/articles/banned-and-restricted\n"
    )
    result = web_sources(prose)
    assert result == [{
        "url": "https://www.mtggoldfish.com/articles/banned-and-restricted",
        "title": 'MTGGoldfish, "Banned and Restricted Announcement – August 10, 2026"',  # noqa: RUF001
        "cited_text": None,
    }]


def test_web_sources_returns_nothing_with_no_sources_section():
    assert web_sources("## Player profile\n\nNo sources heading at all.") == []


# --- a hand-built CoachEvidence ----------------------------------------------


def _rate(wins: int, n: int) -> Rate:
    """Not a real Wilson interval — these tests only check that
    ``format_rate``'s own output appears verbatim in the rendered context,
    never recompute the confidence-interval math (that belongs to
    ``review/leaks.py::_wilson``'s own tests)."""
    if n == 0:
        return Rate(wins=0, n=0, rate=None, ci=(0.0, 0.0), anecdotal=False)
    rate = wins / n
    ci = (max(0.0, rate - 0.1), min(1.0, rate + 0.1))
    return Rate(wins=wins, n=n, rate=rate, ci=ci, anecdotal=n < 10)


def _full_evidence() -> CoachEvidence:
    """One evidence object that exercises every block ``build_coach_context``
    can render: two decks, a scrambled ``by_role`` dict (to check the fixed
    display order), a two-variant and a one-variant matchup/field line each
    (to check the ">1" gate), a leak and a per-deck leak, two example games
    (one tied to a leak code, one a plain recent loss), a decklist with an
    unnamed count, and a non-empty gaps tuple.
    """
    return CoachEvidence(
        source="all",
        population=42,
        format_population=30,
        window_start="2026-06-02",
        as_of="2026-09-15T12:00:00",
        overall=_rate(25, 42),
        overall_games=_rate(50, 84),
        g1=_rate(20, 40),
        post_board=_rate(5, 8),
        on_play=_rate(15, 25),
        on_draw=_rate(10, 17),
        by_deck=(
            DeckLine(
                label="My Boros Deck", archetype="Boros Aggro",
                matches=_rate(20, 30), g1=_rate(15, 20), post_board=_rate(5, 10),
                on_play=_rate(12, 18), on_draw=_rate(8, 12),
            ),
            DeckLine(
                label="Backup Deck", archetype=None,
                matches=_rate(5, 12), g1=_rate(4, 8), post_board=_rate(1, 4),
                on_play=_rate(3, 6), on_draw=_rate(2, 6),
            ),
        ),
        by_source={"arena": _rate(20, 35), "mtgo": _rate(5, 7)},
        by_role={
            "unknown": _rate(2, 5),
            "control": _rate(10, 15),
            "beatdown": _rate(15, 22),
        },
        mulligans={"kept_seven": _rate(20, 30), "mulliganed": _rate(5, 12)},
        by_opponent=(
            MatchupLine(
                archetype="Jeskai Control", rate=_rate(6, 10),
                variants=(("Jeskai Control", 8), ("Jeskai Tempo", 2)),
            ),
            MatchupLine(archetype="Mono Red", rate=_rate(3, 5), variants=(("Mono Red", 5),)),
        ),
        leaks=(
            LeakLine(
                code="mana_screwed", category="mana", pattern="Kept a one-lander",
                present=_rate(2, 12), absent=_rate(20, 28), gap=-0.35,
            ),
        ),
        deck_leaks=(
            DeckLeaks(deck_label="My Boros Deck", leaks=(
                LeakLine(
                    code="over_committed_into_sweeper", category="tempo",
                    pattern="Overcommitted into a sweeper",
                    present=_rate(1, 10), absent=_rate(15, 20), gap=-0.4,
                ),
            )),
        ),
        turning_points=(
            TurningBucket(stage="early", severity="decisive", games=2),
            TurningBucket(stage="early", severity="notice", games=0),
            TurningBucket(stage="mid", severity="decisive", games=3),
            TurningBucket(stage="mid", severity="notice", games=1),
            TurningBucket(stage="late", severity="decisive", games=0),
            TurningBucket(stage="late", severity="notice", games=1),
        ),
        examples=(
            ExampleGame(
                match_id="secret_match_1", date="2026-09-10", game_number=2,
                deck_label="My Boros Deck", opponent="Jeskai Control",
                on_play=True, mulligans=1, chosen_for="mana_screwed",
                turn_lines=("  turn 3 (your turn 2): life 18-20",),
                play_lines=("  turn 2: you resolved Monastery Swiftspear",),
                finding_lines=("- [tempo/decisive] Fell behind on board (game 2): detail",),
            ),
            ExampleGame(
                match_id="secret_match_2", date="2026-09-12", game_number=1,
                deck_label="Backup Deck", opponent="Mono Red",
                on_play=False, mulligans=None, chosen_for="recent_loss",
                turn_lines=(), play_lines=(), finding_lines=(),
            ),
        ),
        decklists=(
            DeckList(
                label="My Boros Deck",
                main=((4, "Monastery Swiftspear"), (4, "Lightning Bolt")),
                side=((2, "Abrade"),),
                unnamed=1,
            ),
        ),
        field=(
            FieldLine(
                archetype="Jeskai Control",
                variants=(("Jeskai Control", 30), ("Jeskai Tempo", 5)),
                decks=35, share=0.22, your_rate=_rate(6, 10),
            ),
            FieldLine(
                archetype="Mono Red", variants=(("Mono Red", 20),),
                decks=20, share=0.15, your_rate=_rate(3, 5),
            ),
        ),
        field_latest_event="2026-09-01",
        gaps=("2 match(es) excluded: Limited queue.",),
        fmt="Standard",
        format_counts=(("Standard", 30), ("Modern", 12)),
    )


def _minimal_evidence() -> CoachEvidence:
    """Every optional block empty, so the "omit unless noted" rule can be
    checked from the other side: nothing that build_coach_context is allowed
    to skip should appear."""
    return CoachEvidence(
        source="all",
        population=10,
        format_population=10,
        window_start=None,
        as_of="2026-09-01T00:00:00",
        overall=_rate(5, 10),
        overall_games=_rate(10, 20),
        g1=_rate(5, 10),
        post_board=_rate(0, 0),
        on_play=_rate(3, 5),
        on_draw=_rate(2, 5),
        by_deck=(),
        by_source={"arena": _rate(5, 10), "mtgo": _rate(0, 0)},
        by_role={},
        mulligans={"kept_seven": _rate(5, 10), "mulliganed": _rate(0, 0)},
        by_opponent=(),
        leaks=(),
        deck_leaks=(),
        turning_points=(
            TurningBucket(stage="early", severity="decisive", games=0),
            TurningBucket(stage="early", severity="notice", games=0),
            TurningBucket(stage="mid", severity="decisive", games=0),
            TurningBucket(stage="mid", severity="notice", games=0),
            TurningBucket(stage="late", severity="decisive", games=0),
            TurningBucket(stage="late", severity="notice", games=0),
        ),
        examples=(),
        decklists=(),
        field=(),
        field_latest_event=None,
        gaps=(),
        fmt="Standard",
        format_counts=(("Standard", 10),),
    )


@pytest.fixture
def full_evidence():
    return _full_evidence()


@pytest.fixture
def full_entries(full_evidence):
    return reading_list(full_evidence)


# --- build_coach_context ------------------------------------------------------


def test_every_block_label_is_present(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    for label in [
        "Scope:", "Overall:", "Splits:", "Mulligans:", "By deck:", "By role:",
        "Against opponent archetypes (format window):",
        "Recurring patterns, all decks:",
        "Recurring patterns, per deck (every format the deck was played in):",
        "Where lost games turned:", "Example losses:", "Current decklists:",
        "Reading list (cite as [R<n>]):",
    ]:
        assert label in context, label
    assert "Top archetypes in public MTGO and paper Standard results" in context
    assert "Not evaluated, or partly evaluated" in context


def test_the_field_header_names_the_report_format(full_evidence, full_entries):
    modern = dataclasses.replace(full_evidence, fmt="Modern")
    context = build_coach_context(modern, full_entries, None, ())
    assert (
        "Top archetypes in public MTGO and paper Modern results since 2026-06-02 "
        "(latest event 2026-09-01); not the Arena ladder:"
    ) in context
    assert "paper Standard results" not in context


def test_scope_names_the_format_and_skill_sections_with_their_counts(
    full_evidence, full_entries
):
    """30 of the 42 matches are Standard's, since its 2026-06-02 reset; the
    skill sections pool all 42, 30 Standard and 12 Modern, most first."""
    context = build_coach_context(full_evidence, full_entries, None, ())
    assert (
        "Format sections (Standard only): records per deck, per role and per opponent "
        "archetype, the decklists and the field — 30 matches since 2026-06-02 (the last "
        "Standard format change)."
    ) in context
    assert (
        "Skill sections (every Constructed format played: Standard 30, Modern 12): the "
        "overall record, game 1 and post-board, play and draw, mulligans, patterns, turning "
        "points and example games — 42 matches."
    ) in context


def test_by_client_sentence_names_how_an_mtgo_match_gets_its_format(
    full_evidence, full_entries
):
    context = build_coach_context(full_evidence, full_entries, None, ())
    assert (
        "An MTGO match counts under the format the player confirmed, else the one its "
        "revealed cards fit (MTGO records no format), and carries a deck only when the "
        "player picked one, so an unpicked match sits in every pooled section but no "
        "per-deck one."
    ) in context
    assert "count as Standard" not in context


def test_every_rate_goes_through_format_rate(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    e = full_evidence
    for rate in [
        e.overall, e.overall_games, e.g1, e.post_board, e.on_play, e.on_draw,
        e.mulligans["kept_seven"], e.mulligans["mulliganed"],
    ]:
        assert format_rate(rate) in context
    for d in e.by_deck:
        for rate in (d.matches, d.g1, d.post_board, d.on_play, d.on_draw):
            assert format_rate(rate) in context
    for rate in e.by_role.values():
        assert format_rate(rate) in context
    for m in e.by_opponent:
        assert format_rate(m.rate) in context
    for leak in e.leaks:
        assert format_rate(leak.present) in context
        assert format_rate(leak.absent) in context
    for dl in e.deck_leaks:
        for leak in dl.leaks:
            assert format_rate(leak.present) in context
            assert format_rate(leak.absent) in context
    for f in e.field:
        assert format_rate(f.your_rate) in context


def test_variants_rendered_only_when_more_than_one(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    # by_opponent's Jeskai Control line has 2 variants -> shown.
    assert "includes: Jeskai Control 8, Jeskai Tempo 2" in context
    # field's Jeskai Control line has 2 variants -> shown.
    assert "includes: Jeskai Control 30, Jeskai Tempo 5" in context
    # Mono Red has exactly 1 variant on both by_opponent and field -> the
    # "{name} {count}" pair the ">1" gate would have rendered never appears.
    assert "Mono Red 5" not in context
    assert "Mono Red 20" not in context


def test_example_match_id_never_rendered(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    for ex in full_evidence.examples:
        assert ex.match_id not in context


def test_example_why_chosen_wording(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    # example 1 was chosen for a leak code that is in evidence.leaks.
    assert "shows the pattern 'Kept a one-lander' (mana_screwed)" in context
    # example 2 was chosen as a plain recent loss.
    assert "why chosen: a recent loss" in context


def test_by_role_rendered_in_a_fixed_order(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    beatdown_pos = context.index("- beatdown:")
    control_pos = context.index("- control:")
    unknown_pos = context.index("- unknown:")
    assert beatdown_pos < control_pos < unknown_pos


def test_where_lost_games_turned_shows_all_six_buckets_including_zeros(
    full_evidence, full_entries
):
    context = build_coach_context(full_evidence, full_entries, None, ())
    assert "your turns 1-3 (decisive): 2 game(s)." in context
    assert "your turns 1-3 (notice): 0 game(s)." in context
    assert "your turns 4-6 (decisive): 3 game(s)." in context
    assert "your turns 4-6 (notice): 1 game(s)." in context
    assert "your turns 7+ (decisive): 0 game(s)." in context
    assert "your turns 7+ (notice): 1 game(s)." in context


def test_decklist_shows_main_side_and_unnamed_count(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    assert "4 Monastery Swiftspear" in context
    assert "4 Lightning Bolt" in context
    assert "2 Abrade" in context
    assert "1 unidentified card(s)" in context


def test_gaps_block_shows_each_gap_line(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    assert "- 2 match(es) excluded: Limited queue." in context


def test_no_previous_report_shows_the_first_report_line(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    assert "This is the player's first report" in context
    assert "Matches since then:" not in context


def test_previous_report_shows_its_focus_section_and_every_progress_line(
    full_evidence, full_entries
):
    previous = CoachReport(
        id=1, generated_at="2026-08-01T00:00:00", model="claude-opus-5", effort="high",
        prompt="p", prose="## Focus areas\n- Work on sideboarding.\n\n## Training plan\nx",
        sources=[], metrics={"as_of": "2026-08-01T00:00:00"}, context_hash="deadbeef",
        input_tokens=None, output_tokens=None, web_search_requests=None, cost_usd=None,
        format="Standard",
    )
    progress = ["3 new match(es) since the last report: 67%.", "a second progress line"]
    context = build_coach_context(full_evidence, full_entries, previous, progress)
    assert "Your previous Standard report (2026-08-01) set these focus areas:" in context
    assert "Work on sideboarding." in context
    assert "Matches since then:" in context
    for line in progress:
        assert line in context


def test_context_ends_with_the_untracked_sentence(full_evidence, full_entries):
    context = build_coach_context(full_evidence, full_entries, None, ())
    assert context.endswith(UNTRACKED)


def test_scope_wording_with_no_format_reset_on_file():
    evidence = _minimal_evidence()
    context = build_coach_context(evidence, reading_list(evidence), None, ())
    assert (
        "Format sections (Standard only): records per deck, per role and per opponent "
        "archetype, the decklists and the field — 10 matches; no Standard format change on "
        "file, so they cover all Standard history."
    ) in context
    assert "Skill sections (every Constructed format played: Standard 10):" in context


def test_empty_blocks_are_omitted():
    evidence = _minimal_evidence()
    context = build_coach_context(evidence, reading_list(evidence), None, ())
    for label in [
        "By deck:", "By role:", "Against opponent archetypes (format window):",
        "Recurring patterns, all decks:", "Recurring patterns, per deck",
        "Example losses:", "Current decklists:", "Not evaluated, or partly evaluated",
    ]:
        assert label not in context
    assert "Top archetypes in public MTGO and paper Standard results" not in context
    # Blocks that are never omitted still show up on a sparse evidence object.
    assert "Scope:" in context
    assert "Where lost games turned:" in context
    assert "Reading list (cite as [R<n>]):" in context
    assert context.endswith(UNTRACKED)


# --- reading_list --------------------------------------------------------------


def test_reading_list_matches_the_entries_predicted_from_the_evidence(full_evidence):
    codes = {
        "mana_screwed", "over_committed_into_sweeper", "turning_point",
        "role_assignment", "mulligan_taken",
    }
    tags = {
        "review", "variance", "tournament-prep", "sideboarding", "mulligans",
        "play-draw", "deckbuilding",
    }
    assert reading_list(full_evidence) == entries_for(codes, tags)


def test_reading_list_with_no_leaks_is_only_core_plus_tag_matches():
    evidence = _minimal_evidence()
    # No leaks, no deck leaks, no turning-point games, no by_role entries and
    # a mulliganed bucket at n=0 -- codes is empty. post_board is n=0 (no
    # sideboarding tag) and decklists is empty (no deckbuilding tag), but
    # on_play/on_draw both have n>0, so play-draw is the one conditional tag.
    result = reading_list(evidence)
    expected = entries_for(set(), {"review", "variance", "tournament-prep", "play-draw"})
    assert result == expected
    assert result  # CORE_IDS alone guarantees a non-empty list


# --- cited_ids -----------------------------------------------------------------


def _entries(*ids: int):
    return [e for e in CANON if e.id in ids]


def test_cited_ids_known_grouped_and_duplicate_forms():
    entries = _entries(1, 3, 7)
    prose = "As [R1] shows... later [R3, R7] and again [R1][R3]."
    assert cited_ids(prose, entries) == ["R1", "R3", "R7"]


def test_cited_ids_semicolon_group():
    entries = _entries(1, 3)
    prose = "See [R1; R3] for context."
    assert cited_ids(prose, entries) == ["R1", "R3"]


def test_cited_ids_unknown_id_is_dropped_and_logged(caplog):
    entries = _entries(1, 3)
    caplog.set_level(logging.WARNING)
    result = cited_ids("Cites [R1] and a made-up [R99].", entries)
    assert result == ["R1"]
    assert any("R99" in record.message for record in caplog.records)


def test_cited_ids_unknown_id_logged_only_once(caplog):
    entries = _entries(1)
    caplog.set_level(logging.WARNING)
    result = cited_ids("[R99] appears twice: once here [R99].", entries)
    assert result == []
    warnings = [r for r in caplog.records if "R99" in r.message]
    assert len(warnings) == 1


# --- build_coach_prompt over a projected database ------------------------------


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_match(
    conn,
    match_id,
    result,
    *,
    deck_id=None,
    started_at="2026-01-01T00:00:00",
    opponent_name="OppPlayerOne",
    opponent_user_id="OPPCLIENTID0001",
):
    """The same minimal shape tests/test_coach_evidence.py's own
    ``_insert_match`` uses, trimmed to what this module's privacy check
    needs: a real-looking opponent identity and deck id on every match."""
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, source, format) VALUES (?, 'Traditional_Ladder', ?, 1, "
        "2, ?, ?, ?, ?, ?, 1, 0, 'r', 'arena', 'Standard')",
        (match_id, deck_id, opponent_user_id, opponent_name, started_at, started_at, result),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 6, 0, 0)",
        (match_id, result),
    )


def test_build_coach_prompt_over_a_projected_database_no_privacy_leak(conn):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('secret-deck-guid-0001', 'My Boros Deck', 'Standard', '{}', 't', 't')"
    )
    match_ids = [f"secret_match_{i}" for i in range(12)]
    for i, mid in enumerate(match_ids):
        _insert_match(
            conn, mid, "win" if i % 2 == 0 else "loss",
            deck_id="secret-deck-guid-0001" if i % 2 == 0 else None,
            started_at=f"2026-0{1 + i % 9}-0{1 + i % 9}T00:00:00",
        )
    conn.commit()

    p = build_coach_prompt(conn, fmt="Standard")
    assert p is not None
    assert len(p.prompt) < 160_000

    forbidden = ["OppPlayerOne", "OPPCLIENTID0001", "secret-deck-guid-0001", *match_ids]
    for bad in forbidden:
        assert bad not in p.prompt, f"{bad!r} leaked into the coach prompt"
    assert "/home/" not in p.prompt.lower()
    assert "c:\\users" not in p.prompt.lower()

    write_coach_report(
        conn, format="Standard", prose="## Focus areas\n- test focus", prompt=p.prompt,
        model="claude-opus-5", sources=[], metrics=p.metrics, context_hash=p.context_hash,
    )
    conn.commit()

    second = build_coach_prompt(conn, fmt="Standard")
    assert second is not None
    assert second.context_hash == p.context_hash
    assert "test focus" in second.prompt
    assert "Matches since then:" in second.prompt
    assert "metrics are unreadable" not in second.prompt


def test_build_coach_prompt_is_deterministic(conn):
    for i in range(10):
        _insert_match(
            conn, f"m{i}", "win" if i % 2 == 0 else "loss",
            started_at=f"2026-0{1 + i % 9}-0{1 + i % 9}T00:00:00",
        )
    conn.commit()
    first = build_coach_prompt(conn, fmt="Standard")
    second = build_coach_prompt(conn, fmt="Standard")
    assert first is not None
    assert first == second


def test_build_coach_prompt_is_none_below_min_sample(conn):
    for i in range(5):
        _insert_match(conn, f"m{i}", "win")
    conn.commit()
    assert build_coach_prompt(conn, fmt="Standard") is None


def _ten_standard_matches(conn):
    for i in range(10):
        _insert_match(
            conn, f"m{i}", "win" if i % 2 == 0 else "loss",
            started_at=f"2026-0{1 + i % 9}-0{1 + i % 9}T00:00:00",
        )
    conn.commit()


def test_build_coach_prompt_hash_and_system_prompt_differ_by_format(conn):
    """The same ten Standard matches, read as a Standard report and as a
    Modern one: the skill sections are the same population, the format
    sections differ, so the evidence (and its hash) must too."""
    _ten_standard_matches(conn)
    standard = build_coach_prompt(conn, fmt="Standard")
    modern = build_coach_prompt(conn, fmt="Modern")
    assert standard is not None and modern is not None
    assert standard.context_hash != modern.context_hash
    assert modern.prompt.startswith(system_prompt("Modern"))
    assert standard.prompt.startswith(system_prompt("Standard"))
    assert (standard.metrics["fmt"], modern.metrics["fmt"]) == ("Standard", "Modern")


def test_a_previous_report_of_another_format_is_not_this_ones_previous(conn):
    _ten_standard_matches(conn)
    p = build_coach_prompt(conn, fmt="Standard")
    write_coach_report(
        conn, format="Standard", prose="## Focus areas\n- standard focus", prompt=p.prompt,
        model="claude-opus-5", sources=[], metrics=p.metrics, context_hash=p.context_hash,
    )
    conn.commit()

    modern = build_coach_prompt(conn, fmt="Modern")
    assert modern.previous is None
    assert "standard focus" not in modern.prompt
    assert "This is the player's first report" in modern.prompt

    standard = build_coach_prompt(conn, fmt="Standard")
    assert standard.previous is not None
    assert "Your previous Standard report" in standard.prompt


def test_a_version_1_previous_report_gets_the_not_comparable_line(conn):
    """A report from before per-format reports: format NULL (read as
    Standard), metrics version 1 (skill sections counted Standard alone)."""
    _ten_standard_matches(conn)
    conn.execute(
        "INSERT INTO coach_report (generated_at, format, model, effort, prompt, prose, "
        "sources_json, metrics_json, context_hash) VALUES ('2026-01-01T00:00:00', NULL, "
        "'claude-opus-5', 'high', 'p', '## Focus areas\n- old focus', '[]', "
        "'{\"version\": 1, \"as_of\": \"2026-01-01T00:00:00\"}', 'h')"
    )
    conn.commit()

    p = build_coach_prompt(conn, fmt="Standard")
    assert p.previous is not None
    assert (
        "The previous Standard report was written before reports covered every format, so "
        "progress can't be measured against it."
    ) in p.prompt
    assert "metrics are unreadable" not in p.prompt
    assert "old focus" in p.prompt
