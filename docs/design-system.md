# The design system — "Table"

The dashboard's visual system: one dark palette with one accent, a type
ramp with a readability floor, radii by role, one elevation recipe, density,
the mana-pip rules and the rules for showing card art. `docs/frontend.md`
and `docs/frontend-pages.md` cover the shell and each view's own behavior;
this file is only the tokens and the rules a new component follows. Every
token and every primitive can be seen, in every state, on the reference page
("The reference page", below).

## Palette

Dark only. Declared once in `web/src/index.css` (CSS custom properties),
mirrored in `web/src/theme.ts` (the chart-facing slots, as literal hex:
recharts writes SVG presentation attributes, which do not resolve `var()`)
and a third time in `scripts/validate_palette.py` (see "Validation" below).
The three move together, and `tests/test_palette.py` fails when they
disagree.

| token | value | utility | role |
|---|---|---|---|
| `--plane` | `#0b0c14` | `bg-plane` | page ground |
| `--surface-1` | `#131522` | `bg-surface` | `Card`, `StatTile` |
| `--surface-2` | `#1a1d2e` | `bg-surface2` | a nested block (`Card elevation={2}`, `Finding`, `Callout`), a `Segmented`'s track, a `Skeleton`, a table row under the pointer, the disc behind an `EmptyState`'s icon, the step that is next in `OnboardingSteps` |
| `--surface-3` | `#24283d` | `bg-surface3` | what is raised from the surface it sits on: a `secondary` button, the checked segment, a meter's track, the chart tooltip, the disc of a step that is done or later in `OnboardingSteps` |
| `--line` | `#252a40` | `border-line` | a chart's grid, a table's row rule |
| `--line-2` | `#343a57` | `border-line2` | a chart's axis, a table's header rule |
| `--edge` | `rgb(150 160 230 / 0.14)` | `border-edge` | a card's border |
| `--edge-strong` | `rgb(150 160 230 / 0.26)` | `border-edge-strong` | the empty state's dashed edge, the chart tooltip's border |
| `--ink` | `#f2f3f8` | `text-ink` | never `#fff`, which haloes at distance |
| `--ink-2` | `#b9bdd0` | `text-ink2` | secondary text; also `PositionTrack`'s zero line |
| `--muted` | `#989db5` | `text-muted` | labels, captions, chart ticks |
| `--accent` | `#f4b6e4` | `bg-accent`, `text-accent` | the brand, the primary action, the one item a page leads with ("The accent", below) |
| `--on-accent` | `#1a1020` | `text-on-accent` | the only text colour on an accent fill |
| `--focus` | `var(--accent)` | | the focus ring ("Focus", below) |
| `--series-1` (self) | `#4a95f0` | `bg-s1` | you |
| `--series-2` (opponent) | `#f0762f` | `bg-s2` | the opponent |
| `--series-3` (field) | `#9ee0a8` | `bg-s3` | the field; your lands |
| `--win` | `#57bd6d` | `text-win` | |
| `--loss` | `#e66e62` | `text-loss` | |
| `--warn` | `#d9a13a` | `text-warn` | thin samples, `PlanProblem`, gap notes |
| `--mana-w/u/b/r/g` | `#f0f2c0` `#b5cde3` `#aca29a` `#db8664` `#93b483` | | Mana-project disc colours |
| `--mana-glyph` | `#111111` | | |

The four hairlines are two lines, each in two forms. `--line` and
`--line-2` are opaque: a chart's grid and axis, and a rule drawn on
`--plane` or `--surface-1`. `--edge` and `--edge-strong` are the same two
lines made translucent, so a border holds on any surface. Over
`--surface-1` they composite to `#25283d` and `#353955`: close to `--line`
and `--line-2`, not equal to them.

`theme.ts`'s `Tokens` (dark, the only set): `self`, `opponent`, `field`,
`grid`, `axis`, `muted`, `surface`, `ink`, `ink2`. Two groups are **CSS
only** and have no slot there, because neither ever becomes a chart mark:
the mana colours (the boundary rule, below) and the accent.

## The accent

The accent is the brand, the primary action, and the one item a page leads
with. **It is never data**: no chart mark, no series and no result wears
it. It is the one hue here that stays apart from all six data colours (the
three series, win, loss and warn) under normal vision and under every
simulated colour-vision deficiency, which the palette check measures
rather than assumes.

Where it appears:

- `Button variant="primary"`: the one call to action a card has.
- `Chip variant="accent"`: the item a list leads with, or an authored
  artefact. Today: a `decisive` finding (through `severityChip`, the only
  severity that takes it).
- `Card tone="accent"`: a tinted border (`border-accent/30`) around an
  authored or metered artefact, such as a written narrative.
  `GenerateCard` and `CopyPromptCard` pass it from their own `accent`
  prop. It is never decoration: the card's body opens with who wrote
  it, when and what it cost (`writtenNote`, `lib/written.ts`), ahead of
  the prose.
- `Meter`'s `accent` fill: a meter that measures no data. The
  card-data download draws one (`CardDataProgress`, on the welcome
  steps' Ready and in Settings' Card data card): determinate while
  downloading, indeterminate while saving.
