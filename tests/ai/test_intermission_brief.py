"""The break read's brief half: the plan, its closest alternatives and
the prompt ``table/intermission.py::build_break_read`` takes from
``ai/brief/break_plans.py``, the provider ``sensei_top.ai.providers`` lends
(``api/providers.py``). The local half, and the read without a provider, are
tests/test_intermission.py's.

Synthetic databases, as there: none of this is Player.log parsing, so the
expectations come from ``archetypes/classify.py``'s documented scoring
constants, worked by hand in each docstring (AGENTS.md rule 8).
"""

from __future__ import annotations

import hashlib
import json

import pytest

from sensei_top.ai import providers
from sensei_top.ai.brief.store import Brief, write_brief
from sensei_top.api.sql import _cached_break_read
from sensei_top.db import open_database
from sensei_top.guide.deck import list_identities
from sensei_top.projector.live_state import Intermission, LiveState
from sensei_top.table.intermission import build_break_read

BRIEFS = providers().break_briefs


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_deck(conn, deck_id, *, name=None, fmt="Standard", cards=None):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, 't', 't')",
        (deck_id, name, fmt, json.dumps(cards or {"maindeck": [], "sideboard": []})),
    )


def _insert_match(
    conn, match_id, deck_id, result, started_at, *, event_id="Traditional_Ladder", best_of=None
):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, best_of) "
        "VALUES (?, ?, ?, 1, 2, 'u', 'n', ?, ?, ?, 0, 0, 'r', ?)",
        (match_id, event_id, deck_id, started_at, started_at, result, best_of),
    )


def _insert_override(conn, match_id, *, label, archetype_key=None):
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, archetype_key) VALUES (?, ?, ?)",
        (match_id, label, archetype_key),
    )


def _insert_fallback(conn, *, fmt, source, name, common_cards):
    """A ``kind='fallback'``, ``include_color=0`` definition with no
    ``Conditions``, so its colour factor is 1.0 (tests/test_intermission.py's
    helper of the same name says why)."""
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, "
        "fetched_at) VALUES (?, 'fallback', ?, ?, 0, ?, 't')",
        (fmt, source, name, json.dumps({"CommonCards": common_cards})),
    )


def _insert_games(conn, match_id, results):
    for number, result in enumerate(results, start=1):
        conn.execute(
            "INSERT INTO games (match_id, game_number, result) VALUES (?, ?, ?)",
            (match_id, number, result),
        )


def _brief(deck_key, archetype_key, **overrides) -> Brief:
    defaults = dict(
        deck_key=deck_key, archetype_key=archetype_key, archetype_label=None,
        archetype_share=None, personal_matches=None, personal_wins=None, personal_losses=None,
        prose="prose", play_around=(), board_in=(), board_out=(), staples=(), problems=(),
        prompt="prompt", model="claude-sonnet-5", generated_at="2026-09-20T00:00:00.000Z",
        corpus_commit=None, list_hash="hash", source="live",
    )
    defaults.update(overrides)
    return Brief(**defaults)


def _live_at_break(*, game_number=1, won=True, reason="ResultReason_Concede", zone_cards=()):
    return LiveState(
        self_seat=1, opponent_seat=2, turn_number=None, active_seat=None,
        life={}, hand={}, library={}, graveyard={}, open_mana={}, other_mana_sources={},
        zone_cards=zone_cards, offer=None,
        intermission=Intermission(game_number=game_number, won=won, reason=reason),
    )


class _FakeAppState:
    """Just enough of ``app.state`` for ``_cached_break_read``'s caches and
    ``providers_of``."""


class _FakeApp:
    def __init__(self):
        self.state = _FakeAppState()


class _FakeRequest:
    def __init__(self):
        self.app = _FakeApp()


