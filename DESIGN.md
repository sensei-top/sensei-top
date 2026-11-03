---
name: Sensei Top site
description: The visual system of senseitop.com, the static landing, help and privacy pages under site/.
colors:
  accent: "#f4b6e4"
  accent-hover: "#f8c9eb"
  on-accent: "#1a1020"
  plane: "#0b0c14"
  surface-1: "#12141f"
  surface-2: "#1a1d2c"
  surface-3: "#24283d"
  surface-3-hover: "#2f3450"
  line: "rgb(190 198 255 / 0.10)"
  line-2: "rgb(190 198 255 / 0.18)"
  ink: "#f2f3f8"
  ink-2: "#b9bdd0"
  muted: "#989db5"
typography:
  display:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(34px, 4.25vw, 62px)"
    fontWeight: 600
    lineHeight: 1.06
    letterSpacing: "-0.03em"
  display-pt-br:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(34px, 3.6vw, 52px)"
    fontWeight: 600
    lineHeight: 1.06
    letterSpacing: "-0.03em"
  page-title:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(32px, 7.4vw, 44px)"
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(24px, 3vw, 32px)"
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: "-0.022em"
  headline-read:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: "-0.022em"
  title:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: "-0.012em"
  lead:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.55
  body:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
  button:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 550
    letterSpacing: "-0.006em"
  nav:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 450
  note:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  caption:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.3
  footer:
    fontFamily: "Inter Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  code: "6px"
  frame: "14px"
  panel: "20px"
  pill: "999px"
spacing:
  gutter: "clamp(20px, 4vw, 40px)"
  section: "clamp(72px, 10vw, 136px)"
  feature: "clamp(40px, 6vw, 72px)"
  page-wide: "75rem"
  page-read: "44rem"
  stage-width: "1080px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  xxl: "56px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: "0 22px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.surface-3}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: "0 22px"
    height: "44px"
  button-secondary-hover:
    backgroundColor: "{colors.surface-3-hover}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: "0 22px"
    height: "44px"
  button-quiet-hover:
    backgroundColor: "{colors.surface-1}"
  video-control:
    backgroundColor: "rgb(11 12 20 / .72)"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    size: "36px"
  video-play-poster:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.pill}"
    size: "64px"
  shot-caption:
    textColor: "{colors.ink-2}"
    typography: "{typography.caption}"
    padding: "9px 14px"
  promise-panel:
    backgroundColor: "{colors.surface-1}"
    rounded: "{rounded.panel}"
    padding: "clamp(24px, 4vw, 56px)"
---

# Design System: Sensei Top site

This file describes `site/` only: the public landing, help, privacy and other static pages. The dashboard's visual system is [`docs/design-system.md`](docs/design-system.md). The two are separate by decision, so dashboard work does not inherit anything written here.

## Overview

**Creative North Star: "The Product Is the Pitch"**

The landing is a category-standard product page, executed exactly. A large framed recording of the real dashboard sits directly under the headline, and each page of the app is then shown and explained in the order the video visits it. Convention is the commitment: there is no metaphor, no quirk and no game imagery laid over the page, so the only vivid thing on screen is the product.

The world is one near-black ground, cool off-white text, one pink accent and one typeface. Depth comes from a lighter framed surface and hairlines rather than from stacked cards. The landings persuade with generous section spacing and wide frames; help, privacy, Linux, Magic Online, Untapped and 404 take the same tokens, header and footer in a single narrow reading column and stay plain.

**Key Characteristics:**
- Dark only: the stylesheet declares a dark color scheme and has no light theme.
- One accent, kept rare enough that the primary action is always the first thing to press.
- Inter Variable alone, 600 at display size with tight tracking.
- Pills for actions, 14 px corners for framed media, 1 px cool hairlines between everything else.
- Real screens from the demo database are the only imagery.
- English and Brazilian Portuguese share one markup and one stylesheet.

## Colors

A cool blue-black ramp with cool off-white text, and one soft pink as the only hue that speaks.

