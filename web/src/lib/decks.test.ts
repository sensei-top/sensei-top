import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import type { Deck, DeckIdentityOut, Match } from '../api'
import {
  archetypeName,
  chosenSort,
  deckAddress,
  deckLine,
  deckRecord,
  deckRedirect,
  decksTiles,
  fieldNameLine,
  filterTiles,
  formatName,
  newestVersion,
  resolveDeck,
  sortTiles,
  tileDetail,
  tileFormats,
} from './decks'

const t = translator('en')

// The zone is America/New_York (vitest.config.ts). Every timestamp below is
// bare, so the log's own local clock. Names, keys and ids are invented.

/** A row of `/api/guide/decks` with only what these functions read. */
function identity(key: string, deckIds: string[], rest: Partial<DeckIdentityOut> = {}): DeckIdentityOut {
  return {
    key,
    name: null,
    format: null,
    deck_ids: deckIds,
    matches: 0,
    match_wins: 0,
    match_losses: 0,
    last_played: null,
    ...rest,
  } as DeckIdentityOut
}

describe('resolveDeck', () => {
  const kites = identity('guid:kites', ['v1', 'v2'])
  const choir = identity('deck:v3', ['v3'])
  const identities = [kites, choir]

  it('names the deck whose key is the id', () => {
    expect(resolveDeck('guid:kites', identities)).toEqual({ identity: kites, viaVersion: false })
    expect(resolveDeck('deck:v3', identities)).toEqual({ identity: choir, viaVersion: false })
  })

  it('names the deck one of whose versions is the id, and marks it so', () => {
    expect(resolveDeck('v2', identities)).toEqual({ identity: kites, viaVersion: true })
    expect(resolveDeck('v3', identities)).toEqual({ identity: choir, viaVersion: true })
  })

  it('names nothing for an id that is neither, or no id', () => {
    expect(resolveDeck('v9', identities)).toBeNull()
    expect(resolveDeck(undefined, identities)).toBeNull()
  })

  it('names nothing from an empty list', () => {
    expect(resolveDeck('guid:kites', [])).toBeNull()
  })
})

describe('deckAddress', () => {
  it('keeps the key’s colon bare', () => {
    expect(deckAddress('guid:ab-12')).toBe('/decks/guid:ab-12')
    expect(deckAddress('deck:a:b')).toBe('/decks/deck:a:b')
  })

  it('still encodes anything else that needs it', () => {
    // A space is %20, a slash %2F: a slash left bare would end the segment.
    expect(deckAddress('guid:two words')).toBe('/decks/guid:two%20words')
    expect(deckAddress('deck:a/b')).toBe('/decks/deck:a%2Fb')
  })
})

describe('deckRedirect', () => {
  it('sends a version’s address to the deck’s, keeping the page under it', () => {
    expect(deckRedirect('/decks/v2/guide', 'guid:kites')).toBe('/decks/guid:kites/guide')
    expect(deckRedirect('/decks/v2/matchups', 'guid:kites')).toBe('/decks/guid:kites/matchups')
  })

  it('lands on the overview when the address had no page under the deck', () => {
    expect(deckRedirect('/decks/v2', 'guid:kites')).toBe('/decks/guid:kites')
  })

  it('sends a key spelled with %3A, in either case, to the bare colon', () => {
    expect(deckRedirect('/decks/guid%3Akites', 'guid:kites')).toBe('/decks/guid:kites')
    expect(deckRedirect('/decks/guid%3akites/guide', 'guid:kites')).toBe('/decks/guid:kites/guide')
  })

  it('sends nowhere once the address is the deck’s own, so it cannot loop', () => {
    expect(deckRedirect('/decks/guid:kites', 'guid:kites')).toBeNull()
    expect(deckRedirect('/decks/guid:kites/matchups', 'guid:kites')).toBeNull()
    expect(deckRedirect('/decks/guid:two%20words/guide', 'guid:two words')).toBeNull()
  })
})

