"""Segmentation tests. Every rule is backed by the anonymized real-log fixture
(tests/fixtures/sample_player.log, captured from client 2026.62.10 on Linux/Proton)
or by minimal synthetic lines for edge cases the fixture can't easily show.
"""

import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sensei_top.reader import segmenter
from sensei_top.reader.segmenter import (
    UNITY_PREFIX,
    EntryKind,
    HeaderStamp,
    JsonAccumulator,
    Segmenter,
    fixed_resolver,
    parse_header_timestamp,
    segment_lines,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_player.log"


@pytest.fixture(autouse=True)
def _unwarned(monkeypatch):
    """The header warnings fire once per process; every test starts unwarned."""
    monkeypatch.setattr(segmenter, "_warned_patterns", set())
    monkeypatch.setattr(segmenter, "_warned_impossible", set())
    monkeypatch.setattr(segmenter, "_warned_summaries", set())


def fixture_lines() -> list[str]:
    return FIXTURE.read_text(encoding="utf-8").splitlines()


def fixture_entries(locale_hint: str | None = "mdy"):
    return segment_lines(fixture_lines(), locale_hint=locale_hint)


# --- whole-fixture behaviour ------------------------------------------------


def test_every_extracted_payload_is_valid_json():
    entries = fixture_entries()
    assert entries, "fixture produced no entries"
    for e in entries:
        json.loads(e.payload)  # raises on corruption -> segmentation bug


def test_noise_prefixes_produce_no_entries():
    noise = [line for line in fixture_lines() if line.startswith(("[PhysX]", "[TaskLogger]"))]
    assert noise, "fixture must contain noise lines"
    assert not segment_lines(noise)


def test_request_entry_extracted_with_method_label():
    reqs = [e for e in fixture_entries() if e.kind == EntryKind.REQUEST]
    assert any(e.label == "GraphGetGraphState" for e in reqs)
    # request payloads carry escaped nested JSON: outer parse must still work
    payload = json.loads(next(e.payload for e in reqs if e.label == "GraphGetGraphState"))
    inner = json.loads(payload["request"])  # second deserialization pass
    assert "GraphId" in inner


def test_response_payload_on_following_line():
    resps = [e for e in fixture_entries() if e.kind == EntryKind.RESPONSE]
    assert any(e.label == "GraphGetGraphState" for e in resps)
    body = json.loads(next(e.payload for e in resps if e.label == "GraphGetGraphState"))
    assert "NodeStates" in body


def test_match_lifecycle_events_extracted():
    events = [e for e in fixture_entries() if e.kind == EntryKind.EVENT]
    payloads = [json.loads(e.payload) for e in events]
    states = [
        p["matchGameRoomStateChangedEvent"]["gameRoomInfo"]["stateType"]
        for p in payloads
        if "matchGameRoomStateChangedEvent" in p
    ]
    assert "MatchGameRoomStateType_Playing" in states
    assert "MatchGameRoomStateType_MatchCompleted" in states


def test_multiline_payload_reassembled():
    events = [e for e in fixture_entries() if e.kind == EntryKind.EVENT]
    multi = [e for e in events if "\n" in e.payload]
    assert multi, "fixture must contain a multi-line payload"
    body = json.loads(multi[0].payload)
    assert body["clientToMatchServiceMessageType"].startswith("ClientToMatchServiceMessageType")


def test_event_label_comes_from_header_context():
    events = [e for e in fixture_entries() if e.kind == EntryKind.EVENT]
    assert any(e.label == "GreToClientEvent" for e in events)


# --- labeled inline events (human-draft fixture) ----------------------------
#
# "[UnityCrossThreadLogger]Draft.Notify {...}" carries its label on the same
# line as its payload: no "==>" arrow, no header context. Discarding these lines
# would leave a human (Premier/Traditional/Cube) draft with no events.
# Expectations below are read off the
# fixture, never off the parser (AGENTS.md non-negotiable #8).

HUMAN_DRAFT_FIXTURE = Path(__file__).parent / "fixtures" / "human_draft_session.log"


def human_draft_entries(locale_hint: str | None = "mdy"):
    lines = HUMAN_DRAFT_FIXTURE.read_text(encoding="utf-8").splitlines()
    return segment_lines(lines, locale_hint=locale_hint)


def test_labeled_inline_event_is_extracted_with_its_own_label():
    events = [e for e in human_draft_entries() if e.kind == EntryKind.EVENT]
    notifies = [e for e in events if e.label == "Draft.Notify"]
    assert len(notifies) == 22, "fixture holds pack one entire, then seven of pack two"
    for e in notifies:
        json.loads(e.payload)  # payload survives intact, not truncated


def test_labeled_inline_event_payload_carries_the_pack():
    # A pack shrinks by exactly one card per pick: pack one runs 15 down to 1,
    # pack two is captured through its seventh pick (15 down to 9). Every
    # notify names the same draft. Read from the fixture, not from the code.
    packs = [
        json.loads(e.payload)
        for e in human_draft_entries()
        if e.label == "Draft.Notify"
    ]
    assert [(p["SelfPack"], p["SelfPick"]) for p in packs] == [
        (1, pick) for pick in range(1, 16)
    ] + [(2, pick) for pick in range(1, 8)]
    # 1-indexed in the log: the opening pack is (1, 1), never (0, 0)
    assert packs[0]["SelfPack"] == 1 and packs[0]["SelfPick"] == 1
    assert [len(p["PackCards"].split(",")) for p in packs] == (
        list(range(15, 0, -1)) + list(range(15, 8, -1))
    )
    assert len({p["draftId"] for p in packs}) == 1


def test_labeled_inline_event_gets_the_preceding_header_timestamp():
    first = next(e for e in human_draft_entries() if e.label == "Draft.Notify")
    assert first.logged_at == "2026-09-08T20:01:17"


def test_scene_change_is_labeled_too():
    events = [e for e in human_draft_entries() if e.kind == EntryKind.EVENT]
    assert any(e.label == "Client.SceneChange" for e in events)


def test_header_timestamp_line_is_never_read_as_a_labeled_event():
    # A header starts with a digit, so it must set the timestamp and emit
    # nothing -- otherwise it would shadow the labeled-event rule.
    entries = segment_lines(["[UnityCrossThreadLogger]9/8/2026 8:01:17 PM"], "mdy")
    assert entries == []


def test_prefixed_line_without_payload_still_emits_nothing():
    entries = segment_lines(["[UnityCrossThreadLogger]STATE CHANGED Foo -> Bar"], "mdy")
    assert entries == []


def test_header_timestamp_attached_when_hint_given():
    entries = fixture_entries(locale_hint="mdy")
    assert any(e.logged_at is not None for e in entries)


def test_no_timestamp_without_locale_hint():
    entries = fixture_entries(locale_hint=None)
    assert all(e.logged_at is None for e in entries)  # never guessed


# --- JsonAccumulator edge cases (synthetic) ---------------------------------


def test_braces_inside_string_literals_ignored():
    acc = JsonAccumulator()
    acc.feed('{"text": "a { b } c {{"}')
    assert acc.complete
    assert json.loads(acc.text)["text"] == "a { b } c {{"


def test_escaped_quote_does_not_end_string():
    acc = JsonAccumulator()
    acc.feed('{"text": "say \\"hi\\" {not a brace}"}')
    assert acc.complete


def test_escaped_nested_json_with_braces():
    # the ==> request shape: JSON string containing escaped JSON
    acc = JsonAccumulator()
    acc.feed('{"id":"x","request":"{\\"GraphId\\":\\"NPE_Tutorial\\"}"}')
    assert acc.complete
    inner = json.loads(json.loads(acc.text)["request"])
    assert inner == {"GraphId": "NPE_Tutorial"}


def test_multiline_split_mid_string():
    acc = JsonAccumulator()
    acc.feed('{"a": "line one')
    assert not acc.complete
    acc.feed('still the same string", "b": 2}')
    assert acc.complete


def test_truncated_payload_never_emitted():
    seg = Segmenter()
    out = seg.feed_line('{ "unfinished": {')
    assert out == []
    seg.flush()  # simulates truncation
    out = seg.feed_line('{"fresh": 1}')
    assert len(out) == 1
    assert json.loads(out[0].payload) == {"fresh": 1}


# --- non-JSON response body (entry shape 5) ---------------------------------
#
# Real shape (module docstring, shape 5): DeckDeleteDeck replies "Success" on
# its own line, not JSON. Modeled on the real log; the UUIDs here are made up.


def test_non_json_response_body_is_captured_verbatim():
    lines = [
        "[UnityCrossThreadLogger]9/23/2026 5:30:38 PM",
        "<== DeckDeleteDeck(00000000-0000-0000-0000-000000000001)",
        "Success",
        '[UnityCrossThreadLogger]==> DeckUpsertDeckV3 {"id":"x","request":"{}"}',
    ]
    entries = segment_lines(lines, locale_hint="mdy")
    assert len(entries) == 2
    resp, req = entries
    assert resp.kind == EntryKind.RESPONSE
    assert resp.label == "DeckDeleteDeck"
    assert resp.payload == "Success"
    assert resp.logged_at == "2026-09-23T17:30:38"
    assert req.kind == EntryKind.REQUEST
    assert req.label == "DeckUpsertDeckV3"


def test_non_json_response_body_does_not_swallow_following_lines():
    # The bug this replaced: the JSON accumulator never saw a "{", so
    # "Continuation takes priority over everything" kept it swallowing every
    # following line -- requests included -- until some line's braces
    # happened to balance by accident.
    lines = [
        "<== DeckDeleteDeck(00000000-0000-0000-0000-000000000001)",
        "Success",
        "Can't find pet for deck Some Deck (00000000-0000-0000-0000-000000000002)",
    ]
    entries = segment_lines(lines)
    assert len(entries) == 1  # the noise line after "Success" produces nothing,
    assert entries[0].payload == "Success"  # but it is never fed to the response


# --- a summarized message is warned ------------------------------------------


def _summarized_block_lines() -> list[str]:
    return [
        "[UnityCrossThreadLogger]10/6/2026 2:37:04 PM: Match to X: GreToClientEvent",
        "[Message summarized because one or more GameStateMessages exceeded the "
        "50 GameObject or 50 Annotation limit.]",
        "::: GameStateMessage",
        ":: GameObject Count = 61",
        ":: Annotation Count = 12",
        ":: something not a count",
        '{"after": 1}',
    ]


def test_summarized_block_warns_once_and_stores_nothing(caplog):
    """SYNTHETIC: no real capture of this block exists. The shape is the one
    manasight #200/#257 and mtgatool's arena-log-decoder document."""
    lines = _summarized_block_lines()
    with caplog.at_level(logging.WARNING):
        entries = segment_lines(lines, locale_hint="mdy")
    plain = segment_lines([lines[0], lines[-1]], locale_hint="mdy")
    assert len(entries) == 1
    assert [replace(e, line_number=0) for e in entries] == [
        replace(e, line_number=0) for e in plain
    ]
    assert entries[0].label == "GreToClientEvent"
    assert entries[0].logged_at == "2026-10-06T14:37:04"
    warnings = [r.getMessage() for r in caplog.records if "summarized" in r.getMessage()]
    assert len(warnings) == 1
    assert "GameObject Count = 61" in warnings[0]
    assert "Annotation Count = 12" in warnings[0]
    assert "something not a count" not in warnings[0]
    assert "+1 other line" in warnings[0]


def test_summarized_block_is_pending_until_a_line_ends_it(caplog):
    """SYNTHETIC. An open block holds the poll's offset (ingest keys on
    ``pending``), so a poll that ends inside it re-reads it whole."""
    lines = _summarized_block_lines()
    seg = Segmenter(locale_hint="mdy")
    seg.feed_line(lines[0])
    assert not seg.pending
    with caplog.at_level(logging.WARNING):
        for ln in lines[1:6]:
            seg.feed_line(ln)
            assert seg.pending
        assert not [r for r in caplog.records if "summarized" in r.getMessage()]
        seg.feed_line(lines[6])
    assert not seg.pending
    assert sum("summarized" in r.getMessage() for r in caplog.records) == 1


def test_summarized_block_flush_warns(caplog):
    """SYNTHETIC: no real capture. ``segment_lines`` ends with ``flush()``, so
    input that ends inside a block still warns."""
    seg = Segmenter()
    for ln in _summarized_block_lines()[1:4]:
        seg.feed_line(ln)
    with caplog.at_level(logging.WARNING):
        seg.flush()
    assert sum("summarized" in r.getMessage() for r in caplog.records) == 1
    assert not seg.pending


def test_summarized_block_met_by_a_second_segmenter_warns_once(caplog):
    """SYNTHETIC. The startup recovery reads Player-prev.log's content and can
    meet the same block again inside Player.log: a second Segmenter, same
    lines, same header."""
    with caplog.at_level(logging.WARNING):
        segment_lines(_summarized_block_lines(), locale_hint="mdy")
        segment_lines(_summarized_block_lines(), locale_hint="mdy")
    assert sum("summarized" in r.getMessage() for r in caplog.records) == 1


def test_summarized_block_reclosed_after_the_offset_held_at_its_marker(caplog):
    """SYNTHETIC. The line that closes a block opens an entry still open when
    the poll ends, so the offset holds at the marker. The next poll's
    Segmenter starts at the marker with the carry from before it, and closes
    the same block at a different line position: one warning in all."""
    lines = _summarized_block_lines()
    opener = '{"open":'
    first = Segmenter(locale_hint="mdy")
    first.feed_line("noise")               # shifts the first poll's line numbers
    first.feed_line(lines[0])
    carry = first.carry_state()            # what ingest commits before the marker
    with caplog.at_level(logging.WARNING):
        for ln in [*lines[1:6], opener]:
            first.feed_line(ln)
        assert first.pending
        second = Segmenter(locale_hint="mdy")
        second.restore_carry(*carry)
        for ln in [*lines[1:6], opener]:
            second.feed_line(ln)
    assert sum("summarized" in r.getMessage() for r in caplog.records) == 1


# --- flush() reports what it dropped -----------------------------------------


def test_flush_returns_the_dropped_entrys_start_line():
    seg = Segmenter()
    seg.feed_line("noise")            # line 1, produces nothing
    seg.feed_line("more noise")       # line 2
    seg.feed_line('{"unfinished":')   # line 3, opens the pending accumulator
    assert seg.flush() == 3


def test_flush_returns_the_dropped_responses_start_line():
    # A response's payload is expected on the line *after* "<==", so the
    # pending entry's start line is one past the header even though nothing
    # has been fed to it yet.
    seg = Segmenter()
    seg.feed_line("noise")  # line 1
    seg.feed_line("<== SomeMethod(00000000-0000-0000-0000-000000000000)")  # line 2
    assert seg.pending
    assert seg.flush() == 3


def test_flush_returns_none_when_nothing_pending():
    seg = Segmenter()
    seg.feed_line('{"complete": 1}')
    assert seg.flush() is None


def test_segment_lines_warns_on_a_dropped_pending(caplog):
    with caplog.at_level(logging.WARNING):
        entries = segment_lines(["noise", '{"unfinished":'])
    assert entries == []
    assert any(
        "dropped an incomplete pending entry starting at line 2" in r.message
        for r in caplog.records
    )


# --- timestamp parsing ------------------------------------------------------
#
# A stamp below that is one of the capture table's examples
# (docs/arena-log.md, "Timestamps") is a real header from
# header_languages.log; the rest are synthetic, built in the captured shapes.


def _time_under(stamp: str, hint: str | None) -> str | None:
    """logged_at of a one-line event under a header with this stamp."""
    (entry,) = segment_lines([UNITY_PREFIX + stamp, '{"a": 1}'], hint)
    return entry.logged_at


def _shape_of(stamp: str) -> str:
    header = parse_header_timestamp(stamp)
    assert header is not None and header.parsed is not None
    return header.parsed.shape


@pytest.mark.parametrize(
    ("text", "hint", "expected"),
    [
        ("8/13/2026 2:40:28 PM", "mdy", "2026-08-13T14:40:28"),
        ("13/8/2026 2:40:28 PM", "dmy", "2026-08-13T14:40:28"),
        ("8/13/2026 12:05:00 AM", "mdy", "2026-08-13T00:05:00"),
        ("8/13/2026 12:05:00 PM", "mdy", "2026-08-13T12:05:00"),
        ("25/9/2026 17:30:00", "dmy", "2026-09-25T17:30:00"),
        ("9/25/2026 17:30:00", "mdy", "2026-09-25T17:30:00"),
        # half past noon, no designator; before the fix this came out 00:30
        ("9/25/2026 12:30:00", "mdy", "2026-09-25T12:30:00"),
        ("9/25/2026 00:30:00", "mdy", "2026-09-25T00:30:00"),
        ("9/25/2026 24:00:00", "mdy", None),
        ("9/25/2026 13:00:00 PM", "mdy", None),
        ("9/25/2026 0:30:00 AM", "mdy", None),
    ],
)
def test_timestamp_parsing(text, hint, expected):
    assert _time_under(text, hint) == expected


def test_ambiguous_date_without_hint_is_none():
    assert _time_under("3/7/2026 1:00:00 PM", None) is None


def test_impossible_date_for_hint_is_none_and_warns_once_per_shape(caplog):
    # 13/8 read as month=13 under mdy: refuse rather than guess
    lines = [
        UNITY_PREFIX + "13/8/2026 1:00:00 PM", '{"a": 1}',
        UNITY_PREFIX + "14/8/2026 1:00:00 PM", '{"b": 2}',   # same shape: no second warning
        UNITY_PREFIX + "13.8.2026 13:00:00", '{"c": 3}',     # another shape warns on its own
    ]
    with caplog.at_level(logging.WARNING, logger=segmenter.__name__):
        entries = segment_lines(lines, "mdy")
    assert [e.logged_at for e in entries] == [None, None, None]
    assert [r.getMessage() for r in caplog.records] == [
        "header '13/8/2026 1:00:00 PM' is not a date when read mdy; "
        "its entries are stored with no time",
        "header '13.8.2026 13:00:00' is not a date when read mdy; "
        "its entries are stored with no time",
    ]


def test_header_context_extracted():
    header = parse_header_timestamp(
        "8/13/2026 2:49:19 PM: Match to SELFCLIENTID0001: GreToClientEvent"
    )
    assert header is not None and header.parsed is not None
    assert header.stamp == "8/13/2026 2:49:19 PM"
    assert header.context == "Match to SELFCLIENTID0001: GreToClientEvent"
    assert fixed_resolver("mdy")(header.parsed) == "2026-08-13T14:49:19"


def test_header_context_extracted_24_hour():
    header = parse_header_timestamp(
        "25/9/2026 17:30:05: Match to SELFCLIENTID0001: GreToClientEvent"
    )
    assert header is not None and header.parsed is not None
    assert header.stamp == "25/9/2026 17:30:05"
    assert header.context == "Match to SELFCLIENTID0001: GreToClientEvent"
    assert fixed_resolver("dmy")(header.parsed) == "2026-09-25T17:30:05"


def test_refused_time_keeps_context():
    header = parse_header_timestamp(
        "9/25/2026 13:00:00 PM: Match to SELFCLIENTID0001: GreToClientEvent"
    )
    assert header is not None
    assert header.parsed is None
    assert header.context == "Match to SELFCLIENTID0001: GreToClientEvent"


@pytest.mark.parametrize(
    "body",
    [
        "STATE CHANGED {}",
        "Startup Timestamp: 10/6/2026 2:42:20 PM",   # letter-led, whatever follows
        "1 thing without a time: 10/6/2026",          # no H:MM:SS before the first ": "
        "",
    ],
)
def test_a_body_that_is_no_header_returns_none(body):
    assert parse_header_timestamp(body) is None


@pytest.mark.parametrize(
    ("stamp", "shape", "fields"),
    [
        ("10/6/2026 2:37:04 PM", "slash-12h", (2026, 10, 6, 14, 37, 4)),
        ("06/10/2026 14:39:17", "slash-24h", (2026, 6, 10, 14, 39, 17)),
        ("06.10.2026 14:39:58", "dot-24h", (2026, 6, 10, 14, 39, 58)),
        ("2026/10/06 14:37:42", "ymd-slash-24h", (2026, 10, 6, 14, 37, 42)),
        ("2026-10-06 오후 2:38:24", "ymd-dash-ko", (2026, 10, 6, 14, 38, 24)),
    ],
)
def test_each_captured_shape_parses_to_its_key_and_fields(stamp, shape, fields):
    header = parse_header_timestamp(stamp)
    assert header is not None and header.parsed is not None
    parsed = header.parsed
    assert parsed.text == stamp
    assert parsed.shape == shape
    assert (parsed.year, parsed.a, parsed.b, parsed.hour, parsed.minute, parsed.second) == fields


def test_a_year_first_stamp_reads_as_written_in_any_order():
    parsed = parse_header_timestamp("2026/10/06 14:37:42").parsed
    assert parsed is not None and parsed.year_first
    expected = datetime(2026, 10, 6, 14, 37, 42)
    assert [parsed.reading(order) for order in (None, "mdy", "dmy")] == [expected] * 3


def test_a_day_month_stamp_reads_only_in_an_order():
    parsed = parse_header_timestamp("06.10.2026 14:39:58").parsed
    assert parsed is not None and not parsed.year_first
    assert parsed.reading(None) is None
    assert parsed.reading("dmy") == datetime(2026, 10, 6, 14, 39, 58)
    assert parsed.reading("mdy") == datetime(2026, 6, 10, 14, 39, 58)
    day_13 = parse_header_timestamp("13.10.2026 14:39:58").parsed
    assert day_13 is not None and day_13.reading("mdy") is None


def test_a_stamp_that_is_no_date_in_either_order_is_in_no_shape():
    header = parse_header_timestamp("13/13/2026 14:00:00")
    assert header is not None and header.parsed is None


@pytest.mark.parametrize("hint", ["mdy", "dmy", None])
@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("2026-10-06 오후 2:38:24", "2026-10-06T14:38:24"),   # captured
        # 오전 (AM) is in no capture: accepted by symmetry with 오후
        ("2026-10-06 오전 9:38:24", "2026-10-06T09:38:24"),
        ("2026-10-06 오전 12:05:00", "2026-10-06T00:05:00"),
        ("2026-10-06 오후 12:05:00", "2026-10-06T12:05:00"),
        ("2026-10-06 오후 13:00:00", None),
        ("2026-10-06 오전 0:30:00", None),
    ],
)
def test_korean_designators(stamp, expected, hint):
    assert _time_under(stamp, hint) == expected


