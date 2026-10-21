"""This game against a wider sample: a personal record in the same matchup
and the field's own numbers for it. See docs/review.md, "`baseline.py` —
this game against a wider sample".

Both comparisons are match-level, not per-game: ``personal_matchup`` and
``field_matchup`` are win/loss records over a matchup, computed once in
``snapshot.py``, not something a per-game loop could sensibly repeat.
"""

from __future__ import annotations

from sensei_top.i18n import _, ngettext
from sensei_top.metagame.tiers import MIN_LARGE_PAPER_PLAYERS, tier_words
from sensei_top.review.findings import (
    AnalyzerResult,
    Category,
    Confidence,
    Evidence,
    Finding,
    Gap,
    Severity,
)
from sensei_top.review.snapshot import MatchSnapshot

ANALYZER = "baseline"

MIN_PERSONAL_SAMPLE = 3
MIN_FIELD_SAMPLE = 20

PLAY_DRAW_MIN_GAMES = 10
GAME_LENGTH_MIN_GAMES = 10
LONG_GAME_MARGIN = 6
SHORT_GAME_MARGIN = 6
_TIMEOUT_REASONS = {"ResultReason_Timeout"}
_CONCEDE_REASONS = {"ResultReason_Concede"}


def _outcome_findings(snap: MatchSnapshot) -> tuple[list[Finding], list[Gap]]:
    """How each game ended, and how its length compares to this deck's own
    average — neutral outcome facts, never mana/land content (that is the
    leak finder's). Reads ``deck_game_length``/``play_draw``, which every
    snapshot carries.
    """
    findings: list[Finding] = []
    gaps: list[Gap] = []

    total_games = sum(g for _tc, g, _w in snap.deck_game_length)
    if total_games < GAME_LENGTH_MIN_GAMES:
        gaps.append(Gap(ANALYZER, ngettext("Only {total_games} completed games recorded with this "
                                         "deck — too few to compare game length against.",
                                         "Only {total_games} completed games recorded with this "
                                         "deck — too few to compare game length against.",
                                         total_games).format(total_games=total_games),
                         cause="small_sample"))
    else:
        weighted_turns = sum(tc * g for tc, g, _w in snap.deck_game_length)
        avg_turns = round(weighted_turns / total_games)
        for game in snap.games:
            if game.result_reason in _TIMEOUT_REASONS:
                findings.append(Finding(
                    "lost_on_time", ANALYZER, Category.BASELINE, Severity.FLAG,
                    Confidence.OBSERVED, _("Game ended on the clock"),
                    _("This game did not finish before the timer ran out."),
                    game_number=game.game_number,
                    pattern=_("Game ended on the clock"),
                ))
            elif game.result_reason in _CONCEDE_REASONS:
                findings.append(Finding(
                    "conceded", ANALYZER, Category.BASELINE, Severity.NOTE,
                    Confidence.OBSERVED, _("Game ended in a concede"),
                    _("This game ended by concession rather than playing to a finish."),
                    game_number=game.game_number,
                ))
            if game.turn_count is None:
                gaps.append(Gap(ANALYZER, _("This game's length was never recorded."),
                                 game_number=game.game_number))
                continue
            if game.turn_count - avg_turns >= LONG_GAME_MARGIN:
                findings.append(Finding(
                    "long_game", ANALYZER, Category.BASELINE, Severity.NOTE,
                    Confidence.OBSERVED,
                    _("Ran long: {turns} player-turns").format(turns=game.turn_count),
                    _("This game ran {turns} player-turns, against this deck's own "
                      "average of {average}.").format(turns=game.turn_count, average=avg_turns),
                    game_number=game.game_number,
                    evidence=(Evidence("turn_count", _("Player-turns this game"),
                                       game.turn_count),
                              Evidence("deck_avg_turns", _("This deck's average"), avg_turns)),
                    pattern=_("Game ran long against this deck's own average"),
                ))
            elif avg_turns - game.turn_count >= SHORT_GAME_MARGIN:
                findings.append(Finding(
                    "short_game", ANALYZER, Category.BASELINE, Severity.NOTE,
                    Confidence.OBSERVED,
                    _("Ran short: {turns} player-turns").format(turns=game.turn_count),
                    _("This game ran {turns} player-turns, against this deck's own "
                      "average of {average}.").format(turns=game.turn_count, average=avg_turns),
                    game_number=game.game_number,
                    evidence=(Evidence("turn_count", _("Player-turns this game"),
                                       game.turn_count),
                              Evidence("deck_avg_turns", _("This deck's average"), avg_turns)),
                    pattern=_("Game ran short against this deck's own average"),
                ))

    # A side's games are its won and lost ones: a draw is in neither the
    # record nor the sample (docs/design-system.md, "Numbers").
    play_games = sum(w + lost for on_play, w, lost in snap.play_draw if on_play)
    draw_games = sum(w + lost for on_play, w, lost in snap.play_draw if not on_play)
    if play_games == 0 and draw_games == 0:
        gaps.append(Gap(ANALYZER, _("Not enough completed games with this deck yet to compare "
                                    "on-play and on-draw records."), cause="small_sample"))
    elif play_games < PLAY_DRAW_MIN_GAMES or draw_games < PLAY_DRAW_MIN_GAMES:
        gaps.append(Gap(ANALYZER, _("Only {play_games} completed games on the play and "
                                    "{draw_games} on the draw with this deck so far — too few "
                                    "to read a split from.").format(
                             play_games=play_games, draw_games=draw_games),
                         cause="small_sample"))
    else:
        play_wins = sum(w for on_play, w, _lost in snap.play_draw if on_play)
        draw_wins = sum(w for on_play, w, _lost in snap.play_draw if not on_play)
        findings.append(Finding(
            "play_draw_split", ANALYZER, Category.BASELINE, Severity.NOTE, Confidence.OBSERVED,
            _("Your deck's own play/draw record"),
            _("With this deck you've won {play_wins} of {play_games} games on the play and "
              "{draw_wins} of {draw_games} on the draw.").format(
                play_wins=play_wins, play_games=play_games,
                draw_wins=draw_wins, draw_games=draw_games),
            evidence=(
                Evidence("play_games", _("Games on the play"), play_games),
                Evidence("play_wins", _("Wins on the play"), play_wins),
                Evidence("draw_games", _("Games on the draw"), draw_games),
                Evidence("draw_wins", _("Wins on the draw"), draw_wins),
            ),
        ))

    return findings, gaps


