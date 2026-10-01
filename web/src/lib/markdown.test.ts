import { describe, expect, it } from 'vitest'
import { type Inline, parseInline, parseReport } from './markdown'

// Every line is invented, written in the shapes the stored reports use:
// `## ` sections, a `### ` subhead, bold lead-ins, `- ` and `1. ` lists,
// citations, links and bare urls.

const text = (value: string): Inline => ({ kind: 'text', text: value })
const cite = (label: string): Inline => ({ kind: 'cite', label })

describe('parseReport', () => {
  it('reads sections, lead-in paragraphs, lists and a subhead', () => {
    const report = [
      'A line before any heading.',
      '',
      '## Player profile',
      '',
      '**Evidence.** You win more often on the play [R4].',
      '',
      '- **Mulligans:** you keep too many slow hands.',
      '- Your sequencing is sound.',
      '',
      '## Training plan',
      '',
      '### 1. Closing out a lead',
      '',
      '1. Replay three losses.',
      '2. Note each missed attack.',
    ].join('\n')
    expect(parseReport(report)).toEqual([
      { title: null, blocks: [{ kind: 'paragraph', inline: [text('A line before any heading.')] }] },
      {
        title: 'Player profile',
        blocks: [
          {
            kind: 'paragraph',
            inline: [
              { kind: 'strong', children: [text('Evidence.')] },
              text(' You win more often on the play '),
              cite('R4'),
              text('.'),
            ],
          },
          {
            kind: 'list',
            ordered: false,
            items: [
              [{ kind: 'strong', children: [text('Mulligans:')] }, text(' you keep too many slow hands.')],
              [text('Your sequencing is sound.')],
            ],
          },
        ],
      },
      {
        title: 'Training plan',
        blocks: [
          // "1." inside a subhead is its text, not a list.
          { kind: 'subhead', inline: [text('1. Closing out a lead')] },
          {
            kind: 'list',
            ordered: true,
            start: 1,
            items: [[text('Replay three losses.')], [text('Note each missed attack.')]],
          },
        ],
      },
    ])
  })

  it('drops blank text before the first heading, and trims a title', () => {
    expect(parseReport('\n  \n##   Focus areas  \n\nBody.')).toEqual([
      { title: 'Focus areas', blocks: [{ kind: 'paragraph', inline: [text('Body.')] }] },
    ])
  })

  it('keeps a titled section with no block', () => {
    expect(parseReport('## Empty\n\n## Next\n\nBody.')).toEqual([
      { title: 'Empty', blocks: [] },
      { title: 'Next', blocks: [{ kind: 'paragraph', inline: [text('Body.')] }] },
    ])
  })

  it('joins a paragraph’s lines, and a line after an item into that item, by one space', () => {
    expect(parseReport('## S\n\nFirst line\nsecond line.\n\n- An item\nthat goes on.\n- Another.')).toEqual([
      {
        title: 'S',
        blocks: [
          { kind: 'paragraph', inline: [text('First line second line.')] },
          { kind: 'list', ordered: false, items: [[text('An item that goes on.')], [text('Another.')]] },
        ],
      },
    ])
  })

  it('reads `* ` as an unordered marker, starts a new list on a change of kind, and an ordered one at its N', () => {
    expect(parseReport('## S\n\n* One\n- Two\n3. Three\n4. Four\n- Five')).toEqual([
      {
        title: 'S',
        blocks: [
          { kind: 'list', ordered: false, items: [[text('One')], [text('Two')]] },
          { kind: 'list', ordered: true, start: 3, items: [[text('Three')], [text('Four')]] },
          { kind: 'list', ordered: false, items: [[text('Five')]] },
        ],
      },
    ])
  })

  it('reads `####` as a subhead too, and a blank line between two lists as two lists', () => {
    expect(parseReport('## S\n\n#### Deeper\n\n- A\n\n- B')).toEqual([
      {
        title: 'S',
        blocks: [
          { kind: 'subhead', inline: [text('Deeper')] },
          { kind: 'list', ordered: false, items: [[text('A')]] },
          { kind: 'list', ordered: false, items: [[text('B')]] },
        ],
      },
    ])
  })
})

