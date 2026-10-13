import * as path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  applyAutostart,
  applyFirstRun,
  autostartFile,
  desktopEntry,
  quoteExecArg,
  startMode,
  type AutostartDeps,
  type LoginItemSettings,
} from './autostart';
import type { Logger } from './log';

function recorder(): { log: Logger; lines: string[] } {
  const lines: string[] = [];
  const push = (message: string) => lines.push(message);
  return { log: { debug: push, info: push, warn: push, error: push }, lines };
}

function osDeps(over: Partial<AutostartDeps> = {}) {
  const { log, lines } = recorder();
  const items: LoginItemSettings[] = [];
  const written = new Map<string, string>();
  const made: string[] = [];
  const removed: string[] = [];
  const deps: AutostartDeps = {
    platform: 'linux',
    packaged: true,
    env: {},
    home: '/home/someone',
    setLoginItemSettings: (s) => items.push(s),
    mkdirSync: (d) => void made.push(d),
    writeFileSync: (f, t) => void written.set(f, t),
    rmSync: (f) => void removed.push(f),
    log,
    ...over,
  };
  return { deps, items, written, made, removed, lines };
}

describe('the login item on Windows', () => {
  it('is named Sensei Top and starts hidden', () => {
    const { deps, items } = osDeps({ platform: 'win32' });
    applyAutostart(deps, true);
    applyAutostart(deps, false);
    expect(items).toEqual([
      { openAtLogin: true, name: 'Sensei Top', args: ['--hidden'] },
      { openAtLogin: false, name: 'Sensei Top', args: ['--hidden'] },
    ]);
  });
});

describe('the autostart entry on Linux', () => {
  const appImage = '/opt/apps/Sensei Top.AppImage';

  it('is written under XDG_CONFIG_HOME, quoted, when turned on', () => {
    const { deps, written, made } = osDeps({ env: { APPIMAGE: appImage, XDG_CONFIG_HOME: '/xdg' } });
    applyAutostart(deps, true);
    const file = '/xdg/autostart/sensei-top.desktop';
    expect(made).toEqual(['/xdg/autostart']);
    expect([...written.keys()]).toEqual([file]);
    const text = written.get(file)!;
    expect(text.split('\n')).toEqual([
      '[Desktop Entry]',
      'Type=Application',
      'Name=Sensei Top',
      'Exec="/opt/apps/Sensei Top.AppImage" --hidden',
      'Terminal=false',
      'X-GNOME-Autostart-enabled=true',
      '',
    ]);
  });

  it('falls back to ~/.config when XDG_CONFIG_HOME is unset or empty', () => {
    expect(autostartFile({}, '/home/someone')).toBe('/home/someone/.config/autostart/sensei-top.desktop');
    expect(autostartFile({ XDG_CONFIG_HOME: '' }, '/home/someone')).toBe('/home/someone/.config/autostart/sensei-top.desktop');
  });

  it('is removed when turned off, and a missing file is fine', () => {
    const { deps, removed, lines } = osDeps({ env: { APPIMAGE: appImage, XDG_CONFIG_HOME: '/xdg' } });
    applyAutostart(deps, false);
    expect(removed).toEqual(['/xdg/autostart/sensei-top.desktop']);
    const missing = osDeps({
      env: { APPIMAGE: appImage },
      rmSync: () => {
        throw Object.assign(new Error('gone'), { code: 'ENOENT' });
      },
    });
    applyAutostart(missing.deps, false);
    expect(missing.lines).toEqual([]);
    expect(lines).toEqual([]);
  });

  it('ignores a relative XDG_CONFIG_HOME', () => {
    expect(autostartFile({ XDG_CONFIG_HOME: 'rel/cfg' }, '/home/someone')).toBe('/home/someone/.config/autostart/sensei-top.desktop');
  });

  it('warns when an ENOENT happens on a write', () => {
    const { deps, lines } = osDeps({
      env: { APPIMAGE: appImage },
      writeFileSync: () => {
        throw Object.assign(new Error('gone'), { code: 'ENOENT' });
      },
    });
    applyAutostart(deps, true);
    expect(lines).toEqual(['could not change the autostart entry']);
  });

  it.each([['/opt/100%/a.AppImage'], ['/opt/a\\b.AppImage']])('writes %s but warns', (image) => {
    const { deps, written, lines } = osDeps({ env: { APPIMAGE: image, XDG_CONFIG_HOME: '/xdg' } });
    applyAutostart(deps, true);
    expect(written.size).toBe(1);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toContain('stops GNOME and KDE from starting it');
  });

  it.each([['/opt/a\u0001b'], ['/opt/a\u007Fb'], ['/opt/a\nb']])('writes nothing for a control character %j', (image) => {
    const { deps, written, lines } = osDeps({ env: { APPIMAGE: image } });
    applyAutostart(deps, true);
    expect(written.size).toBe(0);
    expect(lines).toEqual(['autostart not written: the AppImage path has a control character']);
  });

  it('applies the quoting rules of the Desktop Entry spec', () => {
    expect(quoteExecArg('/a b/c')).toBe('"/a b/c"');
    expect(quoteExecArg('/a"b')).toBe('"/a\\\\"b"');
    expect(quoteExecArg('/a$b`c')).toBe('"/a\\\\$b\\\\`c"');
    expect(quoteExecArg('/a\\b')).toBe('"/a\\\\\\\\b"');
    expect(quoteExecArg('/100%')).toBe('"/100%%"');
    expect(desktopEntry('/x')).toContain('Exec="/x" --hidden');
  });

  it('does nothing but one INFO line without APPIMAGE', () => {
    const { deps, written, removed, items, lines } = osDeps();
    applyAutostart(deps, true);
    applyAutostart(deps, false);
    expect([written.size, removed.length, items.length]).toEqual([0, 0, 0]);
    expect(lines).toHaveLength(2);
    expect(lines[0]).toContain('only to the AppImage');
  });
});

