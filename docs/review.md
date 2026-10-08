# The match report

Read this when touching `review/`, or deciding whether a new signal belongs
in the per-match report versus the leak finder.

**Scope note.** This document covers the per-match postmortem and the
cross-match leak finder — what used to be the whole Review tab. The tab
itself is now the deck guide (`docs/guide.md`, `guide/`), which uses this
package's `build_match_report`/`find_leaks`/`build_consensus` as building
blocks rather than duplicating them; the per-match report still lives on the
match drill-down (`MatchReportPanel`), reachable from a leak's own match
chips exactly as before.

## Why this exists

The report used to measure land drops, mana flood/screw and unspent mana —
log bookkeeping a tracker can compute easily, but not what a serious player
actually reviews a game for. It was rebuilt on the game's own strategy
canon: Mike Flores' role assignment, Reid Duke's Level One course (damage
racing, tempo vs. card advantage, playing from ahead/behind), Duke's
*Thoughtseize You*, and the Lichess idea of naming the move — here, the turn
— that actually decided a game. Land and mana findings were not deleted for
being wrong; they moved to the leak finder, where a *rate* across many games
is the real signal Duke's own review method asks for ("was it a fluke, or a
deck problem?"), not a single game's flood.

## What became possible, and why

Three things changed to make this report about the actual game rather than
its bookkeeping:

1. **Combat is projected.** `migrations/014_combat.sql` and
   `projector/combat.py` turn `gameObjects[].attackState`/`blockState` and
   `AnnotationType_DamageDealt`/`ModifiedLife` into `combat_attacks`,
   `combat_blocks`, `damage_events` and `life_events` — verified against a
   real capture (`tests/fixtures/combat_session.log`; see that migration's
   comments for the traps found along the way: Arena reuses an annotation's
   `id` across different annotation types within one game, and re-broadcasts
   the same attack assertion across several messages).
2. **The metagame corpus has complete decklists.** `meta_deck` stores every
   card of every stored tournament decklist, not a handful of revealed
   cards — `review/consensus.py` aggregates it per archetype into a
   "consensus list": which cards are staples, at what share, tagged with
   effect classes (`review/effects.py`) from Scryfall's own `oracle_text`
   (`migrations/015_card_text.sql`). `build_consensus` defaults to the
   maindeck (`board="main"`, every caller before `guide/` ever needed —
   role assignment reads an opponent's likely maindeck, never their
   sideboard) and optionally narrows by `since`/`min_wins`/`tiers`, added
   for `guide/`'s "consensus among winning post-reset lists" question.
   **`fmt` is required**: only decks from that format's events count,
   because one archetype key can name lists in more than one format's
   corpus, and `fmt=None` (a match or deck with no format) has no
   consensus rather than an all-format one. A match report reads its
   match's own `v_match_format.format`.
   **`since` is not optional in practice**: a consensus aggregated across a
   format reset describes a field that no longer exists, and will name cards
   that are now banned — which is how a match report came to claim an
   opponent's usual staples never showed up and point at a banned card.
   `review/` cannot compute the window itself (`guide/window.py` sits above
   it), so `build_snapshot` and `build_match_report` take a
   `consensus_since` their callers pass down, and `find_leaks` takes either
   that or a per-format resolver, `consensus_window` (below); the consensus
   and field-record cache keys carry both the format and the window. An
   archetype without five post-reset decklists in its format now has no
   consensus rather than a stale one, and the findings that need one simply
   don't appear. Card names are canonicalised on `cards.oracle_id` where
   every name being merged has one on file
   (`migrations/017_card_legality.sql`) — the fix for one card counted under
   two Universes Beyond printings, and it also now matches an adventure,
   split or double-faced card recorded by one face alone against Arena's own
   combined name for the same card, through `archetypes.classify.normalize`,
   which accepts either face. A corpus decklist names the front face; MTGO's
   game log names the face that was played, which can be the back, and the
   MTGO projector resolves either to the combined row
   (`docs/architecture.md`).
