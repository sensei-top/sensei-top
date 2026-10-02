"""MTGO decode/parse/project tests — the "Live MTGO matches" plan's step 11.

Ground truth is read from the real fixture
(``tests/fixtures/mtgo_match_session.log``, 7838 bytes) with
``uv run python scripts/mtgo_probe.py tests/fixtures/mtgo_match_session.log
--force --lines 400`` (AGENTS.md non-negotiable #8) — never by running
``decode_strings``/``parse_strings`` and copying their output. What follows is
what that read showed, recorded here so it stays a check on the code rather
than a mirror of it.

The match GUID is ``f2244feb-54e1-48ec-b3c5-711b20844adf``, appearing twice at
the very start, before any game content.

Game 1: Player2000 rolled a 3, Player1 rolled a 5; Player1 chooses to play
first; both begin with seven cards (no mulligan); the highest *printed*
per-player turn is Turn 5 (Player1's own fifth turn — MTGO's per-player
numbering, never Player2000's), but there are 9 ``Turn N:`` lines total in
the game (Turn 1/1/2/2/3/3/4/4/5, one per player-turn) — ``turn_count`` is in
Arena's units (``parse.py``'s "Turn units"), a count of those lines, so this
game's is 9, not 5. Player2000 concedes, Player1 wins the game; the running
score line reads "Player1 leads the match 1-0" (self-check text, never
authoritative). 28 card events (plays/casts/activates/triggers) across the
whole game.

Game 2: Player2000 chooses to play first; Player2000 mulligans to six cards
(the running "mulligans to six cards" line and the authoritative "puts a card
on the bottom ... begins the game with six cards in hand" line agree, so no
mismatch warning); Player1 keeps seven; the highest printed per-player turn
is Turn 4, but 8 ``Turn N:`` lines total (1/1/2/2/3/3/4/4) — ``turn_count``
is 8, not 4; Player2000 concedes again, Player1 wins the game; the final line
reads "Player1 wins the match 2-0" — the only line that sets
``winner_handle``. 17 card events.
28 + 17 = 45 total, matching the plan's full-fixture ``project()`` expectation.

*** Correction to parse.py's own module docstring ***
The docstring claims "26 distinct @[...] names in the fixture, all 26
reachable through just those four line shapes." The first half is right:
26 distinct bracketed ``@[Name@:i1,i2:@]`` references do appear somewhere in
the file (cross-checked with a ``grep -oP '(?<=@\\[)[^@]+(?=@:)'`` extraction
over the probe's own decoded output, plus a manual add-back for the 5
occurrences of ``Kíli the Resourceful`` that the probe's ASCII-only scanner
corrupts by splitting on the two-byte UTF-8 sequence for 'í'). The second half
does not hold: only 25 of those 26 names are ever the *captured* name of a
plays/casts/activates/triggered-from line. The 26th, "Zombie Druid Token", is
bracketed exactly once in the whole fixture — as the *target* clause of
Thorin, Mountain-king's second triggered-ability line ("...puts a triggered
ability from @[Thorin, Mountain-king@:...] onto the stack (...) targeting
@[Zombie Druid Token@:...]."). ``_TRIGGER_RE`` (like ``_ACTIVATES_RE``) has no
trailing ``$`` anchor and captures only the ability's *source* card — nothing
in parse.py's grammar captures a second, trailing ``@[...]`` reference on the
same line. Zombie Druid Token is a token: it is never played, cast, given its
own "activates an ability of", or given its own "puts a triggered ability
from" line anywhere in the fixture (tokens are never "cast" or "played" in
MTGO's own log text). See ``test_25_of_26_bracketed_names_become_card_events``
below and the handoff note.

*** Also checked against the plan's own Verification section ***
The plan says (line ~494) "a deleted `wins the game` line -> exactly one
cross-check warning and the counted value kept." No such cross-check exists
anywhere in parse.py or project.py: ``_WINS_GAME_RE``'s handler unconditionally
sets ``current.winner_handle`` with no comparison against anything, and
nothing else in either module reacts to a missing "wins the game" line — so
deleting one produces zero warnings, not one. The plan's own Step 2
implementation spec (the only place such logic would be added) describes a
*different*, real cross-check: "begins the game with <n> sets mulligans = 7-n
authoritatively. Cross-check against any `mulligans to` value; warn on
disagreement" — and that one *is* implemented (parse.py's "mulligan count
mismatch" warning) and *is* the "counted value kept" pattern the Verification
section is almost certainly describing. Tested here as the mulligan
cross-check instead of the (nonexistent) "wins the game" one; see
``test_mulligan_cross_check_disagreement_warns_once_and_keeps_the_authoritative_count``
and the handoff note.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.mtgo.decode import decode_strings
from sensei_top.projector.mtgo.parse import parse_strings
from sensei_top.projector.mtgo.project import _resolve_grp_id, _Warner, project_mtgo

FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_match_session.log"
FIXTURE_BYTES = FIXTURE.read_bytes()
GUID = "f2244feb-54e1-48ec-b3c5-711b20844adf"
HANDLES = {"Player1", "Player2000"}


def _parsed():
    return parse_strings(decode_strings(FIXTURE_BYTES))


# --- decode ------------------------------------------------------------


def test_decodes_the_real_fixture_to_115_strings():
    # decode.py's own module docstring records this as the number it was
    # validated against on this exact fixture; pinned here as a regression
    # test rather than left as a comment only.
    assert len(decode_strings(FIXTURE_BYTES)) == 115


def test_first_two_strings_are_both_the_match_guid():
    strings = decode_strings(FIXTURE_BYTES)
    assert strings[0] == GUID
    assert strings[1] == GUID


def test_empty_input_decodes_to_nothing():
    assert decode_strings(b"") == []


def test_garbage_input_decodes_to_nothing():
    assert decode_strings(b"\xff" * 64) == []


def test_decode_never_raises():
    for cut in range(0, 300, 7):
        decode_strings(FIXTURE_BYTES[:cut])
    decode_strings(FIXTURE_BYTES[::-1])
    decode_strings(bytes(range(256)))


def test_min_len_drops_short_noise_runs():
    default = decode_strings(FIXTURE_BYTES)
    stricter = decode_strings(FIXTURE_BYTES, min_len=200)
    assert len(stricter) < len(default)
    # min_len gates the *declared byte length* of the length-prefix, not the
    # decoded string's character count — a multi-byte UTF-8 character (e.g.
    # 'í' in "Kíli the Resourceful") can make len(s) one less than the byte
    # length that passed the gate, so compare UTF-8-encoded length here.
    assert all(len(s.encode("utf-8")) >= 200 for s in stricter)


# --- the truncated-prefix test: the single most important one ----------
#
# This is the live case: a poll can read a `.dat` file mid-flush, and this is
# the only thing standing between that partial read and a corrupt match row.
# Every cut below is strictly less than the fixture's own 7838 bytes.


@pytest.mark.parametrize("cut", [40, 200, 800, 2000, 4000, 6000, 7000, 7837])
def test_truncated_prefixes_are_monotonically_honest(cut):
    full_strings = decode_strings(FIXTURE_BYTES)
    prefix_strings = decode_strings(FIXTURE_BYTES[:cut])

    # A prefix may lose the tail (an in-flight string straddling the cut is
    # dropped, never fabricated) but must never *gain* content the full
    # decode doesn't also have.
    assert set(prefix_strings) <= set(full_strings)

    parsed = parse_strings(prefix_strings)
    assert parsed.match_id in (None, GUID)
    assert parsed.handles <= HANDLES
    assert len(parsed.games) <= 2
    # 9 is the real fixture's own game-1 turn_count (Arena's units — see
    # test_game_one_facts below): a truncated prefix can only ever see a
    # subset of the full games' Turn lines, never more.
    assert all(g.turn_count <= 9 for g in parsed.games)
    # "Player1 wins the match 2-0" is the very last content in the file —
    # every cut here is short of the full 7838 bytes, so no cut can ever see
    # it in full.
    assert parsed.winner_handle is None


# --- parse (Bug B regressions) ------------------------------------------


def test_two_games_not_four():
    """The Bug B regression: the old per-'Turn 1' boundary logic double
    counted this exact fixture into 4 GameRecords (see parse.py's module
    docstring)."""
    assert len(_parsed().games) == 2


def test_game_one_facts():
    g1 = _parsed().games[0]
    assert g1.on_play_handle == "Player1"
    assert g1.mulligans_by_handle == {"Player1": 0, "Player2000": 0}
    # 9 `Turn N:` lines total (probe lines 30, 34, 39, 46, 51, 57, 63, 73,
    # 83 — printed N 1/1/2/2/3/3/4/4/5, one per player-turn), Arena's units
    # (parse.py's "Turn units") — not 5, the highest *printed* per-player N.
    assert g1.turn_count == 9
    assert g1.winner_handle == "Player1"
    assert g1.conceded_handle == "Player2000"
    assert len(g1.card_events) == 28


def test_game_one_turn_numbers_are_the_ordinal_not_the_printed_n():
    """turn_number is Arena's units (parse.py's "Turn units"): the ordinal
    count of `Turn` lines seen so far in the game, not MTGO's own printed
    per-player N — the two agree on the game's very first Turn line but
    diverge from the second Turn line on, including the second player's own
    "Turn 1"."""
    g1 = _parsed().games[0]
    # "Plains" (probe line 32) is played right after the game's first Turn
    # line (line 30, "Turn 1: Player1") — ordinal 1, same as the old units.
    plains = next(ce for ce in g1.card_events if ce.name == "Plains")
    assert plains.turn_number == 1
    # "Fabled Passage" (probe line 37, PlayLand) is played after the game's
    # *second* Turn line (line 34, "Turn 1: Player2000" — the second
    # player's own first turn). Old (printed-N) units read this event's
    # turn_number as 1; the ordinal is 2, since it's the second Turn line
    # seen in the game.
    fabled_passage = next(
        ce for ce in g1.card_events
        if ce.name == "Fabled Passage" and ce.category == "PlayLand"
    )
    assert fabled_passage.turn_number == 2
    # "Cavern of Souls" (probe line 42) is played after the game's third
    # Turn line (line 39, "Turn 2: Player1"). Old units read turn_number 2
    # (the printed N); the ordinal is 3.
    cavern = next(ce for ce in g1.card_events if ce.name == "Cavern of Souls")
    assert cavern.turn_number == 3


def test_game_two_facts():
    g2 = _parsed().games[1]
    assert g2.on_play_handle == "Player2000"
    assert g2.mulligans_by_handle == {"Player1": 0, "Player2000": 1}
    # 8 `Turn N:` lines total (probe lines 105, 107, 111, 114, 120, 124, 133,
    # 137 — printed N 1/1/2/2/3/3/4/4), not 4, the highest printed N.
    assert g2.turn_count == 8
    assert g2.winner_handle == "Player1"
    assert g2.conceded_handle == "Player2000"
    assert len(g2.card_events) == 17


def test_game_two_turn_number_on_the_second_players_own_turn_one():
    """The one card event required by the brief "on the second player's
    turn" for game 2: "Inspiring Vantage" (probe line 109) is played right
    after the game's *second* Turn line (line 107, "Turn 1: Player1" —
    Player2000 chose to play first, so this is Player1's own first turn).
    Old (printed-N) units would read turn_number 1; the ordinal is 2."""
    g2 = _parsed().games[1]
    inspiring_vantage = next(ce for ce in g2.card_events if ce.name == "Inspiring Vantage")
    assert inspiring_vantage.turn_number == 2


def test_score_line_and_match_winner():
    parsed = _parsed()
    assert parsed.score_line == ("Player1", 2, 0)
    assert parsed.winner_handle == "Player1"
    assert parsed.match_id == GUID
    assert parsed.handles == HANDLES


def test_leads_the_match_updates_score_line_but_not_winner_handle():
    """Isolating game 1's own strings (up to and including its "leads the
    match 1-0" line): that line must feed score_line, the self-check, without
    ever setting winner_handle — only "wins the match" is authoritative."""
    strings = decode_strings(FIXTURE_BYTES)
    leads_index = next(i for i, s in enumerate(strings) if "leads the match" in s)
    parsed = parse_strings(strings[: leads_index + 1])
    assert parsed.score_line == ("Player1", 1, 0)
    assert parsed.winner_handle is None


def test_kili_the_resourceful_is_a_card_event_name():
    """The UTF-8 regression this module exists to fix: the ASCII-only probe
    script splits this name into 'K' and 'li the Resourceful' because 'í' is
    the two-byte UTF-8 sequence \\xc3\\xad. The real decoder must treat it as
    one character, and parse.py must capture the whole thing as one
    CardEvent.name."""
    names = {ce.name for g in _parsed().games for ce in g.card_events}
    assert "Kíli the Resourceful" in names


def test_25_of_26_bracketed_names_become_card_events():
    """See the module docstring's "Correction to parse.py's own module
    docstring" section above: 26 distinct @[...] names exist in the fixture,
    but "Zombie Druid Token" — the target of a triggered ability, never its
    source — is never captured as a CardEvent. 25, not 26, is the real count.
    """
    names = {ce.name for g in _parsed().games for ce in g.card_events}
    assert len(names) == 25
    assert "Zombie Druid Token" not in names


def test_mulligan_cross_check_disagreement_warns_once_and_keeps_the_authoritative_count():
    """The real cross-check this parser implements (see the module docstring
    above for why this replaces the plan's literal "deleted `wins the game`
    line" scenario, which corresponds to no code that exists): "begins the
    game with <n>" is authoritative (mulligans = 7 - n) and disagreement with
    a preceding "mulligans to <n> cards" line must warn exactly once, keeping
    the authoritative (counted) value rather than the running one.

    Built from a minimal synthetic string list (not the real fixture, since
    the real fixture's two mulligan sources always agree) — isolating the
    cross-check itself the same way test_leads_the_match_... isolates
    score_line, per AGENTS.md's fixture-derivation rule: the *grammar* under
    test (the two regexes and the comparison between them) comes straight
    from parse.py's own source, not from guessing at behaviour.
    """
    strings = [
        GUID,
        "Player1 joined the game.",
        "Player2000 joined the game.",
        "Player1 chooses to play first.",
        "Player2000 mulligans to six cards.",
        # Disagreement: 'mulligans to six' implies 1 mulligan, but this
        # authoritative line implies 2 (7 - 5).
        "Player2000 begins the game with five cards in hand.",
        "Player1 begins the game with seven cards in hand.",
    ]
    parsed = parse_strings(strings)
    assert len(parsed.warnings) == 1
    assert "mismatch" in parsed.warnings[0]
    assert parsed.games[0].mulligans_by_handle["Player2000"] == 2


def test_handle_ending_in_a_hyphen_is_one_handle_in_both_begins_shapes():
    """A real MTGO opponent's handle ended in "-", and "<H> begins the game
    with ..." read it as the handle minus the hyphen — a third handle, which
    made the projector skip the whole match. Synthetic like the mulligan test
    above: the line shapes are the real log's (decoded with
    scripts/mtgo_probe.py), only the handles are anonymized, keeping the
    trailing hyphen that triggers the bug. Both begins shapes are covered —
    the after-a-mulligan one ("puts a card on the bottom...") and the plain
    one — since the regex's middle differs between them.
    """
    strings = [
        GUID,
        "Player1 joined the game.",
        "Player2000- joined the game.",
        "Player1 chooses to play first.",
        "Player2000- mulligans to six cards.",
        "Player2000- puts a card on the bottom of their library and begins "
        "the game with six cards in hand.",
        "Player1 begins the game with seven cards in hand.",
        "Turn 1: Player1",
        "Player2000- wins the game.",
        "Player2000- joined the game.",
        "Player1 joined the game.",
        "Player2000- chooses to play first.",
        "Player2000- begins the game with seven cards in hand.",
        "Player1 begins the game with seven cards in hand.",
    ]
    parsed = parse_strings(strings)
    assert parsed.handles == {"Player1", "Player2000-"}
    assert parsed.warnings == []
    assert parsed.games[0].mulligans_by_handle == {"Player1": 0, "Player2000-": 1}
    assert parsed.games[1].mulligans_by_handle == {"Player1": 0, "Player2000-": 0}


def test_bare_turn_one_with_no_start_block_starts_a_new_game_and_warns():
    strings = ["Turn 1: Player1"]
    parsed = parse_strings(strings)
    assert len(parsed.games) == 1
    assert len(parsed.warnings) == 1
    assert "Turn 1" in parsed.warnings[0]


# --- project -------------------------------------------------------------

_SOURCE_FILE = "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat"


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_mtgo_row(conn, *, data: bytes, logged_at: str, source_file: str = _SOURCE_FILE) -> None:
    payload = base64.b64encode(data).decode("ascii")
    digest = hashlib.sha256(f"{source_file}:{logged_at}:{len(data)}".encode()).hexdigest()
    conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, ?, 'event', 'MtgoGameLog', ?, 'mtgo')
        """,
        (digest, source_file, logged_at, payload),
    )


