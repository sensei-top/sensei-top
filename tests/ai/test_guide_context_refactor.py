"""The deck guide's prompt context against its pre-refactor form. Split from
``tests/test_guide_rcq.py`` (the RCQ evidence), whose corpus helpers are
copied below; this one needs ``ai/guide/narrative.py``.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.ai.guide.narrative import (
    MIN_TIMES_FACED,
    MOST_FACED_ARCHETYPES,
    TOP_ARCHETYPES_FOR_ORACLE_TEXT,
    _oracle_text_block,
    build_guide_context,
)
from sensei_top.db import open_database
from sensei_top.guide.bundle import DeckGuide, build_deck_guide
from sensei_top.guide.field import archetype_key_by_name, faced_archetypes
from sensei_top.guide.list_diff import ListDiff
from sensei_top.guide.markdown import render
from sensei_top.review.consensus import build_consensus


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _card_row(conn, grp_id, name, oracle):
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text, type_line, mana_cost) VALUES "
        "(?, ?, ?, 'Instant', '{R}')",
        (grp_id, name, oracle),
    )


def _event(conn, event_id, event_date, *, name="e", source="MTGO", duplicate_of=None):
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, format, "
        "tier, duplicate_of) VALUES (?, 'p', 's', ?, ?, ?, 'Standard', 'B', ?)",
        (event_id, source, name, event_date, duplicate_of),
    )


def _deck(conn, event_id, deck_ord, card, *, key=None, name=None, result=None):
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, result, mainboard_json, sideboard_json, "
        "wins) VALUES (?, ?, ?, ?, '[]', 3)",
        (event_id, deck_ord, result, json.dumps([{"count": 4, "name": card}])),
    )
    if key is not None:
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES (?, ?, ?, ?, ?, "
            "'archetype', 'now')",
            (event_id, deck_ord, key, name, name),
        )


def _corpus(conn, key, n, *, event_date="2026-09-20"):
    """n classified decks of archetype key ("Arch <key>"), one event each,
    every deck playing 4x "Staple <key>" — a consensus once n >= 5."""
    for i in range(n):
        _event(conn, f"{key}-{i}", event_date)
        _deck(conn, f"{key}-{i}", 0, f"Staple {key}", key=key, name=f"Arch {key}")


def _own_deck(conn):
    """Deck d1 and one won match with it, so build_deck_guide resolves it."""
    _card_row(conn, 1, "Own Card", "Own card text.")
    _card_row(conn, 2, "Mountain", None)
    _card_row(conn, 3, "Side Card", "Side card text.")
    _card_row(conn, 4, "Front Face // Back Face", "Double-faced text.")
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Standard', ?, 't', 't')",
        (json.dumps({"maindeck": [1] * 4 + [2] * 56, "sideboard": [3, 3]}),),
    )
    _match(conn, "m-own", "2026-09-28T12:00:00", "win")


def _match(conn, match_id, started_at, result):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, format) VALUES (?, 'e', 'd1', 1, 2, 'u', 'n', ?, ?, "
        "?, ?, ?, 'concede', 'Standard')",
        (match_id, started_at, started_at, result,
         2 if result == "win" else 0, 0 if result == "win" else 2),
    )


def _faced(conn, key, n):
    """n lost matches of deck d1 against a classifier verdict for key."""
    for i in range(n):
        match_id = f"faced-{key}-{i}"
        _match(conn, match_id, f"2026-09-2{i}T12:00:00", "loss")
        conn.execute(
            "INSERT INTO opponent_archetype (match_id, format, archetype_key, "
            "archetype_name, colors, label, method, confidence, cards_seen, "
            "conditions_met, conditions_unknown, evidence_json, classified_at) VALUES "
            "(?, 'Standard', ?, ?, 'R', ?, 'archetype', 'high', 3, '[]', '[]', '{}', 'now')",
            (match_id, key, f"Arch {key}", f"Arch {key}"),
        )


# Seven archetypes with 10, 9, 8, 7, 6, 6 and 5 decks: 51 classified decks.
_SEVEN = {"a1": 10, "a2": 9, "a3": 8, "a4": 7, "a5": 6, "a6": 6, "a7": 5}


def _seven_archetypes(conn):
    for grp_id, (key, n) in enumerate(_SEVEN.items(), start=100):
        _card_row(conn, grp_id, f"Staple {key}", f"Staple {key} text.")
        _corpus(conn, key, n)


def test_build_guide_context_is_unchanged_by_the_section_refactor(conn):
    """The deck guide's own prompt context, byte for byte against the
    function as it stood before its section loop was shared with the RCQ
    guide (copied below), on a guide with top-share and most-faced
    sections and a staple's oracle text shared between two archetypes."""
    _own_deck(conn)
    _seven_archetypes(conn)
    for key in ("f1", "f2"):
        _card_row(conn, 300 + int(key[1]), f"Staple {key}", f"Staple {key} text.")
        _corpus(conn, key, 5)
    _faced(conn, "f1", 4)
    _faced(conn, "f2", 3)
    _faced(conn, "a1", 3)
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    expected = _pre_refactor_build_guide_context(guide, conn=conn)
    assert "-- Arch f1 (you faced it 4 times" in expected  # both passes exercised
    assert build_guide_context(guide, conn=conn) == expected