3. **The player's own deck can be classified.** `archetypes.classify`'s
   `complete=True` path already existed for corpus decklists
   (`metagame.classify_meta`); `snapshot.py`'s `_classify_own_deck` runs the
   same engine over the player's own complete decklist
   (`decks.cards_json`) — something no analyzer did before, because nothing
   needed the player's *own* archetype key until role assignment did.

## The analyzers, one per module in `review/analyzers/`

Each is a pure function of one `MatchSnapshot` (`review/snapshot.py`, the
only module that touches `sqlite3`). The registry order in
`analyzers/__init__.py` is the order a postmortem actually reads in.

### `frame.py` — the matchup, and the role it demands

Flores' *Who's the Beatdown?*: "Misassignment of Role = Game Loss." Three
signals, applied as votes: more creatures usually means beatdown; more
removal usually means control; more card draw and counterspells "almost
always" means control (weighted double). The player's own side reads their
*exact* decklist (`snap.own_cards`); the opponent's side reads the field's
consensus list for their archetype (`snap.opp_consensus`) weighted by share
— the best substitute for a decklist this reader never sees in full. Either
side unclassified is a gap, never a guessed role.

The creature vote needs the opponent's side to know which consensus cards
are actually creatures — `ConsensusCard.type_line`, read from the same
`cards` row `build_consensus` already fetches, is what makes that a real
computation rather than a fixed zero. Before it existed, the opponent's
creature rate could only ever read as `0.0`, so "more creatures ⇒ beatdown"
could only ever vote beatdown regardless of what the field actually played —
`test_role_assignment_can_read_control_from_a_creature_heavy_field`
(`tests/test_review.py`) pins this down as a regression test. A consensus
that resolves but carries no signal at all — every rate at zero, a corpus
tagging gap rather than a real absence of removal or card draw — is its own
gap rather than a role read from nothing.

Also carries the neutral game-start facts that used to live in a separate
`opening` analyzer — mulligan count and on-play/on-draw — since AGENTS.md's
own testing invariant (`test_the_report_never_judges_a_mulligan`) requires
they survive: this is a post-game read over projected data, and the hand a
player actually shipped — after bottoming cards under the London rule — is
never in the log at any point, so nothing here states a mulligan was right
or wrong. (`table/opening_hand.py` reads a different, earlier message live,
for the Live page — see `docs/current-match.md` — which is why this
still holds true for a *finished* game without contradicting that.)

### `clock.py` — the damage race

Duke's *Damage Racing* and Flores' *Philosophy of Fire*: cards for life, not
cards for cards. Sums `damage_events` dealt *to a player* (creature-vs-
creature combat is excluded — it doesn't move either player closer to
winning the race) per game, and reports who was ahead and by how much. A
margin of 10+ damage is `DECISIVE`; anything smaller is a `NOTICE`. Below
`MIN_DAMAGE_FOR_A_RACE` (6 total), the game reports a gap instead — a single
early hit is not a race yet.

Leading and trailing a race are two separate codes, `race_ahead` and
`race_behind` — not one `race_leader` code with a variable subject, which
used to read "The opponent were ahead in the damage race" (a grammar bug a
fixed subject removes) and, more to the point, could never become a leak
pattern on its own: whichever side you're on changes what the finding
*means*, so the leak finder needs two ranked patterns here, not one.

### `trajectory.py` — the shape of the whole game

The position index (`review/position.py`) turn by turn, and the turning
point: the largest single-step drop across turns this reader actually
recorded (a drop spanning a gap is real information, not something to
skip). Attribution — an opponent spell that resolved in that window, or
damage taken — is named as *what was observed*, never asserted as sole
cause. See `position.py`'s own docstring for the index's measured real-data
separation (weak at turn 6, strong by a game's last turn — reported
honestly, not tuned toward).

