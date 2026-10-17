# Frontend: the site and screenshots

The static site in `site/`, the demo database and the screenshots taken against it. Cut from [docs/frontend.md](frontend.md), which keeps the rules the dashboard follows.

## The site

`site/` is the public landing, help and privacy pages at `senseitop.com`, in
English and Brazilian Portuguese: six hand-written HTML files (`index.html`,
`help/index.html`, `privacy/index.html` and the same three under `pt-br/`), a
seventh, `404.html`,
in both languages on one page (served for any unknown path, because
`wrangler.json` sets `not_found_handling` to `404-page`), one `site.css`, no build step and no JavaScript of ours. It is not part of `web/` and shares
nothing with it at build time: the palette, the two fonts and the mark are
copied by hand (the hexes in `site.css` follow "Palette" in
[design-system.md](design-system.md); `fonts/` holds the latin and latin-ext
subsets of the two `@fontsource-variable` files with their OFL texts,
`img/` the landing's pictures, captured from the demo database (below) and
never from `docs/images/`: six dashboard pages as WebP (`home`, `live`,
`match-report`, `matchups`, `field`, `coach`), the Portuguese captures of
the same six under `img/pt-br/`, and one 1200×630 PNG card per language
(`og-en.png`, `og-pt-br.png`) for a shared link's preview; the mark from
`web/public/favicon.svg` and the language switcher's globe, drawn for the
site with `--muted`'s hex baked in, since an image in CSS cannot take the
text colour). The switcher sits in the header beside the page links, not
among them: the globe, the current language's code and a link to the
other's, with the group labelled "Language" or "Idioma". A change to the dashboard's colours is not a
change to the site until someone makes it there.

The one script on a page is Cloudflare Web Analytics' beacon, carrying the
site's token (not a secret: it is in every page's source); `_headers`
sets a Content-Security-Policy that allows only the site itself and that
beacon, so adding another script or font host fails in the browser and in
`tests/test_site.py`. `tests/test_site.py` pins two weights per page: what
the first paint fetches (the HTML, `site.css`, every woff2 and every image
that is not lazy) under 600 KB, and the whole page with every lazy image
under 1 MB. The landing's six feature images are lazy, so only the hero's
counts against the first cap. The sentences on the pages are the
maintainer's, in both languages; the Fan Content notice is Wizards' wording,
byte for byte the `WIZARDS_NOTICE` in `tests/test_attribution.py`, on the
Portuguese pages too. The Microsoft Store line is an HTML comment in each
home page, with `STORE_URL` for an address, until the listing exists.

The help page is for the installed app's users: installing, the first run,
Magic Online, troubleshooting and sending a problem report, with no
terminal anywhere in it. `docs/user/` is the from-source and command-line
reference behind it, and the dashboard tour until the site has one. A label
the app shows is quoted in `<b>`, exactly as the dashboard's or the desktop
shell's catalogue (`web/src/locales/`, `desktop/src/locales/`) has it in that
page's language, and `tests/test_site.py` fails when one no longer matches:
renaming a button means changing the page with it. Arena's own labels count,
because the welcome step's instructions quote them. Anything else in bold, a
Windows dialog or a warning, is `<strong>`. Both languages carry the same
section ids, so a link to `#report` works on either.

