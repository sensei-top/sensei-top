import type { ReactNode } from 'react'
import type { Shell } from '../bridge'
import { BackupSection } from '../components/settings/BackupSection'
import { SharingSection } from '../components/settings/SharingSection'
import { SourcesSection } from '../components/settings/SourcesSection'
import { WritingSection, WritingStatus, type WritingStatusAnswer } from '../components/settings/WritingSection'

/** Settings, as sections under their titles: Sources, Writing, Backup
 *  and Draft data, then `children`, the sections that belong to the
 *  browser rather than to a shell (the density control, the credits),
 *  which the page draws itself. The one place that holds a `Shell` and
 *  hands each section its part of the settings and the functions it
 *  calls. With no shell, Sources, Backup and Draft data are not drawn and
 *  Writing is what the API says, as sentences, with no control. Draft
 *  data is drawn only when the shell offers sharing. `payloadHref` is
 *  where a draft's payload is shown, given the draft's id; with none,
 *  Draft data links to nothing. */
export function SettingsView({
  shell,
  writing,
  payloadHref,
  children,
}: {
  shell: Shell | null
  writing: WritingStatusAnswer
  payloadHref?: (draftId: string) => string
  children?: ReactNode
}) {
  const sharing = shell?.settings.sharing ?? null
  return (
    <div className="space-y-10">
      {shell && (
        <SettingsSection id="sources" title="Sources">
          <SourcesSection
            sources={shell.settings.sources}
            save={(change) => shell.save({ sources: change })}
            pickFolder={() => shell.pickFolder()}
          />
        </SettingsSection>
      )}
      <SettingsSection id="writing" title="Writing">
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
        <SettingsSection id="backup" title="Backup">
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
      {shell && sharing && (
        <SettingsSection id="draft-data" title="Draft data">
          <SharingSection
            sharing={sharing}
            payloadHref={sharing.lastDraft !== null && payloadHref ? payloadHref(sharing.lastDraft) : undefined}
            setSharing={(on) => shell.setSharing(on)}
            newInstallation={() => shell.newInstallation()}
            deleteContributions={() => shell.deleteContributions()}
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
