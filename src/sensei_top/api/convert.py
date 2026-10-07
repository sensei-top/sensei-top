"""The API's own translation layer: one function per domain dataclass,
turning it into the ``*Out`` pydantic model ``api/models/`` declares for
it. Kept in one file rather than split by tag, unlike ``models/`` itself —
several converters (``_leak_out``, ``_play_out``) are shared by more than
one router, and ``_deck_guide_out`` alone composes six of the others, so
splitting this by tag would mean import cycles between the split pieces
rather than one flat, easy-to-scan translation layer.
"""

from __future__ import annotations

from sensei_top.api.models.common import (
    BoardCardOut,
    LeakOut,
    MatchupBriefOut,
    PlanProblemOut,
    PlayAroundOut,
    StapleOut,
)
from sensei_top.api.models.current_match import (
    AlternativePlanOut,
    HandCardOut,
    HandReadOut,
    HandSlotOut,
    IntermissionOpponentOut,
    IntermissionOut,
    KeepGuideOut,
    KeyPlayOut,
    MulliganCostOut,
    MulliganRecordOut,
    OpeningHandCardOut,
    OpeningHandOut,
    PastBoardingCardOut,
    PastBoardingGameOut,
    PastBoardingOut,
    RevealedCardOut,
)
from sensei_top.api.models.guide import (
    ArchetypeChangeOut,
    ArchetypeShareOut,
    CardNoteOut,
    CardVerdictOut,
    CoverageOut,
    CoverageRowOut,
    DeckGuideOut,
    DeckIdentityOut,
    DeckPerformanceOut,
    FieldEvidenceOut,
    FormatResetOut,
    GuideNarrativeOut,
    ListDiffOut,
    MatchupPlanOut,
    PersonalRateOut,
    PlayEvidenceOut,
    ProvenanceOut,
)
from sensei_top.api.models.matches import (
    MatchSummaryOut,
    ReportEvidence,
    ReportFinding,
    SummaryBeat,
    SummaryGameLine,
    SummaryGapGroup,
)
from sensei_top.brief.coverage import Coverage
from sensei_top.brief.store import Brief
from sensei_top.review.findings import Finding
from sensei_top.review.summary import Beat, GameLine, GapGroup, MatchSummary
from sensei_top.table.hand_read import HandCard, HandRead, RevealedCard
from sensei_top.table.intermission import (
    AlternativePlan,
    BreakRead,
    OpponentRead,
    PastBoarding,
    PastBoardingCard,
    PastBoardingGame,
)
from sensei_top.table.keep import KeepGuide
from sensei_top.table.opening_hand import OpeningHandCard, OpeningHandRead


def _matchup_brief_out(brief: Brief) -> MatchupBriefOut:
    return MatchupBriefOut(
        deck_key=brief.deck_key,
        archetype_key=brief.archetype_key,
        archetype_label=brief.archetype_label,
        archetype_share=brief.archetype_share,
        personal_matches=brief.personal_matches,
        personal_wins=brief.personal_wins,
        personal_losses=brief.personal_losses,
        prose=brief.prose,
        play_around=[PlayAroundOut(card=p.card, why=p.why) for p in brief.play_around],
        board_in=[BoardCardOut(card=c.card, n=c.n) for c in brief.board_in],
        board_out=[BoardCardOut(card=c.card, n=c.n) for c in brief.board_out],
        staples=[StapleOut(name=s.name, copies=s.copies, share=s.share) for s in brief.staples],
        problems=[PlanProblemOut(archetype=p.archetype, message=p.message) for p in brief.problems],
        model=brief.model,
        generated_at=brief.generated_at,
        corpus_commit=brief.corpus_commit,
        source=brief.source,
    )


def _coverage_out(coverage: Coverage) -> CoverageOut:
    return CoverageOut(
        fmt=coverage.fmt,
        rows=[
            CoverageRowOut(
                archetype_key=row.archetype_key, label=row.label, times_faced=row.times_faced,
                field_share=row.field_share, status=row.status,
            )
            for row in coverage.rows
        ],
        matches_covered=coverage.matches_covered,
        matches_covered_numerator=coverage.matches_covered_numerator,
        matches_covered_denominator=coverage.matches_covered_denominator,
        field_covered=coverage.field_covered,
    )


def _intermission_opponent_out(opponent: OpponentRead) -> IntermissionOpponentOut:
    return IntermissionOpponentOut(
        label=opponent.label,
        archetype_key=opponent.archetype_key,
        confidence=opponent.confidence,
        source=opponent.source,
    )