def test_a_year_first_header_replaces_the_previous_headers_time():
    lines = [
        UNITY_PREFIX + "10/6/2026 2:37:04 PM",
        "<== EventGetActiveMatches(00000000-0000-0000-0000-000000000001)",
        '{"MatchesV3":[]}',
        UNITY_PREFIX + "2026/10/06 14:37:42",
        "<== DeckUpsertDeckV3(00000000-0000-0000-0000-000000000002)",
        '{"DeckId":"x"}',
    ]
    english, japanese = segment_lines(lines, "mdy")
    assert english.logged_at == "2026-10-06T14:37:04"
    assert japanese.logged_at == "2026-10-06T14:37:42"
    assert japanese.header == "2026/10/06 14:37:42"


def test_an_impossible_date_never_keeps_the_previous_headers_time():
    # A day-first log read as mdy: the second header's day is above 12. Its
    # entries must not keep the first header's time.
    lines = [
        UNITY_PREFIX + "06/10/2026 23:59:58",
        '{"a": 1}',
        UNITY_PREFIX + "13/10/2026 00:00:05",
        '{"b": 2}',
    ]
    first, second = segment_lines(lines, "mdy")
    assert first.logged_at == "2026-06-10T23:59:58"
    assert second.logged_at is None
    assert second.header == "13/10/2026 00:00:05"