# --- _resolve_grp_id (MTGO card-name resolution) ------------------------


def test_resolve_grp_id_token_resolves_via_base_name_and_token_type_line(conn):
    """The fixture's own token spelling (`uv run python scripts/mtgo_probe.py
    tests/fixtures/mtgo_match_session.log --force --lines 400`): "Zombie
    Druid Token" is the target of Thorin, Mountain-king's second triggered
    ability (see this module's own "Correction to parse.py's own module
    docstring" note above). Arena's real DB row for it is grp_id 95829, name
    'Zombie Druid', type_line 'Token Creature — Zombie Druid'."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line) VALUES "
        "(95829, 'Zombie Druid', 'Token Creature — Zombie Druid')"
    )
    cache: dict[str, int | None] = {}
    warner = _Warner()
    assert _resolve_grp_id(conn, cache, "Zombie Druid Token", warner) == 95829
    assert warner.count == 0


def test_resolve_grp_id_token_rule_requires_a_token_type_line(conn):
    """A non-token 'Zombie Druid' row must not win the token lookup — the
    guard the function's own docstring explains: a token's base name can
    coincide with an unrelated non-token card's own name, and the real card
    must not win a lookup that was never about it."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line) VALUES "
        "(1, 'Zombie Druid', 'Creature — Zombie Druid')"
    )
    cache: dict[str, int | None] = {}
    warner = _Warner()
    assert _resolve_grp_id(conn, cache, "Zombie Druid Token", warner) is None
    assert warner.count == 1