def test_manual_override_gives_an_exact_plan_and_beats_any_live_read(conn):
    """The manual pick's precedence: ``opponent_deck_override`` always
    wins, checked before ``classify_seen`` is ever called
    (``table/intermission.py``'s ``_resolve_opponent`` returns on the
    override row before it even looks at ``fmt``/``names``), which is what
    lets this test name the opponent without seeding archetype definitions.
    With a brief already stored for the picked archetype, the plan is
    'exact'."""
    deck_id = "deck-exact"
    _insert_deck(
        conn, deck_id, name="Test Deck", cards={"maindeck": [101, 102], "sideboard": [201]}
    )
    _insert_match(conn, "m-exact", deck_id, "incomplete", "2026-09-20T00:00:00")
    _insert_override(conn, "m-exact", label="Rogue Aggro", archetype_key="rogue-aggro")
    conn.commit()

    identity = next(i for i in list_identities(conn) if deck_id in i.deck_ids)
    write_brief(conn, _brief(identity.key, "rogue-aggro", archetype_label="Rogue Aggro"))
    conn.commit()

    result = build_break_read(
        conn, "m-exact", deck_id, _live_at_break(), caches={}, names=[], briefs=BRIEFS
    )

    assert result is not None
    assert result.opponent is not None
    assert result.opponent.source == "manual"
    assert result.opponent.archetype_key == "rogue-aggro"
    assert result.opponent.confidence == "high"
    assert result.plan_basis == "exact"
    assert result.plan is not None and result.plan.archetype_key == "rogue-aggro"
    assert result.plan_archetype_label == "Rogue Aggro"
    assert result.alternatives == ()
    assert result.prompt is None  # already have an exact plan; nothing to draft
    assert result.deck_key == identity.key


def test_closest_alternative_plan_when_the_named_archetype_has_no_brief(conn):
    """The closest plan: the chosen archetype (a live rule-engine read, no
    override) has no stored brief of its own, but a *different* archetype
    the classifier also ranked does — offered as the closest alternative,
    never substituted silently for the actual read.

    Two ``fallback`` definitions, hand-computed against classify.py's own
    constants (read directly, not run-and-observed — AGENTS.md rule 8):
    revealing all 4 of fallback-a's common cards vs. 2 of fallback-b's 4
    gives fit_a = 0.5 * min(4/4, 1) * 1.0 = 0.5 and fit_b = 0.5 * min(2/4, 1)
    * 1.0 = 0.25 (``_FALLBACK_FIT_CAP=0.5``, ``_FALLBACK_FIT_RAMP=4``,
    colour factor forced to 1.0 by each definition's empty ``Conditions``).
    margin_a = fit_a / fit_b = 2.0 clears both ``MIN_FALLBACK_FIT`` (0.25)
    and ``MIN_MARGIN`` (1.5), so ``choose()`` commits to fallback-a; its
    fit/margin also clear ``_MEDIUM_FIT``/``_MEDIUM_MARGIN`` (0.30/2.0), so
    its confidence is 'medium'. fallback-b's own fit (0.25) misses
    ``_MEDIUM_FIT``, so it ranks at confidence 'low' — still offered by
    ``rank_candidates`` (only 'none'-confidence rows are dropped), and it is
    the one with a stored brief.
    """
    deck_id = "deck-closest"
    _insert_deck(conn, deck_id, fmt="Standard", cards={"maindeck": [101], "sideboard": []})
    _insert_match(conn, "m-closest", deck_id, "incomplete", "2026-09-20T00:00:00")
    _insert_fallback(
        conn, fmt="Standard", source="fallback-a", name="Fallback A",
        common_cards=["Card A1", "Card A2", "Card A3", "Card A4"],
    )
    _insert_fallback(
        conn, fmt="Standard", source="fallback-b", name="Fallback B",
        common_cards=["Card B1", "Card B2", "Card B3", "Card B4"],
    )
    conn.commit()

    identity = next(i for i in list_identities(conn) if deck_id in i.deck_ids)
    write_brief(conn, _brief(identity.key, "fallback-b", archetype_label="Fallback B"))
    conn.commit()

    names = ["Card A1", "Card A2", "Card A3", "Card A4", "Card B1", "Card B2"]
    result = build_break_read(
        conn, "m-closest", deck_id, _live_at_break(), caches={}, names=names, briefs=BRIEFS,
    )

    assert result is not None
    assert result.opponent is not None
    assert result.opponent.archetype_key == "fallback-a"
    assert result.opponent.confidence == "medium"
    assert result.plan_basis == "closest"
    assert result.plan is not None and result.plan.archetype_key == "fallback-b"
    assert result.plan_archetype_label == "Fallback B"  # a different archetype than opponent.label
    assert [a.archetype_key for a in result.alternatives] == ["fallback-b"]
    assert result.alternatives[0].confidence == "low"