- The focus ring, and the wordmark's glyph: `BrandGlyph` is the link Home
  at the top of the rail, and in the strip under 48rem. The wordmark
  itself (`Wordmark`, the glyph beside the name) is drawn on the reference
  page and nowhere else yet.
- The icon of the current place, in the rail and in the bottom bar. The
  item's fill and its words stay neutral (`bg-surface3 text-ink`).
- A numbered disc (`bg-accent text-on-accent`). In `OnboardingSteps` it
  is the step that is next, the one thing to do now, beside a
  `Chip variant="accent"` that says "Next". On Home it is the place of
  each of the three things among them. The number is never the only
  carrier: the step says its state in a word, and the three things are
  an ordered list.
- The Detailed Logs drawing (`DetailedLogsGuide`): the ring around the
  one thing to press in each panel, its step's number in the numbered
  disc above, and the tick in Detailed Logs' checkbox, drawn in
  `--on-accent` on an accent fill. The frames and the placeholder bars
  stay neutral, so the accent marks only what to press.

`--on-accent` is the only text colour allowed on an accent fill, and an
accent fill is the only place it appears.

## Validation

`scripts/validate_palette.py` (stdlib only, no dependency on the app)
checks:

- WCAG 2.x contrast: `ink`, `ink-2`, `muted` and `accent` ≥ 4.5 on every
  surface; `series-1/2/3`, `win`, `loss` and `warn` ≥ 3.0 as non-text (WCAG
  1.4.11), and `win`, `loss` and `warn` ≥ 4.5 too, since each is also used
  as text; `on-accent` ≥ 4.5 on an accent fill; each mana disc ≥ 3.0
  against `surface-1`, and `mana-glyph` ≥ 4.5 against each disc.
- Tinted pills: `win`, `loss` and `warn`, each on its own colour at 12%
  (`bg-win/12 text-win`), ≥ 4.5 over `plane`, `surface-1` and `surface-2`.
  On `surface-3` the word stands with no tint.
- Colour-vision-deficiency separation: the Machado, Oliveira & Fernandes
  (2009) full-severity simulation matrices (protan/deutan/tritan), applied
  in linear sRGB, then CIE76 ΔE in CIELAB (D65). The three series pairs,
  and the accent against each of the six data colours, must clear ΔE ≥ 20
  under normal vision *and* all three simulations: a hard failure
  otherwise. Win–loss separation is printed as **advisory** only: it
  collapses under deuteranopia, which is acceptable only because every
  result cell also carries the word "Win"/"Loss", never colour alone.

Run it before changing any colour in the table above:

    uv run python scripts/validate_palette.py

`tests/test_palette.py` runs it with the suite, and also compares every
colour the script declares with the same colour in `index.css`, and every
colour `theme.ts` holds with the script's, so a value changed in one file
and not the others fails a test. The two translucent edges are in
`index.css` alone: the script does not declare them, and nothing checks
them.

What it measures for the palette above. Contrast, against each surface:

| colour | plane | surface-1 | surface-2 | surface-3 |
|---|---|---|---|---|
| `ink` | 17.60 | 16.36 | 15.05 | 13.11 |
| `ink-2` | 10.45 | 9.72 | 8.94 | 7.78 |
| `muted` | 7.27 | 6.76 | 6.21 | 5.41 |
| `accent` | 11.75 | 10.93 | 10.05 | 8.75 |
| `series-1` | 6.36 | 5.91 | 5.44 | 4.74 |
| `series-2` | 6.81 | 6.34 | 5.83 | 5.07 |
| `series-3` | 12.70 | 11.81 | 10.87 | 9.46 |
| `win` | 8.27 | 7.69 | 7.07 | 6.16 |
| `loss` | 6.29 | 5.85 | 5.38 | 4.68 |
| `warn` | 8.46 | 7.87 | 7.23 | 6.30 |

`on-accent` on an accent fill: 11.11. Each word on its own 12% tint:

| colour | over plane | over surface-1 | over surface-2 |
|---|---|---|---|
| `win` | 7.03 | 6.37 | 5.78 |
| `loss` | 5.52 | 5.03 | 4.59 |
| `warn` | 7.15 | 6.48 | 5.89 |

Separation, as the smallest ΔE across normal vision and the three
simulations:

| pair | smallest ΔE | under |
|---|---|---|
| self – opponent | 102.55 | protan |
| self – field | 26.21 | tritan |
| opponent – field | 39.32 | protan |
| accent – `series-1` | 34.36 | protan |
| accent – `series-2` | 51.14 | tritan |
| accent – `series-3` | 30.43 | deutan |
| accent – `win` | 42.50 | deutan |
| accent – `loss` | 45.73 | protan |
| accent – `warn` | 20.28 | tritan |
| win – loss (advisory) | 6.44 | deutan |

Two of these pass with little to spare: `loss` on its own tint over
`surface-2` (4.59 against 4.5) and the accent against `warn` under
tritanopia (20.28 against 20). A change to `loss`, `surface-2`, the accent
or `warn` needs the check run first, not after.

## Type ramp

