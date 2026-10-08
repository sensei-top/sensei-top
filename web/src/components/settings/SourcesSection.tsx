import type { DateOrder, DeepPartial, Saved, ShellSettings } from '../../bridge'
import { useState } from 'react'
import { failureOf, settle, useRestart, useTextSave } from '../../lib/settings'
import { Card, Field } from '../ui'
import { FolderField, PressButton, RestartNote, SaveButton, SavingSelect } from './SaveButton'

type Sources = ShellSettings['sources']
type SaveSources = (change: DeepPartial<Sources>) => Promise<Saved>

const DATE_ORDER_OPTIONS: { value: DateOrder; label: string }[] = [
  { value: 'auto', label: 'Read it from the log' },
  { value: 'mdy', label: 'Month first' },
  { value: 'dmy', label: 'Day first' },
]

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
  const [failure, setFailure] = useState<string | null>(null)
  const open = async (): Promise<boolean> => {
    setFailure(null)
    const sentence = failureOf(await settle(showDataFolder?.() ?? Promise.resolve({ ok: true } as const)))
    setFailure(sentence)
    return sentence === null
  }
  return (
    <Card>
      <div className="space-y-3">
        <Field
          label="Where your matches are kept"
          value={dataDir}
          hint="One folder on this computer. Nothing in it leaves the computer unless you turn that on."
        />
        {showDataFolder && (
          <PressButton variant="quiet" label="Open folder" workingLabel="Opening" doneLabel={null} onPress={open} />
        )}
        {failure && <p className="break-words text-caption text-loss">{failure}</p>}
      </div>
    </Card>
  )
}

function arenaHint({ path, found }: Sources['arenaLog']): string {
  if (path === null) return "The app did not find Arena's log. Give it the file's place."
  return found ? 'The app found it where Arena writes it.' : 'Where Arena writes its log.'
}

function ArenaCard({ sources, save }: { sources: Sources; save?: SaveSources }) {
  const { restart, watch } = useRestart()
  const text = useTextSave({ path: sources.arenaLog.path }, save && ((change) => watch(save({ arenaLog: change }))))
  return (
    <Card title="Arena">
      <div className="space-y-5">
        <Field
          label="Log file"
          value={save ? text.typed.path : (sources.arenaLog.path ?? '')}
          onChange={save && ((value) => text.type('path', value))}
          hint={arenaHint(sources.arenaLog)}
          error={text.errorOf('path')}
        />
        <SavingSelect
          label="Date order"
          value={sources.dateOrder}
          options={DATE_ORDER_OPTIONS}
          onSave={save && ((value) => watch(save({ dateOrder: value as DateOrder })))}
          hint="The order of the day and the month in the log's dates."
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
  const { restart, watch } = useRestart()
  const text = useTextSave(
    { mtgoHandle: sources.mtgoHandle, mtgoDir: sources.mtgoDir },
    save && ((change) => watch(save(change))),
  )
  return (
    <Card title="Magic Online">
      <div className="space-y-5">
        <Field
          label="Your name there"
          value={save ? text.typed.mtgoHandle : (sources.mtgoHandle ?? '')}
          onChange={save && ((value) => text.type('mtgoHandle', value))}
          hint="The game's log never says which player is you."
          error={text.errorOf('mtgoHandle')}
        />
        <FolderField
          label="Folder of game logs"
          value={save ? text.typed.mtgoDir : (sources.mtgoDir ?? '')}
          onChange={save && ((value) => text.type('mtgoDir', value))}
          onPick={pickFolder}
          hint={
            sources.mtgoDir === null
              ? 'Nothing is read from Magic Online until a folder is set.'
              : 'Each game is read once it ends.'
          }
          error={text.errorOf('mtgoDir')}
        />
        {save && <SaveButton dirty={text.dirty} onSave={text.submit} />}
        <RestartNote show={restart} />
      </div>
    </Card>
  )
}