# The pre-refactor ai/guide/narrative.py::build_guide_context, verbatim but for
# its name — the reference the test above compares against.
def _pre_refactor_build_guide_context(guide: DeckGuide, *, conn) -> str | None:
    """Serialize a deck guide into the text a prompt sends. ``None`` when
    there is nothing to write about — a deck with no matches at all.
    """
    if guide.provenance.deck.matches == 0:
        return None

    lines: list[str] = [
        f"Deck: {guide.provenance.deck.name or guide.provenance.deck.key}",
        render(guide),
        "",
        "Card oracle text for your own maindeck and sideboard:",
    ]
    own_grp_ids = list({
        *(guide.provenance.deck.current_cards.get("maindeck") or []),
        *(guide.provenance.deck.current_cards.get("sideboard") or []),
    })
    lines.append(_oracle_text_block(conn, own_grp_ids))

    diff: ListDiff | None = guide.list_diff
    own_name = diff.archetype_name if diff is not None else None
    own_key = diff.archetype_key if diff is not None else None
    key_by_name = archetype_key_by_name(conn)
    since = guide.provenance.window_start
    # Oracle text is printed once per card across every opponent section —
    # and not at all for a card already given with the player's own 75 —
    # since the same staples recur across archetypes and each repeat is pure
    # prompt cost.
    shown_grp_ids: set[int] = set(own_grp_ids)

    def section(heading: str, archetype_key: str) -> bool:
        consensus = build_consensus(conn, archetype_key, fmt=guide.field.fmt, since=since)
        if consensus is None:
            return False
        staples = consensus.staples()
        lines.append(heading)
        for card in staples:
            lines.append(f"  {card.copies:.1f}x {card.name} ({card.share:.0%} of decks)")
        grp_ids = [
            c.grp_id for c in staples
            if c.grp_id is not None and c.grp_id not in shown_grp_ids
        ]
        shown_grp_ids.update(grp_ids)
        text = _oracle_text_block(conn, grp_ids)
        if text:
            lines.append(text)
        return True

    lines.append("")
    lines.append(
        f"Consensus staples and oracle text for the top {TOP_ARCHETYPES_FOR_ORACLE_TEXT} "
        f"opponent archetypes by field share (a card's oracle text is given once, the first "
        f"time it appears):"
    )
    shown_keys: set[str] = set()
    for share in guide.field.shares:
        if len(shown_keys) >= TOP_ARCHETYPES_FOR_ORACLE_TEXT:
            break
        if share.archetype == own_name:
            continue
        archetype_key = key_by_name.get(share.archetype)
        if archetype_key is None or archetype_key in shown_keys:
            continue
        if section(
            f"-- {share.archetype} ({share.share:.1%} of the field) --", archetype_key,
        ):
            shown_keys.add(archetype_key)

    share_by_name = {s.archetype: s.share for s in guide.field.shares}
    faced = sorted(
        (
            (key, name, n)
            for key, (name, n) in faced_archetypes(
                conn, guide.provenance.deck.deck_ids, since=since,
            ).items()
            # key_by_name.get(name) == key: ai/brief/from_guide.py stores each
            # plan under key_by_name[plan.archetype], so a name that maps to
            # another key would file this matchup's plan under the wrong one.
            if n >= MIN_TIMES_FACED and key not in shown_keys and key != own_key
            and key_by_name.get(name) == key
        ),
        key=lambda t: (-t[2], t[0]),
    )
    faced_lines_at = len(lines)
    shown_faced = 0
    for key, name, n in faced:
        if shown_faced >= MOST_FACED_ARCHETYPES:
            break
        share = share_by_name.get(name)
        share_text = (
            f"{share:.1%} of the field" if share is not None
            else "not among the field's top archetypes"
        )
        window_text = "since the reset" if since is not None else "in your history"
        if section(f"-- {name} (you faced it {n} times {window_text}; {share_text}) --", key):
            shown_faced += 1
    if shown_faced:
        lines.insert(faced_lines_at, "")
        lines.insert(
            faced_lines_at + 1,
            f"Consensus staples and oracle text for the archetypes you have actually faced "
            f"most (at least {MIN_TIMES_FACED} times each), not already listed above:",
        )

    return "\n".join(lines)
