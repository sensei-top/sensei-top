"""The live matchup brief's prompt, and the shape of the answer.

What to play around against one opponent archetype, and a game-2 swap plan,
from two decklists and the field — never a game.

**No call is made from here, and — unlike the match report and the deck
guide (``docs/llm.md``) — this feature has no generate button at all.**
``build_brief_context`` assembles the evidence and ``full_prompt`` wraps it
with the framing; ``sensei-top brief --deck KEY --archetype KEY --prompt``
prints it, a Claude Code session on an already-paid-for subscription (or any
assistant) writes the answer, and ``--import FILE`` reads it back into
``matchup_brief`` where the Current match tab picks it up. A generated or
imported deck guide (``POST /api/guide/{key}/narrative`` or ``guide
--import``) fills the same table for every matchup it covers, so most
briefs arrive that way without any per-matchup work at all — which is
exactly why a standalone generate button here would mostly duplicate a
call the guide already made.

**The property that makes this cheap to produce and safe to store is that a
brief is a function of ``(deck, archetype)``, never of a game.** No board
state, no turn, no life total, no hand, no match id ever appears in the
prompt this module builds — ``tests/test_brief_context.py`` pins that. It is
why one authored brief is reusable across every future match against that
archetype rather than being written per game, and why the earlier live
advisor's objection (see ``review/narrative.py``) does not apply: that asked
what to do on a board it could not see; this asks what a decklist does to
another decklist.

**What is sent** (``build_brief_context``): the player's current 75 with
oracle text, the opponent archetype's label and windowed field share, its
consensus staples (at most ``BRIEF_MAX_STAPLES``) with oracle text, the
player's own record against that archetype with this deck, and one ranked
field record for the pairing when the corpus has one
(``metagame.matchup.ranked_field_matchup``, walking Tier A, then B, then D
and naming whichever it lands on). A closing "not given to you"
block names everything about an in-progress game that is deliberately
absent, so whoever writes the brief is never left to assume silence means
something happened.

**What comes back**: the JSON object ``_BRIEF_TOOL``'s schema describes —
still the contract, now for an import rather than a forced tool call.
``brief_from_json`` parses it; ``brief/worker.py``'s import path validates
the plan against the real 75 via ``guide.plans.validate_plans`` before it is
ever stored.
"""


from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

from sensei_top.answers import brief_for, coverage_for
from sensei_top.brief.store import PlayAround, Staple, list_hash
from sensei_top.guide.deck import DeckIdentity, identity_format
from sensei_top.guide.field import _classified_deck_total, field_window, personal_rate
from sensei_top.guide.narrative import (
    BoardCard,
    _oracle_text_block,
    _parse_json_object,
    _wrap_json_prompt,
)
from sensei_top.guide.window import format_resets, legality_known, window_start
from sensei_top.i18n import english
from sensei_top.metagame.matchup import ranked_field_matchup
from sensei_top.metagame.tiers import TIER_WORDS
from sensei_top.review.consensus import ArchetypeConsensus, build_consensus
from sensei_top.review.narrative import NarrativeError

__all__ = [
    "BriefFacts",
    "MultiBriefPrompt",
    "NarrativeError",
    "brief_from_json",
    "briefs_from_json",
    "build_brief_context",
    "full_multi_prompt",
    "full_prompt",
]

BRIEF_MAX_STAPLES = 15  # their consensus list, with oracle text

SYSTEM_PROMPT = (
    "You are writing a short matchup brief for one Magic: The Gathering Arena deck "
    "against one opponent archetype, in the tradition of the game's own strategy writing. "
    "You are given the player's full 75 with oracle text, the opponent archetype's "
    "consensus decklist from real tournament results with oracle text, and the player's "
    "own record in the matchup. Name the specific cards to play around and say concretely "
    "why, from the card text given. Give one game-2 swap plan, balanced, using only cards "
    "the player actually has, at exact counts, named exactly as given. You are not shown "
    "any game in progress — never refer to a board, a turn, a life total, or a hand. Say "
    "when something is inferred from card text rather than measured, and mark it "
    "(reasoned). Never invent a card, a number, or a sample size not given to you."
)

_BRIEF_TOOL = {
    "name": "emit_brief",
    "description": "Return a short matchup brief: what to play around and a game-2 plan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "prose": {
                "type": "string",
                "description": "2-4 short paragraphs: what their deck does to yours and how "
                "the matchup is actually won. Mark inference from card text (reasoned).",
            },
            "play_around": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"card": {"type": "string"}, "why": {"type": "string"}},
                    "required": ["card", "why"],
                },
                "description": "At most 5, most important first.",
            },
            "board_in": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"card": {"type": "string"}, "n": {"type": "integer"}},
                    "required": ["card", "n"],
                },
            },
            "board_out": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"card": {"type": "string"}, "n": {"type": "integer"}},
                    "required": ["card", "n"],
                },
            },
        },
        "required": ["prose", "play_around", "board_in", "board_out"],
    },
}


