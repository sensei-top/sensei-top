import { useTranslation } from 'react-i18next'
import { Navigate, NavLink, Outlet, useLocation } from 'react-router'
import { useShell } from '../bridge'
import { SETTINGS_GROUPS, settingsRedirect, shownGroups, type SettingsBuild } from '../lib/settings'

/** The layout Settings' groups share: the groups this build shows as a
 *  vertical list on the left, the group's page on the right. Bare
 *  `/settings`, and a group this build does not show, go on to another
 *  group in place of the history entry (`settingsRedirect`); the hash goes
 *  with a bare `/settings`, and the shell's `ScrollRestoration` scrolls its
 *  section into view once the group renders. */
export function SettingsLayout() {
  const { t } = useTranslation()
  const { pathname, hash } = useLocation()
  const shell = useShell()
  const build: SettingsBuild = { shell: shell !== null, account: shell?.app?.settings.account.available === true }

  const redirect = settingsRedirect(pathname, hash, build)
  if (redirect != null) return <Navigate replace to={redirect} />

  const shown = shownGroups(build)
  return (
    <div className="flex items-start gap-8">
      <nav aria-label={t('shell.places.settings')} className="flex w-40 shrink-0 flex-col gap-1">
        {SETTINGS_GROUPS.filter((group) => shown.includes(group.id)).map((group) => (
          // NavLink marks the current one with aria-current="page" itself.
          <NavLink
            key={group.id}
            to={group.id}
            className={({ isActive }) =>
              `rounded-control px-3 py-1.5 text-caption font-medium transition-chrome ${
                isActive ? 'bg-surface3 text-ink' : 'text-muted hover:text-ink'
              }`
            }
          >
            {t(group.label)}
          </NavLink>
        ))}
      </nav>
      <div className="min-w-0 flex-1">
        <Outlet />
      </div>
    </div>
  )
}
