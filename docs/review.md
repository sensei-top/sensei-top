# The match report

Read this when touching `review/`, or deciding whether a new signal belongs
in the per-match report versus the leak finder.

**Scope note.** This document covers the per-match postmortem and the
cross-match leak finder. The deck guide (`docs/guide.md`, `guide/`) uses
this package's `build_match_report`/`find_leaks`/`build_consensus` as
building blocks rather than duplicating them; the per-match report lives on
the match drill-down (`MatchReportPanel`), reachable from a leak's own match
chips.

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
   (`metagame.classify_meta`); `snapshot.py`'s `classify_own_deck` runs the
   same engine over the player's own complete decklist
   (`decks.cards_json`) — something no analyzer did before, because nothing
   needed the player's *own* archetype key until role assignment did.

## The analyzers, one per module in `review/analyzers/`

Each is a pure function of one `MatchSnapshot` (`review/snapshot.py`;
"The match report, and its optional narrative" below lists every module
here that touches `sqlite3`). The registry order in
`analyzers/__init__.py` is the order a postmortem's arc runs in; the report
itself sorts findings by game, turn, then code, and gaps by game, then
analyzer, whatever the registry order.

### `frame.py` — the matchup, and the role it demands

Flores' *Who's the Beatdown?* and Duke's *Role Assignment*: "Misassignment
of Role = Game Loss." Three signals, applied as votes: more creatures
usually means beatdown; more removal usually means control; more card draw
and counterspells "almost always" means control (weighted double). The
player's own side reads their *exact* decklist (`snap.own_cards`); the
opponent's side reads the field's consensus list for their archetype
(`snap.opp_consensus`) weighted by share — the best substitute for a
decklist this reader never sees in full. Either side unclassified is a gap,
never a guessed role.

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

Also carries the neutral game-start facts — mulligan count and
on-play/on-draw — and never a verdict on them
(`test_the_report_never_judges_a_mulligan`): this is a post-game read over
projected data, and the hand a player actually shipped — after bottoming
cards under the London rule — is never in the log at any point, so nothing
here states a mulligan was right or wrong. (`table/opening_hand.py` reads a
different, earlier message live, for the Live page — see
`docs/current-match.md` — which is why this still holds true for a
*finished* game without contradicting that.)

### `clock.py` — the damage race

Duke's *Damage Racing* and Flores' *Philosophy of Fire*: cards for life, not
cards for cards. Sums `damage_events` dealt *to a player* (creature-vs-
creature combat is excluded — it doesn't move either player closer to
winning the race) per game, and reports who was ahead and by how much. A
margin of 10+ damage is `DECISIVE`; anything smaller is a `NOTICE`. Below
`MIN_DAMAGE_FOR_A_RACE` (6 total), the game reports a gap instead — a single
early hit is not a race yet.

