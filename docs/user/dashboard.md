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
  once one is written, and a guide that sets your list and results against
  the field.
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

## Language

The dashboard reads in English and in Brazilian Portuguese. The desktop app
asks on its first welcome step, pre-selected on Windows to the language the
installer ran in; Settings has the same choice, with a third value,
**System**, that follows the computer's language (the browser's, in a plain
browser) and changes with it. The app keeps the choice in `shell.json` beside
its other preferences; a plain browser keeps it in its own storage. What has
already been written in one language — a match report, a deck guide, a coach
report — stays as written: nothing stored is translated.
