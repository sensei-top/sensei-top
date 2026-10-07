import type { CoachEvidenceModel, DeckLeaksOut } from '../../api'
import { deckPatternsSummary, patternDirection } from '../../lib/coach'
import { categoryLabel } from '../../lib/guide'
import { patternSentence, patternWords } from '../../lib/patterns'
import { Card, Chip, Disclosure } from '../ui'

type PatternLine = CoachEvidenceModel['leaks'][number]

/** One pattern: its category as a chip and, beside it, how far and which
 *  way the matches with it differ from those without; the API's own
 *  `pattern` as the title; then the Guide's sentence, its counts from the
 *  two rates and its clause from `PATTERN_WORDS` by the code. No bars: the
 *  Guide has them. */
function PatternRow({ pattern }: { pattern: PatternLine }) {
  const direction = patternDirection(pattern)
  const { clause } = patternWords({ code: pattern.code, sample_title: pattern.pattern })
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Chip>{categoryLabel(pattern.category)}</Chip>
        {direction && <span className="text-caption text-muted">{direction}</span>}
      </div>
      <p className="mt-2 text-body font-medium text-ink">{pattern.pattern}</p>
      <p className="mt-1 text-body text-ink2">{patternSentence(clause, pattern.present, pattern.absent)}</p>
    </>
  )
}

function PatternRows({ patterns }: { patterns: PatternLine[] }) {
  return (
    <ul className="divide-y divide-line">
      {patterns.map((pattern, index) => (
        <li key={index} className="py-3 first:pt-0 last:pb-0">
          <PatternRow pattern={pattern} />
        </li>
      ))}
    </ul>
  )
}

/** "Patterns": the leak finder's patterns over every deck, then each deck's
 *  own behind a disclosure. Two decks may share a label, so a deck is keyed
 *  by its place. */
export function PatternsCard({ leaks, deckLeaks }: { leaks: PatternLine[]; deckLeaks: DeckLeaksOut[] }) {
  const decks = deckLeaks.filter((deck) => deck.leaks.length > 0)
  if (leaks.length === 0 && decks.length === 0) return null
  return (
    <Card
      title="Patterns"
      subtitle="What your matches with a pattern have in common, against your matches without it, over every deck."
    >
      {leaks.length > 0 && <PatternRows patterns={leaks} />}
      {decks.length > 0 && (
        // A deck a row, divided as the patterns are, and a line over the
        // first when patterns over every deck sit above: every summary
        // starts under a line, never as the tail of the row above.
        <ul className={`divide-y divide-line ${leaks.length > 0 ? 'mt-3 border-t border-line pt-3' : ''}`}>
          {decks.map((deck, index) => (
            <li key={index} className="py-3 first:pt-0 last:pb-0">
              <Disclosure summary={deckPatternsSummary(deck.deck_label, deck.leaks.length)}>
                <PatternRows patterns={deck.leaks} />
              </Disclosure>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
