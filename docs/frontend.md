# Frontend

Vite + React + TypeScript (strict), Tailwind v4, TanStack Query v5, recharts
and react-router 8, installed with pnpm. Seven places, each with an address
of its own, and the pages under them ("The shell", below).
The visual system ("Table") is its own document,
[docs/design-system.md](design-system.md): tokens, type ramp, radii,
elevation, density, the mana-pip rules and the rules for card art. This
file stays about the app's own structure and behavior.
The pages are in [docs/frontend-pages.md](frontend-pages.md); the static site
and the screenshots are in [docs/frontend-site.md](frontend-site.md).

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
| `/decks/:id` | `DeckOverviewPage` | `DeckOverviewView`: that deck's rank table, its versions and its matches, under the deck strip every tab shows |
| `/decks/:id/matchups` | `DeckMatchupsPage` | `MatchupsView`: one row per archetype it has met |
| `/decks/:id/matchups/:opponent` | `DeckPairingPage` | `PairingView`: that deck against one opponent's deck |
| `/decks/:id/guide` | `DeckGuidePage` | `GuideView` for that deck |
| `/decks/:id/rcq` | `DeckRcqPage` | `RcqView`: the RCQ prep for that deck; `/decks/:id/guide/rcq`, its 1.0.x address, redirects here |
| `/field` | `FieldPage` | `FieldView`: what is played in tournaments, and your record against it |
| `/field/events/*` | `FieldEventPage` | `FieldEventView`: one tournament event, every deck with its standing, archetype and decklist, and where its results were published |
| `/coach` | `CoachPage` | `CoachView`: the latest report, the way to write the next one, and your numbers |
| `/coach/:id` | `CoachPage` | `CoachView`: one earlier report, as it was written |
| `/settings` | `SettingsPage` | `SettingsView`: what a desktop shell hands over, how reports get written, the density control, then the credits |
| `/welcome` | `WelcomePage` | `WelcomeView`: the first-run steps, four or five by which clients the user plays, the step in `?step=`; a desktop shell only, else `NotFoundPage` |
| `/design` | `DesignPage` | the design system's reference page, outside the shell |
| `/design/surfaces` | `DesignSurfacesPage` | `SurfacesView`: the second reference page, Settings and a report's card, drawn with invented values; outside the shell |
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
is no place (`documentTitle` in `shell/places.ts`). An address that is no
place but has a name of its own, `/welcome`, takes it from its route's
handle ("Welcome · Sensei Top"; `layoutName`, "Welcome").

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
`/field` stays bare. The defaults are in `docs/frontend-pages.md`, "Field, and the field-winrate
join".

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

`/decks/:id` and the four addresses under it share
`pages/DeckLayout.tsx`: the link back to `/decks`, the deck's name as
typed ("Unnamed deck", muted, when it has none), the field's name for
it under that once the guide names an archetype whose spaced name
differs from the typed one (`fieldNameLine`), one more line under both
(`lib/decks.ts`'s `deckLine`: the format in words and when it was last
played, joined by `·` and left out part by part when unknown), the deck
strip (`components/DeckKeyNumbers.tsx`: Matches, Games and Play vs draw
over the versions the tab reads, `docs/frontend-pages.md`, "Decks") and
the navigation between Overview, Matchups, Guide and RCQ.

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
each other's; Guide and RCQ drop it, since they read the deck whole.

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

The footer carries three things: "Your match history is kept on this
computer. No account needed.", Wizards' Fan Content Policy notice
verbatim, and a link, Credits, to `/settings#credits`.

The credits are `views/CreditsView.tsx`, under "About and credits" on
`/settings`: Wizards' notice, the data sources, the bundled fonts and mana
glyphs with their copyright lines and licence, the software Sensei Top
is built on, and this program's own notice with a link to its licence.
Under "Software it is built on", the dashboard libraries' entry carries a
button, "Show the notices", that opens the dashboard's
`third-party-notices.txt` in place, in a scrolling `TextBlock`: fetched
from the dashboard's own origin the first time it opens, not linked,
since a link would replace the dashboard in the desktop app's window,
which has no back button. The build writes that file
(`web/scripts/thirdPartyNotices.ts`). Every link in the credits leaves
the app and opens in a new tab. The footer is hidden in focus mode and
the rail is not, so Settings, and the credits with it, are reachable
from every place.

