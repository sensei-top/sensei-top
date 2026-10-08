"""This game against a wider sample — Reid Duke's own review method: "have
you lost enough games in this same way to reveal a fatal flaw?" A single
game cannot answer that; a personal record in the same matchup and the
field's own numbers for it can at least say whether this result was
ordinary or a real outlier.

Both comparisons are match-level, not per-game: ``personal_matchup`` and
``field_matchup`` are win/loss records over a matchup, computed once in
``snapshot.py``, not something a per-game loop could sensibly repeat.
"""

from __future__ import annotations

from sensei_top.metagame.tiers import MIN_LARGE_PAPER_PLAYERS, TIER_WORDS
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
    average — neutral outcome facts, not mana/land content (the user's own
    call). Reuses ``deck_game_length``/``play_draw``, aggregates this deck
    already carries in every snapshot regardless of which analyzers read
    them.
    """
    findings: list[Finding] = []
    gaps: list[Gap] = []

    total_games = sum(g for _, g, _ in snap.deck_game_length)
    if total_games < GAME_LENGTH_MIN_GAMES:
        gaps.append(Gap(ANALYZER, f"Only {total_games} completed games recorded with this "
                                   f"deck — too few to compare game length against.",
                         cause="small_sample"))
    else:
        weighted_turns = sum(tc * g for tc, g, _ in snap.deck_game_length)
        avg_turns = round(weighted_turns / total_games)
        for game in snap.games:
            if game.result_reason in _TIMEOUT_REASONS:
                findings.append(Finding(
                    "lost_on_time", ANALYZER, Category.BASELINE, Severity.FLAG,
                    Confidence.OBSERVED, "Game ended on the clock",
                    "This game did not finish before the timer ran out.",
                    game_number=game.game_number,
                    pattern="Game ended on the clock",
                ))
            elif game.result_reason in _CONCEDE_REASONS:
                findings.append(Finding(
                    "conceded", ANALYZER, Category.BASELINE, Severity.NOTE,
                    Confidence.OBSERVED, "Game ended in a concede",
                    "This game ended by concession rather than playing to a finish.",
                    game_number=game.game_number,
                ))
            if game.turn_count is None:
                gaps.append(Gap(ANALYZER, "This game's length was never recorded.",
                                 game_number=game.game_number))
                continue
            if game.turn_count - avg_turns >= LONG_GAME_MARGIN:
                findings.append(Finding(
                    "long_game", ANALYZER, Category.BASELINE, Severity.NOTE,
                    Confidence.OBSERVED, f"Ran long: {game.turn_count} player-turns",
                    f"This game ran {game.turn_count} player-turns, against this deck's own "
                    f"average of {avg_turns}.",
                    game_number=game.game_number,
                    evidence=(Evidence("turn_count", "Player-turns this game", game.turn_count),
                              Evidence("deck_avg_turns", "This deck's average", avg_turns)),
                    pattern="Game ran long against this deck's own average",
                ))
            elif avg_turns - game.turn_count >= SHORT_GAME_MARGIN:
                findings.append(Finding(
                    "short_game", ANALYZER, Category.BASELINE, Severity.NOTE,
                    Confidence.OBSERVED, f"Ran short: {game.turn_count} player-turns",
                    f"This game ran {game.turn_count} player-turns, against this deck's own "
                    f"average of {avg_turns}.",
                    game_number=game.game_number,
                    evidence=(Evidence("turn_count", "Player-turns this game", game.turn_count),
                              Evidence("deck_avg_turns", "This deck's average", avg_turns)),
                    pattern="Game ran short against this deck's own average",
                ))

    play_games = sum(g for on_play, g, _ in snap.play_draw if on_play)
    draw_games = sum(g for on_play, g, _ in snap.play_draw if not on_play)
    if play_games == 0 and draw_games == 0:
        gaps.append(Gap(ANALYZER, "Not enough completed games with this deck yet to compare "
                                   "on-play and on-draw records.", cause="small_sample"))
    elif play_games < PLAY_DRAW_MIN_GAMES or draw_games < PLAY_DRAW_MIN_GAMES:
        gaps.append(Gap(ANALYZER, f"Only {play_games} completed games on the play and "
                                   f"{draw_games} on the draw with this deck so far — too few "
                                   f"to read a split from.", cause="small_sample"))
    else:
        play_wins = sum(w for on_play, _, w in snap.play_draw if on_play)
        draw_wins = sum(w for on_play, _, w in snap.play_draw if not on_play)
        findings.append(Finding(
            "play_draw_split", ANALYZER, Category.BASELINE, Severity.NOTE, Confidence.OBSERVED,
            "Your deck's own play/draw record",
            f"With this deck you've won {play_wins} of {play_games} games on the play and "
            f"{draw_wins} of {draw_games} on the draw.",
            evidence=(
                Evidence("play_games", "Games on the play", play_games),
                Evidence("play_wins", "Wins on the play", play_wins),
                Evidence("draw_games", "Games on the draw", draw_games),
                Evidence("draw_wins", "Wins on the draw", draw_wins),
            ),
        ))

    return findings, gaps


def analyze_baseline(snap: MatchSnapshot) -> AnalyzerResult:
    findings, gaps = _outcome_findings(snap)

    if snap.personal_matchup is None:
        gaps.append(
            Gap(ANALYZER, "This is the first time this deck has faced this opponent "
                          "identification, so there is no personal record to compare against.",
                cause="small_sample")
        )
    elif snap.personal_matchup.matches_completed < MIN_PERSONAL_SAMPLE:
        gaps.append(
            Gap(ANALYZER, f"Only {snap.personal_matchup.matches_completed} other completed "
                          f"match{'es' if snap.personal_matchup.matches_completed != 1 else ''} "
                          f"in this matchup so far — too few to call a record.",
                cause="small_sample")
        )
    else:
        pm = snap.personal_matchup
        win_rate = round(100 * pm.matches_won / pm.matches_completed)
        this_result = "won" if snap.result == "win" else "lost" if snap.result == "loss" else None
        matches_lost = pm.matches_completed - pm.matches_won
        if this_result:
            findings.append(
                Finding(
                    code="personal_matchup_record",
                    analyzer=ANALYZER, category=Category.BASELINE, severity=Severity.NOTE,
                    confidence=Confidence.OBSERVED,
                    title=(f"You {this_result} — your record in this matchup is "
                           f"{pm.matches_won} wins to {matches_lost} losses"),
                    detail=(
                        f"Before this match, you had played this matchup with this deck "
                        f"{pm.matches_completed} time{'s' if pm.matches_completed != 1 else ''} "
                        f"and won {win_rate}% of them ({pm.games_won} games won to "
                        f"{pm.games_lost} lost)."
                    ),
                    evidence=(
                        Evidence("matches_completed", "Prior matches in this matchup",
                                 pm.matches_completed),
                        Evidence("matches_won", "Prior matches won", pm.matches_won),
                        Evidence("matches_lost", "Prior matches lost", matches_lost),
                        Evidence("win_rate", "Prior win rate in this matchup", win_rate, unit="%"),
                        Evidence("games_won", "Prior games won", pm.games_won),
                        Evidence("games_lost", "Prior games lost", pm.games_lost),
                    ),
                )
            )

    # Named once and reused in all three spots below, per docs/metagame.md's
    # "The format-reset boundary": a field record windowed to post-reset
    # rounds only must say so wherever it appears, since an unlabeled number
    # here would look identical to a pre-reset one pooled across a ban.
    since_suffix = f" since the last format reset ({snap.field_since})" if snap.field_since else ""

    if snap.field_matchup is None:
        if snap.opponent_archetype_key is None:
            cause = "opponent_unclassified"
        elif snap.own_archetype is None:
            cause = "own_unclassified"
        else:
            cause = None  # both sides classified; the corpus simply has no rows for this pairing
        gaps.append(
            Gap(ANALYZER, f"The field's own results for this archetype pairing{since_suffix} "
                          f"were not available — either the corpus has not been fetched, or too "
                          f"few paper/MTGO events cover it.", cause=cause)
        )
    elif snap.field_matchup.n < MIN_FIELD_SAMPLE:
        fm = snap.field_matchup
        gaps.append(
            Gap(ANALYZER, f"Only {fm.n} matches of this pairing are on record in "
                          f"{TIER_WORDS[fm.tier]}{since_suffix} — too few to call a field win "
                          f"rate.")
        )
    else:
        fm = snap.field_matchup
        field_rate = round(100 * fm.matches_won / fm.n)
        findings.append(
            Finding(
                code="field_matchup_rate",
                analyzer=ANALYZER, category=Category.BASELINE, severity=Severity.NOTE,
                confidence=Confidence.OBSERVED,
                title=f"The field wins this matchup {field_rate}% of the time",
                detail=(
                    f"Across {fm.n} matches in {TIER_WORDS[fm.tier]}{since_suffix}, "
                    f"{snap.own_archetype.name if snap.own_archetype else 'your archetype'} has "
                    f"beaten {snap.opponent_label or 'this archetype'} {fm.matches_won} times "
                    f"and lost {fm.matches_lost}."
                ),
                evidence=(
                    Evidence("field_matches", "Matches in this tier", fm.n),
                    Evidence("field_wins", "Wins for your archetype", fm.matches_won),
                    Evidence("field_losses", "Losses for your archetype", fm.matches_lost),
                    Evidence("field_rate", "Field win rate for your archetype", field_rate,
                             unit="%"),
                    Evidence("field_tier", "Tournament tier", fm.tier),
                ) + (
                    (
                        Evidence(
                            "paper_size_floor", "Fewest players in a large paper tournament",
                            MIN_LARGE_PAPER_PLAYERS, unit="players",
                        ),
                    )
                    if fm.tier in ("A", "D") else ()
                ),
                caveats=(
                    "Tournament results from one tier only (MTGO or paper, never Arena — "
                    "Arena publishes no event results), the highest-ranked tier with enough "
                    "matches of this pairing.",
                ),
            )
        )

    return AnalyzerResult(tuple(findings), tuple(gaps))
