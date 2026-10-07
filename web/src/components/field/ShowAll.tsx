import { formatCount } from '../../lib/time'
import { Button } from '../ui'

/** The quiet button under a cut list: "Show all 55". The caller draws it
 *  only while rows are held back, and it goes once pressed. */
export function ShowAll({ total, onShow }: { total: number; onShow: () => void }) {
  return (
    <div className="mt-3">
      <Button variant="quiet" className="min-h-[44px]" onClick={onShow}>
        {`Show all ${formatCount(total)}`}
      </Button>
    </div>
  )
}
