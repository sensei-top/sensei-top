"""The keep guide: what a keepable opening hand looks like for the deck being
played right now, from its maindeck and its own past games — no board state,
so this is as valid during the mulligan decision as at any later point in the
game. See docs/current-match.md, "The keep guide (`table/keep.py`)".

``review.effects`` does the per-card classification, so a card with no
downloaded rules text degrades to ``"unknown"`` (AGENTS.md rule 4), never
guessed from the name alone.

``land_min``/``land_max``/``ideal_hand``/``land_odds`` all depend on knowing
every maindeck card's type line, so they are withheld (``None``/empty) rather
than computed on a partial deck list whenever
``v_deck_land_count.unnamed_count`` is nonzero — a wrong number here is worse
than a missing one, since "3 lands, 2 spells" is advice a player will act on.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from sensei_top.guide import play as guide_play
from sensei_top.guide.deck import DeckIdentity, list_identities
from sensei_top.guide.play import MulliganBucket, WLTally, key_card_timing
from sensei_top.i18n import N_, _, decimal, ngettext, percent
from sensei_top.review import effects

# The heuristics below are deliberately coarse — a single cutoff on curve
# shape, not a simulation of the deck's actual gameplan. They exist to turn
# "I know this deck" into a number, not to replace judgment on a borderline
# hand.
_CHEAP_MANA_VALUE = 2
_LOW_CURVE_CHEAP_SHARE = 0.40
_LOW_CURVE_LAND_MIN = 2
_HIGH_CURVE_LAND_MIN = 3
_LOW_CURVE_LAND_MAX = 4
_HIGH_CURVE_LAND_MAX = 5
_LOW_CURVE_AVG_MV = 3.0
_EARLY_PLAYS_THRESHOLD = 8
_THREAT_CREATURE_SHARE = 0.35
_OPENING_HAND_SIZE = 7

# The deck's own play evidence is only worth citing once there is enough of
# it — the same floor review/leaks.py's
# MIN_SAMPLE and review/analyzers/baseline.py's PLAY_DRAW_MIN_GAMES already
# hold a split to, applied here at two levels: whether key_plays/
# mulligan_cost appear at all (against the identity's total decided games),
# and, per key card, which turn band counts as its "best" one (against that
# band's own games) -- see _best_key_play_band.
_MIN_EVIDENCE_GAMES = 10


@dataclass(frozen=True, slots=True)
class HandSlot:
    """One line of the suggested-hand shape, e.g. ``3`` / ``"lands"``."""

    count: int
    label: str


@dataclass(frozen=True, slots=True)
class MulliganRecord:
    """This deck's own real record at one mulligan count — the empirical
    half of the keep guide, needing no reconstruction of the hand actually
    *kept*, whose zone transfers arrive only after the decision
    (``migrations/009_drop_opening_hand.sql``). ``table/opening_hand.py``
    reads a different message, the offer itself, which arrives before it."""

    mulligans: int
    games: int
    wins: int


@dataclass(frozen=True, slots=True)
class KeyPlay:
    """One of this deck's own key cards (``guide/play.py``'s
    ``_choose_key_cards`` ranking — >=3 copies, finishers first, then mana
    value), chosen from the decklist and card text rather than a hand-kept threat table.
    ``best_band`` is the turn band (``key_card_timing``'s own labels: "by
    T4", "T5-6", "T7-8", "T9+") this card's record is strongest from, among
    bands sampled enough to mean something — see ``_best_key_play_band``.
    ``never_resolved`` is the same card's record across every game where it
    never hit the battlefield at all, so a keep guide can show what naming
    this threat is worth *and* what missing it costs. ``n`` is every decided
    game this identity has played — the same total behind every key card's
    numbers, since ``key_card_timing`` buckets every game for every card,
    resolved or not."""

    card: str
    best_band: str
    best_band_record: WLTally
    never_resolved: WLTally
    n: int


@dataclass(frozen=True, slots=True)
class MulliganCost:
    """This deck's own kept-seven vs. mulliganed-to-six-or-fewer record —
    ``guide/play.mulligan_record`` verbatim, reused rather than
    recomputed, so a keep guide and a deck guide can never disagree about
    it. ``opening_hand.py``'s verdict reads this as a brake: a
    deck that pays little for mulliganing can afford to ship a marginal
    hand; one that pays a lot should not be nudged toward mulliganing on a
    close call."""

    kept_seven: MulliganBucket
    mulliganed: MulliganBucket


# The turn bands ``key_card_timing`` buckets a card's first resolve into are
# codes (dict keys, compared and grouped on elsewhere); a sentence that embeds
# one writes it through this map.
_BAND_WORDS: dict[str, str] = {
    "by T4": N_("by T4"),
    "T5-6": N_("T5-6"),
    "T7-8": N_("T7-8"),
    "T9+": N_("T9+"),
    "never resolved": N_("never resolved"),
}


def band_word(band: str) -> str:
    """``band`` as display text in the current language; an unrecognized
    band is written as it is."""
    return _(_BAND_WORDS[band]) if band in _BAND_WORDS else band


def _best_key_play_band(bands: dict[str, WLTally]) -> tuple[str, WLTally] | None:
    """The turn band ``key_card_timing`` measured this card doing best from,
    restricted first to bands with at least ``_MIN_EVIDENCE_GAMES`` decided
    games — otherwise a single early fluky resolve (say 1-0 off one game)
    would out-rank a band actually played out hundreds of times, the exact
    failure the repo's MIN_SAMPLE/PLAY_DRAW_MIN_GAMES convention exists to
    avoid elsewhere. Falls back to the best win rate among all bands when none
    of them clear that bar, rather than naming no band at all for a card that
    otherwise qualified as one of this deck's key cards. Returns ``None``
    only when every band (bar "never resolved") is literally empty."""
    candidates = {band: tally for band, tally in bands.items() if band != "never resolved"}
    if not candidates:
        return None

    def games(tally: WLTally) -> int:
        return tally.w + tally.l

    qualified = {b: t for b, t in candidates.items() if games(t) >= _MIN_EVIDENCE_GAMES}
    pool = qualified or candidates

    def win_rate(tally: WLTally) -> float:
        n = games(tally)
        return tally.w / n if n else 0.0

    best_band = max(pool, key=lambda b: (win_rate(pool[b]), games(pool[b])))
    return best_band, pool[best_band]


def _build_key_plays(conn: sqlite3.Connection, identity: DeckIdentity) -> tuple[KeyPlay, ...]:
    """``key_card_timing`` for this identity's key cards, reshaped into the
    keep guide's own ``KeyPlay`` rows — one per card, in the same
    finisher/mana-value order ``_choose_key_cards`` ranked them in, since
    ``key_card_timing``'s dict preserves that order."""
    timing = key_card_timing(conn, identity)
    plays: list[KeyPlay] = []
    for card, bands in timing.items():
        best = _best_key_play_band(bands)
        if best is None:
            continue
        best_band, record = best
        never_resolved = bands.get("never resolved", WLTally(w=0, l=0))
        n = sum(tally.w + tally.l for tally in bands.values())
        plays.append(
            KeyPlay(
                card=card,
                best_band=best_band,
                best_band_record=record,
                never_resolved=never_resolved,
                n=n,
            )
        )
    return tuple(plays)


@dataclass(frozen=True, slots=True)
class KeepGuide:
    deck_id: str
    maindeck_size: int
    land_count: int
    unnamed_count: int
    creature_count: int
    interaction_count: int
    untagged_count: int
    avg_mana_value: float | None
    cheap_count: int
    curve: tuple[tuple[int, int], ...]  # (mana_value, copies), nonlands only, 7 means "7+"
    land_min: int | None
    land_max: int | None
    ideal_hand: tuple[HandSlot, ...]
    early_plays: int | None  # ideal_hand's own "play(s) at 1-2 mana" count, exposed as a
    # bare int for table/opening_hand.py's verdict — ideal_hand only carries it as a
    # formatted label
    land_odds: tuple[tuple[int, float], ...]  # (k, P(exactly k lands in 7)), k = 0..7
    expected_lands_seven: float | None
    expected_lands_eight: float | None  # on the draw
    keep_rate: float | None  # P(land_min <= lands in opening 7 <= land_max)
    mulligan_record: tuple[MulliganRecord, ...]
    key_plays: tuple[KeyPlay, ...]  # () below _MIN_EVIDENCE_GAMES decided games -- see notes
    mulligan_cost: MulliganCost | None  # None below _MIN_EVIDENCE_GAMES decided games
    notes: tuple[str, ...]


def _hypergeometric_pmf(population: int, successes: int, draws: int, k: int) -> float:
    """P(exactly k successes) drawing `draws` cards without replacement from
    a `population`-card library holding `successes` copies of the thing
    counted — exact, via binomial coefficients, since a 7-card opening hand
    needs no sequential approximation the way a fractional expected-copy
    count elsewhere in this package does."""
    if k < 0 or k > draws or k > successes or (draws - k) > (population - successes):
        return 0.0
    return (
        math.comb(successes, k)
        * math.comb(population - successes, draws - k)
        / math.comb(population, draws)
    )


_EM_DASH = "—"


def _land_prefix_has_land(type_line: str) -> bool:
    """Mirrors ``v_deck_land_count``'s own SQL exactly
    (``migrations/011_review_views.sql``): ``'Land'`` is checked only in the
    prefix up to and including the first em dash, or the whole ``type_line``
    when there is none — traced by hand against SQLite's 1-based
    ``instr``/``substr`` semantics (rule 8: never by running the view and
    copying its output)."""
    idx = type_line.find(_EM_DASH)
    prefix = type_line if idx == -1 else type_line[: idx + 1]
    return "Land" in prefix


def _maindeck_land_counts(
    conn: sqlite3.Connection, maindeck: Sequence[int]
) -> tuple[int, int, int]:
    """``(maindeck_size, land_count, unnamed_count)`` for an arbitrary grp_id
    sequence, computed the same way ``v_deck_land_count`` computes them for a
    ``decks`` row — but directly against ``cards``, for a maindeck that has
    no ``decks`` row to join yet. ``unnamed_count`` matches the view's own
    ``c.name IS NULL`` test (true both for a grp_id with no ``cards`` row at
    all, and for one whose row has a NULL ``name``)."""
    counts = Counter(int(g) for g in maindeck)
    maindeck_size = sum(counts.values())
    if not counts:
        return 0, 0, 0
    placeholders = ",".join("?" * len(counts))
    rows = conn.execute(
        f"SELECT grp_id, name, type_line FROM cards WHERE grp_id IN ({placeholders})",
        tuple(counts),
    ).fetchall()
    by_id = {r["grp_id"]: r for r in rows}
    land_count = 0
    unnamed_count = 0
    for grp_id, qty in counts.items():
        row = by_id.get(grp_id)
        if row is None or row["name"] is None:
            unnamed_count += qty
            continue
        type_line = row["type_line"]
        if type_line is not None and _land_prefix_has_land(type_line):
            land_count += qty
    return maindeck_size, land_count, unnamed_count


def build_keep_guide(
    conn: sqlite3.Connection,
    deck_id: str | None,
    *,
    maindeck: Sequence[int] | None = None,
    boarded: bool = False,
) -> KeepGuide | None:
    """The keep guide for one deck, or ``None`` when there is no deck to
    build one from (no ``deck_id``, or an empty/unknown maindeck).

    ``maindeck`` supplies the land/creature/interaction/curve numbers when
    ``v_deck_land_count`` has no row for ``deck_id`` yet — a list
    ``project()`` has never rebuilt for: the live replay's own
    ``LiveState.deck_maindeck``, read straight off ``connectResp`` rather
    than waiting on a ``decks`` row. It is read the same way
    ``v_deck_land_count`` itself is (``_maindeck_land_counts``/
    ``_land_prefix_has_land`` mirror that view's own em-dash rule, since
    there is no ``decks`` row to join the view against yet), and ignored
    once a ``v_deck_land_count`` row exists.

    ``boarded`` (the replay saw a SubmitDeckResp, so ``maindeck`` is the list
    held after a sideboarding break) makes ``maindeck`` the source of every
    list-derived number and the per-card loop, even when a ``decks`` row
    exists: that row is game 1's. The mulligan record still reads by
    ``deck_id``, game 1's deck.
    """
    if deck_id is None:
        return None

    use_maindeck = boarded and bool(maindeck)
    land_row = None if use_maindeck else conn.execute(
        "SELECT maindeck_size, land_count, unnamed_count FROM v_deck_land_count "
        "WHERE deck_id = ?",
        (deck_id,),
    ).fetchone()
    if land_row is not None and land_row["maindeck_size"]:
        maindeck_size = land_row["maindeck_size"]
        land_count = land_row["land_count"]
        unnamed_count = land_row["unnamed_count"]
    elif maindeck:
        maindeck_size, land_count, unnamed_count = _maindeck_land_counts(conn, maindeck)
        if not maindeck_size:
            return None
    else:
        return None

    deck_row = (
        None
        if use_maindeck
        else conn.execute(
            "SELECT cards_json FROM decks WHERE deck_id = ?", (deck_id,)
        ).fetchone()
    )
    if deck_row is not None:
        maindeck_grp_ids = json.loads(deck_row["cards_json"]).get("maindeck") or []
    else:
        # No decks row (the same case that sent maindeck_size/land_count/
        # unnamed_count through the _maindeck_land_counts fallback above) —
        # reuse the caller's own maindeck for the per-card loop below rather
        # than reading a row that doesn't exist yet.
        maindeck_grp_ids = list(maindeck) if maindeck else []
    counts = Counter(int(g) for g in maindeck_grp_ids)

    by_id: dict[int, sqlite3.Row] = {}
    if counts:
        rows = conn.execute(
            f"SELECT grp_id, type_line, mana_cost, oracle_text FROM cards "
            f"WHERE grp_id IN ({','.join('?' * len(counts))})",
            tuple(counts),
        ).fetchall()
        by_id = {r["grp_id"]: r for r in rows}

    creature_count = 0
    interaction_count = 0
    untagged_count = 0
    cheap_count = 0
    curve_totals: dict[int, int] = {}
    mv_weighted_sum = 0.0
    mv_weighted_n = 0

    for grp_id, qty in counts.items():
        row = by_id.get(grp_id)
        if row is None:
            continue  # unnamed — already flagged via unnamed_count, never guessed at
        type_line = row["type_line"]
        if effects.is_land(type_line):
            continue
        if effects.is_creature(type_line):
            creature_count += qty
        tags = effects.classify(row["oracle_text"], type_line, row["mana_cost"])
        if isinstance(tags, effects.EffectTags):
            if "spot_removal" in tags or "sweeper" in tags or "counterspell" in tags:
                interaction_count += qty
        else:
            untagged_count += qty
        mv = effects.mana_value(row["mana_cost"])
        if mv is not None:
            curve_totals[min(mv, 7)] = curve_totals.get(min(mv, 7), 0) + qty
            mv_weighted_sum += mv * qty
            mv_weighted_n += qty
            if mv <= _CHEAP_MANA_VALUE:
                cheap_count += qty

    avg_mana_value = mv_weighted_sum / mv_weighted_n if mv_weighted_n else None
    curve = tuple(sorted(curve_totals.items()))
    nonlands = maindeck_size - land_count

    notes: list[str] = []
    land_min: int | None = None
    land_max: int | None = None
    ideal_hand: tuple[HandSlot, ...] = ()
    early_plays: int | None = None
    land_odds: tuple[tuple[int, float], ...] = ()
    expected_lands_seven: float | None = None
    expected_lands_eight: float | None = None
    keep_rate: float | None = None

    if unnamed_count > 0:
        notes.append(
            ngettext(
                "{n} maindeck card(s) are not in the card table yet, so land "
                "counts here may be undercounted — run 'sensei-top cards' for a keepable-hand "
                "band.",
                "{n} maindeck card(s) are not in the card table yet, so land "
                "counts here may be undercounted — run 'sensei-top cards' for a keepable-hand "
                "band.",
                unnamed_count,
            ).format(n=unnamed_count)
        )
    elif nonlands <= 0 or avg_mana_value is None:
        notes.append(
            _(
                "This deck's nonland cards don't carry enough mana-cost data to read a curve "
                "from — no keepable-hand band without one."
            )
        )
    else:
        cheap_share = cheap_count / nonlands
        land_min = (
            _LOW_CURVE_LAND_MIN if cheap_share >= _LOW_CURVE_CHEAP_SHARE else _HIGH_CURVE_LAND_MIN
        )
        land_max = (
            _LOW_CURVE_LAND_MAX if avg_mana_value <= _LOW_CURVE_AVG_MV else _HIGH_CURVE_LAND_MAX
        )
        notes.append(
            _(
                "Land band from this deck's own curve ({cheap_share} of nonland cards at "
                "mana value {cheap_value} or less, average mana value {avg_mana_value}): "
                "keepable hands run {land_min}-{land_max} lands."
            ).format(
                cheap_share=percent(cheap_share),
                cheap_value=_CHEAP_MANA_VALUE,
                avg_mana_value=decimal(avg_mana_value, 1),
                land_min=land_min,
                land_max=land_max,
            )
        )

        early = 2 if cheap_count >= _EARLY_PLAYS_THRESHOLD else 1
        early_plays = early
        threat = 1 if creature_count / nonlands >= _THREAT_CREATURE_SHARE else 0
        raw_lands = round(_OPENING_HAND_SIZE * land_count / maindeck_size)
        lands_in_hand = max(land_min, min(land_max, raw_lands))
        flex = _OPENING_HAND_SIZE - lands_in_hand - early - threat

        slots = [
            HandSlot(lands_in_hand, ngettext("land", "lands", lands_in_hand)),
            HandSlot(
                early, ngettext("play at 1-2 mana", "plays at 1-2 mana", early)
            ),
        ]
        if threat:
            slots.append(HandSlot(threat, _("creature")))
        if flex > 0:
            slots.append(HandSlot(flex, ngettext("flex slot", "flex slots", flex)))
        ideal_hand = tuple(slots)

        odds = tuple(
            (k, _hypergeometric_pmf(maindeck_size, land_count, _OPENING_HAND_SIZE, k))
            for k in range(_OPENING_HAND_SIZE + 1)
        )
        land_odds = odds
        expected_lands_seven = _OPENING_HAND_SIZE * land_count / maindeck_size
        expected_lands_eight = (_OPENING_HAND_SIZE + 1) * land_count / maindeck_size
        keep_rate = sum(p for k, p in odds if land_min <= k <= land_max)

    mulligan_rows = conn.execute(
        """
        SELECT g.self_mulligans AS mulligans, COUNT(*) AS games,
               SUM(CASE WHEN g.result = 'win' THEN 1 ELSE 0 END) AS wins
          FROM games g JOIN matches m USING (match_id)
         WHERE m.deck_id = ? AND g.result IN ('win', 'loss') AND g.self_mulligans IS NOT NULL
         GROUP BY g.self_mulligans
         ORDER BY g.self_mulligans
        """,
        (deck_id,),
    ).fetchall()
    mulligan_record = tuple(
        MulliganRecord(mulligans=r["mulligans"], games=r["games"], wins=r["wins"] or 0)
        for r in mulligan_rows
    )

    # This deck's own play evidence, scoped to the DeckIdentity (the stable
    # Arena GUID) containing this deck_id -- the same lookup
    # api/routes/current_match.py::_brief_response makes, so a list edit that
    # mints a new deck_id never loses the identity's history.
    identity = next((i for i in list_identities(conn) if deck_id in i.deck_ids), None)
    key_plays: tuple[KeyPlay, ...] = ()
    mulligan_cost: MulliganCost | None = None
    if identity is not None:
        play_mrec = guide_play.mulligan_record(conn, identity)
        kept_seven = play_mrec.get("kept_seven")
        mulliganed = play_mrec.get("mulliganed")
        decided_games = (kept_seven.games if kept_seven else 0) + (
            mulliganed.games if mulliganed else 0
        )
        if decided_games < _MIN_EVIDENCE_GAMES:
            notes.append(
                ngettext(
                    "This deck has only {decided_games} decided game(s) on record -- key "
                    "plays and the mulligan cost need at least {minimum} before a split "
                    "means anything.",
                    "This deck has only {decided_games} decided game(s) on record -- key "
                    "plays and the mulligan cost need at least {minimum} before a split "
                    "means anything.",
                    decided_games,
                ).format(decided_games=decided_games, minimum=_MIN_EVIDENCE_GAMES)
            )
        else:
            key_plays = _build_key_plays(conn, identity)
            if kept_seven is not None and mulliganed is not None:
                mulligan_cost = MulliganCost(kept_seven=kept_seven, mulliganed=mulliganed)

    return KeepGuide(
        deck_id=deck_id,
        maindeck_size=maindeck_size,
        land_count=land_count,
        unnamed_count=unnamed_count,
        creature_count=creature_count,
        interaction_count=interaction_count,
        untagged_count=untagged_count,
        avg_mana_value=avg_mana_value,
        cheap_count=cheap_count,
        curve=curve,
        land_min=land_min,
        land_max=land_max,
        ideal_hand=ideal_hand,
        early_plays=early_plays,
        land_odds=land_odds,
        expected_lands_seven=expected_lands_seven,
        expected_lands_eight=expected_lands_eight,
        keep_rate=keep_rate,
        mulligan_record=mulligan_record,
        key_plays=key_plays,
        mulligan_cost=mulligan_cost,
        notes=tuple(notes),
    )