def test_resolve_grp_id_exact_match_wins_over_front_face(conn):
    """Real DB rows: 'Mosswood Dreadknight' is grp_id 87547, 'Mosswood
    Dreadknight // Dread Whispers' is grp_id 86952. "Mosswood Dreadknight" is
    also one of the fixture's own card events (probe line 50, "Player2000
    casts @[Mosswood Dreadknight@:233656,444:@]."). The exact rule must win
    outright rather than falling through to the front-face rule that would
    also match it."""
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (87547, 'Mosswood Dreadknight')")
    conn.execute(
        "INSERT INTO cards (grp_id, name) VALUES "
        "(86952, 'Mosswood Dreadknight // Dread Whispers')"
    )
    cache: dict[str, int | None] = {}
    warner = _Warner()
    assert _resolve_grp_id(conn, cache, "Mosswood Dreadknight", warner) == 87547
    assert warner.count == 0


def test_resolve_grp_id_front_face_resolves_the_combined_name(conn):
    """'Delver of Secrets' is a front-face spelling observed in real MTGO
    logs, not in this project's fixture; Arena's DB only carries the combined
    name. The grp_id seeded here is a test-only placeholder, not the real
    printed card's own id."""
    conn.execute(
        "INSERT INTO cards (grp_id, name) VALUES "
        "(555555, 'Delver of Secrets // Insectile Aberration')"
    )
    cache: dict[str, int | None] = {}
    warner = _Warner()
    assert _resolve_grp_id(conn, cache, "Delver of Secrets", warner) == 555555
    assert warner.count == 0