The footer's notice and every sentence the credits show come from the
`credits` namespace (`src/locales/en/credits.json`); `web/src/credits.ts`
holds the list of entries (names, links, licences, and the keys of their
sentences), not the sentences. The Fan Content notice is
`welcome.intro.wizardsNotice`. `docs/attribution.md` stays the authority:
a new data source gets its row there and its entry in `credits.ts` in the
same change.

### Settings

`/settings` is `pages/SettingsPage.tsx` over `views/SettingsView.tsx`.
The page reads three things, `useShell()`, `useLLMStatus()` and the
density, and draws its own Language section, which reads
`useLanguage()`, first, above the view; the view then draws the
sections in this order, each an `h2` over its cards, with an id an
address can name:

| Section | Id | Component | Drawn when |
|---|---|---|---|
| Language | `language` | `settings/LanguageSection.tsx` | always |
| Sources | `sources` | `settings/SourcesSection.tsx` | a desktop shell |
| Writing | `writing` | `settings/WritingSection.tsx` | always; with no shell, its `WritingStatus` |
| Backup | `backup` | `settings/BackupSection.tsx` | a desktop shell |
| App | `app` | `settings/AppSection.tsx` | a desktop shell |
| Draft data | `draft-data` | `settings/SharingSection.tsx` | a desktop shell that offers sharing |
| Appearance | `appearance` | the page's own | always |
| About and credits | `credits` | `CreditsView` | always |

Language, Appearance and About and credits are drawn with or without
a shell. Language is drawn by the page above the view; Appearance and
About and credits reach the view as its children. Language is a
`Segmented` (System, English, Português (Brasil)) over `i18n.ts`'s
`useLanguage`. The choice is kept in a shell's `shell.json` (written
through `app.set({ language })`, and the shell's publish of it wins at
the next start), else in the browser's own storage; "System" is the
first English or Portuguese tag among the viewer's languages, English
when there is none (`i18n.ts`'s `systemLanguage`); `docs/i18n.md`,
"The language, from setting to sentence", has the same facts beside the
server's half. Appearance is the density control, a `Segmented` (Comfortable,
Compact); `docs/design-system.md`'s "Density" says what it changes and
where the choice is kept.

**In a browser, `/settings` is Language, Writing, Appearance and About
and credits.** Writing is then one card of sentences from
`GET /api/llm/status`: a Claude key is set and which model writes, by
its id as the API gives it; or none is set, and what the app does then
(the prompt is copied, the answer pasted back). Nothing in it can be
changed there: the key is set in the config file (`docs/llm.md`). While
the answer loads the card draws nothing; when it failed, one sentence
says so.

#### The bridge

A desktop shell, in this section, is a program the dashboard would run
inside that can read and write what the API never does: the config
file, the log's path, a folder picker, the backups. It is not "The
shell" above, which is the layout. The Electron shell in `desktop/` is
one (`desktop/README.md`); it hands its settings over as
`window.senseiTopShell`, from its preload script.

`web/src/bridge.ts` holds the types of what a desktop shell hands over
(`Shell`, `ShellSettings`, `Saved` and the types of each section) and
`useShell()`, which answers `null` in a browser and, inside the shell, the
shell's settings, kept current by its change events. No other module in
`web/src/` names a shell's global. `SettingsPage` is the one page that calls
`useShell()` for Settings (`WelcomePage`, `HomePage` for the Detailed Logs
banner and first run's MTGO-only steps, and the layout, for the name of
`/welcome`, call it too), and `SettingsView` the one place that holds a
`Shell`: it hands each section its part of `settings` and the functions that
section calls, so a change of the shell's shape is a change of that one
mapping. Four rules hold every section:

- **A form knows no transport.** A section takes its values and its
  functions as props. With no function to call it is read-only: each
  value is text and nothing is drawn to press (`Field`, `Select` and
  `Switch` each have a read-only form).
