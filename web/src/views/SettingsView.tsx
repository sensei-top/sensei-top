import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Shell } from '../bridge'
import { AccountSection } from '../components/settings/AccountSection'
import { AppSection } from '../components/settings/AppSection'
import { BackupSection } from '../components/settings/BackupSection'
import { ContributeSection } from '../components/settings/ContributeSection'
import { SourcesSection } from '../components/settings/SourcesSection'
import { useAi } from '../ai/registry'
import { inGroup, type SettingsGroupId, type WritingStatusAnswer } from '../lib/settings'

/** Settings, as sections under their titles: Sources, Writing, Backup and
 *  App and Account (the last only in a build that has an account), then `children`, the sections that belong to the browser rather
 *  than to a shell (the density control, the credits), which the page
 *  draws itself. The one place that holds a `Shell` and hands each section
 *  its part of the settings and the functions it calls. With no shell,
 *  Sources, Backup and App are not drawn and Writing is what the API says,
 *  as sentences, with no control. With `group`, only the sections
 *  `groupOfHash` puts in it are drawn. */
export function SettingsView({
  shell,
  writing,
  group,
  children,
}: {
  shell: Shell | null
  writing: WritingStatusAnswer
  group?: SettingsGroupId
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const ai = useAi()
  const shows = (section: string) => inGroup(section, group)
  return (
    <div className="space-y-10">
      {shell && shows('sources') && (
        <SettingsSection id="sources" title={t('settings.sections.sources')}>
          <SourcesSection
            sources={shell.settings.sources}
            save={(change) => shell.save({ sources: change })}
            pickFolder={() => shell.pickFolder()}
            topdeck={{ set: shell.settings.writing.topdeckKey, setKey: (which, key) => shell.setKey(which, key) }}
            showDataFolder={shell.app && (() => shell.app!.showDataFolder())}
            app={
              shell.app && {
                rulesText: shell.app.settings.rulesText,
                firstData: shell.app.settings.firstData,
                startFirstData: () => shell.app!.firstData(),
              }
            }
          />
        </SettingsSection>
      )}
      {ai && shows('writing') && (
        <SettingsSection id="writing" title={t('settings.sections.writing')}>
          {shell ? (
            <ai.WritingSection
              writing={shell.settings.writing}
              save={(change) => shell.save({ writing: change })}
              setKey={(which, key) => shell.setKey(which, key)}
            />
          ) : (
            <ai.WritingStatus answer={writing} />
          )}
        </SettingsSection>
      )}
      {shell && shows('backup') && (
        <SettingsSection id="backup" title={t('settings.sections.backup')}>
          <BackupSection
            backup={shell.settings.backup}
            save={(change) => shell.save({ backup: change })}
            pickFolder={() => shell.pickFolder()}
            pickFile={() => shell.pickFile()}
            backUpNow={() => shell.backUpNow()}
            restoreFrom={(path) => shell.restoreFrom(path)}
          />
        </SettingsSection>
      )}
      {shell?.app && shows('app') && (
        <SettingsSection id="app" title={t('settings.sections.app')}>
          <AppSection
            app={shell.app.settings}
            set={(change) => shell.app!.set(change)}
            checkForUpdates={() => shell.app!.checkForUpdates()}
            restartToUpdate={() => shell.app!.restartToUpdate()}
            showLogs={() => shell.app!.showLogs()}
            exportDiagnostics={() => shell.app!.exportDiagnostics()}
          />
        </SettingsSection>
      )}
      {shell?.app?.settings.account.available && shows('account') && (
        <SettingsSection id="account" title={t('account.settings.title')}>
          <AccountSection state={shell.app.settings.account} actions={shell.app.account} />
        </SettingsSection>
      )}
      {shell?.app?.settings.canContribute && shows('contribute') && (
        <SettingsSection id="contribute" title={t('contribute.heading')}>
          <ContributeSection shell={shell} />
        </SettingsSection>
      )}
      {children}
    </div>
  )
}

/** One section of the page: its title as an `h2`, then its cards. */
function SettingsSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-4">
      <h2 id={id} className="font-display text-title text-ink">
        {title}
      </h2>
      {children}
    </section>
  )
}
