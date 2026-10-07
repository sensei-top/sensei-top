import type { ReactNode } from 'react'
import type { CurrentTurn, TurnZoneCard } from '../api'
import { cardName } from '../lib/cards'
import { CardImage } from './CardImage'
import { Button, CardTile, Chip, EmptyState, SectionLabel } from './ui'

/**
 * One turn's board, arranged the way a 1v1 Magic table actually is.
 *
 * The layout is not decorative — it follows the tournament rules for a real
 * table (MTR 4.7), which is what makes it readable without labels:
 *
 *   - Mirror symmetry across a center line. The opponent's half is yours
 *     rotated 180 degrees, so "far side" always means "theirs".
 *   - Within a half, outward edge inward: hand, then lands, then nonlands.
 *     MTR 4.7: "nonlands must be kept closer to the player's opponent than
 *     lands, and no non-land cards should be between the land area and the
 *     edge of the table closest to the player." So both nonland rows end up
 *     adjacent to the center line, where combat would happen.
 *   - Library, graveyard and exile are one flanking column per half, adjacent
 *     to each other and "distinct at all times".
 *   - Tapped is a 90-degree rotation. It is Magic's only rules-sanctioned
 *     orientation signal, and the fastest read on a board.
 *
 * Everything drawn here is stored state. Counters, attackers and blockers are
 * absent because Arena's log gives us no testable way to know them — see
 * docs/arena-log.md. Nothing is inferred to fill those gaps.
 *
 * What is known about a card is written under it, in a caption as
 * `CardTile` writes one: power and toughness, `New` for a permanent that
 * entered this turn, `Drawn` for a card drawn this turn. Nothing is drawn
 * over a picture or around it, and a line under the board says what each
 * word means when some card carries it.
 */

/** Card width, in px, at every width of the page. Slots are sized from this
 *  so a turned card occupies its turned bounding box instead of overlapping
 *  its neighbours. */
const CARD_W = 64
const CARD_H = Math.round((CARD_W * 680) / 488)

/** The caption's classes, `CardTile`'s own: one line kept whether or not a
 *  card has a caption, so a row's cards line up. */
const CAPTION = 'mt-1.5 min-h-5.5 text-caption tabular-nums text-ink'

const has = (card: TurnZoneCard, type: string) => (card.card_types ?? '').includes(type)
const isLand = (card: TurnZoneCard) => has(card, 'Land')

/** Presentation order within the nonland row, mirroring where Arena puts each
 *  kind: creatures toward the center, then planeswalkers and battles, then the
 *  static permanents. Ordering only — it invents no data. */
const NONLAND_ORDER = ['Creature', 'Planeswalker', 'Battle', 'Artifact', 'Enchantment']
const nonlandRank = (card: TurnZoneCard) => {
  const found = NONLAND_ORDER.findIndex((type) => has(card, type))
  return found === -1 ? NONLAND_ORDER.length : found
}

/** A permanent in play: a slot of its own, turned a quarter when tapped, and
 *  a caption under the slot with its power and toughness and `New` when it
 *  entered this turn. A screen reader hears "tapped" too. */
function Permanent({ card, entered }: { card: TurnZoneCard; entered: boolean }) {
  const name = cardName(card)
  const tapped = card.is_tapped === true
  const pt = card.power != null && card.toughness != null ? `${card.power}/${card.toughness}` : null
  const caption = [pt, entered ? 'New' : null].filter((part): part is string => part != null).join(' · ')
  // Turning swaps the bounding box, so the slot swaps with it; the picture
  // keeps its own size and is centred in the slot.
  const slot = tapped ? { width: CARD_H, height: CARD_W } : { width: CARD_W, height: CARD_H }

  return (
    <figure className="shrink-0" style={{ width: slot.width }}>
      <span className="flex items-center justify-center" style={slot}>
        <span className={`flex shrink-0 ${tapped ? 'rotate-90' : ''}`} style={{ width: CARD_W, height: CARD_H }}>
          <CardImage grpId={card.grp_id} name={name} className="h-full w-full rounded-control object-contain" />
        </span>
      </span>
      <figcaption className={CAPTION}>
        {caption}
        {tapped && <span className="sr-only"> tapped</span>}
      </figcaption>
    </figure>
  )
}

/** A row's label and its cards: the label beside the cards from 48rem, over
 *  them under it, so it never shares a line with them on a phone. */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 md:flex-row md:items-center md:gap-3">
      <SectionLabel as="span" className="md:w-12 md:shrink-0 md:text-right">
        {label}
      </SectionLabel>
      {children}
    </div>
  )
}

