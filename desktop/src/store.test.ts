import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { Logger } from './log';
import { mergePrefs, parseShellJson, ShellStore } from './store';

function recorder(): { log: Logger; lines: string[] } {
  const lines: string[] = [];
  const push = (message: string) => lines.push(message);
  return { log: { debug: push, info: push, warn: push, error: push }, lines };
}

describe('parsing shell.json', () => {
  it('keeps every known key of the right type', () => {
    const { prefs, dropped } = parseShellJson(
      JSON.stringify({
        port: 41234,
        bounds: { x: 10, y: 20, width: 1200, height: 800, maximized: false },
        keepRunningOnClose: true,
        autostart: false,
        checkForUpdates: true,
        diagnostic: false,
        onboarded: true,
      }),
    );
    expect(dropped).toEqual([]);
    expect(prefs).toEqual({
      port: 41234,
      bounds: { x: 10, y: 20, width: 1200, height: 800, maximized: false },
      keepRunningOnClose: true,
      autostart: false,
      checkForUpdates: true,
      diagnostic: false,
      onboarded: true,
    });
  });

  it('drops a value of the wrong type and keeps the rest', () => {
    const { prefs, dropped } = parseShellJson(
      JSON.stringify({ port: '41234', onboarded: 'yes', bounds: { width: -1, height: 800 }, autostart: true }),
    );
    expect(dropped.sort()).toEqual(['bounds', 'onboarded', 'port']);
    expect(prefs).toEqual({ autostart: true });
  });

  it('drops a port outside 1–65535', () => {
    expect(parseShellJson('{"port": 70000}').prefs).toEqual({});
    expect(parseShellJson('{"port": 0}').prefs).toEqual({});
    expect(parseShellJson('{"port": 4.5}').prefs).toEqual({});
  });

  it('keeps bounds without a position, and drops a half position', () => {
    expect(parseShellJson('{"bounds": {"width": 900, "height": 600, "x": 5}}').prefs).toEqual({
      bounds: { width: 900, height: 600 },
    });
  });

  it('carries keys it does not know', () => {
    expect(parseShellJson('{"fromANewerShell": {"a": 1}, "port": 41234}').prefs).toEqual({
      fromANewerShell: { a: 1 },
      port: 41234,
    });
  });

  it('refuses anything but an object', () => {
    expect(() => parseShellJson('[1, 2]')).toThrow();
    expect(() => parseShellJson('null')).toThrow();
    expect(() => parseShellJson('{"port":')).toThrow();
  });
});

describe('merging', () => {
  it('replaces bounds whole and removes a key patched to undefined', () => {
    const merged = mergePrefs(
      { port: 41234, bounds: { x: 1, y: 2, width: 900, height: 600 }, onboarded: true },
      { bounds: { width: 1000, height: 700 }, onboarded: undefined },
    );
    expect(merged).toEqual({ port: 41234, bounds: { width: 1000, height: 700 } });
  });

  it('leaves the original untouched', () => {
    const original = { port: 41234 };
    mergePrefs(original, { port: 41235 });
    expect(original).toEqual({ port: 41234 });
  });
});

describe('the store on disk', () => {
  let dir: string;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shell-store-'));
  });
  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('starts empty when there is no file, and silently', () => {
    const { log, lines } = recorder();
    expect(ShellStore.load(dir, log).get()).toEqual({});
    expect(lines).toEqual([]);
  });

  it('writes what it is given and reads it back at the next launch', () => {
    const store = ShellStore.load(path.join(dir, 'nested'));
    expect(store.update({ port: 41234 })).toBe(true);
    expect(store.update({ onboarded: true })).toBe(true);
    expect(ShellStore.load(path.join(dir, 'nested')).get()).toEqual({ port: 41234, onboarded: true });
    expect(fs.readdirSync(path.join(dir, 'nested'))).toEqual(['shell.json']);
  });

  it('keeps unknown keys through a write', () => {
    fs.writeFileSync(path.join(dir, 'shell.json'), '{"fromANewerShell": 1}');
    ShellStore.load(dir).update({ port: 41234 });
    expect(JSON.parse(fs.readFileSync(path.join(dir, 'shell.json'), 'utf8'))).toEqual({
      fromANewerShell: 1,
      port: 41234,
    });
  });

  it('moves a file that is not JSON aside and starts empty, saying so', () => {
    fs.writeFileSync(path.join(dir, 'shell.json'), '{not json');
    const { log, lines } = recorder();
    expect(ShellStore.load(dir, log).get()).toEqual({});
    expect(fs.readFileSync(path.join(dir, 'shell.json.bad'), 'utf8')).toBe('{not json');
    expect(fs.existsSync(path.join(dir, 'shell.json'))).toBe(false);
    expect(lines).toHaveLength(1);
  });

  it('warns about a dropped value', () => {
    fs.writeFileSync(path.join(dir, 'shell.json'), '{"port": "x"}');
    const { log, lines } = recorder();
    ShellStore.load(dir, log);
    expect(lines).toHaveLength(1);
  });

  it('keeps the merged values for this launch when the write fails', () => {
    const blocker = path.join(dir, 'file');
    fs.writeFileSync(blocker, '');
    const { log, lines } = recorder();
    const store = ShellStore.load(path.join(blocker, 'sub'), log);
    // A directory that cannot exist is unreadable, not missing: one warning for that.
    expect(lines).toHaveLength(1);
    expect(store.update({ port: 41234 })).toBe(false);
    expect(store.get()).toEqual({ port: 41234 });
    expect(lines).toHaveLength(2);
  });
});
