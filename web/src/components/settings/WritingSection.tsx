import type { DeepPartial, KeyName, Saved, ShellSettings } from '../../bridge'
import { useRestart } from '../../lib/settings'
import { Card } from '../ui'
import { KeyField } from './KeyField'
import { RestartNote, SavingSelect } from './SaveButton'

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
  if (answer === 'loading') return null
  if (answer === 'failed') {
    return (
      <Card className="max-w-3xl">
        <p className="text-body text-ink2">The app did not say whether a key is set.</p>
      </Card>
    )
  }
  const first = !answer.configured
    ? 'No Claude key is set. Each report gives you its prompt to copy, and takes the answer you paste back.'
    : answer.model
      ? `A Claude key is set. Reports are written by ${answer.model} when you press the button that says so.`
      : 'A Claude key is set. Reports are written when you press the button that says so.'
  return (
    <Card className="max-w-3xl">
      <div className="space-y-2 text-body text-ink2">
        <p>{first}</p>
        <p>{"The key and the model are set in the app's config file."}</p>
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
  const { restart, watch } = useRestart()
  return (
    <Card
      title="Claude"
      subtitle="With a key of your own, a report is written when you press its button, and what it cost is shown on it. With none, each report gives you its prompt to copy."
    >
      <div className="space-y-5">
        <KeyField
          set={writing.claudeKey}
          onSet={setKey && ((key) => watch(setKey('claude', key)))}
          removeBody="Reports go back to giving you their prompt to copy. What is already written stays."
        />
        <SavingSelect
          label="Model"
          value={writing.model}
          options={writing.models}
          onSave={save && ((model) => watch(save({ model })))}
          hint="What each report cost is measured and shown on the report."
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
  const { restart, watch } = useRestart()
  return (
    <Card title="TopDeck.gg" subtitle="A free key from TopDeck.gg adds its tournaments to the field.">
      <div className="space-y-5">
        <KeyField
          set={set}
          onSet={setKey && ((key) => watch(setKey('topdeck', key)))}
          removeBody="The field stops taking tournaments from TopDeck.gg. What is already here stays."
        />
        <RestartNote show={restart} />
      </div>
    </Card>
  )
}
