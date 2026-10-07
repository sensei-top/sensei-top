import { useFieldParams } from '../lib/field'
import { FieldView } from '../views/FieldView'

/** `/field`: reads `?format=`, `?window=`, `?tier=` and `?pairs=` from the
 *  address and hands them to the view, which knows their defaults once the
 *  formats, the status and the lists have answered. A bare `/field` stays
 *  bare. */
export function FieldPage() {
  const { params, setParam } = useFieldParams()
  return <FieldView params={params} setParam={setParam} />
}
