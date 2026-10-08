import { useState } from 'react'
import { type MatchupBriefOut, useGuideBriefPrompt, useGuideBriefs, useGuideCoverage } from '../api'
import { FORMAT_UNKNOWN_BRIEF } from '../lib/brief'
import { problemSentence } from '../lib/guide'
import { archetypeKeyOf } from '../lib/matchups'
import { briefState } from '../lib/pairing'
import { useNow } from '../lib/time'
import { writtenNote } from '../lib/written'
import { CopyPromptBody } from './CopyPromptCard'
import { PlanBody } from './guide/WrittenCards'
import { Button, Callout, Card, ErrorNote, Loading, SectionLabel } from './ui'

const TITLE = 'Matchup brief'
const SUBTITLE =
  'What to play around and what to bring in against this archetype. It is written once, and Live shows it whenever you meet one.'
const CANNOT_WRITE = 'Too few tournament lists of this archetype to write a brief from yet.'

/** A stored brief: what to play around, card then reason; the swap, its
 *  problems and the prose as a guide's plan lays them (`PlanBody`); then
 *  who wrote it and when, and whether it came with the deck's guide. */
function WrittenBrief({ brief }: { brief: MatchupBriefOut }) {
  const now = useNow()
  const written = writtenNote({ author: brief.model, authoredAt: brief.generated_at, costUsd: null, stale: false, now })
  const note = [written, brief.source === 'guide' ? "It came with the deck's written guide." : null]
    .filter((part) => part != null)
    .join(' ')
  return (
    <>
      {brief.play_around.length > 0 && (
        <div>
          <SectionLabel>Play around</SectionLabel>
          <ul className="mt-1 space-y-1">
            {brief.play_around.map((item, i) => (
              <li key={i} className="break-words text-body">
                <span className="font-medium text-ink">{item.card}</span>{' '}
                <span className="text-ink2">{item.why}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <PlanBody
        boardIn={brief.board_in}
        boardOut={brief.board_out}
        prose={brief.prose}
        problems={brief.problems.map((problem) => problemSentence(problem, false))}
      />
      {note && <p className="mt-3 text-caption text-muted">{note}</p>}
    </>
  )
}

/** The brief against a pairing's opponent, a card of the pairing's page.
 *  It reads the deck's coverage (shared with the page's heading, one
 *  query) and its stored briefs; while either loads the card says so, and
 *  a failure of either is the card's error, drawn in its place. Then, by
 *  `briefState`: a key that is not a named archetype says a brief needs
 *  one; a stored brief is drawn, and when coverage says it is stale, a
 *  warning first and "Write it again" last; with none, a deck whose format
 *  is unknown says so, an archetype with too few lists says so, and any
 *  other offers "Build the prompt". Either button goes on its press and
 *  the prompt's body takes its place: the prompt is fetched on that press,
 *  never when the page loads. */
export function PairingBrief({ deckKey, opponentKey }: { deckKey: string; opponentKey: string }) {
  const coverage = useGuideCoverage(deckKey)
  const briefs = useGuideBriefs(deckKey)
  // Set by a press of "Build the prompt" or "Write it again": the prompt
  // is fetched then, never on the page's load.
  const [open, setOpen] = useState(false)
  const archetype = archetypeKeyOf(opponentKey)
  const prompt = useGuideBriefPrompt(deckKey, archetype ?? undefined, open)

  const error = coverage.error ?? briefs.error
  if (error) return <ErrorNote error={error} />
  // With no error, a query with no data yet is still loading.
  if (coverage.data == null || briefs.data == null) {
    return (
      <Card title={TITLE} subtitle={SUBTITLE}>
        <Loading />
      </Card>
    )
  }

  const state = briefState(opponentKey, coverage.data, briefs.data)
  // A prompt the route answers `format_unknown` or `no_consensus` says the
  // brief cannot be written, in the body's place for an error.
  const promptBody = state.kind !== 'not_named' && (
    <CopyPromptBody
      prompt={prompt.data?.status === 'ok' ? prompt.data.prompt : undefined}
      loading={prompt.isLoading}
      error={
        prompt.error?.message ??
        (prompt.data?.status === 'format_unknown'
          ? FORMAT_UNKNOWN_BRIEF
          : prompt.data?.status === 'no_consensus'
            ? CANNOT_WRITE
            : undefined)
      }
      importCommand={`sensei-top brief --deck "${deckKey}" --archetype "${state.archetype}" --import brief.json`}
    />
  )
  let body
  if (state.kind === 'not_named') {
    body = (
      <p className="text-body text-ink2">
        A brief is written against an archetype named from tournament results, and this deck is not one.
      </p>
    )
  } else if (state.kind === 'format_unknown') {
    body = <p className="text-body text-ink2">{FORMAT_UNKNOWN_BRIEF}</p>
  } else if (state.kind === 'cannot_write') {
    body = <p className="text-body text-ink2">{CANNOT_WRITE}</p>
  } else if (state.kind === 'not_written') {
    body = (
      <>
        <p className="text-body text-ink2">
          No brief for it yet. Build its prompt, paste it into an assistant, and save the answer with the command that
          comes with it.
        </p>
        {open ? (
          promptBody
        ) : (
          <div className="mt-3">
            <Button variant="primary" onClick={() => setOpen(true)}>
              Build the prompt
            </Button>
          </div>
        )}
      </>
    )
  } else {
    body = (
      <>
        {state.stale && (
          <div className="mb-4">
            <Callout tone="warn" title="Written before the list or the field changed">
              <p>
                Your list or the tournament results have changed since this brief was written, so it may name a card or
                a number that no longer holds.
              </p>
            </Callout>
          </div>
        )}
        <WrittenBrief brief={state.brief} />
        {state.stale &&
          (open ? (
            promptBody
          ) : (
            <div className="mt-4">
              <Button variant="secondary" onClick={() => setOpen(true)}>
                Write it again
              </Button>
            </div>
          ))}
      </>
    )
  }

  return (
    <Card title={TITLE} subtitle={SUBTITLE}>
      {body}
    </Card>
  )
}
