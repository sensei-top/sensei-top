import { Check } from 'lucide-react'
import { useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import type { AppChange, AppSettings, DeepPartial, Saved, ShellSettings } from '../bridge'
import { CardDataProgress } from '../components/onboarding/CardDataProgress'
import { DetailedLogsGuide } from '../components/onboarding/DetailedLogsGuide'
import { RestoreButton } from '../components/settings/BackupSection'
import { FolderField, PressButton, RestartNote, SaveButton, SavingSwitch } from '../components/settings/SaveButton'
import { Button, Card, Disclosure, Field, Segmented, TextLink } from '../components/ui'
import { useLanguage, type TFunction } from '../i18n'
import { failureOf, settle, useRestart, useTextSave } from '../lib/settings'
import { neighbour, stepHref, stepNumber, stepsFor, type Plays, type WelcomeStep } from '../lib/welcome'

type Sources = ShellSettings['sources']

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

/** The welcome steps, one at a time: Start, Which do you play?, the setup
 *  of each client chosen (`app.plays`, both when absent), Ready. `step` is
 *  the address's; the buttons at the foot of a step are links to the
 *  neighbouring step's address, so Back and the browser's Back agree, and
 *  "Step n of m" counts only the steps shown. Each step reads the shell's
 *  settings and calls the shell's functions through `actions`, except the
 *  language, which chooses through `i18n.ts`'s `setLanguage`; the view holds
 *  no shell. `onFinished` runs after the shell has written that onboarding
 *  is done, and is where the page goes Home. */
export function WelcomeView({
  step,
  sources,
  app,
  actions,
  onFinished,
}: {
  step: WelcomeStep
  sources: Sources
  app: AppSettings
  actions: WelcomeActions
  onFinished: () => void
}) {
  const { t } = useTranslation()
  const finish = useFailure()
  const steps = stepsFor(app.plays, step)
  const previous = neighbour(step, -1, steps)
  const next = neighbour(step, 1, steps)
  const forward = step === 'start' ? t('welcome.frame.start') : t('welcome.frame.next')
  // Quiet where the step's own control is the one to press: the tiles, or
  // Magic Online's Save.
  const forwardVariant = step === 'plays' || step === 'mtgo' ? 'quiet' : 'primary'
  return (
    <Card className="max-w-3xl">
      <div className="space-y-5">
        <div className="space-y-1">
          <p className="text-caption text-muted">
            {t('welcome.frame.step', { n: stepNumber(step, steps), total: steps.length })}
          </p>
          <h2 className="font-display text-title text-ink">{headingOf(step, t)}</h2>
        </div>
        {step === 'start' && <StartStep app={app} actions={actions} />}
        {step === 'plays' && <PlaysStep plays={app.plays} set={actions.set} />}
        {step === 'arena' && <ArenaStep sources={sources} recheck={actions.recheck} />}
        {step === 'mtgo' && <MtgoStep sources={sources} save={actions.save} pickFolder={actions.pickFolder} />}
        {step === 'done' && <DoneStep app={app} actions={actions} />}
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
    start: t('welcome.headings.start'),
    plays: t('welcome.headings.plays'),
    arena: t('welcome.headings.arena'),
    mtgo: t('welcome.headings.mtgo'),
    done: t('welcome.headings.done'),
  }
  return headings[step]
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

/** The language, the promise, what leaves this computer behind a
 *  disclosure, the Wizards notice, and the restore for someone who has used
 *  the app before. A restore runs even while card data downloads: the shell
 *  stops the download first. */
function StartStep({ app, actions }: { app: AppSettings; actions: WelcomeActions }) {
  const { t } = useTranslation()
  const { language, setLanguage } = useLanguage()
  const restore = useFailure()
  const options = [
    { value: 'en' as const, label: t('common.languages.en') },
    { value: 'pt-BR' as const, label: t('common.languages.pt-BR') },
  ]
  return (
    <div className="space-y-5">
      <Segmented label={t('welcome.language.label')} value={language} options={options} onChange={setLanguage} />
      <p className="text-body text-ink2">{t('welcome.start.promise')}</p>
      <Disclosure summary={t('welcome.intro.leavesTitle')}>
        <div className="space-y-3">
          <ul className="list-disc space-y-3 pl-5 text-body text-ink2">
            <li>{t('welcome.intro.downloads')}</li>
            <li>
              {app.update.state === 'unavailable' ? t('welcome.intro.updatesUnavailable') : t('welcome.intro.dailyCheck')}
            </li>
            <li>{t('welcome.intro.claude')}</li>
          </ul>
          <p className="text-body text-ink2">
            <Trans i18nKey="welcome.intro.credits" components={{ credits: <TextLink href="/settings#credits" /> }} />
          </p>
        </div>
      </Disclosure>
      <p className="text-caption text-muted">{t('welcome.intro.wizardsNotice')}</p>
      <div className="space-y-1.5">
        <p className="text-body text-ink2">{t('welcome.start.restoreTitle')}</p>
        <RestoreButton
          label={t('welcome.start.restore')}
          pickFile={actions.pickFile}
          restoreFrom={actions.restoreFrom}
          onFailure={restore.setFailure}
          // On success the shell reloads the window.
          onRestored={() => {}}
        />
        <Failure text={restore.failure} />
      </div>
    </div>
  )
}

type PlaysChoice = 'arena' | 'mtgo' | 'both'

const PLAYS_OF: Record<PlaysChoice, NonNullable<Plays>> = {
  arena: ['arena'],
  mtgo: ['mtgo'],
  both: ['arena', 'mtgo'],
}

/** The tile the shell's `plays` marks. The shell always sends one, both
 *  until the person picks, so a first run shows Both pressed: the default.
 *  Only a shell older than `plays` sends none, and then nothing is marked. */
function choiceOf(plays: Plays): PlaysChoice | null {
  if (!plays || plays.length === 0) return null
  const arena = plays.includes('arena')
  const mtgo = plays.includes('mtgo')
  return arena && mtgo ? 'both' : arena ? 'arena' : 'mtgo'
}

/** Three tiles; pressing one saves the choice and goes on to the first
 *  step it keeps. */
function PlaysStep({ plays, set }: { plays: Plays; set: WelcomeActions['set'] }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { failure, press } = useFailure()
  const [saving, setSaving] = useState<PlaysChoice | null>(null)
  const current = choiceOf(plays)
  const choose = async (choice: PlaysChoice) => {
    setSaving(choice)
    const chosen = PLAYS_OF[choice]
    const ok = await press(() => set({ plays: chosen }))()
    setSaving(null)
    const next = neighbour('plays', 1, stepsFor(chosen))
    if (ok && next) void navigate(stepHref(next))
  }
  const tiles: { choice: PlaysChoice; label: string }[] = [
    { choice: 'arena', label: t('welcome.plays.arena') },
    { choice: 'mtgo', label: t('welcome.plays.mtgo') },
    { choice: 'both', label: t('welcome.plays.both') },
  ]
  return (
    <div className="space-y-5">
      <p className="text-body text-ink2">{t('welcome.plays.body')}</p>
      <div className="space-y-1.5">
        <div className="grid gap-3 sm:grid-cols-3">
          {tiles.map(({ choice, label }) => {
            const pressed = choice === current
            return (
              <button
                key={choice}
                type="button"
                aria-pressed={pressed}
                disabled={saving !== null}
                onClick={() => void choose(choice)}
                className={`flex min-h-[64px] items-center justify-center gap-2 rounded-control border px-4 py-3 text-body font-medium transition-chrome disabled:opacity-60 ${
                  pressed
                    ? 'border-accent bg-surface3 text-ink'
                    : 'border-edge bg-surface2 text-ink2 hover:border-edge-strong hover:text-ink'
                }`}
              >
                {pressed && <Check size={16} strokeWidth={2.25} aria-hidden className="shrink-0 text-accent" />}
                {label}
              </button>
            )
          })}
        </div>
        <Failure text={failure} />
      </div>
    </div>
  )
}

/** The light beside the status line: decoration, since the sentence beside
 *  it says the same thing. */
function lightOf(path: string | null, detailedLogs: Sources['arenaLog']['detailedLogs']): string {
  if (path === null) return 'bg-loss'
  return detailedLogs === 'enabled' ? 'bg-win' : 'bg-warn'
}

function ArenaStep({ sources, recheck }: { sources: Sources; recheck: WelcomeActions['recheck'] }) {
  const { path, detailedLogs } = sources.arenaLog
  const { t } = useTranslation()
  const check = useFailure()
  const on = path !== null && detailedLogs === 'enabled'
  const status =
    path === null
      ? t('welcome.arena.notFound')
      : detailedLogs === 'enabled'
        ? t('welcome.arena.enabled')
        : detailedLogs === 'disabled'
          ? t('welcome.arena.disabled')
          : t('welcome.arena.unknown')
  return (
    <div className="space-y-5">
      <p className="flex items-start gap-2 text-body text-ink2">
        <span aria-hidden className={`mt-2 inline-block size-2 shrink-0 rounded-pill ${lightOf(path, detailedLogs)}`} />
        <span>{status}</span>
      </p>
      {!on && <DetailedLogsGuide />}
      {!on && (
        <div className="space-y-1.5">
          <PressButton
            variant="quiet"
            label={t('welcome.arena.checkAgain')}
            workingLabel={t('welcome.arena.checking')}
            doneLabel={null}
            onPress={check.press(recheck)}
          />
          <Failure text={check.failure} />
        </div>
      )}
      {path !== null && <Field label={t('welcome.arena.logFile')} value={path} />}
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
    { mtgoHandle: sources.mtgoHandle, mtgoDir: sources.mtgoDir, mtgoDeckDir: sources.mtgoDeckDir },
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
      <FolderField
        label={t('welcome.mtgo.decksLabel')}
        value={text.typed.mtgoDeckDir}
        onChange={(value) => text.type('mtgoDeckDir', value)}
        onPick={pickFolder}
        hint={t('welcome.mtgo.decksHint')}
        error={text.errorOf('mtgoDeckDir')}
      />
      <SaveButton dirty={text.dirty} onSave={text.submit} />
      <RestartNote show={restart} />
    </div>
  )
}

/** Play a match, card data while it downloads or if it failed (the shell
 *  starts it on its own, so idle draws nothing), and the two preferences:
 *  the update check where the build has an updater, autostart where the
 *  shell asks. The tour link (`welcome.done.tour`) is not drawn: the
 *  dashboard has no address for the site's help pages to build it from. */
function DoneStep({ app, actions }: { app: AppSettings; actions: WelcomeActions }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-5">
      <p className="text-body text-ink2">{t('welcome.done.body')}</p>
      <CardDataProgress state={app.firstData} count={app.rulesText} retry={actions.firstData} />
      {app.update.state !== 'unavailable' && (
        <SavingSwitch
          label={t('welcome.done.updatesLabel')}
          checked={app.checkForUpdates}
          onSave={(on) => actions.set({ checkForUpdates: on })}
        />
      )}
      {app.askAutostart && (
        <SavingSwitch
          label={t('welcome.done.autostartLabel')}
          description={t('welcome.done.autostartDescription')}
          checked={app.startWithSystem}
          onSave={(on) => actions.set({ startWithSystem: on })}
        />
      )}
    </div>
  )
}