The `DECISIVE` threshold (a drop of 0.30+) and the words for a swing
("a small swing" / "a notable swing" / "a decisive swing") both live in
`position.py` as `SWING_DECISIVE`/`SWING_NOTABLE`/`swing_words()` — not
duplicated here and again in the summary layer below, so the number that
decides severity and the word a reader sees can never drift apart.

### `role_play.py` — was the assigned role actually played

Two literal checks, not a general "good play" model: a beatdown deck
holding a board-power lead without dealing damage that turn
(`beatdown_held_back`), and a control deck that never once held a card-
advantage lead the whole game (`control_never_ahead_on_cards`). Re-derives
`frame.py`'s role from the same inputs rather than depending on its output —
every analyzer stays a pure function of one snapshot, not of another
analyzer's result.

### `information.py` — what was still live

Duke's *Thoughtseize You*: the opponent's consensus staples (share ≥ 50%)
minus what they actually revealed this match is a real, checkable list of
"cards they could still have had." When a sweeper-tagged staple is on that
list and the player's own board peaked at 4+ permanents, that is named as a
real risk taken — never as "they had it," since this reader cannot see a
hand.

### `resources.py` — the trade

Card-advantage swing per game (hand-size differential, high and low point);
cards stranded in hand at the last recorded turn of a loss; `Countered`
zone transfers for both sides (`card_events.category = 'Countered'`,
projected since day one, read by no analyzer until this one). Duke's
*Tempo & Card Advantage*: a spell that never resolves is a card lost with
nothing gained, on whichever side it lands.

### `baseline.py` — this game against a wider sample

Reid Duke's own review method: "have you lost enough games in this same way
to reveal a fatal flaw?" A single match's own record in this exact matchup
(`personal_matchup`, excluding the match being reported on) and the field's
real-tournament win rate for the archetype pairing in the match's own
format (`field_matchup`, `metagame/matchup.py::ranked_field_matchup(...,
fmt=)`, walking the ranked tiers A, then B, then D for the first with at
least five matches for the pairing and naming the tier it lands on — see
`docs/metagame.md`; a match with no format has no field record at all,
never an all-format one),
both sample-gated
(`MIN_PERSONAL_SAMPLE`/`MIN_FIELD_SAMPLE`). Also carries the neutral
outcome facts that used to live in a separate `clock` analyzer under the
old naming — game length vs. this deck's own average, timeout/concede, and
the play/draw split — since "compared to a wider sample" is exactly what
those are.

`field_matchup` never pools a round from before a detected format reset into
one from after it: `build_snapshot` windows the `v_meta_matchup` query to
the `consensus_since` its caller computed, `_consensus_window(conn, fmt)`
for the match's own format from the match routes (`api/sql.py`, the same
cutoff `docs/metagame.md`'s "Every field number that can pool across the
boundary, doesn't" describes) and records the cutoff it used on the snapshot
itself (`MatchSnapshot.field_since`). When every round for this pairing
predates the cutoff, `field_matchup` is `None` rather than falling back to
the unwindowed number, and `baseline.py`'s gap/finding text names the window
it looked in (`"...since 2026-08-11"`) rather than staying silent about why
the field record is missing.

## The match summary (`review/summary.py`)

A pure function of an already-built `MatchReport` — no `sqlite3`, so it
costs nothing beyond what `build_match_report` already paid for. It selects
and phrases what the analyzers found; it measures nothing new. The per-match
panel used to render every finding as its own card, grouped into seven
category sections that each interleaved every game — a 3-game match landed
as roughly seventeen cards of near-equal visual weight, with a player's own
account of what happened (mulligans, play/draw, hand size) scattered across
the same seven sections it already sits below as stat tiles. `MatchSummary`
gives that a shape a player actually replays a match in:

* **`headline`/`subhead`** — the match's own score and opponent, plus one
  optional sentence, only when a stated condition holds over the report's
  own findings (leading the damage race in every game and still losing some
  of them; a lone `DECISIVE` finding's own already-audited title, reused
  verbatim). Nothing is written to fill an empty slot — `subhead` is `None`
  far more often than not.
* **`matchup`** — the whole-match findings (`game_number is None`: role
  assignment, still-live staples, the personal and field matchup records,
  the play/draw split), compacted to one line each.
* **`games`** — one `GameLine` per game, carrying the bookkeeping that used
  to duplicate the drill-down's own stat tiles (result, why it ended, length,
  play/draw, mulligans) plus up to three `Beat`s: the race (with a two-sided
  meter, not just two numbers), the turning point (worded via
  `position.swing_words`), a stranded hand, a role-play miss, an
  over-committed board. A `Beat`'s own text and evidence always trace back to
  its source `Finding`'s own `Evidence` or anchor — the same rule
  `findings.py` states for a single finding, extended here to a summary
  built from many (`test_summary.py`'s own traceability audit).
* **`gap_groups`** — the report's own `Gap`s collapsed onto their real root
  cause. Four analyzers independently blocked by the same absence (the
  opponent's deck never resolving to a known archetype) used to render as
  four separate paragraphs; `Gap.cause` (`findings.py`) is a stable slug an
  analyzer sets when it knows *why* it has nothing to say, and
  `summary.py`'s own small, closed set of headings
  (`opponent_unclassified`, `own_unclassified`, `small_sample`,
  `consensus_unavailable`) groups every gap that shares one. A gap with no
  recognized cause still renders exactly as it always did — alone.

## The leak finder (`review/leaks.py`)

Duke's review question needs many games, not one: `find_leaks` reruns
`build_match_report` over every completed match, groups findings by `code`,
and ranks each by `|win rate with the pattern − win rate without|`, gated at
`MIN_SAMPLE` (10) on *both* sides of the comparison and reported with a 95%
Wilson score interval — never a rate without its uncertainty. Mana flood and
screw live here and only here: a single flooded game is not a story, but a
flood rate across many games with one deck is a real deckbuilding signal,
computed directly from `turns`/`decks` since no per-match analyzer emits
land findings any more.

`find_leaks` measures **each match against its own format's window**: it
takes a resolver, `consensus_window` (a format → that format's window
start), asks it once per format the population holds, and threads each
match's window into that match's `build_match_report` call — the same
field-matchup windowing `baseline.py` does for a single report, applied
across the whole rerun. A match with no format gets no window and no
consensus, never another format's. `api/routes/review.py`'s two routes
(the leak finder itself and its narrative prompt) both pass a resolver over
`_consensus_window(conn, fmt)` rather than leaving it `None`, and
`guide/bundle.py` and `coach/evidence.py` pass
`guide/window.py::consensus_window_resolver`, so a leak's own
`field_matchup_rate` finding, when it fires, never mixes pre- and
post-reset field data, or one format's field with another's. The older
`consensus_since` (one window for every match) is still accepted; passing
both raises.

Both flags are read per match by `leaks.py::_mana_flags`, which answers
`None` — not `False` — when a match has no evidence to answer from: `screwed`
needs at least one `turns` row for the match (MTGO's projector never writes
`turns` at all, so every MTGO match reads `None` here, never "not screwed"),
and `flooded` separately needs a resolved decklist with every card named and
a usable first/last-turn read, so a match can answer one flag and not the
other. `_mana_leaks` keeps each flag's own known population — the matches
that resolved `True`/`False`, never the `None` ones — and gates `MIN_SAMPLE`
against that population alone, so an MTGO match (or an Arena match missing
just one flag's evidence) is excluded from that flag's own denominator
rather than silently counted in as clean.

Only a `Finding` whose analyzer opted in — `Finding.pattern` (`findings.py`)
set to a fixed, per-code label — ever reaches this ranking; `pattern` is
`None` by default, so a new analyzer never silently enters it. Two real
defects motivated the gate rather than rolling up on `code` alone: a finding
that fires whenever an analyzer merely *had data* (`play_draw_split`,
`field_matchup_rate`, `still_live_staples`, `conceded` all used to rank
this way, correlating with sample availability rather than anything the
player did) and `cards_stranded_in_a_loss`, whose own definition only ever
fires in a game already lost — any win-rate "gap" behind it was its own
definition leaking into the statistic, not a pattern. `pattern` is also
what a leak is titled with now (`sample_title`): a fixed label, never
`Finding.title`, which used to be whichever match happened to be scanned
first — a 38-match pattern headlined by that one match's own hand size.
`test_every_pattern_label_is_free_of_digits` (`tests/test_review.py`) audits
every `pattern=` literal in `analyzers/` for exactly this: a digit in a
pattern label would be that mistake recurring.

`find_leaks` also takes optional `deck_ids`/`since` (scoping the population
to one deck's matches or a date window) and `consensus_cache`/
`colors_cache` (shared memoization for `build_consensus` and
`archetypes.classify._card_colors_by_name` across repeated calls in one
request) — added for `guide/bundle.py`, which needs both a deck-scoped
rollup and the unscoped one side by side and calls this function twice per
request. Every default reproduces the original unscoped, uncached
behaviour exactly, so no existing caller changed.

It also takes `view_cache` and `report_cache`. `view_cache` is the same
memoization pattern, shared with `build_snapshot`'s own per-request cache
for four statements that otherwise rescan a whole view per match (see its
docstring) — created fresh when omitted, same as `consensus_cache`/
`colors_cache`. `report_cache`, unlike the other three, is *not* created
when omitted — one call already builds every report once — but when given,
a whole `MatchReport` already built under a match_id and window (the key
is `(match_id, window)`) is reused instead of rebuilt, so a caller pairing
two `find_leaks` calls (`guide/bundle.py`) or a caller that already built
some of these reports itself (`coach/evidence.py`) pays for each match's
report at most once per request.

## The narrative (`review/narrative.py`, `review/leaks_narrative.py`)

Two separate prompts to write coaching prose from. Neither module makes the
call itself — only `sensei_top.llm.client` imports `anthropic` (AGENTS.md
non-negotiable #5, `docs/llm.md`) — but both now have a one-click path as
well as the copy-paste one:

- `GET .../narrative` always serves the prompt, built locally, offered as
  copyable text by `GenerateCard` (which falls back to plain
  `CopyPromptCard` with no credential configured).
- `POST .../narrative` sends that same prompt through `llm.write_prose` and
  stores the answer — `match_narrative` for the per-match route,
  `leaks_narrative` (a single row; the leak finder here is unscoped) for the
  leaks route — when a credential is configured. 503 otherwise.

The match prompt carries the game's turn-by-turn shape (life/hand/board/
power/lands, both sides' resolved spells) alongside the report's own
findings and gaps — deliberately more than the old findings-only version,
because a coach shown only conclusions can only restate them. The leaks
prompt carries only the ranked pattern list, never a specific match's turns.

Unlike the deck guide, neither has a CLI import path: a stored narrative here
only ever comes from the generate button, since there was never a manual
round trip worth preserving for a single match read once. The deck guide and
the matchup brief additionally support a hand-written import because those
describe a deck rather than one game and stay useful for as long as the deck
does (`docs/brief.md`).

## What still isn't analyzed

Combat is *projected* but this report does not yet reason about individual
attacks/blocks beyond damage totals — `combat_attacks`/`combat_blocks` exist
in the schema for a future analyzer to use (e.g., attacks that went in
unblocked when a block was available). Per-game sideboard decklists and
turn/decision timing (`TimerStateMessage`) are documented as unlocked-but-
unbuilt in the original planning pass; nothing here depends on them yet.