describe('newestVersion', () => {
  const version = (deckId: string, lastPlayed: string) => ({ deck_id: deckId, last_played: lastPlayed }) as Deck
  const versions = [version('v1', '2026-09-01T20:00:00'), version('v2', '2026-09-27T20:00:00'), version('v9', '2026-09-28T09:00:00')]

  it('is the version played last among the deck’s own', () => {
    // v9 is newer but another deck's.
    expect(newestVersion(identity('guid:kites', ['v1', 'v2']), versions)).toBe('v2')
  })

  it('falls to the deck’s first version when none is listed', () => {
    expect(newestVersion(identity('guid:choir', ['v5', 'v6']), versions)).toBe('v5')
  })

  it('is null for a deck with no version', () => {
    expect(newestVersion(identity('guid:none', []), versions)).toBeNull()
  })
})

describe('archetypeName', () => {
  it('spaces a name run together', () => {
    expect(archetypeName('AzureKites')).toBe('Azure Kites')
    expect(archetypeName('4c LanternStormCombo')).toBe('4c Lantern Storm Combo')
  })

  it('leaves a name already spaced as it is', () => {
    expect(archetypeName('Ember Choir')).toBe('Ember Choir')
  })

  it('leaves a hyphen as it is: a capital after one is not after a lower-case letter', () => {
    expect(archetypeName('Mono-Blue Kites')).toBe('Mono-Blue Kites')
  })

  it('puts no space after a digit, nor between capitals', () => {
    expect(archetypeName('4c Lantern')).toBe('4c Lantern')
    expect(archetypeName('5Color Ramp')).toBe('5Color Ramp')
    expect(archetypeName('UW Control')).toBe('UW Control')
  })
})

describe('formatName', () => {
  it('writes each format as the wording has it', () => {
    expect(formatName('Standard', t)).toBe('Standard')
    expect(formatName('TraditionalStandard', t)).toBe('Standard, best of three')
    expect(formatName('TraditionalHistoric', t)).toBe('Historic, best of three')
    expect(formatName('Draft', t)).toBe('Draft')
    expect(formatName('HistoricBrawl', t)).toBe('Historic Brawl')
    expect(formatName('Premodern', t)).toBe('Premodern')
    expect(formatName('Modern', t)).toBe('Modern')
  })

  it('is null without a format', () => {
    expect(formatName(null, t)).toBeNull()
    expect(formatName(undefined, t)).toBeNull()
  })
})

describe('fieldNameLine', () => {
  it('names the field’s archetype when it differs from the typed name', () => {
    expect(fieldNameLine('AzureKiteStorm', 'Kite Storm', t)).toBe('Azure Kite Storm in the field')
  })

  it('says nothing when the spaced name is the typed one, case aside', () => {
    expect(fieldNameLine('EmberChoir', 'Ember Choir', t)).toBeNull()
    expect(fieldNameLine('Ember Choir', 'ember choir', t)).toBeNull()
  })

  it('says nothing when the guide names no archetype', () => {
    expect(fieldNameLine(null, 'Ember Choir', t)).toBeNull()
    expect(fieldNameLine(undefined, null, t)).toBeNull()
  })

  it('names the archetype of a deck with no typed name', () => {
    expect(fieldNameLine('LanternControl', null, t)).toBe('Lantern Control in the field')
  })
})

describe('deckLine', () => {
  const now = new Date(2026, 8, 28, 12, 0, 0).getTime()

  it('joins the format and the last played, and leaves out the match count', () => {
    // 12:00 on the log's own clock, 24 hours before now: "1d ago".
    const deck = identity('guid:kites', ['v1'], {
      format: 'TraditionalStandard',
      matches: 64,
      match_wins: 30,
      match_losses: 33,
      last_played: '2026-09-27T12:00:00',
    })
    expect(deckLine(deck, now, t)).toBe('Standard, best of three · last played 1d ago')
  })

  it('leaves out a format it does not know, with no dash', () => {
    const deck = identity('guid:kites', ['v1'], { matches: 2, last_played: '2026-09-13T12:00:00' })
    expect(deckLine(deck, now, t)).toBe('last played 15d ago')
  })

  it('leaves out a last played it does not know', () => {
    const deck = identity('guid:kites', ['v1'], { format: 'Draft', matches: 2, match_wins: 1 })
    expect(deckLine(deck, now, t)).toBe('Draft')
  })
})

