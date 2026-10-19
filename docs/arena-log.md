# Arena's log: what it actually does

Verified against client 2026.62.10 on Linux/Proton. Everything here cost real
debugging; treat it as given rather than rediscovering it.

**Prerequisite:** *Detailed Logs (Plugin Support)* must be enabled in Arena
(Options → Account). Without it there is no JSON in the log at all.

## File handling

- Arena **truncates `Player.log` on every launch**, preserving the previous
  session as `Player-prev.log` in the same directory — and only until the
  *next* launch. Recovery on startup reads `-prev` first, then the live file.
- Truncation is detected as "file smaller than last time" or "inode changed";
  the offset resets to 0 and the file is re-read. Dedupe absorbs the overlap —
  but "the overlap" is not always a small rotation boundary. Observed for
  real, on Linux/Proton: `Player-prev.log` reappeared almost wholesale inside
  `Player.log`, not just at the seam. Content-based dedup (`reader/ingest.py`)
  still gets most of it, but two independently-captured files are not
  guaranteed to repeat their internal near-duplicates (byte-identical
  same-second polls) in the same relative order, so raw-level dedup is not a
  complete guarantee — see `projector/game_state.py` for the layer that
  actually has to be idempotent regardless.
- The log mixes **CRLF with bare CR** line endings. A terminator check for
  `"\n"` alone stops ingestion at the first bare-CR line. `reader/ingest.py`
  reads the file in binary mode and splits lines itself, byte-exact, to the
  same rule: a line ends at `\n`, at `\r\n`, or at a `\r` not followed by
  `\n` (or that is simply the last byte read, at EOF).
- A line with no terminator means the game is mid-write. Stop before it and
  resume there next pass, rather than parsing half a line.
- The live watcher polls `ingest_file` roughly once a second, and a poll can
  land mid-entry — most often inside a multi-line response. That entry is
  **held back**, not split or discarded: the committed byte offset never
  advances past its first line, and three small pieces of segmenter state
  (`_last_ts`, the most recent header timestamp; `_last_context`, a header's
  label for the next bare `{` line; `_last_header`, that header's stamp as
  written) are persisted alongside it (`ingest_state.carry_ts`/`carry_context`,
  migration 042, and `carry_header`, migration 062) so the next poll's
  segmenter can pick up exactly where the last one left off, rather than
  starting blank every second. A request landing as the first thing in a poll
  used to get `logged_at = NULL` and then a real timestamp when the same
  content was read again whole as `Player-prev.log` — two different digests,
  one entry stored twice. An entry that never closes (corrupt in some new
  way, not merely still arriving) is abandoned past a size cap rather than
  held back forever, which would otherwise make every future poll re-read an
  ever-growing tail.

## Entry shapes

Five shapes matter; everything else (`[PhysX]`, `[Manifest]`, `[TaskLogger]`,
`[Subsystems]`, `[SocialManager]`) is engine noise.

1. **Single-line request** — `[UnityCrossThreadLogger]==> Method {json}`
2. **Response** — a bare `<== Method(uuid)` line with **no prefix**, payload
   starting on the *next* line, possibly spanning many
3. **Prefixed event with header**, payload on following lines
4. **Bare JSON** with no header at all — match service events such as
   `matchGameRoomStateChangedEvent` often appear this way
5. **Response with a non-JSON body** — observed for real on `DeckDeleteDeck`,
   which replies with the bare word `Success` instead of JSON. The segmenter
   emits that first line verbatim as the response's payload instead of
   feeding it to the JSON accumulator, which would otherwise never see a
   `{`/`}` pair balance and swallow every following line — requests included —
   until one happened to balance by accident.

Payloads must be extracted by **brace-depth counting that respects string
literals and backslash escapes**. Payloads legitimately contain `{` and `}`
inside strings (card text, escaped nested JSON), so naive counting or regex
corrupts them.

Request payloads frequently contain **string-escaped JSON inside JSON** — a
second `json.loads` pass on a field like `request`. The reader stores it raw;
the projector does the second pass.

