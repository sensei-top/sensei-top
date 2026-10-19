# The Live page's reads

Read this when touching `table/`, the `/api/current-match/read` route, or
`OpeningHandCard`/`KeepGuideCard`/`OpponentHandCard`/`OpponentRead`/`LibraryCard`.

The Live page (`/live`) is `CurrentMatchView`, which was the Current match
tab when most of this was written: "the tab" below is that page.

## Why this exists

The tab used to show a you-vs-opponent scoreboard (life, hand, library,
graveyard, open mana) and a `HintsPanel` with three free facts: board math
(untapped creature power), play-around (an archetype's signature cards, with
no sense of whether they were still live), and next-draw odds. Two of those
survived — the opponent-deck prediction (`OpponentRead`) and next-draw odds,
which moved from a capped, disclosure-hidden `NextDrawsCard` into the tab's
own primary panel (`LibraryCard`, below). The rest were retired for the same
reason: **Arena already shows life, hand size, library count and untapped
mana on screen.** A second panel restating them is not a second opinion, it
is a second copy.

What Arena does *not* show is what this file's reads compute instead:
whether the hand you were just dealt is worth keeping, whether the hand
you're holding later in the game is the shape your own deck wants, what the
opponent's revealed cards imply is still in their hand, and — the tab's
primary panel once a game is under way — exactly what's left in your own
library and the odds of drawing it soon. Every one of them lives in
`src/sensei_top/table/`, a sibling to `review/` for the same architectural
reason: `review/` only runs once a match is over, `table/` only runs while
one is in progress. Neither writes anything, so every route built on it
stays in the API's read-only majority (AGENTS.md non-negotiable #6).

## The live replay (`table/live.py`, `projector/live_state.py`)

*"What does the board actually look like right now?"* — answered by
replaying the current match's own `raw_events` at request time, never by
reading `turns`/`matches`.