describe('deckRecord', () => {
  it('is a rate from ten finished matches, with the record under it', () => {
    // 35 / 60 = 0.583…, 58%; the losses are 60 - 35.
    expect(deckRecord({ finished: 60, wins: 35 }, t)).toEqual({ figure: '58%', line: 'win rate · 35\u2060–\u206025', thin: false })
    expect(deckRecord({ finished: 10, wins: 5 }, t)).toEqual({ figure: '50%', line: 'win rate · 5\u2060–\u20605', thin: false })
  })

  it('is the rate, muted, from five to nine', () => {
    expect(deckRecord({ finished: 9, wins: 6 }, t)).toEqual({
      figure: '67%',
      line: 'rough win rate · 6\u2060–\u20603, under 10\u00a0matches',
      thin: true,
    })
    expect(deckRecord({ finished: 5, wins: 2 }, t)).toEqual({
      figure: '40%',
      line: 'rough win rate · 2\u2060–\u20603, under 10\u00a0matches',
      thin: true,
    })
  })

  it('is the record, muted, from one to four', () => {
    const line = 'too few for a rate, under 5\u00a0matches'
    expect(deckRecord({ finished: 4, wins: 3 }, t)).toEqual({ figure: '3\u2060–\u20601', line, thin: true })
    expect(deckRecord({ finished: 1, wins: 0 }, t)).toEqual({ figure: '0\u2060–\u20601', line, thin: true })
  })

  it('has no figure with no finished match', () => {
    expect(deckRecord({ finished: 0, wins: 0 }, t)).toEqual({ figure: null, line: 'no finished match yet', thin: false })
  })
})

describe('decksTiles, same-named decks', () => {
  const NOW_LOCAL = new Date(2026, 8, 29, 12, 0, 0).getTime()
  const tiles = decksTiles(
    [
      identity('guid:old', ['v1'], { name: 'Azure Kites', first_played: '2026-09-03T20:00:00', last_played: '2026-09-14T20:00:00' }),
      identity('guid:new', ['v2'], { name: 'Azure Kites', first_played: '2026-09-15T20:00:00', last_played: '2026-09-27T20:00:00' }),
      identity('guid:alone', ['v3'], { name: 'Ember Choir', first_played: '2026-09-01T20:00:00', last_played: '2026-09-02T20:00:00' }),
      identity('guid:blank', ['v4'], { first_played: '2026-09-04T20:00:00', last_played: '2026-09-05T20:00:00' }),
      identity('deck:blank2', ['v5'], { first_played: '2026-09-20T20:00:00', last_played: '2026-09-21T20:00:00' }),
    ],
    [],
    t,
    NOW_LOCAL,
  )

  it('gives the newest of a shared name the chip and the others their range', () => {
    // The API lists the later one second here on purpose: order does not decide.
    expect(tiles[1].newest).toBe(true)
    expect(tiles[1].playedRange).toBeNull()
    expect(tiles[0].newest).toBe(false)
    expect(tiles[0].playedRange).toBe('played Sep 3 to 14')
  })

  it('leaves a name no other tile has, and unnamed tiles, alone', () => {
    for (const tile of tiles.slice(2)) {
      expect(tile.newest).toBe(false)
      expect(tile.playedRange).toBeNull()
    }
  })
})