def test_resolve_grp_id_ambiguous_front_face_is_none_not_a_guess(conn, caplog):
    """Synthetic (not from the fixture or any real card): two combined names
    sharing the same front face. Rule 4 — ambiguity is not resolved by
    guessing which one, and the warning names both candidates."""
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (1, 'Test Card // A')")
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (2, 'Test Card // B')")
    cache: dict[str, int | None] = {}
    warner = _Warner()
    with caplog.at_level(logging.WARNING):
        assert _resolve_grp_id(conn, cache, "Test Card", warner) is None
    assert warner.count == 1
    [message] = [r.message for r in caplog.records if "Test Card" in r.message]
    assert message == (
        "[mtgo] MTGO card name not found in cards.name: 'Test Card' "
        "(front face of 2 cards: 'Test Card // A', 'Test Card // B')"
    )


def test_resolve_grp_id_prefix_must_be_exact_not_a_substring(conn):
    """'Delverish // X' must not match a lookup for "Delver" — the prefix
    check is `substr(name, 1, length(?)+4) = ? || ' // '`, not LIKE, so
    'Delverish ' (the real next 4 characters) never equals 'Delver // '."""
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (1, 'Delverish // X')")
    cache: dict[str, int | None] = {}
    warner = _Warner()
    assert _resolve_grp_id(conn, cache, "Delver", warner) is None
    assert warner.count == 1


