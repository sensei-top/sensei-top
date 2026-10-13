import { useState, type ReactNode } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import type { AppChange, AppSettings, DeepPartial, FirstDataProgress, Saved, ShellSettings } from '../bridge'
import { RestoreButton } from '../components/settings/BackupSection'
import { FolderField, PressButton, RestartNote, SaveButton, SavingSwitch } from '../components/settings/SaveButton'
import { Button, Card, Field, Meter, SectionLabel, Segmented, TextLink } from '../components/ui'
import { useLanguage, type TFunction } from '../i18n'
import { failureOf, settle, useRestart, useTextSave } from '../lib/settings'
import { formatCount } from '../lib/time'
import { WELCOME_STEPS, agePhrase, neighbour, stepHref, stepNumber, withStop, type WelcomeStep } from '../lib/welcome'

type Sources = ShellSettings['sources']

/** What the metagame status says of the two background downloads, in hours
 *  since each ran (`null` when it has not). */
export type DownloadAges = { archetypeHours: number | null; corpusHours: number | null }

/** The status as the page has it: loading, failed, or the two ages. */
export type DownloadsAnswer = 'loading' | 'failed' | DownloadAges

/** The shell's functions the steps call, each of which the page passes
 *  through from `useShell()`. */
export type WelcomeActions = {
  set(change: AppChange): Promise<Saved>
  recheck(): Promise<Saved>
  firstData(): Promise<Saved>
  finishOnboarding(): Promise<Saved>
  save(change: DeepPartial<Sources>): Promise<Saved>
  pickFolder(): Promise<string | null>
  pickFile(): Promise<string | null>
  restoreFrom(path: string): Promise<Saved>
}

/** The welcome steps, one at a time. `step` is the address's; the buttons
 *  at the foot of a step are links to the neighbouring step's address, so
 *  Back and the browser's Back agree. Each step reads the shell's settings
 *  and calls the shell's functions through `actions`, except the language
 *  step, which chooses through `i18n.ts`'s `setLanguage`; the view holds no
 *  shell. `onFinished` runs after the shell has written that onboarding is
 *  done, and is where the page goes Home. */
export function WelcomeView({
  step,
  sources,
  app,
  downloads,
  actions,
  onFinished,
}: {
  step: WelcomeStep
  sources: Sources
  app: AppSettings
  downloads: DownloadsAnswer
  actions: WelcomeActions
  onFinished: () => void
}) {
  const { t } = useTranslation()
  const finish = useFailure()
  const previous = neighbour(step, -1)
  const next = neighbour(step, 1)
  const running = app.firstData.state === 'running'
  const forward =
    step === 'language'
      ? t('welcome.frame.start')
      : step === 'cards' && running
        ? t('welcome.frame.skipBackground')
        : t('welcome.frame.next')
  // Quiet where the step already has a primary action showing.
  const offersDownload =
    step === 'cards' && app.firstData.state === 'idle' && !app.rulesText
  const forwardVariant = step === 'mtgo' || offersDownload ? 'quiet' : 'primary'
  return (
    <Card className="max-w-3xl">
      <div className="space-y-5">
        <div className="space-y-1">
          <p className="text-caption text-muted">
            {t('welcome.frame.step', { n: stepNumber(step), total: WELCOME_STEPS.length })}
          </p>
          <h2 className="font-display text-title text-ink">{headingOf(step, t)}</h2>
        </div>
        {step === 'language' && <LanguageStep />}
        {step === 'welcome' && <WelcomeStepBody app={app} set={actions.set} />}
        {step === 'arena' && <ArenaStep sources={sources} actions={actions} />}
        {step === 'cards' && <CardsStep app={app} downloads={downloads} firstData={actions.firstData} />}
        {step === 'mtgo' && <MtgoStep sources={sources} save={actions.save} pickFolder={actions.pickFolder} />}
        {step === 'done' && <DoneStep app={app} set={actions.set} />}
        {(previous || next || step === 'done') && (
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              {previous && (
                <Button variant="quiet" className="min-h-[44px]" href={stepHref(previous)}>
                  {t('welcome.frame.back')}
                </Button>
              )}
              {next && (
                <Button variant={forwardVariant} className="min-h-[44px]" href={stepHref(next)}>
                  {forward}
                </Button>
              )}
              {step === 'done' && (
                <PressButton
                  variant="primary"
                  label={t('welcome.frame.goHome')}
                  workingLabel={t('welcome.frame.finishing')}
                  doneLabel={null}
                  onPress={async () => {
                    const ok = await finish.press(actions.finishOnboarding)()
                    if (ok) onFinished()
                    return ok
                  }}
                />
              )}
            </div>
            {step === 'done' && <Failure text={finish.failure} />}
          </div>
        )}
      </div>
    </Card>
  )
}