describe('decksTiles, ties and one-day lists', () => {
  const NOW_LOCAL = new Date(2026, 8, 29, 12, 0, 0).getTime()

  it('gives the chip to the first in the API’s order when last_played is equal', () => {
    const same = { name: 'Azure Kites', first_played: '2026-09-03T20:00:00', last_played: '2026-09-14T20:00:00' }
    const tiles = decksTiles([identity('guid:a', ['v1'], same), identity('guid:b', ['v2'], same)], [], t, NOW_LOCAL)
    expect(tiles.map((tile) => tile.newest)).toEqual([true, false])
  })

  it('keeps “last played” for an older same-named list played on one day', () => {
    const tiles = decksTiles(
      [
        identity('guid:new', ['v1'], { name: 'Azure Kites', first_played: '2026-09-15T09:00:00', last_played: '2026-09-27T20:00:00' }),
        identity('guid:day', ['v2'], { name: 'Azure Kites', first_played: '2026-09-14T09:00:00', last_played: '2026-09-14T22:00:00' }),
        identity('guid:one', ['v3'], { name: 'Azure Kites', last_played: '2026-09-10T22:00:00' }),
      ],
      [],
      t,
      NOW_LOCAL,
    )
    expect(tiles.map((tile) => tile.newest)).toEqual([true, false, false])
    expect(tiles[1].playedRange).toBeNull()
    expect(tiles[2].playedRange).toBeNull()
    expect(tiles[1].lastPlayed).toBe(new Date(2026, 8, 14, 22, 0, 0).getTime())
  })
})

describe('tileDetail', () => {
  it('writes the format, and the versions when there are several', () => {
    expect(tileDetail('TraditionalStandard', 1, t)).toBe('Standard, best of three')
    // Between the count and its word a no-break space (U+00A0): they never
    // part on a narrow tile. The line may still break after the dot.
    expect(tileDetail('TraditionalStandard', 4, t)).toBe('Standard, best of three · 4\u00a0versions')
    expect(tileDetail(null, 4, t)).toBe('4\u00a0versions')
  })

  it('is null with no format and one version', () => {
    expect(tileDetail(null, 1, t)).toBeNull()
  })
})

describe('decksTiles', () => {
  const match = (id: string, deckId: string, startedAt: string, result: string | null) =>
    ({ match_id: id, deck_id: deckId, started_at: startedAt, result }) as Match

  const identities = [
    identity('guid:kites', ['v1', 'v2'], {
      name: 'Azure Kites',
      format: 'TraditionalStandard',
      matches: 10,
      match_wins: 6,
      match_losses: 3,
      last_played: '2026-09-27T20:00:00',
    }),
    identity('guid:none', ['v3'], { matches: 1 }),
  ]
  const matches = [
    match('in-progress', 'v2', '2026-09-28T11:00:00', null),
    match('older-loss', 'v2', '2026-09-10T20:00:00', 'loss'),
    match('newest-win', 'v1', '2026-09-20T20:00:00', 'win'),
    match('other-deck', 'v9', '2026-09-27T20:00:00', 'win'),
  ]
  const tiles = decksTiles(identities, matches, t)

  it('keeps the API’s order, one tile per deck', () => {
    expect(tiles.map((tile) => tile.key)).toEqual(['guid:kites', 'guid:none'])
  })

  it('counts wins and losses, draws aside, and writes the second line', () => {
    expect(tiles[0]).toMatchObject({
      name: 'Azure Kites',
      finished: 9,
      wins: 6,
      lastPlayed: new Date(2026, 8, 27, 20, 0, 0).getTime(),
      detail: 'Standard, best of three · 2\u00a0versions',
    })
  })

  it('takes the art from the deck’s newest finished match, never one in progress', () => {
    expect(tiles[0].artMatchId).toBe('newest-win')
  })

  it('marks no tile newest, and gives no range, when no name is shared', () => {
    expect(tiles.map((tile) => tile.newest)).toEqual([false, false])
    expect(tiles.map((tile) => tile.playedRange)).toEqual([null, null])
  })

  it('leaves a deck with no finished match in the list without art, name or line', () => {
    expect(tiles[1]).toMatchObject({ name: null, finished: 0, lastPlayed: null, detail: null, artMatchId: null })
  })
})