### Primary
- **Soft Signal Pink** (#f4b6e4): the primary button, the play button on the poster, the current chapter's progress line, the focus ring and text selection. The logo mark and the roadmap diagram carry it too, and its low-alpha form tints the hero glow.
- **Lifted Pink** (#f8c9eb): hover on the two pink buttons, nothing else.
- **Pink Ink** (#1a1020): text and icons on pink.

### Neutral
- **Night Plane** (#0b0c14): the page ground, the theme color, and the base of the translucent header (`rgb(11 12 20 / .82)`), video controls and caption cues.
- **Raised Night** (#12141f): the frame and screenshot backing, the promise panel, quiet-button hover.
- **Mid Night** (#1a1d2c): declared as the second surface step; the stylesheet does not use it directly, and the roadmap diagram does.
- **Control Slate** (#24283d): the secondary button, inline code, the current language, the resting chapter line, the scrollbar thumb.
- **Control Slate Hover** (#2f3450): secondary-button hover only.
- **Hairline** (`rgb(190 198 255 / 0.10)`): quiet dividers: the header's edge, section and row rules, the footer's top.
- **Strong Hairline** (`rgb(190 198 255 / 0.18)`): frame and shot outlines, the language switch's border, the quiet button's outline, step and pair rules, link underlines at rest.
- **Ink** (#f2f3f8): headings, links, emphasis, button labels.
- **Soft Ink** (#b9bdd0): running text, the lead, navigation at rest, screenshot captions.
- **Muted Ink** (#989db5): facts, notes, the footer's text, chapters at rest, list markers.

### Named Rules
**The One Pink Rule.** Pink marks what to press, where the video is, and where focus is. It is never a heading color, a section fill or a decorative stroke on the page.

**The One Glow Rule.** The low-alpha pink glow behind the hero (10% alpha) and in the frame's shadow (22% alpha) is kept by decision as atmosphere, and an automated warning on it is expected. It stays this faint and appears nowhere else.

## Typography

**Display Font:** Inter Variable (with Segoe UI, system-ui, sans-serif)
**Body Font:** Inter Variable (same stack)

**Character:** One self-hosted variable face doing every job, separated by size and by fine weight steps (400, 450, 500, 550, 600) instead of a pairing. Tight tracking at display size, none in running text.

### Hierarchy
- **Display** (600, fluid to 62 px, 1.06, -0.03em): the landing's one headline, centred, up to 1120 px wide; about 61 px on two lines at 1440. Portuguese runs longer and caps at 52 px.
- **Page title** (600, fluid to 44 px, 1.12, -0.03em): the one heading on a Read page.
- **Headline** (600, fluid to 32 px, 1.12, -0.022em): landing section and feature headings; a fixed 24 px on Read pages.
- **Title** (600, 18 px, 1.12, -0.012em): sub-headings and the two written-report columns.
- **Lead** (400, 18 px, 1.55): the opening paragraph; 47rem wide in the hero.
- **Body** (400, 16 px, 1.6): running text in Soft Ink. Measures as built are 62ch beside feature shots, 56ch in the written-report pair, 68ch in the promise rows, and the 44rem column on Read pages.
- **Label** (450 to 550, 12 to 15 px): buttons at 15 px and 550, navigation at 14 px and 450, captions and chapters at 13 px and 500, the language switch at 12 px and 550.

Emphasis is weight 550 in Ink. On help pages `<b>` quotes a label the app itself shows and `<strong>` stresses a phrase; they look the same and `tests/test_site.py` tells them apart.

### Named Rules
**The One Face Rule.** Inter Variable, self-hosted, carries every string on the site, video captions included. Hierarchy is size and weight, never a second family, italics or uppercase.

## Layout

Two widths share one page skeleton. Landings use a 75rem container and Read pages a 44rem column, both with a fluid gutter (20 to 40 px). Sections on the landing are separated by a fluid 72 to 136 px step; feature rows take 40 to 72 px of block padding.

The first viewport runs: one-line header, centred headline, lead, facts, centred pill buttons with the primary first, then a 16:9 frame up to 1080 px wide with its chapter strip directly under it. The frame runs below the fold on purpose.

The landing then follows a fixed sequence: Get started, six feature rows, written reports, promise rows, and a last row of download buttons before the footer.

At 1024 px and up, feature rows alternate a 4:8 split, with the side switching on every second row. The two full-page rows, Live and Field, instead put heading and text across the top in 5:7 and give the screenshot the full width. Promise rows put the heading in a 4-column rail with content in the other 8. Steps become three columns and the written-report pair two.

At 640 px and below, the header stops sticking and the navigation takes its own line, buttons go full width, and the facts become two columns. The roadmap diagram is hidden below 700 px, where its text would be too small; the same words stay as lists at every width. Phones see the same screenshot files as desktops.

## Elevation & Depth

A hybrid. The page is flat and tonal: dividers are hairlines and the one panel is a tonal step. Only framed product media lifts, with soft shadows that fall away from the ground.

### Shadow Vocabulary
- **Frame** (`box-shadow: 0 0 0 1px var(--line-2), 0 1px 0 0 rgb(255 255 255 / .06) inset, 0 40px 90px -30px rgb(0 0 0 / .8), 0 30px 120px -40px rgb(244 182 228 / .22)`): the hero's video only: outline, top sheen, deep drop and the kept glow.
- **Shot** (`box-shadow: 0 0 0 1px var(--line-2), 0 30px 70px -36px rgb(0 0 0 / .85)`): every feature screenshot; the frame without sheen or glow.
- **Poster play** (`box-shadow: 0 10px 30px -8px rgb(0 0 0 / .7)`): the large play button on the poster.
- **Inset outline** (`box-shadow: inset 0 0 0 1px` with a hairline color): the quiet button, the video controls and the promise panel, so an outline adds no size.

Blur is reserved for what floats over moving content: the sticky header (`blur(14px) saturate(1.4)`) and the video controls (`blur(10px)`).

### Named Rules
**The Media Lifts Rule.** Only the video and the screenshots cast a drop shadow. Text blocks do not float.

## Shapes

Three corners, each with one job: fully round for anything pressed or toggled (999 px), softly rounded for framed media (14 px), and a larger curve (20 px) for the single promise panel. Inline code and the brand mark take 6 px; the focus ring 4 px. Rules are 1 px, except the 2 px chapter line. Icons are drawn SVG, filled or stroked at 1.4 on a 16 px grid, in the current text color.

## Components

### Buttons
Confident pills that always come as a set.
- **Shape:** fully round (999 px), at least 44 px tall.
- **Primary:** pink fill with Pink Ink. It always renders first, whatever the source order.
- **Secondary:** Control Slate with Ink.
- **Quiet:** transparent with an inset Strong Hairline outline, for the third choice.
- **Hover / Focus:** the fill changes over 150 ms, a press moves down 1 px, and focus is a 2 px pink ring at 2 px offset.
- **The set:** three buttons, in the hero, under Get started and before the footer. The primary goes to the Microsoft Store unless the Worker's platform match changes it: a Linux visitor gets Linux as primary, the installer stays quiet, and a macOS or phone visitor keeps the buttons as they are with a note beneath.

### Navigation
- **Style:** a sticky translucent line with the brand on the left, navigation at 14 px in Soft Ink going to Ink on hover, and the language switch. Its Portuguese and English links keep each page's address in step.
- **Language switch:** a small outlined pill with a globe icon; the current language sits on Control Slate.

### Hero Video Frame
The signature surface. A 16:9 recording in a 14 px frame with the Frame shadow, entering once over 900 ms.
- **Poster:** a 64 px pink play button, centred, is the one thing to press.
- **Playing:** pause and captions are 36 px translucent circles top right at every width. They touch the recording's own chip and icons, which is accepted. Captions on inverts to Ink on Night Plane.
- **Autoplay:** muted, looping, and only with motion allowed, at 700 px and wider, and without a data-saver request. Otherwise the poster waits.
- **Without script:** the poster with native controls.
- **Cues:** Inter on translucent Night Plane, wrapped narrower than the frame so they run short of the buttons.

### Chapter Strip
Five equal segments under the frame, named after the app's pages. A 2 px Control Slate line tops each; the current one fills with pink in proportion to its progress and its label turns Ink. A press seeks the video; without script each is a link to its feature row.

### Feature Row
Heading and text beside a Shot: a 14 px frame on Raised Night with a one-line caption bar naming the page, at 13 px over a Hairline rule. Rows rise once into view where scroll timelines exist.

### Promise Rows
Long reading rows divided by Hairlines. The first, what never leaves the machine, is the one filled panel: Raised Night, 20 px corners, inset outline. The written-report pair and the numbered steps also separate with a top rule and no fill.

### Read-Page Elements
- **Contents line:** a wrapping row of links at 14 px between two Hairlines.
- **Inline code:** Control Slate, 6 px corners, in Inter rather than a monospace.
- **Note:** Muted Ink at 14 px.

### Footer
Muted Ink at 13 px, at most 90ch, under a Hairline, with links in Soft Ink. The Fan Content notice and the data credits appear on every page.

## Do's and Don'ts

### Do:
- **Do** take every tracked screenshot from the demo database (`docs/frontend-site.md`, "The demo database"); nothing from a real one enters this site.
- **Do** use focal crops for Home, match report, Matchups and Coach, and full-page shots for Live and Field.
- **Do** keep the three-button set in all three places, with the primary rendered first.
- **Do** keep pause and captions top right of the video at every width.
- **Do** turn all entrance motion off under reduced motion: the frame's 900 ms entrance and the rows' rise, both on `cubic-bezier(.16, 1, .3, 1)`.
- **Do** give a Read page the shared tokens, header and footer and nothing from the landing's stage.
- **Do** size type for the longer language: Portuguese takes its own display size rather than a shortened sentence.

### Don't:
- **Don't** apply this file to the dashboard; `docs/design-system.md` governs it.
- **Don't** add a visible demo-data label to the screenshots or the video.
- **Don't** make phone-specific crops of the screenshots.
- **Don't** add a second accent hue or a second typeface.
- **Don't** put a kicker or eyebrow above a heading; the shot's caption bar labels a screenshot and is not one.
- **Don't** use gradient text, or any gradient beyond the hero's one glow.
- **Don't** build page sections as grids of filled cards; rows divided by hairlines are the structure, and the promise panel stays the only filled block.
- **Don't** use emoji or text glyphs as icons; icons are drawn SVG, and the middle dot between facts and links is punctuation.
