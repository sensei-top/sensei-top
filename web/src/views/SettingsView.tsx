import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Shell } from '../bridge'
import { AppSection } from '../components/settings/AppSection'
import { BackupSection } from '../components/settings/BackupSection'
import { SourcesSection } from '../components/settings/SourcesSection'
import { WritingSection, WritingStatus, type WritingStatusAnswer } from '../components/settings/WritingSection'

/** Settings, as sections under their titles: Sources, Writing, Backup and
 *  App, then `children`, the sections that belong to the browser rather
 *  than to a shell (the density control, the credits), which the page
 *  draws itself. The one place that holds a `Shell` and hands each section
 *  its part of the settings and the functions it calls. With no shell,
 *  Sources, Backup and App are not drawn and Writing is what the API says,
 *  as sentences, with no control. */
export function SettingsView({
  shell,
  writing,
  children,
}: {
  shell: Shell | null
  writing: WritingStatusAnswer
  children?: ReactNode
}) {
  const { t } = useTranslation()
  return (
    <div className="space-y-10">
      {shell && (
        <SettingsSection id="sources" title={t('settings.sections.sources')}>
          <SourcesSection
            sources={shell.settings.sources}
            save={(change) => shell.save({ sources: change })}
            pickFolder={() => shell.pickFolder()}
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
      <SettingsSection id="writing" title={t('settings.sections.writing')}>
        {shell ? (
          <WritingSection
            writing={shell.settings.writing}
            save={(change) => shell.save({ writing: change })}
            setKey={(which, key) => shell.setKey(which, key)}
          />
        ) : (
          <WritingStatus answer={writing} />
        )}
      </SettingsSection>
      {shell && (
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
      {shell?.app && (
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