## Timestamps

A header's date and time are written in **Arena's in-game language**, not
the operating system's locale, and one file can switch between them: a
language saved in the client's settings applies from the first header of the
next launch. (Whether Windows' regional format also reaches the header while
Arena is in English is not known; `docs/status.md`.) The `Startup Timestamp:`
line near the top of every log stays English and is not a header. Captured
on 2026-10-06, every language, five shapes:

| Shape key | Written | Example | Languages |
|---|---|---|---|
| `slash-12h` | `a/b/yyyy h:mm:ss` then `AM`/`PM` | `10/6/2026 2:37:04 PM` | English (month first) |
| `slash-24h` | `a/b/yyyy HH:mm:ss` | `06/10/2026 14:39:17` | Spanish, Italian, French, Portuguese (day first) |
| `dot-24h` | `a.b.yyyy HH:mm:ss` | `06.10.2026 14:39:58` | German (day first) |
| `ymd-slash-24h` | `yyyy/MM/dd HH:mm:ss` | `2026/10/06 14:37:42` | Japanese |
| `ymd-dash-ko` | `yyyy-MM-dd`, `오전`/`오후`, `h:mm:ss` | `2026-10-06 오후 2:38:24` | Korean |

The keys are stored (`header_date_order.shape`, below), so they never
change. A shape with no capture is not added (rule 7), with one exception:
Korean `오전` (AM) is in no capture and is accepted by symmetry with the
captured `오후`, pinned by a string test only.

**What a header is** (`reader/segmenter.py`). A `[UnityCrossThreadLogger]`
body that starts with a digit and holds an `H:MM:SS` time before its first
`": "`. The stamp is the text up to that `": "`, the context label the text
after it. Unprefixed digit-led lines (`10/6/2026 2:37:07 PM
LoadWrapperScene`, `Coroutine…`) are not headers.

**Every header replaces the last one's time, label and stamp**, even when
its date can't be read — then its entries get `logged_at` `None`, never the
previous header's time. Until plan 3 the parser knew only the two slash
shapes, so a Japanese, Korean or German header was no header at all: its
entries silently kept the time of whatever English or Spanish header came
before. A stamp in no captured shape, or one in a captured shape whose time
or date is impossible (`9/25/2026 13:00:00 PM`, a 12-hour hour outside 1–12),
is still a header with no date, and warns once per process per pattern.
`logged_at` is **never synthesized**: a guessed timestamp corrupts ordering
and dedupe permanently.

**Day and month.** `06/10/2026` is the 6th of October in a Spanish header and
would be the 10th of June in an English one, and both can sit in one
`Player.log`, so no single order fits a file, let alone a machine. The CLI's
`--locale` defaults to `[arena] date_order` in `config.toml` (`config
--set-date-order`), else `auto`; `mdy` and `dmy` are overrides that read
every non-year-first header that way and warn once per shape when a date is
impossible in that order. The library functions (`ingest_file`, `live.py`)
default to `None`, which dates year-first shapes only, and pass the string
through unchanged. `auto` (`reader/dates.py`) settles each header with the
first of these that answers:

1. A year-first shape (Japanese, Korean): read as written.
2. Only one order gives a real date (a field above 12): that one.
3. Both orders give the same date (equal fields): that one.
4. The reading inside the file's window, from its last write minus 7 days to
   its last write plus 1 day, both naive local time like the header. A
   header's two readings are at least 27 days apart (2/3 against 3/2), so at
   most one fits; for the live watcher the last write is seconds old, so
   this settles every header of a session up to a week long.
5. The order this database learned for the shape.
6. `None`, with a warning naming the file, the stamp and the shape.