**Why this exists.** A database with 238,520 raw events (~1.33 GB) measures
**~16.2 s** wall time for one `project()` rebuild (of which parsing every
payload with `orjson` is ~9.7 s; dispatch and the SQL writes account for the
rest) — already well past `project_every`'s 5 s default. Left unchecked, the
rebuild would run back-to-back rather than every 5 s; `live.py`'s duty-cycle
gate (`live.py`'s module docstring) instead paces rebuilds to roughly a
`1/duty_factor` share of wall time, so anything sourced from `turns`
(opponent hand size, library, open mana, your own turn history) runs stale
by roughly one gate interval — which grows, not shrinks, as history grows,
since a full rebuild's own cost is a function of total history, not new
rows. Replaying only the *current match* — bounded by its own room-opening
event, 990-4,276 events on the same database — costs **0.03-0.08 s**:
comfortably inside a 1-second poll, and the same order of magnitude
regardless of how much history sits behind it, and unaffected by the gate
since it never reads `turns`/`matches` at all.

Ingest itself no longer waits on a rebuild either: `run_forever` (`live.py`)
runs `ingest_once` on its own thread and its own connection, separate from
the thread that runs `project_if_due`'s rebuilds, so a mulligan offer still
reaches `raw_events` — and this replay — within one ingest tick even while a
match-boundary rebuild is mid-flight on the other thread. Measured by
replaying a match start into a 1.7 GB copy of the real database: the
offers landed 0.13 s after they were written, against 16–22 s on the
single-thread watcher. The one wait left is `project()`'s own commit
(5.7 s measured), which the ingest connection's 30 s `busy_timeout` waits
out rather than failing on. That split only
buys back the *ingest* lag; the staleness this section is about (`turns`,
`matches`, and anything the rebuild alone produces) is unchanged by it, which
is exactly why this replay reads `raw_events` directly instead of waiting for
either.

A rebuild that never stops running also means it never stops holding the
interpreter's GIL, and every API route is a synchronous `def` sharing that
GIL — so `serve --watch` runs the watcher in its own OS process
(`live.WatcherProcess`) rather than a thread inside the API's own process.
Without that separation a rebuild in progress taxed every request roughly
5x, this route included, regardless of whether the request touched anything
the rebuild was actually changing (`live.py`'s module docstring has the
measurements).

This is the general form of what `table/opening_hand.py` already did for
one narrow question ("is a mulligan pending"): `projector/live_state.py`
reuses `GameStateTracker` (the same tracker `project()` uses) and reads its
state as it stands *right now*, mid-turn, via `GameStateTracker.snapshot_now()`
rather than waiting for a turn boundary to finalize a row the way
`project()` does. This does not blur the reader/projector boundary
(non-negotiable #1): the code that knows Arena's message shapes is still
the projector; `table/live.py` only anchors the window (the newest
`MatchGameRoomStateType_Playing` row in `raw_events`, no lookback window —
see below) and calls into it.

**Self/opponent seat resolution reuses the hand asymmetry**
`docs/arena-log.md` documents and `projector/mulligan.py` first proved: our
own hand always resolves to real `gameObjects`; the opponent's hand zone
never does, at any point in the game, not only during a mulligan. That
needs no separate `authenticateResponse` lookup.

**One route, one replay.** `/api/current-match/read` builds a `LiveState`
once per request and hands its pieces to `build_opening_hand_read` and
`build_hand_read` instead of letting each replay independently — one pass
over the current match's events per request, not three.

**The anchor has no lookback window.** An earlier version of this bounded
the anchor search to the newest 2,000 `raw_events` rows — the shape
`table/opening_hand.py` used before this module existed. That window went
silently blind on a real database's own history: match spans there reach
4,276 events (median 1,021, p90 1,743), and **8 of 154 matches (5%)**
exceeded 2,000 — exactly the grindy Bo3s where a game-2 or game-3 mulligan
matters most. The single newest `MatchGameRoomStateType_Playing` row is
always the correct anchor regardless (there is exactly one per match,
verified against a real database), so the window bought nothing but the
blind spot; `find_anchor` has none.

**What it produces (`LiveState`):** `self_seat`/`opponent_seat`,
`turn_number` (`None` during the mulligan phase), per-seat `hand`/`library`/
`graveyard`/`open_mana` (untapped lands, same meaning as `turns.opp_open_mana`
always had) and `other_mana_sources` (untapped non-land mana producers —
rocks, dorks, Treasures; see below), every `zone_cards` entry seen this
game, and the pending `MulliganOffer` if any.

**Widened mana, as two numbers, not one.** `open_mana` under-reports against
ramp: it only ever counted untapped *lands*. Rather than merge in every
mana source (a summoning-sick creature can't legally tap, and an unnamed
Treasure grpId has no `produced_mana` on file to prove it produces
anything), `other_mana_sources` is a deliberate second, honest count —
untapped non-land permanents whose grpId has `cards.produced_mana` on file
— and `hand_read.py`'s `castable_now` sums the two as an explicit upper
bound ("could have"), never a certainty. `turns.opp_open_mana`'s own
meaning is untouched: it is read by the post-game report, and this project
does not redefine a column silently out from under an existing consumer.
The widened figure only exists on the live replay, `other_mana_sources` is
`None` outside one, and the UI labels it as "+N other" rather than folding
it into a single misleading number.

**Our own remaining library** (`build_library_remaining`) is the maindeck
(`decks.cards_json`, or the boarded list once a SubmitDeckResp was seen,
below) minus every copy of our own cards this game has shown
outside the library, deduplicated by `instance_id` so a card drawn then cast
counts once, not twice — the same subtraction `NextDrawsCard.tsx` used to
run client-side off a stale `turns` row, now server-side against the fresh
replay. `library_count` (the population size for the tab's draw-odds math)
comes from the same replay, not the projected `turns.self_library` — the two
would otherwise disagree by however stale the projection is.
A card whose every copy has been seen stays in the list at `left` 0,
so the panel keeps its row instead of dropping it mid-game.

Each nonland card also carries `is_interaction`: `True` when its oracle text
matches one of `effects.classify`'s `spot_removal`, `sweeper` or
`counterspell` patterns (the same three tags `table/keep.py`'s
`interaction_count` counts), `False` when text was available but matched
none of them, and `None` when the card has no downloaded oracle text at all
— a land is always `False` without consulting text. `None` is not the same
claim as `False`: it means "unclassifiable," never "not interaction," per
rule 4. A card table with no `cards --scryfall` run (or the installed-client
path, which never carries oracle text) makes every nonland row `None`.

## The opening-hand read (`table/opening_hand.py`)

*"Is the hand I was just dealt worth keeping?"* — read from the log
**before** the decision, not after.

**Arena does log the opening hand pre-keep.** This corrects a claim that
used to live here and in several other files: `migrations/009_drop_opening_hand.sql`
found that the *kept* hand's zone transfers arrive only after the mulligan
decision, and that finding is still true — but it does not mean nothing is
logged earlier. A `GameStateMessage` diff sets `pendingMessageType:
"ClientMessageType_MulliganResp"` on a player and, in that same or a later
diff, includes that seat's hand as real `gameObjects` — for our own seat
only, exactly as hidden as the opponent's hand is everywhere else in this
project. Verified against 503 real mulligan decisions in a live capture:
every offer resolves to exactly 7 cards, with zero failures, once the replay
is anchored to the current match's own start (Arena reuses small instance
ids and gameStateId counters game to game, even match to match — an
unanchored replay can resolve a stale hand). The parsing itself lives in
`projector/live_state.py` (`projector/mulligan.py` is now a thin wrapper
over it, kept for its existing name and importers), reusing
`GameStateTracker.apply()` for the gameObjects/zones merge rather than
reimplementing it, since a follow-up diff regularly re-affirms the pending
decision without resending the objects.

**Why this bypasses the projection.** Same reasoning as the live replay
above, and originally the *first* place this project drew that line: the
5-second median decision window is well inside `project()`'s ~16 s rebuild
time on a real database, so the projection can never land in time.
`build_opening_hand_read` defaults to replaying `raw_events` itself
(`table/live.py`'s anchor, `projector/live_state.py`'s replay) — every
existing caller keeps working unchanged — but accepts an already-resolved
`offer` from a caller building the wider live state anyway
(`/api/current-match/read`), so one request does one replay, not two.

**The deck comes from the same replay, not `v_current_match`.**
`/api/current-match/read` used to read `deck_id` only from the projected
`matches` row — stale by the same rebuild lag as everything else `project()`
owns, and `NULL` for the whole length of a match this session hasn't
projected yet at all. `projector/live_state.py`'s replay now resolves
`LiveState.deck_maindeck`/`deck_id` itself, from the match's own
`connectResp.deckMessage` (the same message `projector/matches.py`'s
`_handle_deck_message` parks until the match-start event claims it) —
"last one found wins" across the window, covering a mid-match reconnect's
resent deck. That message usually lands one row before or one row after the
room-opening anchor `table/live.py` replays from (measured read-only against
a real database: every one of 288 `MatchGameRoomStateType_Playing` rows had
its nearest connectResp at exactly one of those two offsets, 73 before and
215 after, never further); `replay_from_anchor` widens its own query with a
small, bounded pre-anchor lookback (`_DECK_MESSAGE_LOOKBACK`, a 10x margin
over that measurement) so the common anchor-1 case resolves without ever
touching `matches`. `deck_id` is computed with `projector/matches.py`'s own
`deck_identity`, so a deck resolved this way lands on the identical hash
`project()` would assign once it catches up — the route falls back to
`match_row['deck_id']` only when the replay itself found no connectResp in
either window (no match ingested this session, or a capture starting well
inside the match). After a sideboarding break `deck_maindeck` takes the
latest `ClientMessageType_SubmitDeckResp` of this match
(`submitDeckResp.deck`, a client-outbound message at the payload's top
level, the shape `projector/matches.py`'s `_handle_submit_deck` parses): once
one has been seen it replaces the connectResp's list, and a later connectResp
does not take it back. `deck_id` stays game 1's: it hashes the connectResp
list only, which is the one `project()`'s own `deck_id` is computed from. The
pre-anchor lookback reads connectResp messages only, since a SubmitDeckResp
before the anchor is an earlier match's.

`LiveState.deck_boarded` says `deck_maindeck` came from a SubmitDeckResp; the
library panel (`build_library_remaining`) and the keep guide
(`build_keep_guide(..., boarded=)`) then count that list rather than the
`decks` row, which is game 1's. The keep guide's mulligan record still reads
by `deck_id`, game 1's deck.

**The keep guide it builds along the way is reused, not recomputed.**
`OpeningHandRead` exposes the `KeepGuide` it already built internally
(`build_keep_guide` on this same `deck_id`); `/api/current-match/read` reads
that field instead of calling `build_keep_guide` a second time, falling back
to a fresh build only when `opening_hand` came back `None` (no match, or no
`deck_id` to build from). `build_keep_guide` re-runs `list_identities`
(13 identities × 3 queries on a real database) plus the mulligan aggregate
and `key_card_timing` every time it's called, so the earlier two-call shape
paid that cost twice per second, once inside each of this route's two reads.
Both call sites also pass the replay's own `deck_maindeck` through as
`build_keep_guide`'s new `maindeck` keyword — a fallback land-count source
for the case `v_deck_land_count` has no row yet (the projector fills that
view only on its next `project()`, which a match that started seconds ago
hasn't reached); the live replay already has the same maindeck straight from
`connectResp`, so the land band and ideal hand don't have to wait either.

**Land identification never touches the `cards` table.** Each dealt card
carries Arena's own `CardType_Land` straight from the log, so `land_count`
is exact even for a maindeck `sensei-top cards` has never named — an
improvement over `v_deck_land_count`'s `type_line` em-dash split, which
undercounts exactly there.

**Castability is a real search.** For each spell, the smallest number of
this hand's own lands (played one per turn, any of them, in the best order)
that can pay its colored requirement — `effects.mana_requirement` splits a
cost into its generic amount and colored pips, and a small backtracking
search (`_castable_with`) checks every combination of at most seven lands.
It only ever looks at this hand's own lands, never a hypothetical future
draw. `produced_mana` (`migrations/021_produced_mana.sql`, from Scryfall's
own export) is what makes this possible — `cards.colors` cannot: it is a
card's own color identity, `[]` for essentially every land including duals.
A land with no `produced_mana` on file falls back to
`effects.chosen_basic_type_colors`, which reads the land's own text for the
one shape Scryfall's export leaves blank on purpose: a land that chooses a
basic land type as it enters and then *is* that type (Multiversal Passage,
Thran Portal)
has no fixed mana ability to export, but its own printed text still names a
real, known color set — every basic type — so this is a known fact, not a
guess (rule 4).

**A land still unknown after that no longer blanks the whole verdict.**
Castability is computed twice against the rest of the hand's own lands:
once treating every still-unknown land as colorless, once as every color at
once — the honest bracket around a color nothing on file actually answers.
When both readings land on the same call, that call is published, with a
caveat naming the card(s) whose color didn't end up mattering. When they
disagree, the published verdict is withheld (`None`) and the caveat states
the condition outright — which color would have to make the call, and
which call each side gives — so that caveat becomes the headline rather
than a footnote. Per-card `castable_turn` and `reduced_castable_turn` shown
in the UI always come from the colorless (pessimistic) reading, in every
case.

**Castability reads printed cost only, and some cards' printed cost is the
wrong question.** A card with a cost-reduction clause (`review/effects.py`'s
`cost_reduction`) can be castable well before its mana value alone would
suggest: Eddymurk Crab (`{5}{U}{U}`, mana value 7) costs `{1}` less for each
instant/sorcery in the graveyard; Hearth Elemental (`{5}{R}` on its front
face) has the same "per card in graveyard" shape; Sunderflock (`{7}{U}{U}`,
mana value 9) instead costs `{X}` less, where X is the greatest mana value
among Elementals already on the battlefield — a board-state lookup, not a
per-card count, so it is approximated as the turn after the hand's earliest
other Elemental is castable, with no mana arithmetic, and withheld when the
hand holds no other Elemental (`_reduced_castable_turn_board_elemental`).
`reduced_castable_turn` is the earliest turn this hand's own
lands *and its own in-hand fuel* (instants/sorceries already drawn, for the
graveyard-count shape) or an already-resolved Elemental (for Sunderflock's
shape) can pay for it — computed only when the printed-cost search above
already ran, since it needs every other card's own `castable_turn` as fuel
evidence. It never overwrites `castable_turn`, which always stays the
printed-cost answer; a card whose reduction clause is a shape this parser
has never seen (`UNPARSED_REDUCTION`) withholds `reduced_castable_turn`
rather than guessing at an unfamiliar clause. `//`-split cards (Adventure,
MDFC) read only their front face's cost for both fields — the pre-fix
behaviour summed every pip in the whole string, double-counting the second
face as if it were part of the same cost.

**The verdict** — `keep` / `mulligan` / `marginal` — is one more coarse,
named heuristic in `table/keep.py`'s own style (a cutoff on land count and
early castability, not a simulation), reusing `build_keep_guide` for every
deck-level number rather than recomputing: lands in `[land_min, land_max]`
and enough of the hand castable by turn 3 to hit the deck's own
`early_plays` target (the same number `ideal_hand`'s "play(s) at 1-3 mana"
chip already carries, exposed here as a bare int). Withheld (`None`) rather
than guessed whenever an input is unknown — an unnamed card, no land band
for this deck yet, or (see above) an unresolved land whose color the hand's
own castability actually turns on — with a caveat naming the gap. "No land
band" itself splits two ways: no `deck_id` at all yet gets its own message
pointing at the gap directly, while a `deck_id` whose own land band is
withheld (an unnamed maindeck card, or not enough curve data) reuses
`build_keep_guide`'s own explanation verbatim rather than sending the
player to go read it a second time. The evidence (land count, per-card
castability) still renders in every case; only the headline call is held
back.

**A pressure check moves the verdict once there's enough of the deck's own
history to trust.** `build_keep_guide`'s `key_plays` (below) names this
deck's own evidence-backed threats; when they exist, a hand is checked for
whether it holds one of them and can actually reach it this game
(`castable_turn` or `reduced_castable_turn` set) — never merely for holding
the card. **In band, early plays met:** pressure present keeps the
unconditional "keep" this cutoff always gave; no pressure downgrades to
"marginal," with a reason naming the deck's top threat and its measured
split (a hand can meet the land/curve cutoffs and still be missing the one
card the deck actually wins with). **In band, early plays short:** no
pressure normally proceeds straight to "mulligan," but a `mulligan_cost`
(below) with at least a 13-point gap between this deck's kept-seven and
mulliganed (any number) win rates acts as a brake — the downgrade stops at
"marginal" instead, with a reason naming the cost, since shipping a hand
costs a measured, wide amount for this deck specifically. Only measured
evidence moves the verdict this way: with no `key_plays` at all (below the
same evidence floor as `key_plays`/`mulligan_cost` themselves), every one of
these checks is inert and the plain land-band/early-play cutoff decides
alone, exactly as it did before this mechanism existed.

## The keep guide (`table/keep.py`)

*"What does a keepable hand look like for this deck, in general?"* — the
mulligan question a player who knows their own list already answers from
memory, computed instead from `decks.cards_json` (the boarded list after a
sideboarding break; see the opening-hand read above) and the same
`cards.type_line` / `mana_cost` / `oracle_text` columns `review/snapshot.py`
already reads for the post-game report. Valid at any point in the game,
including before the very first decision — unlike the opening-hand read
above, it says nothing about the *specific* hand in front of you, only what
a good one looks like for this deck.

Two coarse, explicitly-labelled heuristics, not a simulation:

- **Land band.** `land_min` is 2 when at least 40% of nonland cards cost
  mana value 2 or less, else 3. `land_max` is 4 when the deck's average
  nonland mana value is 3.0 or under, else 5. A low-curve aggro deck gets
  2–4; a top-heavy midrange deck gets 3–5.
- **Ideal-hand shape.** Lands = `round(7 × land_count / maindeck_size)`
  clamped into the band above. Early plays = 2 when the deck has at least 8
  cards at mana value ≤ 2, else 1 (`early_plays`, also exposed as a bare
  int for the opening-hand verdict above). A creature slot appears when
  creatures are at least 35% of nonlands. Whatever's left of the 7 is
  "flex." This is the "3 lands, 2 plays at 1-3 mana, 1 creature, 1 flex"
  line the tab renders as chips.

`land_odds` is the exact hypergeometric distribution (`math.comb`, no
approximation) of lands in an opening 7, and `keep_rate` sums it over the
band above — "62% of your opening sevens land in the 2-4 land band."
`mulligan_record` is the deck's own empirical win rate at each mulligan
count, grouped straight from `games.self_mulligans` — no reconstruction of
the hand actually *shipped* (after bottoming cards under the London rule),
which stays genuinely absent from the log at every point, unlike the
pre-decision offer the opening-hand read above uses.

**Degrades to no band, not a wrong one.** `v_deck_land_count.unnamed_count`
(a maindeck card `sensei-top cards` has never named) means the land count
behind every ratio above may be an undercount — a land whose `type_line` was
never fetched can't be recognized as a land. Rather than publish a
plausible-looking "3 lands, 2 spells" built on a number that might be wrong,
`land_min`/`land_max`/`ideal_hand`/`land_odds` all come back empty, with a
note naming the gap and the fix (AGENTS.md rule 4: unknown means `null` plus
a warning, never a guess).

**`key_plays` and `mulligan_cost` are the deck's own play evidence, scoped
to its Arena identity.** Both reuse `guide/`'s existing machinery rather
than reimplementing it — `guide/deck.list_identities` groups every
content-hash `deck_id` this Arena deck has ever had into one `DeckIdentity`,
`guide/play.key_card_timing` buckets each of the identity's own key cards
(≥3 copies, ranked by finisher-ness then mana value) by the player-turn it
first resolved into "by T4" / "T5-6" / "T7-8" / "T9+" / "never resolved,"
and `guide/play.mulligan_record` splits win rate by kept-seven vs.
mulliganed. `key_plays` picks each key card's turn band with the best win
rate among those with at least 10 decided games, else among all bands —
a single lucky one-game spike in "by T4" never outranks a real 19-game sample in "T5-6" — and reports that band's
win-loss record alongside the "never resolved" record for contrast.
`mulligan_cost` pairs the kept-seven and mulliganed (any number)
`MulliganBucket`s directly. Both are gated on the same floor: at least 10 total decided games
for the identity, below which `key_plays` comes back empty and
`mulligan_cost` comes back `None` rather than publishing a split too thin to
mean anything — a note names the actual game count when this happens. On
the real Spellementals deck (283 decided games on file), this surfaces
Sunderflock at 40-20 in its best T5-6 window (72-89 when it never
resolves), Eddymurk Crab at 26-9 by T4, and a kept-seven/mulliganed gap wide
enough (57.9% vs. 44.6%, a 13.2-point gap) to engage the mulligan-cost brake
described above.

## The opponent-hand read (`table/hand_read.py`)

*"Given everything revealed so far, what's still live in their hand?"* —
Duke's *Thoughtseize You* run as a computation instead of in a player's head.

The one honest number behind it is Arena's own hand and library **counts**
(`live.hand`/`live.library` from the live replay above; falls back to
`turns.opp_hand`/`opp_library` when no live replay reached a real turn yet)
— never identities, which stay genuinely hidden unless something revealed
them. For each card in the field's consensus decklist for the opponent's
archetype in the match's own format (`review/consensus.py`, built from that
format's corpus decks since its latest reset), the expected copies still
unaccounted for is that archetype's average count minus whatever has already
turned up this game **anywhere** — a zone other than their hand
(`_seen_elsewhere`, deduplicated by `instance_id`) *and* anything already
confirmed sitting in their hand right now (`known_in_hand`): a card the tab
already shows as a fact has no business also appearing as a probabilistic
guess a few rows below it. The odds it's in hand right now is the
hypergeometric complement over `opp_hand` draws from `opp_hand +
opp_library`, run sequentially (`_prob_at_least_one`) rather than via a
binomial coefficient because the expected-copies figure is rarely a whole
number.

**Lands are filtered out before ever being ranked.** Neither the consensus
builder nor this read used to exclude them, and the result was exactly as
bad as it sounds: verified against the real corpus, URProwess's top-ranked
card by `share × copies` was a basic Island at 6.33 expected copies — ahead
of every real spell in the deck. A land is never a threat and never
something to hold up.

Cards split into **interaction** (tagged `spot_removal` / `sweeper` /
`counterspell`, or any instant) and **threats** (everything else), each
ranked by **expected copies left**, not raw probability — a 3-or-4-of and a
1-of used to cluster to similar-looking percentages once the opponent's
hidden pool got large, which read as noise. Interaction is capped at 5
(`_MAX_INTERACTION`, down from the 8 both lists used to share): the tab
leads with what's actually known and only shows a short, clearly-
speculative estimate below it — the frontend doesn't render `threats` at
all any more (see Frontend, below), though the field stays on the model.
`castable_now` marks an instant whose mana value fits the opponent's open
mana **plus** any known other mana sources (`open_mana + other_mana_sources`,
an upper bound — see the live replay section above) — `null` when either
side is unknown, never a guessed `false`. `grp_id` rides along on every
`HandCard` and `RevealedCard` (`ConsensusCard.grp_id`, or `MIN(grp_id)` off
a live replay's `zone_cards` or `v_turn_zones` for something actually seen)
so the tab can show a picture — `null` only when the name never matched a
`cards` row.

**Degrades in stages, never to a blank card:**

| `status` | When | What still renders |
|---|---|---|
| `format_unknown` | no format names the match (`v_match_format.format` is NULL); checked first, since the classifier never names an opponent in a match with no format and there is no corpus to read for it | the same observed facts as `unclassified` |
| `unclassified` | `v_match_opponent.opponent_key` isn't an `archetype:` key yet | hand size, hidden pool, open mana, held-turns streak, anything actually revealed |
| `no_consensus` | the archetype resolved, but `build_consensus` is below its `min_decks` gate | same observed facts as above |
| `ok` | a consensus exists | the observed facts, plus the ranked interaction list |

An `ok` result also carries the standing caveat: the card list
is the field's *typical* decklist for this archetype, not the opponent's
actual 60, which this reader never sees — the same sentence
`review/analyzers/frame.py` uses for its own opponent-side comparison.

`held_turns` (consecutive latest turns at the same hand size) is a real,
cheap signal worth having even with no per-card read at all: a hand that
hasn't shrunk in several turns is either flooding or sitting on reactive
cards. It still counts off the stored `turns` history regardless of whether
the "now" numbers above came from a live replay — history is history either
way, and only the freshest data point (the live hand size, when available)
feeds into where the streak starts counting from.

## The break read (`table/intermission.py`)

*"Game just ended — what do I board for the next one?"* — the one moment on
this tab where nothing is happening on the board at all, and the read that
takes over the whole tab while it lasts.

**How the break is detected.** `LiveState.intermission` (`projector/
live_state.py`) is set from the same live replay everything else on this
page uses — never a projected column. It opens on a `gameInfo` reading
`matchState: MatchState_GameComplete` and `matchWinCondition:
MatchWinCondition_Best2of3` (the concede path takes the same shape, with
`ResultReason_Concede` on the result), carrying which game just ended, who
won (`None` when either `winningTeamId` or our own team id is unresolved —
rule 4, never a guess) and why. It closes on either of two conditions,
checked in message order: a later `gameInfo.matchState` of
`MatchState_MatchComplete`, or a later `gameInfo` whose `gameNumber` is
greater than the game that opened the break.
`GREMessageType_SubmitDeckConfirmation` does **not** close it — see
`docs/arena-log.md`'s trap 11, pinned by `tests/test_intermission.py`'s
four fixture cut points. **This is fixture-verified only** — a real Bo3 break has not yet been observed live
against a running watcher.

**Why the opponent is classified at request time, not read from
`opponent_archetype`.** Measured on 392 real breaks: median length ~39 s,
80% end within 60 s (min 5 s, max 145 s — how long the user actually took,
not an Arena timer). Measured separately, a full projection round trip
reaches up to ~58 s at the default `--duty-factor 1.0` (`live.py`'s module
docstring). Those two numbers together mean the projected opponent name is
often still mid-game-1 by the time a break this short has already ended —
waiting on `project()` would show a stale or absent read for most of a
break's own lifetime. `table/intermission.py`'s `opponent_seen_names` pools
`card_events` (whatever `project()` has caught up to) with the live
replay's own revealed non-hand zones, and `_resolve_opponent` runs
`archetypes.classify.classify_seen` — `classify_matches`'s per-match rule
engine/corpus read, extracted so it can run on a request-time name set
instead of waiting for a `card_events` row to exist. `rank_candidates`
gained a `seen_names` parameter for the same reason, and
`live_opponent_colors` reimplements `v_opponent_cards`'s colour/count logic
directly in Python over a live name set — it counts **distinct card names**,
not `(name, rarity, colors)` groups the way the SQL view does, a documented
simplification (its own docstring) rather than an attempt to match the view
exactly.

**The live read is in the match's format.** `build_break_read` resolves it
once: `v_match_format.format` (the log's for an Arena match, the pick or the
inference for an MTGO one), falling back to `formats.py::arena_format` over
the deck's format and event id only for a database whose `matches.format`
(migration 055) is not projected yet. `classify_seen` reads that format's
rules, and the corpus prior is that format's too
(`archetypes/corpus.py::build_prior(conn, fmt)`, kept per format under
`caches["priors"]`). No format means no prior, never Standard's, and no
live read at all: `_resolve_opponent` returns `None` before classifying, so
only a manual pick still names the opponent. `IntermissionOut.fmt` carries
the format the read resolved, `null` when none, so the card can say why
there is no opponent read.

**`build_break_read`'s precedence.** A manual pick (`opponent_deck_override`)
always wins first, ahead of any live read — the user's own correction. Given
a named (or manually picked) archetype, the plan itself follows a free-tier
order: an **exact** stored `matchup_brief` for `(deck, archetype)`; failing
that, the **closest** already-written brief for a different archetype this
deck could plausibly be facing (`_closest_alternatives`, best `fit` first,
excluding the archetype actually named); this deck identity's own **past
boarding** the last time it faced this same archetype (`_past_boarding`,
measured against the past match's own game-1 maindeck, never a chained
diff); and, last, a **prompt** to write the exact plan from
(`brief.narrative.full_prompt`, the same call `/api/current-match/brief`
makes for the ordinary in-game brief). Past boarding is not a fourth linear
tier in the data itself — it is a supplementary field the frontend positions
differently depending on which of the other three fired (below the plan
when exact, above the "closest" warning when closest, or as the only
content alongside the prompt when neither exists). No identity for
the player's own deck: `plan` and `prompt` both come back `None`, and the UI
says so rather than rendering dead buttons (rule 4). No archetype named at
all (a game 1 conceded before a card was seen, or a match with no format):
`prompt` comes back `None`, but the alternatives still run, so the top one
can still show as a "closest" plan, and past boarding reads that same
alternative (`intermission.py`, step 5b). The
prompt is `full_prompt`'s, so it is `None` too when the player's own deck has
no format (`docs/brief.md`).

**Post-board record.** `postboard_record` (`{won, lost}`, or `None`) is this
deck identity's games 2 and 3 against the archetype the read named or the
user picked (`_postboard_record`): the same identity and exclusion as
`_past_boarding`, over every earlier finished match with
`matches.best_of = 3`, a drawn game counted in neither number. It reads only
the named or picked archetype, never the "closest" alternative that past
boarding falls back to: the card words it as a record against this
opponent's deck, which a guess at a different archetype is not. `None` when
no archetype is named or picked, when the identity is unknown, or when no
such earlier game exists. Bo1 matches stay out: their games are not
post-board games.

**Degradation.** Unknown opponent → no prompt, though a "closest" plan
from the alternatives may still show; no format → no
live read, so the same unless the user picked the opponent's deck; `stale`
flags a plan whose brief predates the current field or the current 75
(`brief.store.is_stale`) without withholding it — a stale plan is still the
best evidence available, just labelled as possibly out of date.

**Per-match memoization and cost.** `caches` is a plain dict the API layer
owns across polls: `definitions`/`colors_by_name`/`prior` (the classifier's
own slow loads, shared with the rest of the archetype-naming machinery) plus,
per match, the brief `prompts`, `past_boarding` and `postboard_record`
results — all keyed to include the match id, since nothing that feeds any of
them can change while *this* match is still being played (only past,
completed matches and the corpus do). Measured on the real database: a cold
`build_break_read` costs ~2.0 s, almost all of it `full_prompt` (~1.05 s:
`format_resets` ~0.75 s, the personal matchup-rate read ~0.27 s) plus
`_past_boarding` (~0.27 s). Memoized, a reprojection mid-break (the watcher still rebuilds on every
match-boundary event) now costs ~70 ms instead of paying that ~2 s again,
and an ordinary cache hit costs ~3 ms; only the first poll of a match's
first break ever pays the full ~2 s. `api/sql.py`'s `_cached_break_read`
owns the cache key (see Wiring, below).

**Frontend.** `SideboardPlanCard` renders the headline ("Lost game 1
(concede)"), the plan itself (`BoardPlan`/`PlayAroundList`, reused from
`MatchupBriefCard` rather than forked), past boarding, and — when there is
no plan at all — a `CopyPromptCard` carrying the prompt and the exact `brief
--import` command to paste the answer back through. With neither a plan nor
a prompt it says why instead: a match whose `fmt` is `null` gets its own
sentence ("No tournament format is known for this match, so the opponent's
deck can't be named from the cards seen, and there is no plan to show."),
distinct from the unnamed-opponent one. The opponent is the status strip's
during the break, as at every other phase: its name, its chip (the
confidence, or "picked" for a manual pick) and the cards seen come from
`intermission.opponent` and `intermission.cards_seen`, the live read, not
from the projected match, which can trail it. `SideboardOpponentRail` holds
only the other archetypes with a written plan, each expandable to its own
full board; with none it is not drawn, and the plan card takes the full
width. The plan card's title is the result and its reason alone ("Lost game
1 (concede)"), since the strip already says which game is next and against
what. Under the title, one line gives this deck's own games 2 and 3 against
the opponent's deck, from `intermission.postboard_record`: "Your games 2–3
against it: 58% · 35–25" from ten games won or lost, the record alone under
ten, and no line when the record is null or every earlier game 2 or 3 was a
draw. In `CurrentMatchView.tsx`, the break phase takes precedence over every
other phase — including a pending mulligan decision, which cannot actually
co-occur with a break since the next game's opening hand doesn't exist until
sideboarding ends — and `MatchStatusStrip` renders `"Sideboarding, game N
next"` in place of the ordinary game/turn phase phrase.

## The event rule (`table/queues.py`)

During a game in an event the Live page shows what every tracker shows, and
no advice. In casual queues and on the ranked ladder it shows everything,
unless the user turned advice off in Settings.

| | game in an event | casual or ladder game, or between games |
|---|---|---|
| remaining library and its draw odds | shown | shown |
| the opponent's revealed cards, hand size, open mana | shown | shown |
| the archetype read (`OpponentRead`) | shown | shown |
| the opening hand's verdict and evidence (`OpeningHandCard`) | hidden | shown |
| the keep guide (`KeepGuideCard`) | hidden | shown |
| "Could be holding" and its caveat (`OpponentHandCard`) | hidden | shown |
| the matchup brief (the disclosure bar) | hidden | shown |
| the sideboard plan (the break) | — | shown in every queue |

**Why the line sits there.** Magic's digital tournament documents are
where a rule could reach a tracker, and they cover tournaments, not the
ladder:

- The [Digital Tournament Rules](https://blogs.magicjudges.org/rules/dtr/)
  let a player "take written notes during a match and may refer to those
  notes" ([2.10](https://blogs.magicjudges.org/rules/dtr/2-10/); a LAN event
  may restrict them). The sideboard plan read between games is that.
- The [Digital Infraction Procedure Guide, 2.2 Outside
  Assistance](https://blogs.magicjudges.org/rules/dipg/2-2/), allows "Deck
  Tracking software … as long as they do not provide any Private
  Information" in online events, and forbids software that shows what the
  game client can't. Every read on this page is derived from what the
  client shows. But its philosophy also says "any strategy advice, play
  advice, or construction advice from an external source is considered
  outside assistance". The sentence speaks of people, and a keep verdict is
  not one; a judge could still read it as one, so an event's game gets no
  advice.
- The ladder is not a tournament: neither document reaches it. What does,
  [Wizards' Terms](https://company.wizards.com/en/legal/terms) §2.2, treats
  every third-party tool alike, whatever it shows.
- The terms of Arena's own events (the
  [Arena Open](https://magic.wizards.com/en/news/mtg-arena/arena-open-terms-and-conditions),
  [Arena Direct](https://magic.wizards.com/en/news/mtg-arena/arena-direct-terms-and-conditions)
  and the [Qualifiers](https://magic.gg/events/qualifier-play-in#rulesandpolicies))
  have no clause on trackers, notes or advice; they forbid cheating and
  modifying the client, and incorporate a Wizards Play Policy that could
  not be fetched (2026-10-19) and is unread.

Both rules documents are read from the judges' copies, effective June
2020; no newer version was found (2026-10-19).

**Advice means a short allowlist of casual and ladder queues.**
`ADVICE_QUEUES` holds `Play`, `Constructed_BestOf3`, `AIBotMatch`,
`DualColorPrecons`, `Ladder` and `Traditional_Ladder`, each read off a real
database's `matches.event_id`. Any other id is an event:
`Traditional_Cons_Event_*`, every draft, every Arena Open, Direct and
Qualifier. So is a missing one (rule 4), which covers MTGO too: its matches
carry no event id, and its leagues and challenges are what the rule is for.
`DirectGame` is an event on purpose (the user's decision, 2026-10-01):
community tournaments on Arena are played by Direct Challenge, and the log
can't tell one from a game with a friend. A queue missing from the list
costs only the advice in that queue until it is added.

**The user's switch.** Settings' Live section has "Advice during a game",
on by default. It is the browser's own (`web/src/shell/liveAdvice.ts`,
`localStorage`, like the density control), since the API writes only
authored artifacts (non-negotiable #6), and it can only hide more: off,
every queue looks like an event's game, and the break still shows its
sideboard plan. The server never sees it.

**The queue comes from the live replay first.** `LiveState.event_id` is
read from the room-start event that anchors the replay
(`reservedPlayers[].eventId`, the path `projector/matches.py` reads for
`matches.event_id`), so the rule holds at the first mulligan of a match,
before `project()` has written its row. The projected `event_id` is the
fallback when the replay found none. `GET /api/current-match/read` returns
`advice` (the queue allows it, or a break is in progress), and the
dashboard obeys it without deriving it again, then ands it with the switch.
The server still builds every read: the rule decides what the page draws,
and the route stays one shape in every queue.

`web/src/lib/livePanels.ts` is the table of which panels each phase draws,
with and without advice; `livePanels.test.ts` pins that no advice panel
appears in any phase without it.

Until this change (2026-10-19) the rule was the ranked-play rule, and
this module was named for it: the ladder counted as ranked and showed no advice
either, on the reading that real-time coaching in ranked play was a line no
tracker crossed. Read against the documents above, that line is the
tournaments', and the ladder is not one. The read also returned `ranked`,
which only fed the strip's "ranked, advice off" and is gone.

## Wiring: one route

`GET /api/current-match/read` returns the opening-hand read, keep guide,
opponent-hand read and our own remaining library
(`OpeningHandOut`/`KeepGuideOut`/`HandReadOut`/`LibraryCardOut[]`) in a
single `CurrentMatchRead`. They share the same current match and one live
replay (see above), and the tab rides its own unconditional 1s timer while
mounted — several round trips per beat for one screen would be waste that
one isn't, and a fast replay makes an unconditional 1s poll affordable in a
way it wasn't when the same timer had to wait on `project()`.

`opening_hand` is built *before* the `v_current_match` lookup and returned
even when that lookup finds nothing, per its own section above. Everything
else still gates on a match row exactly as it always did.

`build_consensus` scans `meta_deck` and parses JSON per archetype; at a
heartbeat cadence that cost would be constant while a game runs.
`api/sql.py`'s `_cached_consensus(request, conn, opponent_key, fmt)` keeps
one consensus on `app.state`, keyed on `(archetype_key, fmt, corpus token,
window)`: the consensus is the match's format's, built from that format's
corpus decks since its latest reset (`_cached_consensus_window`, cached per
`(token, fmt)`), and a match with no format has none. A `sensei-top meta`
refresh moves the token and invalidates it for free, and nothing else needs
to.

The opponent-identity lookup gets the same treatment for the same reason:
`v_match_opponent`'s `WHERE match_id = ?` can't push down into the view's
`v_opponent_cards` CTE, so reading it for one match costs the same as
scanning every match's opponent-card history — measured 27ms per request
regardless of how many matches that filter actually matched. `api/sql.py`'s
`_cached_match_opponent` caches that row on `app.state`, keyed on
`(match_id, projection_state.projections)` — a rebuild is the only thing
that can change what the view says about this match's opponent (nothing on
this route reads `raw_events`/`card_events` directly), and that counter is a
single-row read that moves exactly when a rebuild commits. It replaced an
earlier token, `COUNT(*) FROM card_events`, which cost more per call
(65-82ms, paid on every hit, not just a miss) than the 27ms it was
protecting. `/api/current-match` and `/api/current-match/brief` share the
same cache.

`api/sql.py`'s `_cached_mana_source_grp_ids` gets the same treatment for
`table/live.py`'s `_mana_source_grp_ids` — a full `cards` scan (5.4ms) that
only changes on a `cards` refresh, keyed on `cards`' own row count, the same
pattern `_cached_consensus` above uses.

`api/sql.py`'s `_cached_break_read` follows the same on-`app.state` pattern
for the break read above, but with a wider key: `match_id`, `deck_id`, the
game number the break follows, the `frozenset` of opponent names revealed so
far (a zone reveal since the last poll invalidates it the same way a new
`card_events` row does), `opponent_deck_override` and `matchup_brief`'s own
row count and freshest timestamp (a manual pick or an imported brief is
exactly what the user does *during* a break, and neither moves a projection
token), the projection token, and a second reference token (the corpus
fetch, `meta_deck_archetype`'s classification stamp, and the `archetypes`/
`cards` row counts) that also gates a second, longer-lived dict —
`break_classify_caches` — holding the slower `definitions`/`colors_by_name`/
`prior`/prompt/past-boarding loads `build_break_read` itself memoizes (see
above). A cache miss still costs the full read; a hit is a dictionary
lookup on top of the live replay the caller already paid for.

**Recent field was removed.** The tab used to carry a fifth read — this
deck's last few completed matches, opponent-first — as a rail card
(`table/history.py`, `RecentOpponentsCard.tsx`). It answered "what has this
deck actually been facing lately", a real question, but not one worth a
permanent slot on a screen meant to answer "what do I do on my turn right
now": a match's own opponent history is a research question, not a live
read, and the tab's real estate went to the remaining-library panel
instead. The code was deleted outright rather than hidden, since nothing
else consumed it.

## A second source: MTGO

MTGO is ingested and projected exactly as before — `Match_GameLog_<guid>.dat`
still lands in `raw_events`, still projects into `matches`/`games` (never
`turns`; see below), and an MTGO match still shows up in History and
Matchups automatically, no manual step required. What changed
(`migrations/040_arena_only_current_match.sql`) is that `v_current_match` is
now Arena-only: an MTGO match can never become "the match in progress" on
*this* tab, no matter how recently it started or how genuinely live it is.

The reason full support was never viable is structural, not a missing
feature. MTGO writes a transcript (`Match_GameLog_<guid>.dat`), not a
board-state protocol — there is no GRE, no `LiveState`, no per-object zone
tracking. Every read on this tab is downstream of `LiveState`/GRE in one way
or another, so almost the whole tab would have been structurally
unavailable for an MTGO match, not just unimplemented:

- **`OpeningHandCard`, `KeepGuideCard` (with live odds), `LibraryCard`,
  `OpponentHandCard`** all need either a `deck_id` (Arena's client tells us
  our own decklist; MTGO's transcript never does — only a separate `.dek`
  file would, and nothing here reads one) or a live zone-by-zone replay
  (`turns`, which MTGO never populates — see `table/live.py`).
- **`OpponentRead`** was the one panel that would have survived close to
  fully intact: it works off revealed opponent cards, which MTGO's
  transcript does supply (bracketed card names in every relevant line — see
  `projector/mtgo/parse.py`). An MTGO match would have shown, at best, an
  opponent-archetype read plus the disclosure bar and nothing else — not
  worth the added measured latency (`docs/architecture.md`'s duty-cycle
  note) it was costing the Arena tab to keep MTGO eligible for a spot it
  could barely fill.

Since the tab is Arena-only now, there is no more source badge on the status
strip either — it used to read "MTGO" instead of "Arena" whenever
`CurrentMatch.source == 'mtgo'`; with `source` always `'arena'` on this tab
(`api/models/current_match.py`), a badge that never varies has nothing to
say, so it was removed along with the branch that rendered it
(`CurrentMatchView.tsx`).

**`started_at` means "first raw event seen," not "first turn started," for
both sources — but what that first event *is* differs.** For Arena it is the
first parsed line of a `MatchGameRoomStateChangedEvent` for this match id.
For MTGO there is no equivalent structured start marker; `started_at` is the
first raw_events row's `logged_at` for that match's `source_file` — i.e. the
first moment this tracker's own file watcher saw *any* line, not a
client-reported match-start instant. This distinction still matters for
History/Matchups queries that compare `started_at` across sources — see "Who
owns which table" in `docs/architecture.md` and the 036/037 migration
history it links to — even though `v_current_match` itself no longer needs
to reconcile the two.

**The most-recently-active rule, and the cross-source race it used to lose.**
Before migration 040, `v_current_match` picked the incomplete match with the
newest `started_at` across *both* sources — "whichever game you most
recently began is the one the tab shows," regardless of which client was
running it. The failure case: an MTGO match still live at 14:00 while an
Arena match both starts *and finishes* at 14:30. `MAX(started_at)` picked
the just-completed Arena match (nothing in the query knew it had already
ended), so the outer `WHERE result='incomplete'` then rejected it — the tab
showed *no* match, not the wrong one, until the MTGO match's own
`started_at` became the max again. Filtering `v_current_match` to
`source='arena'` in both the outer `WHERE` *and* the inner `MAX` subquery
(migration 040's actual change — an MTGO row could otherwise still hold the
global max and blank an in-progress Arena match's own tie, which is a
distinct failure from the one above and just as real) removes MTGO from
either side of the comparison entirely, so this specific race is moot: only
Arena matches ever compete for the tab now. A same-source version — two
Arena matches racing, one finishing just as another starts — remains
theoretically possible, but Arena itself only runs one match room at a time,
so it isn't a practical concern the way the cross-source case was.

**MTGO's turn numbering is per player, not per game.** Arena's `turns` table
numbers turns globally within a game (turn 1, 2, 3, ... regardless of whose
turn it is); MTGO's transcript numbers each player's own turns independently
(the transcript says "your turn 3" and "opponent's turn 3" as distinct
counters). `table/live.py` never has to reconcile the two schemes because it
never runs for an MTGO match at all — `turns` stays structurally empty for
MTGO, full stop, not just empty for this one reason, and (since migration
040) not just because MTGO never reaches this tab either. Anyone tempted to
wire a partial live replay for MTGO later needs to solve this numbering
mismatch first.

## Frontend

**Focus mode.** From 48rem up this page (`/live`) is capped at the
window's height instead of letting the page scroll — see
`docs/frontend.md`'s "Focus mode".
The base render is meant to fit a second monitor with nothing scrolled: a
one-line status strip, a two-column grid (a primary read and a rail, split 60/40),
and a disclosure bar holding the matchup brief, a `Disclosure` that
opens over the page and scrolls inside itself. The match's facts are
the status strip's alone, so the bar repeats none of them, and without
advice it is not drawn, since the brief is advice. Under 48rem there is no
cap: the page scrolls, and the strip takes two lines
("The status strip", below).

**Four phases**, driven by `read.data?.intermission`,
`read.data?.opening_hand` and `turns.length === 0`, never by a separate mode
flag. The break phase is checked first and, when present, pre-empts every
other row below it — there is no board to show and no keep guide to run
until the next game's opening hand exists:

| phase | primary | rail |
|---|---|---|
| between games (Bo3 break) | `SideboardPlanCard` — headline, board plan or prompt, past boarding | `SideboardOpponentRail` — the other archetypes with a written plan; not drawn when there are none, and the plan card takes the full width |
| a decision is pending | `OpeningHandCard` — the real 7 as images, verdict headline, evidence | `KeepGuideCard` (full) |
| mulligan phase, no offer yet | `KeepGuideCard` (full) | `OpponentRead` |
| game under way | `LibraryCard` — our own remaining deck, by mana value, no card cap | `OpponentHandCard`, `OpponentRead` (dense) |

Without advice (an event's game or the switch off, "The event rule" above) a pending
decision and the mulligan phase both draw `LibraryCard` with `OpponentRead`
in the rail, and a game under way draws `LibraryCard` with
`OpponentHandCard` (facts only, `estimate={false}`) and `OpponentRead`
(dense). Once a game is under way the keep guide is gone in every queue:
it has said what it had to, and the rail is the opponent's. The status
strip adds "event, advice off" or "advice off in Settings", so a missing
keep guide before the first turn never reads as a broken one. Before any
match row exists, such a game's pending decision shows an "Event game" or
"Advice off" empty state instead of the opening hand. The rows above come from `lib/livePanels.ts`.

A decision can be pending even before `current.data` (`/api/current-match`)
exists at all — `opening_hand` does not wait on a projected match row — so
`CurrentMatchView` renders a minimal status-strip-plus-`OpeningHandCard`
layout for that window rather than falling through to the "no match in
progress" empty state.

**What is known about a card is written under it.** Both hands draw
their cards as `CardTile` (`docs/frontend.md`'s "Card images"), and
a line under each row says once what its captions mean. Nothing is
drawn on a card's picture, and no `title` carries a sentence.

| where | caption |
|---|---|
| opening hand, a spell | `Turn 3`: `castable_turn` |
| opening hand, a spell whose `reduced_castable_turn` is sooner than its `castable_turn`, or is the only one of the two | `Turn 2, reduced` |
| opening hand, a spell with neither | `No turn` |
| opening hand, a land | none; the caption's space stays, so the pictures keep one line |
| "Could be holding" | the chance the card is in their hand, then the chip `Now` when `castable_now` |
| either hand, `tags_known` false | a second line, muted: `Text unknown` |

The line under the opening hand says that the turn is the earliest
this hand's own lands cast the card, and is there when at least one
card is not a land; a second sentence says what "reduced" counts, when
a card says it. The line under "Could be holding" says that the
number is the chance the card is in their hand, and what `Now` marks
when a card carries it. `castable_now` of `null` draws no chip, as
`false` does: the caption never says an instant is out of reach.

**`LibraryCard` is the primary panel once a game is under way.** It
replaced `NextDrawsCard`, which lived in a disclosure and capped its list at
8 rows — a limit sized for a demoted, secondary card, not for the one thing
every competing MTG Arena tracker leads with (your own deck, remaining,
always visible). No card cap: the fresh live replay behind it costs the
same either way, unlike the old client-side subtraction against a stale
`turns` row.

The card is the decklist and nothing else. A strip on top answers
the lands: how many are left out of the deck's land count (the land
rows' summed quantity), then the chance of at least one on the next
draw, within two draws and within three. Under it, one table: the
cost (its header, "Cost", is for a screen reader; the pips say it),
Card, Left and "Next draw", the chance the very next card is a copy.
The header is the whole explanation, so there is no footnote. Rows are
grouped by mana value; the cost is drawn as pips (`ManaCost`,
`docs/design-system.md`'s "Mana pips"), each row's copies left out of
its quantity beside it. The lands strip, the grouping and every
chance are `lib/library.ts`.

Within a group the rows sort by copies left, most first, so the
likeliest draw of each cost leads it, with the name as tie-break. A
card with none left stays, dimmed, at the bottom of its group: the
group does not lose a row mid-game, and a player looking for a card
finds it gone rather than missing. The name column truncates rather
than wrapping, and the header stays put while the list scrolls inside
the card.

Until 1.0.1 a band of three tiles sat above the list: land odds,
interaction odds and a flood or screw comparison, with a footnote
under them. Together they moved from the next draw to the next three
and back, and gave the land chance in more than one form. Feedback on
the 1.0.1 announcement named this card first when it called the
dashboard's information randomly spread, so the card then asked one
question, three draws ahead, and answered it on every row. The API's
`is_interaction` stays, though no dashboard component reads it.

Until this change every row carried that three-draw chance, the lands
were a row like the others, rows sorted by name within a group, and a
card with no copies left dropped out of the list. Three draws ahead on
every row put a percentage everywhere that read the same at a glance;
the next draw is the number every other tracker shows per card, so it
is the one a row carries now, and the lands, the one count a player
plans around, get the three horizons in a strip of their own. Sorting
by name kept a row's place fixed as the game evolved; sorting by copies
left reshuffles a group only when a draw changes its order, and puts the
answer to "what am I likely to draw at this cost" first.

**`OpponentHandCard` leads with facts, then demotes the estimate.** Order
is hand size / open mana (plus any widened "+N other" sources) / held
turns, then "Revealed in hand" and "Shown so far" (both facts — cards Arena
has actually shown), and only then a short "Could be holding" list
(interaction only, capped at 5). The list is not dimmed, since that
would dim the cards' pictures. Its place, last, and its label say it
is an estimate, and the server's caveat, drawn under it, says the
cards are the field's typical list and not their real 60; the label
does not say it a second time. The old "Still in their deck"
list — a full-deck-minus-seen guess at cards not even confirmed in hand —
is gone from the UI entirely: it was the least trustworthy number on the
tab, and half of it used to be the opponent's own basic lands.

`OpponentHandCard`'s subtitle says how many times the opponent
mulliganed, when they did, and "Shown so far" is a row of small chips.

`OpponentRead` takes a `dense` prop rather than forking into a second
component: dense, it puts the candidate shortlist behind a `Disclosure`.
With no shortlist and no unnamed-deck detail to show it draws nothing,
rather than an empty card titled "Opponent deck". "Pick this deck"
(`PickDeckButton`) is not on the card: it sits in the status strip,
after the opponent's name it corrects, so it is there whenever a match
is current, whether or not the card is drawn; its `DeckPicker`
popover is `fixed`-positioned and never clips inside the strip. The
strip's confidence reads "picked" once the user has picked. During the
break the button is not drawn, since the sideboard plan has its own
picker.

Until this change the keep guide stayed in the rail once a game was
under way, in a dense form without its land-odds bars or mulligan
record, and "Pick this deck" lived on the opponent-deck card, which was
therefore drawn, often empty, from the first turn.

**The status strip** holds the game and the turn as large numerals,
the facts joined by `·` (the games won and lost in the match, on the
play or on the draw, the phase when there is more to say than the
turn, the opponent's cards seen, how long ago the match was first
seen), and the opponent's identity: pips, name, confidence. From
48rem up it is one line, and the facts are cut to fit it. Under 48rem
it is two: game, turn, pips and confidence on the first; the
opponent's name and then the facts on the second, wrapping, none cut.
While sideboarding the phase reads "Sideboarding, game 2 next", and the
opponent's identity and cards seen come from the break read
("The break read", above), so they agree with the plan card beside
them.

**The status strip flags a likely-abandoned match.** `v_current_match`
stays current until the next match begins even if the current one never
received a `MatchCompleted` event (a crash, or Arena killed mid-game) — see
`migrations/003_current_match.sql`. Past 90 minutes since `started_at`
(`LIKELY_ABANDONED_MINUTES`), the strip says so and the live dot stops
pulsing, rather than looking indefinitely live under a green dot the way it
used to. This is always the current match's own `started_at` — "first raw
event seen for this match" per source, as described above — never a
cross-source `last_event_at` (which doesn't exist yet): for an MTGO match
that means 90 minutes since this tracker's file watcher first saw a line for
that game log, not 90 minutes since MTGO itself reports the match began.
