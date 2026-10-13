import type { DateOrder, DeepPartial, Saved, ShellSettings } from '../../bridge'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from '../../i18n'
import { failureOf, settle, useRestart, useTextSave } from '../../lib/settings'
import { Card, Field } from '../ui'
import { FolderField, PressButton, RestartNote, SaveButton, SavingSelect } from './SaveButton'

// The games' own names, the same in every language.
const ARENA = 'Arena'
const MAGIC_ONLINE = 'Magic Online'

type Sources = ShellSettings['sources']
type SaveSources = (change: DeepPartial<Sources>) => Promise<Saved>

/** What the app reads: the two games' logs, in a card each, then the
 *  folder where the matches are kept. Only a shell knows any of it, so with
 *  no shell the page does not draw this section at all. With a shell and no
 *  `save`, every value is text and nothing can be changed. */
export function SourcesSection({
  sources,
  save,
  pickFolder,
  showDataFolder,
}: {
  sources: Sources
  save?: SaveSources
  pickFolder?: () => Promise<string | null>
  showDataFolder?: () => Promise<Saved>
}) {
  return (
    <div className="max-w-3xl space-y-6">
      <ArenaCard sources={sources} save={save} />
      <MagicOnlineCard sources={sources} save={save} pickFolder={pickFolder} />
      <DataFolderCard dataDir={sources.dataDir} showDataFolder={showDataFolder} />
    </div>
  )
}

/** The folder where the matches are kept: always text, since moving it is not
 *  something the page does, and "Open folder" when the shell can show it. */
function DataFolderCard({ dataDir, showDataFolder }: { dataDir: string; showDataFolder?: () => Promise<Saved> }) {
  const { t } = useTranslation()
  const [failure, setFailure] = useState<string | null>(null)
  const open = async (): Promise<boolean> => {
    setFailure(null)
    const sentence = failureOf(await settle(showDataFolder?.() ?? Promise.resolve({ ok: true } as const), t), t)
    setFailure(sentence)
    return sentence === null
  }
  return (
    <Card>
      <div className="space-y-3">
        <Field
          label={t('settings.sources.dataFolderLabel')}
          value={dataDir}
          hint={t('settings.sources.dataFolderHint')}
        />
        {showDataFolder && (
          <PressButton
            variant="quiet"
            label={t('settings.sources.openFolder')}
            workingLabel={t('common.opening')}
            doneLabel={null}
            onPress={open}
          />
        )}
        {failure && <p className="break-words text-caption text-loss">{failure}</p>}
      </div>
    </Card>
  )
}

function arenaHint({ path, found }: Sources['arenaLog'], t: TFunction): string {
  if (path === null) return t('settings.sources.arenaNotFound')
  return found ? t('settings.sources.arenaFound') : t('settings.sources.arenaDefault')
}

function ArenaCard({ sources, save }: { sources: Sources; save?: SaveSources }) {
  const { t } = useTranslation()
  const dateOrderOptions: { value: DateOrder; label: string }[] = [
    { value: 'auto', label: t('settings.sources.dateOrder.auto') },
    { value: 'mdy', label: t('settings.sources.dateOrder.mdy') },
    { value: 'dmy', label: t('settings.sources.dateOrder.dmy') },
  ]
  const { restart, watch } = useRestart()
  const text = useTextSave({ path: sources.arenaLog.path }, save && ((change) => watch(save({ arenaLog: change }))))
  return (
    <Card title={ARENA}>
      <div className="space-y-5">
        <Field
          label={t('settings.sources.logFile')}
          value={save ? text.typed.path : (sources.arenaLog.path ?? '')}
          onChange={save && ((value) => text.type('path', value))}
          hint={arenaHint(sources.arenaLog, t)}
          error={text.errorOf('path')}
        />
        <SavingSelect
          label={t('settings.sources.dateOrderLabel')}
          value={sources.dateOrder}
          options={dateOrderOptions}
          onSave={save && ((value) => watch(save({ dateOrder: value as DateOrder })))}
          hint={t('settings.sources.dateOrderHint')}
        />
        {save && <SaveButton dirty={text.dirty} onSave={text.submit} />}
        <RestartNote show={restart} />
      </div>
    </Card>
  )
}

function MagicOnlineCard({
  sources,
  save,
  pickFolder,
}: {
  sources: Sources
  save?: SaveSources
  pickFolder?: () => Promise<string | null>
}) {
  const { t } = useTranslation()
  const { restart, watch } = useRestart()
  const text = useTextSave(
    { mtgoHandle: sources.mtgoHandle, mtgoDir: sources.mtgoDir },
    save && ((change) => watch(save(change))),
  )
  return (
    <Card title={MAGIC_ONLINE}>
      <div className="space-y-5">
        <Field
          label={t('settings.sources.yourName')}
          value={save ? text.typed.mtgoHandle : (sources.mtgoHandle ?? '')}
          onChange={save && ((value) => text.type('mtgoHandle', value))}
          hint={t('settings.sources.yourNameHint')}
          error={text.errorOf('mtgoHandle')}
        />
        <FolderField
          label={t('settings.sources.logsFolder')}
          value={save ? text.typed.mtgoDir : (sources.mtgoDir ?? '')}
          onChange={save && ((value) => text.type('mtgoDir', value))}
          onPick={pickFolder}
          hint={
            sources.mtgoDir === null
              ? t('settings.sources.logsFolderNone')
              : t('settings.sources.logsFolderSet')
          }
          error={text.errorOf('mtgoDir')}
        />
        {save && <SaveButton dirty={text.dirty} onSave={text.submit} />}
        <RestartNote show={restart} />
      </div>
    </Card>
  )
}
