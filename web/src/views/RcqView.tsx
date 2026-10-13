import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useGenerateRcq,
  useGuide,
  useLLMStatus,
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
/** How far back the expected-archetype chips read the field. */
const CHIP_WINDOW_DAYS = 14

export function RcqView({ deckKey }: { deckKey: string }) {
  const { t } = useTranslation()
  const guide = useGuide(deckKey)
  const stored = useRcqGuide(deckKey)
  const llmStatus = useLLMStatus()
  const generate = useGenerateRcq()

  // The field the chips offer: the last two weeks of the deck's format, the
  // field a store's players will have netdecked from. Nothing is asked
  // until the guide names the format, nor when it names none. The guide's
  // own numbers keep their own window.
  const formatUnknown = guide.data != null && guide.data.field.fmt == null
  const chipFormat = guide.data?.field.fmt ?? undefined
  const metaWindow: MetaWindow | undefined = chipFormat ? { days: CHIP_WINDOW_DAYS } : undefined
  const presence = useMetaPresence(metaWindow, chipFormat)
  const { tier, options } = useMemo(() => expectedOptions(presence.data ?? []), [presence.data])

  // `null` until the player has inputs of their own: the list then reads
  // as the deck's current 75.
  const [kept, setKept] = useState<RcqInputs | null>(() => readInputs(browserStorage(), deckKey))
  const inputs: RcqInputs = kept ?? { decklist: prefillText(guide.data?.list_diff), expected: [], own: null }
  const change = (next: RcqInputs) => {
    setKept(next)
    writeInputs(browserStorage(), deckKey, next)
  }

  // No format hides the chips, so stored picks must not shape the preview or the guide.
  const key = previewKey({ ...inputs, expected: formatUnknown ? [] : inputs.expected })
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
    ? t('rcq.chips.shareNote', { tier, days: CHIP_WINDOW_DAYS })
    : null

  return (
    <div className="space-y-6">
      <p className="text-caption">
        <BackLink href={`${deckAddress(deckKey)}/guide`}>{t('rcq.view.back')}</BackLink>
      </p>

      <InputsCard
        inputs={inputs}
        onChange={change}
        options={options}
        shareNote={shareNote}
        optionsPending={chipFormat !== undefined && presence.isPending}
        formatUnknown={formatUnknown}
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
        title={response ? t('rcq.view.writeAgain') : t('rcq.view.write')}
        subtitle={t('rcq.view.subtitle')}
        accent
        writer={writerFrom(llmStatus.data)}
        prompt={current ? preview.data?.prompt : undefined}
        narrative={undefined}
        model={response?.model}
        generatedAt={response?.generated_at}
        costUsd={response?.cost_usd}
        stale={changed}
        staleNote={t('rcq.view.staleNote')}
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
