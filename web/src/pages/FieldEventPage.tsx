import { useParams } from 'react-router'
import { FieldEventView } from '../views/FieldEventView'

/** `/field/events/<key>`: the key is the API's, slashes included; React
 *  Router has decoded each segment of the splat. */
export function FieldEventPage() {
  return <FieldEventView eventKey={useParams()['*']} />
}
