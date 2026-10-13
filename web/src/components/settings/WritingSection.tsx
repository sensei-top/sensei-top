import type { DeepPartial, KeyName, Saved, ShellSettings } from '../../bridge'
import { useTranslation } from 'react-i18next'
import { useRestart } from '../../lib/settings'
import { Card } from '../ui'
import { KeyField } from './KeyField'
import { RestartNote, SavingSelect } from './SaveButton'

// Product names, the same in every language.
const CLAUDE = 'Claude'
const TOPDECK = 'TopDeck.gg'

type Writing = ShellSettings['writing']

/** What the API says of writing, with no shell: `configured` and the
 *  model's id as it came, `'loading'` while it is asked, `'failed'` when
 *  it did not answer. */
export type WritingStatusAnswer = { configured: boolean; model: string | null } | 'loading' | 'failed'

/** How reports get written, with no shell: one card of sentences from the
 *  API's answer, whether a Claude key is set and which model writes, or
 *  what the app does with none. Nothing in it can be changed here; the
 *  config file is where that is done. While the answer loads it draws
 *  nothing. The model is shown by its id as the API gives it, since the
 *  page holds no list of the models' names. */
export function WritingStatus({ answer }: { answer: WritingStatusAnswer }) {
  const { t } = useTranslation()
  if (answer === 'loading') return null
  if (answer === 'failed') {
    return (
      <Card className="max-w-3xl">
        <p className="text-body text-ink2">{t('settings.writing.statusFailed')}</p>
      </Card>
    )
  }
  const first = !answer.configured
    ? t('settings.writing.noKey')
    : answer.model
      ? t('settings.writing.keyWithModel', { model: answer.model })
      : t('settings.writing.keyNoModel')
  return (
    <Card className="max-w-3xl">
      <div className="space-y-2 text-body text-ink2">
        <p>{first}</p>
        <p>{t('settings.writing.configFile')}</p>
      </div>
    </Card>
  )
}

/** How reports get written, with a shell: the Claude card (its key, then
 *  the model that writes) and the TopDeck.gg card (its key). A key is
 *  never shown, only whether one is set. With no shell the page draws
 *  `WritingStatus` in its place; with a shell and no functions to call,
 *  every value is text and nothing can be changed. */
export function WritingSection({
  writing,
  save,
  setKey,
}: {
  writing: Writing
  save?: (change: DeepPartial<Writing>) => Promise<Saved>
  setKey?: (which: KeyName, key: string | null) => Promise<Saved>
}) {
  return (
    <div className="max-w-3xl space-y-6">
      <ClaudeCard writing={writing} save={save} setKey={setKey} />
      <TopDeckCard set={writing.topdeckKey} setKey={setKey} />
    </div>
  )
}

function ClaudeCard({
  writing,
  save,
  setKey,
}: {
  writing: Writing
  save?: (change: DeepPartial<Writing>) => Promise<Saved>
  setKey?: (which: KeyName, key: string | null) => Promise<Saved>
}) {
  const { t } = useTranslation()
  const { restart, watch } = useRestart()
  return (
    <Card title={CLAUDE} subtitle={t('settings.writing.claudeSubtitle')}>
      <div className="space-y-5">
        <KeyField
          set={writing.claudeKey}
          onSet={setKey && ((key) => watch(setKey('claude', key)))}
          removeBody={t('settings.writing.claudeRemoveBody')}
        />
        <SavingSelect
          label={t('settings.writing.model')}
          value={writing.model}
          options={writing.models}
          onSave={save && ((model) => watch(save({ model })))}
          hint={t('settings.writing.modelHint')}
        />
        <RestartNote show={restart} />
      </div>
    </Card>
  )
}

function TopDeckCard({
  set,
  setKey,
}: {
  set: boolean
  setKey?: (which: KeyName, key: string | null) => Promise<Saved>
}) {
  const { t } = useTranslation()
  const { restart, watch } = useRestart()
  return (
    <Card title={TOPDECK} subtitle={t('settings.writing.topdeckSubtitle')}>
      <div className="space-y-5">
        <KeyField
          set={set}
          onSet={setKey && ((key) => watch(setKey('topdeck', key)))}
          removeBody={t('settings.writing.topdeckRemoveBody')}
        />
        <RestartNote show={restart} />
      </div>
    </Card>
  )
}
