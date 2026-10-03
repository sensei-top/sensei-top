"""Segmentation tests. Every rule is backed by the anonymized real-log fixture
(tests/fixtures/sample_player.log, captured from client 2026.62.10 on Linux/Proton)
or by minimal synthetic lines for edge cases the fixture can't easily show.
"""

import json
import logging
from pathlib import Path

import pytest

from sensei_top.reader.segmenter import (
    EntryKind,
    JsonAccumulator,
    Segmenter,
    parse_header_timestamp,
    segment_lines,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_player.log"


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
# line as its payload: no "==>" arrow, no header context. These lines used to
# be discarded outright, which is why the draft tab stayed blank for a human
# (Premier/Traditional/Cube) draft. Expectations below are read off the
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
    ts, _ = parse_header_timestamp(text, hint)
    assert ts == expected


def test_ambiguous_date_without_hint_is_none():
    ts, _ctx = parse_header_timestamp("3/7/2026 1:00:00 PM", None)
    assert ts is None


def test_impossible_date_for_hint_is_none():
    # 13/8 read as month=13 under mdy: refuse rather than guess
    ts, _ = parse_header_timestamp("13/8/2026 1:00:00 PM", "mdy")
    assert ts is None


def test_header_context_extracted():
    ts, ctx = parse_header_timestamp(
        "8/13/2026 2:49:19 PM: Match to SELFCLIENTID0001: GreToClientEvent", "mdy"
    )
    assert ts == "2026-08-13T14:49:19"
    assert ctx == "Match to SELFCLIENTID0001: GreToClientEvent"


def test_header_context_extracted_24_hour():
    ts, ctx = parse_header_timestamp(
        "25/9/2026 17:30:05: Match to SELFCLIENTID0001: GreToClientEvent", "dmy"
    )
    assert ts == "2026-09-25T17:30:05"
    assert ctx == "Match to SELFCLIENTID0001: GreToClientEvent"


def test_refused_time_keeps_context():
    ts, ctx = parse_header_timestamp(
        "9/25/2026 13:00:00 PM: Match to SELFCLIENTID0001: GreToClientEvent", "mdy"
    )
    assert ts is None
    assert ctx == "Match to SELFCLIENTID0001: GreToClientEvent"


def test_non_timestamp_line_returns_none_none():
    assert parse_header_timestamp("STATE CHANGED {}", "mdy") == (None, None)