@dataclass(frozen=True, slots=True)
class BriefFacts:
    """The structured numbers behind the prose — stored alongside a
    generated brief so the frontend can show a share and a personal record
    without parsing them back out of text, and computed here from the same
    two queries the prompt's own sentences are built from, so the two can
    never disagree."""

    staples: tuple[Staple, ...]
    archetype_share: float | None
    personal_matches: int | None
    personal_wins: int | None
    personal_losses: int | None


def _archetype_share(
    conn: sqlite3.Connection, archetype_key: str, fmt: str, *, since: str | None
) -> float | None:
    """Share is always computed within the current format-reset window
    (``since``, when one is detected) — never the whole corpus. Pooling
    across an undetected reset is exactly the failure ``guide/window.py``
    exists to prevent (``docs/metagame.md``'s "format-reset boundary"); a
    live brief is not exempt from that discipline just because it skips the
    guide's other, more expensive machinery.

    The denominator is ``guide/field.py``'s own ``_classified_deck_total``
    — the single source for the truncated-denominator guard both modules
    used to warn about separately. Only the denominator is shared: this
    function's own count below is scoped to one ``archetype_key`` with no
    top-N truncation, unlike ``_shares_for_window``'s name-keyed, capped
    list, so there is no shared count query to converge on.
    """
    where, params = field_window(fmt, since)

    total = _classified_deck_total(conn, where, params)
    if not total:
        return None
    count = conn.execute(
        f"SELECT COUNT(*) FROM meta_deck_archetype a JOIN meta_event e ON e.event_id = a.event_id "
        f"WHERE {where} AND a.archetype_key = ?",
        (*params, archetype_key),
    ).fetchone()[0]
    return count / total


def _current_window_start(conn: sqlite3.Connection, fmt: str) -> str | None:
    """The day after the most recent detected format reset, or ``None`` for
    the whole corpus when there isn't one — the same rule
    ``guide/bundle.py`` uses to pick a guide's own window. A brief skips the
    guide's more expensive ``structural_change`` (which archetype changed
    shape at the reset), but it must never skip the window itself: an
    un-windowed consensus or share is exactly the mistake the hand-written
    guide made once (``docs/guide.md``'s "Why this exists"). ``None`` does
    not mean "no reset happened" — see ``_window_note``."""
    resets = format_resets(conn, fmt)
    if not resets:
        return None
    return window_start(resets[0])


def _window_note(conn: sqlite3.Connection, fmt: str, since: str | None) -> str:
    """One sentence saying what the field numbers below actually span.

    The third case is the one that bites: with no legality data on this
    machine no ban is detectable, so "no format reset detected" would state
    as a fact about the format what is really a hole in the local data, and
    the brief's shares and consensus would quietly pool across a ban
    (``guide.window.legality_known``)."""
    if since is not None:
        return (
            f"Field data below is windowed to {fmt} decks from {since} onward (a format "
            f"reset was detected)."
        )
    if legality_known(conn, fmt):
        return (
            f"Field data below covers the whole stored {fmt} corpus — no format reset "
            f"detected."
        )
    return (
        f"Field data below covers the whole stored {fmt} corpus. No card legality data is "
        f"present here, so a format reset cannot be detected at all: these numbers may pool "
        f"across a ban. Treat them as unwindowed."
    )


def _own_seventy_five_block(
    conn: sqlite3.Connection, identity: DeckIdentity
) -> tuple[str, list[int]]:
    maindeck = identity.current_cards.get("maindeck") or []
    sideboard = identity.current_cards.get("sideboard") or []
    grp_ids = list({*maindeck, *sideboard})
    if not grp_ids:
        return "", []
    names = {
        row["grp_id"]: row["name"]
        for row in conn.execute(
            f"SELECT grp_id, name FROM cards WHERE grp_id IN ({','.join('?' for _ in grp_ids)})",
            grp_ids,
        )
    }
    main_counts = Counter(maindeck)
    side_counts = Counter(sideboard)
    lines = ["Maindeck:"]
    for grp_id, n in sorted(main_counts.items(), key=lambda kv: names.get(kv[0], "")):
        lines.append(f"  {n}x {names.get(grp_id, '?')}")
    lines.append("Sideboard:")
    for grp_id, n in sorted(side_counts.items(), key=lambda kv: names.get(kv[0], "")):
        lines.append(f"  {n}x {names.get(grp_id, '?')}")
    return "\n".join(lines), grp_ids