describe('parseInline', () => {
  it('holds a citation inside bold', () => {
    expect(parseInline('**Keep the pressure on [R2].** Then')).toEqual([
      { kind: 'strong', children: [text('Keep the pressure on '), cite('R2'), text('.')] },
      text(' Then'),
    ])
  })

  it('reads italic', () => {
    expect(parseInline('an *early* attack')).toEqual([
      text('an '),
      { kind: 'em', children: [text('early')] },
      text(' attack'),
    ])
  })

  it('does not read a `*` with a space after it, or one closing after a space, as italic', () => {
    expect(parseInline('2 * 3 * 4')).toEqual([text('2 * 3 * 4')])
    expect(parseInline('a *word *here')).toEqual([text('a *word *here')])
  })

  it('reads a link, its label as children', () => {
    expect(parseInline('read [the primer](https://example.com/primer) first')).toEqual([
      text('read '),
      { kind: 'link', url: 'https://example.com/primer', children: [text('the primer')] },
      text(' first'),
    ])
  })

  it('holds a link inside bold', () => {
    expect(parseInline('**See [this piece](https://example.com/a).**')).toEqual([
      {
        kind: 'strong',
        children: [
          text('See '),
          { kind: 'link', url: 'https://example.com/a', children: [text('this piece')] },
          text('.'),
        ],
      },
    ])
  })

  it('ends a bare url before a full stop, and before a closing parenthesis', () => {
    expect(parseInline('Source: https://www.example.com/page.')).toEqual([
      text('Source: '),
      { kind: 'url', url: 'https://www.example.com/page' },
      text('.'),
    ])
    expect(parseInline('(see http://example.com/x)')).toEqual([
      text('(see '),
      { kind: 'url', url: 'http://example.com/x' },
      text(')'),
    ])
  })

  it('reads two adjacent citations as two', () => {
    expect(parseInline('as argued [R1][R13].')).toEqual([text('as argued '), cite('R1'), cite('R13'), text('.')])
  })

  it('leaves an unmatched `**` as text', () => {
    expect(parseInline('a **lead with no end')).toEqual([text('a **lead with no end')])
  })

  it('does not read `**` with a space after the opener as bold', () => {
    expect(parseInline('** x**')).toEqual([text('** x**')])
  })

  it('reads `[R4]` followed by a url in parentheses as a link labelled R4, not a citation', () => {
    expect(parseInline('[R4](https://example.org/r4)')).toEqual([
      { kind: 'link', url: 'https://example.org/r4', children: [text('R4')] },
    ])
  })

  it('keeps balanced parentheses in a link’s url, and ends it at an unbalanced one', () => {
    expect(parseInline('[a page](https://example.org/a_(b))')).toEqual([
      { kind: 'link', url: 'https://example.org/a_(b)', children: [text('a page')] },
    ])
    // The first `)` closes the url; the second closes the sentence's aside.
    expect(parseInline('(see [a page](https://example.org/a))')).toEqual([
      text('(see '),
      { kind: 'link', url: 'https://example.org/a', children: [text('a page')] },
      text(')'),
    ])
  })

  it('holds no citation or bare url in a link’s label: they stay text', () => {
    expect(parseInline('[per [R2] and https://example.org/x](https://example.org/y)')).toEqual([
      { kind: 'link', url: 'https://example.org/y', children: [text('per [R2] and https://example.org/x')] },
    ])
  })

  it('leaves a link to anything but http or https as text', () => {
    expect(parseInline('[label](javascript:alert(1))')).toEqual([text('[label](javascript:alert(1))')])
  })

  it('never reads `_` as emphasis', () => {
    expect(parseInline('a snake_case_name stays')).toEqual([text('a snake_case_name stays')])
  })

  it('reads code, and leaves a bracket that is not a citation as text', () => {
    expect(parseInline('run `sync` now [see below]')).toEqual([
      text('run '),
      { kind: 'code', text: 'sync' },
      text(' now [see below]'),
    ])
  })
})
