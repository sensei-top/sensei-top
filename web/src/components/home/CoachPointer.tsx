import { Button, Card } from '../ui'

/** The coach on Home is a pointer: what it is, and the way there. Home
 *  never asks the coach's own routes for anything. */
export function CoachPointer() {
  return (
    <Card title="Coach" className="flex flex-col">
      <p className="text-body text-ink2">
        A report across every deck you play: what keeps happening, where lost games turn, and what to read next. It
        is written when you ask for it.
      </p>
      <div className="mt-4">
        <Button href="/coach">Open the coach</Button>
      </div>
    </Card>
  )
}