function headingOf(step: WelcomeStep, t: TFunction): string {
  const headings: Record<WelcomeStep, string> = {
    language: t('welcome.headings.language'),
    welcome: t('welcome.headings.welcome'),
    arena: t('welcome.headings.arena'),
    cards: t('welcome.headings.cards'),
    mtgo: t('welcome.headings.mtgo'),
    done: t('welcome.headings.done'),
  }
  return headings[step]
}

function LanguageStep() {
  const { t } = useTranslation()
  const { language, setLanguage } = useLanguage()
  const options = [
    { value: 'en' as const, label: t('common.languages.en') },
    { value: 'pt-BR' as const, label: t('common.languages.pt-BR') },
  ]
  return (
    <div className="space-y-5">
      <p className="text-body text-ink2">{t('welcome.language.body')}</p>
      <Segmented label={t('welcome.language.label')} value={language} options={options} onChange={setLanguage} />
    </div>
  )
}

function WelcomeStepBody({ app, set }: { app: AppSettings; set: WelcomeActions['set'] }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-5">
      <p className="text-body text-ink2">{t('welcome.intro.body')}</p>
      <p className="text-caption text-muted">{t('welcome.intro.wizardsNotice')}</p>
      <div className="space-y-2">
        <SectionLabel as="h3">{t('welcome.intro.leavesTitle')}</SectionLabel>
        <ul className="list-disc space-y-3 pl-5 text-body text-ink2">
          <li>{t('welcome.intro.downloads')}</li>
          <li>
            {app.update.state === 'unavailable' ? (
              t('welcome.intro.updatesUnavailable')
            ) : (
              <div className="space-y-2">
                <p>{t('welcome.intro.dailyCheck')}</p>
                <SavingSwitch
                  label={t('welcome.intro.checkForUpdates')}
                  checked={app.checkForUpdates}
                  onSave={(on) => set({ checkForUpdates: on })}
                />
              </div>
            )}
          </li>
          <li>{t('welcome.intro.claude')}</li>
        </ul>
      </div>
      <p className="text-body text-ink2">
        <Trans
          i18nKey="welcome.intro.credits"
          components={{ credits: <TextLink href="/settings#credits" /> }}
        />
      </p>
    </div>
  )
}

/** A press that says why it failed under itself, in the loss colour. */
function useFailure() {
  const { t } = useTranslation()
  const [failure, setFailure] = useState<string | null>(null)
  const press = (action: () => Promise<Saved>) => async (): Promise<boolean> => {
    setFailure(null)
    const sentence = failureOf(await settle(action(), t), t)
    setFailure(sentence)
    return sentence === null
  }
  return { failure, press, setFailure }
}

function Failure({ text }: { text: string | null }) {
  return text ? <p className="break-words text-caption text-loss">{text}</p> : null
}

