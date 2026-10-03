import { useMemo, useState } from 'react'
import {
  useGenerateRcq,
  useGuide,
  useLLMStatus,
  useMetagameStatus,
  useMetaPresence,
  useRcqGuide,
  useRcqPreview,
  type MetaWindow,
} from '../api'
import { GenerateCard } from '../components/GenerateCard'
import { InputsCard } from '../components/rcq/InputsCard'
import { PreviewCard } from '../components/rcq/PreviewCard'
import { RcqResult } from '../components/rcq/RcqResult'
import { BackLink, ErrorNote, Loading } from '../components/ui'
import { deckAddress } from '../lib/decks'
import {
  browserStorage,
  expectedOptions,
  prefillText,
  PREVIEW_DEBOUNCE_MS,
  previewKey,
  readInputs,
  useDebounced,
  writeInputs,
  type RcqInputs,
} from '../lib/rcq'
import { writerFrom } from '../lib/writer'

/** A deck's RCQ prep: the 75 the player will register and the archetypes
 *  they expect, read back by the preview, then one button that writes a
 *  tournament-day guide from them, and the latest one written.
 *
 *  The inputs are kept in `localStorage` per deck; until the player edits
 *  the list, the text box holds the deck's current 75 as the guide reads
 *  it. The preview is asked once the inputs stand still for
 *  `PREVIEW_DEBOUNCE_MS`. The write sends the list as typed with the
 *  expected keys and the chosen archetype the shown preview read, so the
 *  prompt shown is the prompt sent; it is offered only while that preview
 *  is of the current inputs, and while a newer one is on its way the
 *  button waits. */
export function RcqView({ deckKey }: { deckKey: string }) {
  const guide = useGuide(deckKey)
  const stored = useRcqGuide(deckKey)
  const llmStatus = useLLMStatus()
  const generate = useGenerateRcq()

  // The field's window, as the guide's own field reads it: since the last
  // reset when one is detected, else a year.
  const status = useMetagameStatus()
  const resetStart = status.data?.format_reset_start
  const metaWindow: MetaWindow | undefined = status.data
    ? resetStart
      ? { since: resetStart }
      : { days: 365 }
    : undefined
  const presence = useMetaPresence(metaWindow)
  const { tier, options } = useMemo(() => expectedOptions(presence.data ?? []), [presence.data])

  // `null` until the player has inputs of their own: the list then reads
  // as the deck's current 75.
  const [kept, setKept] = useState<RcqInputs | null>(() => readInputs(browserStorage(), deckKey))
  const inputs: RcqInputs = kept ?? { decklist: prefillText(guide.data?.list_diff), expected: [], own: null }
  const change = (next: RcqInputs) => {
    setKept(next)
    writeInputs(browserStorage(), deckKey, next)
  }

  const key = previewKey(inputs)
  const settledKey = useDebounced(key, PREVIEW_DEBOUNCE_MS)
  // The inputs the settled key was built from; parsed back, so the request
  // and its key can never disagree.
  const settled = useMemo<RcqInputs>(() => {
    const [decklist, expected, own] = JSON.parse(settledKey) as [string, string[], string | null]
    return { decklist, expected, own }
  }, [settledKey])
  const preview = useRcqPreview(deckKey, settled, settledKey)
  const current = preview.data != null && !preview.isPlaceholderData && settledKey === key

  if (guide.isPending) return <Loading />
  if (guide.error) return <ErrorNote error={guide.error} />

  const response = stored.data?.status === 'ok' ? stored.data : undefined
  const showOwnPicker = inputs.own != null || (current && preview.data?.own_archetype_key == null)
  const changed = response?.decklist_text != null && response.decklist_text.trim() !== inputs.decklist.trim()
  const names: Record<string, string> = Object.fromEntries(
    (preview.data?.expected ?? []).map((each) => [each.key, each.name]),
  )
  const shareNote = tier
    ? `A chip's share is of the Tier ${tier} decks ${resetStart ? 'since the last reset' : 'of the last year'}.`
    : null

  return (
    <div className="space-y-6">
      <p className="text-caption">
        <BackLink href={`${deckAddress(deckKey)}/guide`}>The guide</BackLink>
      </p>

      <InputsCard
        inputs={inputs}
        onChange={change}
        options={options}
        shareNote={shareNote}
        optionsPending={presence.isPending}
        showOwnPicker={showOwnPicker}
        names={names}
      />

      <PreviewCard
        preview={preview.data}
        error={preview.error}
        pending={preview.isPending}
        updating={preview.isFetching || settledKey !== key}
        inputs={inputs}
      />

      <GenerateCard
        title={response ? 'Write the RCQ guide again' : 'Write the RCQ guide'}
        subtitle="A game plan, the field you will meet, a plan for each matchup checked against your 75, the flex slots and a checklist between rounds."
        accent
        writer={writerFrom(llmStatus.data, null, 'guide')}
        prompt={current ? preview.data?.prompt : undefined}
        narrative={undefined}
        model={response?.model}
        generatedAt={response?.generated_at}
        costUsd={response?.cost_usd}
        stale={changed}
        staleNote="The list has changed since."
        loading={!current && inputs.decklist.trim() !== ''}
        onGenerate={() =>
          generate.mutate({
            key: deckKey,
            body: { decklist: inputs.decklist, expected: settled.expected, own: settled.own },
          })
        }
        generating={generate.isPending}
        generateError={generate.error?.message}
      />

      {stored.error ? (
        <ErrorNote error={stored.error} />
      ) : (
        stored.data && <RcqResult deckKey={deckKey} response={stored.data} />
      )}
    </div>
  )
}