@pytest.mark.parametrize(
    ("stamp", "again"),
    [
        ("2026-10-06 14:39:58", "2026-10-06 14:40:12"),
        ("6/10/2026 2:39:58 pm", "6/10/2026 2:40:12 pm"),
    ],
)
@pytest.mark.parametrize("hint", ["mdy", "dmy"])
def test_an_uncaptured_shape_is_a_header_with_no_time_that_warns_once(
    stamp, again, hint, caplog
):
    context = ": SELFCLIENTID0001 to Match: ClientToGreuimessage"
    lines = [
        UNITY_PREFIX + "2026/10/06 14:39:40" + context, '{"a": 1}',
        UNITY_PREFIX + stamp + context, '{"b": 2}',
        UNITY_PREFIX + again + context, '{"c": 3}',   # same pattern, digits as 9
    ]
    with caplog.at_level(logging.WARNING, logger=segmenter.__name__):
        good, unknown, repeat = segment_lines(lines, hint)
    assert good.logged_at == "2026-10-06T14:39:40"
    assert (unknown.logged_at, unknown.label, unknown.header) == (
        None, "ClientToGreuimessage", stamp
    )
    assert (repeat.logged_at, repeat.header) == (None, again)
    assert [r.getMessage() for r in caplog.records] == [
        f"header {stamp!r} is not a date and time in any shape a capture has shown; "
        "its entries are stored with no time"
    ]


