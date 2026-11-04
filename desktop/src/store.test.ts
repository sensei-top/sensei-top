import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { Logger } from './log';
import { mergePrefs, parseShellJson, settleAiFeatures, ShellStore } from './store';

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
        aiFeatures: false,
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
      aiFeatures: false,
    });
  });

  it('keeps a well-formed contribute answer, keeps null, and drops anything else', () => {
    const answer = { yes: true, policyVersion: '2026-11-01', answeredAt: '2026-11-02T00:00:00.000Z', ageConfirmed: true };
    expect(parseShellJson(JSON.stringify({ contribute: answer }))).toEqual({ prefs: { contribute: answer }, dropped: [] });
    expect(parseShellJson(JSON.stringify({ contribute: null }))).toEqual({ prefs: { contribute: null }, dropped: [] });
    expect(parseShellJson(JSON.stringify({ contribute: { ...answer, yes: 'yes' } }))).toEqual({ prefs: {}, dropped: ['contribute'] });
    expect(parseShellJson(JSON.stringify({ contribute: true }))).toEqual({ prefs: {}, dropped: ['contribute'] });
  });

  it('keeps consentErrors when it is a boolean and drops anything else', () => {
    expect(parseShellJson(JSON.stringify({ consentErrors: true }))).toEqual({ prefs: { consentErrors: true }, dropped: [] });
    expect(parseShellJson(JSON.stringify({ consentErrors: 'yes' }))).toEqual({ prefs: {}, dropped: ['consentErrors'] });
  });

  it('drops a value of the wrong type and keeps the rest', () => {
    const { prefs, dropped } = parseShellJson(
      JSON.stringify({ port: '41234', onboarded: 'yes', bounds: { width: -1, height: 800 }, autostart: true, aiFeatures: null }),
    );
    expect(dropped.sort()).toEqual(['aiFeatures', 'bounds', 'onboarded', 'port']);
    expect(prefs).toEqual({ autostart: true });
  });

  it('keeps plays, drops unknown entries with a warning, reads empty or missing as absent', () => {
    expect(parseShellJson(JSON.stringify({ plays: ['mtgo'] }))).toEqual({ prefs: { plays: ['mtgo'] }, dropped: [] });
    expect(parseShellJson(JSON.stringify({ plays: ['mtgo', 'arena'] })).prefs.plays).toEqual(['arena', 'mtgo']);
    const junk = parseShellJson(JSON.stringify({ plays: ['arena', 'paper', 3] }));
    expect(junk.prefs.plays).toEqual(['arena']);
    expect(junk.dropped).toEqual(['plays']);
    const allJunk = parseShellJson(JSON.stringify({ plays: 'arena' }));
    expect(allJunk.prefs).toEqual({});
    expect(allJunk.dropped).toEqual(['plays']);
    expect(parseShellJson(JSON.stringify({ plays: [] }))).toEqual({ prefs: {}, dropped: [] });
    expect(parseShellJson('{}').prefs.plays).toBeUndefined();
  });

  it('keeps each of the three languages', () => {
    for (const language of ['system', 'en', 'pt-BR']) {
      const { prefs, dropped } = parseShellJson(JSON.stringify({ language }));
      expect(prefs).toEqual({ language });
      expect(dropped).toEqual([]);
    }
  });

  it('drops a language outside the list, a number and null, naming the key', () => {
    for (const value of ['fr', 7, null]) {
      const { prefs, dropped } = parseShellJson(JSON.stringify({ language: value }));
      expect(prefs).toEqual({});
      expect(dropped).toEqual(['language']);
    }
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

  it('round-trips plays through the store', () => {
    expect(ShellStore.load(dir).update({ plays: ['mtgo'] })).toBe(true);
    expect(ShellStore.load(dir).get().plays).toEqual(['mtgo']);
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

describe('deciding aiFeatures once (plan 40D, DD6)', () => {
  let dir: string;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shell-store-'));
  });
  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });
  const onDisk = () => JSON.parse(fs.readFileSync(path.join(dir, 'shell.json'), 'utf8')) as Record<string, unknown>;

  it('writes true when onboarding was already finished', () => {
    fs.writeFileSync(path.join(dir, 'shell.json'), '{"onboarded": true}');
    expect(settleAiFeatures(ShellStore.load(dir))).toBe(true);
    expect(onDisk()).toEqual({ onboarded: true, aiFeatures: true });
  });

  it('leaves an install that is not onboarded undecided, a database beside it or not', () => {
    fs.writeFileSync(path.join(dir, 'shell.json'), '{"onboarded": false}');
    fs.writeFileSync(path.join(dir, 'sensei-top.db'), '');
    expect(settleAiFeatures(ShellStore.load(dir))).toBeUndefined();
    expect(onDisk()).toEqual({ onboarded: false });
  });

  it('leaves a fresh install undecided, and writes nothing', () => {
    const { log, lines } = recorder();
    const store = ShellStore.load(dir);
    expect(settleAiFeatures(store, log)).toBeUndefined();
    expect(store.get()).toEqual({});
    expect(fs.existsSync(path.join(dir, 'shell.json'))).toBe(false);
    expect(lines).toHaveLength(1);
  });

  it('never decides a value that is there again', () => {
    fs.writeFileSync(path.join(dir, 'shell.json'), '{"onboarded": true, "aiFeatures": false}');
    const before = fs.readFileSync(path.join(dir, 'shell.json'), 'utf8');
    expect(settleAiFeatures(ShellStore.load(dir))).toBe(false);
    expect(fs.readFileSync(path.join(dir, 'shell.json'), 'utf8')).toBe(before);
  });

  it('a set persists to the next launch', () => {
    const store = ShellStore.load(dir);
    expect(settleAiFeatures(store)).toBeUndefined();
    expect(store.update({ aiFeatures: false, onboarded: true })).toBe(true);
    expect(settleAiFeatures(ShellStore.load(dir))).toBe(false);
    expect(onDisk()).toEqual({ aiFeatures: false, onboarded: true });
  });

  it('is decided in main.ts before the settings are first read and published', () => {
    const source = fs.readFileSync(path.join(__dirname, 'main.ts'), 'utf8');
    expect(source.split('settleAiFeatures(').length - 1).toBe(1);
    const decided = source.indexOf('settleAiFeatures(store');
    expect(decided).toBeGreaterThan(-1);
    for (const later of ['new SettingsService(', 'settings.refresh()']) {
      const at = source.indexOf(later);
      expect(at, later).toBeGreaterThan(decided);
    }
  });
});

describe('installId', () => {
  it('keeps a non-empty string and drops an empty one or a number', () => {
    expect(parseShellJson('{"installId":"abc"}')).toEqual({ prefs: { installId: 'abc' }, dropped: [] });
    for (const bad of ['""', '42']) {
      const { prefs, dropped } = parseShellJson(`{"installId":${bad}}`);
      expect(prefs.installId).toBeUndefined();
      expect(dropped).toEqual(['installId']);
    }
  });
});