describe('sorting and filtering the tiles', () => {
  const NOW_LOCAL = new Date(2026, 8, 29, 12, 0, 0).getTime()
  const played = (day: number) => `2026-09-${String(day).padStart(2, '0')}T20:00:00`
  // Invented decks: wins/losses decide `finished` (ten or more is a rate).
  const tiles = decksTiles(
    [
      identity('a', ['va'], { format: 'Standard', match_wins: 6, match_losses: 4, last_played: played(10) }),
      identity('b', ['vb'], { format: 'TraditionalStandard', match_wins: 9, match_losses: 1, last_played: played(5) }),
      identity('c', ['vc'], { format: 'Standard', match_wins: 3, match_losses: 0, last_played: played(20) }),
      identity('d', ['vd'], { format: 'Pioneer', match_wins: 8, match_losses: 12, last_played: played(15) }),
      identity('e', ['ve'], { format: null, match_wins: 1, match_losses: 3, last_played: played(25) }),
      identity('f', ['vf'], { format: 'Pioneer', match_wins: 0, match_losses: 0, last_played: null }),
    ],
    [],
    t,
    NOW_LOCAL,
  )
  const keys = (list: { key: string }[]) => list.map((tile) => tile.key)

  it('sorts by last played, undated last', () => {
    expect(keys(sortTiles(tiles, 'lastPlayed'))).toEqual(['e', 'c', 'd', 'a', 'b', 'f'])
  })

  it('puts the tiles with a rate first by rate, then every other tile by last played', () => {
    // Rates: b 90%, a 60%, d 40%; the rest: e (25th), c (20th), f (undated).
    expect(keys(sortTiles(tiles, 'winRate'))).toEqual(['b', 'a', 'd', 'e', 'c', 'f'])
  })

  it('sorts by finished matches, ties by last played', () => {
    // Finished: d 20, a 10, b 10, e 4, c 3, f 0.
    expect(keys(sortTiles(tiles, 'matches'))).toEqual(['d', 'a', 'b', 'e', 'c', 'f'])
  })

  it('breaks a tie on Matches by last played, the earlier-played tile listed first', () => {
    const tied = decksTiles(
      [
        identity('old', ['v1'], { match_wins: 3, match_losses: 2, last_played: played(3) }),
        identity('new', ['v2'], { match_wins: 1, match_losses: 4, last_played: played(9) }),
      ],
      [],
      t,
      NOW_LOCAL,
    )
    expect(keys(sortTiles(tied, 'matches'))).toEqual(['new', 'old'])
  })

  it('keeps a tile of five to nine matches among the unrated, whatever its rate', () => {
    const rough = decksTiles(
      [
        identity('rough', ['v1'], { match_wins: 9, match_losses: 0, last_played: played(3) }),
        identity('rated', ['v2'], { match_wins: 5, match_losses: 5, last_played: played(2) }),
        identity('none', ['v3'], { match_wins: 0, match_losses: 0, last_played: played(9) }),
      ],
      [],
      t,
      NOW_LOCAL,
    )
    expect(keys(sortTiles(rough, 'winRate'))).toEqual(['rated', 'none', 'rough'])
  })

  it('breaks a tie on rate by last played, the earlier-played tile listed first', () => {
    const same = decksTiles(
      [
        identity('old', ['v1'], { match_wins: 5, match_losses: 5, last_played: played(3) }),
        identity('new', ['v2'], { match_wins: 10, match_losses: 10, last_played: played(9) }),
      ],
      [],
      t,
      NOW_LOCAL,
    )
    expect(keys(sortTiles(same, 'winRate'))).toEqual(['new', 'old'])
  })

  it('does not change the list it is given', () => {
    const before = keys(tiles)
    sortTiles(tiles, 'matches')
    expect(keys(tiles)).toEqual(before)
  })

  it('reads an unknown sort as last played', () => {
    expect(chosenSort('winRate')).toBe('winRate')
    expect(chosenSort('nonsense')).toBe('lastPlayed')
    expect(chosenSort(null)).toBe('lastPlayed')
  })

  it('lists each format present once, none for an unknown one', () => {
    expect(tileFormats(tiles)).toEqual(['Standard', 'TraditionalStandard', 'Pioneer'])
  })

  it('keeps the tiles of a format, all with none, and none for a stale one', () => {
    expect(keys(filterTiles(tiles, 'Pioneer'))).toEqual(['d', 'f'])
    expect(filterTiles(tiles, null)).toHaveLength(6)
    expect(filterTiles(tiles, '')).toHaveLength(6)
    expect(filterTiles(tiles, 'Modern')).toEqual([])
  })
})
