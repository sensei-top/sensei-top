# Troubleshooting

`sensei-top doctor` reports what Sensei Top can find: Arena's log, Magic
Online's folder, the card data and the database. It changes nothing and is
safe to run while the app is open. Start there.

**No Arena matches at all.** Check that **Detailed Logs (Plugin Support)**
is on in Arena (Options → Account) and that Arena was restarted after
turning it on. Without it, Arena's log is missing most of what Sensei Top
reads.

**Matches from an earlier session are missing.** Arena wipes `Player.log`
every time it starts and keeps the session before only in
`Player-prev.log`, until the next launch. A session played with Sensei Top
closed for two Arena launches in a row is gone from Arena's side; keep the
app running in the tray while you play.

**Dates or times look wrong.** If your log's dates read day-first, set
`config --set-date-order dmy`.

**A Magic Online match is missing.** Run `sensei-top mtgo-status`; see
[Magic Online](mtgo.md). MTGO moves its log folder on every update.

**The opponent's deck is wrong or unnamed.** Name it yourself on the
match's page; that choice outlives every rebuild. See
[naming the opponent's deck](dashboard.md#naming-the-opponents-deck).

**A restored database is corrupt.** A `-wal` file from the old database was
left beside it. Use `sensei-top restore`, which moves it aside; see
[Backups](backups.md#restoring-one).

**Reporting a bug.** The diagnostics export in Settings (or
`sensei-top diagnostics --out FILE`) writes a zip of the app's logs and a
report. It never includes your database, any key or your MTGO handle, and
the player names that older versions' MTGO warnings wrote into the log are
masked on the way in. Arena's `Player.log` goes in only when you tick
"Include Player.log" (or give the command `--with-player-log`), since that
file names your opponents and your decks; issues are public, so leave it
unticked for one. Attach the zip to an issue, with what the dashboard
showed and what the game showed.
