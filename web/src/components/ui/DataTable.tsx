import type { ReactNode } from 'react'

/** Every chart ships with its numbers in a table: the accessible view, and
 *  (dark-only now) simply good practice for a number worth checking exactly.
 *  Every column after the first is right-aligned and keeps a gap on its
 *  left, so no two columns touch at any width, headers included. */
export function DataTable({
  columns,
  rows,
}: {
  columns: string[]
  // ReactNode, not just text: a cell may carry a control of its own, such
  // as the opponent's deck with the way to correct it.
  rows: ReactNode[][]
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-body tabular-nums">
        <thead>
          <tr className="border-b border-line2 text-left">
            {columns.map((column, index) => (
              <th
                key={column}
                className={`pb-2 text-caption font-medium text-muted ${
                  index === 0 ? '' : 'pl-4 text-right'
                }`}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-b border-line last:border-0 hover:bg-surface2">
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className={`py-2.25 ${cellIndex === 0 ? 'text-ink' : 'pl-4 text-right text-ink2'}`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
