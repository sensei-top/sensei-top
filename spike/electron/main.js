// Throwaway shell spike for release plan 6 phase 0. It answers the plan's
// criteria list with log lines instead of opinions: every window event, page
// message, process exit and (on Linux under XWayland) Arena's window state
// goes to one file. Nothing here is the real shell.
'use strict';

const { app, BrowserWindow, Tray, Menu, globalShortcut, screen, nativeImage, shell } = require('electron');
const { execFile } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const STARTED = process.hrtime.bigint();

function arg(name, fallback) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : fallback;
}

const BASE_URL = arg('url', 'http://127.0.0.1:8765').replace(/\/$/, '');
const OVERLAY_ROUTE = arg('overlay-route', '/design/surfaces');
const OVERLAY_LEVEL = arg('overlay-level', 'screen-saver'); // or 'none' to skip setAlwaysOnTop
const OVERLAY_FOCUSABLE = arg('overlay-focusable', '0') === '1';
const SHOW_MAIN = arg('main', '1') !== '0'; // --main=0 keeps the dashboard hidden, so launching takes no focus
const HOTKEY_INTERACT = 'Control+Alt+O';
const HOTKEY_HIDE = 'Control+Alt+H';

// ---- diagnostics -----------------------------------------------------------

const SESSION = crypto.randomBytes(4).toString('hex');
const HOME = os.homedir();
let logStream = null;

function scrub(text) {
  return String(text).split(HOME).join('~');
}

function log(source, level, message, fields) {
  const extra = fields ? ' ' + scrub(JSON.stringify(fields)) : '';
  const line = `${new Date().toISOString()} session=${SESSION} ${source} ${level} ${scrub(message)}${extra}\n`;
  process.stdout.write(line);
  if (logStream) logStream.write(line);
}

function openLog() {
  const dir = app.getPath('logs');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'shell-spike.log');
  logStream = fs.createWriteStream(file, { flags: 'a' });
  return file;
}

function sinceStartMs() {
  return Number((process.hrtime.bigint() - STARTED) / 1000000n);
}

function watchContents(name, contents) {
  const loadStart = new Map();
  contents.on('did-start-navigation', (details) => {
    if (details.isMainFrame) loadStart.set(details.url, Date.now());
  });
  contents.on('did-finish-load', () => {
    const url = contents.getURL();
    const began = loadStart.get(url);
    log(name, 'info', 'page loaded', { path: new URL(url).pathname, ms: began ? Date.now() - began : null });
  });
  contents.on('did-fail-load', (_e, code, description, url, isMainFrame) => {
    log(name, 'error', 'load failed', { code, description, url, isMainFrame });
  });
  contents.on('console-message', (event) => {
    log(name, 'page', `console.${event.level}: ${event.message}`, { source: event.sourceId, line: event.lineNumber });
  });
  contents.on('render-process-gone', (_e, details) => {
    log(name, 'error', 'renderer gone', details);
  });
  contents.on('unresponsive', () => log(name, 'warn', 'renderer unresponsive'));
  contents.on('responsive', () => log(name, 'info', 'renderer responsive again'));
}

function watchWindow(name, win) {
  const bounds = () => log(name, 'info', 'bounds', win.getBounds());
  win.on('moved', bounds);
  win.on('resized', bounds);
  win.on('show', () => log(name, 'info', 'shown'));
  win.on('hide', () => log(name, 'info', 'hidden'));
  win.on('focus', () => log(name, 'info', 'focus gained'));
  win.on('blur', () => log(name, 'info', 'focus lost'));
  win.on('always-on-top-changed', (_e, onTop) => log(name, 'info', 'always-on-top changed', { onTop }));
  watchContents(name, win.webContents);
}

function nativeId(win) {
  const handle = win.getNativeWindowHandle();
  if (process.platform === 'win32') return '0x' + handle.readBigUInt64LE(0).toString(16);
  if (handle.length >= 8) return '0x' + handle.readBigUInt64LE(0).toString(16);
  return '0x' + handle.readUInt32LE(0).toString(16);
}

function logMetrics(reason) {
  const byType = {};
  let totalKb = 0;
  for (const m of app.getAppMetrics()) {
    const kb = m.memory.workingSetSize;
    byType[m.type] = (byType[m.type] || 0) + Math.round(kb / 1024);
    totalKb += kb;
  }
  log('shell', 'info', 'memory MB by process type', { reason, totalMB: Math.round(totalKb / 1024), ...byType });
}

// ---- Linux: Arena's window, read through the X server ----------------------
// Under Proton, Arena is an XWayland client, as this shell is when forced to
// x11. xprop is the only X tool on the author's machine, so this reads
// _NET_CLIENT_LIST_STACKING (bottom to top) and each window's class, name and
// state, and logs whenever Arena's state or the stacking order changes.

