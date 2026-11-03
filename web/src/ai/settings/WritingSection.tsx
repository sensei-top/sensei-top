import type { DeepPartial, KeyName, Saved, ShellSettings } from '../../bridge'
import { useTranslation } from 'react-i18next'
import { useRestart, type WritingStatusAnswer } from '../../lib/settings'
import { Card } from '../../components/ui'
import { KeyField } from '../../components/settings/KeyField'
import { RestartNote, SavingSelect } from '../../components/settings/SaveButton'

// Product names, the same in every language.
const CLAUDE = 'Claude'

type Writing = ShellSettings['writing']

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
 *  the model that writes). A key is never shown, only whether one is
 *  set. With no shell the page draws `WritingStatus` in its place; with
 *  a shell and no functions to call, every value is text and nothing
 *  can be changed. */
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