def analyze_baseline(snap: MatchSnapshot) -> AnalyzerResult:
    findings, gaps = _outcome_findings(snap)

    if snap.personal_matchup is None:
        gaps.append(
            Gap(ANALYZER, _("This is the first time this deck has faced this opponent "
                            "identification, so there is no personal record to compare "
                            "against."),
                cause="small_sample")
        )
    elif snap.personal_matchup.matches_completed < MIN_PERSONAL_SAMPLE:
        gaps.append(
            Gap(ANALYZER, ngettext(
                "Only {n} other completed match in this matchup so far — too few to call "
                "a record.",
                "Only {n} other completed matches in this matchup so far — too few to call "
                "a record.",
                snap.personal_matchup.matches_completed,
            ).format(n=snap.personal_matchup.matches_completed),
                cause="small_sample")
        )
    else:
        pm = snap.personal_matchup
        win_rate = round(100 * pm.matches_won / pm.matches_completed)
        this_result = "won" if snap.result == "win" else "lost" if snap.result == "loss" else None
        matches_lost = pm.matches_completed - pm.matches_won
        title = ""
        if this_result == "won":
            title = _("You won — your record in this matchup is {wins} wins to "
                      "{losses} losses").format(wins=pm.matches_won, losses=matches_lost)
        elif this_result == "lost":
            title = _("You lost — your record in this matchup is {wins} wins to "
                      "{losses} losses").format(wins=pm.matches_won, losses=matches_lost)
        if this_result:
            findings.append(
                Finding(
                    code="personal_matchup_record",
                    analyzer=ANALYZER, category=Category.BASELINE, severity=Severity.NOTE,
                    confidence=Confidence.OBSERVED,
                    title=title,
                    detail=ngettext(
                        "Before this match, you had played this matchup with this deck "
                        "{n} time and won {win_rate}% of them ({games_won} games won to "
                        "{games_lost} lost).",
                        "Before this match, you had played this matchup with this deck "
                        "{n} times and won {win_rate}% of them ({games_won} games won to "
                        "{games_lost} lost).",
                        pm.matches_completed,
                    ).format(n=pm.matches_completed, win_rate=win_rate,
                             games_won=pm.games_won, games_lost=pm.games_lost),
                    evidence=(
                        Evidence("matches_completed", _("Prior matches in this matchup"),
                                 pm.matches_completed),
                        Evidence("matches_won", _("Prior matches won"), pm.matches_won),
                        Evidence("matches_lost", _("Prior matches lost"), matches_lost),
                        Evidence("win_rate", _("Prior win rate in this matchup"), win_rate,
                                 unit="%"),
                        Evidence("games_won", _("Prior games won"), pm.games_won),
                        Evidence("games_lost", _("Prior games lost"), pm.games_lost),
                    ),
                )
            )

    # Named once and reused in all three spots below, per docs/metagame.md's
    # "The format-reset boundary": a field record windowed to post-reset
    # rounds only must say so wherever it appears, since an unlabeled number
    # here would look identical to a pre-reset one pooled across a ban.
    since = snap.field_since

    if snap.field_matchup is None:
        if snap.opponent_archetype_key is None:
            cause = "opponent_unclassified"
        elif snap.own_archetype is None:
            cause = "own_unclassified"
        else:
            cause = None  # both sides classified; the corpus simply has no rows for this pairing
        if since:
            reason = _("The field's own results for this archetype pairing since the last "
                       "format reset ({since}) were not available — either the corpus has not "
                       "been fetched, or too few paper/MTGO events cover it."
                       ).format(since=since)
        else:
            reason = _("The field's own results for this archetype pairing were not "
                       "available — either the corpus has not been fetched, or too few "
                       "paper/MTGO events cover it.")
        gaps.append(Gap(ANALYZER, reason, cause=cause))
    elif snap.field_matchup.n < MIN_FIELD_SAMPLE:
        fm = snap.field_matchup
        if since:
            reason = ngettext(
                "Only {n} matches of this pairing are on record in {tier} since the "
                "last format reset ({since}) — too few to call a field win rate.",
                "Only {n} matches of this pairing are on record in {tier} since the "
                "last format reset ({since}) — too few to call a field win rate.",
                fm.n,
            ).format(n=fm.n, tier=tier_words(fm.tier), since=since)
        else:
            reason = ngettext(
                "Only {n} matches of this pairing are on record in {tier} — too few "
                "to call a field win rate.",
                "Only {n} matches of this pairing are on record in {tier} — too few "
                "to call a field win rate.",
                fm.n,
            ).format(n=fm.n, tier=tier_words(fm.tier))
        gaps.append(Gap(ANALYZER, reason))
    else:
        fm = snap.field_matchup
        field_rate = round(100 * fm.matches_won / fm.n)
        own_name = snap.own_archetype.name if snap.own_archetype else _("your archetype")
        opp_name = snap.opponent_label or _("this archetype")
        if since:
            field_detail = _(
                "Across {n} matches in {tier} since the last format reset ({since}), "
                "{own} has beaten {opponent} {wins} times and lost {losses}."
            ).format(n=fm.n, tier=tier_words(fm.tier), since=since, own=own_name,
                     opponent=opp_name, wins=fm.matches_won, losses=fm.matches_lost)
        else:
            field_detail = _(
                "Across {n} matches in {tier}, {own} has beaten {opponent} {wins} times "
                "and lost {losses}."
            ).format(n=fm.n, tier=tier_words(fm.tier), own=own_name,
                     opponent=opp_name, wins=fm.matches_won, losses=fm.matches_lost)
        findings.append(
            Finding(
                code="field_matchup_rate",
                analyzer=ANALYZER, category=Category.BASELINE, severity=Severity.NOTE,
                confidence=Confidence.OBSERVED,
                title=_("The field wins this matchup {rate}% of the time"
                        ).format(rate=field_rate),
                detail=field_detail,
                evidence=(
                    Evidence("field_matches", _("Matches in this tier"), fm.n),
                    Evidence("field_wins", _("Wins for your archetype"), fm.matches_won),
                    Evidence("field_losses", _("Losses for your archetype"), fm.matches_lost),
                    Evidence("field_rate", _("Field win rate for your archetype"), field_rate,
                             unit="%"),
                    Evidence("field_tier", _("Tournament tier"), fm.tier),
                ) + (
                    (
                        Evidence(
                            "paper_size_floor",
                            _("Fewest players in a large paper tournament"),
                            MIN_LARGE_PAPER_PLAYERS, unit=_("players"),
                        ),
                    )
                    if fm.tier in ("A", "D") else ()
                ),
                caveats=(
                    _("Tournament results from one tier only (MTGO or paper, never Arena — "
                      "Arena publishes no event results), the highest-ranked tier with enough "
                      "matches of this pairing."),
                ),
            )
        )

    return AnalyzerResult(tuple(findings), tuple(gaps))
