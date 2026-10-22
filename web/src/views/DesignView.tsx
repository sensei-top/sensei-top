/**
 * The design system's reference page: every token and every primitive in
 * every state, at `/design`. No link in the app leads to it; the second
 * reference page, `/design/surfaces`, links back to it. Its names and
 * numbers are invented; the one thing it reads is card art, whose ids come
 * from a request the dashboard already makes.
 */
import { Plus, RefreshCw } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ChartHover,
  XAxis,
  YAxis,
} from 'recharts'
import { useMatchDetail, useMatches, type MatchDetail } from '../api'
import { ChartTooltip } from '../components/ChartTooltip'
import { axisProps, gridProps, percentLabel } from '../components/chartChrome'
import {
  BrandGlyph,
  Button,
  Callout,
  Card,
  CardArt,
  CardTile,
  Chip,
  ColorBars,
  CurveBars,
  DataTable,
  DeckTile,
  Dialog,
  Disclosure,
  EmptyState,
  Field,
  Finding,
  IntervalBar,
  ManaCost,
  ManaPips,
  Meter,
  OnboardingSteps,
  PageHeader,
  SectionLabel,
  Segmented,
  Select,
  Skeleton,
  StatTile,
  Switch,
  TextBlock,
  TextLink,
  Tooltip,
  TwoSidedMeter,
  Wordmark,
  severityChip,
  type ButtonSize,
  type ButtonVariant,
  type ChipVariant,
  type FindingWeight,
} from '../components/ui'
import { formatPercent } from '../lib/format'
import { castCards, takeUnused, type ArtCard } from '../lib/matchArt'
import { NBSP } from '../lib/matchups'
import { placeById } from '../shell/places'
import { useTokens } from '../theme'

/** Up to this many distinct cards; the shapes below reuse them in turn. */
const ART_CARDS = 3

/** The newest match's cards by `lib/matchArt.ts`'s rule, the viewer's
 *  first and then the opponent's, distinct by id. Nothing else of the
 *  match is read. */
function artCards(detail: MatchDetail | undefined): ArtCard[] {
  const used = new Set<number>()
  const cards: ArtCard[] = []
  for (const side of ['self', 'opponent'] as const) {
    const cast = castCards(detail, side)
    for (let card = takeUnused(cast, used); card && cards.length < ART_CARDS; card = takeUnused(cast, used)) {
      cards.push(card)
    }
  }
  return cards
}

export default function DesignView() {
  const matches = useMatches()
  const newest = matches.data?.[0]?.match_id
  return newest ? <WithMatchArt matchId={newest} /> : <Reference art={[]} />
}

/** Split out because `useMatchDetail` always asks: it renders only once
 *  there is a match to ask about. */
function WithMatchArt({ matchId }: { matchId: string }) {
  const detail = useMatchDetail(matchId)
  return <Reference art={artCards(detail.data)} />
}

function Reference({ art }: { art: ArtCard[] }) {
  return (
    <main className="mx-auto max-w-6xl space-y-14 px-4 py-8 sm:px-8 sm:py-12">
      <PageHeader
        kicker="Sensei Top"
        title="Design reference"
        lead="Every token and every component, in every state. The names and numbers on this page are invented. Only the card art is real: it comes from cards this copy has already seen."
        actions={
          <TextLink href="/design/surfaces" className="inline-flex min-h-[44px] items-center">
            Surfaces
          </TextLink>
        }
      />
      <Palette />
      <TypeRamp />
      <RadiiAndElevation />
      <Buttons />
      <Links />
      <Chips />
      <Cards art={art} />
      <StatTiles />
      <DeckTiles art={art} />
      <EmptyStates />
      <Onboarding />
      <Findings />
      <Callouts />
      <TextBlocks />
      <Disclosures />
      <Tooltips />
      <SegmentedControls />
      <Fields />
      <Selects />
      <Switches />
      <DialogSample />
      <Meters />
      <BarsSection />
      <Table />
      <LineChartSection />
      <BarChartSection />
      <Pips />
      <Brand />
      <CardTiles art={art} />
      <ArtShapes art={art} />
    </main>
  )
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="space-y-4">
      <h2 id={`${id}-title`} className="font-display text-heading text-ink">
        {title}
      </h2>
      {children}
    </section>
  )
}

/* ---------------------------------------------------------------- tokens */

const PALETTE: { group: string; tokens: string[] }[] = [
  { group: 'Surfaces', tokens: ['--plane', '--surface-1', '--surface-2', '--surface-3'] },
  { group: 'Lines and edges', tokens: ['--line', '--line-2', '--edge', '--edge-strong'] },
  { group: 'Text', tokens: ['--ink', '--ink-2', '--muted'] },
  { group: 'Brand and focus', tokens: ['--accent', '--on-accent', '--focus'] },
  { group: 'Series', tokens: ['--series-1', '--series-2', '--series-3'] },
  { group: 'Outcomes', tokens: ['--win', '--loss', '--warn'] },
  {
    group: 'Mana',
    tokens: ['--mana-w', '--mana-u', '--mana-b', '--mana-r', '--mana-g', '--mana-glyph'],
  },
]

