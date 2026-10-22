# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Magic: The Gathering players on Arena, from the casual ladder player who
wants a record of their games to the competitive grinder playing ranked,
events and MTGO, often preparing for a Regional Championship Qualifier
(RCQ). They play on a Windows or Linux desktop (a Steam Deck counts), in
English or Brazilian Portuguese. They open the dashboard between
games and matches: to see their record, review a loss, check a matchup or
prepare a deck. During a game they glance at Live.

## Product Purpose

Sensei Top is a fully local companion app for Arena and MTGO. It reads the
log files both clients already write, keeps every raw event verbatim,
rebuilds matches, games and turns from them, and shows the player's own
record, match reports, matchup reads, deck guides and the tournament field
on a dashboard served on loopback. Success is a player who answers their
own question about their games from evidence they can trust, without an
account or a bill.

## Positioning

- Everything stays on the player's machine: no account, no upload, no
  telemetry about anyone's games. Free, AGPL-3.0-only.
- Real evidence only: the player's own games, plus a tournament corpus
  tiered by evidence quality. Unknown is shown as unknown, never guessed.
- Written guides (match report, leak finder, deck guide, RCQ guide, coach)
  come from a prompt the player copies to any chatbot, or from their own
  Claude key with a button press. Nothing is metered unless they set it up.
- Marketing never calls it "AI".

## Operating Context

- Arena writes `Player.log`; MTGO writes `Match_GameLog_*.dat`. The app only
  reads them, and never reads the memory of, injects into or automates
  either client.
- Installed as a desktop app (Electron shell around the web dashboard;
  AppImage on Linux, installer and Microsoft Store on Windows) or run from
  source.
- MTGO's log never names the player's deck, so the player confirms it
  (`/mtgo/picks`). Live (the current-match reads) is Arena-only.
- The static site (`site/`) is the landing, help and privacy pages.

## Capabilities and Constraints

- Desktop only: dashboard views are designed and checked at 1008 px wide
  and up, never at phone width. `site/` stays responsive.
- Card, deck and archetype names, prompts, guide exports and the CLI stay
  English in every language. Interface text is keyed and translated (en,
  pt-BR).
- Competitive 1v1 constructed: no draft, no overlay, no Alchemy or Brawl.
- Open: a paid Microsoft Store listing and a later optional subscription
  are planned, not built (`BACKLOG.md` BL-070, BL-006).

## Brand Commitments

- Name: Sensei Top. Contact: contact@ address. No trademark filing.
- Never the word "AI" in marketing.
- Unofficial Fan Content under Wizards of the Coast's Fan Content Policy
  (`docs/attribution.md`).

## Evidence on Hand

- A demo database (`docs/frontend-site.md`) for screenshots; the user's real
  match history is gitignored and never shown.
- The UI sweep's task walks: `.claude/handoffs/ui-sweep/` (untracked).
- No testimonials, user counts or reviews to quote; don't invent any.

## Product Principles

1. The player's own evidence first, and honest about how much there is.
2. Local and free by default; anything metered is opt-in and a button press.
3. Never synthesize: missing data reads as missing.
4. Answer the player's question in their words, not the app's internals.
