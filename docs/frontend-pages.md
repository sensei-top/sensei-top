# Frontend: the pages

The dashboard page by page: Home, Matches and a match's views, the current-match reads, the opponent-deck read, the MTGO picks, the match report, Decks, the RCQ page, the Deck guide, Field and Coach. Cut from [docs/frontend.md](frontend.md), which keeps the rules every page follows.

## Home

`HomeView` (`views/HomeView.tsx`) is the page at `/`. It reads every source
and takes no filter. Until a match is recorded it shows first run (below).
After that, from the top: the Detailed Logs banner, inside the desktop shell
only, the last session, three things worth a look, the MTGO matches that
still need a deck, the recent matches beside the win rate by week, the deck
tiles, and the field beside a pointer to the coach. A part with nothing to
show is not drawn, and the part beside it takes the row.

The components in `components/home/` only draw. **Every count on Home is
a pure function in `lib/home.ts`**, of the API's rows and a clock handed
to it, with no React in the file. A finished match is one whose result
is `win`, `loss` or `draw`. A match whose start cannot be read has no
place in a session, a week or a list by date, so Home leaves it out;
Matches still lists it.

### What it asks for

| Request | Hook | For |
|---|---|---|
| `/api/live` | `useLive` | first run's steps, the count in "All 1,204 matches", whether the list is cut short |
| `/api/matches?source=all&limit=500` | `useMatches` | the session, the 30 days, the last match, the recent matches, the weeks, the records against the field (by each match's `format`), which match gives which art |
| `/api/guide/decks` | `useGuideDecks` | the deck tiles, one per deck |
| `/api/review/leaks?source=all` | `useLeaks` | the pattern |
| `/api/formats` | `useFormats` | the default format, whose field Home shows |
| `/api/metagame/status?format=` | `useMetagameStatus` | that format's reset, where the field's window starts |
| `/api/metagame/presence?format=` | `useMetaPresence` | that format's field |
| `/api/matches/{id}` | `useMatchArt` | card art alone, seven matches at most |
| `/api/mtgo/needs-pick` | `useMtgoNeedsPick` | the Needs a deck card |

Home has no format control. It names the default format explicitly in
the status and the presence, rather than leaving both to the API's own
default, so the window, the field and the viewer's record cannot drift
apart, and neither is asked for before `/api/formats` answers.

Home never asks for `/api/coach`, `/api/coach/narrative` or a match's
report (`/api/matches/{id}/report`). The coach on Home is `CoachPointer`,
two sentences and a button to `/coach`.

A request on its way holds its card's place with a `Skeleton`. One that
failed says so in the card that needed it (`ErrorNote`), and the rest of
the page stands. While the tracker cannot be reached Home draws nothing:
the shell's own callout says so.

### Needs a deck

`NeedsDeckCard` (`components/home/NeedsDeckCard.tsx`) lists the MTGO
matches the user has not yet answered, newest first, five at most and then
a count of the rest. Each row links to the match's page, where the pick is
made ("The MTGO deck pick", below). A match counts as answered once it has
a confirmed deck, or "No list" with a format. The card is hidden while its
request loads and when the queue is empty. A failed request shows an
`ErrorNote` in its place rather than vanishing. From two waiting matches up,
the card links to `/mtgo/picks` ("Review all {n} at once", "Picking many MTGO
matches", below).

### First run

First run is no match from any source (`isFirstRun`).
`FirstRun` draws three steps in an `OnboardingSteps`, and
`firstRunSteps` reads their states from the heartbeat: the tracker is
watching, Arena is writing its log (one event or more), play a match.
The first step not done is the one that is next, and the only one that
says what to do. The third is never done on that screen: a recorded
match ends first run.

The first step shows `shell.liveStatus.notWatching`, or
`shell.liveStatus.watcherStopped` once the watcher has died after
starting. It is the sentence the live status's panel
(`shell/LiveStatus.tsx`) and Live's callout, below, show.

**Inside the desktop shell, first run follows the welcome steps'
choice** (`plays`, through `HomePage`; a browser gets the steps
above). For a player of Magic Online alone (`lib/home.ts`'s
`mtgoOnly`) the lead and the three steps are MTGO's own: the watcher,
with MTGO's sentences for not watching and stopped; a game-log folder
being watched (`mtgo_watching`), since MTGO's events arrive only when a
game ends, its detail saying to set the folder only when none is set;
and play a match. For anyone who plays Arena, while the Detailed Logs
banner holds (below), the log step's detail is the banner's body
(`DetailedLogsBody`): the drawing and Check again, in place of the
sentence. The events count every source, so a player of both with an
MTGO folder can read that step as done with no Arena event; the
banner then stands above `FirstRun`, and is held back only while the
log step carries it.

### The Detailed Logs banner

`DetailedLogsBanner` (`components/home/DetailedLogsBanner.tsx`) is a
`warn` `Callout` at the top of Home, inside the desktop shell only,
while `lib/home.ts`'s `detailedLogsNag` holds: the user plays Arena
(`plays`, both when missing), the shell found or was given Arena's
log, and doctor does not read Detailed Logs as `enabled`. It never
shows to a player of Magic Online alone, nor when no log was found,
which the welcome steps and Settings already say. It carries one
sentence, the drawing at its compact size (`DetailedLogsGuide`,
`docs/frontend.md`, "Welcome") and Check again, which re-reads doctor
through the shell; the shell's published result takes the banner away
once it reads `enabled`. A check that still reads `unknown` says that
nothing changed, and that Arena writes the line only when it starts.
There is no periodic re-read: Check again and the next shell start
are the two ways it clears.

### The session, and the three things

**The last session** (`lastSession`) is the newest run of finished
matches in which no match starts more than three hours after the one
before it ended (`SESSION_GAP_MS`; its start, where it has no end). It is
named by the day its first match started. The line about the last 30
days is drawn only when those days hold a finished match outside the
session: with none, it would repeat the headline.

**The three things** are the first three that exist of, in this order
(`threeThings`): the last finished match; the first pattern that costs
the viewer (`firstPattern`: the leak finder's first whose win rate with it
is below the rate without); the field. Fewer when fewer exist, never a filler. A candidate whose
request failed still takes its place, as the failure.

A pattern's title and sentence are Home's own words, by the leak
finder's code (`patternWords` in `lib/patterns.ts`).
A code with no words there takes the title the API sends
(`sample_title`), so a new code in `review/` shows on Home before it
has words of its own.

### The weeks

`weeklyWinrate` counts finished matches by the week they started in:
the twelve weeks that end with the newest finished match's week, from
the first of them that holds a match. `WeeklyWinrate` draws them as a
line from 0 to 100%, and its last point carries its rate as a label.
A week with fewer than ten matches (`RATE_MIN_MATCHES`) is a hollow
dot, and the card says so under the chart. A week with no match has
no point, and the line does not cross it (`connectNulls={false}`).
One week alone is a sentence and no chart (`docs/frontend.md`, "Charts"). With no
week to show the card is not drawn.

### The list of 500

Home asks for the 500 newest matches (`HOME_MATCH_LIMIT`) and counts in
the browser. The list is cut short when it holds 500 and the heartbeat
counts more matches than it holds; with no heartbeat yet, when it holds
500. Two counts say so when it touches them:

- **The weeks.** The oldest week in a list cut short holds only part of
  its matches, so that week and any before it are left out, and the card
  says "Counted over your last 500 matches."
- **The field.** When the list does not reach back to the start of the
  field's window, the card says "Your record is counted over your last
  500 matches." This reads the whole list, not only the field's format,
  since the cap applies to the list.

The session and the 30 days are counted over the same list and carry no
such note. The deck tiles do not read the list for their records: those
are each deck's own totals from `/api/guide/decks`.

### Decks, and the field

**A tile is a deck, not a version** (`homeDecks`): one per identity of
`/api/guide/decks`, five at most, those with the most matches in the
last 30 days first and then by last played. An identity with no match is
left out. From ten matches won or lost (`RATE_MIN_MATCHES`; a draw is
neither) the record is a rate, "58%" over "35–25"; from five to nine
the rate muted, "67%" over "6–3 · rough"; under five the record, "3–1",
muted, over the "too few for a rate" line; with none
there is no figure. A tile leads to
the deck's own address, `deckAddress(deck.key)` (`lib/decks.ts`), never
a version's id.

**The field** (`homeField`) is the default format's, the one
`/api/formats` names (`docs/frontend.md`, "Filters are in the address"), and both of its
titles name it: the card is "The Modern field, and you against it"
(`FieldAgainstYou`), and as one of the three things it reads "Two decks
are 41% of the Modern field" (`fieldTitle`, `ThreeThings.tsx`). It is
read from the first ranked tier with lists in the window — A, then B,
then C, then D (`firstTierWithLists`), the same rule the Field page's
default share uses. Six decks at most, each a `FieldRow`
(`components/field/`), the row the Field page draws too. The window
starts at the format's reset, else 90 days back, which is the Field
page's own default: a bare `/field` and Home ask `useMetaPresence` with
the same window and format, so they share one request. Under each deck's
name is the viewer's record against it in the same window
(`recordAgainst`), counted over the finished matches in the same format
(`matchesInFormat`: a match's `format` from `/api/matches`; a match with
none counts toward no format) whose opponent carries both that row's
archetype key and its label, for one deck: the deck of the newest match
in the format that has one, in every version of it. With no such match
the record is over every deck in the format. The art is the newest
finished match in the format against the first row's deck. The card
names whichever tier it landed on in words (`tierKind` in `lib/field.ts`, the `field.tier.kind` keys): "paper
tournaments of 64+ players" for A, "MTGO challenges" for B, "MTGO
leagues" for C, "paper tournaments under 64 players" for D.

### Art

`lib/matchArt.ts` chooses a match's art. `castCards(detail, side)` is the
cards one side cast in the match, distinct, the card first cast latest
in the match first: what the match turned to, not its opening plays.
`takeUnused` takes the first of them not yet on the page, so **one card
appears once on a page**. Home takes them in the page's order: the hero
(the viewer's, from the newest finished match), the last match (the
opponent's), the pattern (the viewer's), the field (the opponent's, from
the newest finished match against the field's first deck), then each
deck tile (the viewer's, from that deck's newest finished match).

**Art comes from a finished match only**, because `useMatchArt` reads a
match's detail once and never again (`docs/frontend.md`, "Data fetching"): a match
still in progress would keep the cards it had when the page opened.
Seven matches at most: the newest, the field's (asked for only when the
field is among the three things) and one for each of five decks.

### The clock

`HomeView` renders once a second (`useNow`), so that "22h ago" stays
true. What it counts moves with the minute, not the second: a count
that reads the time takes the minute's start, and is memoized on it.

The win rate by week reads less of the clock still. `WeeklyWinrate` is
wrapped in `memo`; it takes the weeks, which are rebuilt only when the
list changes, and the start of the current year in place of the time,
since a short date reads the time for its year alone. So it renders when
the weeks or the year change and at no other time. It has to: see
`docs/frontend.md`, "Charts". The chart is also mounted anew when its box changes
height (`key={chartHeight}`), which opening the numbers under it does,
so the line draws in at its new size.

### Dates and numbers

Home's dates and numbers come from `lib/time.ts` (`formatLongDay`,
`formatShortDay`, `formatIsoDateShort`, `formatDayTime` and
`formatCount`), which draw on `lib/format.ts`: they follow the
language the dashboard is read in, `en-US` in English, never the
browser's own locale. A moment is shown in the viewer's own zone.
`formatLongDay` and `formatShortDay` add the year when it is not the
current one; `formatDayTime` never shows a year. A date the API sends
bare (`YYYY-MM-DD`, a format's reset) goes through `formatIsoDateShort`,
which reads the date from its own parts and through no zone, so it cannot
land on the day before. A week starts on Monday at 00:00 in the viewer's
zone (`weekStart`).

Every timestamp Home reads goes through `parseTimestamp`, the one
place a timestamp is read: one with no zone is the log's own clock, read
as local time. `lib/home.ts` reads none any other way.

A percent, a record and a small sample are written by `lib/format.ts`'s
`formatPercent` and `formatRecord` and `lib/sample.ts`, never by Home's own
code (`docs/design-system.md`, "Numbers").

`lib/format.ts`'s `formatFixed` writes a number to fixed places in the
language's separators, but rounds the shortest decimal that names the
number, not its binary value: `formatFixed(1.005, 2)` is "1.01", where
`(1.005).toFixed(2)` is "1.00". A value that was read with `toFixed`
before can differ in its last digit.

### Layout

Columns begin at 64rem (`lg`): the recent matches take two thirds beside
the weeks, and the field two thirds beside the coach. Two things change
at 48rem (`md`) instead: the hero's art moves from above the words to
their right, and the three things go from a column to a row. The deck
tiles are two to a row, three from 48rem and five from 64rem.

### The places with nothing to show

Live, Matches, Decks, Field and Coach each draw an `EmptyState`
with the place's own icon (`placeById`), a title, and one sentence that
says what will appear and what causes it:

- **Live** shows a `Callout tone="warn"` with `shell.liveStatus.notWatching`
  above the empty state while the tracker is not watching. When
  `/api/live` says `watcher_stopped` (the watcher died after starting) it
  shows `shell.liveStatus.watcherStopped` instead, and above every branch: a
  match in progress, the opening hand, the break and the empty state,
  because a watcher that dies mid-match leaves the match frozen on screen.
  It is a `shrink-0` item, so focus mode's height cap holds. `CurrentMatchView`
  chooses the sentence and `liveState` (`lib/home.ts`) the pill's
  state; Home's first step uses the same sentences. Live is in
  focus mode, where the live status is not drawn from 48rem up, so the
  page says so itself.
- **Matches** tells "No matches yet" from "No match fits these filters"
  by the heartbeat's count of matches, and the second offers "Show every
  match". With no match in the list the summary band is not drawn. Until the
  heartbeat has answered, an empty list shows `Loading`, since the page
  cannot yet tell the two apart.
- **Coach** shows the empty state alone, with too few matches and no
  report written before, and only once the coach has answered: a
  request that failed says it failed. A report written before is
  still shown when the matches are too few.
- **Field** says that the server downloads tournament results on its own
  while it runs, and that `sensei-top meta` does it from the command line.

## Matches

`/matches` is `MatchHistoryView`: a band of two numbers, then the list,
both under the source and deck filters.

**The list asks for 500**, the route's maximum, and shows 50 rows at a
time, with a button that shows 50 more. A caption over the rows says how
many are listed, and with 500 in hand a caption under the last row says
the list stops there. The shown count starts again at 50 when a filter
changes.

**The band** (`components/MatchesSummary.tsx`) is matches won and games won,
counted in the client over every match in hand, not only the rows shown, so
the band and the list can never disagree. A finished match is a win, a loss
or a draw, and a draw is neither won nor lost. Each tile follows "Numbers"
in `docs/design-system.md` (`rateOrRecord`): from ten finished the rate,
"58%", with the record under it; from five to nine the rate, muted, over the
record and "rough"; under five the record as the number, muted, with a line
saying it is too few for a rate; with nothing finished an em
dash and a line that says so. The band is not drawn from
`/api/metrics/winrate` or `/api/metrics/play-draw`, which did not answer for
every source when the page was built; they do now, and play and draw are
still to join the page (`BACKLOG.md`, BL-023).

**A row** (`components/MatchRow.tsx`) is one link to its match, at least
44 px high, with no button inside it. Home's "Recent matches" draws the
same row. On Matches the row carries one more caption, the event in
words and the rank. From 48rem up a row is a grid (when, result, the
opponent's deck, the viewer's deck, event and rank); under that it
stacks.

**The event in words** is `eventLabel` (`lib/events.ts`). The names
known are written out in a table. Any other id is respelled and never
looked up: the trailing date goes, underscores become spaces, and a set
code stays as it is stored, so `QuickDraft_SOS_20260831` reads "Quick
Draft, SOS". A match with no event shows nothing in its place, since no
event does not mean MTGO.

**The deck filter never says "All decks" over a filtered list.** A deck
in the address that `useDecks` does not list is shown in the select as
an option of its own, selected.

Correcting the opponent's deck is done on the match's own page, which
shows `OpponentDeckLabel` for every match.

## The turn-by-turn view is a Magic table

It lives only on the replay's page (`/matches/:id/replay`,
`MatchReplayView`). Live has no turn history: it shows the current-match
reads, taken from the latest turn or from a fresh live replay
(`docs/current-match.md`), and nothing per turn. A flat list of cards
drawn and played is a history, which `TurnByTurn` owns, so Live stays a
snapshot and links to no match's page.

### The replay's page

Top to bottom: the way back to the report, the games as a `Segmented`,
"Sideboarding" (`components/match/SideboardingCard.tsx`, drawn when the
game has any), "Turn by turn" (`TurnByTurn`), then the game's numbers
(`components/match/GameCharts.tsx`).

**The game and the turn are in the address**: `?game=2&turn=5`. No
game, or one the match does not have, is the first game. No turn, or one
the game does not have, is the game's last turn. `turn=0` is the opening
hand, when the game has one. Choosing a game or a turn replaces the
history entry, so Back leads to the report, and choosing a game drops
the turn. A reload keeps both.

**The charts do not move when the turn changes.** recharts starts a
chart's draw-in over whenever the chart renders again, so `GameCharts`
is memoized and takes the query's own arrays as props, whose identity
does not change with the turn. `isAnimationActive={false}` is not the
way: the draw-in is wanted once.

`TurnByTurn` shows **one turn at a time**: a `TurnScrubber` strip to
move through the game, a `BoardTable` for the chosen turn, and a short
list of what happened during it.

### The turns

`TurnScrubber` is a radio group named "Turns", as `Segmented` is one:
one tab stop (the chosen tick), the arrow keys move and choose, Home and
End go to either end. It does not wrap: the arrow keys stop at the first
and the last turn, since a game has a start and an end. A tick is at
least 44 px in both directions. The strip scrolls inside itself and
brings the chosen tick into view.

A tick shows the turn's number, "Open" for the opening hand. In a game
with a board, a bar under the number says whose turn it was and the two
lives are under it; a legend line under the strip says what each means.
A screen reader hears the tick's name in words ("Turn 5, your turn").
Those words are visually hidden, which positions them absolutely, so the
strip is `relative`: without it they are laid out against the page and
make it wider than the window. The same holds for each battlefield row.

### The board

`BoardTable`'s layout is not a visual choice; it follows how a 1v1 table
is arranged (MTR 4.7):

- **Mirrored across a center line.** The opponent's half on top, yours
  below, each the other rotated 180°.
- **Outer edge inward: hand, lands, nonlands.** MTR 4.7 requires
  nonlands to sit closer to the opponent than lands, so both nonland
  rows end up against the center line, where combat would happen.
- **Library, graveyard and exile are one group per half**, adjacent and
  distinct: a column beside the rows from 48rem up, a line under the
  player's name under that. A graveyard or an exile with cards is a
  quiet `Button` with `aria-expanded`; open, its cards are a block of
  `CardTile`s under the opponent's rows or over yours. One pile is open
  at a time, and it closes when the turn changes.
- **Tapped is a quarter turn**, Magic's only rules-sanctioned
  orientation signal. The slot takes the turned card's bounding box, so
  neighbours do not slide under it, and a screen reader hears "tapped",
  so orientation is never the only carrier.

Cards are 64 px wide at every width of the page. Each row has its label:
beside the cards from 48rem up, over them under that, so a label never
shares a line with its cards on a phone. A battlefield row scrolls
inside itself; a hand wraps.

**What is known about a card is written under it**, in a caption as
`CardTile` writes one (`docs/design-system.md`, "Card art"): power and
toughness, "New" for a permanent that entered this turn, "Drawn" for a
card drawn this turn. Nothing is laid over a picture or around it. A
line under the board says what "New" and "Drawn" mean, and only when
some card carries the word.

"New" comes from comparing the chosen turn's `instance_id` set with the
turn before it: two stored snapshots compared, not an inference. Turn 1
carries no "New", since with no turn before it every permanent would.

Three rules about what it must *not* do:

- **State and events stay separate.** The board is how things stood at
  the end of the turn; the list under it is what happened during it. A
  creature cast that turn is on the board and in the list, each for its
  own reason.
- **Never invent a side.** `is_self` is `null` when Arena never named
  the viewer's seat. `BoardTable` says so in a sentence, and draws no
  half, since the cards were recorded and whose they were was not.
- **Never draw a board that was not recorded.** An MTGO game has plays
  and no board (`docs/status.md`). Its strip has ticks from 1 to the
  highest of its turn count and its plays' turns, with no bar and no
  lives; one sentence stands in the board's place; its plays are listed
  turn by turn; and no chart is drawn, since there is nothing to plot.

## The current-match reads

`useCurrentMatchRead` (`api.ts`) backs `OpeningHandCard`, `KeepGuideCard`,
`OpponentHandCard`, `OpponentRead` and `LibraryCard` — see
`docs/current-match.md` for what each one computes and why, and for the
four-phase layout (`CurrentMatchView`) that decides which of them is the
base render's primary card and which sit in its rail at any given moment;
the disclosure bar holds the matchup brief and nothing else. They replaced a
you-vs-opponent scoreboard and a `HintsPanel` that restated
life/hand/library/mana Arena already shows on screen. A fifth read, this
deck's recent opponents (`RecentOpponentsCard`), was added and later removed
outright: a match's own opponent history is a research question, not
something worth a permanent slot on a screen meant to answer "what do I do
right now" — the tab's real estate went to `LibraryCard` instead, the tab's
own answer to what survived from `HintsPanel.tsx`'s next-draw-odds table.
Unlike that table (client-side, capped at 8 rows, computed against a stale
`turns` row), `LibraryCard` is the tab's *primary* panel once a game is
under way: the whole remaining library, server-side, sourced from the same
fresh live replay as everything else on the tab, no row cap. Every card here
hides itself rather than rendering an empty card when it has nothing to say
— no library data yet, no consensus for the opponent's archetype, no
mulligan decision currently pending.

The page is `/live`, and what it draws in each of its four states (a
break between games, a hand offered, the mulligan phase, a game under
way) is in `docs/current-match.md`'s "Frontend", with the strip at
the page's top and the lines under each row of cards. Once a game is
under way the rail is the opponent's: their hand, then the deck read;
the keep guide is drawn only before the first turn. Advice (the keep
guide, the opponent-hand estimate, the brief) shows in casual and ladder
games, never in an event's, and Settings' "Advice during a game" hides it
everywhere (`docs/current-match.md`, "The event rule"). Under 48rem the
page scrolls: the strip takes two lines and cuts none of its facts.

Each fact is shown once on this page. The status strip alone carries the
game, the turn, play or draw, the record, the opponent's deck with its
confidence, the cards seen and the pick button; `OpponentRead` holds the
cards behind an unnamed deck and the candidates, `LibraryCard` is the
decklist, and between games the plan card's title is the result and its
reason, with the opponent and the next game left to the strip, and its
first line this deck's own games 2 and 3 against that deck. The old
"Match details" disclosure that repeated the strip is gone.

`useCurrentMatchRead` rides a 1s timer of its own on top of the ordinary
heartbeat, unconditionally whenever `CurrentMatchView` is mounted — the one
scoped exception (besides `/api/live`) to "nothing refetches on its own
timer," and it exists
because the opening-hand read's decision window has a measured 5-second
median in real play that the ~3s heartbeat alone would eat too much of. It
used to gate on a match actually being in progress (a `matchInProgress`
flag); that gate is gone, since the request it drives replays only the
current match (see `docs/frontend.md`, "Data fetching", and
`docs/current-match.md`, "The live replay (`table/live.py`,
`projector/live_state.py`)", for its cost).

An AI-suggested line of play (`AskClaudeCard`) used to live in this tab too,
asking *what should I do on this board right now* — a question the
projector cannot answer mid-match (no combat, no stack, no opponent hand).
That is retired. "The live matchup brief" below asks a different
question — about two decklists, not a board — which is why it is worth
writing down once and reusing.

## The live matchup brief

`MatchupBriefCard` (`components/MatchupBriefCard.tsx`), reachable from
Current match's disclosure bar rather than rendered inline, is what to play
around against this match's opponent and a game-2 swap plan — the useful
half of the deck guide's §6, reachable while a game is actually on the
clock. See `docs/brief.md` for the design.

A brief is written once per `(deck, archetype)` and reused in every future
match against that archetype, so the common case is that one is already
stored — either from an import, or as a side effect of generating a deck
guide (`docs/llm.md`) — and this renders instantly off the heartbeat. When
none is, `CopyPromptCard` offers the text to write one from and the exact
`sensei-top brief --import` command line to save the answer.
Deliberately no generate button here, unlike the match report and the deck
guide: generating the guide already fills this cache for every matchup it
covers, so a second button on this card would mostly duplicate a call the
guide already made (`brief/narrative.py`'s own docstring).

Each status gets a distinct, honest answer rather than one generic empty
state: `no_match` renders nothing (`CurrentMatchView`'s own empty state
already covers "no game in progress"), `unclassified` says the opponent
is not identified yet, `format_unknown` says no tournament format is
known for the user's deck, so there are no lists to write from (`docs/frontend.md`, "Say
what you mean in the UI" has the text), `no_consensus` says the corpus
has too few decks of this archetype to write from, `prompt` shows the
copy-prompt card, and `ok` renders `BriefBody` — the play-around list
(struck through once a card has actually shown up this match, the same
trick `OpponentHandCard` uses for its own revealed-card chips), the
IN/OUT plan with any `PlanProblem` shown inline rather than hidden, and
the prose.

## The opponent-deck read

`OpponentRead` (`components/OpponentRead.tsx`) replaced a card that used to
appear only below `'low'`/`'unknown'` confidence and, once shown, offered
nothing but the classifier's own single guess. It draws no headline: the
deck's name, its confidence (or "picked" for a manual override), the
colours, the count of cards seen and the "pick this deck" button
(`PickDeckButton`, from the same file) are the status strip's alone ("The
status strip", `docs/current-match.md`), so the card does not repeat them.
What it holds is the cards seen, when the deck is unnamed (the strip's
label falls through to the colours-and-signature-card layer at that point,
same as `v_match_opponent` always did), listed through `formatList`. Below
`'high'` confidence it also shows the top few candidates from `GET .../opponent-deck/candidates` —
label, a bar sized to `fit`, and `reasons` (matched cards, or a colour the
definition needs that the opponent hasn't shown) — instead of asking the
player to trust a label that may have named itself off one generic card
early in the match. See `docs/opponent-deck.md`'s "Naming the opponent's
deck" for why fit, not a raw condition count, is what `classify.py` ranks
on. With neither the unnamed deck's cards nor a shortlist, the card is
not drawn.

`OpponentDeckLabel` (`components/OpponentDeckLabel.tsx`), the compact
label and picker on a match's own page (`MatchHero.tsx`), and
`PickDeckButton` share one `DeckPicker` popover: a filter box over every
definition for the match's format, not only the classifier's own
shortlist, offered at any confidence rather than only when the
classifier reports doubt, since a wrong `'medium'` or `'high'` guess is
exactly as correctable as an uncertain one. `MatchRow`, the row of
History and Home, draws its own opponent's deck in the row and offers
no picker.

When no archetype matched, `v_match_opponent` builds the label from the
colours and a signature card (`UR · Mox Opal`, migration 030). Wherever a
`ManaPips` sits beside that label — `OpponentDeckLabel`, the Matchups table,
the current-match band — `lib/opponent.ts::opponentLabelText` strips the
`UR · ` prefix, so the colours read once, as pips. It is display-only:
`opponent_key` and the stored label keep the prefix, and nothing matches on
the stripped text. A label with no pips beside it (the match-detail heading)
keeps its letters, since they are the only place
the colours appear.

## The MTGO deck pick

MTGO's log never names the user's deck, so an MTGO match's page carries
`MtgoDeckPick` (`components/match/MtgoDeckPick.tsx`) under its hero, and an
Arena match's page does not. The user always confirms. What the server
infers only orders the choices and pre-fills the format (plan 12, D1).

Unanswered, the card asks "Which deck was this?" and lists the
candidates from `GET .../mtgo-pick/candidates`: every MTGO deck, best
match first. Each choice shows the deck's name, how many of the cards
played in this match its list holds, and a few of its cards, since
MTGO's own exports are named by number. The last choice is "No list",
which confirms the format alone. Choosing a deck sets the format to the
candidate's `format_prefill`: the deck store's format, else the format
last confirmed for the same deck, else the format inferred for this
match from the cards it revealed, else none. While the chosen format is
still the pre-fill, a caption under the select says which of the three
it came from (`mtgo.prefill.*`, by `format_prefill_source`): "Pre-filled
from the format MTGO files this deck under.", "Pre-filled from your last
pick for this deck." or "Pre-filled: inferred from the cards revealed in
this match." Once the user picks another format the caption goes.
Choosing "No list" keeps whatever format is already chosen. The user can
change it in the format select, whose options are `/api/formats`'
formats in its order (`mtgoFormatsOf`, `lib/mtgoPick.ts`), and
`MTGO_FORMATS`, the seven formats the route takes, while that has not
answered. Confirm needs a deck, or "No list" with a format
(`canConfirm`). A deck with no format is a valid answer; a format with
no deck question answered is not.

Answered, it is a "Your deck" card that reads the deck and the format, with
a Change button that reopens the choice, starting from the existing pick.

## Picking many MTGO matches

`/mtgo/picks` (`pages/MtgoPicksPage.tsx`, `views/MtgoPicksView.tsx`)
answers many waiting MTGO matches at once, from `useMtgoPickGroups`
(`GET /api/mtgo/picks/candidates`; the grouping rule is in
`docs/architecture.md`, "Picking many MTGO matches at once"). It has three
sections: "Fits a saved list" (sure groups), "Close to a saved list"
(partial groups, collapsed) and "Pick one at a time" (unsure matches, each
linking to its match page, where the single pick is made). Each group is a
`PickGroupCard` (`components/mtgo/PickGroupCard.tsx`): the list's name, the
count and dates, the cards played from it, for a partial group the cards
played that it lacks, the format select with the single pick's pre-fill
caption, any "also close" lists with a switch, and the matches behind a
disclosure, each of which can be left out. Its state and the items it sends
are `lib/mtgoPicks.ts`. Confirm sends one `PUT /api/mtgo/picks`; the page
then refetches and says how many matches now count toward the list. The
hints come from `useMtgoPickHints`, a separate request that starts once the
groups have drawn; until it answers, or when it fails, the hint line is
simply absent.

## The match report

`/matches/:id` is the report: `MatchDetailView` draws the way back to
the list, the hero, and `MatchReportPanel`
(`components/MatchReportPanel.tsx`), which renders
`GET /api/matches/{id}/report`. The games turn by turn are on the
replay's page, one address further. AGENTS.md rule 5 and
`docs/review.md`, "The match report, and its optional narrative",
say why advice is given after a match and not during one.

**The hero** (`components/match/MatchHero.tsx`) has Home's shape: the
art at the right with a fade to the left, on top with a fade down under
48rem, and no word on the picture. The art is a card the opponent cast:
the one whose first cast came latest in the match, as on Home
(`castCards`, `lib/matchArt.ts`), or the viewer's own when
the opponent cast nothing, or none. The words are a label line (the
event in words, when), the report's headline and subhead, then the two
decks: the viewer's as `MatchRow` writes it, the opponent's as
`OpponentDeckLabel`, which is the way to correct it. Last, a `Button`
that leads to the replay. Until the report has arrived, or when it has
nothing to say, the title is the result and the games' count from the
match itself.

**The games** (`components/match/GameCard.tsx`): one `Card` per game of
`summary.games` (`review/summary.py`, `docs/review.md`), in game order,
in a grid that fits as many columns as hold 16rem each. A card has the
game's title and its result as a chip (a game with no result carries a
muted chip that says so); the game's position line, memoized; the facts
as a `dl` (seat, mulligans, length, how it ended), a fact that is not
known not drawn; the game's beats, three at most; and a link to that
game on the replay. A beat is its label, its meter when it has one
(`TwoSidedMeter`, `components/ui/Meter.tsx`, in the colours every chart
uses for the viewer and the opponent), its sentence, and its weight as a
chip when it is more than a note. A game with no position line draws no
chart and no box for one. Under the grid, one sentence says what the
line is, and a `Disclosure` holds its numbers as one table.

**The position line** is `review/position.py`'s index, which
`MatchReportOut.position_track` carries; nothing computes it in the
client. It is the one chart whose zero line carries meaning (ahead or
behind), so that line is drawn heavier (`ink-2`, 2 px) than a gridline.
The turning point's own turn is a `ReferenceDot` on it. The replay draws
the same line larger (`PositionTrack`), and under it three `TurnChart`s
(life, hand, board) that share one legend, drawn once over the three,
and one recharts `syncId` (`match-charts-{game_number}`): a turn under
the pointer on one of them is marked on all three.

**What stood out** holds the findings that weigh more than a note,
heaviest first, then by game and turn. A finding's weight is a `Chip`
through `severityChip` (`components/ui/severity.ts`), the mapping the
coach draws its own with: `decisive` takes the `accent` variant, `flag`
takes `warn`, `notice` takes `neutral` and `note` a muted `neutral`. The
label is always the word; colour is reinforcement only. A finding's body
is its detail, then every caveat, then its evidence behind a
`Disclosure`, without the rows whose value the title already says
(`evidenceIsRedundant`). A finding whose `confidence` is `partial` says
so in words after where it happened, and one line under the list says
what that means, drawn only when some finding shown is partial. Every
other finding is under them behind a `Disclosure`, drawn the same way.
The analyzers' category names are the code's words and are not on the
page.

**Beside the findings** from 64rem up, under them below that: "This
pairing" (the matchup's beats, not drawn without beats), the gaps, and
the coach's summary.

**Gaps have a card of their own, "What this report could not see", and
are never mixed with the findings.** This is rule 4 made visible: a
report with nothing to say about a turn must not read the same as a
report that checked and found it clean. They are `summary.gap_groups`,
so gaps that share one cause (`Gap.cause`, `docs/review.md`) stand under
one heading: the cause, with what it blocked under it. Four are shown
and the rest are behind a `Disclosure`.

**The columns swap when no finding weighs more than a note**, which is
every MTGO match: from 64rem up the gaps take the wide column and "What
stood out" heads the narrow one (`GapsLead`). The cards are one grid's
children at every width, so a card keeps its state when the window
crosses 64rem. With no gaps either, the report is one column.

`ReportNarrativeCard` starts closed behind a "Show the coach's summary"
button, since building the prompt means building the whole report's
context, which is not worth doing each time a match is opened. Open, it
is a `GenerateCard` that carries the game's turn-by-turn shape beside
the findings, and never a raw hand or graveyard. Unlike the guide it has
no command-line importer: a match review is read once, about a game
already played, so a stored narrative comes only from the generate
button (`docs/review.md`).

## Decks

`/decks` (`pages/DecksPage.tsx`) is one tile per deck, an identity of
`GET /api/guide/decks` however many versions its list has had, in the
order the route answers them, last played first. `decksTiles`
(`lib/decks.ts`) builds each tile: the deck's own name, its record by
the small-sample rule (`deckRecord`: from ten finished matches a rate over
the record, "58%" over "35–25"; from five to nine the rate, "67%", muted,
over the record and "rough"; under five the record, "3–1", muted, with
the line saying it is too few for a rate), the format in words with how
many versions when there is more than one (`tileDetail`), when it was
last played, and its art: a card the viewer cast in the deck's newest
finished match of the same 500-match list Home reads, one card per
page. A deck with no finished match in that list keeps the empty art
box; nothing more is asked for it. The grid is Home's own: two to a
row under 48rem, three from there, five from 64rem. With no deck at
all, "No decks yet".

A tile leads to `deckAddress(key)`: `/decks/` and the identity's own
key (`addressSegment`, its colon written bare). `/decks/:id` and the
four addresses under it (Matchups, a pairing, the Guide, the RCQ tab)
share `pages/DeckLayout.tsx` (`docs/frontend.md`, "A deck's pages").

**`?version=`** names one of the deck's versions to read alone;
absent, unrecognized, or on a deck of one version, it means every
version (`chosenVersion`, `lib/deckOverview.ts`). `VersionSwitcher`
writes it by replacing the history entry and keeping the scroll, as
`useFilters` does for the address filters, and the Overview, Matchups
and a pairing each draw it when the deck has more than one version.
`useDeckMatches` and `useDeckPlayDraw` (`api.ts`) fan one request per
entry of `versionIds` out with `useQueries` and combine them
(`AllQueries<T>`, its `all()` combiner): `data` is set only once every
version has answered, and one failure is the whole read's error. Each
version's matches are asked for at `DECK_MATCH_LIMIT` (500, the route's
own maximum).

**The deck strip** (`components/DeckKeyNumbers.tsx`) sits under the deck's
name and its line, over the tabs, so every tab shows it: three `StatTile`s
(`deckKeyNumbers`, `lib/deckOverview.ts`), in one row from 48rem and
stacked under it, then a caption. It reads the versions the tab reads
(`versionIds`), so on the Guide and the RCQ tab, which drop `?version=`,
it is every version.

- **Matches**: the finished matches' record by the small-sample rule
  (`rateOrRecord`), a draw counted toward neither side.
- **Games**: the same over every match's games won and lost, finished
  match or not.
- **Play vs draw**: with ten games on each side, the gap in points
  between the two whole percentages (the figure and the line agree, since
  the percentages are subtracted, not the raw rates); with fewer on
  either side "too few", muted; with no game on either, an em dash. The
  line names both sides, the play first: "58% on the play · 50% on the
  draw"; a side under ten games is its record, and one with none is
  "no games".

The caption says the games are counted per game, over the games whose first
player is known, and, when a version's list was cut at `DECK_MATCH_LIMIT`,
how many matches were counted. This is the one place that is said: the strip
is the first thing on every tab drawn from that list.

The strip and the Overview ask for the same matches with the same query
(`useDeckMatches`), so the strip costs no second request. While either read
is pending it keeps its height, with its labels and empty tiles, so the tabs
under it do not jump; a detail that wraps once loaded (some widths between 768
and about 1100 px) moves the tabs by that line, once. When the matches or
the play-draw read fails, the strip's place is an `ErrorNote`: the Guide
reads neither, so nothing else on that tab would show the failure. A
failed matches read therefore shows two notes on the Overview, Matchups and
a pairing, the strip's and the page's own.

One known gap in Play vs draw: `/api/metrics/play-draw` has no games-lost
field and its `games_completed` counts draws, so a drawn game lowers a
side's rate and reads as a loss in its record (`docs/design-system.md`,
"Numbers"; the debt is `BACKLOG.md`, BL-045).