function ArenaStep({ sources, actions }: { sources: Sources; actions: WelcomeActions }) {
  const { path, detailedLogs } = sources.arenaLog
  const { t } = useTranslation()
  const recheck = useFailure()
  const restore = useFailure()
  return (
    <div className="space-y-5">
      {path === null ? (
        <p className="text-body text-ink2">{t('welcome.arena.notFound')}</p>
      ) : (
        <div className="space-y-3">
          <p className="text-body text-ink2">
            {detailedLogs === 'enabled' && t('welcome.arena.enabled')}
            {detailedLogs === 'unknown' && t('welcome.arena.unknown')}
            {detailedLogs === 'disabled' && t('welcome.arena.disabled')}
          </p>
          <Field label={t('welcome.arena.logFile')} value={path} />
        </div>
      )}
      {path !== null && detailedLogs !== 'enabled' && (
        <ol className="list-decimal space-y-1 pl-5 text-body text-ink2">
          <li>{t('welcome.arena.instruction1')}</li>
          <li>{t('welcome.arena.instruction2')}</li>
          <li>{t('welcome.arena.instruction3')}</li>
        </ol>
      )}
      {(path === null || detailedLogs !== 'enabled') && (
        <div className="space-y-1.5">
          <PressButton
            variant="quiet"
            label={t('welcome.arena.checkAgain')}
            workingLabel={t('welcome.arena.checking')}
            doneLabel={null}
            onPress={recheck.press(actions.recheck)}
          />
          <Failure text={recheck.failure} />
        </div>
      )}
      <Card title={t('welcome.arena.restoreTitle')} elevation={2}>
        <div className="space-y-3">
          <p className="text-body text-ink2">{t('welcome.arena.restoreBody')}</p>
          <RestoreButton
            label={t('welcome.arena.chooseBackup')}
            pickFile={actions.pickFile}
            restoreFrom={actions.restoreFrom}
            onFailure={restore.setFailure}
            // On success the shell reloads the window.
            onRestored={() => {}}
          />
          <Failure text={restore.failure} />
        </div>
      </Card>
    </div>
  )
}

function Rows({ children }: { children: ReactNode }) {
  return <dl className="space-y-1.5">{children}</dl>
}

function Row({ label, state }: { label: string; state: string | null }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 text-body">
      <dt className="text-ink2">{label}</dt>
      <dd className="text-ink">{state}</dd>
    </div>
  )
}

function downloadState(hours: number | null | undefined, answer: DownloadsAnswer, t: TFunction): string | null {
  if (answer === 'loading') return null
  if (answer === 'failed') return t('welcome.cards.notKnown')
  return hours == null ? t('welcome.cards.notYet') : t('welcome.cards.updated', { age: agePhrase(hours, t) })
}

const megabytes = (bytes: number) => Math.round(bytes / 1_000_000)

/** What the running state says, from the shell's parsed event (S17b). */
function progressSentence(progress: FirstDataProgress | undefined, t: TFunction): string {
  if (!progress) return t('welcome.cards.progressStart')
  if (progress.stage === 'save') return t('welcome.cards.progressSave')
  return progress.total === null
    ? t('welcome.cards.progressSoFar', { done: megabytes(progress.done) })
    : t('welcome.cards.progressOf', { done: megabytes(progress.done), total: megabytes(progress.total) })
}

function CardsMeter({ progress }: { progress: FirstDataProgress | undefined }) {
  const { t } = useTranslation()
  const label = t('welcome.cards.meterLabel')
  if (progress?.stage === 'download' && progress.total) {
    return <Meter fraction={progress.done / progress.total} color="accent" label={label} />
  }
  return <Meter fraction={0} color="accent" label={label} indeterminate />
}