_NOT_GIVEN = (
    "Not given to you, and not to be assumed: there is no game in progress here — "
    "no board state, no turn number, no life totals, no hand, no match result. This "
    "brief is about two decklists and the field, not a specific game."
)


def _opponent_section(
    conn: sqlite3.Connection,
    identity: DeckIdentity,
    archetype_key: str,
    archetype_label: str | None,
    *,
    fmt: str,
    since: str | None,
    consensus: ArchetypeConsensus | None,
    own_archetype_key: str | None,
    shown_grp_ids: set[int] | None = None,
) -> tuple[list[str], BriefFacts] | None:
    """Everything a brief says about one opponent archetype — share,
    consensus staples with their card text, the player's own record, one
    ranked-tier field record — or ``None`` when the consensus does not clear
    ``build_consensus``'s ``min_decks`` gate. Shared by the one-archetype
    and the several-archetype prompt so the two can never describe the same
    matchup differently.

    ``shown_grp_ids``, when given, is the card text already printed earlier
    in the same prompt: those cards are left out of this section's text
    block and the set is updated in place. A consensus staple shared by
    three archetypes is then described once, not three times."""
    if consensus is None:
        consensus = build_consensus(
            conn, archetype_key, fmt=fmt, board="main", since=since
        )
    if consensus is None:
        return None

    top_cards = consensus.cards[:BRIEF_MAX_STAPLES]
    staples = tuple(Staple(name=c.name, copies=c.copies, share=c.share) for c in top_cards)
    opp_grp_ids = [c.grp_id for c in top_cards if c.grp_id is not None]
    if shown_grp_ids is not None:
        opp_grp_ids = [g for g in opp_grp_ids if g not in shown_grp_ids]
        shown_grp_ids.update(opp_grp_ids)
    opp_oracle = _oracle_text_block(conn, opp_grp_ids)
    archetype_share = _archetype_share(conn, archetype_key, fmt, since=since)

    lines: list[str] = [
        f"Opponent archetype: {archetype_label or archetype_key}" + (
            f" ({archetype_share:.1%} of the classified field)"
            if archetype_share is not None else ""
        ),
        "Their consensus decklist (from real tournament results):",
    ]
    for staple in staples:
        lines.append(f"  {staple.copies:.1f}x {staple.name} ({staple.share:.0%} of decks)")
    lines.append("")
    if shown_grp_ids is None:
        lines.append("Card text for their consensus staples:")
    else:
        lines.append(
            "Card text for their consensus staples (a card already described earlier in "
            "this prompt is not repeated):"
        )
    lines.append(opp_oracle)

    rate = personal_rate(conn, identity.deck_ids, archetype_label or "")
    lines.append("")
    if rate is not None:
        lines.append(
            f"Your own record with this deck against {archetype_label}: "
            f"{rate.wins}-{rate.losses} across {rate.matches} matches."
        )
    else:
        lines.append(f"Your own record with this deck against {archetype_label}: no matches yet.")

    if own_archetype_key is not None:
        ranked = ranked_field_matchup(
            conn, own_archetype_key, archetype_key, since, fmt=fmt
        )
        if ranked is not None:
            since_clause = f" since {since}" if since else ""
            lines.append(
                f"Field record for this pairing, from {TIER_WORDS[ranked.tier]}{since_clause}: "
                f"{ranked.matches_won}-{ranked.matches_lost} across {ranked.n} matches."
            )

    facts = BriefFacts(
        staples=staples,
        archetype_share=archetype_share,
        personal_matches=rate.matches if rate is not None else None,
        personal_wins=rate.wins if rate is not None else None,
        personal_losses=rate.losses if rate is not None else None,
    )
    return lines, facts