**The Overview** (`DeckOverviewView`, `views/DeckOverviewView.tsx`) is,
top to bottom: the version switcher; a "By rank" table (Rank · Matches ·
Record · Rate), shown once the matches in hand were played at two ranks or
more; a "Versions" card, one row per version, each a link that chooses it
alone, its second line "58% · 35–25" from ten finished matches and the
record alone under it, shown only when every version is being read and the
deck has more than one; and last, the deck's Matches card. The summary
band and the three play-draw tiles it used to hold are the strip's now. A
version chosen with no match against it says so, with a link back to
reading every version.

**Matchups** (`MatchupsView`, `views/MatchupsView.tsx`) is one row per
archetype the chosen versions have met, most met first: pips and name (a
link to the pairing), and a line under it with the games, own first, and,
once the field's numbers are in, how the archetype wins in tournaments over
however many entries, marked too few to trust under five
(`MIN_TRUSTED_FIELD_SAMPLE`). The columns are Archetype · Matches · Record ·
Rate · Game 1 · Games 2–3, in the order `docs/design-system.md`, "Numbers",
gives; the Rate cell (`RateCell`) is the rate from ten finished matches,
the rate muted from five to nine, a muted "too few" under five, and an em
dash only with no match won or lost. Game 1 and Games 2–3 count games,
and only a best-of-three match's (`best_of = 3`): a best-of-one game is a
different queue's, with its own hand smoothing, and is in neither. Each
cell is the rate alone, as the Rate cell is, over games: the percent from
ten games won or lost, muted from five to nine, a muted "too few" under
five, and an em dash with none, which is also what a row with no
best-of-three match shows; a drawn game counts in neither number. A row is never left out for
being small. The field is the deck's own format's
(`useFieldRecords(format)`, the format coverage names, "Field, and the
field-winrate join" below); a deck with no format has no field line. Three
tiles sit above the table: archetypes met (and how many were named), and the
best and worst among those met ten finished times or more
(`RATE_MIN_MATCHES`) by wins over wins plus losses, the threshold at which
the table's own "Rate" column stops being muted, since a ranking of rough
rates would rank noise; with none that often the tile says so, and
with one it is the best and the worst says there is only one so far. There
is no chart: a row already shows the pips, the name, the games and the
field's own rate beside them.

**A pairing** (`PairingView`, `/decks/:id/matchups/:opponent`) is one
deck against one opponent's deck, `:opponent` a Matchups row's own
`opponent_key` (`pairingAddress`: its colon bare, a `/` written `%2F`
for a double-faced opponent name). Its heading draws the opponent the
way a Matchups row does when a match is in hand; with none, an
`archetype:` key is named from the deck's own coverage (shared with the
brief below, one query) or spaced from the key itself, a `manual:` key
as typed, a `colors:` key "Unrecognized deck", anything else "Unknown
deck". Three tiles, five when the pairing has a best-of-three match:
Record (by the small-sample rule over the row's wins and losses, so it
agrees with the Matchups row, a draw counting toward neither), Games (own
first, "17–4"), Game 1 and Games 2–3 (the same split as the Matchups row's
two columns, by the small-sample rule over games), and In tournaments (the
field's rate for the archetype in the deck's format, over the same window
`useFieldRecords` gives Matchups). Below the tiles is the matchup brief
against this opponent (`components/PairingBrief.tsx`, `docs/brief.md`)
in one of five states (`briefState`, `lib/pairing.ts`): not named (the
key is not an archetype), written, with a warning and "Write it again"
when the deck's coverage says the list or the field moved since; and,
with no brief stored, no tournament format known for the deck
(coverage's `fmt` null, `matchups.brief.formatUnknown`), too few tournament
lists to write from yet, or not written with a "Build the prompt"
button. A prompt the route answers `format_unknown` or `no_consensus`
says the same in the prompt's place. Last, the deck's Matches card, this
pairing's matches alone.

**`MatchRow withDeck={false}`** is what both the Overview's and a
pairing's Matches card draw (`DeckMatchesCard`, shared by both): the
row leaves out the viewer's own deck, column and all, since the page's
own title already names it.

## The RCQ page

`/decks/:id/rcq` is `DeckRcqPage` (`pages/DeckRcqPage.tsx`), the deck
layout's fourth tab ("RCQ"), beside the Guide; like the Guide it reads the
deck whole and drops `?version=`. `/decks/:id/guide/rcq`, its address in
1.0.x, is `RcqRedirect`: it replaces itself with the tab and keeps the
search and hash. It hands the deck key to `RcqView` (`views/RcqView.tsx`, parts
in `components/rcq/`; pure helpers in `lib/rcq.ts`). Inputs card: the
pasted 75 (prefilled with the deck's list, editable), the expected
archetypes as chips from `/api/metagame/presence` over the last 14 days
of the deck's format (`CHIP_WINDOW_DAYS`; the format is the guide's
`field.fmt`, and nothing is asked before the guide answers), and an
own-archetype picker only when the preview says the list could not be
classified. The inputs persist in `localStorage` per deck key, and the
preview query is debounced. A deck with no format has no field to pick
from, so the "Expected at the store" block is not drawn at all, and
expected archetypes stored from before are left out of the preview's key
(`RcqView.tsx`), so they reach neither the preview nor the guide's
request. Then the preview (counts, warnings, freshness per source; with
no format, one line in place of the expected archetypes, the freshness
and the recent events), `GenerateCard` with the prompt behind its
toggle, and the latest stored guide with "Copy as Markdown" and
"Download .md" (`docs/guide.md`, "The RCQ guide").

## The Deck guide tab

`/decks/:id/guide` is `DeckGuidePage` (`pages/DeckPages.tsx`), which
reads `deckKey` from the deck layout's outlet context and hands it to
`GuideView` (`views/GuideView.tsx`), keyed on that key so moving to
another deck starts the page afresh. The view has no deck picker of its
own: the deck comes from the address alone, and the Guide reads the deck
whole, whichever version was played.

**The sections, and where they live.** `GuideView` reads `useGuide` and
`useGuideNarrative`, then draws whichever sections `guideSections`
(`lib/guide.ts`) returns for what the narrative holds, each inside a
`<div>` whose `id` is the section's. A section absent from that list is
not drawn at all. In order:

| id | Label | File | Drawn |
|---|---|---|---|
| `guide-scope` | Scope | `components/guide/ScopeCard.tsx` | always |
| `guide-how-it-works` | How it works | `components/guide/WrittenCards.tsx` | a written guide exists |
| `guide-your-play` | Your play | `components/guide/PlayCard.tsx` | always |
| `guide-the-list` | The list | `components/guide/ListCard.tsx` | always |
| `guide-the-field` | The field | `components/guide/FieldCard.tsx` | always |
| `guide-sideboard-plans` | Sideboard plans | `components/guide/WrittenCards.tsx` | the written guide has a plan or a problem |
| `guide-matchup-coverage` | Matchup coverage | `components/MatchupCoverageCard.tsx` | always |
| `guide-between-rounds` | Between rounds | `components/guide/WrittenCards.tsx` | the written guide has a checklist item |
| `guide-write` | Write and export | `components/guide/WriteAndExport.tsx` | always |

Right after Scope, and only once the narrative read has settled, a deck
with no written guide gets one `Callout`, "No written guide yet", saying
what the three written sections will hold and linking to Write and
export (`NoWrittenGuide`, in `WrittenCards.tsx`).

**Scope** is four `StatTile`s (record, tournament lists read,
rules-text coverage, the field's window), the format-reset sentence
when one was found, and the server's own gap sentences in a `warn`
`Callout` (`ScopeCard.tsx`). The page's title already names the deck,
so the card's own title is just "Scope".

**Your play**, in this order (`PlayCard.tsx`):

- up to four `StatTile`s: kept-seven and mulliganed records, a win's
  and a loss's median turns. A tile whose number the API does not send
  is not drawn.
- the deck's own patterns, one `LeakCard` (`elevation={2}`) each: its
  chip the leak's category, its two win-rate bars, and a `Disclosure`
  over that pattern's own matches as `MatchRow`s (`PatternMatches.tsx`:
  newest first, the first ten, a quiet button for the rest, and a match
  the shared match list does not hold counted in one sentence rather
  than drawn).
- the written guide's fix prose, when there is one, under the "Patterns
  in this deck's matches" label.
- the same patterns across every deck, behind one more `Disclosure`
  ("Across all of your decks, N patterns", not drawn when there are
  none), each match row naming its deck.
- the leak finder's cross-deck training plan as an accent
  `GenerateCard` (`LeaksNarrativeCard`, in `LeakCard.tsx`). It is
  unscoped, so it reads the same under any deck's guide, and it draws
  nothing when there is no report yet.
- when a key card first resolved: a `DataTable` from 48rem, a
  three-column grid a card under it.
- the board on your own turn: two tables, "Games won" and "Games lost",
  each only its own turns, side by side from 64rem, either absent when
  its side has none.
- behind one closed `Disclosure` a zone at a time, where won and lost
  games differ most.

**The list** (`ListCard.tsx`) compares the 75 with the winning lists of
its archetype (`guide/list_diff.py`); with no archetype matched it is an
`EmptyState`. Otherwise Maindeck and Sideboard each get a sentence
counting how many cards differ from the field, then the differing rows
(name, a `Chip` with the verdict's word when it is not `correct`, a
caption of what the viewer and the field play, and the written guide's
note on that card as `Prose` when it has one), then the rows in line
with the field behind one closed `Disclosure`. Possible duplicate cards
under two names are one `warn` `Callout`, the server's sentences as
sent.

**The field** (`FieldCard.tsx`) is the deck's format's field. A deck
with no format (`field.fmt` null) is an `EmptyState`, "No field to
show", checked before the next one; with no tournament shares at all it
is an `EmptyState` too; otherwise up to three `StatTile`s (the deck's
own archetype's win rate in the field, the most-played archetype, and,
only with a format reset, how many of the shown archetypes changed at
it), then a `DataTable` of every archetype's share. Its `Before` column
is left out when no row has a pre-reset share. A share too thin to trust
and a personal record that does not carry over are said in the row's
caption, in words; a record that does not carry over is muted as well.

**Sideboard plans** (`SideboardPlansCard`, in `WrittenCards.tsx`) is
the written guide's plan against each archetype it covers, in the
guide's own order, each a nested `Card elevation={2}`: the archetype's
name, then the prose beside a swap of "Bring in" and "Take out" lists.
From 64rem the prose is the left column and the swap the right one;
under 64rem the swap comes first. Any problem the plan-validation step
found is drawn inline in its plan. A problem naming an archetype no plan
covers is said once, at the top of the card, in a `warn` `Callout`. The
plan's body, `PlanBody`, is exported: a pairing's stored brief draws it
too.

**Matchup coverage** (`MatchupCoverageCard.tsx`) is always drawn,
written guide or not: three `StatTile`s (matches covered, field covered,
left to write); then, when any archetype lacks a brief or has an
out-of-date one, a "Write every missing brief" button that fetches the
prompt for all of them only when pressed and shows it in place with
`CopyPromptBody` and the import command; then a `DataTable` (Archetype,
Brief, Field) whose archetype cell links to that pairing
(`pairingAddress`), whose status is a neutral `Chip`, and whose field
share is a whole percent or a dash. No rows at all is an `EmptyState`. A
deck with no format (coverage's `fmt` null) has no rows and no tiles:
the card is one `EmptyState`, "Nothing to cover yet", with
`matchups.brief.formatUnknown` as its message, and a prompt for every missing
brief that answers `format_unknown` says the same in the prompt's place.

**Between rounds** (`BetweenRoundsCard`, in `WrittenCards.tsx`) is the
written guide's checklist, numbered as written.

**Write and export** (`NarrativeAndExport`, in `WriteAndExport.tsx`) is
an accent `GenerateCard` titled "Write the guide" or "Rewrite the
guide", its `staleNote` "The list has changed since.", beside "Export
the evidence", a card that fetches `GET /api/guide/{key}/markdown` only
once opened and shows it in a scrolling `TextBlock` with its own copy
button.

**The way between sections.** `SectionNav.tsx` draws two navs, one
shown at a time: from 64rem a sticky column at the page's right; under
64rem a strip above the sections whose links sit in one row that
scrolls sideways inside itself, never the page. The strip sticks under
the shell's own sticky header below 48rem and at the window's top from
48rem, where the shell's header is static. Both heights are read from
the page (`useStickyHeights`, a `ResizeObserver` on the strip and the
header) and written as `--guide-header` and `--guide-strip` on the
view's root; every section's `scroll-margin-top` is built from them
(`SECTION_CLASS`, in `GuideView.tsx`), so a link's target clears
whatever is stuck above it at any width. The current link is brought
into view by moving the strip's own scroll alone (`rowScrollTarget`,
`lib/guide.ts`), tracking a smooth scroll in flight so a fast run of
changes cannot leave it short. `useScrollSpy` (`lib/scrollSpy.ts`) is
one shared `IntersectionObserver` over every section, a section current
once it crosses into the top 30% or so of the viewport, and the two ends
of the page handled apart by `scrollEdge` and `spyCurrent`, pure
functions beside the hook in `lib/scrollSpy.ts`, tested in
`lib/scrollSpy.test.ts`. It subscribes again when the guide's read,
sometimes slow, resolves and the sections exist, not only once on mount.

`lib/guide.ts` holds the section list and the pure functions behind
these cards (verdict labels, a board's split into differing and in line,
a field row's caption, a pattern's win counts, timing-bucket labels),
each tested in `lib/guide.test.ts`. `lib/written.ts` holds `writtenLine`
and `writtenNote`, shared with every other written card (in `docs/frontend.md`).

## Field, and the field-winrate join

`/field` is `pages/FieldPage.tsx`, which reads the address's four
filters (`docs/frontend.md`, "Filters are in the address"), and `views/FieldView.tsx`, which
draws `metagame/`'s tournament corpus (`docs/metagame.md`) for one
format and the viewer's own record against it. Its cards are in
`components/field/`. Nothing is drawn but a `Loading` until
`/api/formats` answers. Top to bottom:

1. **The format** (`Select`, "Format"), with a caption under it, drawn
   whenever some format holds the viewer's matches or tournament events
   (`anyFormatData`). Its options are those formats, in the API's order,
   and always the selected one (`formatChoices`). The caption is the
   viewer's own matches in the format and where each one's format was
   read from (`formatCaption`), a part at 0 left out: "12 of your
   matches are Modern: 4 from Arena's log, 5 you confirmed, 3 inferred
   from the cards revealed.", or "None of your matches are Pauper." It
   stays above the empty state, the loading and the error below, so a
   format with nothing in it can be left.
2. **The controls** (`FieldControls`): the window, a native `<select>`,
   and the tier the share is counted in, a `Segmented` of the four ranked
   tiers — paper tournaments of 64+ players (A), MTGO challenges (B),
   MTGO leagues (C) and paper tournaments under 64 players (D).
3. **Three tiles** (`FieldTiles`): the lists read in the tier and
   window, the most played deck with its share, and the viewer's record
   against the two most played, over every deck of theirs in the
   selected format (`topTwoTile`, `lib/field.ts`). The third tile has
   five states: nothing played, an em dash and "not met" with the window;
   only draws, an em dash and "no finished match yet"; one to four matches
   won or lost, the record muted, with the "too few for a rate" line; five
   to nine, the rate muted, with the record and "rough"; from
   ten the rate, with the record and where it comes from ("with any of your
   decks"). Not drawn when the tier has no list in the window.
4. **"What is being played"** (`ShareCard`): one `FieldRow` per deck, the
   most played first, twelve and then a button for the rest. A row is the pips
   and the name, the viewer's record against it under the name in the one-line
   form (`rowCaption`: "58% · 35–25" from ten matches, the record alone, "6–3",
   under ten, "not played" with none), the share as a `Meter` in the field's
   colour (`s3`) and the number of lists. A caption under the list says what
   the bar and the record count; a second says the record is counted over the
   last 500 matches when Home's rule finds the match list full and short of the
   window (`listShort`); tier C adds a third, that a league publishes only its
   undefeated lists.
5. **"The events"** (`EventsCard`): the stored events of the share
   list's format, window and tier, newest first, twelve
   (`EVENTS_SHOWN`) and then a button for the rest. A row is the date,
   the event's name linking to its page (`eventHref`) and a caption
   (`eventCaption`): where the results were published, how many
   decklists ("standings only" for none) and, when known, the archetype
   that won. A copy set aside by dedup and an event with no deck are not
   listed. The card waits for the tier, so its request names the tier
   the share list counts.
6. **"How the field wins"** (`WinrateCard`): a `DataTable` of Archetype ·
   Matches · Win rate · Lists, over tiers A, B and D together whatever the tier
   control says, since a league publishes no losses to count. A row
   needs two finished matches (`WINRATE_MIN_MATCHES`). Rows are sorted
   by matches, then rate, then name: sorted by rate alone, the top rows
   would be decks of one list on a handful of matches. Twelve, then the
   rest.
7. **"Archetype against archetype"** (`MatchupsCard`): a `Segmented`,
   "Counted from", cumulative over paper 64+ alone, paper 64+ and MTGO
   challenges, or all three ranked tiers with rounds (`?pairs=A|AB|ABD`),
   then the rounds between two named decks, the most matches first,
   twenty and then the rest. From 48rem a table of four columns (Archetype ·
   Against · Matches · Record, the record written won–lost–drawn with the
   rate after it); under it each row is two lines. A rate on fewer than
   five matches (`MIN_TRUSTED_FIELD_SAMPLE`) is muted, and the count is
   always shown. When a step
   has no round and the next step's tier has lists in the window, the
   empty card offers a button that takes it.
8. **A paused source's line**, in a warn `Callout`, one for each source
   whose fetch is paused (mtgo.com or TopDeck), in the words of
   `holdLine` (`lib/sources.ts`, pinned in `sources.test.ts`). It is
   drawn under the empty state too. A source that is only waiting says
   so inside the disclosure instead.
9. **The TopDeck.gg credit**, a caption naming the format ("Modern
   tournament data from TopDeck.gg."), drawn only when the selected
   format's status counts a stored TopDeck event
   (`corpus_topdeck_events` > 0). A configured key that has fetched
   nothing for the format draws no credit, since none of its data is on
   the page. It sits on the page, outside the disclosure below, because
   TopDeck's API terms ask for a visible credit and link.
10. **"Where these numbers come from"** (`SourcesDisclosure`), a
    `Disclosure`, closed: the events stored by tier and the copies set
    aside, the age of the tournament results and of the archetype rules,
    the sources' table, a waiting source's line under it, and the commands
    to download them again when either is more than seven days old or was
    never fetched.

The page draws no chart: every number is a row, a table or a tile.

**The defaults.** The format is `/api/formats`' `default`, the format of
the viewer's most recent match that has one, else Standard (`docs/frontend.md`, "Filters are
in the address"). The window is the format's reset when the status has
one, else 90 days; `?window=reset` with no reset known means 90 days.
The tier is the first ranked tier with lists in the window, A, then B,
then C, then D — Home's own rule (`firstTierWithLists`). `?pairs=` is
`A` when tier A has lists in the window, else `AB` when tier B has, else
`ABD`. Every metagame read names the format. The status waits for
`/api/formats`, and the three metagame reads (`useMetaPresence`,
`useMetaWinrate`, `useMetaMatchups`) wait for `useMetagameStatus()`, so
no request goes out with a window guessed before the page knows whether
a reset exists; `docs/metagame.md`'s "Every field number that can pool
across the boundary, doesn't" says why that matters. The matchups wait
for the lists too when the address names no `?pairs=`, since the default
depends on them.

**Tiers are never blended in a share.** `useMetaPresence` returns every
tier's rows and the page keeps one tier's, because a league's count
(only its undefeated decks are published) added into a paper share
would favour whatever wins leagues.

**The viewer's matches** are read as Home reads them,
`useMatches(undefined, 'all', HOME_MATCH_LIMIT)`, every source and every
deck. Only the selected format's count toward a record (`ownCounts`,
`lib/field.ts`): a match's `format` is the one `/api/matches` sends
(`v_match_format`: the log's, else the MTGO pick, else the inferred
format), and a match with none counts toward no format. A record is
`recordAgainst` (`lib/home.ts`) with no deck named. Whether the list is
short reads the whole list, since the cap applies to it, not to a
format.

With no tournament event stored for the format the page is one
`EmptyState`, "No Modern tournament results yet", under the format
control when it is drawn. Its message says the server downloads results
on its own while it runs, and `sensei-top meta` from the command line;
a paused source's line follows it.

**An event's page**, `/field/events/<key>`, is
`pages/FieldEventPage.tsx`, which hands the address's splat to
`views/FieldEventView.tsx`. The key is the API's
(`GET /api/metagame/events/{key}`): the event's stored path without
`Tournaments/` and `.json`, so it keeps its slashes, each segment
encoded in the address. Top to bottom: the event's name; its date,
format and kind (`kindWords`); the source line or lines
(`sourceLines`), "Results from mtgo.com" or "Results from melee.gg"
linked to the event's own page, or for a TopDeck event the credit
TopDeck's terms ask for, "Data provided by TopDeck.gg.", and a line
linking the event there; for a league, that it publishes only its
undefeated lists; the read line (`readLine`) when the latest read found
the source's copy empty or gone (`docs/metagame.md`, "When a source
empties an event"); then every deck in the API's order
(`EventDeckList`): its standing, its archetype drawn as the share list
draws one, or "No archetype named", and its list, a group per card
type, the sideboard flat. An event with standings and no list draws the
standings alone. An unknown key, a copy set aside by dedup and an event
with no deck are a 404, and the page says "No event at this address."
with a link back to the field. The words are `lib/fieldEvent.ts`'s,
pinned in `fieldEvent.test.ts`.

**The join.** A deck's Matchups page and a pairing's page ("Decks"
above) are where a personal number and a field number sit side by side:
a line under each archetype's name on Matchups, a tile ("In
tournaments") on a pairing, both fed by the shared
`useFieldRecords(format)` (`api.ts`). `format` is the deck's own, the
`fmt` its coverage (`useGuideCoverage`) answers: `undefined` while that
loads and `null` for a deck with no format both ask nothing, so a deck
is never shown another format's field, and with none the page draws no
field number at all. The join is guarded, not assumed:
`archetypeKeyOf()` only extracts a key from an `opponent_key` the
classifier itself produced (`'archetype:' + key`); a manual label, a
colours-only guess, or `'unknown'` has no field number to join to,
because there is no shared vocabulary to look one up by.

One `archetype:` key holds several labels: "Control" holds Jeskai
Control and Sultai Control. The field's rows are one per key and label,
so the two kinds of page join them two ways. Field and Home count a
record against a row over the matches whose opponent carries both the
row's key and its label. Matchups and a pairing group the viewer's
matches by key alone, so their field rate is pooled over every label of
the key: `fieldRecordsByKey` (`lib/matchups.ts`) adds up the key's wins,
losses, draws and lists, and the rate is wins over the three, with no
rate when the key has no finished match.

Neither Matchups nor a pairing has a window control of its own:
`useFieldRecords(format)` reads that format's `useMetagameStatus()` and
windows the field's win rate to `{ since: format_reset_start }` once a
reset is detected, else a fixed 365 days; `/field` is where a narrower
or explicit window belongs. The same guard, the same per-format field
and the same reset-aware windowing exist server-side in
`api/routes/matches.py`'s `_field_context`, which feeds
`review/narrative.py`'s optional `FieldContext` the same way.

## Coach

`/coach` and `/coach/:id` are `pages/CoachPage.tsx`, which reads the
address's parameter (`lib/coach.ts::reportParam`: no parameter is the
latest report, a positive integer written in digits is that report,
anything else is unknown), and `views/CoachView.tsx`. The page is keyed
by the parameter, so moving between reports starts the model picker
fresh. What the coach measures and what it leaves out is
`docs/coach.md`; this section is what the page draws.

`/coach` is one format's page, and reads `?format=` as Field does
(`docs/frontend.md`, "Filters are in the address"): `useCoachFormat` gives the address's
format, else `/api/formats`' default, and its setter takes the default
out of the address. Nothing but a `Loading` is drawn until
`/api/formats` answers, and every request after it names the format:
`useCoach(format)`, `useCoachNarrative(format)` and the generate POST,
which always sends the format the page shows rather than leaving it to
the API's default.

`/coach`, top to bottom:

1. **The format** (`Select`, "Format"), the same control as Field's,
   drawn only when two formats or more qualify (`coachFormatChoices`: a
   format with the viewer's matches or a stored report, and always the
   selected one). It stays above "Not enough matches for a report yet"
   too, so a format with too few matches can be left.
2. **A callout**, when the viewer has played since the report was
   written.
3. **The report**, the format's latest: a heading that names its format
   ("Modern report of Sep 22"; `reportTitle`, and a report stored with no
   format is a Standard report, `reportFormat`) with a byline in one
   caption line (the model, what it cost, how many times it searched the
   web), both drawn by `ReportDocument` in `views/CoachView.tsx`; then one
   card per `## ` section of the prose (`components/CoachReport.tsx`). A citation in the prose (`[R4]`) is a
   link to its article, opened in a new tab. The last card is the
   sources, the reading-list entries and then the web pages, each a
   `TextLink`.
4. **The writing card** (`GenerateCard`), after the report because it is
   the action and the report is what the page is for. Its subtitle names
   the format whose news Claude searches for. Its picker lists the
   models by name alone; a caption says what the viewer's last report
   with the chosen model cost, when there is one.
5. **Your numbers** (`components/coach/Profile.tsx`), the evidence the
   report is written from, drawn only when the coach has enough
   matches. Below.
6. **Every report**, whenever a stored report is not the one on the page
   (`showHistory`): one row a report of any format, newest first, its
   title naming its format. A row's title is a link to that report's
   address; the newest report of the page's own format links to the
   page's own address (`reportLink`); the report on screen is not a link
   and says so.

`/coach/:id` is a callout with the way back to the latest report of that
report's format, the report, and the history. It has no writing card and
no numbers: the numbers are today's, not that report's. The newest
report of a format goes to that format's address, `/coach` for the
default format and `/coach?format=` otherwise (`coachAddress`), so a
report has one address. The report list and the models are the same for
every format, so this page reads them from whichever `/api/coach` answer
is already cached (`useAnyCoach`), and asks for the default format's
only when none is. An id that names no report, or a parameter that is
not a number, draws "No such report".

`useCoach` and `useCoachNarrative` each rebuild the evidence on the
server and take seconds; neither waits for the other, and each part of
the page waits for its own.

### Your numbers

Every rate on the page is written by `lib/coach.ts::rateWords`, which
turns the API's rate into three strings: the record, wins then losses
("174–211", `formatRecord`), the percent ("45%") and the range
("40%–50%", each end a whole percent). A rate the API marks `anecdotal`,
under ten matches (the same ten as `RATE_MIN_MATCHES`; the Coach has
no rough rate from five, since the API sends no percent under ten), has
a record and no percent, and the page draws the record muted beside the
"too few" line or word, never a percent of a handful; with no match at
all, a dash.
`rateWords` reads the API's flag and keeps no threshold of its own. The
range is the API's interval, and the caption under the heading says in a
sentence what it is; the words "confidence interval" and "sample" are not
on the page. A range is written with word joiners round its dash
(`WORD_JOINER`, exported by `lib/format.ts`), so a narrow tile cannot
break it in two. The coach's matches and games are wins and losses only,
so a record's losses are the rate's `n` less its wins.

The cards, in order, are in `components/coach/`:

1. **Six tiles** (`Profile`, `overallTiles`): matches, games, game 1,
   games 2–3, on the play, on the draw. Two to a row under 48rem,
   three from it. From ten, the percent is the figure and the record and
   the range are the line; under ten, the record is the figure, muted,
   over the "too few for a rate" line; with no match, a dash over "None
   played".
2. **By deck** (`DecksCard`): one row a deck in a `ul`, not a table, since
   six numbers a deck do not fit a phone's width as columns. The deck's matches
   are beside its name (from ten the percent over the record and the range;
   under ten the record, muted, over "too few") and its four splits are a `dl`
   under it, each the percent over the record, or under ten the record, muted,
   over "too few", with no range. Two decks can share a name, so the rows are
   keyed by position.
3. **By role** and **Mulligans** (`RolesAndMulligans`), side by side
   from 40rem: a `DataTable` each, of a name, Record (wins then losses)
   and Rate, the percent with its range under it, or "too few", muted,
   under ten.
4. **Decks you met** (`DecksMetCard`): Archetype · Record · Rate, with the
   labels pooled under an archetype's name in caption
   (`variantsWords`: the three most met, then "and 4 more").
5. **Patterns** (`PatternsCard`): the leak finder's rows over every
   deck. A row is the category as a `Chip`, the difference in points
   and which way it goes ("30 points better with it"), the pattern's
   name as the API gives it, and the Guide's sentence
   (`lib/patterns.ts::patternSentence`, which `LeakCard` also calls).
   A pattern can be one that helps, so the page says the direction and
   does not call a row a leak. Each deck with patterns of its own has
   a `Disclosure` under the list.
6. **Where lost games turned** (`TurningCard`): three tiles, early,
   mid and late, each the lost games that first slipped then and how
   many of them were decisive.
7. **The field** (`FieldRatesCard`): Archetype · Record · Rate · Share,
   your record against each archetype before its share of the
   tournament lists, and no range. A share over fewer than
   `MIN_TRUSTED_FIELD_SAMPLE` lists is muted. The number of lists and
   the pooled labels are caption lines under the name, which is how four
   columns fit 360 px.
8. **What these numbers leave out**: the server's own sentences, as a
   plain list.
