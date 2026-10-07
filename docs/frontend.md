# Frontend

Vite + React + TypeScript (strict), Tailwind v4, TanStack Query v5, recharts
and react-router 8, installed with pnpm. Eight places, each with an address
of its own, and the pages under them ("The shell", below).
The visual system ("Table") is its own document,
[docs/design-system.md](design-system.md): tokens, type ramp, radii,
elevation, density, the mana-pip rules and the rules for card art. This
file stays about the app's own structure and behavior.

## The shell

Every place has an address. `routes.tsx` is the whole table, and `main.tsx`
hands it to react-router's `createBrowserRouter`. A route has no loader and
no action: it says which page an address shows, and the page's own hooks
fetch. TanStack Query stays the only data layer.

| Address | Component | What it shows |
|---|---|---|
| `/` | `HomePage` | `HomeView`: every source, no filter |
| `/live` | `CurrentMatchView` | the match in progress |
| `/matches` | `MatchesPage` | `MatchHistoryView`: the summary band, then the list, under the source and deck filters |
| `/matches/:id` | `MatchPage` | `MatchDetailView`: that match's report |
| `/matches/:id/replay` | `MatchReplayPage` | `MatchReplayView`: that match turn by turn, one game and one turn at a time |
| `/decks` | `DecksPage` | every deck, one tile each, last played first |
| `/decks/:id` | `DeckOverviewPage` | `DeckOverviewView`: that deck's record, play and draw, and its matches |
| `/decks/:id/matchups` | `DeckMatchupsPage` | `MatchupsView`: one row per archetype it has met |
| `/decks/:id/matchups/:opponent` | `DeckPairingPage` | `PairingView`: that deck against one opponent's deck |
| `/decks/:id/guide` | `DeckGuidePage` | `GuideView` for that deck |
| `/field` | `FieldPage` | `FieldView`: what is played in tournaments, and your record against it |
| `/field/events/*` | `FieldEventPage` | `FieldEventView`: one tournament event, every deck with its standing, archetype and decklist, and where its results were published |
| `/coach` | `CoachPage` | `CoachView`: the latest report, the way to write the next one, and your numbers |
| `/coach/:id` | `CoachPage` | `CoachView`: one earlier report, as it was written |
| `/settings` | `SettingsPage` | `SettingsView`: what a desktop shell hands over, how reports get written, the density control, then the credits |
| `/design` | `DesignPage` | the design system's reference page, outside the shell |
| `/design/surfaces` | `DesignSurfacesPage` | `SurfacesView`: the second reference page, Settings and what a paid plan adds, drawn with invented values; outside the shell |
| any other | `NotFoundPage` | "No such page" |

A file in `pages/` reads the address (its parameters, its filters) and
hands what it read to a view. A file in `views/` draws, and may link to
an address. One view reads the address itself: `MatchReplayView` keeps
its game and its turn there (`?game=2&turn=5`), since choosing a turn is
what the view is for. One view takes nothing from the address and is
routed as it is: `CurrentMatchView`.

The sections below were written when each view was a tab, and many still
call it one. "History" is `MatchHistoryView` and "Current match" is
`CurrentMatchView`: each is the same view, at the address the table
gives it.

### The places

`shell/places.ts` names the seven places in the rail's order: Home, Live,
Matches, Decks, Field, Coach and Settings. Each has one
`lucide-react` icon, and no two are alike. `placeAt(pathname)` answers the
place an address is at or under, so `/decks/abc/guide` is in Decks and an
event's page, under `/field/events/`, is in Field.
`placeById(id)` answers a place by its id, for a page that needs the
place's own icon: a place's empty state takes its icon from there, so
the icon is named once.

### The layout

`shell/Shell.tsx` is the layout route every place renders in.

- **From 48rem up**: the rail (`shell/Rail.tsx`, 84 px wide) and beside it
  one column, capped at `max-w-[1196px]`, that holds the bar, the page and
  the footer on the same edges. The rail is the glyph as a link Home, then
  each place as an icon over its label, with Settings at the bottom. The
  bar is the place's name, which is the page's one `h1`, and the live
  status.
- **Under 48rem**: a strip that stays at the top of the window (the glyph,
  the name, the live status as its dot) and the bottom bar
  (`shell/BottomBar.tsx`), fixed at the window's foot: Home, Live, Matches,
  Decks and More. More opens a native modal `<dialog>` with the other three
  places. The dialog holds focus while it is open and closes on Escape by
  itself; it also closes on a press outside it, on its Close button and on
  any navigation. More reads as current when the page is one of the places
  behind it. A place's item in the bar or the sheet is at least 44 px high.

The current place's item carries `aria-current="page"`. Live carries a
dot on its icon while a match is in progress, with the words for a screen
reader before the label ("match in progress,").

**The window scrolls**, not an element inside it, so react-router's
`ScrollRestoration` puts a list back where it was left when Back returns
to it. The page body never scrolls sideways: anything wider than the
column scrolls inside its own container.

**The skip link** is the first thing a keyboard reaches: "Skip to the
page", out of sight until it holds focus. It moves focus to
`<main id="page">` and leaves the address as it is.

**The document's title** is the place's name and the product's, "Matches ·
Sensei Top", and the product's name alone at Home and at an address that
is no place (`documentTitle` in `shell/places.ts`).

**An address the router does not know** renders inside the shell: no place
is current, and the `h1` is "No such page".

### Filters are in the address

`lib/filters.ts`'s `useFilters()` reads the source from `?source=` and the
deck from `?deck=`, so a filtered page can be linked to and reloaded as it
is. `arena` is the default source, the API's own, and is left out of the
address, so an unfiltered page has one address. A setter replaces the
history entry and keeps the scroll where it is: Back leaves the page
instead of walking through filter states.

`components/Filters.tsx` holds the two controls, and Matches is the one
page that draws them. `SourceFilter` is a `Segmented` (Arena, MTGO, All
sources). `DeckFilter` is a select with "All decks" first; it shows
nothing while there are no decks. Home takes no filter and reads every
source, so a player with no Arena match still opens a page with their
own matches on it.

A deck's own pages take no filter. The address names the deck. Overview
and Matchups ask with `source="all"`, since a deck is one deck on
whichever client it was played, and the guide's requests take no source
at all.

Field keeps four filters of its own in the address, read by
`useFieldParams()` in `lib/field.ts` under the same rules: `?format=` (a
format `/api/formats` lists), `?window=` (`reset`, or a number of days),
`?tier=` (the tier the share is counted in) and `?pairs=` (the tiers the
matchups are counted over). An absent or unknown value means the
default, and a default is never written into the address, so a bare
`/field` stays bare. The defaults are in "Field, and the field-winrate
join", below.

**The format's default** is `/api/formats`' own `default`: the format of
the user's most recent match that has one (`v_match_format`, so the
log's, else the MTGO pick, else the inferred format), and Standard when
no match has one (`api/sql.py::default_format`). `formatOf`
(`lib/field.ts`) reads `?format=` against the formats the API lists, and
an absent or unknown value is that default. Coach reads `?format=` the
same way (`lib/coach.ts::useCoachFormat`, with `formatOf` and
`paramFor`), so a bare `/coach` is the default format's page too.
Neither page asks for anything that depends on the format before
`/api/formats` answers, since a bare address means whatever format that
answer names.

### A deck's pages

`/decks/:id` and the three addresses under it share
`pages/DeckLayout.tsx`: the link back to `/decks`, the deck's name as
typed ("Unnamed deck", muted, when it has none), the field's name for
it under that once the guide names an archetype whose spaced name
differs from the typed one (`fieldNameLine`), one more line under both
(`lib/decks.ts`'s `deckLine`: the format in words, the whole deck's
match count and wins, when it was last played) and the navigation
between Overview, Matchups and Guide.

`:id` is the deck's identity key (`guid:<arena_deck_id>` or
`deck:<deck_id>`, `/api/guide/decks`' own `key`), its colon written
bare (`lib/decks.ts`'s `addressSegment` and `deckAddress`: a colon is
legal in a path, and the router marks a tab current only when its own
link is spelled exactly as the address is). `resolveDeck` answers the
identity whose key is `id`, else the identity one of whose versions (a
content-hash `deck_id`) is `id`, so a link to a version still opens its
deck, else none at all. An address that names a version, or that spells
the key's colon `%3A`, is sent on to the deck's own address
(`deckRedirect`), the page under it and the query and hash kept, in
place of the history entry. An id that names no deck shows "No such
deck" and none of the four pages.

The layout hands its pages `DeckOutletContext`: `deckKey`, the
identity's key; `deckId`, the version `/api/decks` says was played
last (`newestVersion`), which no page reads; `versionIds`, the versions
a page reads, every one of the deck's or the one `?version=` chose;
`version`, that chosen one or `null`. `?version=` is read by
`chosenVersion` (`lib/deckOverview.ts`) and written by
`VersionSwitcher`. Overview and Matchups carry it in their own links and
each other's; Guide drops it, since it reads the deck whole.