def _alternative_plan_out(alt: AlternativePlan) -> AlternativePlanOut:
    return AlternativePlanOut(
        archetype_key=alt.archetype_key,
        label=alt.label,
        confidence=alt.confidence,
        fit=alt.fit,
        brief=_matchup_brief_out(alt.brief),
    )


def _past_boarding_card_out(card: PastBoardingCard) -> PastBoardingCardOut:
    return PastBoardingCardOut(
        grp_id=card.grp_id, card=card.card, n=card.n, in_current_75=card.in_current_75,
    )


def _past_boarding_game_out(game: PastBoardingGame) -> PastBoardingGameOut:
    return PastBoardingGameOut(
        game_number=game.game_number,
        board_in=[_past_boarding_card_out(c) for c in game.board_in],
        board_out=[_past_boarding_card_out(c) for c in game.board_out],
        result=game.result,
        result_reason=game.result_reason,
    )


def _past_boarding_out(past: PastBoarding) -> PastBoardingOut:
    return PastBoardingOut(
        match_id=past.match_id,
        played_at=past.played_at,
        games=[_past_boarding_game_out(g) for g in past.games],
    )


def _intermission_out(read: BreakRead) -> IntermissionOut:
    return IntermissionOut(
        game_number=read.game_number,
        next_game=read.next_game,
        won=read.won,
        reason=read.reason,
        opponent=_intermission_opponent_out(read.opponent) if read.opponent is not None else None,
        cards_seen=read.cards_seen,
        plan=_matchup_brief_out(read.plan) if read.plan is not None else None,
        plan_basis=read.plan_basis,
        plan_archetype_label=read.plan_archetype_label,
        stale=read.stale,
        alternatives=[_alternative_plan_out(a) for a in read.alternatives],
        past_boarding=[_past_boarding_out(p) for p in read.past_boarding],
        prompt=read.prompt,
        deck_key=read.deck_key,
        fmt=read.fmt,
    )


def _hand_card_out(card: HandCard) -> HandCardOut:
    return HandCardOut(
        name=card.name,
        grp_id=card.grp_id,
        type_line=card.type_line,
        mana_cost=card.mana_cost,
        mana_value=card.mana_value,
        tags=list(card.tags),
        tags_known=card.tags_known,
        expected_copies_left=card.expected_copies_left,
        p_in_hand=card.p_in_hand,
        castable_now=card.castable_now,
    )

def _revealed_card_out(card: RevealedCard) -> RevealedCardOut:
    return RevealedCardOut(name=card.name, grp_id=card.grp_id)

def _opening_hand_card_out(card: OpeningHandCard) -> OpeningHandCardOut:
    return OpeningHandCardOut(
        grp_id=card.grp_id,
        name=card.name,
        type_line=card.type_line,
        mana_cost=card.mana_cost,
        is_land=card.is_land,
        mana_value=card.mana_value,
        tags=list(card.tags),
        tags_known=card.tags_known,
        castable_turn=card.castable_turn,
        reduced_castable_turn=card.reduced_castable_turn,
    )

def _opening_hand_out(read: OpeningHandRead) -> OpeningHandOut:
    return OpeningHandOut(
        seat=read.seat,
        mulligan_count=read.mulligan_count,
        on_the_play=read.on_the_play,
        cards=[_opening_hand_card_out(c) for c in read.cards],
        land_count=read.land_count,
        land_min=read.land_min,
        land_max=read.land_max,
        ideal_hand=[HandSlotOut(count=s.count, label=s.label) for s in read.ideal_hand],
        keep_rate=read.keep_rate,
        mulligan_record=[
            MulliganRecordOut(mulligans=m.mulligans, games=m.games, wins=m.wins)
            for m in read.mulligan_record
        ],
        unnamed_count=read.unnamed_count,
        colors_known=read.colors_known,
        verdict=read.verdict,
        reasons=list(read.reasons),
        caveats=list(read.caveats),
    )

def _finding_out(f: Finding) -> ReportFinding:
    """A review.Finding, translated into the API's own contract — the
    dataclass stays internal, the pydantic model is what the frontend sees."""
    return ReportFinding(
        code=f.code,
        analyzer=f.analyzer,
        category=f.category.value,
        severity=f.severity.value,
        confidence=f.confidence.value,
        title=f.title,
        detail=f.detail,
        game_number=f.game_number,
        turn_number=f.turn_number,
        self_turn_index=f.self_turn_index,
        evidence=[
            ReportEvidence(key=e.key, label=e.label, value=e.value, unit=e.unit,
                            display=e.display)
            for e in f.evidence
        ],
        caveats=list(f.caveats),
        pattern=f.pattern,
    )

def _beat_out(b: Beat) -> SummaryBeat:
    return SummaryBeat(
        code=b.code, label=b.label, text=b.text, magnitude=b.magnitude,
        severity=b.severity.value, game_number=b.game_number, meter=b.meter,
    )

