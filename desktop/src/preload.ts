// The preload script (release plan 6, S9): `window.senseiTopShell`, the one
// global the dashboard's bridge reads. Each member is an `ipcRenderer.invoke`
// call, except `initial`, read once with `sendSync` from the main process's
// cache so the first render already has the settings (`null` when they could
// not be read).
//
// `reportError`, `reportProblem` and `onReportProblem` are S11's (DB9, DB15).
// `account.setProfile`, `exportData`, `deleteCloudHistory` and `deleteAccount`
// are plan 40b S12's.
//
// `app` also carries onboarding's three actions (S15): `recheck`, `firstData`
// and `finishOnboarding`.
//
// It runs on every page the window loads, the `data:` loading and error pages
// included, so it does nothing unless the page is served over `http:` (the
// dashboard): the main process refuses the other pages' messages, and they
// have no use for the bridge.
//
// A sandboxed preload can require only `electron`, so this file does not
// import `settings.ts` at run time: the channel names are repeated below, and
// `settings.test.ts` checks they match `CHANNELS`. Types are erased.

import { contextBridge, ipcRenderer } from 'electron';
import type { AccountReply, ProfileChange } from './cloud/account';
import type { ReportOutcome } from './cloud/report';
import type { AccountSignInReply, AccountState, AppChange, BridgeSettings, DeepPartial, KeyName, Saved, ShellSettings } from './settings';

const CHANNEL = {
  initial: 'sensei-top:initial',
  save: 'sensei-top:save',
  setKey: 'sensei-top:set-key',
  pickFolder: 'sensei-top:pick-folder',
  pickFile: 'sensei-top:pick-file',
  backUpNow: 'sensei-top:back-up-now',
  restoreFrom: 'sensei-top:restore-from',
  appSet: 'sensei-top:app-set',
  appCheckForUpdates: 'sensei-top:app-check-for-updates',
  appRestartToUpdate: 'sensei-top:app-restart-to-update',
  appShowLogs: 'sensei-top:app-show-logs',
  appShowDataFolder: 'sensei-top:app-show-data-folder',
  appExportDiagnostics: 'sensei-top:app-export-diagnostics',
  appRecheck: 'sensei-top:app-recheck',
  appFirstData: 'sensei-top:app-first-data',
  appFinishOnboarding: 'sensei-top:app-finish-onboarding',
  accountStatus: 'sensei-top:account-status',
  accountSignIn: 'sensei-top:account-sign-in',
  accountSignOut: 'sensei-top:account-sign-out',
  accountSetProfile: 'sensei-top:account-set-profile',
  accountExport: 'sensei-top:account-export',
  accountDeleteHistory: 'sensei-top:account-delete-history',
  accountDelete: 'sensei-top:account-delete',
  reportError: 'sensei-top:report-error',
  reportProblem: 'sensei-top:report-problem',
  reportProblemRequested: 'sensei-top:report-problem-requested',
  changed: 'sensei-top:changed',
} as const;

// The sandboxed preload has `location`; the build has no DOM types.
const { location } = globalThis as unknown as { location: { protocol: string } };

if (location.protocol === 'http:') {
  const initial = ipcRenderer.sendSync(CHANNEL.initial) as BridgeSettings | null;

  contextBridge.exposeInMainWorld('senseiTopShell', {
    initial,
    save: (change: DeepPartial<ShellSettings>): Promise<Saved> => ipcRenderer.invoke(CHANNEL.save, change),
    setKey: (which: KeyName, key: string | null): Promise<Saved> => ipcRenderer.invoke(CHANNEL.setKey, which, key),
    pickFolder: (): Promise<string | null> => ipcRenderer.invoke(CHANNEL.pickFolder),
    pickFile: (): Promise<string | null> => ipcRenderer.invoke(CHANNEL.pickFile),
    backUpNow: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.backUpNow),
    restoreFrom: (path: string): Promise<Saved> => ipcRenderer.invoke(CHANNEL.restoreFrom, path),
    app: {
      set: (change: AppChange): Promise<Saved> => ipcRenderer.invoke(CHANNEL.appSet, change),
      checkForUpdates: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.appCheckForUpdates),
      restartToUpdate: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.appRestartToUpdate),
      showLogs: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.appShowLogs),
      showDataFolder: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.appShowDataFolder),
      exportDiagnostics: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.appExportDiagnostics),
      recheck: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.appRecheck),
      firstData: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.appFirstData),
      finishOnboarding: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.appFinishOnboarding),
    },
    account: {
      status: (): Promise<AccountState> => ipcRenderer.invoke(CHANNEL.accountStatus),
      signIn: (provider: 'google' | 'discord'): Promise<AccountSignInReply> => ipcRenderer.invoke(CHANNEL.accountSignIn, provider),
      signOut: (): Promise<Saved> => ipcRenderer.invoke(CHANNEL.accountSignOut),
      setProfile: (change: ProfileChange): Promise<AccountReply> => ipcRenderer.invoke(CHANNEL.accountSetProfile, change),
      exportData: (): Promise<AccountReply> => ipcRenderer.invoke(CHANNEL.accountExport),
      deleteCloudHistory: (): Promise<AccountReply> => ipcRenderer.invoke(CHANNEL.accountDeleteHistory),
      deleteAccount: (): Promise<AccountReply> => ipcRenderer.invoke(CHANNEL.accountDelete),
    },
    reportError: (error: { name: string; message: string; stack: string | null }): Promise<boolean> => ipcRenderer.invoke(CHANNEL.reportError, error),
    reportProblem: (report: { text: string; attachLog: boolean }): Promise<ReportOutcome> => ipcRenderer.invoke(CHANNEL.reportProblem, report),
    /** Calls `listener` when the tray's "Report a problem" was chosen; returns a function that stops it. */
    onReportProblem: (listener: () => void): (() => void) => {
      const handler = () => listener();
      ipcRenderer.on(CHANNEL.reportProblemRequested, handler);
      return () => {
        ipcRenderer.removeListener(CHANNEL.reportProblemRequested, handler);
      };
    },
    /** Calls `listener` with the new settings after any change; returns a function that stops it. */
    onChange: (listener: (settings: BridgeSettings) => void): (() => void) => {
      const handler = (_event: unknown, settings: BridgeSettings) => listener(settings);
      ipcRenderer.on(CHANNEL.changed, handler);
      return () => {
        ipcRenderer.removeListener(CHANNEL.changed, handler);
      };
    },
  });
}