/** One battlefield row. Scrolls inside itself so a wide board never makes the
 *  page scroll sideways; a row with no card keeps a card's height. */
function BattlefieldRow({
  label,
  cards,
  entered,
}: {
  label: string
  cards: TurnZoneCard[]
  entered: Set<number>
}) {
  return (
    <Row label={label}>
      {/* `relative` keeps a tapped card's visually hidden word inside the
          scroller; without it the word is laid out against the page and
          widens it. */}
      <div
        className={`relative flex min-w-0 flex-1 gap-1.5 overflow-x-auto ${cards.length === 0 ? 'items-center' : 'items-end'}`}
        style={{ minHeight: CARD_H }}
      >
        {cards.length === 0 ? (
          <span className="text-caption text-muted">None</span>
        ) : (
          cards.map((card) => (
            <Permanent key={card.instance_id} card={card} entered={entered.has(card.instance_id)} />
          ))
        )}
      </div>
    </Row>
  )
}

/** A card in a hand that is hidden from us, among cards that are not: the
 *  same placeholder the backs are, with an empty caption so the row's
 *  cards line up. */
function HiddenInHand({ card }: { card: TurnZoneCard }) {
  return (
    <figure className="flex shrink-0 flex-col" style={{ width: CARD_W }}>
      <CardImage grpId={null} name={cardName(card)} className="aspect-[488/680] w-full rounded-control" />
      <figcaption className={CAPTION} />
    </figure>
  )
}

/**
 * A hand. Ours shows faces; theirs shows backs, because Arena omits the game
 * object for a card we may not see — the rows exist, the identities do not.
 * A hand of backs alone overlaps them into a fan, since they carry nothing
 * one by one, with the count in words beside it. A hand wraps.
 */
function Hand({ cards, drawnOnTurn }: { cards: TurnZoneCard[]; drawnOnTurn?: number }) {
  const hidden = cards.length > 0 && cards.every((card) => card.grp_id == null)
  return (
    <Row label="Hand">
      {cards.length === 0 ? (
        <div className="flex flex-1 items-center" style={{ minHeight: CARD_H }}>
          <span className="text-caption text-muted">Empty</span>
        </div>
      ) : hidden ? (
        <div className="flex flex-1 items-center gap-3">
          <div className="flex shrink-0 items-center">
            {cards.map((card, index) => (
              <span
                key={card.instance_id}
                className="flex shrink-0"
                style={{ width: CARD_W, marginLeft: index > 0 ? -CARD_W * 0.55 : 0 }}
              >
                <CardImage grpId={null} name={cardName(card)} className="aspect-[488/680] w-full rounded-control" />
              </span>
            ))}
          </div>
          <span className="text-caption text-muted">{cards.length} hidden</span>
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 flex-wrap items-start gap-1.5">
          {cards.map((card) =>
            card.grp_id == null ? (
              <HiddenInHand key={card.instance_id} card={card} />
            ) : (
              <CardTile key={card.instance_id} grpId={card.grp_id} name={cardName(card)} width={CARD_W}>
                {drawnOnTurn != null && card.drawn_on_turn === drawnOnTurn ? 'Drawn' : null}
              </CardTile>
            ),
          )}
        </div>
      )}
    </Row>
  )
}

/** One of the piles: a quiet button when it holds cards to show, which
 *  opens them under the half; a line of text otherwise. */
function Pile({
  label,
  count,
  open = false,
  onToggle,
}: {
  label: string
  count: number | null | undefined
  open?: boolean
  /** Given only when the pile holds cards to show. */
  onToggle?: () => void
}) {
  const shown = count ?? '—'
  if (!onToggle) {
    return (
      <div className="flex h-8 items-center justify-between gap-2 px-3 text-caption md:w-full">
        <span className="text-muted">{label}</span>
        <span className="font-medium tabular-nums text-ink">{shown}</span>
      </div>
    )
  }
  return (
    <Button variant="quiet" size="sm" aria-expanded={open} onClick={onToggle} className="md:w-full">
      <span className="flex w-full items-center justify-between gap-2">
        <span>{label}</span>
        <span className="tabular-nums text-ink">{shown}</span>
      </span>
    </Button>
  )
}

/** Where each part of a half sits: its order in the one column under 48rem,
 *  and its row of the two-column grid from 48rem. */