def test_postboard_record_is_none_without_a_named_archetype_or_a_game(conn):
    """Nothing named: ``None`` even though a closest alternative exists and a
    Bo3 was played against it (the record reads ``chosen_key`` only). Named,
    but the only earlier match is a Bo1: ``None`` as well."""
    deck_id = "deck-post-none"
    _insert_deck(conn, deck_id, cards={"maindeck": [101], "sideboard": []})
    _insert_match(conn, "m-cur", deck_id, "incomplete", "2026-09-20T00:00:00", best_of=3)
    _insert_match(conn, "m-bo1", deck_id, "win", "2026-09-10T00:00:00", best_of=1)
    _insert_override(conn, "m-bo1", label="Rogue Aggro", archetype_key="rogue-aggro")
    _insert_games(conn, "m-bo1", ["loss", "loss"])
    # Two fallbacks, each with two of its four cards revealed, tie at fit
    # 0.25, so the margin
    # (1.0, under MIN_MARGIN 1.5, as hand-computed in the closest-alternative
    # test above) commits to neither: both rank as alternatives, nothing is
    # named. A finished Bo3 was played against the first.
    for source, name in (("fallback-a", "Fallback A"), ("fallback-b", "Fallback B")):
        _insert_fallback(
            conn, fmt="Standard", source=source, name=name,
            common_cards=[f"Card {name[-1]}{i}" for i in range(1, 5)],
        )
    _insert_match(conn, "m-alt", deck_id, "win", "2026-09-11T00:00:00", best_of=3)
    _insert_override(conn, "m-alt", label="Fallback A", archetype_key="fallback-a")
    _insert_games(conn, "m-alt", ["win", "loss", "loss"])
    conn.commit()
    # An alternative is one with a stored brief.
    identity = next(i for i in list_identities(conn) if deck_id in i.deck_ids)
    write_brief(conn, _brief(identity.key, "fallback-a", archetype_label="Fallback A"))
    conn.commit()

    names = ["Card A1", "Card A2", "Card B1", "Card B2"]
    unnamed = build_break_read(
        conn, "m-cur", deck_id, _live_at_break(), caches={}, names=names, briefs=BRIEFS,
    )
    assert unnamed is not None
    assert unnamed.opponent is None or unnamed.opponent.archetype_key is None
    assert [a.archetype_key for a in unnamed.alternatives] == ["fallback-a"]
    assert unnamed.postboard_record is None

    _insert_override(conn, "m-cur", label="Rogue Aggro", archetype_key="rogue-aggro")
    conn.commit()
    named = build_break_read(
        conn, "m-cur", deck_id, _live_at_break(), caches={}, names=[], briefs=BRIEFS
    )
    assert named is not None and named.postboard_record is None


def test_cached_break_read_sees_a_pick_and_a_brief_made_during_the_break(conn):
    """The two things a user actually does *during* a break — pick the
    opponent's deck by hand, then import the brief written from this card's
    own prompt — move no projection token, so the cache key has to carry
    both itself. Without them the card would show the old answer until the
    watcher happened to reproject."""
    deck_id = "deck-edit"
    _insert_deck(conn, deck_id, fmt="Standard", cards={"maindeck": [101], "sideboard": []})
    _insert_match(conn, "m-edit", deck_id, "incomplete", "2026-09-20T00:00:00")
    conn.commit()
    live = _live_at_break()
    request = _FakeRequest()
    request.app.state.providers = providers()

    before = _cached_break_read(request, conn, "m-edit", deck_id, live)
    assert before is not None and before.opponent is None

    _insert_override(conn, "m-edit", label="Rogue Aggro", archetype_key="rogue-aggro")
    conn.commit()
    picked = _cached_break_read(request, conn, "m-edit", deck_id, live)
    assert picked.opponent is not None and picked.opponent.source == "manual"
    assert picked.plan is None

    identity = next(i for i in list_identities(conn) if deck_id in i.deck_ids)
    write_brief(conn, _brief(identity.key, "rogue-aggro", archetype_label="Rogue Aggro"))
    conn.commit()
    imported = _cached_break_read(request, conn, "m-edit", deck_id, live)
    assert imported.plan_basis == "exact"
    assert imported.plan is not None and imported.plan.archetype_key == "rogue-aggro"