def _game_line_out(g: GameLine) -> SummaryGameLine:
    return SummaryGameLine(
        game_number=g.game_number, result=g.result, result_reason_text=g.result_reason_text,
        turn_count=g.turn_count, on_play=g.on_play, self_mulligans=g.self_mulligans,
        beats=[_beat_out(b) for b in g.beats],
    )

def _gap_group_out(g: GapGroup) -> SummaryGapGroup:
    return SummaryGapGroup(cause=g.cause, blocked=list(g.blocked))

def _summary_out(s: MatchSummary) -> MatchSummaryOut:
    return MatchSummaryOut(
        headline=s.headline,
        subhead=s.subhead,
        matchup=[_beat_out(b) for b in s.matchup],
        games=[_game_line_out(g) for g in s.games],
        gap_groups=[_gap_group_out(g) for g in s.gap_groups],
    )

def _leak_out(leak) -> LeakOut:
    """A review.leaks.Leak, translated into the API's own contract — shared
    by ``/api/review/leaks`` and the guide routes, which both surface the
    same leak-finder output at different scopes."""
    return LeakOut(
        code=leak.code, category=leak.category, sample_title=leak.sample_title,
        n_with=leak.n_with, win_rate_with=leak.win_rate_with, ci_with=leak.ci_with,
        n_without=leak.n_without, win_rate_without=leak.win_rate_without,
        ci_without=leak.ci_without, gap=leak.gap,
        match_ids_with=list(leak.match_ids_with),
    )

def _deck_identity_out(identity) -> DeckIdentityOut:
    return DeckIdentityOut(
        key=identity.key, arena_deck_id=identity.arena_deck_id, name=identity.name,
        format=identity.format, deck_ids=list(identity.deck_ids), matches=identity.matches,
        match_wins=identity.match_wins, match_losses=identity.match_losses,
        games_won=identity.games_won, games_lost=identity.games_lost,
        first_played=identity.first_played, last_played=identity.last_played,
    )

def _reset_out(reset) -> FormatResetOut | None:
    if reset is None:
        return None
    return FormatResetOut(
        date=reset.date, cards=list(reset.cards), detected_from=reset.detected_from
    )

def _provenance_out(p) -> ProvenanceOut:
    return ProvenanceOut(
        deck=_deck_identity_out(p.deck), reset=_reset_out(p.reset), window_start=p.window_start,
        matches_before_reset=p.matches_before_reset, corpus_fetched_at=p.corpus_fetched_at,
        corpus_latest_event=p.corpus_latest_event, classified_decks=p.classified_decks,
        oracle_coverage=p.oracle_coverage,
    )

def _play_out(p) -> PlayEvidenceOut:
    return PlayEvidenceOut(
        board_curve=p.board_curve, zone_curve=p.zone_curve, key_card_timing=p.key_card_timing,
        mulligan_record=p.mulligan_record, game_length=p.game_length,
    )

def _card_verdict_out(c) -> CardVerdictOut:
    return CardVerdictOut(
        card=c.card, yours=c.yours, board=c.board, consensus_copies=c.consensus_copies,
        consensus_share=c.consensus_share, recommended=c.recommended, verdict=c.verdict,
    )

def _list_diff_out(d) -> ListDiffOut | None:
    if d is None:
        return None
    return ListDiffOut(
        archetype_key=d.archetype_key, archetype_name=d.archetype_name,
        winning_decks=d.winning_decks, min_wins=d.min_wins,
        maindeck=[_card_verdict_out(c) for c in d.maindeck],
        sideboard=[_card_verdict_out(c) for c in d.sideboard],
        duplicate_warnings=list(d.duplicate_warnings),
    )

def _field_evidence_out(f) -> FieldEvidenceOut:
    return FieldEvidenceOut(
        fmt=f.fmt, window_start=f.window_start, classified_decks=f.classified_decks,
        shares=[
            ArchetypeShareOut(
                archetype=s.archetype, decks=s.decks, share=s.share,
                share_before_reset=s.share_before_reset, movement=s.movement,
            )
            for s in f.shares
        ],
        changes={
            name: ArchetypeChangeOut(
                archetype=c.archetype, pre_reset_decks=c.pre_reset_decks,
                fraction_playing_a_banned_card=c.fraction_playing_a_banned_card,
                banned_cards=list(c.banned_cards), post_reset_decks=c.post_reset_decks,
                verdict=c.verdict, carryable=c.carryable,
            )
            for name, c in f.changes.items()
        },
        personal_rates=[
            PersonalRateOut(
                archetype=r.archetype, matches=r.matches, wins=r.wins, losses=r.losses,
                carryable=r.carryable,
            )
            for r in f.personal_rates
        ],
        own_performance=(
            DeckPerformanceOut(
                decks=f.own_performance.decks, wins=f.own_performance.wins,
                losses=f.own_performance.losses, win_rate=f.own_performance.win_rate,
            )
            if f.own_performance is not None else None
        ),
        corpus_fetched_at=f.corpus_fetched_at, corpus_latest_event=f.corpus_latest_event,
    )