The landing is the one page whose `<body>` carries a class, `landing`, and
every rule for its layout is scoped under it in `site.css`: `.page` widens
from the reading pages' 46rem to 76rem, and the prose inside it (the four
cards, the written-reports section) keeps a measure of about 46rem. On a
display 1024 px or wider the hero is two columns, text left and the Home
capture right, allowed to run 4rem past the frame's right edge; the clip
for that sits on `body.landing`, not `.page`, because `.page` would clip at
its own padding box (the reason is in the stylesheet). Under the hero, the
three "Get started" steps stand in three columns; then one `section.feature`
per place of the dashboard's rail, in the rail's order (Home, Live, Matches,
Decks, Field, Coach), each an eyebrow, a heading, one paragraph and one
capture, image and text on alternating sides; then "Written reports" as
two cards, and the four cards (what never leaves your machine, what is not
planned, free software, donate) in two columns with their headings stepped
down. Under 1024 px every grid is one column, in the same order, and the
page reads as the help page does. The site's one motion is here: a feature
row rises as it scrolls into view, inside `@supports (animation-timeline:
view())` and `prefers-reduced-motion: no-preference`, so a browser without
scroll-driven animations, or a reader who asked for no motion, sees the
page at rest. The landings alone preload the two latin woff2 files; a
reading page's fonts arrive with its stylesheet.

Every page but the 404 carries an Open Graph head, so a link posted on X,
Discord or WhatsApp unfurls: `og:title` equal to the page's `<title>`,
`og:description` equal to its description meta, `og:url` its canonical,
`og:image` an absolute URL to the language's card (the protocol takes no
relative path), `og:image:alt`, `og:locale` with the other language as
alternate, `twitter:card`, and `theme-color` equal to `--plane` in
`site.css`. The 404 has no description and no counterpart, so it has none
of them. The card's headline and lead repeat the landing's hero word for
word (`web/scripts/og-card.html`), with a slice of the Home capture beside
them. `tests/test_site.py` checks each of these against the page itself and
the card's PNG header for 1200×630, not against a copy of the values.

A Cloudflare Worker serves the directory as static assets: Workers Builds,
connected to the public repository, deploys `main` with `npx wrangler deploy`
and no build command. `wrangler.json` at the repository root names the
Worker, points it at `site/` and turns off preview URLs and Workers Logs;
without the file, Workers Builds writes its own on every deploy, which
answers an unknown path with an empty 404. Workers static assets read
`_headers` and `_redirects` the way Pages does, and never serve either file.

Two things are not plain files. The Download buttons, `/download/windows`
and `/download/linux`, run the Worker's script (`worker/index.mjs`, its
logic in `worker/download.mjs`); so does every English page with a
Portuguese version, for the language below. `run_worker_first` in `wrangler.json` keeps it to those paths. It fetches
the newest release's `latest.yml` or `latest-linux.yml` from GitHub — the
feed an installed copy's updater reads — and redirects to the file it names
in that release, so the buttons follow each release with no step of their
own. GitHub's `releases/latest/download/<name>` cannot do it directly,
because the installers' names carry the version (`electron-builder.yml`).
The release job publishes every asset in one command, so the feed never
names a file that is not there yet. A feed it cannot fetch or does not
recognise sends the visitor to the releases page. The runtime takes every
export of `index.mjs` for an entry point, so it exports only the handler;
`worker/download.test.mjs` runs under `node --test`, from
`tests/test_site.py`. Try it with `wrangler dev`: the dry run of a deploy
does not start the runtime, and missed exactly that mistake.

The same script picks the language (`worker/language.mjs`, for every
English page with a Portuguese version: `/`, `/help/` and `/privacy/`): a visitor whose `request.cf.country` is `BR` gets a
redirect to the Portuguese page, unless the request's Referer is a page of
the site itself, which is what keeps the English link on a Portuguese page
from bouncing straight back. Without a cookie (the privacy pages promise
none), that Referer is the only memory of the choice, and it is why
`_headers` sends `Referrer-Policy: same-origin` rather than `no-referrer`:
the site sees its own pages as the Referer, and every other site still sees
none. A Brazilian who types the address afresh lands on Portuguese each
time, and a Portuguese page is never redirected to English. The privacy
pages promise the redirect for every translated page without naming them,
so a new pair of pages goes into `PORTUGUESE` and `run_worker_first` too;
`tests/test_site.py` fails until it does. `wrangler dev`
fills `request.cf` from the machine's own connection, so it shows only the
local country's side; the other side is the unit test.
The Worker answers on `senseitop.com`, with `www` redirecting there, and on
the account's `workers.dev` address. It was meant to be a Pages project
(plan 9, D2); the dashboard's git flow now creates a Worker, and a static
site loses nothing by it. Paths in the pages are absolute from the site's root, so
open them through a static server (`python3 -m http.server --directory
site`), not from `file://`.