Leading and trailing a race are two separate codes, `race_ahead` and
`race_behind`, each with a fixed subject rather than one code with a
variable one: a variable subject cannot agree with its verb ("You were
ahead" / "The opponent was ahead"), and whichever side you're on changes
what the finding *means*, so leading and trailing are opposite signals,
each its own leak pattern.

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
zone transfers for both sides (`card_events.category = 'Countered'`). Duke's
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
outcome facts — game length vs. this deck's own average, timeout/concede,
and the play/draw split — since "compared to a wider sample" is exactly
what those are.

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

* **`headline`/`subhead`** — the match's own score and opponent, plus an
  optional subhead, written only when a stated condition holds over the
  report's own findings (leading the damage race in every game and still
  losing some of them; a lone `DECISIVE` finding's own already-audited
  title, reused verbatim). Nothing is written to fill an empty slot —
  `subhead` is `None` far more often than not. The race sentence doesn't
  stop at the mismatch: after it comes one sentence per lost game, in game
  order, naming that game's top beat by the same severity order the game's
  own beats use ("Game 2, Turned: your turn 4 · a decisive swing."), or "no
  single cause stood out" when the game has none. Leading the race and
  losing says only that something else decided the game; the beat is the
  report's best candidate for what. Two kinds of beat are never a cause:
  the race itself, the sentence's own premise, and `never_behind`, which
  says the position never swung against you. No analyzer reads lands played
  and a mulligan is never a beat, so a game lost to mana screw or a
  mulligan names whichever other beat fired, or no single cause.
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

  The Turned beat counts "your turn N" with the finding's
  `self_turn_index`, the turn's rank among your own turns, never Arena's
  shared `turn_number`, which counts both players' turns. With no own-turn
  index the beat reads the magnitude alone.

  Each beat also carries its finding's `turn_number` (`None` when the
  finding has none, as `never_behind` doesn't), so the dashboard can open
  the replay on a flagged turn, and a `definition`: one plain sentence
  saying what its label measures. The sentences live beside
  `_GAME_BEAT_LABELS`, one per label rather than per code, so the three
  race codes share Race's and `turning_point`/`never_behind` share
  Turned's; a label with none, and every matchup beat, carries `None`.
  The words for why a game ended name who, read from the game's own
  result: a 1v1 game is lost by whoever concedes or runs out of time, so a
  concession is "you conceded" on a loss and "your opponent conceded" on a
  win, and the same for the clock. With the result unknown or a draw the
  subjectless words stay ("conceded", "ended on the clock"). Nothing about
  it is stored.
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
post-reset field data, or one format's field with another's.
`consensus_since` (one window for every match) is also accepted, though no
caller passes it; passing both raises.

Both flags are read per match by `leaks.py::mana_flags`, which answers
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
`archetypes.classify.card_colors_by_name` across repeated calls in one
request) — `guide/bundle.py` needs both a deck-scoped rollup and the
unscoped one side by side and calls this function twice per request. Left
out, the population is unscoped and each call memoizes on its own.

It also takes `view_cache` and `report_cache`. `view_cache` is the same
memoization pattern, shared with `build_snapshot`'s own per-request cache
for four statements that otherwise rescan a whole view per match (see its
docstring) — created fresh when omitted, same as `consensus_cache`/
`colors_cache`. `report_cache`, unlike the other three, is *not* created
when omitted — one call already builds every report once — but when given,
a whole `MatchReport` already built under a match_id and window (the key
is `review/leaks.py::report_cache_key`: `(match_id, window)` in English,
with the request's language added otherwise, so a prompt — always built
under `english()` — never reuses a report a Portuguese page built) is
reused instead of rebuilt, so a caller pairing
two `find_leaks` calls (`guide/bundle.py`) or a caller that already built
some of these reports itself (`coach/evidence.py`) pays for each match's
report at most once per request.

## The narrative (`review/narrative.py`, `review/leaks_narrative.py`)