@pytest.mark.parametrize(
    "line",
    [
        # Modeled on the relaunch capture; the times are made up.
        UNITY_PREFIX + "Startup Timestamp: 10/6/2026 2:42:20 PM",
        "Startup Timestamp: 10/6/2026 2:42:20 PM",
        "10/6/2026 2:37:07 PM LoadWrapperScene",
    ],
)
def test_startup_timestamp_and_unprefixed_stamps_are_not_headers(line):
    seg = Segmenter(locale_hint="dmy")
    seg.feed_line(UNITY_PREFIX + "06/10/2026 14:42:30")
    seg.feed_line(line)
    (entry,) = seg.feed_line('{"a": 1}')
    assert entry.logged_at == "2026-10-06T14:42:30"
    assert entry.header == "06/10/2026 14:42:30"


def test_a_given_resolver_gets_each_captured_header_once_in_file_order():
    seen: list[HeaderStamp] = []

    def resolve(parsed: HeaderStamp) -> str | None:
        seen.append(parsed)
        return "2000-01-01T00:00:00" if parsed.shape == "dot-24h" else None

    seg = Segmenter(resolve_date=resolve)
    out = []
    for line in [
        UNITY_PREFIX + "06.10.2026 14:39:58", '{"a": 1}', '{"b": 2}',
        UNITY_PREFIX + "06/10/2026 14:39:17", '{"c": 3}',
        UNITY_PREFIX + "2026-10-06 14:39:58", '{"d": 4}',   # in no shape: never offered
    ]:
        out.extend(seg.feed_line(line))
    assert [p.text for p in seen] == ["06.10.2026 14:39:58", "06/10/2026 14:39:17"]
    assert [e.logged_at for e in out] == ["2000-01-01T00:00:00"] * 2 + [None, None]


