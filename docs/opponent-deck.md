# Opponent deck

How the opponent's deck is named from the cards revealed, from the `archetypes/` module's rule engine to the corpus read and the manual pick; cut from [architecture.md](architecture.md).

## Naming the opponent's deck

Arena never sends the opponent's decklist (see
[arena-log.md](arena-log.md) trap 11b), so it is inferred from the cards they
revealed. `src/sensei_top/archetypes/source.py` downloads rule-based
definitions; `classify.py` evaluates them against what a match showed and
writes `opponent_archetype`. Classification runs immediately after `project()`
in both `cmd_project` and `LiveIngester.project_if_due`, because a rebuild deletes
its output — it is part of finishing the rebuild, not a separate job.

Naming a match at all needs its format first, because definitions are per
format and so is the corpus. "A match's format" below says where each
match's format comes from and how the classifier uses it.

The label itself is a **view**, `v_match_opponent`, layering
`manual override > classified archetype > colours and a signature card`
(`classified archetype` combines two evidence sources — see "A second
evidence source" below — but the view sees one written verdict per match).
It is a view rather than a stored column because it depends on `cards` and
`archetypes`, which the projector does not own and which the user may populate
long after a match was projected: a column would read stale until the next
rebuild, and a view is always current. In the moment between `project()` and
`classify_matches()` committing, the label degrades to the colours layer rather
than showing a blank. That colours layer carries up to three revealed
nonland cards (`opponent_signature_cards`, from `032_corpus_naming.sql`), so
a genuinely unnamed match (no rule definition, no corpus archetype) says more
than a single card's worth.

`serve` also refreshes the definitions on a background thread with its own
connection, so the process briefly has two writers. WAL plus the existing
`busy_timeout=5000` covers it, and both writes are short. `cli.py`'s
`_start_reference_refresh` is a writer by the same argument: its own
connection, ticking every five minutes, and its Arena-card step
(`cards.refresh_arena_cards`) only ever inserts the handful of grpIds an
Arena patch actually added, so the write stays short even though the thread
itself never stops. A write that loses to the rebuild's write lock (measured
in `docs/architecture.md`, "Live mode's two cadences") is caught by the loop
and retried on the next tick. The corpus refresh is a writer too, on its own
connection, with one difference: it waits for the lock rather than losing to
it. Its connection sets `busy_timeout` to 60 s
(`cli.py::_CORPUS_BUSY_TIMEOUT_MS`), because a busy error against the
watcher's rebuild would cost the run and then hold the source for an hour
(`docs/metagame.md`, "Fetching the corpus"), and nothing waits on this
thread. Its own writes are short: each
event's store, and `reclassify_corpus`, which reads every corpus deck first
and then replaces every classification in one transaction. Measured on a
copy of the real database (458 events, 11,685 decks, 2026-10-05): the
reclassification took 2.9 s, of which the write transaction held the lock
0.05 s, and dedup took 0.15 s in all. The daily backup's own background
thread (see `docs/architecture.md`, "Backups") is yet another writer by the same argument, but
for a different reason: its only writes are two tiny `backup_state` upserts
before and after the multi-minute copy, so it is a long *reader*, not a long
*writer* — WAL's one-writer-many-readers guarantee means it never blocks or
delays the watcher at all, no matter how long the `VACUUM INTO` itself
takes.

`v_match_opponent` (and `v_matchup_winrate`, unioned across the matches of
one row: one key, deck, source and format) also carry `opponent_colors`: the
colours the opponent actually *revealed* (`v_opponent_cards.colors`), never
the archetype's assumed colours — a classified match can be all colours its
definition allows while the opponent has only shown one.
`v_opponent_cards.colors` is `''` both when only colourless cards were
revealed and when revealed cards' colours are simply unknown (no matching
`cards` row yet); those two cannot be told apart, so `''` becomes `NULL` at
this column, and the dashboard renders nothing for it — never the word
"Colourless" (rule 4: unknown means `NULL`, never a guess). This is what lets
`ManaPips` (docs/design-system.md) render the real disc-and-glyph symbols
beside an opponent-deck label instead of a parsed-out colour prefix.

An opponent key keeps its spelling (`archetype:<key>`), so an override or a
brief written before formats needed no migration. A key faced in two formats
is two matchups, though. `v_match_opponent` carries the match's `format`
(migration 056), and `v_matchup_winrate` has one row per `(opponent_key,
deck_id, source, format)` since migration 058, with its label chosen per key
and format. Matches with no format share one row per key, deck and source,
never merged into a named format's. `GET /api/metrics/matchups` reads it as
one row per format, key and deck.

