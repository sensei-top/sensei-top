import type { DraftPayload, SharedDraft } from '../../bridge'
import { ago, useNow } from '../../lib/time'
import { Card, Disclosure, SectionLabel } from '../ui'

const NEVER_SENT = [
  'Your Arena name or id.',
  "An opponent's name or id.",
  'How long you took over a pick.',
  'The log itself, or anything from Magic Online.',
]

/** What is never sent, a line each, as a short list: drawn in Settings'
 *  section "Draft data" and over a draft's payload. */
export function NeverSent() {
  return (
    <ul className="list-disc space-y-1 pl-5 text-body text-ink2 marker:text-muted">
      {NEVER_SENT.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  )
}

type PickRow = DraftPayload['picks'][number]
type Game = DraftPayload['games'][number]

/** "What is sent": one draft's payload in words, as the viewer reads it
 *  before and after sharing it. Its title and, by `on` and `shared`, what
 *  sharing did or would do with it: off, that it would be sent; on, that
 *  it was sent and when, or that it waits for the draft's games, and
 *  nothing for a draft not shared or removed. Then that cards are sent as
 *  numbers, what is never sent, and a card for each part: the app, the
 *  draft, the picks behind a disclosure per pack, the deck and the games.
 *  It draws what it is handed and asks for nothing: a list that is empty
 *  draws no card, and a part of a game that is not known is left out of
 *  its line. */
export function PayloadView({ payload, on, shared }: { payload: DraftPayload; on: boolean; shared: SharedDraft }) {
  const now = useNow()
  const when = shared.state === 'shared' ? ago(shared.at, now) : null
  const status = !on
    ? 'Sharing is off, so this was not sent. It is what would be.'
    : shared.state === 'shared'
      ? when && `This was sent ${when}.`
      : shared.state === 'waiting'
        ? "This is sent once the draft's games are over."
        : null

  return (
    <div className="max-w-3xl space-y-6">
      <div className="space-y-2">
        <h2 className="font-display text-heading text-ink">What this draft sends</h2>
        {status && <p className="text-lead text-ink2">{status}</p>}
        <p className="text-caption text-muted">Cards are sent as Arena's numbers. They are shown here by name.</p>
      </div>
      <Card title="Never sent">
        <NeverSent />
      </Card>
      {payload.about.length > 0 && (
        <Card title="About the app">
          <Facts facts={payload.about} />
        </Card>
      )}
      {payload.draft.length > 0 && (
        <Card title="The draft">
          <Facts facts={payload.draft} />
        </Card>
      )}
      {payload.picks.length > 0 && (
        <Card title="The picks">
          <div className="space-y-3">
            {packsOf(payload.picks).map(([pack, picks]) => (
              <Disclosure key={pack} summary={`Pack ${pack}`}>
                <ul className="space-y-1 text-body text-ink2">
                  {picks.map((pick) => (
                    <li key={pick.pick}>{pickLine(pick)}</li>
                  ))}
                </ul>
              </Disclosure>
            ))}
          </div>
        </Card>
      )}
      <Card title="The deck">
        {payload.deck ? (
          <div className="space-y-4">
            <CardNames label="Main deck" names={payload.deck.main} />
            <CardNames label="Sideboard" names={payload.deck.sideboard} />
          </div>
        ) : (
          <p className="text-body text-ink2">No deck was read from the log.</p>
        )}
      </Card>
      {(payload.games.length > 0 || payload.record !== null) && (
        <Card title="The games">
          <div className="space-y-3">
            {payload.games.length > 0 && (
              <ul className="space-y-1 text-body text-ink2">
                {payload.games.map((game, i) => (
                  <li key={i}>{gameLine(game)}</li>
                ))}
              </ul>
            )}
            {payload.record !== null && <p className="text-body text-ink">Record: {payload.record}</p>}
          </div>
        </Card>
      )}
    </div>
  )
}

/** Labelled values, a label and its value to a row. */
function Facts({ facts }: { facts: DraftPayload['about'] }) {
  return (
    <dl className="space-y-1.5">
      {facts.map(({ label, value }) => (
        <div key={label} className="flex flex-wrap items-baseline justify-between gap-x-3">
          <dt className="text-caption text-muted">{label}</dt>
          <dd className="min-w-0 break-words text-body text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** A list of card names under its label, a card to a line in the order
 *  it first appears, its copies before its name when there is more than
 *  one, as the recommended deck writes them; no list when there are none. */
function CardNames({ label, names }: { label: string; names: string[] }) {
  if (names.length === 0) return null
  return (
    <div className="space-y-2">
      <SectionLabel>{label}</SectionLabel>
      <ul className="gap-x-6 text-body text-ink2 sm:columns-2">
        {copiesOf(names).map(([name, copies]) => (
          <li key={name} className="break-inside-avoid">
            {copies > 1 ? `${copies} ${name}` : name}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Each name once, in the order it first appears, with how many times the
 *  list holds it. */
function copiesOf(names: string[]): [string, number][] {
  const copies = new Map<string, number>()
  for (const name of names) copies.set(name, (copies.get(name) ?? 0) + 1)
  return [...copies.entries()]
}

/** The picks grouped by pack, the packs in order and each pack's picks in
 *  order. */
function packsOf(picks: PickRow[]): [number, PickRow[]][] {
  const packs = new Map<number, PickRow[]>()
  for (const pick of picks) {
    const list = packs.get(pick.pack)
    if (list) list.push(pick)
    else packs.set(pick.pack, [pick])
  }
  return [...packs.entries()]
    .sort(([a], [b]) => a - b)
    .map(([pack, list]): [number, PickRow[]] => [pack, [...list].sort((a, b) => a.pick - b.pick)])
}

function pickLine(pick: PickRow): string {
  const count = pick.from.length
  const from = count === 1 ? '1 card' : `${count} cards`
  return pick.taken === null
    ? `Pick ${pick.pick}: the card taken is not known, from ${from}`
    : `Pick ${pick.pick}: took ${pick.taken} from ${from}`
}

/** A game's line: its result, then the seat, the length and the
 *  opponent's colours, each left out when it is not known. */
function gameLine(game: Game): string {
  const parts = [game.result]
  if (game.onThePlay !== null) parts.push(game.onThePlay ? 'on the play' : 'on the draw')
  if (game.turns !== null) parts.push(game.turns === 1 ? '1 turn' : `${game.turns} turns`)
  if (game.against !== null) parts.push(`against ${game.against}`)
  return parts.join(', ')
}
