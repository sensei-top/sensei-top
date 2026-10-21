import { useTranslation } from 'react-i18next'
import type { DraftPayload, SharedDraft } from '../../bridge'
import type { TFunction } from '../../i18n'
import { formatList } from '../../lib/format'
import { ago, useNow } from '../../lib/time'
import { Card, Disclosure, SectionLabel } from '../ui'

/** What is never sent, a line each, as a short list: drawn in Settings'
 *  section "Draft data" and over a draft's payload. */
export function NeverSent() {
  const { t } = useTranslation()
  const lines = [
    t('prompts.sharing.neverSent.identity'),
    t('prompts.sharing.neverSent.opponent'),
    t('prompts.sharing.neverSent.pickTime'),
    t('prompts.sharing.neverSent.log'),
  ]
  return (
    <ul className="list-disc space-y-1 pl-5 text-body text-ink2 marker:text-muted">
      {lines.map((line) => (
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
  const { t } = useTranslation()
  const now = useNow()
  const when = shared.state === 'shared' ? ago(shared.at, now) : null
  const status = !on
    ? t('prompts.sharing.payload.statusOff')
    : shared.state === 'shared'
      ? when && t('prompts.sharing.payload.statusSent', { when })
      : shared.state === 'waiting'
        ? t('prompts.sharing.payload.statusWaiting')
        : null

  return (
    <div className="max-w-3xl space-y-6">
      <div className="space-y-2">
        <h2 className="font-display text-heading text-ink">{t('prompts.sharing.payload.heading')}</h2>
        {status && <p className="text-lead text-ink2">{status}</p>}
        <p className="text-caption text-muted">{t('prompts.sharing.payload.numbers')}</p>
      </div>
      <Card title={t('prompts.sharing.payload.neverSent')}>
        <NeverSent />
      </Card>
      {payload.about.length > 0 && (
        <Card title={t('prompts.sharing.payload.about')}>
          <Facts facts={payload.about} />
        </Card>
      )}
      {payload.draft.length > 0 && (
        <Card title={t('prompts.sharing.payload.draft')}>
          <Facts facts={payload.draft} />
        </Card>
      )}
      {payload.picks.length > 0 && (
        <Card title={t('prompts.sharing.payload.picks')}>
          <div className="space-y-3">
            {packsOf(payload.picks).map(([pack, picks]) => (
              <Disclosure key={pack} summary={t('prompts.sharing.payload.pack', { pack })}>
                <ul className="space-y-1 text-body text-ink2">
                  {picks.map((pick) => (
                    <li key={pick.pick}>{pickLine(pick, t)}</li>
                  ))}
                </ul>
              </Disclosure>
            ))}
          </div>
        </Card>
      )}
      <Card title={t('prompts.sharing.payload.deck')}>
        {payload.deck ? (
          <div className="space-y-4">
            <CardNames label={t('prompts.sharing.payload.mainDeck')} names={payload.deck.main} />
            <CardNames label={t('prompts.sharing.payload.sideboard')} names={payload.deck.sideboard} />
          </div>
        ) : (
          <p className="text-body text-ink2">{t('prompts.sharing.payload.noDeck')}</p>
        )}
      </Card>
      {(payload.games.length > 0 || payload.record !== null) && (
        <Card title={t('prompts.sharing.payload.games')}>
          <div className="space-y-3">
            {payload.games.length > 0 && (
              <ul className="space-y-1 text-body text-ink2">
                {payload.games.map((game, i) => (
                  <li key={i}>{gameLine(game, t)}</li>
                ))}
              </ul>
            )}
            {payload.record !== null && <p className="text-body text-ink">{t('prompts.sharing.payload.record', { record: payload.record })}</p>}
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

function pickLine(pick: PickRow, t: TFunction): string {
  const from = t('prompts.sharing.payload.cards', { count: pick.from.length })
  return pick.taken === null
    ? t('prompts.sharing.payload.pickUnknown', { pick: pick.pick, from })
    : t('prompts.sharing.payload.pickTook', { pick: pick.pick, taken: pick.taken, from })
}

/** A game's line: its result, then the seat, the length and the
 *  opponent's colours, each left out when it is not known. */
function gameLine(game: Game, t: TFunction): string {
  const parts = [game.result]
  if (game.onThePlay !== null) {
    parts.push(game.onThePlay ? t('prompts.sharing.payload.onThePlay') : t('prompts.sharing.payload.onTheDraw'))
  }
  if (game.turns !== null) parts.push(t('prompts.sharing.payload.turns', { count: game.turns }))
  if (game.against !== null) parts.push(t('prompts.sharing.payload.against', { colours: game.against }))
  return formatList(parts, { type: 'unit' })
}