### A match's format

**Arena's log names it.** The projector writes `matches.format` (migration
055) from the deck's format and the event id, through
`formats.py::arena_format`. The mapping is Standard only: Arena's Standard
decks, its Standard events and its unqualified ranked ladder are Standard.
Limited, the Arena-only formats (Historic, Alchemy, Brawl, Timeless,
Explorer) and the precon queues are `NULL` by design, with no warning. An
event id that looks constructed and still maps to nothing warns once per
event id in a rebuild, not once per match. MTGO's log never names a format,
so an MTGO match's `matches.format` is always `NULL`.

**An MTGO match's format is read off its cards.** `classify.py::infer_formats`
reads both seats' revealed cards against `card_legality` and writes two
tables, for MTGO matches only (migration 056), both rebuilt in full by every
`classify_matches()` run. `match_format_fit` has one row per format the match
fits: none of its revealed non-token cards is `not_legal` there. A ban does not
rule a format out. `banned` and `restricted` still fit, because Scryfall's
ban list is today's, not the one in force on the match's date.
`match_format_inference` has one row per MTGO match: the inferred format and
a `reason`. The inferred format is the single narrowest fitting format under
`formats.py::BROADER`, a partial order: Standard ⊂ Pioneer ⊂ Modern ⊂ Legacy
⊂ Vintage, Premodern ⊂ Legacy, and Pauper ⊂ Vintage only. Two incomparable
narrowest formats give no format and reason `ambiguous`, never a tiebreak by
pool size. Cards legal in both Standard and Pauper are exactly that case, so
Pauper is only ever confirmed by the user's pick, never inferred.

Every other reason says why there is no inference, checked in this order:
`unresolved_cards` (a card event never resolved, so the match is not judged on
the cards that did), `unknown_legality` (a resolved card with no `cards` row,
or without a `card_legality` row in all seven formats; unknown is never read
as legal), `no_fit` (every format has a card `not_legal` in it), and
`too_few_cards` (fewer than five distinct non-token names, `MIN_REVEALED`).
A match whose cards cannot all be read has no fit rows at all; a
`too_few_cards` match keeps its fit, which is exact, and only the inference
waits. Tokens never count. A resolved token is skipped by its type line, and
an unresolved event whose `card_events.mtgo_name` is MTGO's token spelling
(`"<Base> Token"`) or a game marker (*The Initiative*, *Undercity*) is set
aside rather than blocking the match. A `NULL` `mtgo_name`, from a row
projected before migration 060, still blocks it.

**`v_match_format` is the format every reader uses**, resolved at read time:
Arena's `matches.format`, else the user's MTGO pick (`mtgo_match_pick.format`,
through `v_match_deck`, which applies a pick to MTGO matches only), else the
inference. Its `format_source` says which answered: `log`, `pick` or
`inferred`, and `NULL` when `format` is. Neither the pick nor the inference is
ever written into `matches.format`: `project()` may not read the pick (rule
6). So an unconfirmed MTGO match counts under its inferred format until a
pick overrides it, and the Field page's format caption says how many of a
format's matches were inferred (`GET /api/formats`).

A deck has a format too, for the guide, the brief and its coverage:
`guide/deck.py::identity_format` (`deck_format(conn, key)` for an API key).
It is the deck's `decks.format` as one of the seven (`TraditionalStandard` is
Standard; Draft and any other spelling is none), else the format most of the
deck's matches have in `v_match_format`, a tie going to the most recently
played and then the lower name, else `NULL`.

**The classifier names a match under every format it could be.** An Arena
match is named under its `matches.format`. An MTGO match is named under every
format in its fit that has definitions, so a Modern-shaped match gets Modern,
Legacy and Vintage rows. `opponent_archetype` is keyed `(match_id, format)`
since migration 056, and `v_match_opponent` joins the row for the match's
`v_match_format` format. `classify_matches` never reads the pick, so a
rebuild comes out the same whatever the user has answered. That is also its
limit: **a pick always corrects the format, but the opponent's deck follows
only inside the fit.** A pick outside the match's fit, or on a match with no
fit, finds no `opponent_archetype` row, and the label falls back to colours
and a signature card until the user picks the opponent's deck as well. A
match whose format has no definitions (no format at all, or Premodern, which
MTGOFormatData ships no rules for) is counted `skipped_format`.

**The limit: legality is today's.** A card rotated out of Standard since a
match was played reads `not_legal` there now, so an MTGO match played before a
Standard rotation no longer fits Standard and is inferred as Pioneer, or
broader. A pick of Standard corrects the format, but not the deck name:
Standard is outside that match's fit, so no Standard row was written for it.
A ban has no such effect on the fit, since a
ban never rules a format out. A date-aware rotation and ban history is not
built.

