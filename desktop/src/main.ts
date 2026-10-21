// The desktop shell's main process (release plan 6, S8): the only file that
// loads Electron. Everything with a rule in it lives in the modules it wires
// together: `autostart.ts` (D25), `server.ts` (the `serve` child), `window.ts` (the main window),
// `tray.ts` (D14), `log.ts` (D17), `store.ts` (shell.json, D2), `settings.ts`
// (the bridge's settings and its IPC contract, S9; `preload.ts` is its page side),
// `updater.ts` (S14, D24), `i18n.ts` (the shell's own text, plan 18 D8).
// Onboarding's three actions (S15) are answered by `settings.ts`.
//
// - One instance (F7): a second launch shows the first one's window, and
//   retries the server if it had given up.
// - SIGTERM and SIGINT are logged before quitting (F10: `will-quit` does not
//   run on a signal); a second signal exits at once.
// - Quitting stops the server first: its stdin closes, it shuts down in
//   order, and only then does the app exit.
// - Updates (S14): electron-updater is loaded only where `updaterAvailability`
//   says the updater can run; elsewhere the log says once why. "Restart to
//   update" takes the quit path itself (`quitAndInstall` spawns the installer
//   before it quits), and on Linux frees the single-instance lock for the new
//   AppImage. An install that fails quits when a quit was asked during the
//   stop, and otherwise restores the shell (the server, the quit flags, the
//   window's, the lock): the next quit must stop the server again, since
//   install-on-quit is still armed.

import * as electron from 'electron';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { applyAutostart, applyFirstRun, startMode } from './autostart';
import { setLanguage, setSystemTags, t } from './i18n';
import { logPath, newSessionId, ShellLog } from './log';
import {
  asksAutostart,
  canAutostart,
  CHANNELS,
  diagnosticsArgs,
  formatListing,
  restoreLeftovers,
  restoreLeftoversMessage,
  SettingsService,
  trustedSender,
  type BridgeSettings,
  type Saved,
} from './settings';
import { DB_NAME, resolveDataDir, serverCommand, ServerController, type ServerState } from './server';
import { ShellStore } from './store';
import { StatusTray, type UpdateMenu } from './tray';
import { updaterAvailability, UpdateService, type UpdateStatus } from './updater';
import { appMenuTemplate, MainWindow } from './window';

// F6: under ELECTRON_RUN_AS_NODE, `electron` is a path string and this is plain Node.
if (typeof electron.app !== 'object' || electron.app === null) {
  process.stderr.write('Sensei Top: ELECTRON_RUN_AS_NODE is set, so Electron runs as plain Node. Unset it and start again.\n');
  process.exit(1);
}

const { app, BrowserWindow, Menu, Tray, dialog, ipcMain, nativeImage, screen, shell } = electron;
const packaged = app.isPackaged;
const onWindowsStore = process.windowsStore === true;
const canStartWithSystem = canAutostart({
  platform: process.platform,
  packaged,
  appImage: process.env.APPIMAGE,
  windowsStore: onWindowsStore,
});

const { dir: dataDir, overridden } = resolveDataDir({
  platform: process.platform,
  env: process.env,
  home: os.homedir(),
  packaged,
});
// A development run pointed at a scratch directory keeps its Electron
// profile (shell.json, localStorage, the single-instance lock) there too.
if (overridden) app.setPath('userData', path.join(dataDir, 'userData'));

try {
  fs.mkdirSync(dataDir, { recursive: true });
} catch {
  // the log says why below, and the server's start fails visibly
}

const session = newSessionId();
const shellLog = new ShellLog(logPath(dataDir), { session, echo: !packaged });
const log = shellLog.child('shell.main');

if (!app.requestSingleInstanceLock()) {
  log.info('second launch: the running instance was asked to show its window');
  shellLog.close();
  app.quit();
} else {
  run();
}