function xprop(args) {
  return new Promise((resolve) => {
    execFile('xprop', args, { timeout: 2000 }, (err, stdout) => resolve(err ? null : stdout));
  });
}

let lastArena = '';

async function pollArena() {
  const root = await xprop(['-root', '_NET_CLIENT_LIST_STACKING', '_NET_ACTIVE_WINDOW']);
  if (!root) return;
  const stacking = (root.match(/_NET_CLIENT_LIST_STACKING\(WINDOW\): window id # (.*)/) || [])[1];
  const active = (root.match(/_NET_ACTIVE_WINDOW\(WINDOW\): window id # (\S+)/) || [])[1] || null;
  if (!stacking) return;
  const ids = stacking.split(',').map((s) => s.trim());
  let arena = null;
  for (const id of ids) {
    const props = await xprop(['-id', id, 'WM_CLASS', '_NET_WM_NAME', '_NET_WM_STATE']);
    if (props && /mtga/i.test(props)) {
      arena = {
        id,
        class: (props.match(/WM_CLASS\(STRING\) = (.*)/) || [])[1] || null,
        name: (props.match(/_NET_WM_NAME\(UTF8_STRING\) = (.*)/) || [])[1] || null,
        state: (props.match(/_NET_WM_STATE\(ATOM\) = (.*)/) || [])[1] || '(none)',
      };
      break;
    }
  }
  const overlayId = overlay && !overlay.isDestroyed() ? nativeId(overlay) : null;
  const norm = (id) => (id ? BigInt(id).toString(16) : null);
  const order = ids.map(norm);
  const summary = {
    arena,
    arenaActive: arena ? norm(active) === norm(arena.id) : false,
    arenaIndex: arena ? order.indexOf(norm(arena.id)) : null,
    overlayIndex: overlayId ? order.indexOf(norm(overlayId)) : null,
    windows: ids.length,
  };
  summary.overlayAboveArena =
    summary.arenaIndex !== null && summary.overlayIndex !== null && summary.overlayIndex > summary.arenaIndex;
  const key = JSON.stringify(summary);
  if (key !== lastArena) {
    lastArena = key;
    log('arena', 'info', arena ? 'arena window state' : 'arena window not found', summary);
  }
}

// ---- windows ---------------------------------------------------------------

let mainWindow = null;
let overlay = null;
let tray = null;
let clickThrough = true;
let overlayCovers = false;

const OVERLAY_CSS = `
  html, body, #root { background: transparent !important; }
  html { outline: 2px dashed rgba(244, 182, 228, 0.9); outline-offset: -2px; }
  html { scrollbar-width: none; user-select: none; }
  ::-webkit-scrollbar { display: none; }
`;

function createMain() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    show: false,
    title: 'Sensei Top (shell spike)',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  watchWindow('main', mainWindow);
  mainWindow.once('ready-to-show', () => {
    if (SHOW_MAIN) mainWindow.show();
    log('main', 'info', 'ready-to-show', { msSinceProcessStart: sinceStartMs() });
  });
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      mainWindow.hide();
      log('main', 'info', 'close pressed: hidden to tray');
    }
  });
  mainWindow.loadURL(BASE_URL + '/');
}

function overlayBounds() {
  const area = screen.getPrimaryDisplay().bounds;
  if (overlayCovers) return area;
  const width = 420;
  const height = Math.min(760, area.height - 80);
  return { x: area.x + area.width - width - 24, y: area.y + 56, width, height };
}

function createOverlay() {
  overlay = new BrowserWindow({
    ...overlayBounds(),
    show: false,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    hasShadow: false,
    resizable: false,
    skipTaskbar: true,
    focusable: OVERLAY_FOCUSABLE,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
    ...JSON.parse(arg('overlay-opts', '{}')),
  });
  if (OVERLAY_LEVEL !== 'none') overlay.setAlwaysOnTop(true, OVERLAY_LEVEL);
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  applyClickThrough();
  watchWindow('overlay', overlay);
  overlay.webContents.on('did-finish-load', () => overlay.webContents.insertCSS(OVERLAY_CSS));
  overlay.once('ready-to-show', () => {
    overlay.showInactive();
    log('overlay', 'info', 'ready-to-show', {
      msSinceProcessStart: sinceStartMs(),
      nativeId: nativeId(overlay),
      bounds: overlay.getBounds(),
    });
  });
  overlay.loadURL(BASE_URL + OVERLAY_ROUTE);
}

function applyClickThrough() {
  overlay.setIgnoreMouseEvents(clickThrough, { forward: true });
  if (!OVERLAY_FOCUSABLE) overlay.setFocusable(!clickThrough);
  log('overlay', 'info', 'click-through set', { clickThrough });
  refreshTray();
}