describe('a development run', () => {
  it.each(['win32', 'linux'] as const)('never applies on %s', (platform) => {
    const { deps, written, removed, items, lines } = osDeps({
      platform,
      packaged: false,
      env: { APPIMAGE: '/x.AppImage' },
    });
    applyAutostart(deps, true);
    expect([written.size, removed.length, items.length]).toEqual([0, 0, 0]);
    expect(lines).toEqual(['autostart is recorded but not applied in a development run']);
  });
});

function firstRun(note: string | null, prefs: { autostart?: boolean; language?: string } = {}, rmFails = false) {
  const { log, lines } = recorder();
  let current = { ...prefs };
  const applied: boolean[] = [];
  const removed: string[] = [];
  const reads: string[] = [];
  applyFirstRun({
    dir: '/app',
    readFileSync: (file) => {
      reads.push(file);
      if (note === null) throw Object.assign(new Error('none'), { code: 'ENOENT' });
      return note;
    },
    rmSync: (file) => {
      if (rmFails) throw new Error('locked');
      removed.push(file);
    },
    store: {
      get: () => current,
      update: (patch: { autostart?: boolean; language?: string }) => {
        current = { ...current, ...patch };
        return true;
      },
    } as never,
    apply: (on) => void applied.push(on),
    log,
  });
  return { applied, removed, reads, lines, prefs: () => current };
}

describe('first-run.json', () => {
  it('seeds the language when none is chosen', () => {
    const run = firstRun('{"autostart": true, "language": "pt-BR"}');
    expect(run.prefs().language).toBe('pt-BR');
    expect(run.applied).toEqual([true]);
    expect(run.removed).toEqual([path.join('/app', 'first-run.json')]);
  });

  it('leaves a language already chosen alone, and still applies autostart', () => {
    const run = firstRun('{"autostart": true, "language": "pt-BR"}', { language: 'en' });
    expect(run.prefs().language).toBe('en');
    expect(run.applied).toEqual([true]);
  });

  it('ignores a language it does not know, with a warning', () => {
    const run = firstRun('{"autostart": false, "language": "fr"}');
    expect(run.prefs().language).toBeUndefined();
    expect(run.lines.some((line) => line.includes('"language"'))).toBe(true);
    expect(run.applied).toEqual([false]);
    expect(run.removed).toEqual([path.join('/app', 'first-run.json')]);
  });

  it('applies the language when autostart is absent', () => {
    const run = firstRun('{"language": "en"}');
    expect(run.prefs().language).toBe('en');
    expect(run.applied).toEqual([]);
    expect(run.removed).toEqual([path.join('/app', 'first-run.json')]);
  });

  it('applies the language when autostart was already chosen', () => {
    const run = firstRun('{"autostart": true, "language": "pt-BR"}', { autostart: false });
    expect(run.prefs()).toEqual({ autostart: false, language: 'pt-BR' });
    expect(run.applied).toEqual([]);
  });

  it('is read beside the executable, applied, stored and deleted', () => {
    const run = firstRun('{"autostart": true}');
    expect(run.reads).toEqual([path.join('/app', 'first-run.json')]);
    expect(run.applied).toEqual([true]);
    expect(run.prefs().autostart).toBe(true);
    expect(run.removed).toEqual([path.join('/app', 'first-run.json')]);
  });

  it('reads a note that starts with a byte order mark', () => {
    const run = firstRun('\uFEFF{"autostart": true}');
    expect(run.applied).toEqual([true]);
  });

  it('applies an unticked box too', () => {
    const run = firstRun('{"autostart": false}');
    expect(run.applied).toEqual([false]);
    expect(run.prefs().autostart).toBe(false);
  });

  it('is deleted but not applied when the user already chose', () => {
    const run = firstRun('{"autostart": true}', { autostart: false });
    expect(run.applied).toEqual([]);
    expect(run.prefs().autostart).toBe(false);
    expect(run.removed).toEqual([path.join('/app', 'first-run.json')]);
  });

  it('does nothing when absent', () => {
    const run = firstRun(null);
    expect(run.applied).toEqual([]);
    expect(run.removed).toEqual([]);
    expect(run.lines).toEqual([]);
  });

  it.each([['{nope'], ['{"autostart": "yes"}'], ['{}'], ['[true]'], ['null']])('warns, deletes and applies nothing for %s', (text) => {
    const run = firstRun(text);
    expect(run.applied).toEqual([]);
    expect(run.prefs().autostart).toBeUndefined();
    expect(run.removed).toEqual([path.join('/app', 'first-run.json')]);
    expect(run.lines).toHaveLength(1);
  });

  it('warns and carries on when the delete fails', () => {
    const run = firstRun('{"autostart": true}', {}, true);
    expect(run.lines).toContain('first-run.json could not be deleted');
    expect(run.applied).toEqual([true]);
  });
});

describe('starting with the system', () => {
  it.each([
    [['app'], 'win32', 'show'],
    [['app', '--hidden'], 'win32', 'hidden'],
    [['app', '--hidden'], 'linux', 'minimized'],
    [['app'], 'linux', 'show'],
  ] as const)('%j on %s: %s', (argv, platform, mode) => {
    expect(startMode(argv, platform)).toBe(mode);
  });
});
