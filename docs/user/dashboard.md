# The dashboard

The dashboard has six places and Settings, each at an address of its own,
so a page can be bookmarked, linked to and reloaded as it is:

- **Home** — the last session, three things worth a look, the recent matches
  beside the win rate by week, your decks and the field.
- **Live** (Arena only) — the match in progress: a replay of what's been
  revealed, a keep guide, a read of the opponent's likely hand, your remaining
  library and a between-games sideboard plan.
- **Matches** — every match, filtered by client or deck, each with a report
  and a turn-by-turn replay of its games.
- **Decks** — a page for each of your decks: its record over every version
  or one, its record against each opponent archetype with the matchup brief
  once one is written, a guide that sets your list and results against
  the field, and an RCQ tab that prepares one event.
- **Field** — the metagame from real MTGO and paper tournament results
  (never Arena).
- **Coach** — a dated report across every deck, each one kept and measured
  against the one before it.
- **Settings** — the language, whether a Claude key is set and which model
  writes with it, the density of the display, and the credits.

Turn numbers are **player-turns**, matching Arena's own counter: a game where
each player took 12 turns counts as 24.

## Naming the opponent's deck

Arena never tells you what deck your opponent is playing, so Sensei Top
works it out from the cards they reveal — typically eight to fifteen a
match, which is usually enough. `sensei-top archetypes` downloads the deck
definitions that make this possible, and `serve` refreshes them in the
background when they are over a day old. Both only ever download; nothing
about your games is uploaded, and both work from cache when you are
offline. When the guess is uncertain the dashboard says so and lets you
name the deck yourself.

## What the dashboard can change

The dashboard reads; it changes almost nothing. Every database connection
opens read-only, except the few that store something only you can author:
naming an opponent's deck yourself, picking the deck of a Magic Online
match, one at a time or a group at once, and saving a written deck guide,
matchup brief, match or leak narrative, coach report or RCQ guide. While
`serve` runs, the API it uses is documented at http://127.0.0.1:8000/docs.

## The account, error reports and Help build the stats

The desktop app adds three things the dashboard alone does not have, all
of them done by the app's shell, so an install run from source gets none
of them: no account, no cloud backup, no error reports and no games sent.

- **The account**, free and optional: Settings → Account, signing in with
  Google or Discord in the system browser. Cloud backup of the match
  history (a summary of each match, never a log, a name or chat) and error
  reports are each a separate yes. The backup restores the history on
  another computer; Settings → Account also exports the cloud data and
  deletes the cloud history or the whole account. A match pulled from the
  cloud that this install has no log of is marked "Restored" on Matches
  and has no report or replay. On Linux with no keyring the app does not
  keep the sign-in, so it asks again at each launch.
- **Report a problem**, in the tray, Settings → App and on an error
  message: one report, sent after you agree to it, with or without an
  account. Automatic error reports are the account's separate yes.
- **Help build the stats**, a yes of its own that needs no account: it
  sends your games, stripped of everything that names you or your
  opponent, to the pool Sensei Top's own stats are built from. Settings
  turns it off.

What each one sends, and for how long it is kept, is in the
[privacy policy](https://senseitop.com/privacy/); the step-by-step is
[on the website](https://senseitop.com/help/#account).

## Language

The dashboard reads in English and in Brazilian Portuguese. The desktop app
asks on its first welcome step, pre-selected on Windows to the language the
installer ran in; Settings has the same choice, with a third value,
**System**, that follows the computer's language (the browser's, in a plain
browser) and changes with it. The app keeps the choice in `shell.json` beside
its other preferences; a plain browser keeps it in its own storage. What has
already been written in one language — a match report, a deck guide, a coach
report — stays as written: nothing stored is translated.