/** Each value as the browser resolved it, so the page cannot drift from
 *  index.css: it holds no colour of its own. */
function readTokens(): Record<string, string> {
  const style = getComputedStyle(document.documentElement)
  return Object.fromEntries(
    PALETTE.flatMap(({ tokens }) => tokens).map((token) => [token, style.getPropertyValue(token).trim()]),
  )
}

function Palette() {
  const [values] = useState(readTokens)
  return (
    <Section id="palette" title="Palette">
      {PALETTE.map(({ group, tokens }) => (
        <div key={group} className="space-y-2">
          <SectionLabel>{group}</SectionLabel>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {tokens.map((token) => (
              <li key={token} className="min-w-0">
                <div
                  aria-hidden
                  className="h-14 rounded-control border border-edge"
                  style={{ background: `var(${token})` }}
                />
                <div className="mt-1.5 text-caption text-ink">{token}</div>
                <div className="text-caption break-all text-muted">{values[token] || '—'}</div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </Section>
  )
}

const RAMP: { step: string; className: string; sample: string }[] = [
  { step: 'display', className: 'font-display text-display text-ink', sample: '61%' },
  { step: 'hero', className: 'font-display text-hero text-ink', sample: 'Azure Kites' },
  { step: 'stat', className: 'font-display text-stat text-ink', sample: '14–9' },
  { step: 'heading', className: 'font-display text-heading text-ink', sample: 'Your matchups' },
  { step: 'title', className: 'font-display text-title text-ink', sample: 'On the play, on the draw' },
  { step: 'lead', className: 'text-lead text-ink2', sample: 'One sentence under a page title.' },
  { step: 'body', className: 'text-body text-ink2', sample: 'Running text in a card or a finding.' },
  { step: 'caption', className: 'text-caption text-muted', sample: 'A subtitle, a table header, a note.' },
  { step: 'chip', className: 'text-chip font-semibold tracking-label text-muted', sample: 'A label' },
]

function TypeRamp() {
  return (
    <Section id="type" title="Type ramp">
      <ul className="space-y-4">
        {RAMP.map(({ step, className, sample }) => (
          <li key={step} className="grid gap-1 sm:grid-cols-[7rem_minmax(0,1fr)] sm:items-baseline">
            <span className="text-caption text-muted">{step}</span>
            <span className={`min-w-0 break-words ${className}`}>{sample}</span>
          </li>
        ))}
      </ul>
    </Section>
  )
}

const RADII: { name: string; className: string; use: string }[] = [
  { name: 'control', className: 'rounded-control', use: 'Inputs, nav items' },
  { name: 'block', className: 'rounded-block', use: 'A finding, a callout' },
  { name: 'card', className: 'rounded-card', use: 'Cards and tiles' },
  { name: 'hero', className: 'rounded-hero', use: "A page's lead panel" },
  { name: 'pill', className: 'rounded-pill', use: 'Buttons, chips' },
]

function RadiiAndElevation() {
  return (
    <Section id="radii" title="Radii and elevation">
      <ul className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        {RADII.map(({ name, className, use }) => (
          <li key={name}>
            <div aria-hidden className={`h-16 border border-edge-strong bg-surface2 ${className}`} />
            <div className="mt-1.5 text-caption text-ink">{name}</div>
            <div className="text-caption text-muted">{use}</div>
          </li>
        ))}
      </ul>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-card border border-dashed border-edge-strong p-5">
          <SectionLabel as="p">The plane</SectionLabel>
          <p className="mt-1 text-body text-ink2">The page itself. Nothing sits on it without a surface.</p>
        </div>
        <Card title="Elevation 1" subtitle="A card: surface 1, an edge, the lift">
          <Card elevation={2} title="Elevation 2">
            <p className="text-body text-ink2">A block nested in a card: surface 2, no edge, no shadow.</p>
            <div className="mt-3 rounded-control bg-surface3 px-3 py-2 text-caption text-ink">
              Surface 3: a control on a block
            </div>
          </Card>
        </Card>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------ primitives */

const VARIANTS: ButtonVariant[] = ['primary', 'secondary', 'quiet']
const SIZES: ButtonSize[] = ['md', 'sm']

function Buttons() {
  return (
    <Section id="buttons" title="Buttons">
      <Card>
        <div className="space-y-5">
          {VARIANTS.map((variant) => (
            <div key={variant} className="space-y-2">
              <SectionLabel>{variant}</SectionLabel>
              <div className="flex flex-wrap items-center gap-3">
                {SIZES.map((size) => (
                  <Button key={size} variant={variant} size={size}>
                    Size {size}
                  </Button>
                ))}
                <Button variant={variant} disabled>
                  Disabled
                </Button>
                <Button variant={variant} href="#buttons">
                  A link
                </Button>
                {SIZES.map((size) => (
                  <Button key={`icon-${size}`} variant={variant} size={size} iconOnly aria-label="Add a deck">
                    <Plus size={size === 'md' ? 18 : 16} aria-hidden />
                  </Button>
                ))}
                <Button variant={variant} size="sm">
                  <RefreshCw size={16} aria-hidden />
                  With an icon
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </Section>
  )
}

function Links() {
  return (
    <Section id="links" title="Links">
      <Card>
        <div className="space-y-2 text-body text-ink2">
          <p>
            A link inside the app: <TextLink href="/matches">All matches</TextLink>.
          </p>
          <p>
            A link that leaves it: <TextLink href="https://scryfall.com">Scryfall</TextLink>.
          </p>
          <p>
            A reference mark in running text, muted: the plan follows the article{' '}
            <TextLink href="https://scryfall.com" muted className="text-caption" aria-label="R1: Scryfall">
              [R1]
            </TextLink>
            .
          </p>
        </div>
      </Card>
    </Section>
  )
}

const CHIP_VARIANTS: ChipVariant[] = ['neutral', 'win', 'loss', 'warn', 'accent', 'seen']
const WEIGHTS: FindingWeight[] = ['decisive', 'flag', 'notice', 'note']

function Chips() {
  return (
    <Section id="chips" title="Chips">
      <Card>
        <div className="space-y-4">
          {(['md', 'sm'] as const).map((size) => (
            <div key={size} className="space-y-2">
              <SectionLabel>Size {size}</SectionLabel>
              <div className="flex flex-wrap items-center gap-2">
                {CHIP_VARIANTS.map((variant) => (
                  <Chip key={variant} variant={variant} size={size}>
                    {variant}
                  </Chip>
                ))}
                <Chip size={size} muted>
                  neutral, muted
                </Chip>
                <Chip size={size} emphasis>
                  emphasis
                </Chip>
              </div>
            </div>
          ))}
          <div className="space-y-2">
            <SectionLabel>Severity</SectionLabel>
            <div className="flex flex-wrap items-center gap-2">
              {WEIGHTS.map((weight) => (
                <Chip key={weight} size="sm" {...severityChip(weight)}>
                  {weight}
                </Chip>
              ))}
            </div>
          </div>
        </div>
      </Card>
    </Section>
  )
}

const LONG_SUBTITLE =
  'Share of the decks in the tier you pick, over the window you pick, counted once per list, with the archetypes too thin to name folded into one row at the bottom.'

function Cards({ art }: { art: ArtCard[] }) {
  const [range, setRange] = useState<'30' | '90'>('30')
  const card = art[0]
  return (
    <Section id="cards" title="Cards">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          title="Plain"
          subtitle="A subtitle under the title"
          action={
            <Segmented
              size="sm"
              label="Window"
              value={range}
              onChange={setRange}
              options={[
                { value: '30', label: '30 days' },
                { value: '90', label: '90 days' },
              ]}
            />
          }
        >
          <p className="text-body text-ink2">The one raised surface, with an action beside its title.</p>
        </Card>
        <Card title="Accent tone" subtitle="Written by you, 3 days ago" tone="accent">
          <p className="text-body text-ink2">
            For an authored artefact: a written narrative. The header still says who wrote it.
          </p>
        </Card>
        <Card
          title="With art"
          subtitle={card?.name ?? 'No card yet'}
          art={<CardArt grpId={card?.grpId ?? null} name={card?.name ?? null} fade="down" className="h-32" />}
        >
          <p className="text-body text-ink2">The art slot sits above the header, clipped by the radius.</p>
        </Card>
      </div>
      <SectionLabel>Narrow cards: the subtitle runs the card's width, under the title and the action</SectionLabel>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card
          title="Field share"
          subtitle={LONG_SUBTITLE}
          action={
            <Segmented
              size="sm"
              label="Window"
              value={range}
              onChange={setRange}
              options={[
                { value: '30', label: '30 days' },
                { value: '90', label: '90 days' },
              ]}
            />
          }
        >
          <p className="text-body text-ink2">With an action.</p>
        </Card>
        <Card title="Field share" subtitle={LONG_SUBTITLE}>
          <p className="text-body text-ink2">Without one.</p>
        </Card>
        <Card
          title="Notes"
          subtitle="What the last twenty matches say about this deck."
          action={<span className="text-caption text-muted">Written by you, 3 days ago, from 36 matches</span>}
        >
          <p className="text-body text-ink2">With an action wider than the space beside the title.</p>
        </Card>
        <Card title="Loading">
          {/* A sample: `data-sample` keeps the screenshot script from
              waiting on it as if the page were still loading. */}
          <div data-sample className="space-y-3">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-20 w-full" />
          </div>
        </Card>
      </div>
    </Section>
  )
}

function StatTiles() {
  return (
    <Section id="stat-tiles" title="Stat tiles">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile label="Match win rate" value="58%" detail="21–15 over 36 matches" />
        <StatTile label="On the play" value="62%" detail="31 games" />
        <StatTile label="Mulligans" value="0.4" />
        <StatTile label="Matches" value="5–4" detail={`too few for a rate, under 10${NBSP}matches`} muted />
      </div>
    </Section>
  )
}

function EmptyStates() {
  return (
    <Section id="empty" title="Empty state">
      <Card title="Matchups">
        <EmptyState
          title="No matches yet"
          message="Play a match in Arena with the watcher running and it appears here."
          action={<Button variant="secondary">Read the setup guide</Button>}
        />
      </Card>
      <EmptyState message="With a sentence only, and no title or action." />
      <SectionLabel>With a place's icon</SectionLabel>
      <EmptyState
        icon={placeById('matches').icon}
        title="No matches yet"
        message="A place with nothing to show carries its own icon, a title and one sentence."
      />
    </Section>
  )
}

const DECK_TILES = [
  {
    name: 'Azure Kites',
    figure: '61%',
    line: 'won 14 of 23',
    detail: `Standard, best of three · 4${NBSP}versions`,
    lastPlayed: 'last played Sep 12',
    chip: 'Newest',
  },
  { name: 'Ember Choir', figure: '4 of 7', line: 'matches won', detail: 'Standard', lastPlayed: 'played Sep 3 to 9' },
  { name: null, figure: null, line: 'no finished match yet', detail: null, lastPlayed: 'last played Aug 30' },
]

function DeckTiles({ art }: { art: ArtCard[] }) {
  return (
    <Section id="deck-tile" title="Deck tile">
      <p className="text-body text-ink2">
        Ten finished matches or more, a rate; five to nine, a rate drawn muted; one to four, a count; none, no figure. A deck with no name, muted.
      </p>
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4">
        {DECK_TILES.map((tile, index) => (
          <li key={tile.name ?? 'unnamed'} className="min-w-0">
            <DeckTile
              name={tile.name}
              href="/design"
              figure={tile.figure}
              line={tile.line}
              detail={tile.detail}
              lastPlayed={tile.lastPlayed}
              chip={tile.chip}
              art={art.length ? art[index % art.length] : null}
            />
          </li>
        ))}
      </ul>
    </Section>
  )
}

function Onboarding() {
  return (
    <Section id="onboarding" title="Onboarding steps">
      <Card>
        <OnboardingSteps
          steps={[
            { title: 'Open the lantern', state: 'done' },
            {
              title: 'Light the wick',
              state: 'next',
              detail: 'Only the step that is next says what to do. The disc, the word and the fill all agree.',
            },
            { title: 'Read by its light', state: 'later' },
          ]}
        />
      </Card>
    </Section>
  )
}

const FINDINGS: { weight: FindingWeight; where: string; title: string; body: string }[] = [
  {
    weight: 'decisive',
    where: 'Game 2, turn 5',
    title: 'The race turned on one block',
    body: 'You traded your only flyer for a ground creature, and the opponent was ahead on damage from then on.',
  },
  {
    weight: 'flag',
    where: 'Game 1, turn 1',
    title: 'Kept a one-land hand on the draw',
    body: 'A one-lander on the draw hits its second land by turn 2 a little over half the time.',
  },
  {
    weight: 'notice',
    where: 'Game 3',
    title: 'Mana spent below curve',
    body: 'You left three or more mana unspent on four of seven turns.',
  },
  {
    weight: 'note',
    where: 'Match',
    title: 'Your usual pace against this deck',
    body: 'Games against Ember Choir run about two turns longer than your average.',
  },
]

function Findings() {
  return (
    <Section id="findings" title="Findings">
      <Card title="Match report" subtitle="The four weights">
        <div className="space-y-3">
          {FINDINGS.map((finding) => (
            <Finding key={finding.weight} weight={finding.weight} where={finding.where} title={finding.title}>
              {finding.body}
            </Finding>
          ))}
        </div>
      </Card>
    </Section>
  )
}

function Callouts() {
  return (
    <Section id="callouts" title="Callouts">
      <Card>
        <div className="space-y-3">
          <Callout title="Verdict">
            Favoured on the play, even on the draw. Keep a two-lander only with a one-drop.
          </Callout>
          <Callout tone="warn" title="What this cannot say">
            Nine matches is too few to tell a real edge from a good week.
          </Callout>
          <Callout>A callout with no title: one thing said apart from the rest.</Callout>
        </div>
      </Card>
    </Section>
  )
}

function TextBlocks() {
  return (
    <Section id="text-block" title="Text block">
      <Card>
        <div className="space-y-3">
          <TextBlock>
            sensei-top guide --deck "a-sample-deck-name-with-no-spaces-long-enough-to-run-past-a-narrow-card"
            --import guide.json
          </TextBlock>
          <TextBlock scroll>
            {'A block long enough to scroll rather than grow the card: '.repeat(8)}
          </TextBlock>
        </div>
      </Card>
    </Section>
  )
}

function Disclosures() {
  return (
    <Section id="disclosure" title="Disclosure">
      <Card>
        <div className="space-y-4">
          <Disclosure summary="How this is measured">
            <p className="text-body text-ink2">
              Each game counts once. A match you conceded before game 1 ended counts as a loss.
            </p>
          </Disclosure>
          <Disclosure summary="Open from the start" defaultOpen>
            <p className="text-body text-ink2">Its content shows until the summary is pressed.</p>
          </Disclosure>
        </div>
      </Card>
    </Section>
  )
}

function Tooltips() {
  return (
    <Section id="tooltip" title="Tooltip">
      <Card>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Tooltip tip="Cards still in your hand on the last turn of a game you lost.">
              <SectionLabel as="span">Stranded</SectionLabel>
            </Tooltip>
            <Chip size="sm" {...severityChip('flag')}>
              Flag
            </Chip>
          </div>
          <div className="flex justify-end">
            <Tooltip align="end" tip="A trigger at the right of its container: the tip opens leftward.">
              <SectionLabel as="span">Right-aligned</SectionLabel>
            </Tooltip>
          </div>
          <p className="text-body text-ink2">
            Hover the label, or reach it with Tab: the tip opens, and Escape closes it. A trigger at the right of
            its container takes <code>align="end"</code>.
          </p>
        </div>
      </Card>
    </Section>
  )
}

function SegmentedControls() {
  const [md, setMd] = useState<'all' | 'bo1' | 'bo3'>('all')
  const [sm, setSm] = useState(2)
  return (
    <Section id="segmented" title="Segmented control">
      <Card>
        <div className="space-y-4">
          <div className="space-y-2">
            <SectionLabel>Size md</SectionLabel>
            <Segmented
              label="Format"
              value={md}
              onChange={setMd}
              options={[
                { value: 'all', label: 'All' },
                { value: 'bo1', label: 'Best of one' },
                { value: 'bo3', label: 'Best of three' },
              ]}
            />
          </div>
          <div className="space-y-2">
            <SectionLabel>Size sm</SectionLabel>
            <Segmented
              size="sm"
              label="Game"
              value={sm}
              onChange={setSm}
              options={[
                { value: 1, label: 'Game 1 · Win' },
                { value: 2, label: 'Game 2 · Loss' },
                { value: 3, label: 'Game 3 · Win' },
              ]}
            />
          </div>
        </div>
      </Card>
    </Section>
  )
}

/** One sample of a control, under its small label. */
function Sample({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 space-y-2">
      <SectionLabel>{label}</SectionLabel>
      {children}
    </div>
  )
}

function Fields() {
  const [name, setName] = useState('')
  const [folder, setFolder] = useState('/games/logs')
  const [missing, setMissing] = useState('/games/nowhere')
  const [disabled, setDisabled] = useState('/games/logs')
  const [key, setKey] = useState('')
  return (
    <Section id="fields" title="Fields">
      <Card>
        <div className="grid gap-6 sm:grid-cols-2">
          <Sample label="Empty">
            <Field
              label="Name on the table"
              value={name}
              onChange={setName}
              placeholder="The name your opponents see"
              hint="Matches are read for this name."
            />
          </Sample>
          <Sample label="Filled">
            <Field label="Folder" value={folder} onChange={setFolder} hint="Where the game writes its log." />
          </Sample>
          <Sample label="With an error">
            <Field
              label="Folder"
              value={missing}
              onChange={setMissing}
              error="No folder is there. Pick one that exists."
            />
          </Sample>
          <Sample label="Disabled">
            <Field
              label="Folder"
              value={disabled}
              onChange={setDisabled}
              disabled
              hint="Where the game writes its log."
            />
          </Sample>
          <Sample label="A password">
            <Field
              label="Key"
              type="password"
              value={key}
              onChange={setKey}
              placeholder="Paste a key"
              hint="Shown only while you type it."
            />
          </Sample>
          <Sample label="Read-only">
            <Field label="Folder" value="/games/logs" hint="Where the game writes its log." />
          </Sample>
          <Sample label="Read-only and not set">
            <Field label="Name on the table" value="" hint="Matches are read for this name." />
          </Sample>
        </div>
      </Card>
    </Section>
  )
}

const SOURCE_SAMPLE_OPTIONS = [
  { value: 'all', label: 'Every source' },
  { value: 'arena', label: 'Arena' },
  { value: 'mtgo', label: 'MTGO' },
]

function Selects() {
  const [body, setBody] = useState('all')
  const [caption, setCaption] = useState('arena')
  const [above, setAbove] = useState('mtgo')
  const [disabled, setDisabled] = useState('arena')
  return (
    <Section id="selects" title="Selects">
      <Card>
        <div className="grid gap-6 sm:grid-cols-2">
          <Sample label="Beside, body size">
            <Select label="Source" value={body} onChange={setBody} options={SOURCE_SAMPLE_OPTIONS} />
          </Sample>
          <Sample label="Beside, caption size">
            <Select
              label="Source"
              size="caption"
              value={caption}
              onChange={setCaption}
              options={SOURCE_SAMPLE_OPTIONS}
            />
          </Sample>
          <Sample label="Above">
            <Select
              label="Source"
              placement="above"
              value={above}
              onChange={setAbove}
              options={SOURCE_SAMPLE_OPTIONS}
            />
          </Sample>
          <Sample label="Disabled">
            <Select
              label="Source"
              value={disabled}
              onChange={setDisabled}
              disabled
              options={SOURCE_SAMPLE_OPTIONS}
            />
          </Sample>
          <Sample label="Read-only">
            <Select label="Source" value="arena" options={SOURCE_SAMPLE_OPTIONS} />
          </Sample>
        </div>
      </Card>
    </Section>
  )
}

const BACK_UP_DAILY = 'A copy of the match history is made once a day, and the oldest goes.'

function Switches() {
  const [off, setOff] = useState(false)
  const [on, setOn] = useState(true)
  const [described, setDescribed] = useState(true)
  const [disabled, setDisabled] = useState(false)
  return (
    <Section id="switches" title="Switches">
      <Card>
        <div className="grid gap-6 sm:grid-cols-2">
          <Sample label="Off">
            <Switch label="Start with the computer" checked={off} onChange={setOff} />
          </Sample>
          <Sample label="On">
            <Switch label="Start with the computer" checked={on} onChange={setOn} />
          </Sample>
          <Sample label="With a description">
            <Switch
              label="Back up every day"
              description={BACK_UP_DAILY}
              checked={described}
              onChange={setDescribed}
            />
          </Sample>
          <Sample label="Disabled">
            <Switch
              label="Back up every day"
              description={BACK_UP_DAILY}
              checked={disabled}
              onChange={setDisabled}
              disabled
            />
          </Sample>
          <Sample label="Read-only">
            <div className="space-y-3">
              <Switch label="Start with the computer" checked />
              <Switch label="Start with the computer" checked={false} />
            </div>
          </Sample>
        </div>
      </Card>
    </Section>
  )
}

function DialogSample() {
  const [open, setOpen] = useState(false)
  const [deleted, setDeleted] = useState(false)
  return (
    <Section id="dialog" title="Dialog">
      <Card>
        <div className="space-y-3">
          <Button
            aria-haspopup="dialog"
            onClick={() => {
              setDeleted(false)
              setOpen(true)
            }}
          >
            Delete the sample
          </Button>
          {deleted && <p className="text-body text-ink2">The sample is deleted.</p>}
        </div>
        <Dialog
          open={open}
          onClose={() => setOpen(false)}
          title="Delete the sample?"
          actions={
            <>
              <Button variant="primary" onClick={() => setOpen(false)}>
                Keep it
              </Button>
              <Button
                onClick={() => {
                  setDeleted(true)
                  setOpen(false)
                }}
              >
                Delete the sample
              </Button>
            </>
          }
        >
          <p>It cannot be brought back. Nothing else on this page changes.</p>
        </Dialog>
      </Card>
    </Section>
  )
}

function Meters() {
  const fills = [
    { color: 's1', fraction: 0.62, label: 'Series 1' },
    { color: 's2', fraction: 0.41, label: 'Series 2' },
    { color: 's3', fraction: 0.77, label: 'Series 3' },
    { color: 'muted', fraction: 0.3, label: 'Muted' },
    { color: 'accent', fraction: 0.55, label: 'Accent' },
  ] as const
  return (
    <Section id="meters" title="Meters">
      <Card>
        <ul className="space-y-3">
          {fills.map(({ color, fraction, label }) => (
            <li key={color} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3rem] items-center gap-3">
              <span className="text-caption text-ink2">{label}</span>
              <Meter fraction={fraction} color={color} />
              <span className="text-right text-caption text-muted">{formatPercent(fraction)}</span>
            </li>
          ))}
          <li className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3rem] items-center gap-3">
            <span className="text-caption text-ink2">Indeterminate</span>
            <Meter fraction={0} color="accent" label="Indeterminate sample" indeterminate />
            <span className="text-right text-caption text-muted">—</span>
          </li>
          <li className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3rem] items-center gap-3">
            <span className="text-caption text-ink2">Two-sided</span>
            <TwoSidedMeter self={14} opp={9} />
            <span className="text-right text-caption text-muted">14–9</span>
          </li>
          <li className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3rem] items-center gap-3">
            <span className="text-caption text-ink2">Interval</span>
            <IntervalBar rate={0.56} ci={[0.41, 0.7]} colorClass="s1" />
            <span className="text-right text-caption text-muted">56%</span>
          </li>
        </ul>
      </Card>
    </Section>
  )
}

function BarsSection() {
  return (
    <Section id="bars" title="Bars">
      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="Colour bars" subtitle="Two colours ringed">
          <ColorBars
            colors={[
              { color: 'U', count: 9 },
              { color: 'R', count: 7 },
              { color: 'G', count: 5 },
              { color: 'W', count: 3 },
              { color: 'B', count: 1 },
            ]}
            highlight={new Set(['U', 'R'])}
          />
        </Card>
        <Card title="Curve bars" subtitle="Mana value 1 to 7+">
          <CurveBars
            curve={[
              [1, 3],
              [2, 7],
              [3, 5],
              [4, 4],
              [5, 2],
              [7, 1],
            ]}
          />
        </Card>
      </div>
    </Section>
  )
}

function Table() {
  return (
    <Section id="table" title="Data table">
      <Card>
        <DataTable
          columns={['Opponent deck', 'Matches', 'Win rate']}
          rows={[
            ['Ember Choir', '12', '58.3%'],
            ['Moss Lantern', '9', '44.4%'],
            ['Glass Orchard', '6', '66.7%'],
          ]}
        />
      </Card>
    </Section>
  )
}

/* ----------------------------------------------------------------- charts */

/** Every chart's numbers, one button away under it. */
function Numbers({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-3 space-y-3">
      <Button variant="quiet" size="sm" aria-expanded={open} onClick={() => setOpen((was) => !was)}>
        {open ? 'Hide the numbers' : 'Show the numbers'}
      </Button>
      {open && children}
    </div>
  )
}

const LIFE = [
  { turn: 1, you: 20, opponent: 20 },
  { turn: 2, you: 20, opponent: 18 },
  { turn: 3, you: 17, opponent: 18 },
  { turn: 4, you: 17, opponent: 14 },
  { turn: 5, you: 13, opponent: 11 },
  { turn: 6, you: 13, opponent: 6 },
  { turn: 7, you: 10, opponent: 0 },
]

function LineChartSection() {
  const t = useTokens()
  const dot = (color: string) => ({ r: 3, strokeWidth: 2, stroke: t.surface, fill: color })
  return (
    <Section id="line-chart" title="Line chart">
      <Card title="Life by turn" subtitle="Lines 2 px, dots ringed in the card's surface">
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={LIFE} margin={{ top: 8, left: 0, right: 12 }}>
            <CartesianGrid {...gridProps(t)} />
            <XAxis dataKey="turn" {...axisProps(t)} />
            <YAxis width={32} domain={[0, 'auto']} allowDecimals={false} {...axisProps(t)} />
            <ChartHover
              content={({ active, payload, label }) => (
                <ChartTooltip active={active} payload={payload} label={label} labelPrefix="Turn " />
              )}
            />
            <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: t.muted, paddingTop: 4 }} />
            <Line
              dataKey="you"
              name="You"
              stroke={t.self}
              strokeWidth={2}
              dot={dot(t.self)}
              activeDot={{ r: 4, strokeWidth: 2, stroke: t.surface }}
            />
            <Line
              dataKey="opponent"
              name="Opponent"
              stroke={t.opponent}
              strokeWidth={2}
              dot={dot(t.opponent)}
              activeDot={{ r: 4, strokeWidth: 2, stroke: t.surface }}
            />
          </LineChart>
        </ResponsiveContainer>
        <Numbers>
          <DataTable
            columns={['Turn', 'You', 'Opponent']}
            rows={LIFE.map((row) => [String(row.turn), String(row.you), String(row.opponent)])}
          />
        </Numbers>
      </Card>
    </Section>
  )
}

const WIN_RATE = [
  { deck: 'Ember Choir', rate: 58.3 },
  { deck: 'Moss Lantern', rate: 44.4 },
  { deck: 'Glass Orchard', rate: 66.7 },
]

function BarChartSection() {
  const t = useTokens()
  const format = (value: number) => formatPercent(value / 100)
  return (
    <Section id="bar-chart" title="Bar chart">
      <Card title="Win rate by opponent deck" subtitle="Radius 4 on the value end">
        <ResponsiveContainer width="100%" height={60 + WIN_RATE.length * 44}>
          <BarChart data={WIN_RATE} layout="vertical" margin={{ left: 0, right: 56 }}>
            <CartesianGrid {...gridProps(t)} horizontal={false} vertical />
            <XAxis type="number" domain={[0, 100]} unit="%" {...axisProps(t)} />
            <YAxis type="category" dataKey="deck" width={104} {...axisProps(t)} />
            <ChartHover
              cursor={{ fill: t.grid, fillOpacity: 0.3 }}
              content={({ active, payload, label }) => (
                <ChartTooltip active={active} payload={payload} label={label} format={format} />
              )}
            />
            <Bar dataKey="rate" name="Win rate" fill={t.self} radius={[0, 4, 4, 0]} barSize={18}>
              <LabelList dataKey="rate" position="right" formatter={percentLabel} fill={t.ink} fontSize={12} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <Numbers>
          <DataTable
            columns={['Opponent deck', 'Win rate']}
            rows={WIN_RATE.map((row) => [row.deck, format(row.rate)])}
          />
        </Numbers>
      </Card>
    </Section>
  )
}

/* ------------------------------------------------------- identity, brand */

function Pips() {
  const identities = ['W', 'U', 'B', 'R', 'G', 'UR', 'WBG', 'WUBRG']
  const costs = ['{1}{U}', '{2}{R}{R}', '{1}{U/R}{U/R}', '{2/W}', '{3}{U/P}', '{X}{C}']
  return (
    <Section id="pips" title="Mana pips">
      <Card>
        <div className="space-y-4">
          {(['md', 'lg'] as const).map((size) => (
            <div key={size} className="space-y-2">
              <SectionLabel>Size {size}</SectionLabel>
              <div className="flex flex-wrap items-center gap-4">
                {identities.map((colors) => (
                  <ManaPips key={colors} colors={colors} size={size} />
                ))}
              </div>
            </div>
          ))}
          <div className="space-y-2">
            <SectionLabel>Cost, size sm</SectionLabel>
            <div className="flex flex-wrap items-center gap-4">
              {costs.map((cost) => (
                <ManaCost key={cost} cost={cost} />
              ))}
            </div>
          </div>
        </div>
      </Card>
    </Section>
  )
}

function Brand() {
  return (
    <Section id="brand" title="Glyph and wordmark">
      <Card>
        <div className="flex flex-wrap items-end gap-8">
          {[16, 24, 64].map((size) => (
            <div key={size} className="flex flex-col items-center gap-2">
              <BrandGlyph size={size} className="text-accent" />
              <span className="text-caption text-muted">{size} px</span>
            </div>
          ))}
          <div className="flex flex-col items-start gap-3">
            <Wordmark />
            <Wordmark size="sm" />
            <Wordmark glyphOnly />
          </div>
        </div>
      </Card>
    </Section>
  )
}

/* -------------------------------------------------------------- card tile */

/** The tile's states with invented captions: a turn, a reduced turn, a land
 *  (no caption, the space kept), odds with `Now`, and a card with no picture
 *  on file, whose text is unknown. The pictures are the page's art cards,
 *  in turn; with none recorded yet every tile is its name in the card's
 *  shape. */
function CardTiles({ art }: { art: ArtCard[] }) {
  const pick = (index: number): ArtCard | undefined => (art.length ? art[index % art.length] : undefined)
  const tile = (index: number, fallback: string) => {
    const card = pick(index)
    return { grpId: card?.grpId ?? null, name: card?.name ?? fallback }
  }
  return (
    <Section id="card-tile" title="Card tile">
      <p className="text-body text-ink2">
        A whole card with what is known about it written under the picture. Nothing is drawn on the card.
      </p>
      <div className="flex flex-wrap items-start gap-2">
        <CardTile {...tile(0, 'Azure Kites')} width={110}>
          <div>Turn 3</div>
        </CardTile>
        <CardTile {...tile(1, 'Ember Choir')} width={110}>
          <div>Turn 2, reduced</div>
        </CardTile>
        <CardTile {...tile(2, 'Moss Lantern')} width={110} />
        <CardTile {...tile(0, 'Azure Kites')} width={110}>
          <div className="flex items-center gap-1.5">
            <span>17%</span>
            <Chip size="sm" variant="warn">
              Now
            </Chip>
          </div>
        </CardTile>
        <CardTile grpId={null} name="Tidal Lantern" width={110}>
          <div>No turn</div>
          <div className="text-muted">Text unknown</div>
        </CardTile>
      </div>
    </Section>
  )
}

/* --------------------------------------------------------------- card art */

const TILES = [
  { title: 'Azure Kites', detail: '14–9 · 60.9%' },
  { title: 'Ember Choir', detail: '6–7 · 46.2%' },
  { title: 'Moss Lantern', detail: '3–1 · 75.0%' },
]

function ArtShapes({ art }: { art: ArtCard[] }) {
  const pick = (index: number): ArtCard | undefined => (art.length ? art[index % art.length] : undefined)
  const hero = pick(0)
  return (
    <Section id="card-art" title="Card art">
      {art.length === 0 && (
        <p className="text-body text-ink2">No card art yet. It appears here once this copy has recorded a match.</p>
      )}

      <SectionLabel>Hero</SectionLabel>
      <div className="relative overflow-hidden rounded-hero border border-edge bg-surface shadow-lift [--art-surface:var(--surface-1)]">
        <CardArt
          grpId={hero?.grpId ?? null}
          name={hero?.name ?? null}
          fade="down"
          className="h-[170px] sm:hidden"
        />
        <CardArt
          grpId={hero?.grpId ?? null}
          name={hero?.name ?? null}
          fade="left"
          className="absolute inset-y-0 right-0 hidden w-3/5 sm:block"
        />
        <div className="relative -mt-3.5 flex flex-col justify-end gap-2 px-5 pb-6 sm:mt-0 sm:h-[304px] sm:max-w-[42%] sm:px-8 sm:pb-8">
          <SectionLabel as="p">Your deck</SectionLabel>
          <p className="font-display text-hero text-ink">Azure Kites</p>
          <p className="text-lead text-ink2">60.9% over 23 matches this format.</p>
        </div>
      </div>

      <SectionLabel>Tile</SectionLabel>
      <ul className="grid gap-4 sm:grid-cols-3">
        {TILES.map((tile, index) => {
          const card = pick(index)
          return (
            <li
              key={tile.title}
              className="overflow-hidden rounded-card border border-edge bg-surface shadow-lift [--art-surface:var(--surface-1)]"
            >
              <CardArt grpId={card?.grpId ?? null} name={card?.name ?? null} fade="down" className="h-[124px]" />
              <div className="relative -mt-3.5 px-4 pb-4">
                <p className="font-display text-title text-ink">{tile.title}</p>
                <p className="mt-0.5 text-caption text-muted">{tile.detail}</p>
              </div>
            </li>
          )
        })}
      </ul>

    </Section>
  )
}