def _deck_guide_out(guide) -> DeckGuideOut:
    return DeckGuideOut(
        provenance=_provenance_out(guide.provenance),
        play=_play_out(guide.play),
        leaks=[_leak_out(leak) for leak in guide.leaks],
        leaks_all_decks=[_leak_out(leak) for leak in guide.leaks_all_decks],
        list_diff=_list_diff_out(guide.list_diff),
        field=_field_evidence_out(guide.field),
        gaps=list(guide.gaps),
    )

def _guide_narrative_out(n) -> GuideNarrativeOut:
    return GuideNarrativeOut(
        engine=n.engine, fix=n.fix,
        card_notes=[CardNoteOut(card=c.card, verdict=c.verdict, why=c.why) for c in n.card_notes],
        matchups=[
            MatchupPlanOut(
                archetype=m.archetype, prose=m.prose,
                board_in=[BoardCardOut(card=c.card, n=c.n) for c in m.board_in],
                board_out=[BoardCardOut(card=c.card, n=c.n) for c in m.board_out],
            )
            for m in n.matchups
        ],
        checklist=list(n.checklist),
        problems=[PlanProblemOut(archetype=p.archetype, message=p.message) for p in n.problems],
    )


def _keep_guide_out(keep: KeepGuide | None) -> KeepGuideOut | None:
    if keep is None:
        return None
    return KeepGuideOut(
        maindeck_size=keep.maindeck_size,
        land_count=keep.land_count,
        unnamed_count=keep.unnamed_count,
        creature_count=keep.creature_count,
        interaction_count=keep.interaction_count,
        untagged_count=keep.untagged_count,
        avg_mana_value=keep.avg_mana_value,
        cheap_count=keep.cheap_count,
        curve=[[mv, n] for mv, n in keep.curve],
        land_min=keep.land_min,
        land_max=keep.land_max,
        ideal_hand=[HandSlotOut(count=s.count, label=s.label) for s in keep.ideal_hand],
        early_plays=keep.early_plays,
        land_odds=[[float(k), p] for k, p in keep.land_odds],
        expected_lands_seven=keep.expected_lands_seven,
        expected_lands_eight=keep.expected_lands_eight,
        keep_rate=keep.keep_rate,
        mulligan_record=[
            MulliganRecordOut(mulligans=m.mulligans, games=m.games, wins=m.wins)
            for m in keep.mulligan_record
        ],
        notes=list(keep.notes),
        key_plays=[
            KeyPlayOut(
                card=kp.card,
                best_band=kp.best_band,
                best_band_wins=kp.best_band_record.w,
                best_band_losses=kp.best_band_record.l,
                never_resolved_wins=kp.never_resolved.w,
                never_resolved_losses=kp.never_resolved.l,
                n=kp.n,
            )
            for kp in keep.key_plays
        ],
        mulligan_cost=(
            MulliganCostOut(
                kept_seven_games=keep.mulligan_cost.kept_seven.games,
                kept_seven_wins=keep.mulligan_cost.kept_seven.wins,
                kept_seven_losses=keep.mulligan_cost.kept_seven.losses,
                mulliganed_games=keep.mulligan_cost.mulliganed.games,
                mulliganed_wins=keep.mulligan_cost.mulliganed.wins,
                mulliganed_losses=keep.mulligan_cost.mulliganed.losses,
            )
            if keep.mulligan_cost is not None
            else None
        ),
    )


def _hand_read_out(hand: HandRead) -> HandReadOut:
    return HandReadOut(
        status=hand.status,
        archetype_key=hand.archetype_key,
        archetype_label=hand.archetype_label,
        deck_count=hand.deck_count,
        hand_size=hand.hand_size,
        hidden_pool=hand.hidden_pool,
        open_mana=hand.open_mana,
        other_mana_sources=hand.other_mana_sources,
        held_turns=hand.held_turns,
        known_in_hand=[_revealed_card_out(c) for c in hand.known_in_hand],
        revealed_this_match=[_revealed_card_out(c) for c in hand.revealed_this_match],
        interaction=[_hand_card_out(c) for c in hand.interaction],
        threats=[_hand_card_out(c) for c in hand.threats],
        caveats=list(hand.caveats),
    )