def _hash_of(maindeck: dict[int, int], sideboard: dict[int, int]) -> str:
    """``ai/brief/store.py::list_hash``'s documented rule, written out: the
    SHA-256 of both boards as sorted ``[grp_id, count]`` pairs, JSON with
    sorted keys."""
    payload = json.dumps(
        {"maindeck": sorted(maindeck.items()), "sideboard": sorted(sideboard.items())},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# The deck both staleness tests play: 101 x2 and 102 main, 201 side.
_CARDS = {"maindeck": [101, 101, 102], "sideboard": [201]}
_CURRENT = _hash_of({101: 2, 102: 1}, {201: 1})
_STALENESS = [
    pytest.param(_CURRENT, "commit-now", False, id="same-75-same-corpus"),
    pytest.param(_hash_of({101: 2}, {201: 1}), "commit-now", True, id="other-75"),
    pytest.param(_CURRENT, "commit-before", True, id="other-corpus"),
]


def _store_corpus_commit(conn, sha):
    conn.execute(
        "INSERT INTO meta_fetch (id, commit_sha, fetched_at, window_days, events) "
        "VALUES (1, ?, 't', 30, 0)",
        (sha,),
    )


@pytest.mark.parametrize(("list_hash", "corpus_commit", "stale"), _STALENESS)
def test_an_exact_plan_is_stale_for_another_75_or_another_corpus(
    conn, list_hash, corpus_commit, stale
):
    """``BreakBriefs.plan`` works staleness out: the brief's ``list_hash``
    against the deck's current 75, its ``corpus_commit`` against
    ``meta_fetch``'s (``commit-now``). Either differing is stale."""
    deck_id = "deck-stale-exact"
    _insert_deck(conn, deck_id, cards=_CARDS)
    _insert_match(conn, "m-stale", deck_id, "incomplete", "2026-09-20T00:00:00")
    _insert_override(conn, "m-stale", label="Rogue Aggro", archetype_key="rogue-aggro")
    _store_corpus_commit(conn, "commit-now")
    conn.commit()
    identity = next(i for i in list_identities(conn) if deck_id in i.deck_ids)
    write_brief(conn, _brief(
        identity.key, "rogue-aggro", list_hash=list_hash, corpus_commit=corpus_commit,
    ))
    conn.commit()

    result = build_break_read(
        conn, "m-stale", deck_id, _live_at_break(), caches={}, names=[], briefs=BRIEFS
    )

    assert result is not None and result.plan_basis == "exact"
    assert result.stale is stale


@pytest.mark.parametrize(("list_hash", "corpus_commit", "stale"), _STALENESS)
def test_a_closest_plan_carries_its_own_staleness(conn, list_hash, corpus_commit, stale):
    """The closest plan's ``stale`` is the first alternative's own. Revealing
    all four of fallback-a's cards names it (fit 0.5, as worked in the
    closest-alternative test above) and two of fallback-b's ranks it at
    0.25; only fallback-b has a brief."""
    deck_id = "deck-stale-closest"
    _insert_deck(conn, deck_id, cards=_CARDS)
    _insert_match(conn, "m-stale", deck_id, "incomplete", "2026-09-20T00:00:00")
    for source, name in (("fallback-a", "Fallback A"), ("fallback-b", "Fallback B")):
        _insert_fallback(
            conn, fmt="Standard", source=source, name=name,
            common_cards=[f"Card {name[-1]}{i}" for i in range(1, 5)],
        )
    _store_corpus_commit(conn, "commit-now")
    conn.commit()
    identity = next(i for i in list_identities(conn) if deck_id in i.deck_ids)
    write_brief(conn, _brief(
        identity.key, "fallback-b", list_hash=list_hash, corpus_commit=corpus_commit,
    ))
    conn.commit()

    names = ["Card A1", "Card A2", "Card A3", "Card A4", "Card B1", "Card B2"]
    result = build_break_read(
        conn, "m-stale", deck_id, _live_at_break(), caches={}, names=names, briefs=BRIEFS,
    )

    assert result is not None and result.plan_basis == "closest"
    assert result.alternatives[0].stale is stale
    assert result.stale is stale