def test_resolve_grp_id_cache_hit_issues_no_query(conn):
    """The cache stores the final answer — None included — so a second call
    for a name already resolved (or already known unresolved) costs no
    query, only a dict lookup."""
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (87547, 'Mosswood Dreadknight')")
    cache: dict[str, int | None] = {}
    warner = _Warner()
    assert _resolve_grp_id(conn, cache, "Mosswood Dreadknight", warner) == 87547

    queries: list[str] = []
    conn.set_trace_callback(queries.append)
    try:
        assert _resolve_grp_id(conn, cache, "Mosswood Dreadknight", warner) == 87547
    finally:
        conn.set_trace_callback(None)
    assert queries == []


def test_full_fixture_projects_one_match_two_games_45_card_events(conn):
    _insert_mtgo_row(conn, data=FIXTURE_BYTES, logged_at="2026-09-14T12:42:37")
    result = project_mtgo(conn, "Player1")
    assert result["matches"] == 1
    assert result["games"] == 2
    assert result["card_events"] == 45

    row = conn.execute("SELECT * FROM matches WHERE match_id = ?", (GUID,)).fetchone()
    assert row["source"] == "mtgo"
    assert row["result"] == "win"
    assert row["games_won"] == 2
    assert row["games_lost"] == 0
    assert row["started_at"] == "2026-09-14T12:42:37"
    assert row["ended_at"] == "2026-09-14T12:42:37"


