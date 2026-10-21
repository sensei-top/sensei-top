---
name: counting-downloads
description: Counts Sensei Top's downloads since the public release from GitHub's release asset counters, which are the only place a download from the site is counted (the site's Download buttons redirect there), and estimates active installs from the updater's feed reads. Says which counts mean what, what inflates them, and which Cloudflare numbers are and are not visitors. Use when the user asks how many downloads, installs or users the app has, for the weekly numbers in the announcement handoff, or before quoting adoption anywhere (SignPath, the ~3,000 MAU threshold in docs/status.md).
---

# Counting downloads

    uv run python .claude/skills/counting-downloads/scripts/downloads.py
    uv run python .claude/skills/counting-downloads/scripts/downloads.py --since v0.7.0

It reads GitHub's public releases API (no token) and prints one row per
release, newest first, then the installer total and the active-install
estimate. `--since` defaults to `v1.0.0`, the first public release
(2026-10-17); the `0.7.x` releases before it went to the beta testers.

## What each column is

| Column | Assets | Counts as |
|---|---|---|
| win, appimg, tar | `Sensei-Top-Setup-*.exe`, `Sensei-Top-*.AppImage`, `Sensei-Top-*.tar.gz` | **downloads** — the only columns summed |
| feeds w/l | `latest.yml`, `latest-linux.yml` | updater checks, plus one per site Download click (below); never downloads |
| blkmap | `*.exe.blockmap` | the Windows updater's differential download; never downloads |

**The site cannot be split from GitHub.** `/download/windows`, `/download/linux`
and `/download/linux-tar` (`worker/download.mjs`) redirect to the same
release files, so a download from the site and one from the releases page
land on the same counter.

## What inflates the counts

Say these alongside any number you quote:

- **Updates count as downloads.** An in-app update fetches the new release's
  installer, so a release after `v1.0.0` counts new installs and updates
  together. The newest release's installer count is the noisiest for this.
- **The maintainer and the beta testers** download every release.
- **The feeds read twice for a site click.** The Worker reads
  `latest.yml` / `latest-linux.yml` to find the newest file before
  redirecting, so each Download click adds one feed read.

## The active-install estimate

The updater (`desktop/src/updater.ts`) reads the feed 30 s after launch and
every 24 h after, on the Windows installer build and the AppImage only (not
the tarball, not the Store build). The newest release's feed reads divided
by its days out approximate daily active installs. It is an **upper bound**,
never a measurement: an app restarted twice in a day reads twice, and site
clicks add to it. It misses anyone with the update check off, the tarball
and the Store build. A release under a day old is too new to divide.

## Cloudflare, for the site side

Cloudflare → Analytics & Logs → **Web Analytics** → senseitop.com, with
"Exclude bots": Visits and the Country / Referer / Path breakdowns. That is
the only visitor count. Two numbers that look like visitors and are not:

- **Workers & Pages request counts.** The Worker runs only on the paths
  `wrangler.json`'s `run_worker_first` names; images and other assets never
  reach it.
- **Account analytics / Traffic overview.** Every request to the zone,
  crawlers included.

WhatsApp sends no referrer, so its visits read as direct. Most site
traffic is Brazilian and goes to `/pt-br/`.

## Where the numbers go

Weekly, in `.claude/handoffs/announcement.md` (plan 25, "Measuring"),
with the date read. GitHub's counters only grow, so a week's downloads
are this week's total minus last week's.
