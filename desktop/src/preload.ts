// The preload script (release plan 6, S9): `window.senseiTopShell`, the one
// global the dashboard's bridge reads. Each member is an `ipcRenderer.invoke`
// call, except `initial`, read once with `sendSync` from the main process's
// cache so the first render already has the settings (`null` when they could
// not be read).
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
import type { AppChange, BridgeSettings, DeepPartial, Deleted, KeyName, Saved, ShellSettings } from './settings';

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
  changed: 'sensei-top:changed',
} as const;

// Plan 10's draft sharing: this shell offers none, so these answer without
// asking the main process. `sharing` is `null`, so the page never draws them.
const NOT_AVAILABLE = 'Not available yet.';
const unavailable = (): Promise<Saved> => Promise.resolve({ ok: false, error: NOT_AVAILABLE });

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
    setSharing: (_on: boolean): Promise<Saved> => unavailable(),
    payloadOf: (_draftId: string): Promise<null> => Promise.resolve(null),
    sharedState: (_draftId: string): Promise<{ state: 'not-shared'; at: null }> =>
      Promise.resolve({ state: 'not-shared', at: null }),
    unshare: (_draftId: string): Promise<Saved> => unavailable(),
    deleteContributions: (): Promise<Deleted> => Promise.resolve({ ok: false, error: NOT_AVAILABLE }),
    newInstallation: (): Promise<Saved> => unavailable(),
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