def test_started_at_is_the_first_rows_logged_at_ended_at_the_last(conn):
    """Three progressive prefixes as three rows, mirroring the live-flush
    shape end to end: the longest payload wins the content, but started_at
    still comes from the earliest row and ended_at from the latest — not from
    whichever row happened to carry the longest payload."""
    _insert_mtgo_row(conn, data=FIXTURE_BYTES[:2000], logged_at="2026-09-14T12:42:00")
    _insert_mtgo_row(conn, data=FIXTURE_BYTES[:6000], logged_at="2026-09-14T12:42:22")
    _insert_mtgo_row(conn, data=FIXTURE_BYTES, logged_at="2026-09-14T12:42:44")

    result = project_mtgo(conn, "Player1")
    assert result["matches"] == 1

    row = conn.execute("SELECT * FROM matches WHERE match_id = ?", (GUID,)).fetchone()
    assert row["started_at"] == "2026-09-14T12:42:00"
    assert row["ended_at"] == "2026-09-14T12:42:44"


def test_prefix_cut_mid_mulligan_is_incomplete_with_no_ended_at(conn):
    """A cut landing right after both "joined the game" lines but before
    either "chooses to play first" or any "begins the game with <n>" line —
    the earliest possible in-progress read, a match still choosing mulligans
    with nothing else decided yet. game 1 exists (the "joined the game"
    start-block signal opened it) but has_action() is still False, so
    on_play/turn_count/self_mulligans are all still at the GameRecord's own
    defaults (None/0/absent), and the match has no "wins the match" line —
    incomplete, honestly, per project.py's own "never discarded, even with
    zero games" rule.

    Byte offset 222 was located by bisecting real cuts of the fixture with
    decode_strings (a mechanical search for the byte boundary between two
    already-confirmed real lines — see the probe transcript's line order in
    this module's docstring — not by running parse_strings/project_mtgo and
    copying their semantic output): it is the smallest cut whose decode
    contains both "joined the game" strings but not yet "chooses to play
    first". Independently confirmed here to decode to exactly the GUID x2 +
    two "rolled a" lines + two "joined the game" lines (6 strings, 0 warnings,
    1 empty GameRecord) before being handed to project_mtgo.
    """
    cut = 222
    strings = decode_strings(FIXTURE_BYTES[:cut])
    assert len(strings) == 6
    parsed = parse_strings(strings)
    assert len(parsed.games) == 1
    g = parsed.games[0]
    assert g.on_play_handle is None
    assert g.mulligans_by_handle == {}
    assert g.turn_count == 0
    assert parsed.winner_handle is None
    assert parsed.warnings == []

    _insert_mtgo_row(conn, data=FIXTURE_BYTES[:cut], logged_at="2026-09-14T12:42:00")
    result = project_mtgo(conn, "Player1")
    assert result["matches"] == 1
    assert result["games"] == 1

    row = conn.execute("SELECT * FROM matches WHERE match_id = ?", (GUID,)).fetchone()
    assert row["result"] == "incomplete"
    assert row["ended_at"] is None

    game = conn.execute(
        "SELECT * FROM games WHERE match_id = ? AND game_number = 1", (GUID,)
    ).fetchone()
    assert game["on_play"] is None
    assert game["turn_count"] is None
    assert game["self_mulligans"] is None