Steps 2 and 4 teach: the order lands in `header_date_order`, one row per
shape key (`date_order`, the stamp that `settled_by` it, its `source_file`,
`settled_at` in UTC), in the same transaction as the read's rows, and only
when it changes. What a read learns applies to its own later headers; there
is no second pass, so an earlier `None` in that read stays `None`. A header
that settles its shape against the learned order warns, and the new order is
learned — the latest evidence wins — but rows already stored never change.
The `mdy`/`dmy` overrides neither read nor write the table. `project()`
never touches it: it is reader state, like `ingest_state`. Each `auto`
warning fires once per process per file and shape, so a watcher polling
every second doesn't repeat it.

**The stamp is kept.** `raw_events.header` (migration 062) holds each
entry's stamp exactly as written, outside the digest, so a date read wrongly
today can be re-derived later. Nothing re-derives it yet; `docs/status.md`
records the one case that would need it.

## The traps

Each of these produced a real bug or a wrong conclusion.

**1. `GameStage_GameOver` is emitted twice** for a match's final game — once
with `MatchState_GameComplete`, again with `MatchState_MatchComplete`. Count
only the former, or every deciding game is counted twice.

**2. `gameInfo.results` is cumulative**, not this game's result. It lists every
result so far in the match. Game N's outcome is the `MatchScope_Game` entry at
index `N - 1`. Taking the last entry makes every game inherit the latest result.

**3. Most events batch multiple `GameStateMessage` entries** in
`greToClientEvent.greToClientMessages[]`. Iterate every element; a find-first
approach silently drops turn changes.

**4. `turnInfo` is a sibling of `gameInfo`, not nested inside it.**

**5. `turnInfo.turnNumber` counts player-turns, not rounds.** A game where each
player took 12 turns reports `turnNumber: 24`, and `players[].turnNumber` in
that same message reads 12. Game "length" is therefore roughly twice the round
count — label it as player-turns in any UI, or the numbers look absurd.

**6. Full snapshots and diffs look alike, but `type` tells them apart.** A
`GameStateMessage` with `type: GameStateType_Full` is the whole board and
replaces what came before; `GameStateType_Diff` carries only what changed.
Merge a diff's fields into running state and purge anything in its
`diffDeletedInstanceIds`, or the board fills with phantom cards. On one real
session, diffs outnumbered full snapshots 206 to 1. A full snapshot whose
`update` is `GameStateUpdate_Undo` is not a fresh start but a rewind (trap 16).
This trap once said no flag existed; the projector branched on `type` all
along.

**7. `AnnotationType_ObjectIdChanged` re-keys objects.** A resolving spell gets
a new `instanceId`; without re-keying, battlefield counts double-count. One
session contained 32 of these.

**8. Annotation `type` is an array of strings** even when single-valued, and
data lives in a uniform `details[]` array of typed key/value entries with
snake_case keys (`orig_id`, `new_id`, `zone_src`). Look details up by key;
never index positionally.

**9. State can outlive `GameOver`.** Arena keeps sending state for a game after
its `GameOver`, and an abandoned game never gets one at all. The last turn must
be flushed at the end of the replay or it is silently dropped.

**10. Arena omits `mulliganCount` entirely when it is zero**, but reports it
for both seats when non-zero. Seeing the seat at all is what distinguishes
"kept seven" (0) from "never observed" (`NULL`).

**11. `GREMessageType_SubmitDeckReq` *does* appear**, paired with a
`SubmitDeckConfirmation`, at Bo3 sideboard intermissions, and always for our
own seat. An earlier note here claimed it never appears; that was wrong. It is
still not a reliable game boundary (game 1 has none), so key boundaries off
`gameInfo.gameNumber` changing — and it never carries the opponent's deck.

**11b. Arena never sends the opponent's decklist, deck name, or rank.**
Verified by sweeping every label in a real capture: every `DeckId` in the log
belongs to our own account, `connectResp.deckMessage` is only ever sent for our
seat, and `reservedPlayers[].courseId` — which looks promising — holds a
cosmetic avatar id such as `Avatar_Basic_Teferi`. Every opponent `Draw` is a
zone transfer with `grp_id` NULL, because the client omits the game object for
a card we may not see. So the opponent's deck can only ever be *inferred* from
the cards they revealed; see `src/sensei_top/archetypes/`.