@english()
def build_brief_context(
    conn: sqlite3.Connection,
    identity: DeckIdentity,
    archetype_key: str,
    archetype_label: str | None,
    *,
    fmt: str | None = None,
    consensus: ArchetypeConsensus | None = None,
    own_archetype_key: str | None = None,
) -> tuple[str, BriefFacts] | None:
    """Build the prompt text and the structured facts behind it, or
    ``None`` when there is nothing to write about — the opponent
    archetype's consensus does not clear ``build_consensus``'s own
    ``min_decks`` gate, or the deck's format is unknown (no field to read a
    window from). That is a real gap, never guessed around.
    """
    if fmt is None:
        fmt = identity_format(conn, identity)
    if fmt is None:
        return None
    since = _current_window_start(conn, fmt)
    section = _opponent_section(
        conn, identity, archetype_key, archetype_label, fmt=fmt, since=since,
        consensus=consensus, own_archetype_key=own_archetype_key,
    )
    if section is None:
        return None
    section_lines, facts = section

    own_block, own_grp_ids = _own_seventy_five_block(conn, identity)
    own_oracle = _oracle_text_block(conn, own_grp_ids)

    lines: list[str] = [
        f"Deck: {identity.name or identity.key}",
        _window_note(conn, fmt, since),
        "",
        "Your current 75:",
        own_block,
        "",
        "Card text for your own maindeck and sideboard:",
        own_oracle,
        "",
        *section_lines,
        "",
        _NOT_GIVEN,
    ]
    return "\n".join(lines), facts


# --- several briefs in one prompt ---------------------------------------------

MULTI_BRIEF_MAX = 8  # matchups per prompt; the rest wait for the next round

MULTI_SYSTEM_PROMPT = (
    "You are writing several short matchup briefs for one Magic: The Gathering Arena "
    "deck — one brief per opponent archetype section below — in the tradition of the "
    "game's own strategy writing. You are given the player's full 75 with oracle text "
    "once, then one section per opponent archetype: its consensus decklist from real "
    "tournament results with oracle text (a card already described earlier is not "
    "repeated), and the player's own record in that matchup. Write each brief on its own "
    "terms, as if it were the only one: never refer to another section, and never carry a "
    "claim from one matchup into another. In each, name the specific cards to play around "
    "and say concretely why, from the card text given, and give one game-2 swap plan, "
    "balanced, using only cards the player actually has, at exact counts, named exactly "
    "as given. Write exactly one brief per section, in the order given, and copy each "
    "section's archetype key into that brief's archetype_key character for character. You "
    "are not shown any game in progress — never refer to a board, a turn, a life total, or "
    "a hand. Say when something is inferred from card text rather than measured, and mark "
    "it (reasoned). Never invent a card, a number, or a sample size not given to you."
)

_MULTI_BRIEF_TOOL = {
    "name": "emit_briefs",
    "description": "Return one short matchup brief per opponent archetype section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "briefs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "archetype_key": {
                            "type": "string",
                            "description": "The section's archetype key, copied exactly.",
                        },
                        **_BRIEF_TOOL["input_schema"]["properties"],
                    },
                    "required": [
                        "archetype_key", *_BRIEF_TOOL["input_schema"]["required"],
                    ],
                },
            },
        },
        "required": ["briefs"],
    },
}


@dataclass(frozen=True, slots=True)
class MultiBriefPrompt:
    """One prompt covering several matchups, and an honest account of the
    ones it left out: ``no_consensus`` has nothing to anchor a brief to
    (the same gap ``full_prompt`` returns ``None`` for), ``deferred`` is
    past ``MULTI_BRIEF_MAX`` and waits for the next round."""

    prompt: str
    included: tuple[str, ...]
    no_consensus: tuple[str, ...]
    deferred: tuple[str, ...]


