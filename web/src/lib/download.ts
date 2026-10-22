/** Hand the browser a Markdown document to save under `fileName`. The
 *  RCQ guide and the deck guide's export both save their `.md` this way. */
export function saveMarkdown(text: string, fileName: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  // Let go of the file once the browser has started saving it.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