**11c. A Bo3 break has no event of its own — it is the gap between two
`gameInfo`s.** It opens on a `gameInfo` with `stage: GameStage_GameOver`,
`matchState: MatchState_GameComplete` and `matchWinCondition:
MatchWinCondition_Best2of3`; a concede takes the same path, with
`ResultReason_Concede` on its result. Two nearby messages look like markers
and are not:

- `GREMessageType_IntermissionReq` rides the game-over event, but it also
  rides the match-final one — the event that carries `GameComplete` *then*
  `MatchComplete` (trap 1). Key off `matchState`, processed in message order,
  never off `IntermissionReq`.
- `SubmitDeckConfirmation` (trap 11) is a bare `{type, systemSeatIds, msgId,
  gameStateId}` with no `gameInfo`, and it does not end the break: we are
  still waiting on the opponent's own submission. In
  `tests/fixtures/intermission_session.log` the confirmation lands 14 seconds
  before game 2's first `gameInfo` (`gameNumber: 2`, `GameStage_Start`), which
  is the break's real end.

The board state stays as game 1 left it until game 2's first state message
arrives, so a replay that stops mid-break still sees the finished game's zones.

The break ends on the first of two things, in message order: a
`MatchState_MatchComplete` (trap 1), or a `gameInfo` whose `gameNumber` is
greater than the game that opened it — `projector/live_state.py`'s
`replay_live_state` clears `LiveState.intermission` on either, and never on
`SubmitDeckConfirmation`.