const ORDER = ['', 'order-1', 'order-2', 'order-3', 'order-4', 'order-5', 'order-6']
const MD_ROW = ['', 'md:row-start-1', 'md:row-start-2', 'md:row-start-3', 'md:row-start-4', 'md:row-start-5', 'md:row-start-6']

/** One player's half: a rail with life, the rows, the piles and, when one
 *  is open, the pile's cards.
 *
 *  From 48rem the rows and the rail are the left column and the piles a
 *  column at the right, beside the rows. An open pile is a block of the
 *  half's width: under the opponent's rows, over yours, so it stays beside
 *  the piles. Under 48rem everything is one column, the piles a line under
 *  the rail and an open pile's block right under that line. */
function Half({
  who,
  life,
  library,
  graveyard,
  exile,
  hand,
  lands,
  nonlands,
  entered,
  drawnOnTurn,
  active,
  openPile,
  onOpenPile,
  reversed,
}: {
  who: 'You' | 'Opponent'
  life: number | null | undefined
  library: number | null | undefined
  graveyard: TurnZoneCard[]
  exile: TurnZoneCard[]
  hand: TurnZoneCard[]
  lands: TurnZoneCard[]
  nonlands: TurnZoneCard[]
  entered: Set<number>
  drawnOnTurn?: number
  active: boolean
  openPile: string | null
  onOpenPile: (pile: string | null) => void
  /** True for your half, which stacks nonlands → lands → hand so the nonland
   *  row ends up against the center line on both sides. */
  reversed: boolean
}) {
  const key = (pile: string) => `${who}:${pile}`
  const toggle = (pile: string) => onOpenPile(openPile === key(pile) ? null : key(pile))
  const opened =
    openPile === key('graveyard') && graveyard.length > 0 ? { pile: 'graveyard', cards: graveyard }
    : openPile === key('exile') && exile.length > 0 ? { pile: 'exile', cards: exile }
    : null
  const heading = opened
    ? who === 'You'
      ? opened.pile === 'graveyard' ? 'Your graveyard' : 'Your exile'
      : opened.pile === 'graveyard' ? "The opponent's graveyard" : "The opponent's exile"
    : ''

  // Each part's place: [order under 48rem, grid row from 48rem]. Yours
  // runs the other way, and its rows move down one when a pile is open.
  const shift = opened ? 1 : 0
  const place = reversed
    ? { board: [1, 1 + shift], lands: [2, 2 + shift], hand: [3, 3 + shift], rail: [4, 4 + shift], piles: [5, 1 + shift], block: [6, 1] }
    : { rail: [1, 1], hand: [4, 2], lands: [5, 3], board: [6, 4], piles: [2, 1], block: [3, 5] }
  const at = ([order, row]: number[]) => `${ORDER[order]} ${MD_ROW[row]}`

  return (
    <div className="flex flex-col gap-2 md:grid md:grid-cols-[minmax(0,1fr)_10rem] md:gap-x-4">
      <div className={`flex items-center gap-2 md:col-start-1 ${at(place.rail)}`}>
        <span aria-hidden className={`inline-block size-2 rounded-pill ${who === 'You' ? 'bg-s1' : 'bg-s2'}`} />
        <span className="text-chip font-semibold tracking-label text-ink">{who}</span>
        {active && <Chip size="sm">Active</Chip>}
        <span className="ml-auto text-body font-semibold tabular-nums text-ink">
          {life ?? '—'} <span className="text-caption font-normal text-muted">life</span>
        </span>
      </div>
      <div className={`md:col-start-1 ${at(place.hand)}`}>
        <Hand cards={hand} drawnOnTurn={drawnOnTurn} />
      </div>
      <div className={`md:col-start-1 ${at(place.lands)}`}>
        <BattlefieldRow label="Lands" cards={lands} entered={entered} />
      </div>
      <div className={`md:col-start-1 ${at(place.board)}`}>
        <BattlefieldRow label="Board" cards={nonlands} entered={entered} />
      </div>
      {/* MTR 4.7: library, graveyard and exile all to one side of the
          battlefield, adjacent, and distinct at all times. */}
      <div
        className={`flex flex-wrap gap-1 md:col-start-2 md:row-span-4 md:flex-col md:flex-nowrap md:self-start ${at(place.piles)}`}
      >
        <Pile label="Library" count={library} />
        <Pile
          label="Graveyard"
          count={graveyard.length}
          open={opened?.pile === 'graveyard'}
          onToggle={graveyard.length > 0 ? () => toggle('graveyard') : undefined}
        />
        <Pile
          label="Exile"
          count={exile.length}
          open={opened?.pile === 'exile'}
          onToggle={exile.length > 0 ? () => toggle('exile') : undefined}
        />
      </div>
      {opened && (
        <div className={`rounded-block bg-surface2 p-3 md:col-span-2 md:col-start-1 ${at(place.block)}`}>
          <SectionLabel className="mb-2">{heading}</SectionLabel>
          <div className="flex flex-wrap items-start gap-1.5">
            {opened.cards.map((card) => (
              <CardTile key={card.instance_id} grpId={card.grp_id} name={cardName(card)} width={CARD_W} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function BoardTable({
  turn,
  prev,
  selfSeat,
  openPile,
  onOpenPile,
}: {
  turn: CurrentTurn
  /** The previous turn's snapshot, used to say what entered play. */
  prev: CurrentTurn | undefined
  selfSeat: number | null | undefined
  openPile: string | null
  onOpenPile: (pile: string | null) => void
}) {
  const zones = turn.zones ?? []

  // is_self is null when Arena never named our seat, which happens on a
  // truncated session. Comparing with === would drop every card from both
  // halves; say so instead.
  const unattributed = zones.length > 0 && zones.every((card) => card.is_self == null)

  const pick = (zone: string, mine: boolean) =>
    zones.filter((card) => card.zone === zone && card.is_self === mine)
  const battlefield = (mine: boolean) => pick('battlefield', mine)
  const nonlands = (mine: boolean) =>
    battlefield(mine)
      .filter((card) => !isLand(card))
      .sort((a, b) => nonlandRank(a) - nonlandRank(b))

  // Anything on the battlefield now that was not there last turn entered play
  // this turn. Two stored snapshots compared — nothing inferred.
  const before = new Set((prev?.zones ?? []).map((card) => card.instance_id))
  const entered = new Set(
    zones.filter((card) => card.zone === 'battlefield' && !before.has(card.instance_id))
      .map((card) => card.instance_id),
  )
  // On the very first turn there is no previous snapshot, so everything would
  // read as "entered" — which is true but not worth saying.
  const enteredMarks = prev ? entered : new Set<number>()

  const active = (mine: boolean) =>
    turn.active_seat != null && selfSeat != null && (turn.active_seat === selfSeat) === mine

  if (unattributed) {
    return (
      <EmptyState message="Arena never said which seat was yours in this session, so the two sides cannot be told apart. The cards were recorded; whose they were was not." />
    )
  }

  // The legend says only what the board shows: a word is explained when some
  // card carries it. Only your own hand says what was drawn.
  const anyNew = zones.some((card) => card.zone === 'battlefield' && card.is_self != null && enteredMarks.has(card.instance_id))
  const anyDrawn = pick('hand', true).some((card) => card.grp_id != null && card.drawn_on_turn === turn.turn_number)

  return (
    <div>
      <Half
        who="Opponent"
        life={turn.opp_life}
        library={turn.opp_library}
        graveyard={pick('graveyard', false)}
        exile={pick('exile', false)}
        hand={pick('hand', false)}
        lands={battlefield(false).filter(isLand)}
        nonlands={nonlands(false)}
        entered={enteredMarks}
        active={active(false)}
        openPile={openPile}
        onOpenPile={onOpenPile}
        reversed={false}
      />

      {/* The center line. Combat would happen here; both nonland rows sit
          against it, which is what the MTR layout produces. */}
      <div className="my-3 border-t-2 border-edge" />

      <Half
        who="You"
        life={turn.self_life}
        library={turn.self_library}
        graveyard={pick('graveyard', true)}
        exile={pick('exile', true)}
        hand={pick('hand', true)}
        lands={battlefield(true).filter(isLand)}
        nonlands={nonlands(true)}
        entered={enteredMarks}
        drawnOnTurn={turn.turn_number}
        active={active(true)}
        openPile={openPile}
        onOpenPile={onOpenPile}
        reversed
      />

      {(anyNew || anyDrawn) && (
        <div className="mt-3 space-y-0.5 text-caption text-muted">
          {anyNew && <p>New: it entered the battlefield this turn.</p>}
          {anyDrawn && <p>Drawn: you drew it this turn.</p>}
        </div>
      )}
    </div>
  )
}