function run(): void {
  const store = ShellStore.load(app.getPath('userData'), shellLog.child('shell.store'));
  if (store.get().diagnostic) shellLog.setLevel('DEBUG');

  log.info('start', {
    app: app.getVersion(),
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
    os: `${os.type()} ${os.release()} ${os.arch()}`,
    osVersion: process.getSystemVersion(),
    packaged,
    dataDir,
    dataDirOverridden: overridden,
    displayServer: process.env.XDG_SESSION_TYPE ?? null,
    desktop: process.env.XDG_CURRENT_DESKTOP ?? null,
  });

  const command = serverCommand({
    packaged,
    platform: process.platform,
    resourcesPath: process.resourcesPath,
    appPath: app.getAppPath(),
  });
  // D25: Electron alone writes the Run entry (Windows); Linux gets an XDG entry.
  const applyLoginItem = (on: boolean): void =>
    applyAutostart(
      {
        platform: process.platform,
        packaged,
        env: process.env,
        home: os.homedir(),
        setLoginItemSettings: (settings) => app.setLoginItemSettings(settings),
        mkdirSync: (dir) => void fs.mkdirSync(dir, { recursive: true }),
        writeFileSync: (file, text) => fs.writeFileSync(file, text, 'utf8'),
        rmSync: (file) => fs.rmSync(file),
        log: shellLog.child('shell.autostart'),
      },
      on,
    );
  // The installer's note, once, before the window exists.
  applyFirstRun({
    dir: path.dirname(process.execPath),
    readFileSync: (file) => fs.readFileSync(file, 'utf8'),
    rmSync: (file) => fs.rmSync(file),
    store,
    apply: applyLoginItem,
    log: shellLog.child('shell.autostart'),
  });
  // The language, before any text is drawn (the installer's note may have just set it, above).
  // getPreferredSystemLanguages, not getLocale: getLocale is valid only after `ready`, and this runs before it.
  setSystemTags(() => app.getPreferredSystemLanguages());
  setLanguage(store.get().language ?? 'system');

  const server = new ServerController({
    command,
    dataDir,
    session,
    env: process.env,
    verbose: () => Boolean(store.get().diagnostic),
    rememberedPort: () => store.get().port,
    rememberPort: (port) => {
      store.update({ port });
    },
    log: shellLog.child('shell.server'),
  });
  log.info('server command', { file: command.file });

  let window: MainWindow | null = null;
  const liveWindow = (): MainWindow | null => (window && !window.win.isDestroyed() ? window : null);
  let tray: StatusTray | null = null;
  let stopping = false;
  let readyToQuit = false;
  /** A Quit or a signal came while a stop was already under way. */
  let quitAsked = false;

  // S14: electron-updater is never loaded where the updater cannot run.
  const updaterLog = shellLog.child('shell.updater');
  const availability = updaterAvailability({
    platform: process.platform,
    packaged,
    windowsStore: Boolean(process.windowsStore),
    appImage: process.env.APPIMAGE,
  });
  let updates: UpdateService | null = null;
  let updatesOff: UpdateStatus | null = availability.available ? null : { state: 'unavailable', reason: availability.reason };
  if (!availability.available) updaterLog.info('updates off', { reason: availability.reason });
  // Before the service exists no check has run: `idle`.
  const updateStatus = (): UpdateStatus => updates?.status ?? updatesOff ?? { state: 'idle' };
  const updateMenu = (): UpdateMenu => ({
    canCheck: updates !== null && (store.get().checkForUpdates ?? true),
    ready: updateStatus().state === 'ready',
  });

  // Resolves once the server is ready or has given up: a setting that
  // restarts it (D12) and a restore both wait for that.
  const serverSettled = (): Promise<void> =>
    new Promise((resolve) => {
      const onState = (state: ServerState) => {
        if (state.kind !== 'ready' && state.kind !== 'failed') return;
        server.off('state', onState);
        resolve();
      };
      server.on('state', onState);
    });

  const pick = async (properties: Array<'openFile' | 'openDirectory' | 'createDirectory'>): Promise<string | null> => {
    const options: electron.OpenDialogOptions = { properties };
    const result = window ? await dialog.showOpenDialog(window.win, options) : await dialog.showOpenDialog(options);
    return result.canceled ? null : (result.filePaths[0] ?? null);
  };

  // D19: a restore that stopped partway leaves no database at its path and
  // its files under `.replaced` names; a server started then would create a
  // fresh, empty database in their place.
  const restoreBlock = (): string | null => {
    let entries: string[] = [];
    try {
      entries = fs.readdirSync(dataDir);
    } catch {
      return null;
    }
    const files = restoreLeftovers(DB_NAME, entries.includes(DB_NAME), entries);
    return files.length > 0 ? restoreLeftoversMessage(files) : null;
  };
  const startUnlessBlocked = (): boolean => {
    const block = restoreBlock();
    if (block) {
      log.error(block);
      window?.showError(shellLog.scrub(logPath(dataDir)), block);
      return false;
    }
    server.start();
    return true;
  };

  // D16: show what would go in, ask for the file, then write the zip.
  const exportDiagnostics = async (): Promise<Saved> => {
    try {
      const listing = formatListing(await server.run(['diagnostics', '--list', '--shell-log', logPath(dataDir)]));
      const box: electron.MessageBoxOptions = {
        type: 'question',
        title: t('diagnostics.title'),
        message: t('diagnostics.title'),
        detail: `${listing}\n\n${t('diagnostics.playerLog')}`,
        buttons: [t('diagnostics.saveAs'), t('diagnostics.cancel')],
        defaultId: 0,
        cancelId: 1,
        checkboxLabel: t('diagnostics.includePlayerLog'),
        checkboxChecked: false,
      };
      const answer = window ? await dialog.showMessageBox(window.win, box) : await dialog.showMessageBox(box);
      if (answer.response !== 0) return { ok: true };
      const saveOptions: electron.SaveDialogOptions = {
        defaultPath: 'sensei-top-diagnostics.zip',
        filters: [{ name: 'Zip', extensions: ['zip'] }],
      };
      const target = window ? await dialog.showSaveDialog(window.win, saveOptions) : await dialog.showSaveDialog(saveOptions);
      if (target.canceled || !target.filePath) return { ok: true };
      await server.run(diagnosticsArgs({ out: target.filePath, shellLog: logPath(dataDir), withPlayerLog: answer.checkboxChecked }));
      return { ok: true };
    } catch (error) {
      const stderr = (error as { stderr?: unknown }).stderr;
      log.warn('diagnostics export failed', { error: String(error) });
      return { ok: false, error: typeof stderr === 'string' && stderr.trim() ? stderr.trim() : t('diagnostics.failed') };
    }
  };

  const settings = new SettingsService({
    run: (args, options) => server.run(args, options),
    stopServer: () => server.stop(),
    startServer: () => {
      const settled = serverSettled();
      if (!startUnlessBlocked()) return Promise.resolve();
      return settled;
    },
    reloadWindow: () => liveWindow()?.win.webContents.reloadIgnoringCache(),
    store,
    dataDir,
    version: app.getVersion(),
    platform: process.platform,
    askAutostart: asksAutostart(process.platform, onWindowsStore, canStartWithSystem),
    canAutostart: canStartWithSystem,
    windowsStore: onWindowsStore,
    newestBackup: (dir) => {
      try {
        const stat = fs.statSync(path.join(dir, `${DB_NAME}.backup`));
        return { at: stat.mtime.toISOString(), bytes: stat.size };
      } catch {
        return null;
      }
    },
    countBackups: (dir) => {
      try {
        return fs.readdirSync(dir).filter((name) => name.startsWith(`${DB_NAME}.backup`) && !name.includes('.tmp.')).length;
      } catch {
        return 0;
      }
    },
    now: () => new Date(),
    applyAutostart: applyLoginItem,
    setDiagnostic: (on) => shellLog.setLevel(on ? 'DEBUG' : 'INFO'),
    setLanguage: (choice) => setLanguage(choice),
    pickFolder: () => pick(['openDirectory', 'createDirectory']),
    pickFile: () => pick(['openFile']),
    showLogs: () => {
      void shell.openPath(path.join(dataDir, 'logs')).then((error) => {
        if (error) log.warn('could not open the log folder', { error });
      });
    },
    openDataFolder: () => shell.openPath(dataDir),
    // An updater event can arrive after the window is gone (a failed
    // install-on-quit, at the `quit` event).
    changed: (next: BridgeSettings) => {
      liveWindow()?.win.webContents.send(CHANNELS.changed, next);
    },
    updateStatus,
    setUpdateChecks: (on) => {
      updates?.setEnabled(on);
      tray?.setUpdate(updateMenu());
    },
    log: shellLog.child('shell.settings'),
  });

  // A status change rebuilds the tray menu and sends the page its settings.
  const onUpdateStatus = (): void => {
    tray?.setUpdate(updateMenu());
    settings.updateChanged();
  };

  const checkForUpdates = (): Promise<Saved> =>
    updates ? updates.checkNow() : Promise.resolve({ ok: false, error: t('update.off') });

  // The quit path, taken by hand: the server stops, the window may close, and
  // the next `before-quit` (electron-updater's own `app.quit()`) goes through.
  // The window is told only once the server has stopped: a window closed
  // during the stop follows D13 (it hides, or on Linux with keep-running off
  // it asks to quit, which `before-quit` records).
  const installUpdate = async (service: UpdateService): Promise<Saved> => {
    let began = false;
    let lockReleased = false;
    const result = await service.restartToUpdate(async () => {
      began = true;
      updaterLog.info('restart to update: stopping the server');
      stopping = true;
      settings.stopFirstData();
      await server.stop();
      window?.setQuitting();
      readyToQuit = true;
      // The new AppImage starts before app.quit() and must not find the lock taken.
      if (process.platform === 'linux') {
        app.releaseSingleInstanceLock();
        lockReleased = true;
      }
    });
    if (result.ok || !began) return result;
    // The tray's Quit always quits: one asked for during the stop goes through.
    if (quitAsked) {
      updaterLog.warn('the update was not installed: quitting, as asked');
      readyToQuit = true;
      app.quit();
      return result;
    }
    updaterLog.warn('the update was not installed: starting the server again');
    stopping = false;
    readyToQuit = false;
    window?.cancelQuitting();
    if (lockReleased && !app.requestSingleInstanceLock()) {
      updaterLog.warn('the single-instance lock could not be taken again');
    }
    startUnlessBlocked();
    return result;
  };
  let restarting: Promise<Saved> | null = null;
  const restartToUpdate = (): Promise<Saved> => {
    if (!updates) return Promise.resolve({ ok: false, error: t('update.nothingReady') });
    restarting ??= installUpdate(updates).finally(() => {
      restarting = null;
    });
    return restarting;
  };

  // Only the dashboard, on the running server's origin, is answered.
  const trusted = (event: electron.IpcMainEvent | electron.IpcMainInvokeEvent): boolean => {
    const ok = trustedSender(event.senderFrame?.url ?? '', server.port);
    if (!ok) log.warn('refused an IPC message from an unexpected page');
    return ok;
  };
  // The refusal is built when it is answered, in the language of that moment.
  const handle = <A extends unknown[], R>(channel: string, refused: () => R, fn: (...args: A) => R | Promise<R>): void => {
    ipcMain.handle(channel, (event, ...args) => (trusted(event) ? fn(...(args as A)) : refused()));
  };
  ipcMain.on(CHANNELS.initial, (event) => {
    event.returnValue = trusted(event) ? settings.current : null;
  });
  const refusedSaved = (): Saved => ({ ok: false, error: t('ipc.refused') });
  const refusedNull = (): null => null;
  handle(CHANNELS.save, refusedSaved, (change: Parameters<SettingsService['save']>[0]) => settings.save(change));
  handle(CHANNELS.setKey, refusedSaved, (which: 'claude' | 'topdeck', key: string | null) => settings.setKey(which, key));
  handle(CHANNELS.pickFolder, refusedNull, () => settings.pickFolder());
  handle(CHANNELS.pickFile, refusedNull, () => settings.pickFile());
  handle(CHANNELS.backUpNow, refusedSaved, () => settings.backUpNow());
  handle(CHANNELS.restoreFrom, refusedSaved, (file: string) => settings.restoreFrom(String(file)));
  handle(CHANNELS.appSet, refusedSaved, (change: Parameters<SettingsService['setApp']>[0]) => settings.setApp(change));
  handle(CHANNELS.appCheckForUpdates, refusedSaved, () => checkForUpdates());
  handle(CHANNELS.appRestartToUpdate, refusedSaved, () => restartToUpdate());
  handle(CHANNELS.appExportDiagnostics, refusedSaved, () => exportDiagnostics());
  handle(CHANNELS.appRecheck, refusedSaved, () => settings.recheck());
  handle(CHANNELS.appFirstData, refusedSaved, () => settings.firstData());
  handle(CHANNELS.appFinishOnboarding, refusedSaved, () => settings.finishOnboarding());
  handle(CHANNELS.appShowDataFolder, refusedSaved, () => settings.showDataFolder());
  handle(CHANNELS.appShowLogs, refusedSaved, (): Saved => {
    settings.showLogs();
    return { ok: true };
  });
  let signals = 0;

  for (const signal of ['SIGTERM', 'SIGINT'] as const) {
    process.on(signal, () => {
      signals++;
      log.warn(`received ${signal}`, { count: signals });
      if (signals > 1) app.exit(1);
      else app.quit();
    });
  }
  process.on('uncaughtExceptionMonitor', (error) => {
    log.error('uncaught exception in the main process', { error });
  });
  process.on('unhandledRejection', (reason) => {
    log.error('unhandled rejection in the main process', { reason: String(reason) });
  });

  app.on('second-instance', () => {
    log.info('second launch: showing the window');
    window?.open();
    if (server.state.kind === 'failed') server.retry();
  });
  app.on('child-process-gone', (_event, details) => {
    if (details.reason === 'clean-exit') log.info('child process exited', { ...details });
    else log.error('child process gone', { ...details });
  });
  // Closing the window decides for itself (D13); never quit implicitly.
  app.on('window-all-closed', () => {});
  app.on('before-quit', (event) => {
    window?.setQuitting();
    settings.stopFirstData();
    if (readyToQuit) return;
    event.preventDefault();
    if (stopping) {
      quitAsked = true;
      return;
    }
    stopping = true;
    log.info('quitting: stopping the server');
    void server.stop().finally(() => {
      readyToQuit = true;
      app.quit();
    });
  });
  app.on('will-quit', () => {
    updates?.dispose();
    tray?.destroy();
    tray = null;
    log.info('quit');
    shellLog.close();
  });

  void app.whenReady().then(() => {
    log.info('displays', screen.getAllDisplays().map((display) => ({
      id: display.id,
      bounds: display.bounds,
      scaleFactor: display.scaleFactor,
      rotation: display.rotation,
      primary: display.id === screen.getPrimaryDisplay().id,
    })));
    app.getGPUInfo('basic').then(
      (gpu) => {
        const devices = (gpu as { gpuDevice?: Array<Record<string, unknown>> }).gpuDevice ?? [];
        log.info('gpu', devices.map((d) => ({ vendorId: d.vendorId, deviceId: d.deviceId, active: d.active, driver: d.driverVersion })));
      },
      (error: unknown) => log.warn('gpu info unavailable', { error: String(error) }),
    );

    Menu.setApplicationMenu(Menu.buildFromTemplate(appMenuTemplate(packaged)));
    window = new MainWindow(
      {
        BrowserWindow,
        openExternal: (url) => shell.openExternal(url),
        workAreas: () => screen.getAllDisplays().map((display) => display.workArea),
      },
      {
        store,
        log: shellLog.child('shell.window'),
        pageLog: shellLog.child('shell.page'),
        platform: process.platform,
        start: startMode(process.argv, process.platform),
        sinceStart: () => performance.now(),
        quit: () => app.quit(),
        preload: path.join(__dirname, 'preload.js'),
      },
    );

    tray = new StatusTray(
      {
        Tray,
        Menu,
        icon: (name) => {
          const image = nativeImage.createFromPath(path.join(__dirname, '..', 'assets', 'tray', `${name}.png`));
          if (image.isEmpty()) log.warn('tray icon missing', { name });
          return image;
        },
        fetch: (input, init) => fetch(input, init),
      },
      {
        open: () => window?.open(),
        settings: () => window?.open('/settings'),
        // The result shows in Settings' App section.
        checkForUpdates: () => {
          window?.open('/settings');
          void checkForUpdates();
        },
        restartToUpdate: () => {
          void restartToUpdate().then((result) => {
            if (!result.ok) dialog.showErrorBox(t('tray.menu.restartToUpdate'), result.error);
          });
        },
        exportDiagnostics: () => {
          void exportDiagnostics().then((result) => {
            if (!result.ok) void dialog.showErrorBox(t('diagnostics.title'), result.error);
          });
        },
        showLogs: () => {
          void shell.openPath(path.join(dataDir, 'logs')).then((error) => {
            if (error) log.warn('could not open the log folder', { error });
          });
        },
        quit: () => app.quit(),
      },
      shellLog.child('shell.tray'),
      process.platform,
      (port) => server.watcherStopped(port),
    );

    if (availability.available) {
      try {
        const { autoUpdater } = require('electron-updater') as typeof import('electron-updater');
        updates = new UpdateService({ updater: autoUpdater, log: updaterLog, onStatus: onUpdateStatus });
        updates.start(store.get().checkForUpdates ?? true);
      } catch (error) {
        updaterLog.error('the updater could not be loaded', { error: String(error) });
        updates?.dispose();
        updates = null;
        updatesOff = { state: 'unavailable', reason: 'unsupported' };
      }
      tray.setUpdate(updateMenu());
    }

    // The first page load reads the settings synchronously, so they come first.
    const settingsLoaded = settings.refresh();
    let previous: ServerState['kind'] = server.state.kind;
    let firstDataChecked = false;
    server.on('state', (state: ServerState) => {
      tray?.setServer(state);
      if (state.kind === 'ready') {
        void settingsLoaded.then(() => {
          window?.serverReady(state.port);
          if (!firstDataChecked) {
            firstDataChecked = true;
            void settings.startFirstDataIfMissing();
          }
        });
      }
      // The reason is already in the log (`server.ts`); the page names the file.
      else if (state.kind === 'failed') window?.showError(shellLog.scrub(logPath(dataDir)));
      else if (state.kind === 'starting' && previous === 'failed') window?.showLoading();
      previous = state.kind;
    });
    startUnlessBlocked();
  });
}