### The live status

`shell/LiveStatus.tsx` shows one state, the first of these that holds:

| State | When | Its words |
|---|---|---|
| not running | the heartbeat's last request failed | "Tracker not running" |
| watcher stopped | `/api/live` says `watcher_stopped`: the watcher process died on its own after `serve` started it | "Watcher stopped" |
| a match | a match is in progress | "Match in progress" |
| watching | `/api/live` says `watching` | "Watching Arena" |
| not watching | none of the above | "Not watching" |

It is a pill, and the pill is a button that opens a panel with the rest: a
link to the match, whether the tracker is following Arena's
log, when data last changed (`last_ingest_at`, which is when data changed,
not when the reader last looked), and, when the tracker is also watching
MTGO's game logs (`mtgo_watching`), that each MTGO game appears once it
ends. With the tracker not running the panel says only that,
since what the heartbeat last said is old. The link sits in the panel and
not the pill, because a button that is also a link has two jobs and a
keyboard can ask for only one. Escape closes the panel and returns focus
to the pill; a press outside it and a move to another page close it too.

The words also sit in a polite live region of their own (`role="status"`),
out of sight beside the pill and never around it, so a change is announced
and the control is not read again with it. Under 48rem the pill is its dot
alone and the words are its name. The dot's colour is decoration: the words
are the fact. Nothing is drawn until the first heartbeat has answered
either way.

"In progress" is one rule, in `lib/liveMatch.ts`, for the live status, the
dot on Live and the Live page's own strip. A current match that started 90
minutes ago or more (`LIKELY_ABANDONED_MINUTES`) is more likely abandoned
than still being played, and nothing calls it in progress.

While the heartbeat's last request has failed, the shell also shows one
notice over the page (a `Callout`, `tone="warn"`): the tracker is not
running, and what is on screen is what was last loaded. It goes once the
tracker answers again.

### Focus mode

Live is in focus mode from 48rem up. The bar and the footer go and the
page is capped at the window's height, so a live read fits a second
monitor with nothing scrolled (`docs/current-match.md`). The rail stays as
it is, so every place is one click away, and the place's name stays as the
`h1` for a screen reader. Under 48rem the page scrolls like any other.