**11d. A match's best-of is in `gameInfo.matchWinCondition`, on every game's
state messages.** `MatchWinCondition_Best2of3` is a best of three and
`MatchWinCondition_SingleElimination` a best of one; a real history holds
nothing else. The value is the match's, not the game's: a Bo1 carries
`SingleElimination` on its one game, a Bo3 `Best2of3` on all of them. Neither
the queue nor the event id says which: `DirectGame` is either. The projector
keeps the first value it sees as `matches.best_of` (3 or 1); an unknown value
is NULL and warns, a later different value warns and changes nothing, and a
match whose log never shows a `gameInfo` (`sample_player.log`'s) is NULL with
no warning of its own.

**12. The `name` field on a game object is a numeric ID, not a string.** Card
names require a `grpId` lookup against Scryfall data.

**12b. `isTapped` is set but never cleared.** A game object carries
`"isTapped": true` when a permanent taps, and Arena **never** sends the false —
149 objects carry the true across a full real log, and not one carries the
false. Because diffs merge field by field (trap 6), a land that untaps keeps
reading tapped forever unless something else corrects it. That something is
`AnnotationType_TappedUntappedPermanent`, whose `details[]` holds
`{"key": "tapped", "valueInt32": [1 | 0]}` — 87 taps and 79 untaps in the same
log. It is the only untap signal there is.

Worse, **the untap rides the message that advances the turn**. Every untap in
the fixture arrives in a diff reading `turnNumber: N+1, step: Step_Upkeep`, so
handling it in the ordinary annotation pass (which runs before `turnInfo`) would
untap the board of the turn that just *ended* — showing every land upright on
the very turn it was tapped for mana. `_apply_tapped` therefore runs after the
turn boundary, alone among the annotations. A mid-turn untap effect crosses no
boundary, so it still lands on the turn it happened in.

**12c. `ZoneType_Exile` is shared and carries no `ownerSeatId`.** Hand,
graveyard, library and sideboard zones all name their owner; exile, battlefield,
stack and limbo do not. So exiled cards have to be attributed from each object's
own `ownerSeatId` (ownership, not control — the card belongs to whoever owns it,
not whoever exiled it), and an exiled instance whose game object we never
received cannot be attributed at all. Unlike a hidden hand, it is dropped rather
than recorded as a card back: with no zone owner and no object, emitting one
would mean inventing a seat.

**12d. `power` and `toughness` are boxed as `{"value": n}`.** They appear only
on objects that have them, and a characteristic-defining `*` arrives as the same
box with no `value` key. Both absences collapse to `NULL` — never 0, which would
be a real number nobody observed.

**Combat is projected as of `migrations/014_combat.sql`.** This was
"deliberately unparsed" for a while, and the deliberate part was narrower
than it sounded: nothing in the captured fixture showed its annotation shape,
so no fixture-backed test could be written (AGENTS.md rule 7) — not that
Arena withholds it. `tests/fixtures/combat_session.log` was carved once a
real capture containing `gameObjects[].attackState`/`blockState` and
`AnnotationType_DamageDealt`/`ModifiedLife` was found (see that migration's
own comments for two traps found in the process: Arena reuses an
annotation's `id` across genuinely different annotation types within one
game, so a shared dedup set silently drops real events; and the same attack
assertion gets re-broadcast across several consecutive messages for one real
attack). Counters (`AnnotationType_CounterAdded`/`Removed`) remain unparsed
for the original reason — no captured fixture shows their shape yet.
`turnInfo.phase` / `step` are read and discarded for a different reason: a
turn snapshot is a single end-of-turn state, so a phase would read
`Step_Cleanup` on every row and carry no information.

**13. `Player-prev.log` and `Player.log` can overlap almost entirely, not just
at a rotation seam.** The "recovery reads `-prev` then the live file" story
above assumes a narrow shared boundary; a real capture (Linux/Proton) instead
had `-prev` reappear almost wholesale inside the live file, hours of session
included twice. Raw-event dedup narrows this (see `reader/ingest.py`'s digest
docstring) but a duplicate raw event can still reach the projector — which is
why `card_events` dedupes itself on the `ZoneTransfer` annotation's own `id`
rather than trusting the reader to have caught everything first.

**14. Arena logs the opening hand before the mulligan decision, contradicting
what this file used to imply.** Trap 10 above is about `mulliganCount`
specifically and is still correct; it is not a claim that nothing about a
mulligan is logged before the decision. A `GameStateMessage` diff sets
`players[].pendingMessageType == "ClientMessageType_MulliganResp"` and, in
that same or a later diff, includes the pending seat's hand as real
`gameObjects` (`grpId` included) — but only for our own seat, exactly as
consistent with trap 11b as everything else about the opponent. The decision
itself is a `ClientToGREMessage` with `payload.type ==
"ClientMessageType_MulliganResp"`, `mulliganResp.decision` one of
`MulliganOption_AcceptHand` / `MulliganOption_Mulligan` — always ours; Arena
relays the opponent's decision only as its *effect* on shared state, never
the outgoing message. Verified against 503 real decisions in a live capture:
every offer resolves to exactly 7 cards (Magic's own London mulligan rule),
zero failures. Two more traps hit getting there:

- A follow-up diff regularly re-affirms `pendingMessageType` without
  resending `gameObjects` — a single message cannot always be parsed alone.
- **Filtering `gameObjects` by `zoneId` over-counts the hand.** A stale
  object can keep an old `zoneId` after actually leaving that zone; the
  zone's own `objectInstanceIds` is the only reliable membership list.
  `card_events` and `turn_zones` never hit this because they read from
  `zones[].objectInstanceIds` already (`game_state.py`'s `_zone_cards`) —
  it is only a hazard for code that reads `gameObjects` directly.

**Arena also reuses small instance ids and `gameStateId` counters from game
to game, even match to match.** A naive fixed-size backward scan over
`raw_events` can resolve a stale hand from an unrelated earlier game that
happens to reuse the same ids — real and observed, not theoretical. Anchor
any such replay to the current match's own room-opening event
(`matchGameRoomStateChangedEvent` / `MatchGameRoomStateType_Playing`) and
never read further back than that.

**15. A draft's `BotDraftDraftStatus`/`BotDraftDraftPick` messages are
double-encoded, and there is no draft-instance id anywhere in them.** The
outer log line is one JSON object; its `Payload` (responses) or `request`
(requests) field is itself a JSON *string* holding the real content —
`greToClientEvent`'s nesting is one level, this is two, and a single
`json.loads` silently returns the outer envelope rather than failing loudly.
Card ids inside arrive as strings too (`"102691"`), not integers. And
`EventName` (e.g. `"QuickDraft_SOS_20260831"`) names the redrafted *event*,
never one specific draft of it — verified across every key in a real
capture, the outer keys are only `CurrentModule`, `DTO_InventoryInfo`,
`Payload`, `id`, `request`, none of them a draft-instance id. Nothing
parses a draft today — the draft assistant was deleted on 2026-10-01 and
the segmenter only labels these entries, so they stay in `raw_events` — but
`docs/draft.md` and `projector/draft.py` at the `archive/draft` tag, in
the project's pre-public history rather than this repository, hold the
full protocol and how `draft_id` was synthesized, for whoever brings
drafts back.

**16. A player can undo an action, and the log rewinds with it.** Arena
sends a `GameStateType_Full` state whose `update` is `GameStateUpdate_Undo`
and whose `prevGameStateId` names the state the game returns to. The states
in between never happened: a spell cast in them was not cast. Only the
user's own undos reach the log (211 in the real history as of 2026-10-19;
the 76 that cancelled something cancelled the user's own cast or
sacrifice). The projector drops the `card_events` recorded after the named
state, by the order states were applied, not by comparing ids: 16 of 923
real games carry `gameStateId`s that are not monotonic. An undo naming a
state never applied in that game drops nothing and warns. Arena also
rewinds its annotation ids: the cast that follows an undo can reuse the
cancelled cast's annotation and instance ids while moving a different
card, so the ids of the dropped rows are forgotten too, or the real cast
would look like a re-broadcast. `tests/fixtures/undo_session.log` holds one
(Undo at state 101, back to 99).

**17. `GREMessageType_QueuedGameStateMessage` is a state message too.** It
carries a `gameStateMessage` like `GREMessageType_GameStateMessage` does,
and its zone changes are real: apply it once, like any other. In the real
history (2026-10-19), 7,772 queued states and none of them arrived again as
a plain one, so nothing is applied twice. A queued and a plain message can
share one event: `tests/fixtures/undo_session.log` has queued states 96 and
97 beside plain 98 and 99.

**18. Arena can replace an oversized message with a summary.** Other
projects document a `[Message summarized because one or more
GameStateMessages exceeded the 50 GameObject or 50 Annotation limit.]` line
followed by lines opening with three or two colons that give the counts,
in place of the message itself. None has appeared in the user's logs (2026-10-19). The segmenter
recognises the block, warns once per block with its counts, and stores
nothing: the state it replaced is lost, and that game's replay is missing
it. A block that is the very last thing in a file that never grows again
does not warn (`docs/status.md`, "Correctness").

**19. One bad message must not cost its neighbours.** An event batches many
messages (trap 3), the game's result often among them. The projector
catches an exception per message, warns with the message's `type` and
`gameStateId` and applies the rest; before, one failure lost the whole
event, `GameOver` included.

## Deriving the two hardest fields

- **Self seat**: match `authenticateResponse.clientId` (or `userId`) against
  `reservedPlayers[]`. If the log lost that event (truncated session), the seat
  is unresolved — warn, and omit rows whose meaning depends on it.
- **On the play**: `turnInfo.activePlayer` when `turnNumber == 1`, compared to
  self seat. **Record it per game, not per match** — in Bo3 the previous loser
  chooses, so it alternates within a match. `activePlayer` is present on
  ~83% of mulligan-offer messages too, well before `turnNumber` ever exists
  (trap 14) — `table/opening_hand.py` reads it there for the same
  comparison, since who is on the play is already decided by the time the
  first hand is offered.

## Expect breakage

Wizards has removed log data without notice repeatedly (collection and
inventory endpoints in Aug 2021, MMR in Aug 2022, opponent display names in
July 2024). Design every parser to degrade: an unknown or missing field
produces a warning and a `NULL`, never an exception that halts ingestion.