### Ranking by fit, not by raw condition count

Ranking archetypes by a count of met conditions, with fewer unknowns as the
tiebreak, lets a definition one requirement short of proof outrank one that
never had a second requirement to begin with: ranked that way, a real match
named its opponent "Dimir Harmonizer" off a single generic card (one of the
two the Harmonizer definition needs) for twenty-odd turns, while the actual
signature card — the whole of a one-condition Excruciator definition — sat
unseen. A count also never checks a definition's own colours against what has
actually been shown; that wrong guess was green, the opponent straight Dimir.

`classify.py` scores every candidate as a single **fit** in `[0, 1]`:
`proof` (the fraction of a definition's requirements that came back met)
times `support` (diminishing returns on raw proof count, so one lone hit
never outweighs two independent ones) times `colour_factor` (how
well the definition's own required colours — derived from the local `cards`
table, unioned across an `all` condition or intersected across a `one-of`
one — agree with the colours the opponent has actually shown; a mismatch
demotes fit rather than erasing it, and sharpens as more cards go by without
the missing colour ever turning up). A verdict is only *named* — written to
`opponent_archetype` at all — when the leader clears an absolute fit floor
**and** beats the best *differently labelled* rival by a real margin; a
close call or a genuine tie leaves the match unclassified rather than picking
an arbitrary winner, and `v_match_opponent` falls through to the colours-and-
signature-card layer exactly as it does for any other unclassified match.
`confidence_of()` is gated the same way, on fit and margin rather than a raw
condition count, and a fallback (a family match, not a proved archetype) is
capped below `'high'` by construction.

The constants (fit floors, the margin multiplier, the colour-agreement ramp)
were fitted against a validation pass over real, previously-classified
matches — 21 of 22 kept their label, one (a `'low'`-confidence one-card
fallback hit) moved to unclassified, none flipped to a wrong label. They are
tunable, not derived; if real data disagrees with them, that is information; a
constant should move before a test does (`AGENTS.md`'s testing rule extends to
tuning: read what actually happened before adjusting the threshold that
disagreed with it).

### A second evidence source: the corpus's own decklists

`choose()`'s rule engine is exact, but a well-defined archetype's fit
saturates fast, because `_fit_score` counts
*conditions* met, not cards seen — a definition with one condition reaches
its ceiling on the first confirming card and cannot be pushed any further by
a fifth or sixth signature card revealed later in the match. Measured against
195 real Standard matches: 46 stayed unclassified, and 38 of those scored
*zero* candidates outright — not a close call the margin gate rejected, but
no rule definition sharing a single card with what was revealed at all.

`archetypes/corpus.py` reads the same metagame corpus `review/consensus.py`
already aggregates into consensus card lists (`meta_deck` /
`meta_deck_archetype`, 10,000-plus real MTGO/paper decklists, already
archetype-labelled by the same rule engine over *complete* decklists — see
`docs/metagame.md`) as a second opinion: a Laplace-smoothed naive-Bayes
log-odds score over card presence, `log P(archetype) + Σ log(P(card |
archetype) / P(card))` summed over every card this match actually revealed.
It strengthens additively with each card (the property the rule engine's fit
lacks), and needs no definition that names the cards this match revealed —
but it can only name labels the definitions gave its decks
(`metagame/classify_meta.py::classify_meta_decks`, which labels each corpus
deck with `choose()` over its complete list and skips a deck with no
verdict). It is silent by the same discipline as everything else here
(rule 4): `build_prior()` returns `None` on a corpus with nothing to say, and
a machine that has never fetched or classified the corpus names every match
by the rule engine alone.

**The prior is per format.** `build_prior(conn, fmt)` learns only from the
corpus decks of `fmt` (`meta_event.format`), and its reset and `"gone"`
archetypes are that format's too, so a Modern match is never scored against
Standard's archetypes. A format the corpus holds no classified decks for
(the fetch takes Standard and Modern unless asked for another: see
`docs/review.md`, "Metagame data: real tournament results, not Arena aggregators")
has no prior, and its matches are named by the rule engine alone. No format is no prior, never Standard's: `api/sql.py` caches one prior
per corpus state and format for the picker, and `table/intermission.py` keeps
one per format for the Bo3 break read, each for the match's `v_match_format`
format.

Ban-awareness is inherited from `guide/window.py` rather than reimplemented:
a banned card is dropped from every count and an archetype the reset killed
(`structural_change`'s `"gone"` verdict) is excluded from the prior entirely,
rather than windowing the corpus to post-reset dates alone. Measured, the
ban-aware full corpus scored 90% precision on 6,773 decks against the
windowed corpus's 82% on 655 — a card-to-archetype association is not a win
rate, so the "never window `meta_*` across a ban" rule (which protects rates
and shares) does not forbid this; a banned card simply never appears in a
live match to begin with.

`classify_matches()` builds one prior per format per run (not per match), for
each format it is about to name a match under, and combines
the two verdicts by **confidence rank, the rule engine breaking an exact
tie** — the more legible answer of the two when both agree. Neither source is
ever changed to accommodate the other: `choose()`, `evaluate()` and
`_fit_score` know nothing of the corpus, and the corpus source has its own
floors (`CORPUS_MIN_CARDS`, `CORPUS_MIN_ODDS` and the medium/high tiers in
`classify.py`) on an entirely different scale (unbounded log-odds, not a
bounded `[0, 1]` fit) rather than reusing the rule engine's numbers. A
corpus-won verdict is written with `method = 'corpus'`, flows through
`opponent_source` unchanged (that column reads `a.method` directly),
and reuses `_archetype_label`/`color_label` so it renders identically to a
rule-named deck. `rank_candidates()` takes the same prior as an optional
argument to nudge (never invent) a candidate's `fit` in the picker's
shortlist; omitted, the shortlist is the rule engine's alone.

Every constant here — `CORPUS_MIN_CARDS = 3`, `CORPUS_MIN_ODDS = 25.0`,
`MIN_CORPUS_DECKS = 8` — was fitted against one snapshot of one player's real
match history and the 15 matches they had manually corrected, the same
"tunable, not derived" discipline the rule engine's own fit floors follow
above. They are expected to move once real behaviour disagrees with them.

### Correcting the classifier: a pick, not free text

The dashboard offers every archetype and fallback definition for a match's
format, ranked by the same fit `choose()` uses, via
`archetypes.rank_candidates()` and `GET
/api/matches/{id}/opponent-deck/candidates`. Unlike `choose()`, which commits
to one verdict or none, this returns everything — a definition the revealed
cards contradict is still worth offering, because the player watched the
match and may know better than a dozen-card heuristic. It is ranked last, at
confidence `'none'`, with a `reasons` entry naming the seen card that ruled it
out when there is one (`_elimination_reason`). Every scored candidate carries
its own `fit` and `reasons` (which cards matched, and any colour the
definition needs that hasn't shown up) — what the Live page's
shortlist and the picker's fit bar both render directly, rather than
re-deriving anything client-side. The picker is offered at every confidence,
not only when the classifier reports doubt: a wrong `'medium'` or `'high'`
guess is exactly as correctable as an uncertain one, so nothing in the API or
the dashboard gates it on `opponent_confidence` any more.

`rank_candidates()` also flags whichever candidate matches the match's
current `opponent_deck_override`, if any, as `picked: true` — a lookup it
already has the connection and match id to do itself, so nothing downstream
needs to re-query `opponent_deck_override` separately. Its one reader is the
picker itself (`OpponentDeckLabel.tsx`), which marks the current pick; every
other surface that needs "the opponent's deck" reads the override through
`v_match_opponent` (where a manual pick outranks the classifier) rather than this flag, so a correction reaches them without
passing through the candidate list at all.

"Rogue" — Magic's term for a deck with no established archetype — is not one
of these definitions, so it never appears in the API response; the dashboard
adds it itself, always last. Picking it stores an override with a `label` but
no `archetype_key`.

`opponent_deck_override` therefore carries an `archetype_key` (added in
`006_deck_picker.sql`) alongside `label`: set when the pick names a real
definition, `NULL` for Rogue. `v_match_opponent` prefers `'archetype:' ||
archetype_key` for `opponent_key` when it is set, so a picked archetype
merges into the same matchup as matches the classifier itself named that
way, rather than splitting off under its own `manual:` key. Migration 006
also deleted every existing override: the free-text "name it" feature it
replaces produced labels with no `archetype_key` and no way to reconcile them
with the picker's candidate list, so the one row that had accumulated was
wiped rather than left stale.

`010_zone_card_detail.sql` widened `v_turn_zones` with `mana_cost`,
`type_line` and `colors` — columns `cards` had held since `003_current_match.sql`
but no view ever surfaced beyond `name`. Nothing new to compute: the join
already happened, and the frontend's zone displays (the current-match tab's
facts panel, the turn-by-turn board) needed more than a bare name to say
anything about a card.