Semantic names, not raw sizes: `text-{name}` utilities defined in
`index.css`'s `@theme inline` block. Density (below) scales spacing by the
full factor, but the four smallest steps have a readability **floor**, so
Compact never drops below it; the larger steps scale freely:

| utility | size (Comfortable) | floor | face | use |
|---|---|---|---|---|
| `text-chip` | 12px | 11px | interface | chips, labels |
| `text-caption` | 13px | 12px | interface | subtitles, captions, a table's column headers, a button's text |
| `text-body` | 14.5px | 14px | interface | body and table cells |
| `text-lead` | 16px | 14.5px | interface | the sentence under a page's title |
| `text-title` | 18px | — | display, 700 | `Card` titles |
| `text-heading` | 22px | — | display, 700 | a page's title |
| `text-stat` | 30px | — | display, 800 | `StatTile` values, a `DeckTile`'s figure, Home's headline under 48rem |
| `text-hero` | 44px | — | display, 800 | the keep verdict, first run's title from 48rem |
| `text-display` | 60px | — | display, 800 | `LibraryCard`'s odds figures, Home's headline from 48rem |

A step from `title` up carries its own weight and tracking and is always
set in the display face, so it is always written with `font-display`
beside it (`font-display text-title`). The four steps below it are the
interface face, which is the page's default and needs no class.

**Labels.** A label is `text-chip font-semibold tracking-label text-muted`,
in sentence case: no capitals, no monospaced face. `SectionLabel` is that
rule as a component. A table's column header is
`text-caption font-medium text-muted`. Text that sits on a series fill is
`text-plane`.

Chart ticks are SVG text, which takes no utility: `chartChrome.ts` sets
them at 12 px in `Tokens.muted`.

No default Tailwind `text-{xs…9xl}` size class, and no arbitrary
`text-[Npx]`, appears anywhere in `web/src/**/*.tsx`. Grep to prove it
stays that way after a change.

Fonts: `--font-display` is Bricolage Grotesque (titles, page titles, large
figures, the wordmark) and `--font-sans` is Hanken Grotesk (everything
else), each with a real fallback stack. **Numbers are the interface face
with tabular figures** (`font-variant-numeric: tabular-nums`, set once on
`body`); there is no monospaced face. Both are variable fonts, weight axis
only, self-hosted through the `@fontsource-variable` packages and imported
once in `main.tsx` (Hanken Grotesk with its italic), so they are bundled
at build time and never fetched from a font host at runtime.

**`TextBlock`.** The literal text of a prompt, a command or exported
Markdown is set in the interface face, since there is no monospaced one:
a `pre`, `rounded-block border border-edge bg-plane p-3`, in
`text-caption text-ink2`, wrapped so a long word breaks rather than
scrolling the block sideways. `scroll` caps it at `max-h-64` with its
own scrollbar; without it the block is as tall as its text.

## Radii, by role

