import type { DeckGuideOut, PersonalRateOut } from '../../api'
import { archetypeName } from '../../lib/decks'
import { fieldCaption } from '../../lib/guide'
import { formatCount } from '../../lib/time'
import { placeById } from '../../shell/places'
import { percent } from '../../theme'
import { Card, DataTable, EmptyState, StatTile } from '../ui'

/** A no-break space: a count and the word after it never part. */
const NBSP = '\u00a0'

/** The tournament field the deck plays into, since the format reset when
 *  one was found: three tiles (the deck's own archetype in the field, the
 *  most played archetype, and with a reset how many of those shown changed
 *  at it), then every archetype's share, most played first, in the
 *  server's order. The table fits a 360 px screen: the name takes what the
 *  three number columns leave and breaks inside a word if it must. */
export function FieldCard({ guide }: { guide: DeckGuideOut }) {
  const { field } = guide
  const reset = guide.provenance.reset != null
  const personalByArchetype = new Map<string, PersonalRateOut>(field.personal_rates.map((r) => [r.archetype, r]))

  const subtitle = reset
    ? "Each archetype's share of the tournament lists since the format reset, most played first."
    : "Each archetype's share of the tournament lists, most played first."

  if (field.shares.length === 0) {
    return (
      <Card title="The field" subtitle={subtitle}>
        <EmptyState
          icon={placeById('field').icon}
          title="No tournament results yet"
          message="This page shows what is being played in tournaments and your own record against each deck. It fills in once tournament results are downloaded, which this version does only from the command line."
        />
      </Card>
    )
  }

  const own = field.own_performance
  const ownDetail = own
    ? `${formatCount(own.wins)}–${formatCount(own.losses)} over ${
        own.decks === 1 ? `1${NBSP}list` : `${formatCount(own.decks)}${NBSP}lists`
      }`
    : 'not found in the field'
  const top = field.shares[0]
  const changed = field.shares.filter((s) => {
    const verdict = field.changes[s.archetype]?.verdict
    return verdict === 'changed' || verdict === 'gone'
  }).length
  const shown =
    field.shares.length === 1
      ? 'of the one archetype shown'
      : `of the ${formatCount(field.shares.length)}${NBSP}archetypes shown`

  const withBefore = field.shares.some((s) => s.share_before_reset != null)
  const columns = withBefore ? ['Archetype', 'Share', 'Before', 'You'] : ['Archetype', 'Share', 'You']

  return (
    <Card title="The field" subtitle={subtitle}>
      <div className={`grid gap-4 ${reset ? 'md:grid-cols-3' : 'md:grid-cols-2'}`}>
        <StatTile label="Your archetype" value={own ? percent(own.win_rate) : '—'} detail={ownDetail} />
        <StatTile label="Most played" value={percent(top.share)} detail={archetypeName(top.archetype)} />
        {reset && <StatTile label="Changed at the reset" value={formatCount(changed)} detail={shown} />}
      </div>
      <div className="mt-5">
        <DataTable
          columns={columns}
          rows={field.shares.map((s) => {
            const personal = personalByArchetype.get(s.archetype)
            const voided = personal != null && !personal.carryable
            const name = (
              // `wrap-anywhere`, not `break-words`: in a table only
              // `overflow-wrap: anywhere` lets a long word shrink the column.
              <div key="archetype" className="min-w-0 wrap-anywhere">
                <div className="text-body text-ink">{archetypeName(s.archetype)}</div>
                <div className="text-caption text-muted">{fieldCaption(s, field.changes[s.archetype])}</div>
                {voided && <div className="text-caption text-muted">Your record does not carry over.</div>}
              </div>
            )
            const you = personal ? (
              <span key="you" className={`whitespace-nowrap ${voided ? 'text-muted' : ''}`}>
                {formatCount(personal.wins)}–{formatCount(personal.losses)}
              </span>
            ) : (
              '—'
            )
            const share = (
              <span key="share" className="whitespace-nowrap">
                {percent(s.share)}
              </span>
            )
            const before = (
              <span key="before" className="whitespace-nowrap">
                {percent(s.share_before_reset)}
              </span>
            )
            return withBefore ? [name, share, before, you] : [name, share, you]
          })}
        />
      </div>
    </Card>
  )
}
