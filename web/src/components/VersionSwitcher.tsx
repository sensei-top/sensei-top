import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'
import type { Deck } from '../api'
import { versionLabel } from '../lib/deckOverview'
import { Select } from './ui'

/** Which of a deck's versions a page reads, held in the address as
 *  `?version=`: first every version (no parameter), then each version in
 *  the order given, newest first. A change replaces the history entry and
 *  keeps the scroll, as `useFilters` does, so Back leaves the page instead
 *  of walking through versions. Styled as Matches' deck filter, 44 px high;
 *  on a narrow screen the select shrinks and cuts off the option it shows
 *  rather than pushing the page sideways. The caller draws it only for a
 *  deck with more than one version. */
export function VersionSwitcher({
  versions,
  value,
  now,
}: {
  versions: Deck[]
  value: string | null
  now: number
}) {
  const { t } = useTranslation()
  const [, setParams] = useSearchParams()
  const choose = (version: string) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        if (version) next.set('version', version)
        else next.delete('version')
        return next
      },
      { replace: true, preventScrollReset: true },
    )
  return (
    <Select
      label={t('common.filters.version')}
      size="caption"
      value={value ?? ''}
      onChange={choose}
      options={versions.map((version, index) => ({ value: version.deck_id, label: versionLabel(version, now, t, index === 0) }))}
    >
      <option value="">{t('common.filters.everyVersion')}</option>
    </Select>
  )
}