Focus mode is read from the address (`Shell.tsx`'s `focus`). No control
turns it on or off.

### The footer and the credits

The footer carries three things: "Reads a local SQLite database. No
account, no upload.", Wizards' Fan Content Policy notice verbatim, and a
link, Credits, to `/settings#credits`.

The credits are `views/CreditsView.tsx`, under "About and credits" on
`/settings`: Wizards' notice, the data sources, the bundled fonts and mana
glyphs with their copyright lines and licence, and this program's own
notice. Every link in them leaves the app and opens in a new tab. The
footer is hidden in focus mode and the rail is not, so Settings, and the
credits with it, are reachable from every place.

The footer's notice and every sentence the credits show come from
`web/src/credits.ts`, and `docs/attribution.md` stays the authority: a new
data source gets its row there and its entry in `credits.ts` in the same
change.

### Settings

`/settings` is `pages/SettingsPage.tsx` over `views/SettingsView.tsx`.
The page reads three things, `useShell()`, `useLLMStatus()` and the
density, and the view draws the sections in this order, each an `h2`
over its cards, with an id an address can name:

| Section | Id | Component | Drawn when |
|---|---|---|---|
| Sources | `sources` | `settings/SourcesSection.tsx` | a desktop shell |
| Writing | `writing` | `settings/WritingSection.tsx` | always; with no shell, its `WritingStatus` |
| Plan | `plan` | `settings/PlanSection.tsx` | a desktop shell that offers a paid plan |
| Backup | `backup` | `settings/BackupSection.tsx` | a desktop shell |
| Cloud sync | `sync` | `settings/SyncSection.tsx` | a desktop shell that offers a paid plan |
| Draft data | `draft-data` | `settings/SharingSection.tsx` | a desktop shell that offers sharing, whatever the plan |
| Appearance | `appearance` | the page's own | always |
| About and credits | `credits` | `CreditsView` | always |

Appearance and About and credits belong to the browser, not to a shell,
and reach the view as its children. Appearance is the density control,
a `Segmented` (Comfortable, Compact); `docs/design-system.md`'s
"Density" says what it changes and where the choice is kept.

**In a browser, which is every page today, `/settings` is Writing,
Appearance and About and credits.** Writing is then one card of
sentences from `GET /api/llm/status`: a Claude key is set and which
model writes, by its id as the API gives it; or none is set, and what
the app does then (the prompt is copied, the answer pasted back).
Nothing in it can be changed there: the key is set in the config file
(`docs/llm.md`). While the answer loads the card draws nothing; when it
failed, one sentence says so.

#### The bridge

A desktop shell, in this section, is a program the dashboard would run
inside that can read and write what the API never does: the config
file, the log's path, a folder picker, the backups. It is not "The
shell" above, which is the layout. None exists yet.

`web/src/bridge.ts` holds the types of what a desktop shell hands over
(`Shell`, `ShellSettings`, `Saved` and the types of each section) and
`useShell()`, which answers `null`: a browser has no shell. No other
file in `web/src/` names a shell's global. `SettingsPage` is the one
caller of `useShell()`, and `SettingsView` the one place that holds a
`Shell`: it hands each section its part of `settings` and the functions
that section calls, so a change of the shell's shape is a change of that
one mapping. Four rules hold every section:

- **A form knows no transport.** A section takes its values and its
  functions as props. With no function to call it is read-only: each
  value is text and nothing is drawn to press (`Field`, `Select` and
  `Switch` each have a read-only form).
- **No stored secret reaches the page.** `writing.claudeKey` and
  `writing.topdeckKey` say whether a key is set, never the key, and
  `save()` never carries one. A key's block (`settings/KeyField.tsx`)
  holds what is typed in its own state, sends it through `setKey` alone,
  and clears it when the shell answers and on "Cancel". Sync's
  passphrase and recovery code live in their card's state and are
  cleared when their step ends. None of them is ever put in the
  address, in storage or in a `console` call. The licence key is the one
  typed secret shown as plain text, since it is read back against a
  receipt; a refused one stays in its field with the reason under it.
- **Nothing invented reaches the app.** A section is drawn only where
  what it shows comes from something true, and with no shell nothing is
  but Writing's sentences. A backup's date or an allowance made up in
  the app would be a false statement (non-negotiable #4), so the
  sections are drawn with invented values only on `/design/surfaces`,
  below.
- **The API does not change for them.** No route, no write and no
  metered call was added for Settings; whatever a section saves goes
  through a desktop shell, never through the read-only API
  (non-negotiables #5 and #6).

A save answers `Saved`: `{ ok: true, restart? }` or `{ ok: false,
error }`. `error` is a sentence the shell wrote for a person, shown as
it comes; with none, the page says `lib/settings.ts`'s `SAVE_FAILED`,
"It was not saved. Try again." `restart` draws `RESTART_NEEDED` as the
card's last line (`RestartNote`) until the page is left.

Three fields of the types are there because a state had nothing to show
without them: `Sync`'s `on` and `paused` carry `enabled`, whether this
computer syncs, which is the one thing its switch turns; `Sharing`
carries `lastDraft`, the newest finished draft, which the section links
to; `backup.inFolder` counts the copies the folder holds, which the
failed backup's sentences name.

#### How a form saves

- **A `Switch` or a `Select` saves on change** (`SavingSwitch`,
  `SavingSelect`, in `settings/SaveButton.tsx`). It is disabled while
  the save is in flight; when the save fails it goes back to what is
  saved and the failure's sentence is under it.
- **Text fields save by the card's one button** (`SaveButton`): disabled
  until something in the card differs from what is saved, "Saving" in
  flight, "Saved" for two seconds after. A failure's sentence is the
  `error` of the field it is about. What differs and what is sent come
  from `lib/settings.ts`: `changedFields` and `changeToSend` send only
  what differs, each value trimmed, and an emptied field as `null`,
  never an empty string; a value that differs only by white space is no
  change.
- **A button that starts something slow is a `PressButton`** ("Back up
  now", "Sync now", "Manage the plan"): its own label says what it is
  doing and, where it has one, what it did, for two seconds. What went
  wrong is its card's to say.
- **A folder's field is a `FolderField`**: the field, and "Choose a
  folder" (`pickFolder()`) beside it from 40rem and under it below that.
  The answer is written into the field, which can also be typed into;
  nothing is saved until the card's "Save".
- **What a press did is said where it was pressed**, by the button's
  label or a sentence under the control. No toast.
- **A choice that cannot be undone asks first**, in a `Dialog` whose
  primary button is the safe one ("Keep it") and whose other button
  says what it does ("Delete my cloud data").

#### The sections

- **Sources.** Two cards: Arena (the log's path; the date order, a
  `Select` of "Read it from the log", "Month first" and "Day first") and
  Magic Online (the handle, the folder of game logs). Under them, where
  the matches are kept, read-only. When the shell found the log itself
  (`arenaLog.found`) the path's hint says so.
- **Writing**, with a shell. Claude (its key; the model, from the
  shell's `models`; one sentence that a report's cost is measured and
  shown on the report, with no number) and TopDeck.gg (its key).
- **Plan.** One card by the plan's state (`none`, `trial`, `active`,
  `payment-failed`, `ended`); `not-offered` draws no section. The offer,
  in `none` and under `ended`, is a card of tone `accent`, and it is the
  one place in the app a price is written. Each price is text the shell
  hands over, so no file in `web/src` holds one but `lib/sampleShell.ts`.
  While a plan runs (`trial`, `active`, `payment-failed`) its card shows
  the allowance (`AllowanceMeter`: a `Meter` in the accent with the part
  left beside it, about how many reports of each kind are left, said as
  alternatives, and the day it starts again; on a trial, which never
  starts again, no day). Every count is the shell's estimate, said with
  "about"; the page never computes one. Under the plan's card, the
  computers it works on (`DevicesCard`), each but this one with
  "Remove". The sentences are the functions of `lib/plan.ts`.
- **Backup.** The last backup as a sentence, when and how large
  (`sizeOf`, `lib/size.ts`), or a `warn` callout when it failed; the
  folder; how many copies are kept (3, 7, 14 or 30); "Back up now";
  "Restore from a backup file", which asks first.
- **Cloud sync**, by `Sync`'s state. `no-plan` is one sentence and a
  link to `#plan`, nothing else. `off` offers the setup, which takes
  two steps inside the card: the passphrase twice, 12 characters or
  more; then the recovery code, shown once, with "I have kept the
  code". The sentence on a lost passphrase is said at both steps. `on`
  is the switch, the last sync, the storage as a `Meter`, "Sync now"
  (while the switch is on, and not while a full storage or an ended
  plan pauses it), a link to the computers, and "Delete my cloud
  data", which asks first. `paused` is `on` under a callout, `warn`
  for the quota and for the plan, `neutral` offline. `locked` asks for
  the passphrase or the recovery code. Its failures are three
  sentences: "It did not sync. Try again.", "The cloud copy was not
  deleted. Try again." and the switch's `SAVE_FAILED`. The
  passphrase's check and the storage's sentence are `lib/sync.ts`.
- **Draft data.** Free, so nothing in it names a plan. The switch "Share
  my finished drafts", off until the viewer presses it; what is sent and
  what never is, as two short lists; a link to what the newest draft
  would send; how many drafts were sent, which counts what the server
  holds under this installation's id, so a delete sets it to 0; the id,
  read-only, with "Make a new one"; "Delete everything I sent". Both of
  the last ask first.

`components/sharing/` holds what sharing draws outside Settings:
`PayloadView` (what one draft sends, in words, under what is never
sent), `SharingNote` (the line under a draft's header that sharing is
on) and `DraftReceipt` (a finished draft's line: waiting to be sent,
sent with "Undo", or removed). No address draws any of the three, so
they are drawn only on `/design/surfaces`.

**Draft data and `components/sharing/` describe drafts, which the app no
longer reads** (the draft assistant was deleted on 2026-10-01). They are
kept on purpose: plan 10's match-data contribution reworks them for
finished matches rather than starting again (`docs/status.md`). The
Overlay section went with the pivot, since no overlay is planned.

**Not built yet**, and none of it drawn in the app: a desktop shell, so
every section above but Writing and the two of the browser; a first-run wizard,
which will be built from these controls and `OnboardingSteps`; a
diagnostics switch and export.

#### The second reference page

`/design/surfaces` (`pages/DesignSurfacesPage.tsx`, loaded lazily,
`views/SurfacesView.tsx`) stands outside the shell as `/design` does,
and the two link to each other. It draws `SettingsView` with a sample
shell from `lib/sampleShell.ts`: its state is in the page's memory, a
save answers after 400 ms, and the folder picker answers an invented
path. A "Sample" select at the top, its label above it, picks the shell
(`SAMPLE_OPTIONS`: the two with no shell, nothing set, everything set, a
save that fails, a restart, each backup's failure, each plan's state,
each sync state), and a new pick starts that sample's state again.
Under Settings: `PayloadView` over an invented draft, the two lines a
draft's page would draw, and a report's card as each writer draws it
(`GenerateCard`, below). Every name, path, price and day on the page is
invented. `lib/sampleShell.ts` is imported by this page alone, and it
is the one file in `web/src` that holds a price.

## Shared primitives (`components/ui/`)

One file per primitive, all re-exported from `index.ts`, so every
`from '../components/ui'` import resolves in one place:

- **Surfaces.** `Card` (title, subtitle, the `action` slot, the `art`
  slot, `elevation`, `tone`), `StatTile` (a label, a value, one line of
  detail), `DeckTile` (one of the viewer's decks: a card's art, then
  the deck's name, its record and when it was last played; the words
  under the art are the way into the deck's page), `Finding` (one
  finding as a nested block: its weight as a chip, where it happened, a
  title and a body), `Callout` (a nested block that says one thing
  apart from the rest of its card; `tone="warn"` adds a warn-tinted
  edge and nothing else), `EmptyState` (an optional icon, an optional
  title, one sentence, an optional action; a place's own empty state
  carries that place's icon), `OnboardingSteps` (a short run of steps,
  each done, next or later and saying so in a word; only the step that
  is next says what to do), `Disclosure` (the native `<details>`, so it
  opens with the keyboard and in find-in-page with no script; its
  summary is one string; no component spells a `<details>` of its own
  where a `Disclosure` fits) and
  `PageHeader` (a label, a title as an `h1`, one sentence, the page's
  own actions; inside the shell the bar already holds the page's one
  `h1`, so only the reference page, which stands outside it, draws a
  `PageHeader`).
- **Controls.** `Button` (`primary`/`secondary`/`quiet`, `secondary`
  when none is named; two sizes; `href` renders a link with the same
  look, the router's `Link` when the `href` is a place in the app;
  `iconOnly` makes it round, and the type refuses it without an
  `aria-label`) and `Segmented` (a radio group: one tab stop, the arrow
  keys move and select, Home and End go to either end; `label` names
  the group when nothing on screen does).
- **Forms.** `Field` (one line of text with its label over it, and
  under it a hint, or an error in its place; a `password` field never
  shows its value), `Select` (the native `select` with its label
  beside it, above it, or above it under 48rem and beside it from
  there; `children` are options drawn first, as "All decks"),
  `Switch` (a row of the label, an optional description, the state as
  a word, and the switch, a `button` with `role="switch"`; only the
  switch is pressed) and `Dialog` (the native modal `dialog`, for a
  question that waits for an answer: it opens only when `open` says
  so, and Escape, a press on the backdrop and its own buttons all end
  in one `onClose`). With no `onChange`, `Field`, `Select` and
  `Switch` are read-only: the label, then the value as text, or "Not
  set", and nothing to press. Every `select` in the app is a
  `Select`. The one text input outside them is the filter in
  `OpponentDeckLabel.tsx`'s popover, and the one other `dialog` is
  the bottom bar's More sheet; both stay as they are.
- **Links.** `TextLink` (a link in or beside text) and `BackLink` (the
  way back to a list: a `TextLink` with an arrow inside it).
  docs/design-system.md's "Links" has the rule, and says what a link
  that acts as a control looks like instead.
- **Marks.** `Chip` (`neutral`/`win`/`loss`/`warn`/`accent`/`seen`),
  `ManaPips`, `SectionLabel`, `Wordmark` and `BrandGlyph`.
  `severityChip` is a function, not a component: it maps the Severity
  vocabulary onto `Chip`'s own props, so
  `<Chip {...severityChip(severity)}>` is the one way a severity is
  drawn.
- **Data.** `DataTable` (the first column at the left, every other
  one right-aligned with a gap on its left, so no two columns touch
  at any width, headers included), `Meter`/`TwoSidedMeter`/
  `IntervalBar`, and `ColorBars`/`CurveBars` (a colour count and a
  mana curve; drawn by the draft page until it was deleted, and only on
  `/design` today).
- **Pictures.** `CardArt`, a card's art alone, and `CardTile`, a
  whole card with what is known about it written under the picture
  (both in "Card images", below).
- **Waiting and failing.** `Loading` (a shape-holding `Skeleton`, not
  bare "Loading…" text), `Skeleton` and `ErrorNote`.
- **Text.** `Prose` (inline `**bold**` and `` `code` `` only, which is
  all a narrative needs) and `TextBlock` (a wrapped `pre` in the
  interface face, for a prompt, a command or exported Markdown, which
  never lets a page scroll sideways; `docs/design-system.md` has its
  tokens).

`components/CardImage.tsx` sits one level up, not inside `ui/`. The
full token system the primitives are built on (palette, type ramp,
radii, elevation, density, the mana-pip rules, card art) is
[docs/design-system.md](design-system.md); this file only says what the
primitives do, not the tokens under them. Every one of them is shown in
every state on the reference page, `/design`.

## The typed contract

Types are **generated from the API's OpenAPI schema** and committed:

    pnpm gen:types      # dump_openapi.py → openapi.json → src/types/api.ts

Never hand-write a response type. Renaming a field in a pydantic model then
regenerating turns a would-be runtime `undefined` into a build failure — which
is the whole point. `src/types/api.ts` is generated but committed so the
frontend builds without a Python environment; `openapi.json` is an
intermediate and is gitignored.

Generation is offline and needs no server or database — `create_app()` only
records its path.

## Data fetching

One hook per endpoint in `api.ts`, with `deckId` in the query key so switching
decks refetches rather than showing another deck's numbers. `useMatches`
carries its `limit` in the key too (`'default'` when none is given, which
is the route's own 50), so a page that asks for 500 matches never reads
another page's list of 50, or the reverse.

One endpoint has two hooks. `useMatchArt` reads `/api/matches/{id}`, as
`useMatchDetail` does, under a key of its own (`['match-art', id]`) and
with `staleTime: 'static'`. A query that is static is not asked again by
an invalidation, so the heartbeat below passes it by. That is right for
what it reads, the cards of a match that is over, and for nothing that
can still change: see "Home".

**Auto-refresh is heartbeat-driven, not poll-everything.** `/api/live` returns
two tokens, deliberately separate:

- `revision` — the newest `raw_events.id`, then the projected tables' row
  counts. Moves on every 1 Hz ingest tick. Nothing in the dashboard reads
  it: the live status's "data last changed" is `last_ingest_at`.
- `projection_revision` — built from `projection_state.projections` plus the
  projected-table row counts (`matches`/`games`/`turns`/`card_events`). It moves only when a rebuild actually commits.

`shell/Shell.tsx`'s heartbeat effect invalidates on `projection_revision`,
not `revision`:

```tsx
useEffect(() => {
    if (!projectionRevision) return
    queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'live' })
}, [projectionRevision, queryClient])
```

Keying this on `revision` used to invalidate every mounted query on every
ingest tick — every 1s Arena was running, whether or not a rebuild had
happened — against its own original intent ("within a beat of the projector
committing"). `revision` moving is not a signal that anything a `matches`/
`games`/`turns`-reading query would show has actually changed; only a
committed rebuild is. An idle dashboard now costs one small `/api/live`
request every 3 s and no invalidation at all until the next rebuild lands
(paced by `live.py`'s duty-cycle gate — see `docs/architecture.md`'s "Live
mode's two cadences"), and a live one updates within a beat of that rebuild
committing rather than of the next ingest tick.

`useCurrentMatchRead` is the one scoped exception, carrying its own 1s
`refetchInterval` on top of the heartbeat — it does not depend on a rebuild
at all, since it replays `raw_events` directly rather than reading a
projected table. `useCurrentMatchRead`'s opening-hand read has
a 5-second median decision window in real play that the ~3s heartbeat alone
would eat too much of — see "The current-match reads" below. It used to gate
the fast timer on a match actually being in progress; that gate is gone now that the route it drives
replays only the current match (0.03-0.08s) rather than reading data a
`project()` rebuild produced (which can now take ~16s+ to land, and is
gated to run even less often than that suggests) — the fast poll runs
unconditionally whenever `CurrentMatchView` is mounted, which is the only
time this hook is called at all, so an idle dashboard on another tab still
does none of this work. (`useDraft` was a second exception until the draft
assistant was deleted, 2026-10-01.)

**Every `GET` hook here is a `useQuery` — the split between query and
mutation now tracks who does the writing, not just "does this cost money".**
`useReportNarrativePrompt`, `useLeaksNarrative` and `useGuideNarrative` stay
plain queries: they always return the stored prose (or the prompt to write
one) and cost nothing to read, so riding the heartbeat is not just safe but
useful — a narrative written from any source shows up in the tab within a
beat, whether it arrived via a CLI import or the generate button.
`useSetOpponentDeck` and the three generate mutations —
`useGenerateMatchReportNarrative`, `useGenerateLeaksNarrative`,
`useGenerateGuideNarrative` — are `useMutation`s because they genuinely
write, and the last three do so via an opt-in Claude call (AGENTS.md
non-negotiable #5, `docs/llm.md`) that must never fire on a timer. Each
invalidates its own query key on success for the same reason
`useSetOpponentDeck` already did: the heartbeat's revision is built from row
counts, and a stored narrative changes none of them.

The MTGO deck pick follows the same split. `useMtgoNeedsPick` (Home's
queue) and `useMtgoPickCandidates` (the match page's choices, keyed
`['mtgo-pick-candidates', id]`) are queries. `useSetMtgoPick` is the
mutation behind `PUT /api/matches/{id}/mtgo-pick`. A pick changes no row
count either, so it does its own refreshing. On success it writes the
returned pick straight into that match's candidates query, so the card
shows the answer at once. When it settles it invalidates every query but
`live`, the same predicate the heartbeat uses. A pick moves a match between
decks and formats, which nearly every read sees, so a narrower list would
have to name half of `api.ts`.

## Say what you mean in the UI

`last_ingest_at` means *when data last changed*, not *when the reader last
looked* — those are different fields (`last_checked_at` is the other) because
conflating them produced a badge that read "updated 2s ago" forever, even with
Arena closed. A freshness indicator that is always fresh is worse than none.

Label units explicitly. Turn counts are **player-turns**, not rounds, so the UI
says so rather than leaving a 24-turn game looking absurd.

A button that shows or hides content in place carries `aria-expanded`, bound
to the same boolean that decides whether the content renders. A button that
replaces itself with what it reveals (`ReportNarrativeCard`'s "Show coach's
summary") is not a toggle and does not get one.

**A deck or match with no format says so, and says why.** The API
answers `format_unknown`, or a null `fmt` or `format`, when a deck or a
match has no tournament format, and the card that needed one says that
instead of "too few lists", which would be a false reason. Every such
text begins "No tournament format is known", never "the format is
unknown": a match from a Limited or Arena-only queue has no tournament
format by design, which is not the same as one nobody could read. The
texts, as the code carries them:

| Card | When | Text |
|---|---|---|
| `PairingBrief` and `MatchupCoverageCard` (`FORMAT_UNKNOWN_BRIEF`, `lib/brief.ts`) | coverage's `fmt` is null, or a brief prompt answers `format_unknown` | "No tournament format is known for this deck, so there are no tournament lists to write a brief from. On MTGO, you can set it by confirming the format of one of its matches." |
| `MatchupBriefCard` | the live brief answers `format_unknown` | "No tournament format is known for your deck, so there are no tournament lists to write a brief from." |
| `OpponentHandCard` | the hand read answers `format_unknown` | "No tournament format is known for this match, so there are no tournament lists to estimate specific cards from." |
| `rcq/PreviewCard` | the preview's `format` is null | "No tournament format is known for this deck, so there is no tournament field to show." |
| `guide/FieldCard` | the guide's `field.fmt` is null | "No tournament format is known for this deck, so there is no tournament field to show." |
| `SideboardPlanCard` | `IntermissionOut.fmt` is null, with no plan, no prompt and no opponent | "No tournament format is known for this match, so the opponent's deck can't be named from the cards seen, and there is no plan to show." |
| `SideboardOpponentRail` (`SideboardPlanCard.tsx`) | `IntermissionOut.fmt` is null and no opponent is named | "No tournament format is known for this match, so the opponent's deck can't be named from the cards seen." |

A brief already stored for a pairing is drawn even when the deck has no
format (`briefState`, `lib/pairing.ts`): it is the user's own authored
text, and the missing format only stops a new one from being written.
`IntermissionOut.fmt` null means the break attempts no live read of the
opponent at all, which is why the break's two texts say the opponent's
deck can't be named rather than that lists are missing.

## Card images

Thumbnails come only from the local API (`/api/cards/{grp_id}/image`); the
browser never talks to Scryfall directly. `CardImage` (in
`components/CardImage.tsx`) always sets `alt` to the card's name and loads
lazily. Two failure modes are now deliberately distinct: a card hidden from us
(no grpId at all — an opponent's hand) renders a card-shaped placeholder, since
there really is a card there, we just cannot see it; an id Scryfall cannot map,
or being offline, still falls back to the name as text via `onError`, since
those are genuinely "we don't know what this is." **Never show a grpId** (the
rule that used to live only in `CurrentMatchView` now lives in `cardName()` in
`lib/cards.ts`).

Hovering a loaded thumbnail shows a larger preview in a `document.body`
portal, positioned from the thumbnail's own bounding rect and flipped
above/below to stay on screen — a portal rather than a CSS `group-hover`
popover because the battlefield rows scroll horizontally inside their own
containers, and a popover positioned inside one would clip. The preview reuses
the *same* `/api/cards/{grp_id}/image` URL at a larger render size: it is a
browser cache hit, not a second Scryfall fetch, so it costs nothing further
against rule 5 in `AGENTS.md`.

Live shows whole cards as `CardTile` (`components/ui/CardTile.tsx`):
`OpponentHandCard`'s one ranked row (interaction only; the old,
separate "threats" row was dropped, see below) and `OpeningHandCard`'s
seven cards, both 110 px wide, so a name-only fallback never resizes
the row around it. The tile is a `figure`: the picture is a
`CardImage`, with its preview under the pointer, and what is known
about the card is the `figcaption` under it. Nothing is drawn on the
picture and the tile carries no `title`
(docs/design-system.md's "Card art"). A `null` `grp_id` must *not*
fall through to `CardImage`'s own dashed "hidden card" placeholder: a
consensus card that never matched a `cards` row is a card we know the
name of, not one we cannot see, so `CardTile` branches before
`CardImage` and draws the name in a card-shaped box instead.
`OpeningHandCard`'s own hand is never hidden from us at all, so its
tiles always have a `grp_id`. What each caption says is in
`docs/current-match.md`'s "Frontend".

**A card's art alone is a second picture, not a crop of the first.**
`/api/cards/{grp_id}/art` is the image route's twin: its own download,
its own cache, the same 404 for "no such picture" and "offline right
now" alike. `CardArt` (`components/ui/CardArt.tsx`) is its one caller,
and draws it as the background of a box the caller shapes. A background
reports nothing about loading, so the component asks for the same URL
through an `Image` first and sets the background only once it has
arrived; until then, and for good when it never arrives, the box shows
nothing and the surface behind it stands. No page depends on its art.

The button in the art's corner shows the whole card, through
`CardPreview` (exported from `components/CardImage.tsx`, the same
preview a thumbnail opens): on hover with a mouse, on keyboard focus,
and on tap, where there is no hover. It closes when the pointer or the
focus leaves, on Escape, when the page scrolls, and on a tap anywhere
else. It carries `aria-expanded` and the label "Show the card: {name}".
That button is how a viewer finds the artist's name and the copyright
line, which Scryfall asks of art shown alone (`docs/attribution.md`).
When the whole card's image does not load, the preview shows the card's
name as text, as a thumbnail does. The rules for showing either picture
— a whole card is never cropped, covered or tinted; text never sits on
art — are in docs/design-system.md's "Card art".

## Home

`HomeView` (`views/HomeView.tsx`) is the page at `/`. It reads every
source and takes no filter. Until a match is recorded it shows
first run alone. After that, from the top: the last session, three things
worth a look, the MTGO matches that still need a deck, the recent matches beside the win rate by week, the deck
tiles, and the field beside a pointer to the coach. A part with nothing
to show is not drawn, and the part beside it takes the row.

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
`ErrorNote` in its place rather than vanishing.

### First run

First run is no match from any source (`isFirstRun`).
`FirstRun` draws three steps in an `OnboardingSteps`, and
`firstRunSteps` reads their states from the heartbeat: the tracker is
watching, Arena is writing its log (one event or more), play a match.
The first step not done is the one that is next, and the only one that
says what to do. The third is never done on that screen: a recorded
match ends first run.

The first step shows `watcherCallout`'s sentence: `NOT_WATCHING_SENTENCE`,
or `WATCHER_STOPPED_SENTENCE` once the watcher has died after starting. It
is the sentence the live status's panel (`shell/LiveStatus.tsx`) and Live's
callout, below, show.

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
finder's code (`PATTERN_WORDS` in `components/home/ThreeThings.tsx`).
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
One week alone is a sentence and no chart ("Charts" below). With no
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
neither) the record is a rate, "58%" over "won 14 of 24"; under ten it
is the count, "6 of 9"; with none there is no figure. A tile leads to
the deck's own address, `deckAddress(deck.key)` (`lib/decks.ts`), never
a version's id.

**The field** (`homeField`) is the default format's, the one
`/api/formats` names ("Filters are in the address"), and both of its
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
names whichever tier it landed on in words (`TIER_KIND`): "paper
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
match's detail once and never again ("Data fetching" above): a match
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
"Charts" below. The chart is also mounted anew when its box changes
height (`key={chartHeight}`), which opening the numbers under it does,
so the line draws in at its new size.

### Dates and numbers

Home's dates and numbers come from the en-US formatters in
`lib/time.ts`: `formatLongDay`, `formatShortDay`, `formatIsoDateShort`,
`formatDayTime`, `formatCount` and `formatPercent`. They read the same
whatever the browser's locale is. A moment is shown in the viewer's
own zone. `formatLongDay` and `formatShortDay` add the year when it is
not the current one; `formatDayTime` never shows a year. A date the
API sends bare (`YYYY-MM-DD`, a format's reset) goes through
`formatIsoDateShort`, which reads the date from its own parts and
through no zone, so it cannot land on the day before. A week starts on
Monday at 00:00 in the viewer's zone (`weekStart`).

Every timestamp Home reads goes through `parseTimestamp`, the one
place where a timestamp with no zone is taken as UTC. `lib/home.ts`
reads none any other way.

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

- **Live** shows a `Callout tone="warn"` with `NOT_WATCHING_SENTENCE`
  above the empty state while the tracker is not watching. When
  `/api/live` says `watcher_stopped` (the watcher died after starting) it
  shows `WATCHER_STOPPED_SENTENCE` instead, and above every branch: a
  match in progress, the opening hand, the break and the empty state,
  because a watcher that dies mid-match leaves the match frozen on screen.
  It is a `shrink-0` item, so focus mode's height cap holds. `watcherCallout`
  and `liveState` (`lib/home.ts`) choose the sentence and the pill's
  state; Home's first step uses the same sentence. Live is in
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
- **Field** says that tournament results are downloaded from the command
  line, because nothing in the app starts that download yet.

## Matches

`/matches` is `MatchHistoryView`: a band of two numbers, then the list,
both under the source and deck filters.

**The list asks for 500**, the route's maximum, and shows 50 rows at a
time, with a button that shows 50 more. A caption over the rows says how
many are listed, and with 500 in hand a caption under the last row says
the list stops there. The shown count starts again at 50 when a filter
changes.

**The band** (`components/MatchesSummary.tsx`) is matches won and games
won, counted in the client over every match in hand, not only the rows
shown, so the band and the list can never disagree. A finished match is
a win, a loss or a draw. With nothing to divide by, the number is an em
dash and the line under it says so. The band is not drawn from
`/api/metrics/winrate` or `/api/metrics/play-draw`, which did not answer
for every source when the page was built; they do now, and play and draw
are still to join the page (`docs/status.md`).

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
three-phase layout (`CurrentMatchView`) that decides which of them is the
base render's primary card versus its rail versus its disclosure bar at any
given moment. They replaced a you-vs-opponent scoreboard and a `HintsPanel`
that restated life/hand/library/mana Arena already shows on screen. A fifth
read, this deck's recent opponents (`RecentOpponentsCard`), was added and
later removed outright: a match's own opponent history is a research
question, not something worth a permanent slot on a screen meant to answer
"what do I do right now" — the tab's real estate went to `LibraryCard`
instead, the tab's own answer to what survived from `HintsPanel.tsx`'s
next-draw-odds table. Unlike that table (client-side, capped at 8 rows,
computed against a stale `turns` row), `LibraryCard` is the tab's *primary*
panel once a game is under way: the whole remaining library, server-side,
sourced from the same fresh live replay as everything else on the tab, no
row cap. Every card here hides itself rather than rendering an empty card
when it has nothing to say — no library data yet, no consensus for the
opponent's archetype, no mulligan decision currently pending.

The page is `/live`, and what it draws in each of its four states (a
break between games, a hand offered, the mulligan phase, a game under
way) is in `docs/current-match.md`'s "Frontend", with the strip at
the page's top and the lines under each row of cards. Under 48rem the
page is one column that scrolls: the strip takes two lines and cuts
none of its facts, and the library's odds tiles stack one to a row.

`useCurrentMatchRead` rides a 1s timer of its own on top of the ordinary
heartbeat, unconditionally whenever `CurrentMatchView` is mounted — the one
scoped exception (besides `/api/live`) to "nothing refetches on its own
timer," and it exists
because the opening-hand read's decision window has a measured 5-second
median in real play that the ~3s heartbeat alone would eat too much of. It
used to gate on a match actually being in progress (a `matchInProgress`
flag); that gate is gone, since the request it drives now costs 0.03-0.08s
regardless (see "Data fetching" above and `docs/current-match.md`).

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
known for the user's deck, so there are no lists to write from ("Say
what you mean in the UI" has the text), `no_consensus` says the corpus
has too few decks of this archetype to write from, `prompt` shows the
copy-prompt card, and `ok` renders `BriefBody` — the play-around list
(struck through once a card has actually shown up this match, the same
trick `OpponentHandCard` uses for its own revealed-card chips), the
IN/OUT plan with any `PlanProblem` shown inline rather than hidden, and
the prose.

## Writing prose: `GenerateCard` and `CopyPromptCard`

`components/CopyPromptCard.tsx` has two exports. `CopyPromptBody` is
everything inside the card (the buttons to copy and to show the prompt,
the error, the import command as a `TextBlock` with its own copy
button, and the prompt itself, scrolling, once shown) with no card of
its own, for a caller that already has a title: the Guide's "Matchup
coverage" and a pairing's brief. `CopyPromptCard` wraps that body in a
`Card`, for everywhere else. Both take `children`, drawn first.

`components/GenerateCard.tsx` (`docs/llm.md`) takes `writer`, who
writes the report, and builds one body: the written note (`writtenNote`,
`lib/written.ts`: the author, the day, the cost and, when out of date, a
sentence, the caller's own or "The evidence has changed since."), then
the stored prose or "Nothing written yet.", then the caller's own
children. It draws that body the same way whoever writes, so a stored
narrative and who wrote it show either way; only the buttons differ:

| `writer` | The card |
|---|---|
| `{ by: 'nobody', offered: false }` | the body goes to `CopyPromptCard` as its children, above "Copy the prompt" |
| `{ by: 'nobody', offered: true }` | the same, and under its buttons one sentence with a link to `/settings#plan` |
| `{ by: 'key' }` | the body over a button row that calls the matching `POST .../narrative` route, and a "Show the prompt" toggle |
| `{ by: 'plan' }` | as the key's, and under the buttons about how many of this kind are left, when the shell gave a count |
| `{ by: 'plan', used: true }` | `CopyPromptCard`'s buttons, with a callout over them: the allowance is used, the day it starts again (none on a trial) and that the prompt is here to copy |

A caller builds its writer with `writerFrom(status, plan, kind)`
(`lib/writer.ts`): a plan that runs writes first, then a key of the
viewer's, else nobody, and the plan is offered when one is sold to a
viewer who has none. Only a desktop shell knows a plan, so every caller
passes `plan` as `null` today and the app draws the first and the third
rows; the others are drawn on `/design/surfaces`. No row draws a lock, a
badge or a price, and the button's words do not change with the writer.
`CopyPromptCard` and `CopyPromptBody` take `over` and `under`, nodes
drawn over and under their buttons, which is where the plan's sentences
go. A press under a plan has to go through the desktop shell once one
exists: the `POST .../narrative` routes answer 503 with no key
configured.

The deck guide's narrative is structured rather than a prose blob, so
its caller (`WriteAndExport.tsx`) passes no `narrative` and lets `model`
and `generatedAt` alone say that something is stored (`GenerateCard`'s
`hasContent`); the match report's summary and the training plan pass
their prose directly.

The prompt, the Markdown export and every command to run are drawn as
`components/ui/TextBlock.tsx`: a `pre` in the interface face, wrapped so
nothing runs past its card, capped at `max-h-64` with its own scroll
when the `scroll` prop is set (the prompt, the Markdown) and as tall as
its text otherwise (an import command). Copying is `useCopied()`
(`lib/clipboard.ts`), one hook shared by both cards and by
`WriteAndExport.tsx`'s Markdown button: whether a copy landed in the
last two seconds, and the function that makes one. A refused copy stays
silent; the button's label is the only feedback either way.

An optional `controls` prop renders a picker in the button row, before
the "write it" button; the Coach page's model picker (`docs/coach.md`)
is the one caller so far. What the coach's report and its sources
look like is under "Coach".

Neither offers a textarea to paste an answer into by hand: `POST
.../narrative` is the one write path for a Claude-generated answer,
gated on a configured credential and touching only an authored-artifact
table (non-negotiable #6's allowlist); a hand-written answer only ever
arrives through the CLI `--import` commands, never a second route here.

## The opponent-deck read

`OpponentRead` (`components/OpponentRead.tsx`) replaced a card that used to
appear only below `'low'`/`'unknown'` confidence and, once shown, offered
nothing but the classifier's own single guess. It is unconditional now — the
headline reads `You picked: X` for a manual override, `X · confidence` once a
candidate has clearly won, or `X — unclear` when nothing has (the label falls
through to the colours-and-signature-card layer at that point, same as
`v_match_opponent` always did). Below `'high'` confidence it also shows the
top few candidates from `GET .../opponent-deck/candidates` — label, a bar
sized to `fit`, and `reasons` (matched cards, or a colour the definition needs
that the opponent hasn't shown) — instead of asking the player to trust a
label that may have named itself off one generic card early in the match. See
`docs/architecture.md`'s "Naming the opponent's deck" for why fit, not a raw
condition count, is what `classify.py` ranks on.

`OpponentDeckLabel` (`components/OpponentDeckLabel.tsx`), the compact
label and picker on a match's own page (`MatchHero.tsx`), and
`OpponentRead` share one `DeckPicker` popover: a filter box over every
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
the stripped text. A label with no pips beside it (the match-detail heading,
`OpponentRead`'s headline) keeps its letters, since they are the only place
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
it came from (`prefillCaption`, by `format_prefill_source`): "Pre-filled
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

## The match report

`/matches/:id` is the report: `MatchDetailView` draws the way back to
the list, the hero, and `MatchReportPanel`
(`components/MatchReportPanel.tsx`), which renders
`GET /api/matches/{id}/report`. The games turn by turn are on the
replay's page, one address further. AGENTS.md rule 5 and
`docs/architecture.md`, "The match report, and its optional narrative",
say why advice is given after a match and not during one.

**The hero** (`components/match/MatchHero.tsx`) has Home's shape: the
art at the right with a fade to the left, on top with a fade down under
48rem, and no word on the picture. The art is the first card the
opponent cast (`castCards`, `lib/matchArt.ts`), or the viewer's own when
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

`ReportNarrativeCard` starts closed behind a "Show coach's summary"
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
Home's rule (`deckRecord`: ten finished matches before a rate replaces
a raw count, "58%" over "won 14 of 24"), the format in words with how
many versions when there is more than one (`tileDetail`), when it was
last played, and its art: a card the viewer cast in the deck's newest
finished match of the same 500-match list Home reads, one card per
page. A deck with no finished match in that list keeps the empty art
box; nothing more is asked for it. The grid is Home's own: two to a
row under 48rem, three from there, five from 64rem. With no deck at
all, "No decks yet".

A tile leads to `deckAddress(key)`: `/decks/` and the identity's own
key (`addressSegment`, its colon written bare). `/decks/:id` and the
three addresses under it (Matchups, a pairing, the Guide) share
`pages/DeckLayout.tsx` ("A deck's pages" above).

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

**The Overview** (`DeckOverviewView`, `views/DeckOverviewView.tsx`) is,
top to bottom: the version switcher; Matches' own summary band over
the matches in hand; the games on the play and on the draw as three
tiles (`playDrawTiles`); a "By rank" table, shown once the matches in
hand were played at two ranks or more; a "Versions" card, one row per
version, each a link that chooses it alone, shown only when every
version is being read and the deck has more than one; and last, the
deck's Matches card. A version chosen with no match against it says
so, with a link back to reading every version.

**Matchups** (`MatchupsView`, `views/MatchupsView.tsx`) is one row per
archetype the chosen versions have met, most met first: pips and name (a
link to the pairing), and a line under it with the games, own first,
and, once the field's numbers are in, how the archetype wins in
tournaments over however many entries, marked too few to trust under
five (`MIN_TRUSTED_FIELD_SAMPLE`). The field is the deck's own format's
(`useFieldRecords(format)`, the format coverage names, "Field, and the
field-winrate join" below); a deck with no format has no field line.
Three tiles sit above the table: archetypes met (and how many were
named), and the best and worst among those met five times or more
(`MATCHUP_MIN_MATCHES`) by wins over matches. A rate needs ten matches
(`RATE_MIN_MATCHES`), the same threshold the table's own "Rate" column
uses. There is no chart: a row already shows the pips, the name, the
games and the field's own rate beside them.

**A pairing** (`PairingView`, `/decks/:id/matchups/:opponent`) is one
deck against one opponent's deck, `:opponent` a Matchups row's own
`opponent_key` (`pairingAddress`: its colon bare, a `/` written `%2F`
for a double-faced opponent name). Its heading draws the opponent the
way a Matchups row does when a match is in hand; with none, an
`archetype:` key is named from the deck's own coverage (shared with the
brief below, one query) or spaced from the key itself, a `manual:` key
as typed, a `colors:` key "Unrecognized deck", anything else "Unknown
deck". Three tiles: Record, Games, and In tournaments (the field's rate
for the archetype in the deck's format, over the same window
`useFieldRecords` gives Matchups). Below the tiles is the matchup brief
against this opponent (`components/PairingBrief.tsx`, `docs/brief.md`)
in one of five states (`briefState`, `lib/pairing.ts`): not named (the
key is not an archetype), written, with a warning and "Write it again"
when the deck's coverage says the list or the field moved since; and,
with no brief stored, no tournament format known for the deck
(coverage's `fmt` null, `FORMAT_UNKNOWN_BRIEF`), too few tournament
lists to write from yet, or not written with a "Build the prompt"
button. A prompt the route answers `format_unknown` or `no_consensus`
says the same in the prompt's place. Last, the deck's Matches card, this
pairing's matches alone.

**`MatchRow withDeck={false}`** is what both the Overview's and a
pairing's Matches card draw (`DeckMatchesCard`, shared by both): the
row leaves out the viewer's own deck, column and all, since the page's
own title already names it.

## The RCQ page

`/decks/:id/guide/rcq` is `DeckRcqPage` (`pages/DeckRcqPage.tsx`), a
child of the deck layout like the Guide, which links to it ("Prepare for
an RCQ"). It hands the deck key to `RcqView` (`views/RcqView.tsx`, parts
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
`FORMAT_UNKNOWN_BRIEF` as its message, and a prompt for every missing
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
functions in `lib/guide.ts` that `lib/scrollSpy.ts` imports. It
subscribes again when the guide's read, sometimes slow, resolves and the
sections exist, not only once on mount.

`lib/guide.ts` holds the section list and the pure functions behind
these cards (verdict labels, a board's split into differing and in line,
a field row's caption, a pattern's win counts, timing-bucket labels),
each tested in `lib/guide.test.ts`. `lib/written.ts` holds `writtenLine`
and `writtenNote`, shared with every other written card (below).

## Charts

The rules that actually shaped these charts:

- **Never a dual-axis chart.** Life (0–20), hand (0–7) and board count sit on
  different scales, so they are three separate charts. A second y-axis invents
  a correlation the data does not contain.
- **A single value is a stat tile, not a one-bar bar chart.** A deck's
  Overview, Matchups and pairing pages show tiles, never a bar chart
  with one bar. Home's win rate by week, with one week alone, is a
  sentence and no chart.
- **Color follows the entity, never its rank.** Blue is always you, orange
  always the opponent, green always the field and lands. A filter that changes the
  series count must not repaint the survivors. Every
  chart reads its colours from `useTokens()` by slot name, never a raw
  hex, so this can't be gotten wrong per call site.
- **One hue for nominal categories.** Both play/draw bars are the same color;
  a value-ramp there would double-encode bar length as hue. This is also why
  a mana pip may label a chart's category axis in a numbers table beside it,
  but never becomes the bar's own fill — see the mana boundary rule below.
- **Grid and axes are solid hairlines**, one shade off the surface. Dashed
  gridlines read as "threshold" when they are just a grid. A line that is
  a threshold is dashed and says what it is: the 50% line of Home's win
  rate by week, labelled "even".
- **A chart on a page that renders on a clock is a memoized component of
  its own, and takes nothing that moves with the clock.** Each render of
  a chart's component gives its axes new props, recharts works the
  line's points out again, and a new set of points starts the line's
  motion over. On a page that renders every second the motion never
  ends, and a label drawn at its end (the last point's rate) never
  appears. The cure is `memo` and props that keep their identity, as in
  `WeeklyWinrate` ("Home" above); turning the motion off is not
  (docs/design-system.md's "Motion").
- **Text wears text tokens, never the series color.** A colored swatch beside
  the label carries identity; the custom tooltip exists for exactly this.
- **Every chart ships its numbers as a table.** A screen reader gets the
  exact numbers, and a reader checking one value never has to eyeball a
  bar's length. `WeeklyWinrate` and `PositionTrack` keep theirs in a
  `Disclosure`, "Show the numbers", under the chart.
- **A legend is always present for two or more series.** Identity is never
  carried by color alone. The match-detail turn-chart trio shares one legend
  above all three rather than repeating it per chart (`docs/architecture.md`
  is not the place for this — see "Match detail" in this file's view notes).

The palette is validated by `scripts/validate_palette.py` (WCAG contrast plus
Machado et al. 2009 colour-vision-deficiency simulation, CIE76 ΔE
separation) — not eyeballed. Besides the series it checks the accent,
which has to stay apart from every data colour because it is never one,
and the tinted pills a result's word sits on. Run it before changing any
colour:

    uv run python scripts/validate_palette.py

`tests/test_palette.py` runs the same check with the suite;
docs/design-system.md's "Validation" has the numbers.

## Field, and the field-winrate join

`/field` is `pages/FieldPage.tsx`, which reads the address's four
filters ("Filters are in the address"), and `views/FieldView.tsx`, which
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
   selected format. Not drawn when the tier has no list in the window.
4. **"What is being played"** (`ShareCard`): one `FieldRow` per deck,
   the most played first, twelve and then a button for the rest. A row
   is the pips and the name, the viewer's record against it under the
   name, the share as a `Meter` in the field's colour (`s3`) and the
   number of lists. A caption under the list says what the bar and the
   record count; a second says the record is counted over the last 500
   matches when Home's rule finds the match list full and short of the
   window (`listShort`); tier C adds a third, that a league publishes
   only its undefeated lists.
5. **"The events"** (`EventsCard`): the stored events of the share
   list's format, window and tier, newest first, twelve
   (`EVENTS_SHOWN`) and then a button for the rest. A row is the date,
   the event's name linking to its page (`eventHref`) and a caption
   (`eventCaption`): where the results were published, how many
   decklists ("standings only" for none) and, when known, the archetype
   that won. A copy set aside by dedup and an event with no deck are not
   listed. The card waits for the tier, so its request names the tier
   the share list counts.
6. **"How the field wins"** (`WinrateCard`): a `DataTable` of win rate,
   matches and lists, over tiers A, B and D together whatever the tier
   control says, since a league publishes no losses to count. A row
   needs two finished matches (`WINRATE_MIN_MATCHES`). Rows are sorted
   by matches, then rate, then name: sorted by rate alone, the top rows
   would be decks of one list on a handful of matches. Twelve, then the
   rest.
7. **"Archetype against archetype"** (`MatchupsCard`): a `Segmented`,
   "Counted from", cumulative over paper 64+ alone, paper 64+ and MTGO
   challenges, or all three ranked tiers with rounds (`?pairs=A|AB|ABD`),
   then the rounds between two named decks, the most matches first,
   twenty and then the rest. From 48rem a table of four columns; under it
   each row is two lines. A rate on fewer than five matches
   (`MATCHUP_THIN`) is muted, and the count is always shown. When a step
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
the viewer's most recent match that has one, else Standard ("Filters are
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
("Filters are in the address"): `useCoachFormat` gives the address's
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
3. **The report** (`components/CoachReport.tsx`), the format's latest: a
   heading that names its format ("Modern report of Sep 22";
   `reportTitle`, and a report stored with no format is a Standard
   report, `reportFormat`) with a byline in one caption line (the model,
   what it cost, how many times it searched the web), then one card per
   `## ` section of the prose. A citation in the prose (`[R4]`) is a
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
turns the API's rate into three strings: the record ("174 of 385"),
the percent ("45%") and the range ("40–50%"). A rate the API marks
`anecdotal`, under ten matches, has a record and no percent: the page
draws a dash, never a percent of a handful. `rateWords` reads the
API's flag and keeps no threshold of its own. The range is the API's
interval, and the caption under the heading says in a sentence what it
is; the words "confidence interval" and "sample" are not on the page.
The range's two numbers are joined by word joiners (`WORD_JOINER`), so
a narrow tile cannot break it in two.

The cards, in order, are in `components/coach/`:

1. **Six tiles** (`Profile`): matches, games, game 1, after
   sideboarding, on the play, on the draw. Two to a row under 48rem,
   three from it.
2. **By deck** (`DecksCard`): one row a deck in a `ul`, not a table,
   since six numbers a deck do not fit a phone's width as columns. The
   deck's record is beside its name and its four splits are a `dl`
   under it. Two decks can share a name, so the rows are keyed by
   position.
3. **By role** and **Mulligans** (`RolesAndMulligans`), side by side
   from 40rem: a `DataTable` each, of a name, the record and the rate
   with its range under it.
4. **Decks you met** (`DecksMetCard`): the same three columns, with the
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
7. **The field** (`FieldRatesCard`): archetype, share, record and rate.
   The number of lists and the pooled labels are caption lines under
   the name, which is how four columns fit 360 px.
8. **What these numbers leave out**: the server's own sentences, as a
   plain list.

## Colors live in three places, on purpose

`src/index.css` holds every colour as a CSS custom property;
`src/theme.ts` holds the chart-facing ones a second time, as TypeScript;
`scripts/validate_palette.py` declares every colour it checks a third
time. The first duplication is forced: recharts writes SVG presentation
attributes, which do **not** resolve `var()`. The second is chosen: the
script is the thing you run *before* editing either file, so it stands
on its own and imports nothing from the app.

Nothing keeps them in step by hand. `tests/test_palette.py` compares
every colour the script declares with the same colour in `index.css`,
and every colour `theme.ts` holds with the script's, so a colour
changed in one file and not the others fails the suite.

The brand's accent and the mana colours are in `index.css` and the
script only, never in `theme.ts`: neither is ever a chart mark
(docs/design-system.md).

Dark only (docs/design-system.md): there is one palette, not a dark
selected-set alongside a light one. `useTokens()` keeps its old signature (a
function, not a constant) so no call site needed to change when the light
palette was deleted.

## Ports

Both are fixed: the API on **8000**, the Vite dev server on **5173** with
`strictPort: true` so it fails loudly rather than hopping to 5174 and silently
changing the URL. Development proxies `/api` to the API rather than enabling
CORS, so dashboard and API are same-origin in development exactly as they are
in production, where FastAPI serves `src/sensei_top/web_dist` itself.

That same-origin proxy is also why `api/guard.py`'s `LoopbackGuard` never gets
in development's way: the browser's `Host` and `Origin` point at loopback
either way, dev or built, so the guard's Host/Origin/fetch-metadata checks
pass identically in both. The one check the frontend has to help with is the
fourth: every non-`GET` request needs the dashboard's own `X-Tracker-Client`
header, which `api.ts`'s `put`/`post` wrappers add unconditionally. A write
built some other way — a hand-rolled `fetch`, a paste into Swagger's `/docs`
"Try it out" — 403s without it, the same as a cross-site request would.

The server also answers a page's address with the page. An address
inside the dashboard (`/matches/abc`) names no file in `src/sensei_top/web_dist`, so
`api/dashboard.py`'s `DashboardFiles`, the mount at `/`, answers
`index.html` wherever a plain file mount would answer 404, to a `GET`
or a `HEAD` only. Two kinds of path keep their 404. A path under
`/api/` stays a JSON 404, so a mistyped API path is never a page with
status 200. A path under `/assets/` stays a 404 as well: Vite names
those files by their hash, so a missing one is a page from an older
build asking for a file that is gone, and HTML in answer to a request
for a script is a worse failure than a 404. The Vite dev server falls
back to `index.html` by its own default, so an address opens the same
way on 5173 and on 8000. `tests/test_dashboard.py` pins each of these.

Which page an address shows is the router's business, not the server's.
An address `routes.tsx` does not know opens with status 200 like any
other and shows "No such page": the server cannot tell a place from a
mistyped one.

## Checks

    pnpm lint       # oxlint
    pnpm test       # vitest, once: every src/**/*.test.ts
    pnpm build      # tsc -b && vite build — typecheck is part of the build

Strict TypeScript is not optional; it caught the readonly-payload and label
formatter mismatches in recharts' own types. Fix the type, do not cast it away.

### Tests

What is tested is what counts, not what draws: the pure functions under
`src/lib/`, each in a `*.test.ts` beside it (`ls src/lib/*.test.ts` lists
them). They take the API's rows and a clock and return what a component
shows, so a test needs no browser, no DOM and no server; `vitest.config.ts`
runs them in Node and loads neither the React nor the Tailwind plugin. No
component has a test, and a hook that reads a query or the address
(`useFilters`, `useMatchInProgress`) has none either: what a page looks
like and does is still checked in a browser.

Three rules hold them:

- **The expected value is worked out from the function's written rule**,
  by hand, and the test says how where it is not plain (`docs/testing.md`,
  "Ground truth comes from the data"). A value copied from a run of the
  function tests nothing. A test that fails is read before it is changed:
  either the rule or the test's own rows are wrong, and the answer says
  which.
- **The zone is fixed, and it is not UTC.** Weeks and days are the
  viewer's own, and a bare timestamp from the API is UTC
  (`parseTimestamp`). `vitest.config.ts` sets `America/New_York`: in UTC a
  bare timestamp read as local time would pass by accident, and New York's
  clocks change, so a week on each side of the change is a case.
- **The clock is an argument.** Every function that needs the time takes
  `now`; a test passes one and never reads the real clock. A function
  that calls `Date.now()` itself (`lib/brief.ts`'s `ageText`) is not
  tested until it takes one.

A row in a test carries only the fields the function reads, cast to the
API's type: the generated types ask for every field, and a row of forty
would hide the three that matter.

## Screenshots

    pnpm shots --label before    # every view at 1280 and 360 px

`scripts/screenshots.mjs` drives a headless Chromium (Playwright, a dev
dependency; `pnpm exec playwright install chromium` once) through every
address of a server that is already up, and writes one full-height PNG per
view and width: eighteen views in all. They are Home, Live, Matches, a match
and its replay, Decks, a deck's Overview (once by its own key and once, with
a version chosen, by the key of the deck with the most matches), a deck's
Matchups (the same two ways), a deck's Guide, Field, an event's page, Coach,
Settings, the reference page and the not-found page. A pairing's page has an
address but is not in this list. Each is opened from a cold load of its own
address, the way a link or a reload opens it. The flags follow the script's
name directly: pnpm forwards a `--` as written, and the script refuses it.
`--only` takes the ids of the views to capture (`--only design,settings`),
and `--base` the server's address (`http://127.0.0.1:8000` when none is
given). It is a way to look at a change, not a check: nothing compares the
images, and neither `pnpm lint` nor `pnpm build` runs it.

A view in the script's list is an id and a path, in the rail's order, each
place followed by the pages under it: `{ id: 'deck-guide', path:
'/decks/:deck/guide' }`. `:match` and `:deck` are filled with the newest
match and the newest deck the API returns (`GET /api/matches?source=all`,
`GET /api/decks`); a view that needs one the database does not have is
skipped, and the script says so. `:event` is the key of the first event `GET
/api/metagame/events` answers with no parameters, so the route's defaults:
the default format, the last 90 days, every tier, newest first. Its slashes
are kept, as `eventHref` writes them. The last two views are the reference
page (`/design`) and an address that is no place (`/no-such-page`). A new
page joins the list by its path. The second reference page,
`/design/surfaces`, is not in the list: which sample it draws is picked on
the page itself.

Two rules hold it:

- **It sends `GET` and nothing else.** Every other method is aborted before
  it leaves the page, so a capture can never reach a metered call or a write
  route, whatever it clicks.
- **Its output is real match history** — opponents' handles, decklists — so
  it defaults to `.claude/handoffs/redesign/screens/<label>/`, which is
  gitignored. Never point `--out` at a tracked directory.

Before each capture the script waits for the page's skeletons to go,
since a skeleton means data is still on its way. The reference page
shows skeletons as samples, which never go: a skeleton inside an element
carrying `data-sample` is not waited on. A sample of a loading state
anywhere else takes the same attribute.

The window scrolls, and Playwright's `fullPage` captures a scrolling
window by resizing the viewport to the document. recharts starts a
chart's draw-in over whenever its container changes size, so a capture
taken that way catches the first frame, with no bars in it. The script
grows the viewport itself first: to the document's height
(`growToDocument`), then by whatever a pane that scrolls inside the page
is hiding (`growToContent`: Live from 48rem up). Only then does
it wait for the draw-in (`DRAW_IN_MS`, 2 s) and capture. A document taller
than `MAX_HEIGHT` (16,000 px) is still resized by `fullPage`, and the
script says so beside the view's name, since its charts may be empty.

Run it against a copy of the database, not the live one: a server started
with `--db` on a snapshot and the three `--no-*-refresh` flags plus
`--no-backup` reads the same data and downloads and writes nothing.