- **No stored secret reaches the page.** `writing.claudeKey` and
  `writing.topdeckKey` say whether a key is set, never the key, and
  `save()` never carries one. A key's block (`settings/KeyField.tsx`)
  holds what is typed in its own state, sends it through `setKey` alone,
  and clears it when the shell answers and on "Cancel". A key is never
  put in the address, in storage or in a `console` call.
- **Nothing invented reaches the app.** A section is drawn only where
  what it shows comes from something true, and with no shell nothing is
  but Writing's sentences. A backup's date made up in the app would be
  a false statement (non-negotiable #4), so the
  sections are drawn with invented values only on `/design/surfaces`,
  below.
- **The API does not change for them.** No route, no write and no
  metered call was added for Settings; whatever a section saves goes
  through a desktop shell, never through the read-only API
  (non-negotiables #5 and #6).

A save answers `Saved`: `{ ok: true, restart? }` or `{ ok: false,
error }`. `error` is a sentence the shell wrote for a person, shown as
it comes; with none, the page says `settings.saveFailed` (`lib/settings.ts`),
"It was not saved. Try again." `restart` draws `settings.restartNeeded` as the
card's last line (`RestartNote`) until the page is left.

The App section is the shell's own preferences, which the server
never reads: starting with the system, recording with the window
closed on Linux, the update check and diagnostic mode. Its actions go
through `app.set`, never `save()`. "Export diagnostics" answers
`{ ok: true }` when the person cancels the shell's dialog too, so the
section never says the export happened.
`app.settings.update` says where the shell's own update stands. Where
the shell cannot update itself (the Store build, a development run, Linux
outside the AppImage) the section draws one sentence in place of the
switch, so nothing is offered that would do nothing. Otherwise one
sentence under the switch says what the last check found
(`lib/settings.ts`'s `updateSentence`), and a downloaded update adds
"Restart to update", which goes through `app.restartToUpdate`.

Two fields of the types are there because a state had nothing to show
without them: `Sharing` carries `lastDraft`, the newest finished draft,
which the section links to; `backup.inFolder` counts the copies the
folder holds, which the failed backup's sentences name.

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
  now", "Delete them"): its own label says what it is
  doing and, where it has one, what it did, for two seconds. What went
  wrong is its card's to say.
- **A folder's field is a `FolderField`**: the field, and "Choose a
  folder" (`pickFolder()`) beside it from 40rem and under it below that.
  The answer is written into the field, which can also be typed into;
  nothing is saved until the card's "Save".
- **What a press did is said where it was pressed**, by the button's
  label or a sentence under the control. No toast.
- **A choice that cannot be undone asks first**, in a `Dialog` whose
  primary button is the safe one ("Keep them") and whose other button
  says what it does ("Delete them").

#### The sections

- **Sources.** Arena (the log's path; the date order, a `Select` of
  "Read it from the log", "Month first" and "Day first"), Magic Online
  (the handle, the folder of game logs, the folder of decks) and, with
  a shell, Card data: how many cards have rules text, the download as
  `CardDataProgress` draws it (below, "Welcome"), and "Download card
  data", or "Download again" once there is any or a run has ended.
  Under them, where the matches are kept, read-only, with "Open
  folder". When the shell found the log itself (`arenaLog.found`) the
  path's hint says so.
- **Writing**, with a shell. Claude (its key; the model, from the
  shell's `models`; one sentence that a report's cost is measured and
  shown on the report, with no number) and TopDeck.gg (its key).
- **Backup.** The last backup as a sentence, when and how large
  (`sizeOf`, `lib/size.ts`), or a `warn` callout when it failed; the
  folder; how many copies are kept (3, 7, 14 or 30); "Back up now";
  "Restore from a backup file", which asks first.
- **App.** The version; "Start when Windows starts" ("Start when you
  log in" elsewhere); on Linux, "Keep running when the window is
  closed"; "Check for updates" with "Check now" and one sentence on where the
  update stands, or that sentence alone where the copy cannot update
  itself; "Restart to update" once one has downloaded; "Diagnostic mode";
  "Show logs" and "Export diagnostics", with one caption that says what
  the export holds and that matches are never in it; last, the sentence
  naming the welcome steps and "Go through them again", a link to
  `/welcome`.
- **Draft data.** The switch "Share
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

**Inside the desktop shell** every section above is drawn but Draft
data, which waits for a shell that offers sharing. The first-run steps
are "Welcome", below.

### Welcome

`/welcome` is `pages/WelcomePage.tsx` over `views/WelcomeView.tsx`, a
child of the layout route like `/settings` but not a place in the rail.
The desktop shell opens it until `app.settings.onboarded` is true;
Settings' App section links back to it. The page and the layout (`shell/Shell.tsx`,
for the name) are the two callers of `useShell()` here; the view takes the shell's settings and a
`WelcomeActions` of its functions as props, so it is drawn to static
markup in its test with no shell. **With no shell the address is
`NotFoundPage`:** a browser has nothing to set up. The route's handle,
`{ title: 'Welcome', needsShell: true }`, is how the layout names it:
"Welcome" as the `h1` and "Welcome · Sensei Top" as the document's title
(`places.ts`'s `layoutName`), and with no shell "No such page", matching
the page.

The step is in the address, `?step=start|plays|arena|mtgo|done`
(`lib/welcome.ts`'s `stepOf`; a missing, unknown or retired value,
such as `cards` from before plan 23, is Start), so the reload that
follows a restore lands back on Start. Which steps a run shows is the
shell's `plays` (`stepsFor`): Arena's and Magic Online's only when
chosen, both when `plays` is missing or empty, and "Step n of m"
counts only the steps shown. A step the choice leaves out but the
address names is kept in its place, so it still has a number and
neighbours. Back and the forward button are links to the neighbouring
address, so the browser's Back agrees with them. Every step after the
first can be passed over. Wording is the view's own, written for the
first run: each step's body, labels and buttons aside, stays under 30
words in English (plan 23's budget; no test pins it). It repeats
nothing from Settings but its controls (`FolderField`, `SaveButton`,
`RestartNote`, `PressButton`, `SavingSwitch`, and `BackupSection`'s
`RestoreButton` with its confirming dialog).

| Step | Reads | Calls |
|---|---|---|
| Start | `useLanguage()`'s resolved language, pre-selected; `welcome.intro.wizardsNotice`; `app.settings.update`, for which update sentence the list shows | `setLanguage(language)` (`i18n.ts`), which writes the shell's `language` through `app.set`, not through `actions`; links to `/settings#credits`; `pickFile()`, Settings' own restore dialog, then `restoreFrom(path)` |
| Which do you play? | `app.settings.plays`, for the pressed tile | `app.set({ plays })`, then the first step the choice keeps |
| Arena | `sources.arenaLog` (`path`, `detailedLogs`) | `app.recheck()` |
| Magic Online | `sources.mtgoHandle`, `mtgoDir`, `mtgoDeckDir`, `mtgoFound` | `save({ sources: { mtgoHandle, mtgoDir, mtgoDeckDir } })`, `pickFolder()` |
| Ready | `app.settings.firstData`, `rulesText`; `update`, `checkForUpdates`; `askAutostart`, `startWithSystem` | `app.firstData()`, from Try again; `app.set({ checkForUpdates })`, `app.set({ startWithSystem })`; `app.finishOnboarding()`, then Home |

Notes the table does not carry:

- **Start says one sentence of what the app does.** "What leaves this
  computer" is a `Disclosure`, collapsed; its list's wording is a
  promise the site repeats, so it stays as it was, the credits link
  inside it. The Wizards notice is a caption under it, its wording the
  Fan Content Policy's (`docs/attribution.md`).
- **Which do you play? is three tiles**, Arena, Magic Online and Both,
  each a button with `aria-pressed`. Pressing one saves `plays` and goes
  on to the first step the choice keeps. The shell sends both until the
  person picks, so a first run shows Both pressed; only a shell older
  than `plays` sends none, and then no tile is.
- **The Arena step is one status line** with a light beside it (the
  light is decoration: the sentence says the same), then, while doctor
  does not read Detailed Logs on, the drawing (`DetailedLogsGuide`,
  below) and Check again. **Detailed Logs** is `enabled`, `disabled`
  or `unknown`; `unknown` also means the shell could not read its
  doctor. Both it and `mtgoFound` are read-only: a `save()` never
  carries them.
- **A found MTGO folder pre-fills the field** (`mtgoDir`, else
  `mtgoFound`, else empty) but is saved only by "Save", so the person
  chooses it. The folder of decks (`mtgoDeckDir`, which the shell
  writes with `config --set-mtgo-deck-dir`) is optional and never
  pre-filled.
- **Card data starts on its own** (`docs/desktop.md`, "Updates and
  onboarding"), so no step asks for it. Ready draws
  `components/onboarding/CardDataProgress.tsx`, which Settings' Card
  data card draws too: the meter and a sentence while the download
  runs, the count once it is done, the reason and Try again if it
  failed, and nothing while it is idle, since what starts a download
  differs by page.
- **The download's state is the shell's.** `firstData` is `idle`,
  `running` (with the latest plain line, except one naming the
  database, which the shell never sends, and `progress`, the latest
  event the shell parsed from `cards --progress`: bytes of the
  download, then the save stage; the component words it, drawing a
  meter), `done` or `failed`; leaving the page does not stop the run,
  and coming back shows where it is. `done`'s line is never shown: the
  CLI's last line names the database's full path.
- **Ready holds the two preferences**: the update check, where the
  build has an updater, and autostart, where the shell asks. Both are
  preferences, and Ready is where the person stops reading. Ready
  links to no tour: the tour is after 1.0.0 (`docs/status.md`), and
  its label, `welcome.done.tour`, is in both catalogues, not drawn.

**The Detailed Logs drawing** (`components/onboarding/DetailedLogsGuide.tsx`)
is our own, not Arena's screens: three panels, Arena's home screen with
the Options gear, the Options menu with Account, and Account's list with
Detailed Logs (Plugin Support) ticked, then a caption to start Arena
again. Arena is reduced to muted placeholder bars, so the drawing names
no label of Arena's but the three it points at, and those are keyed
text in Arena's own words in each language (`docs/i18n.md`'s glossary).
The frames and the accent rings are HTML boxes, so a ring grows around a
label that wraps; only the gear, the bars and the checkboxes are SVG.
The whole drawing is one image whose `aria-label` says the steps in a
sentence. `compact` is the Home banner's size. Below `sm` the panels
stack. Nothing to retake when Arena changes its art, and no attribution
question: it shows none of Arena's.

#### The second reference page

`/design/surfaces` (`pages/DesignSurfacesPage.tsx`, loaded lazily,
`views/SurfacesView.tsx`) stands outside the shell as `/design` does, and
the two link to each other. It draws `SettingsView` with a sample shell from
`lib/sampleShell.ts`: its state is in the page's memory, a save answers
after 400 ms, and the folder picker answers an invented path. The App
section's sample is the page's own (`useSampleApp`), laid over whichever
shell is picked, since `lib/sampleShell.ts` has no `app`. A "Sample" select
at the top, its label above it, picks the shell (`SAMPLE_OPTIONS`: the two
with no shell, nothing set, everything set, a save that fails, a restart,
each backup's failure, each sharing state), and a new pick starts that
sample's state again. Under Settings: `PayloadView` over an invented draft,
the two lines a draft's page would draw, and a report's card as each writer
draws it (`GenerateCard`, below), and last the Detailed Logs drawing at both
its sizes, the Arena step's and the Home banner's. Every name, path and day
on the page is invented. `lib/sampleShell.ts` is imported by this page
alone.

## Shared primitives (`components/ui/`)

One file per primitive, all re-exported from `index.ts`, so every
`from '../components/ui'` import resolves in one place:

- **Surfaces.** `Card` (title, subtitle, the `action` slot, the `art`
  slot, `elevation`, `tone`), `StatTile` (a label, a value, one line of
  detail, and `muted`, which draws the value muted for a figure too thin
  to read as a rate), `DeckTile` (one of the viewer's decks: a card's art, then
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
can still change: see `docs/frontend-pages.md`, "Home".

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
would eat too much of — see `docs/frontend-pages.md`, "The current-match reads". It used to gate
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
have to name half of `api.ts`. The page that picks many at once (in `docs/frontend-pages.md`) reads
`useMtgoPickGroups` and `useMtgoPickHints` and writes through
`useSetMtgoPicks` (`PUT /api/mtgo/picks`), which invalidates the same way.

## Every text is keyed

No sentence a user reads is written in a component or in `lib/`: it is a
key in `src/locales/en/<namespace>.json`, looked up with `t()`. A
component takes `t` from `useTranslation()`; a `lib/` function that
builds a sentence takes `t: TFunction` as an argument. Numbers, dates and
lists go through `lib/format.ts`, in the language the text resolved to.
The rules, the namespaces and what is never translated are in
[i18n.md](i18n.md). `scripts/i18nCheck.test.ts` fails on a literal it can
see.

The English texts this page quotes are what `locales/en/` holds today;
where a section names a key, that key is the source.

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
| `PairingBrief` and `MatchupCoverageCard` (`matchups.brief.formatUnknown`) | coverage's `fmt` is null, or a brief prompt answers `format_unknown` | "No tournament format is known for this deck, so there are no tournament lists to write a brief from. On MTGO, you can set it by confirming the format of one of its matches." |
| `MatchupBriefCard` | the live brief answers `format_unknown` | "No tournament format is known for your deck, so there are no tournament lists to write a brief from." |
| `OpponentHandCard` | the hand read answers `format_unknown` | "No tournament format is known for this match, so there are no tournament lists to estimate specific cards from." |
| `rcq/PreviewCard` | the preview's `format` is null | "No tournament format is known for this deck, so there is no tournament field to show." |
| `guide/FieldCard` | the guide's `field.fmt` is null | "No tournament format is known for this deck, so there is no tournament field to show." |
| `SideboardPlanCard` | `IntermissionOut.fmt` is null, with no plan, no prompt and no opponent | "No tournament format is known for this match, so the opponent's deck can't be named from the cards seen, and there is no plan to show." |

A brief already stored for a pairing is drawn even when the deck has no
format (`briefState`, `lib/pairing.ts`): it is the user's own authored
text, and the missing format only stops a new one from being written.
`IntermissionOut.fmt` null means the break attempts no live read of the
opponent at all, which is why the break's text says the opponent's
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

## Writing prose: `GenerateCard` and `CopyPromptCard`

`components/CopyPromptCard.tsx` has two exports. `CopyPromptBody` is
everything inside the card (the buttons to copy and to show the prompt, the
error, the box to paste the answer into, the import command as a `TextBlock`
with its own copy button, and the prompt itself, scrolling, once shown) with
no card of its own, for a caller that already has a title: the Guide's
"Matchup coverage" and a pairing's brief. `CopyPromptCard` wraps that body
in a `Card`, for everywhere else. Both take `children`, drawn first.

`components/GenerateCard.tsx` (`docs/llm.md`) takes `writer`, who
writes the report, and builds one body: the written note (`writtenNote`,
`lib/written.ts`: the author, the day, the cost and, when out of date, a
sentence, the caller's own or "The evidence has changed since."), then
the stored prose or "Nothing written yet.", then the caller's own
children. It draws that body the same way whoever writes, so a stored
narrative and who wrote it show either way; only the buttons differ:

| `writer` | The card |
|---|---|
| `{ by: 'nobody' }` | the body goes to `CopyPromptCard` as its children, above "Copy the prompt" |
| `{ by: 'key' }` | the body over a button row that calls the matching `POST .../narrative` route, and a "Show the prompt" toggle |

A caller builds its writer with `writerFrom(status)` (`lib/writer.ts`):
a key of the viewer's writes, else nobody. Neither row draws a lock, a
badge or a price, and the button's words do not change with the writer.
The `POST .../narrative` routes answer 503 with no key configured.

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
look like is under `docs/frontend-pages.md`, "Coach".

Given `save`, the card's `PUT` through one of `api.ts`'s `usePaste…`
mutations, `CopyPromptBody` draws a box under the copy buttons and a
Save button, disabled while the box is empty. Save resolves once the
answer is stored and the card's queries have refetched, so the stored
prose replaces the prompt; the `PUT`'s own response is never written
into the cache. A refusal shows "The answer was not saved." with the
server's sentence under it and marks the box invalid; a request that
got no answer says the tracker did not answer and that the text is
still in the box. A pasted answer's author, `pasted`, is never shown:
`lib/written.ts::isPasted` turns it into "Pasted in on {day}.", the
brief card into "pasted in", the coach byline into "Pasted in.". The
import command (`guide --import`, `brief --import`; the other cards
have none) is drawn only when `useShell()` is null, a browser with no
desktop shell, where a terminal is at hand, under "Or save it with
this command:". `CopyPromptCard` calls `useShell()` itself, the one
component that does (`bridge.ts` names the exception). `GenerateCard`
forwards `save` only when nobody writes the report; with a key, the
generate button is the write. Every write is still a route on
non-negotiable #6's allowlist; the box adds no table.

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
  `WeeklyWinrate` (`docs/frontend-pages.md`, "Home"); turning the motion off is not
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
  is not the place for this — see `docs/frontend-pages.md`, "The match report").

The palette is validated by `scripts/validate_palette.py` (WCAG contrast plus
Machado et al. 2009 colour-vision-deficiency simulation, CIE76 ΔE
separation) — not eyeballed. Besides the series it checks the accent,
which has to stay apart from every data colour because it is never one,
and the tinted pills a result's word sits on. Run it before changing any
colour:

    uv run python scripts/validate_palette.py

`tests/test_palette.py` runs the same check with the suite;
docs/design-system.md's "Validation" has the numbers.

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
The desktop app is the exception to the fixed API port: its shell picks
one and it is never 8000 (`docs/desktop.md`, "The desktop shell").

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
    pnpm test       # vitest, once: every src/**/*.test.ts and scripts/**/*.test.ts
    pnpm build      # tsc -b && vite build — typecheck is part of the build

Strict TypeScript is not optional; it caught the readonly-payload and label
formatter mismatches in recharts' own types. Fix the type, do not cast it away.

### Tests

What is tested is what counts, not what draws: the pure functions under
`src/lib/`, each in a `*.test.ts` beside it (`ls src/lib/*.test.ts` lists
them). They take the API's rows and a clock and return what a component
shows, so a test needs no browser, no DOM and no server; `vitest.config.ts`
runs them in Node and loads neither the React nor the Tailwind plugin. The
layout's naming rule (`shell/places.test.ts`) is pure and tested too.
`views/WelcomeView.tsx` has a test, drawn to static markup with
`react-dom/server` and a fake shell's settings, as `*.test.ts` with
`createElement` (the config includes no `.tsx`), so it pins what each state
says and not what a press does. `components/home/SessionHero.tsx` and
`components/onboarding/DetailedLogsGuide.tsx` (each language's labels,
caption and image label from its own catalogue) have one each in the same
pattern; no other component has a test, and a hook that reads a query or the
address (`useFilters`, `useMatchInProgress`) has none either: what a page
looks like and does is still checked in a browser. Three tests sit outside
`src/`, in `scripts/`, and they are the dashboard tests that touch the
filesystem: `thirdPartyNotices.test.ts`, for the build step that writes the
dashboard's third-party notices, builds package folders in a temporary
directory and reads them back; `i18nCheck.test.ts` reads `src/` and the
catalogues; `site-images.test.ts` reads `routes.tsx` and the site's files.

Three rules hold them:

- **The expected value is worked out from the function's written rule**,
  by hand, and the test says how where it is not plain (`docs/testing.md`,
  "Ground truth comes from the data"). A value copied from a run of the
  function tests nothing. A test that fails is read before it is changed:
  either the rule or the test's own rows are wrong, and the answer says
  which.
- **The zone is fixed, and it is not UTC.** Weeks and days are the
  viewer's own, and a bare timestamp from the API is the log's own local
  clock, read as local time (`parseTimestamp`); a value with `Z` or an
  offset is read as written, and every UTC value the server sends carries
  `Z` (`tests/test_timestamps.py`). `vitest.config.ts` sets
  `America/New_York`: in UTC a bare timestamp read as UTC would pass by
  accident, and New York's clocks change, so a week on each side of the
  change is a case.
- **The clock is an argument.** Every function that needs the time takes
  `now`; a test passes one and never reads the real clock. A function
  that calls `Date.now()` itself (`lib/brief.ts`'s `ageText`) is not
  tested until it takes one.

A row in a test carries only the fields the function reads, cast to the
API's type: the generated types ask for every field, and a row of forty
would hide the three that matter.
