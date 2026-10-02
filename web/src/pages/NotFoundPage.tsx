import { Button, EmptyState } from '../components/ui'

/** Any address that is no place. The shell's `h1` already reads "No such
 *  page", so the empty state carries no title of its own. */
export function NotFoundPage() {
  return (
    <EmptyState
      message="Nothing is at this address."
      action={
        <Button variant="primary" href="/">
          Go to Home
        </Button>
      }
    />
  )
}