### The demo database

    uv run python scripts/demo_db.py --from PATH --to PATH [--live MATCH_ID] [--seed N]

Every screenshot in `site/img/` and `docs/images/` is taken against a
database `scripts/demo_db.py` wrote, and the rule it serves is this one:
nothing captured from the real database goes into a tracked file. The script
copies a database (read-only, through SQLite's backup) to a `--to` that must
not exist and must be gitignored if it is inside the repository, projects
the copy so every match its raw events hold is in `matches`, then rewrites
every identifier `privacy_scan.py` knows (`terms_for_demo`, the scan's own
terms) in every text column of every table, MTGO's base64 logs included. The
user becomes `Deshi#00001` (`Deshi` on MTGO), every other player a given
name and five digits drawn with `--seed`. It projects the copy, rewrites it
again, and scans it once more: one term left deletes the copy, and the
script exits 2 printing only counts by category. Nothing it prints names a
term or a path. `--live` cuts the raw events inside one completed, unranked
best-of-three Arena match at its last game's result, so the Live page shows
that match in progress; `--live-cut` picks an earlier row from the per-game
ranges it prints. Before serving the copy, run
`MTGO_HANDLE=Deshi uv run sensei-top --db <copy> project`: the subcommand
classifies the opponents' decks after projecting, which the script never
does, and the handle keeps the MTGO matches, which a rebuild under the
machine's own handle would drop. Start the server with the same variable
set, since a later rebuild of its own uses it too.

The captures themselves come from `pnpm site:images --base <server> --locale
<en-US|pt-BR> --out <dir>`, run from `web/` against a server that is up on
a demo copy (`web/scripts/site-images.mjs`; `--base` and `--out` have no
default, since the real server's pages hold real match history). It opens
each view of `SITE_VIEWS` at 1440×900, writes `<name>.png` and, with
`magick`, `<name>.webp` at quality 85, then renders the language's card to
`og.png` with the `home.webp` beside it; `--only` picks views by name. It
copies nothing into `site/` or `docs/`: each file is looked at, then moved
by hand. Two copies of the database are made for one set of captures. The
uncut copy gives every view but Live; the Live capture needs a copy cut
inside a match (`--live`), and a cut drops every later match, so the two
cannot be one database. The Live capture also needs `--clock`, the
browser's clock fixed at a moment inside the cut match, in UTC
(`--clock 2026-08-26T21:36:00Z` for the match the site shows); without it
the Live header compares the match's start with today and calls the match
abandoned. The Portuguese pictures are captured again with `--locale
pt-BR`, from the same two copies, into `site/img/pt-br/`.

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

The table of views is `web/scripts/views.mjs`, shared with
`site-images.mjs`, as is the resolution of an address's placeholders. A view
is an id and a path, in the rail's order, each place followed by the pages
under it: `{ id: 'deck-guide', path: '/decks/:deck/guide' }`. `:match` is the
newest match (`GET /api/matches?source=all`); `:deck` is the key of the
first deck `GET /api/guide/decks` answers, the last played; `:largest` is
the key of the deck with the most matches and `:version` the version of it
`GET /api/decks` says was played last. A view that needs one the database
does not have is skipped, and the script says so. `:event` is the key of the
first event `GET /api/metagame/events` answers with no parameters, so the
route's defaults: the default format, the last 90 days, every tier, newest
first. Its slashes are kept, as `eventHref` writes them. The last two views
are the reference page (`/design`) and an address that is no place
(`/no-such-page`). A new page joins the list by its path. The second
reference page, `/design/surfaces`, is not in the list: which sample it
draws is picked on the page itself.

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