Defined as theme tokens (`index.css`'s `@theme inline`), not chosen ad hoc
per component:

| utility | value | Compact | role |
|---|---|---|---|
| `rounded-control` | 12px | 12px | inputs and selects (`Field`, `Select`), a row or a link that acts as a control, the chart tooltip and `Tooltip`, inline code, the picture of a `CardTile` |
| `rounded-block` | 14px | 14px | nested blocks: `Card elevation={2}`, `Finding`, `Callout`, `TextBlock`, `Skeleton`, a step of `OnboardingSteps` |
| `rounded-card` | 18px | 16px | cards and tiles: `Card`, `StatTile`, `DeckTile`, `EmptyState`, each of Home's three things; a `Dialog` |
| `rounded-hero` | 22px | 18px | the one lead panel of a page: Home's last session, first run |
| `rounded-pill` | 999px | 999px | `Button`, `Chip`, `Segmented`, `Meter`, a `Switch`'s track and disc, a disc (a step's number, the one behind an `EmptyState`'s icon) |

## Elevation

One recipe, `--lift`: a hairline highlight at the top edge and one soft
shadow underneath, `inset 0 1px 0 rgb(255 255 255 / 0.04), 0 12px 32px
-12px rgb(0 0 0 / 0.6)`. It is exposed as the `shadow-lift` utility and
applied to every surface raised from the page: `Card`, `StatTile`,
`DeckTile`, `ErrorNote`, the chart tooltip and `Tooltip`, a page's lead panel, each
of Home's three things, a `Dialog`.

`Card` takes an `elevation` prop. `1` (the default) is a page's own
top-level card: `surface-1`, `rounded-card`, a border in `edge`, and the
lift. `2` is a block nested inside one of those (the deck guide's
`LeakCard`/`PlanCard`, the match report's per-finding cards):
`surface-2`, `rounded-block`, and neither border nor shadow. A nested block
is set apart by its fill alone. `Finding` and `Callout` are nested blocks
too.

`Card` also takes a `tone`: `'accent'` swaps the border from `edge` to an
accent tint. It is never set through `className`, since that would fight
the default at equal specificity; `tone` is a real conditional inside
`Card` itself, so it always wins.

**The header.** The title's line holds the title and, at its right, the
`action`. The subtitle runs under it at the card's full width, so neither
a long subtitle nor a wide action squeezes the other into a column. An
action too wide for the title's line takes the line under the title, and
one wider than the card wraps its own text. Nothing is truncated. The
`action` slot is also where a short note beside a title goes (who wrote a
narrative, and when), as text in `text-caption text-muted`.

`Card`'s `art` slot renders above the header, edge to edge, clipped by the
card's own radius: see "Card art" below.

## Density

`--d` is `1` by default and `.85` when compact. `--spacing: calc(0.25rem *
var(--d))` in `@theme inline` makes every Tailwind spacing utility (`p-4`,
`gap-3`, …) scale automatically, with no hand-scaled classes; the type
ramp scales down to its floors, and the two large radii step down (the
table above).

**Compact is both a choice and a width.** `:root[data-density="compact"]`
is the choice. `@media (width < 48rem)` is the width: anything narrower
than Tailwind's `md` breakpoint is compact without being asked. Nothing
new is designed for that width any more (`docs/frontend.md`, "Widths"):
the media query stays for a browser tab made that narrow, and for the
layouts already built under it.

The choice is persisted to `localStorage` (every read/write wrapped in
`try/catch`: a private window or blocked storage must never break the
toggle itself), default `comfortable`. The control is a `Segmented` on
`/settings` (`pages/SettingsPage.tsx`). `shell/density.ts` holds the rest:
`useDensity()` for the control, and `applyStoredDensity()`, which
`main.tsx` calls before the first render, so a compact page never paints
comfortable first.

**A target's floor is spelled in pixels.** Spacing utilities scale with
density, so `min-h-11` is 44 px only when comfortable, and a narrow
window is always compact. A target that must stay 44 px high says
`min-h-[44px]`.

## Focus

One focus ring, from a token, for everything that takes focus: `index.css`
sets `:focus-visible` to a 2px outline in `--focus`, offset 2px. A
component never spells its own, which is why no primitive in
`components/ui/` carries a focus class.

One exception is the skip link's target, `<main id="page">`. It takes
focus so the next Tab starts inside the page, and it draws no ring,
because it is the page and not a control. The rule sits in `index.css`
beside the ring's own (`#page:focus-visible`), so no component spells it.
The other is the Guide's section block (`SECTION_CLASS` in
`views/GuideView.tsx`), which takes focus when a link scrolls it to the
top and, for the same reason, draws no ring. It is the one component that
spells a focus class, `outline-none!`, to beat the ring's rule.

## Links

A link in or beside text is a `TextLink`: the text's own colour
(`text-ink`) and an underline, which is `decoration-muted` until the
pointer is over it and `decoration-ink` then. The underline is what says
"link". A link never takes a series colour, which is data, and never the
accent, which is the brand and the primary action.

An `href` that begins with a single `/` is a place in the app. `TextLink`
renders the router's `Link` for it, and so does `Button` for its own
`href`, so following it never reloads the page. Anything else leaves the
app, and a `TextLink` opens it in a new tab
(`target="_blank" rel="noreferrer"`), so the dashboard stays where it was.

The way back to a list ("All matches", "All decks") is a `BackLink`: a
`TextLink` with `ArrowLeft` before its words, the arrow inside the link,
so the two are one target.

A link that acts as a control is not a `TextLink` and carries no
underline:

- **An item of a navigation** (the rail, the bottom bar and its sheet, a
  deck's Overview, Matchups and Guide) is `rounded-control` and
  `text-muted`, `text-ink` under the pointer, with `transition-chrome`.
  The current one is `bg-surface3 text-ink` and carries
  `aria-current="page"`.
- **A section's own nav link** (the deck guide's `SectionNav`, in its
  strip and its column) is `rounded-control` and `text-muted`,
  `text-ink` under the pointer, `bg-surface3 font-medium text-ink` when
  current: a navigation item's recipe, but marked
  `aria-current="true"`, not `"page"`, since it is not the page.
- **A row's way in** (a deck's name in `/decks`, a row of Home's recent
  matches, the words of a `DeckTile`) is `rounded-control` and takes
  `bg-surface3` under the pointer. A name keeps its colour; in the
  table, the muted "Unnamed deck" turns `text-ink` there. On a surface
  that holds art the way in is the words, or a `Button` under them,
  and never the whole surface: the art has a button of its own, and
  one control does not sit inside another.
- **An action** is a `Button` with an `href`.

## Form controls

`Field`, `Select`, `Switch` and `Dialog` (`docs/frontend.md`'s
"Shared primitives (`components/ui/`)") are the whole of a form. Each is
the native element under the house look, so the browser's own keyboard
and screen-reader behaviour is kept, never rebuilt.

- **A label is always drawn**, never a placeholder standing in for one:
  over a `Field`, in `text-caption font-medium text-ink2`; beside or over
  a `Select` by its `placement` (beside for a filter over a list, over
  for a form); on a `Switch`'s own row, in `text-body text-ink`, with its
  description under it in `text-caption text-muted`.
- **One box for text and choices**: `min-h-[44px]`, `rounded-control`, a
  border in `edge`, `bg-surface`, `text-ink`. A disabled control is the
  same box at `opacity-50`.