Two separate prompts to write coaching prose from — the coaching layer over
the report, not a summary of it. Neither module makes the call itself —
only `sensei_top.llm.client` imports `anthropic` (AGENTS.md non-negotiable
#5, `docs/llm.md`); both stay pure functions of already-projected data —
but both have a one-click path as well as the copy-paste one:

- `GET .../narrative` serves the prompt whenever there is something to
  narrate, built locally, offered as copyable text by `GenerateCard`
  (which falls back to plain `CopyPromptCard` with no credential
  configured), with the stored prose beside it once one is written
  (`status: "ok"`; `"prompt"` before; `"no_report"`, and no prompt, when
  there is nothing to narrate).
- `POST .../narrative` sends the prompt without its answer contract
  (`full_prompt`; the copied one, `copied_prompt`, ends by asking for one
  `{"prose": ...}` object) through `llm.write_prose` and
  stores the answer — `match_narrative` for the per-match route,
  `leaks_narrative` (a single row; the leak finder here is unscoped) for the
  leaks route — when a credential is configured. 503 otherwise.
- `PUT .../narrative` stores an answer pasted into the card, read
  through `answers.py` (its `for` line must name this match, or the
  training plan), in the same table, with the author `pasted` and no
  cost. It calls no model (`docs/llm.md`, "Saving a pasted answer").

The match prompt (`build_narrative_context(report, snap, field=...)`)
carries the game's turn-by-turn shape (life/hand/board/power/lands for both
sides, both sides' resolved spells in order) alongside the report's own
findings and gaps, because a coach shown only conclusions can only restate
them. Never a raw zone dump — no hands, no graveyards, no exile contents,
and `MatchSnapshot` never carries the opponent's Arena handle or user id in
the first place. It ends with an explicit "not tracked" block (the stack,
counters, attachments, the exact phase or step, the opponent's hand) so
whoever writes the review is never left to assume silence means empty
(rule 4). The leaks prompt carries only the ranked pattern list, never a
specific match's turns.

Unlike the deck guide, neither has a CLI import path: a stored
narrative here comes from the generate button or from an answer pasted
into the card, since a terminal round trip was never worth adding for a
single match read once. The deck guide and the matchup brief also take
a CLI import because they describe a deck rather than one game and stay
useful for as long as the deck does (`docs/brief.md`).

## What still isn't analyzed

Combat is *projected* but this report does not yet reason about individual
attacks/blocks beyond damage totals — `combat_attacks`/`combat_blocks` exist
in the schema for a future analyzer to use (e.g., attacks that went in
unblocked when a block was available). Per-game sideboard decklists and
turn/decision timing (`TimerStateMessage`) are documented as unlocked-but-
unbuilt in the original planning pass; nothing here depends on them yet.

## The match report, and its optional narrative

`src/sensei_top/review/` is a post-projection analysis package, the same
shape as `archetypes/` one stage further out: it reads projected tables and
views, never `raw_events`, and nothing in `projector/` may import it (see its
own module docstring for the two hard rules this implies). `GET
/api/matches/{id}/report` returns its output — deterministic findings and
gaps, recomputed fresh on every request rather than stored.

The report is a postmortem built on the game's own strategy canon (Flores'
role assignment, Duke's damage racing and tempo/card-advantage framing, the
Lichess-style idea of naming the turn that decided a game) rather than log
bookkeeping — see "The analyzers, one per module in `review/analyzers/`" above
for what each analyzer measures and the article behind it. `review/analyzers/` is a package, one module per concept
in that arc (`frame`, `clock`, `trajectory`, `role_play`, `information`,
`resources`, `baseline`), registered in `review/analyzers/__init__.py`'s
`ANALYZERS` tuple; `match_report.py` runs every entry over one
`MatchSnapshot` and concatenates the results in a stable sort, never
registry order.

**Computed on demand, not persisted — the same reasoning as
`v_match_opponent` (`docs/opponent-deck.md`, "Naming the opponent's deck"), one step further.** Several analyzers read
`cards.type_line`/`oracle_text` (to tag a card's effect, or classify a
decklist), downloaded reference data the projector does not own, possibly
populated (`sensei-top cards`) long after a match was projected; and they
read a match's `decks.cards_json` through `v_match_deck`, which the user's
MTGO pick changes with no rebuild. A stored `findings` table would read
*wrong*, not merely stale, for every match analyzed before either change. **The analyzers themselves never
touch `sqlite3`** — they are pure functions of a `MatchSnapshot`, which is what
makes them testable from a constructed snapshot with no database at all — every
one has the signature `analyze_*(snap: MatchSnapshot) -> AnalyzerResult`, with
zero database access in `review/analyzers/`.

Query access in this package is confined to five modules with distinct jobs:
`snapshot.py` (the per-match read the analyzers run on, a fixed set of
queries, none per turn),
`leaks.py` (the cross-match population, 6), `consensus.py` (the corpus scan,
3), and `narrative_store.py` / `leaks_store.py` (2 each). `match_report.py`
takes a connection but issues no query of its own — it passes one through to
`build_snapshot` and then runs the pure analyzers over the result.

`snapshot.py` does one read per match, including a same-request
classification of the player's own deck (`archetypes.classify`'s
`complete=True` path, the same one `metagame.classify_meta` runs over a
corpus decklist) and a scan of the metagame corpus for the opponent's
archetype's consensus decklist (`review/consensus.py`).

