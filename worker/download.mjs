// /download/windows and /download/linux redirect to that platform's file in
// the newest release, read from the same latest.yml / latest-linux.yml an
// installed copy's updater reads: GitHub's `releases/latest/download/<name>`
// needs a name without a version in it, and the installers carry theirs
// (desktop/electron-builder.yml). A release is published with every asset in
// one command, so the feed moves only once the file it names exists. If
// GitHub cannot be reached, or the feed is not what it should be, the
// redirect goes to the releases page instead.
//
// /download/linux-tar is the exception: no feed lists the tarball (it writes no
// update info, so latest-linux.yml keeps naming the AppImage), so its name is
// built from the feed's version, checked as the others' is. What keeps that
// name pointing at a real file: the release job won't publish without a
// Sensei-Top-*.tar.gz, and attaches it in the same `gh release create` as the
// feed (.github/workflows/desktop.yml). Without that check, this route would
// send a visitor to GitHub's 404 page instead of the releases page.

export const RELEASES = 'https://github.com/sensei-top/sensei-top/releases'

export const PLATFORMS = {
  windows: { feed: 'latest.yml', extension: '.exe' },
  linux: { feed: 'latest-linux.yml', extension: '.AppImage' },
  'linux-tar': { feed: 'latest-linux.yml', name: (version) => `Sensei-Top-${version}.tar.gz` },
}

/**
 * The file's address in its release, or null when the feed is not one we expect.
 * With `build`, the file is built from the version instead of read from `path:`.
 */
export function fileUrl(feed, extension, build) {
  const field = (name) => feed.match(new RegExp(`^${name}: *'?([^'\\s]+)'? *$`, 'm'))?.[1]
  const version = field('version')
  if (!version || !/^\d+\.\d+\.\d+$/.test(version)) return null
  if (build) return `${RELEASES}/download/v${version}/${build(version)}`
  const path = field('path')
  if (!path || !/^[A-Za-z0-9._-]+$/.test(path) || !path.endsWith(extension)) return null
  return `${RELEASES}/download/v${version}/${path}`
}

export async function newest(platform) {
  try {
    const response = await fetch(`${RELEASES}/latest/download/${platform.feed}`)
    if (response.ok) return fileUrl(await response.text(), platform.extension, platform.name) ?? `${RELEASES}/latest`
  } catch {
    // Fall through to the releases page.
  }
  return `${RELEASES}/latest`
}

/** The redirect for a /download/<platform> path, or null for any other path. */
export async function download(request) {
  const name = new URL(request.url).pathname.match(/^\/download\/([a-z-]+)$/)?.[1]
  const platform = Object.hasOwn(PLATFORMS, name ?? '') ? PLATFORMS[name] : null
  if (!platform) return null
  return new Response(null, {
    status: 302,
    headers: { Location: await newest(platform), 'Cache-Control': 'no-store' },
  })
}