def test_a_segmenter_takes_a_hint_or_a_resolver_not_both():
    with pytest.raises(ValueError, match="not both"):
        Segmenter(locale_hint="mdy", resolve_date=fixed_resolver("dmy"))


def test_header_on_inline_entries():
    stamp = "2026/10/06 14:37:42"
    lines = [
        '{"before": 1}',
        UNITY_PREFIX + stamp,
        UNITY_PREFIX + '==> GraphGetGraphState {"id":"x","request":"{}"}',
        UNITY_PREFIX + 'Client.SceneChange {"toSceneName":"Home"}',
        '{"bare": 1}',
    ]
    before, *after = segment_lines(lines)   # no hint: a year-first stamp needs none
    assert (before.logged_at, before.header) == (None, None)
    assert [(e.logged_at, e.header) for e in after] == [("2026-10-06T14:37:42", stamp)] * 3


def test_header_on_multi_line_entries():
    lines = [
        UNITY_PREFIX + "2026-10-06 오후 2:38:24",
        "<== DeckUpsertDeckV3(00000000-0000-0000-0000-000000000001)",
        "{",
        '  "DeckId": "x"',
        "}",
        UNITY_PREFIX + "06.10.2026 14:39:58: SELFCLIENTID0001 to Match: ClientToGreuimessage",
        "{",
        '  "requestId": 5',
        "}",
        UNITY_PREFIX + "06/10/2026 14:39:17",
        "<== DeckDeleteDeck(00000000-0000-0000-0000-000000000002)",
        "Success",
    ]
    response, event, bare = segment_lines(lines, "dmy")
    assert (response.logged_at, response.header) == (
        "2026-10-06T14:38:24", "2026-10-06 오후 2:38:24"
    )
    assert (event.logged_at, event.label, event.header) == (
        "2026-10-06T14:39:58", "ClientToGreuimessage", "06.10.2026 14:39:58"
    )
    assert (bare.payload, bare.logged_at, bare.header) == (
        "Success", "2026-10-06T14:39:17", "06/10/2026 14:39:17"
    )


