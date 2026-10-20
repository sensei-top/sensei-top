// Start with the system (release plan 6, D25). Electron-free: every outside
// effect is an argument, so vitest runs it under plain Node.
//
// - Windows: Electron's login item, named exactly `Sensei Top` (the NSIS
//   uninstaller deletes that `Run` value), started with `--hidden`.
// - Linux: `app.setLoginItemSettings` does nothing there, so the shell writes
//   an XDG autostart entry itself, and only for the AppImage (`APPIMAGE`
//   names the file to start; any other run has no stable path). The tarball is
//   such a run, so `canAutostart` (`settings.ts`) is false there: the page
//   shows no toggle and onboarding does not ask.
// - A development run never applies either.
// - `first-run.json` is the installer's note of the checkbox it asked (D25) and
//   of the language it ran in (plan 18, S7): each applied once if the user has
//   not chosen that yet, independently, then the note is deleted.

import * as path from 'node:path';
import type { Logger } from './log';
import type { ShellStore } from './store';
import type { StartMode } from './window';

export const LOGIN_ITEM_NAME = 'Sensei Top';
export const HIDDEN_FLAG = '--hidden';
export const FIRST_RUN_NAME = 'first-run.json';
export const DESKTOP_FILE = 'sensei-top.desktop';

export interface LoginItemSettings {
  openAtLogin: boolean;
  name?: string;
  args?: string[];
}

export interface AutostartDeps {
  platform: NodeJS.Platform;
  packaged: boolean;
  env: NodeJS.ProcessEnv;
  home: string;
  setLoginItemSettings: (settings: LoginItemSettings) => void;
  mkdirSync: (dir: string) => void;
  writeFileSync: (file: string, text: string) => void;
  rmSync: (file: string) => void;
  log: Logger;
}

/** D25: hidden on Windows (the tray), minimized on Linux (GNOME may draw no tray). */
export function startMode(argv: readonly string[], platform: NodeJS.Platform): StartMode {
  if (!argv.includes(HIDDEN_FLAG)) return 'show';
  return platform === 'linux' ? 'minimized' : 'hidden';
}

/** The Desktop Entry spec's two layers for one `Exec` argument: the quoting
 *  layer escapes `"`, `` ` ``, `$` and `\` with a backslash, and the string
 *  layer then doubles every backslash; `%` is the field-code introducer. */
export function quoteExecArg(value: string): string {
  const quoted = value.replace(/[\\"`$]/g, (c) => `\\${c}`);
  return `"${quoted.replace(/\\/g, '\\\\').replace(/%/g, '%%')}"`;
}

export function desktopEntry(appImage: string): string {
  return [
    '[Desktop Entry]',
    'Type=Application',
    `Name=${LOGIN_ITEM_NAME}`,
    `Exec=${quoteExecArg(appImage)} ${HIDDEN_FLAG}`,
    'Terminal=false',
    'X-GNOME-Autostart-enabled=true',
    '',
  ].join('\n');
}

export function autostartFile(env: NodeJS.ProcessEnv, home: string): string {
  // The XDG spec ignores a relative XDG_CONFIG_HOME.
  const xdg = env.XDG_CONFIG_HOME;
  const config = xdg && path.posix.isAbsolute(xdg) ? xdg : path.posix.join(home, '.config');
  return path.posix.join(config, 'autostart', DESKTOP_FILE);
}

/** Applies the choice to the operating system. Never throws. */
export function applyAutostart(deps: AutostartDeps, on: boolean): void {
  const { log } = deps;
  if (!deps.packaged) {
    log.info('autostart is recorded but not applied in a development run', { on });
    return;
  }
  if (deps.platform === 'win32') {
    deps.setLoginItemSettings({ openAtLogin: on, name: LOGIN_ITEM_NAME, args: [HIDDEN_FLAG] });
    return;
  }
  if (deps.platform !== 'linux') {
    log.info('autostart is recorded but not applied on this platform', { on, platform: deps.platform });
    return;
  }
  const appImage = deps.env.APPIMAGE;
  if (!appImage) {
    log.info('autostart is recorded but applies only to the AppImage on Linux', { on });
    return;
  }
  if (on) {
    if (/[\u0000-\u001F\u007F]/.test(appImage)) {
      log.warn('autostart not written: the AppImage path has a control character');
      return;
    }
    if (/[%\\]/.test(appImage)) {
      log.warn('autostart written, but a % in the path stops GNOME and KDE from starting it, and a backslash stops KDE');
    }
  }
  const file = autostartFile(deps.env, deps.home);
  try {
    if (on) {
      deps.mkdirSync(path.dirname(file));
      deps.writeFileSync(file, desktopEntry(appImage));
    } else {
      deps.rmSync(file);
    }
  } catch (error) {
    // turning it off when it was never on is fine
    if (!on && (error as NodeJS.ErrnoException).code === 'ENOENT') return;
    log.warn('could not change the autostart entry', { on, error: String(error) });
  }
}

export interface FirstRunDeps {
  /** The executable's directory: where the installer left the note. */
  dir: string;
  readFileSync: (file: string) => string;
  rmSync: (file: string) => void;
  store: Pick<ShellStore, 'get' | 'update'>;
  apply: (on: boolean) => void;
  log: Logger;
}

/** Reads the installer's note once, applies each field the user has not chosen,
 *  and deletes it either way. A note that is not understood applies nothing. */
export function applyFirstRun(deps: FirstRunDeps): void {
  const { log } = deps;
  const file = path.join(deps.dir, FIRST_RUN_NAME);
  let text: string;
  try {
    text = deps.readFileSync(file);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
      log.warn('first-run.json could not be read', { error: String(error) });
    }
    return;
  }
  let choice: boolean | null = null;
  let language: 'en' | 'pt-BR' | null = null;
  try {
    const parsed: unknown = JSON.parse(text.replace(/^\uFEFF/, ''));
    const note = typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : {};
    if (typeof note.autostart === 'boolean') choice = note.autostart;
    else log.warn('first-run.json has no boolean "autostart"; ignored');
    if (note.language === 'en' || note.language === 'pt-BR') language = note.language;
    else if (note.language !== undefined) log.warn('first-run.json has a "language" that is not en or pt-BR; ignored');
  } catch (error) {
    log.warn('first-run.json is not valid JSON; ignored', { error: String(error) });
  }
  try {
    deps.rmSync(file);
  } catch (error) {
    log.warn('first-run.json could not be deleted', { error: String(error) });
  }
  if (language !== null) {
    if (deps.store.get().language !== undefined) {
      log.info('first-run.json language ignored: a language was already chosen');
    } else {
      deps.store.update({ language });
      log.info('first-run.json applied', { language });
    }
  }
  if (choice === null) return;
  if (deps.store.get().autostart !== undefined) {
    log.info('first-run.json ignored: autostart was already chosen');
    return;
  }
  deps.store.update({ autostart: choice });
  log.info('first-run.json applied', { autostart: choice });
  deps.apply(choice);
}