@english()
def full_multi_prompt(
    conn: sqlite3.Connection,
    identity: DeckIdentity,
    archetypes: list[tuple[str, str | None]],
    *,
    fmt: str | None = None,
    own_archetype_key: str | None = None,
    limit: int = MULTI_BRIEF_MAX,
) -> MultiBriefPrompt | None:
    """One prompt asking for a brief per ``(archetype_key, label)`` in
    ``archetypes``, in the caller's order (most important first — the
    caller's ranking decides what ``limit`` defers, not this function).
    The player's 75 and its card text appear once, not once per matchup.
    It ends with the answer contract for the deck's coverage card
    (``answers.coverage_for``) and the 75 it is written for.
    ``None`` when not one archetype has a consensus to write from.

    Each section is built by the same ``_opponent_section`` the single-brief
    prompt uses, and ``brief/importer.py`` stores each answer through the
    single-brief path — so a brief written from this prompt is stored with
    exactly the context and facts a one-at-a-time import would have given
    it.

    ``None`` too when the deck's format is unknown."""
    if fmt is None:
        fmt = identity_format(conn, identity)
    if fmt is None:
        return None
    since = _current_window_start(conn, fmt)
    shown: set[int] = set()
    sections: list[tuple[str, list[str]]] = []
    no_consensus: list[str] = []
    deferred: list[str] = []
    for archetype_key, label in archetypes:
        if len(sections) >= limit:
            deferred.append(archetype_key)
            continue
        section = _opponent_section(
            conn, identity, archetype_key, label, fmt=fmt, since=since, consensus=None,
            own_archetype_key=own_archetype_key, shown_grp_ids=shown,
        )
        if section is None:
            no_consensus.append(archetype_key)
            continue
        sections.append((archetype_key, section[0]))
    if not sections:
        return None

    own_block, own_grp_ids = _own_seventy_five_block(conn, identity)
    own_oracle = _oracle_text_block(conn, own_grp_ids)
    lines: list[str] = [
        f"Deck: {identity.name or identity.key}",
        _window_note(conn, fmt, since),
        "",
        "Your current 75:",
        own_block,
        "",
        "Card text for your own maindeck and sideboard:",
        own_oracle,
    ]
    for i, (archetype_key, section_lines) in enumerate(sections, start=1):
        lines += [
            "",
            f"=== Matchup {i} of {len(sections)} — archetype_key: {archetype_key} ===",
            *section_lines,
        ]
    lines += [
        "",
        "Not given to you, and not to be assumed: there is no game in progress here — "
        "no board state, no turn number, no life totals, no hand, no match result. These "
        "briefs are about decklists and the field, not a specific game.",
    ]
    prompt = _wrap_json_prompt(
        MULTI_SYSTEM_PROMPT, _MULTI_BRIEF_TOOL["input_schema"], "\n".join(lines),
        answer_for=coverage_for(identity.key),
        written_for=list_hash(identity.current_cards),
    )
    return MultiBriefPrompt(
        prompt=prompt,
        included=tuple(key for key, _ in sections),
        no_consensus=tuple(no_consensus),
        deferred=tuple(deferred),
    )


def briefs_from_json(raw: str | dict) -> list[tuple[str, dict]]:
    """Parse an answer to ``full_multi_prompt`` into ``(archetype_key,
    parsed)`` pairs, each ``parsed`` exactly what ``brief_from_json``
    returns for one brief. All or nothing: a malformed item, or the same key
    twice, raises ``NarrativeError`` naming it rather than storing part of
    an answer the user then has to reconcile by hand."""
    raw = _parse_json_object(raw)
    items = raw.get("briefs")
    if not isinstance(items, list) or not items:
        raise NarrativeError("expected a non-empty 'briefs' array.")
    out: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        key = item.get("archetype_key") if isinstance(item, dict) else None
        if not isinstance(key, str) or not key:
            raise NarrativeError(f"briefs[{i}] has no archetype_key.")
        if key in seen:
            raise NarrativeError(f"archetype_key {key!r} appears twice.")
        seen.add(key)
        try:
            out.append((key, brief_from_json(item)))
        except NarrativeError as exc:
            raise NarrativeError(f"briefs[{i}] ({key}): {exc}") from exc
    return out


def _play_around_from(raw: dict) -> tuple[PlayAround, ...]:
    return tuple(PlayAround(card=p["card"], why=p["why"]) for p in raw.get("play_around", []))


def _board_from(raw: dict, key: str) -> tuple[BoardCard, ...]:
    return tuple(BoardCard(card=c["card"], n=c["n"]) for c in raw.get(key, []))


@english()
def full_prompt(
    conn: sqlite3.Connection, identity: DeckIdentity, archetype_key: str,
    archetype_label: str | None, **kwargs,
) -> tuple[str, BriefFacts] | None:
    """The complete text to hand an assistant, ending with the answer
    contract (``answers.py``) for this deck and archetype and the 75 it is
    written for, plus the structured facts to store beside whatever it
    writes. ``None`` when there is no consensus for
    the archetype, or the deck's format is unknown — a real gap, never guessed
    around."""
    built = build_brief_context(conn, identity, archetype_key, archetype_label, **kwargs)
    if built is None:
        return None
    context, facts = built
    prompt = _wrap_json_prompt(
        SYSTEM_PROMPT, _BRIEF_TOOL["input_schema"], context,
        answer_for=brief_for(identity.key, archetype_key),
        written_for=list_hash(identity.current_cards),
    )
    return prompt, facts


def brief_from_json(raw: str | dict) -> dict:
    """Parse an authored brief into the same dict shape the removed API call
    used to return. Raises ``NarrativeError`` on anything malformed."""
    raw = _parse_json_object(raw)
    try:
        return {
            "prose": raw["prose"],
            "play_around": _play_around_from(raw),
            "board_in": _board_from(raw, "board_in"),
            "board_out": _board_from(raw, "board_out"),
        }
    except (KeyError, TypeError) as exc:
        raise NarrativeError(f"missing or malformed field: {exc}") from exc
