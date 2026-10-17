import type { AppSettings, DateOrder, DeepPartial, Saved, ShellSettings } from '../../bridge'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from '../../i18n'
import { failureOf, settle, useRestart, useTextSave } from '../../lib/settings'
import { formatCount } from '../../lib/time'
import { CardDataProgress } from '../onboarding/CardDataProgress'
import { Card, Field } from '../ui'
import { FolderField, PressButton, RestartNote, SaveButton, SavingSelect } from './SaveButton'

// The games' own names, the same in every language.
const ARENA = 'Arena'
const MAGIC_ONLINE = 'Magic Online'

type Sources = ShellSettings['sources']
type SaveSources = (change: DeepPartial<Sources>) => Promise<Saved>

/** What the app reads: the two games' logs, in a card each, then the card
 *  data (drawn only when the shell passes its app part), then the folder
 *  where the matches are kept. Only a shell knows any of it, so with
 *  no shell the page does not draw this section at all. With a shell and no
 *  `save`, every value is text and nothing can be changed. */
export function SourcesSection({
  sources,
  save,
  pickFolder,
  showDataFolder,
  app,
}: {
  sources: Sources
  save?: SaveSources
  pickFolder?: () => Promise<string | null>
  showDataFolder?: () => Promise<Saved>
  /** The shell's app state; with none, the Card data card is not drawn. */
  app?: Pick<AppSettings, 'rulesText' | 'firstData'> & { startFirstData(): Promise<Saved> }
}) {
  return (
    <div className="max-w-3xl space-y-6">
      <ArenaCard sources={sources} save={save} />
      <MagicOnlineCard sources={sources} save={save} pickFolder={pickFolder} />
      {app && <CardDataCard app={app} />}
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
    { mtgoHandle: sources.mtgoHandle, mtgoDir: sources.mtgoDir, mtgoDeckDir: sources.mtgoDeckDir },
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
        <FolderField
          label={t('settings.sources.decksFolder')}
          value={save ? text.typed.mtgoDeckDir : (sources.mtgoDeckDir ?? '')}
          onChange={save && ((value) => text.type('mtgoDeckDir', value))}
          onPick={pickFolder}
          hint={
            sources.mtgoDeckDir === null
              ? t('settings.sources.decksFolderNone')
              : t('settings.sources.decksFolderSet')
          }
          error={text.errorOf('mtgoDeckDir')}
        />
        {save && <SaveButton dirty={text.dirty} onSave={text.submit} />}
        <RestartNote show={restart} />
      </div>
    </Card>
  )
}

/** What card data the app holds: the count, a button that starts the
 *  download, and the download's own states once it has started. */
function CardDataCard({ app }: { app: NonNullable<Parameters<typeof SourcesSection>[0]['app']> }) {
  const { t } = useTranslation()
  const [failure, setFailure] = useState<string | null>(null)
  const { rulesText: count, firstData: state } = app
  const start = async (): Promise<boolean> => {
    setFailure(null)
    const sentence = failureOf(await settle(app.startFirstData(), t), t)
    setFailure(sentence)
    return sentence === null
  }
  // Only a refusal, which comes back while the state is idle or done, stays.
  if (state.state === 'running' && failure !== null) setFailure(null)
  const idle = state.state === 'idle'
  const line =
    count === null
      ? t('settings.sources.cardData.unknown')
      : count > 0
        ? t('settings.sources.cardData.count', { n: formatCount(count) })
        : t('settings.sources.cardData.none')
  const button = idle || state.state === 'done'
  return (
    <Card title={t('settings.sources.cardData.title')}>
      <div className="space-y-3">
        {idle && <p className="text-body text-ink2">{line}</p>}
        <CardDataProgress state={state} count={count} retry={app.startFirstData} />
        {button && (
          <PressButton
            variant={count || !idle ? 'quiet' : 'primary'}
            label={count || !idle ? t('settings.sources.cardData.downloadAgain') : t('settings.sources.cardData.download')}
            workingLabel={t('common.cardData.starting')}
            doneLabel={null}
            onPress={start}
          />
        )}
        {button && failure && <p className="break-words text-caption text-loss">{failure}</p>}
      </div>
    </Card>
  )
}