def test_no_handle_configured_projects_nothing_but_warns_once(conn):
    _insert_mtgo_row(conn, data=FIXTURE_BYTES, logged_at="2026-09-14T12:42:37")
    result = project_mtgo(conn, None)
    assert result["matches"] == 0
    assert result["warnings"] == 1
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


def test_v_current_match_never_shows_mtgo_however_new(tmp_path):
    """Migration 040 (migrations/040_arena_only_current_match.sql) makes
    v_current_match Arena-only: an MTGO match never becomes the current
    match, no matter how recently it started relative to Arena's own rows.
    Inverted from this test's pre-040 self (then named
    test_v_current_match_prefers_mtgo_when_newest, which asserted the
    opposite) — same setup, opposite expectation.

    Built directly via SQL rather than through a full Arena ingest+project():
    only matches.match_id/started_at/result are required columns
    (migrations/001_init.sql), so a minimal synthetic Arena row is enough to
    exercise v_current_match's ordering."""
    conn = open_database(tmp_path / "t.db")
    try:
        # An older, already-finished Arena match — excluded by
        # result='incomplete' regardless of source.
        conn.execute(
            "INSERT INTO matches (match_id, started_at, result, source) "
            "VALUES ('arena-old', '2026-09-14T10:00:00', 'win', 'arena')"
        )
        # The MTGO match: incomplete, newest by started_at — the exact
        # condition that used to win before migration 040.
        _insert_mtgo_row(conn, data=FIXTURE_BYTES[:2000], logged_at="2026-09-14T12:42:00")
        project_mtgo(conn, "Player1")

        # No Arena match is currently incomplete, and MTGO can never show
        # here, so the view is empty rather than surfacing the MTGO match.
        current = conn.execute("SELECT match_id, source FROM v_current_match").fetchone()
        assert current is None
    finally:
        conn.close()


def test_v_current_match_prefers_a_newer_arena_match_over_mtgo(tmp_path):
    conn = open_database(tmp_path / "t.db")
    try:
        # The MTGO match: incomplete, first-seen earlier.
        _insert_mtgo_row(conn, data=FIXTURE_BYTES[:2000], logged_at="2026-09-14T12:42:00")
        project_mtgo(conn, "Player1")
        # A newer incomplete Arena match starts after the MTGO one was first seen.
        conn.execute(
            "INSERT INTO matches (match_id, started_at, result, source) "
            "VALUES ('arena-new', '2026-09-14T13:00:00', 'incomplete', 'arena')"
        )

        current = conn.execute("SELECT match_id, source FROM v_current_match").fetchone()
        assert current is not None
        assert current["source"] == "arena"
        assert current["match_id"] == "arena-new"
    finally:
        conn.close()


def test_an_in_progress_arena_match_survives_a_newer_mtgo_match(tmp_path):
    """The bug migration 040 actually fixes: before it filtered the inner
    MAX subquery to source='arena' too (not just the outer WHERE), an MTGO
    match holding the global-maximum started_at would blank the tab even
    though a genuinely in-progress Arena match still existed — the Arena
    row's own started_at could never tie a MAX that belonged to MTGO. Real,
    not hypothetical: the production database held 315 MTGO matches, 23 of
    them incomplete, any one of which could have outdated an Arena match's
    started_at this way."""
    conn = open_database(tmp_path / "t.db")
    try:
        # An in-progress Arena match, started earlier.
        conn.execute(
            "INSERT INTO matches (match_id, started_at, result, source) "
            "VALUES ('arena-live', '2026-09-14T10:00:00', 'incomplete', 'arena')"
        )
        # An MTGO match first observed later — alone would hold the global
        # MAX(started_at) if the subquery weren't source-filtered too.
        _insert_mtgo_row(conn, data=FIXTURE_BYTES[:2000], logged_at="2026-09-14T12:42:00")
        project_mtgo(conn, "Player1")

        current = conn.execute("SELECT match_id, source FROM v_current_match").fetchone()
        assert current is not None
        assert current["source"] == "arena"
        assert current["match_id"] == "arena-live"
    finally:
        conn.close()