def test_header_carries_to_a_fresh_segmenter():
    first = Segmenter(locale_hint="dmy")
    first.feed_line(
        UNITY_PREFIX + "06/10/2026 14:39:30: SELFCLIENTID0001 to Match: ClientToGreuimessage"
    )
    carry = first.carry_state()
    assert carry == ("2026-10-06T14:39:30", "ClientToGreuimessage", "06/10/2026 14:39:30")
    second = Segmenter(locale_hint="dmy")
    second.restore_carry(*carry)
    (entry,) = second.feed_line('{"requestId": 5}')
    assert (entry.logged_at, entry.label, entry.header) == carry


def test_restore_carry_still_takes_two_values():
    # reader/ingest.py restores only the two values it persists today
    seg = Segmenter(locale_hint="mdy")
    seg.restore_carry("2026-10-06T14:37:04", None)
    (entry,) = seg.feed_line('{"a": 1}')
    assert (entry.logged_at, entry.header) == ("2026-10-06T14:37:04", None)


# header_languages.log was captured on 2026-10-06 by switching Arena's in-game
# language: one English response, then per language one DeckUpsertDeckV3
# response and one ClientToGreuimessage event. The pairs, in file order, are
# Japanese, Korean, Spanish, German, then Italian and French; matched to the
# capture table (docs/arena-log.md, "Timestamps") by the second each example
# shows and its payload's LastPlayed.
HEADER_LANGUAGES = Path(__file__).parent / "fixtures" / "header_languages.log"
HEADER_RELAUNCH = Path(__file__).parent / "fixtures" / "header_relaunch.log"
_PAIR_SHAPES = [
    "ymd-slash-24h", "ymd-dash-ko", "slash-24h", "dot-24h", "slash-24h", "slash-24h",
]
_PAIR_LABELS = ["DeckUpsertDeckV3", "ClientToGreuimessage"]
_DOTNET_EPOCH = datetime(1, 1, 1)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _payload_times(entries) -> list[str]:
    """Each entry's local time to the second, read from its own payload: a
    DeckUpsertDeckV3 response's LastPlayed is local time with its offset,
    written the second its header was; a ClientToGreuimessage's timestamp is
    .NET ticks (100 ns since 0001-01-01) in UTC, put in local time by the
    offset of the response before it."""
    times = []
    offset = None
    for e in entries:
        body = json.loads(e.payload)
        if "Attributes" in body:
            raw = next(a["value"] for a in body["Attributes"] if a["name"] == "LastPlayed")
            played = datetime.fromisoformat(json.loads(raw))
            offset = played.utcoffset()
            local = played.replace(tzinfo=None)
        else:
            assert offset is not None
            local = _DOTNET_EPOCH + timedelta(microseconds=int(body["timestamp"]) // 10) + offset
        times.append(local.replace(microsecond=0).isoformat())
    return times


def test_every_language_at_its_own_headers_time_under_dmy():
    entries = segment_lines(_lines(HEADER_LANGUAGES), "dmy")
    assert len(entries) == 1 + 2 * len(_PAIR_SHAPES)
    languages = entries[1:]
    assert [e.logged_at for e in languages] == _payload_times(languages)
    assert [e.label for e in languages] == _PAIR_LABELS * len(_PAIR_SHAPES)
    assert [_shape_of(e.header) for e in languages] == [
        shape for shape in _PAIR_SHAPES for _ in _PAIR_LABELS
    ]


def test_year_first_and_english_entries_right_under_mdy():
    entries = segment_lines(_lines(HEADER_LANGUAGES), "mdy")
    english, year_first = entries[0], entries[1:5]
    assert [e.logged_at for e in year_first] == _payload_times(year_first)
    assert [e.label for e in year_first] == _PAIR_LABELS * 2
    # The English response ({"MatchesV3": []}) carries no time of its own: its
    # stamp is the capture table's "10/6/2026 2:37:04 PM", and its date is the session's,
    # which the Japanese response's LastPlayed fixes.
    session_date = _payload_times(year_first)[0][:10]
    assert english.label == "EventGetActiveMatches"
    assert english.logged_at == f"{session_date}T14:37:04"
    assert english.header == "10/6/2026 2:37:04 PM"


def test_header_is_each_captured_stamp_exactly_as_written():
    entries = segment_lines(_lines(HEADER_LANGUAGES), "dmy")
    # The capture table: the response of each language whose example it shows
    assert [entries[i].header for i in (1, 3, 5, 7)] == [
        "2026/10/06 14:37:42",
        "2026-10-06 오후 2:38:24",
        "06/10/2026 14:39:17",
        "06.10.2026 14:39:58",
    ]


def test_relaunch_request_before_the_first_header_has_no_time_and_no_header(caplog):
    with caplog.at_level(logging.WARNING, logger=segmenter.__name__):
        entries = segment_lines(_lines(HEADER_RELAUNCH), "dmy")
    request, *responses = entries
    assert (request.kind, request.label) == (EntryKind.REQUEST, "GraphGetGraphState")
    assert (request.logged_at, request.header) == (None, None)
    # The relaunch came up in Portuguese: day first, on the capture day.
    assert [_shape_of(e.header) for e in responses] == ["slash-24h", "slash-24h"]
    assert all(e.logged_at and e.logged_at.startswith("2026-10-06T") for e in responses)
    # Every digit-led prefixed line in it is a captured shape.
    assert not caplog.records
