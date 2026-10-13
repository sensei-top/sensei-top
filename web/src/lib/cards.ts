import type { CurrentCardEvent } from '../api'
import type { TFunction } from '../i18n'

/**
 * Never show a grpId. A raw number tells the reader nothing, and there is no
 * case where it is the best available answer: either we know the card, or we
 * do not and should say so. A card hidden from us carries no id at all; an id
 * with no name is either Arena's face-down placeholder or a card the local
 * table has not been refreshed for, and "unknown" covers both honestly.
 */
export function cardName(event: Pick<CurrentCardEvent, 'card_name' | 'grp_id'>, t: TFunction): string {
  if (event.card_name) return event.card_name
  return event.grp_id == null ? t('common.card.hidden') : t('common.card.unknown')
}
