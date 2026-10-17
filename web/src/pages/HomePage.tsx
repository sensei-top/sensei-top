import { useShell } from '../bridge'
import { detailedLogsNag, mtgoOnly } from '../lib/home'
import { HomeView } from '../views/HomeView'

/** `/`: Home, over every source and with no filter, so a player with no
 *  Arena match still opens a page with their own on it. One deck's own
 *  record, over any of its versions, is on its Overview
 *  (`DeckOverviewView`). The shell, where there is one, decides whether the
 *  Detailed Logs banner shows; the browser path has none. */
export function HomePage() {
  const shell = useShell()
  const app = shell?.app
  const banner =
    shell && app && detailedLogsNag(shell.settings.sources, app.settings.plays)
      ? { detailedLogs: shell.settings.sources.arenaLog.detailedLogs, recheck: () => app.recheck() }
      : null
  const first =
    shell && app
      ? { banner, mtgoOnly: mtgoOnly(app.settings.plays), mtgoDir: shell.settings.sources.mtgoDir }
      : undefined
  return <HomeView detailedLogs={banner} firstRun={first} />
}