function toggleOverlayVisible(source) {
  if (overlay.isVisible()) overlay.hide();
  else overlay.showInactive();
  log('overlay', 'info', 'visibility toggled', { source, visible: overlay.isVisible() });
  refreshTray();
}

// ---- tray ------------------------------------------------------------------

function trayIcon() {
  // A 16 px pink square drawn in memory; the spike ships no image files.
  const size = 16;
  const pixels = Buffer.alloc(size * size * 4);
  for (let i = 0; i < size * size; i++) pixels.set([0xe4, 0xb6, 0xf4, 0xff], i * 4);
  return nativeImage.createFromBitmap(pixels, { width: size, height: size });
}

function refreshTray() {
  if (!tray) return;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: 'Open dashboard', click: () => mainWindow.show() },
      { label: overlay?.isVisible() ? 'Hide overlay' : 'Show overlay', click: () => toggleOverlayVisible('tray') },
      {
        label: 'Click-through',
        type: 'checkbox',
        checked: clickThrough,
        click: () => {
          clickThrough = !clickThrough;
          applyClickThrough();
        },
      },
      {
        label: 'Overlay covers the screen',
        type: 'checkbox',
        checked: overlayCovers,
        click: () => {
          overlayCovers = !overlayCovers;
          overlay.setBounds(overlayBounds());
          refreshTray();
        },
      },
      { type: 'separator' },
      { label: 'Log memory now', click: () => logMetrics('tray') },
      { label: 'Open log folder', click: () => shell.openPath(app.getPath('logs')) },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() },
    ]),
  );
}

// ---- startup ---------------------------------------------------------------

if (!app.requestSingleInstanceLock()) {
  process.stdout.write('shell spike: another instance is running; it was asked to focus.\n');
  app.exit(0);
} else {
  app.on('second-instance', () => {
    log('shell', 'info', 'second launch: focusing the running instance');
    mainWindow.show();
    mainWindow.focus();
  });

  app.on('child-process-gone', (_e, details) => log('shell', 'error', 'child process gone', details));
  app.on('before-quit', () => {
    app.isQuitting = true;
  });
  app.on('will-quit', () => {
    logMetrics('quit');
    globalShortcut.unregisterAll();
    log('shell', 'info', 'quitting');
  });
  app.on('window-all-closed', () => {});

  app.whenReady().then(async () => {
    const file = openLog();
    log('shell', 'info', 'start', {
      log: file,
      electron: process.versions.electron,
      chrome: process.versions.chrome,
      node: process.versions.node,
      os: `${os.type()} ${os.release()} ${os.arch()}`,
      session: process.env.XDG_SESSION_TYPE || null,
      desktop: process.env.XDG_CURRENT_DESKTOP || null,
      ozonePlatform: app.commandLine.getSwitchValue('ozone-platform') || '(default)',
      url: BASE_URL,
      overlayRoute: OVERLAY_ROUTE,
      overlayLevel: OVERLAY_LEVEL,
      overlayFocusable: OVERLAY_FOCUSABLE,
    });
    log('shell', 'info', 'displays', screen.getAllDisplays().map((d) => ({
      id: d.id, bounds: d.bounds, scaleFactor: d.scaleFactor, rotation: d.rotation, primary: d.id === screen.getPrimaryDisplay().id,
    })));
    app.getGPUInfo('basic').then((gpu) => log('shell', 'info', 'gpu', {
      devices: gpu.gpuDevice?.map((d) => ({ vendorId: d.vendorId, deviceId: d.deviceId, active: d.active, driver: d.driverVersion })),
    }));
    screen.on('display-metrics-changed', (_e, display, changed) => log('shell', 'info', 'display changed', { id: display.id, changed, bounds: display.bounds, scaleFactor: display.scaleFactor }));

    createMain();
    createOverlay();

    tray = new Tray(trayIcon());
    tray.setToolTip('Sensei Top (shell spike)');
    refreshTray();
    log('shell', 'info', 'tray created');

    for (const [accelerator, action] of [
      [HOTKEY_INTERACT, () => {
        clickThrough = !clickThrough;
        applyClickThrough();
      }],
      [HOTKEY_HIDE, () => toggleOverlayVisible('hotkey')],
    ]) {
      const ok = globalShortcut.register(accelerator, () => {
        log('hotkey', 'info', 'fired', { accelerator });
        action();
      });
      log('hotkey', ok ? 'info' : 'error', ok ? 'registered' : 'registration refused', { accelerator });
    }

    const autoQuit = Number(arg('auto-quit', 0));
    if (autoQuit > 0) {
      setTimeout(() => {
        logMetrics('before auto-quit');
        app.quit();
      }, autoQuit * 1000);
    }

    setInterval(() => logMetrics('interval'), 30000).unref();
    if (process.platform === 'linux') {
      setInterval(() => pollArena().catch((err) => log('arena', 'error', String(err))), 1000).unref();
    }
  });
}