function CardsStep({
  app,
  downloads,
  firstData,
}: {
  app: AppSettings
  downloads: DownloadsAnswer
  firstData: WelcomeActions['firstData']
}) {
  const { t } = useTranslation()
  const { failure, press } = useFailure()
  const state = app.firstData
  const count = app.rulesText
  const ages = typeof downloads === 'object' ? downloads : null
  const start = (label: string, variant: 'primary' | 'quiet') => (
    <div className="space-y-1.5">
      <PressButton variant={variant} label={label} workingLabel={t('welcome.cards.starting')} doneLabel={null} onPress={press(firstData)} />
      {state.state !== 'failed' && <Failure text={failure} />}
    </div>
  )
  return (
    <div className="space-y-5">
      <p className="text-body text-ink2">{t('welcome.cards.intro')}</p>
      <div className="space-y-3">
        {state.state === 'idle' && !count && start(t('welcome.cards.download'), 'primary')}
        {state.state === 'idle' && !!count && (
          <>
            <p className="text-body text-ink2">{t('welcome.cards.alreadyHave', { n: formatCount(count) })}</p>
            {start(t('welcome.cards.downloadAgain'), 'quiet')}
          </>
        )}
        {state.state === 'running' && (
          <div className="space-y-2">
            <CardsMeter progress={state.progress} />
            <p role="status" className="break-words text-body text-ink2">
              {progressSentence(state.progress, t)}
            </p>
          </div>
        )}
        {state.state === 'done' && (
          <p className="text-body text-ink2">
            {!count ? t('welcome.cards.doneEmpty') : t('welcome.cards.doneCount', { n: formatCount(count) })}
          </p>
        )}
        {state.state === 'failed' && (
          <>
            <p className="break-words text-body text-loss">
              {t('welcome.cards.failed', { reason: withStop(state.error) })}
            </p>
            {start(t('welcome.cards.tryAgain'), 'quiet')}
          </>
        )}
      </div>
      <div className="space-y-2">
        <SectionLabel as="h3">{t('welcome.cards.alsoTitle')}</SectionLabel>
        <Rows>
          <Row
            label={t('welcome.cards.archetypes')}
            state={downloadState(ages?.archetypeHours, downloads, t)}
          />
          <Row
            label={t('welcome.cards.tournaments')}
            state={downloadState(ages?.corpusHours, downloads, t)}
          />
        </Rows>
        <p className="text-caption text-muted">{t('welcome.cards.background')}</p>
      </div>
    </div>
  )
}

function MtgoStep({
  sources,
  save,
  pickFolder,
}: {
  sources: Sources
  save: WelcomeActions['save']
  pickFolder: WelcomeActions['pickFolder']
}) {
  const { t } = useTranslation()
  const { restart, watch } = useRestart()
  const text = useTextSave(
    { mtgoHandle: sources.mtgoHandle, mtgoDir: sources.mtgoDir },
    (change) => watch(save(change)),
  )
  // A folder the app found fills the field the first time it is drawn; it
  // is saved only when the person presses Save.
  const [seeded, setSeeded] = useState(false)
  if (!seeded) {
    setSeeded(true)
    if (sources.mtgoDir === null && sources.mtgoFound !== null) text.type('mtgoDir', sources.mtgoFound)
  }
  const hint =
    sources.mtgoDir !== null
      ? t('welcome.mtgo.hintSaved')
      : sources.mtgoFound !== null
        ? t('welcome.mtgo.hintFound')
        : t('welcome.mtgo.hintNone')
  return (
    <div className="space-y-5">
      <p className="text-body text-ink2">{t('welcome.mtgo.skip')}</p>
      <Field
        label={t('welcome.mtgo.handleLabel')}
        value={text.typed.mtgoHandle}
        onChange={(value) => text.type('mtgoHandle', value)}
        hint={t('welcome.mtgo.handleHint')}
        error={text.errorOf('mtgoHandle')}
      />
      <FolderField
        label={t('welcome.mtgo.folderLabel')}
        value={text.typed.mtgoDir}
        onChange={(value) => text.type('mtgoDir', value)}
        onPick={pickFolder}
        hint={hint}
        error={text.errorOf('mtgoDir')}
      />
      <SaveButton dirty={text.dirty} onSave={text.submit} />
      <RestartNote show={restart} />
    </div>
  )
}

function DoneStep({ app, set }: { app: AppSettings; set: WelcomeActions['set'] }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-5">
      <p className="text-body text-ink2">{t('welcome.done.body')}</p>
      {app.askAutostart && (
        <SavingSwitch
          label={t('welcome.done.autostartLabel')}
          description={t('welcome.done.autostartDescription')}
          checked={app.startWithSystem}
          onSave={(on) => set({ startWithSystem: on })}
        />
      )}
    </div>
  )
}