- **The sentence under a field** is its hint in `text-muted`, or its
  error in `text-loss` in the hint's place, with the border turned
  `loss`. The sentence carries the error; the colour only reinforces it,
  and the field says `aria-invalid`.
- **A switch says its state in a word**, "On" or "Off", in
  `text-caption text-ink2` beside it. The track is 44 × 24 px,
  `rounded-pill`, in `surface3` when off and the accent when on; the
  disc, 18 px, is `muted` off and `--on-accent` on, the only thing drawn
  on the accent. The whole row is not a target: only the switch is
  pressed, and its hit area keeps the 44 px floor.
- **A read-only control is text**: the label, then the value in
  `text-body text-ink`, or "Not set" in `text-muted`. No box, no greyed
  control, nothing that looks pressable.
- **A dialog is for a question that waits for an answer**, one that
  cannot be undone. It is `rounded-card`, `bg-surface`, a border in
  `edge` and the lift, at most `max-w-md`, over a backdrop of `plane` at
  70 percent. Its title is an `h2` in `font-display text-title`; its
  body `text-body text-ink2`; its buttons on the right, the safe one
  rightmost and primary. The other button says what it does ("Delete my
  cloud data", "Make a new one"), never "OK", "Yes" or "Confirm". There
  is no danger button: what a press destroys is said by its words, not
  by a red fill. A dialog holds three fields at most.
- **What a press did is said where it was pressed**: in the button's
  label ("Saving", "Saved") or in a sentence under the control. No toast,
  nothing that appears elsewhere on the page or leaves by itself.

## Mana pips

`components/ui/ManaPips.tsx`. Glyph paths are from the Mana project by
Andrew Gioia (github.com/andrewgioia/mana; font glyphs SIL OFL 1.1; mana
symbol imagery © Wizards of the Coast) — fetched once, at dev time, and
inlined as constants; nothing is fetched at runtime. Each pip is rendered as
its printed-card form: a disc in the mana colour, the glyph centred at ~72%
scale, filled `--mana-glyph`, with a subtle drop shadow.

Sizes are upscaled for legibility at distance, revised once already (18px
read as small at second-monitor distance at the first checkpoint):
`--pip: max(18px, calc(22px * var(--d)))` default, `--pip-lg: max(22px,
calc(28px * var(--d)))` for hero contexts (the current-match band's opponent
identity), and `--pip-sm: max(16px, calc(18px * var(--d)))` for a mana cost,
which sits inside a line of body text and is no taller than it. Compact
density never shrinks a default pip below 18px.

`<ManaPips colors="UB" size="md" | "lg" />` takes a WUBRG string in any
order and renders the letters present in canonical WUBRG order; a character
outside WUBRG is ignored; `null`/`undefined`/`''` renders nothing (rule 4:
unknown means no render, never a guess — never the word "Colourless"
either, since `''` covers both "revealed only colourless cards" and
"revealed cards whose colours are unknown", which cannot be told apart).
`role="img"` with an `aria-label` naming the colours in the dashboard's
language (keyed, `common.revealedColours`: `"Revealed colours: blue,
black"`) carries accessibility; each inner `svg` is `aria-hidden`.

`<ManaCost cost="{1}{U/R}{U/R}" />`, from the same file, draws a card's
mana cost as its printed symbols, at `--pip-sm`. A colour symbol is the
colour's pip; a hybrid is a disc split on the diagonal, the first
symbol upper-left, each half its own colour with its glyph small (a
`2/W` half is the grey disc with a `2`); a Phyrexian symbol is its
colour's disc carrying a Φ; generic, `X`, `C` and `S` are a grey disc,
`--mana-c`, carrying the symbol's text in `--mana-glyph`. It draws the
front face only (`costSymbols`, the same face `effects.mana_value`
reads), and reads Arena's parenthesised hybrid, `{(U/B)}`, as `{U/B}`.
A null or empty cost, a land's, renders nothing. The accessible label
is the cost in braces (`common.manaCost`), since every symbol in it is
drawn. `--mana-c` is in `scripts/validate_palette.py` with the five
colours.

**The boundary rule:** mana colours are identity chrome: beside a deck
or archetype name, or as a table row's label. **They never colour a
chart mark.** `ColorBars`' colour-pool bars and the share `Meter`s
on Field and Home stay one hue, per docs/frontend.md's "one hue for
nominal categories" and "color follows the entity" rules; a pip may
label the row a bar belongs to, the bar itself never changes colour to
match. This is also why recharts' own category-axis ticks never carry a
pip (they render plain SVG text): where a pip is called for beside a
chart, it lives in the numbers table, never on the chart canvas.

Pips and colour letters never say the same thing twice. Where pips sit
beside an opponent label that begins with its own colour letters (the
colours-and-signature fallback), the letters are stripped for display —
`docs/frontend-pages.md`'s "The opponent-deck read".

## Card art

A card has two pictures, and they are different downloads with different
rules (`docs/attribution.md`, and `docs/frontend.md`'s "Card images" for
the two routes):

- **The whole card**, shown by `CardImage` and `CardPreview`, and by
  `CardTile` (`components/ui/CardTile.tsx`) where something is known
  about the card and has to be said beside it.
- **The card's art alone**, shown by `CardArt` (`components/ui/CardArt.tsx`)
  from `/api/cards/{grp_id}/art`. It is its own picture, never a crop of
  the whole card.

The rules for showing them. The first is Scryfall's own; the second and
third are this project's reading of what Scryfall asks, not Scryfall's
wording:

- **A whole card image is shown whole**: never cropped, covered, stretched,
  tinted or blurred. Nothing is laid over it, and nothing around it
  dims it. What is known about a card is written under its picture,
  in a `CardTile`'s caption.
- **Art keeps its own colours**: no `opacity`, `filter` or blend mode on
  it. Text never sits on the picture. A fade is a gradient at one edge,
  from transparent to the colour of the surface behind the box, and text
  sits where the gradient has arrived.
- **Every piece of art leads to the whole card**, which carries the
  artist's name and the copyright line: the button in the art's corner
  shows it on hover, on keyboard focus and on tap. The Credits page says
  so (`credits.ts`).
- **Neither picture is ever behind a paywall.** Scryfall's terms forbid one
  in front of their data.

Using `CardArt`:

- **The box needs a height, always.** `className` gives the box its shape
  (its size, its radius, its place), and the layer inside it fills that
  height. A box with no height of its own shows nothing.
- `y` moves the picture up or down inside the box, in percent (`30` by
  default; `0` shows its top). The `card-art` utility in `index.css` does
  the rest: the picture covers the box at any shape.
- `fade` is `'none'`, `'down'`, `'left'` or `'right'`. The colour it
  arrives at is `--art-surface`, which `Card`, `Finding`, `Callout` and
  `DeckTile` each set to their own fill; on no such surface it is the
  plane. A surface that holds art and is none of those sets
  `--art-surface` itself, as Home's lead panel and its three things do.
  The last 15% of the fade is that colour alone, the band where text
  may begin.
- **Art is never the only carrier of anything.** With no id, or a picture
  that does not load (a new install, offline, a card Scryfall cannot map),
  the box shows nothing, the surface behind it stands, and there is no
  button. A page reads the same without its art.
- Inside a card, art goes in `Card`'s `art` slot:
  `art={<CardArt … fade="down" className="h-32" />}`.
- **A page shows a card once.** A page with several pieces of art takes
  each from `lib/matchArt.ts`: `castCards` is the cards one side cast in
  a match, and `takeUnused` takes the first of them that the page does
  not show yet (`docs/frontend-pages.md`'s "Home"). The reference page is the
  exception, since it shows the same few cards in every shape.

Using `CardTile`:

- It takes `grpId`, `name`, a `width` in pixels and the caption as
  `children`. The picture keeps the card's own shape at that width.
  With no `grpId` (a card known by name, with no picture on file) the
  picture is the name in a box of the card's shape, which is not
  `CardImage`'s dashed placeholder for a card hidden from the viewer.
- **The caption is under the picture**, in `text-caption` with
  tabular figures, `text-ink`; a second line that says less is
  `text-muted`. It keeps the height of one line when it is empty, so
  a row of tiles keeps one line of pictures whether or not each card
  has something to say. A mark that needs more than a word is a small
  `Chip` in the caption.
- **The tile carries no `title`.** What a tooltip would say is in the
  caption, or is said once in a line under the row
  (`text-caption text-muted`), which a pointer is not needed to read.
- **A row of tiles is never dimmed** to say its cards are a guess.
  The row's label and the line under it say so.

## Motion

There is no house rule restricting motion, and no `isAnimationActive={false}`
anywhere. An early idea to make focus mode's panels motionless was
explicitly rejected at the Stage 3 checkpoint: recharts' own draw-in
animation, the `Skeleton` shimmer, a smooth scroll to a section (the deck
guide's `SectionNav`, `goToSection`), and ordinary hover and transition
polish are all fine. `.transition-chrome` in `index.css` is the one
transition for chrome (colour, background and border, 120ms). Colour
only: nothing in the chrome changes size.

**A chart on a page that renders on a clock is a memoized component of
its own, and takes nothing that moves with the clock.** A render of the
chart's component starts its motion over, so on a page that renders
every second the motion never ends, and a label drawn at the motion's
end never shows. Home's `WeeklyWinrate` is the example
(`docs/frontend.md`'s "Charts"). Turning the motion off is not the cure:
`isAnimationActive={false}` stays out.

The one thing that is still respected is the standing web accessibility
convention, `prefers-reduced-motion: reduce`. It turns off
`.transition-chrome`, every `animate-pulse` (the live dot, the
`Skeleton` shimmer and the indeterminate `Meter`), the turn of `Disclosure`'s chevron, the slide of a
`Switch`'s disc (120ms), and `SectionNav`'s own scroll: `goToSection`
checks the media query itself, since `window.scrollTo`'s `behavior` option
reads no CSS. That is a user preference honored on every project, not a
project-specific "no motion" policy.

## The reference page

`/design` renders `views/DesignView.tsx` in place of the app: every token
and every primitive in every state, under the title "Design reference".
Its route stands outside the shell (`routes.tsx`), so it has no rail and
no footer. No link in the app leads to it; it is opened by its address,
or from the second reference page below.
`pages/DesignPage.tsx` loads it lazily, so it is a chunk of its own that
no other page pays for.

Its sections: palette, type ramp, radii and elevation, buttons, links,
chips, cards, stat tiles, deck tile, empty state, onboarding steps,
findings, callouts, text block, disclosure, tooltip, segmented control, fields,
selects, switches, dialog, meters, bars, data table, line chart, bar
chart, mana pips and costs, glyph and wordmark, card tile, card art.

Its names and numbers are invented. The one real thing on it is its
cards: three at most from the newest Arena match, chosen by
`lib/matchArt.ts`'s rule, the viewer's first and then the opponent's.
The card art section shows their art and the card tile section their
whole pictures, under invented captions. With no match recorded yet
the card art section says so, and each tile is an invented name in
the card's shape.

A skeleton shown there as a sample sits inside an element carrying
`data-sample`, which tells the screenshot script that it is not a page
still loading (`docs/frontend-site.md`'s "Screenshots").

`/design/surfaces`, linked from the top of `/design` and back, is the second
reference page: it draws surfaces rather than primitives, Settings in every
state a desktop shell can hand over, picked by a "Sample" select at its top,
a report's card as each writer draws it, and the Detailed Logs drawing at
both its sizes. Everything on it is invented (`docs/frontend.md`, "The
second reference page"). A new state of a surface gets its sample there, as
a new state of a primitive gets one on `/design`.

## Where the code is still older

The primitives in `components/ui/` follow every rule in this file. Some
components outside it were written before a rule existed and still carry
what the rule replaces:

- Radii chosen per component (`rounded`, `rounded-md`, `rounded-lg`,
  `rounded-xl`, `rounded-full`) and one `shadow-xl`, on
  `CardImage.tsx`'s enlarged card.
- `CardImage`'s two placeholders, no id (a dashed box) and a failed
  load (the name in a small label), are plain `rounded`, not
  `rounded-control` or a `Chip`.
- `Disclosure`'s `summary` takes a plain string, not a node, so nothing
  but the chevron and the words can sit in its `<summary>`, which also
  carries no 44 px floor. The Guide's disclosures, in `PlayCard`,
  `ListCard` and `LeakCard`, sit under it, and so does Field's "Where
  these numbers come from".

Each is replaced when its component is next rebuilt. None of them is a
pattern to copy.

## Numbers

Every percent, record and small sample on the dashboard is written one
way, by the helpers in `lib/format.ts` and `lib/sample.ts`. A page that
writes its own is the thing this section exists to stop: before it, the
same win rate read "57.5%" on one page, "58" on the next and "won 23 of
40" on a third.

**A percent is a whole number with its sign.** `lib/format.ts`'s
`formatPercent` takes a fraction and writes it through `Intl` in the
reader's language: "58%", "58 %" where the language puts a space there.
A fraction strictly between 0 and 0.01 reads "<1%", and one strictly
between 0.99 and 1 reads ">99%", so a card that is not certain never
reads as certain and a card that is possible never reads as impossible.
No decimal: the samples behind these numbers are a few dozen matches,
and a tenth of a point would claim a precision they do not have. A
catalogue string never writes `%` after `{{pct}}`; the formatter writes
it. A points figure (a gap between two rates, a movement since a reset)
is not a percent and keeps its own form: the Guide's movement since a
reset keeps one decimal ("up 14.0 points") beside whole-number shares,
so it can differ by a point from the difference the two shares show.

**A record is wins–losses.** `formatRecord(wins, losses)` writes "6–3",
with an en dash held to its numbers by word joiners so a line never
breaks inside it. Never "won 6 of 9": that form hides the losses
behind a subtraction. A share of a corpus is not a record and stays
"N of M lists". The match report's headline and Home's last-match
title follow the same order: "Lost 1–2 to X", the viewer's games first.

**A draw is never a loss.** A record counts wins and losses; a draw is
neither, and neither is a match still in progress. Where a caller has
only a count played and a count won, losses are played minus won minus
draws, never played minus won. `/api/metrics/play-draw`'s
`games_completed` counts draws, so the deck strip's Play vs draw, the
match report's play/draw record and `sensei-top report` read `games_won`
and `games_lost` instead.

**Ten finished matches before a rate, five before a rough one.** A
personal record has two thresholds, `RATE_MIN_MATCHES` (10) and
`ROUGH_RATE_MIN` (5), over matches, or over games for a games figure.
From ten up, a tile's figure is the rate and its line is the record
(a deck's tile on Decks and Home says "win rate · 35–25").
From five to nine, the figure is the rate drawn muted, and its line is
the record and "rough" ("rough win rate · 6–3, under 10 matches" on a
deck's tile): a reader sees which way a matchup leans without
reading it as a measurement. Under five, the figure is the record, drawn
muted, and its line says it is too few for a rate. A table's Rate cell
is the rate from ten, the rate muted from five to nine, and "too few",
muted, under five, on one line (`whitespace-nowrap`), beside the record
its own column already has. A row is never left out for being small,
since a missing row reads as a matchup never played; an em dash means
nothing at all, never "too few". `rateOrRecord` (a tile) and `rateCell`
(a cell, drawn by `components/RateCell.tsx`) in `lib/sample.ts` make the
choice, so no component branches on the count. The rough rate needs a
muted figure, so it is only where one can be drawn: where only one line
is free (a version's row, a field row's caption, the keep-cost sentence)
the line is "58% · 35–25" from ten up and the record alone under it (a
version's row on a deck's page says "58% win rate · 35–25"), a
sentence (the session line, the play/draw line) keeps ten alone, and so
does a ranking (Matchups' best and worst). A chart keeps its hollow dot
for a point under ten, since a chart cannot draw a record. The Coach
keeps ten alone too: its rates come from the server, which marks one
under ten anecdotal (`review/leaks.py`, `MIN_SAMPLE`) and sends no
percent for it.

Field evidence is not a personal record. It measures other people's
lists, so it keeps the corpus thresholds in `docs/metagame.md`
(`MIN_TRUSTED_FIELD_SAMPLE`, `WINRATE_MIN_MATCHES`), from the same
`lib/sample.ts`.

**A record table's columns come in one order.** Name · Matches ·
Record · Rate, then any split (G1 · Post-board, then Play · Draw), then
the field's columns (Share, Field rate). A table without a column skips
it and keeps the rest in this order, so a reader who learned one table
reads every other one without looking.

## Rules a new component follows

- **Tokens only.** A color is a CSS custom property or a `Tokens` slot,
  never a hex literal typed at the call site (chart marks are the one place
  a literal hex is unavoidable, and even there it comes from `theme.ts`'s
  `Tokens`, not a fresh value).
- **A number is written by `lib/format.ts` and `lib/sample.ts`**: a
  percent, a record, a rate under ten (rough or too few) and a record
  table's column order
  follow "Numbers" above, never a format chosen per component.
- **The accent is never data**, and `--on-accent` is the only text on it.
- **Semantic type utilities only.** `text-body`, `text-caption`, etc. — never
  a default Tailwind size class, never an arbitrary `text-[Npx]`. A step
  from `title` up comes with `font-display`.
- **A label follows the label rule**: sentence case, `SectionLabel` or its
  four classes. No capitals, no monospaced face.
- **Text carries meaning; colour reinforces it.** A `Chip`'s variant, a
  result's `win`/`loss` colour, a severity's tint — none of them is the only
  signal. The word is always present.
- **Radii and elevation come from the shared roles above**, not a new
  `rounded-*` or shadow chosen per component.
- **No focus class.** The one ring in `index.css` covers everything that
  takes focus.
- **A link is a primitive or one of the two control looks** in "Links"
  above: `TextLink`, `BackLink`, a `Button` with an `href`, an item of a
  navigation, a row's way in. Never an `<a>` with classes of its own.
- **A 44 px floor says `min-h-[44px]`**, never a spacing utility, which
  density scales.
- **A pip labels a row; it never becomes a chart mark's colour** (the
  boundary rule above).
- **A word the page cannot explain in place wears a `Tooltip`**
  (`components/ui/Tooltip.tsx`), never a sentence in a `title`, which a
  keyboard cannot open. The word becomes a focusable
  trigger, marked by a dotted underline in `muted` and the help cursor:
  dotted, so it never reads as a link's solid one. The tip is one plain
  sentence in the chart tooltip's look (`surface-3`, `edge-strong`,
  `rounded-control`, the lift), under the word. It opens on hover and on
  keyboard focus, stays open while the pointer moves onto it, closes on
  Escape until the next hover or focus, and is tied to its word by
  `aria-describedby`, so a screen reader reads it closed or open. The
  trigger holds text only: a control inside it would be a second stop
  for the keyboard. The match report's beat labels are the first user
  (`docs/frontend-pages.md`, "The match report").
- **A whole card image is shown whole, and art follows "Card art" above.**
  A `CardArt` box always has a height, and nothing depends on the picture
  arriving.
- **What is known about a card is written under it**, in a
  `CardTile`'s caption, and a row of tiles says once, in a line under
  it, what its captions mean. Never a mark on the picture, never a
  sentence in a `title`.
- **A new primitive, or a new state of one, gets its sample on the
  reference page in the same change.**
- **A form's control is `Field`, `Select` or `Switch`**, and a question
  that waits for an answer is a `Dialog`: never a new input, a bare
  `select` or a checkbox standing for a switch ("Form controls" above).
- **What a press did is said where it was pressed.** No toast.
- **The safe choice is a dialog's primary button**, and the other says
  what it does.
- **A free feature shows no lock, no badge and no price.** A price is
  written only in the plan's own card, from text a desktop shell hands
  over; a report's card says who writes it in a sentence, never a mark.
- **A place with nothing to show draws an `EmptyState`** with the
  place's icon, a title and one sentence, which says what will appear
  and what causes it.
- **A chart on a page that renders on a clock is memoized**, and takes
  nothing that moves with the clock (see "Motion" above).
- **No motion restriction** — see "Motion" above. `prefers-reduced-motion` is
  still respected; a house style banning animation is not.