Every analyzer returns `Finding`s (something observed) and `Gap`s (something
it could not evaluate, and why) — kept as separate lists so a report's
silence is never mistaken for "nothing was wrong" (rule 4). `self_open_mana`
is the sharpest case: NULL means both "tapped out" and "never observed your
board" (migration 008), so nothing here computes an "unspent mana" reading
from it. `review/position.py`'s position index —
a transparent, fixed-weight formula over life/board/hand/mana, never fitted
to outcomes — turns the per-turn combat and life data ("What became possible, and why" above) into the number `trajectory.py`
anchors a game's turning point to.

The narrative over this report is "The narrative (`review/narrative.py`,
`review/leaks_narrative.py`)" above.

**The matchup brief has no generate button of its own**, but it is not
import-only either. `POST /api/guide/{key}/narrative` writes
`matchup_brief` rows as a second effect, via
`brief/from_guide.py::store_guide_matchups`, for every matchup the generated
guide covers. So a brief arrives by several paths: a CLI `brief --import`
or `brief --missing --import`, a CLI `guide --import`, the guide's generate
route, or one of the guide's three `PUT` routes for a pasted answer (one
brief, the multi-brief coverage answer, or a guide, which backfills briefs the
same way; `docs/brief.md`). Its own card
(`MatchupBriefCard`) remains `CopyPromptCard`-only, deliberately — a brief is
read while a game is on the clock, which is the worst moment to start a
minutes-long API call.

A malformed answer or import raises `NarrativeError` — the CLI says what was
wrong rather than storing half a guide, and the generate route maps it to a
502 rather than storing anything; the API's own `GET` routes answer `200`
with an honest status for every "nothing to show yet" case — an empty
report, never a broken page.

### Metagame data: real tournament results, not Arena aggregators

The report's matchup context wanted one more input: how the current
archetype is actually performing in the field right now, not just what
defines it. Three sources were evaluated and two were rejected before
`metagame/` was written — its own fetch still has to meet the free-download
standard (reference lookups only, fail-soft, no more than the feature needs;
AGENTS.md non-negotiable #5, in full in [llm.md](llm.md)):

- `mtgdecks.net/robots.txt` disallows `ClaudeBot`, `anthropic-ai`,
  `Claude-Webt`, `GPTBot`, `CCBot`, and a site-specific `MTGMeta-Scraper`
  user agent by name, and carries `Content-Signal: ai-train=no`. That isn't
  rate-limiting; it's the site stating, in the one channel meant for
  automated readers, that this kind of tool specifically should not read it.
- `mtgazone.com` blocks even an unauthenticated fetch of its own
  `robots.txt` (403) — its anti-bot layer refuses the request before any
  policy can be read at all.
- `17lands.com` publishes aggregated play data under a CC BY 4.0 license —
  the right posture, the opposite of the two sites above — but it collects
  from Arena Limited drafts, not constructed. Its data cannot answer a
  Standard matchup question regardless of license terms, so it was rejected
  on coverage, not access **for this feature**. That reasoning still holds
  exactly as written — but it does not generalize to every feature this
  project might build, only to a *constructed* matchup question. The draft
  assistant (deleted 2026-10-01; `archive/draft` tag) asked a Limited pick
  question instead, the one thing 17lands' data actually answers, and reused
  this same access verdict rather than re-litigating it.

Rule 5 draws the line between the sanctioned calls and everything else at
"does this serve the data freely to any request, for the format this project
actually classifies." `fbettega/MTG_decklistcache` clears both bars: MIT-
adjacent GPL-3.0 data served over plain `git`/HTTP, and its `MTGO` and
`MTGmelee` sources are real constructed results, in the formats `archetypes/`
classifies. The fetch follows Standard, Modern and every format the stored corpus
already holds (`metagame/auto.py::followed_formats`); `sensei-top meta
--format X` adds another on demand. `metagame/`
fetches it windowed by date and incremental by blob SHA (the cache is ~157 MB
of history this project mostly does not need); see [metagame.md](metagame.md)
for the evidence-tier rules that constrain what each stored event is allowed to
claim, and for why `archetypes.classify`'s rule engine runs in a different mode
against a full decklist than it does against the dozen cards a live match
reveals.
