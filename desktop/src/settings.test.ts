import * as fs from 'node:fs';
import * as path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  CHANNELS,
  diagnosticsArgs,
  formatListing,
  interpretRestore,
  keyCommand,
  parseBackupBytes,
  parseConfigJson,
  parseDoctorArena,
  planAppChange,
  filePairLines,
  planChange,
  restoreLeftovers,
  restoreLeftoversMessage,
  SettingsService,
  toAppSettings,
  toShellSettings,
  trustedSender,
  type BridgeSettings,
  type SettingsDeps,
} from './settings';
import type { ShellJson } from './store';
import type { UpdateStatus } from './updater';

// The shape `sensei-top config --json` prints (cli.py::_config_json); the
// values are made up.
const CONFIG = {
  config_path: '/cfg/config.toml',
  arena: { log: null, date_order: 'auto' },
  mtgo: { handle: 'someone', dir: '/mtgo/logs', deck_dir: null },
  backup: { dir: '/data/backups', keep: 3 },
  claude: { key_set: true, key_source: 'keyring', model: 'claude-opus-5-5', effort: 'high' },
  topdeck: { key_set: false, key_source: null },
  models: [{ value: 'claude-opus-5-5', label: 'Opus 5.5' }],
};
// The shape of `doctor --json`'s arena_log part (doctor.py::report).
const DOCTOR = { arena_log: { path: '/games/Player.log', source: 'autodetect', detailed_logs: 'unknown' } };

describe('config --json to ShellSettings', () => {
  it('maps every field the page shows', () => {
    const settings = toShellSettings(parseConfigJson(JSON.stringify(CONFIG)), parseDoctorArena(JSON.stringify(DOCTOR)), {
      dataDir: '/data',
      backupInFolder: 2,
      lastBackup: null,
    });
    expect(settings).toEqual({
      sources: {
        arenaLog: { path: '/games/Player.log', found: true },
        dateOrder: 'auto',
        mtgoHandle: 'someone',
        mtgoDir: '/mtgo/logs',
        dataDir: '/data',
      },
      writing: {
        claudeKey: true,
        topdeckKey: false,
        model: 'claude-opus-5-5',
        models: [{ value: 'claude-opus-5-5', label: 'Opus 5.5' }],
      },
      backup: { dir: '/data/backups', keep: 3, last: null, inFolder: 2 },
      sharing: null,
    });
  });

  it('is found only when nobody chose the path', () => {
    const config = parseConfigJson(JSON.stringify({ ...CONFIG, arena: { log: '/mine/Player.log', date_order: 'dmy' } }));
    const extras = { dataDir: '/d', backupInFolder: 0, lastBackup: null };
    const chosen = toShellSettings(config, { path: '/mine/Player.log', source: 'config' }, extras);
    expect(chosen.sources.arenaLog).toEqual({ path: '/mine/Player.log', found: false });
    expect(chosen.sources.dateOrder).toBe('dmy');
    // doctor failing costs `found` and nothing else
    const noDoctor = toShellSettings(config, null, extras);
    expect(noDoctor.sources.arenaLog).toEqual({ path: '/mine/Player.log', found: false });
  });

  it('is not found when a path is configured, even if doctor says autodetect', () => {
    const config = parseConfigJson(JSON.stringify({ ...CONFIG, arena: { log: '/mine/Player.log', date_order: 'auto' } }));
    const settings = toShellSettings(config, { path: '/mine/Player.log', source: 'autodetect' }, { dataDir: '/d', backupInFolder: 0, lastBackup: null });
    expect(settings.sources.arenaLog.found).toBe(false);
  });

  it('reports no path when there is none anywhere', () => {
    const settings = toShellSettings(
      parseConfigJson(JSON.stringify(CONFIG)),
      parseDoctorArena(JSON.stringify({ arena_log: { path: null, source: 'none' } })),
      { dataDir: '/d', backupInFolder: 0, lastBackup: null },
    );
    expect(settings.sources.arenaLog).toEqual({ path: null, found: false });
  });

  it('refuses a shape it does not know instead of guessing', () => {
    expect(() => parseConfigJson(JSON.stringify({ ...CONFIG, backup: { dir: 'x', keep: 'many' } }))).toThrow(/backup.keep/);
    expect(() => parseConfigJson(JSON.stringify({ ...CONFIG, arena: { log: null, date_order: 'ymd' } }))).toThrow(/date_order/);
    expect(() => parseConfigJson('[]')).toThrow();
  });

  it('reads the shell preferences with their defaults', () => {
    const info = { version: '1.2.3', platform: 'linux', update: { state: 'idle' } as const };
    expect(toAppSettings({}, info)).toEqual({
      startWithSystem: false,
      keepRunningOnClose: false,
      checkForUpdates: true,
      diagnostic: false,
      update: { state: 'idle' },
      version: '1.2.3',
      platform: 'linux',
    });
    const prefs: ShellJson = { autostart: true, checkForUpdates: false, diagnostic: true, keepRunningOnClose: true };
    expect(toAppSettings(prefs, info)).toMatchObject({ startWithSystem: true, checkForUpdates: false, diagnostic: true, keepRunningOnClose: true });
  });
});

describe('a change to CLI arguments', () => {
  it('writes each setting with its own flag; null clears', () => {
    expect(planChange({ sources: { arenaLog: { path: '/a/Player.log' } } }).args).toEqual(['config', '--set-arena-log', '/a/Player.log']);
    expect(planChange({ sources: { arenaLog: { path: null } } }).args).toEqual(['config', '--set-arena-log', '']);
    expect(planChange({ sources: { dateOrder: 'dmy' } }).args).toEqual(['config', '--set-date-order', 'dmy']);
    expect(planChange({ sources: { mtgoHandle: null, mtgoDir: '/m' } }).args).toEqual([
      'config', '--set-mtgo-handle', '', '--set-mtgo-dir', '/m',
    ]);
    expect(planChange({ writing: { model: 'claude-opus-5-5' } }).args).toEqual(['config', '--set-model', 'claude-opus-5-5']);
    expect(planChange({ backup: { dir: '/b', keep: 4 } }).args).toEqual(['config', '--set-backup-dir', '/b', '--set-backup-keep', '4']);
  });

  it('sends nothing for what the shell cannot change or only reads', () => {
    expect(planChange({}).args).toBeNull();
    expect(planChange({ sources: { dataDir: '/elsewhere' } }).args).toBeNull();
    expect(planChange({ sources: { arenaLog: { found: true } } }).args).toBeNull();
    expect(planChange({ writing: { claudeKey: true, topdeckKey: false } }).args).toBeNull();
    expect(planChange({ backup: { inFolder: 9, last: null } }).args).toBeNull();
  });

  it('refuses values the CLI would refuse', () => {
    expect(() => planChange({ backup: { keep: 0 } })).toThrow();
    expect(() => planChange({ backup: { keep: 1.5 } })).toThrow();
    expect(() => planChange({ sources: { dateOrder: 'ymd' as 'auto' } })).toThrow();
  });

  it('puts a key on stdin and never in the arguments', () => {
    const claude = keyCommand('claude', '  sk-test-secret \n');
    expect(claude.args).toEqual(['config', '--set-key', '-']);
    expect(claude.stdin).toBe('sk-test-secret\n');
    const topdeck = keyCommand('topdeck', 'td-test-secret');
    expect(topdeck.args).toEqual(['config', '--set-topdeck-key', '-']);
    expect(topdeck.stdin).toBe('td-test-secret\n');
    for (const command of [claude, topdeck]) {
      expect(command.args.join(' ')).not.toContain('secret');
    }
    expect(keyCommand('claude', null)).toEqual({ args: ['config', '--clear-key'] });
    expect(keyCommand('topdeck', null)).toEqual({ args: ['config', '--clear-topdeck-key'] });
    expect(() => keyCommand('claude', '   ')).toThrow();
    expect(() => keyCommand('claude', 'a\nb')).toThrow();
  });
});

describe('which changes restart the server (D12, D18)', () => {
  it('restarts for what the server reads only at start', () => {
    expect(planChange({ sources: { arenaLog: { path: '/a' } } }).restart).toBe(true);
    expect(planChange({ sources: { dateOrder: 'mdy' } }).restart).toBe(true);
    expect(planChange({ sources: { mtgoDir: '/m' } }).restart).toBe(true);
    expect(planChange({ sources: { mtgoHandle: 'x' } }).restart).toBe(true);
    expect(planChange({ backup: { dir: '/b' } }).restart).toBe(true);
    expect(planChange({ backup: { keep: 2 } }).restart).toBe(true);
  });

  it('does not restart for the model', () => {
    expect(planChange({ writing: { model: 'claude-opus-5-5' } }).restart).toBe(false);
  });

  it('restarts for diagnostic mode only when it changes', () => {
    const current = toAppSettings({ diagnostic: false }, { version: '1', platform: 'linux', update: { state: 'idle' } });
    expect(planAppChange(current, { diagnostic: true })).toEqual({ patch: { diagnostic: true }, restart: true });
    expect(planAppChange(current, { diagnostic: false }).restart).toBe(false);
    expect(planAppChange(current, { startWithSystem: true })).toEqual({ patch: { autostart: true }, restart: false });
    expect(planAppChange(current, { checkForUpdates: false, keepRunningOnClose: true })).toEqual({
      patch: { checkForUpdates: false, keepRunningOnClose: true },
      restart: false,
    });
  });
});

describe('restore exit status', () => {
  it('restarts the server after success and after a refusal', () => {
    expect(interpretRestore(0, '')).toEqual({ restartServer: true, saved: { ok: true } });
    expect(interpretRestore(1, 'Refused: newer schema.\n')).toEqual({
      restartServer: true,
      saved: { ok: false, error: 'Refused: newer schema.' },
    });
  });

  it('leaves the server stopped on status 3 and shows stderr, which names each file', () => {
    const stderr = 'Restore stopped partway.\n  a.db.replaced -> a.db\n';
    const outcome = interpretRestore(3, stderr);
    expect(outcome.restartServer).toBe(false);
    expect(outcome.saved).toEqual({ ok: false, error: stderr.trim() });
  });

  it('does not start a server after a status it does not know', () => {
    expect(interpretRestore(2, '').restartServer).toBe(false);
    expect(interpretRestore(null, '').restartServer).toBe(false);
  });

  it('restarts when the command never ran', () => {
    expect(interpretRestore('not-run', '').restartServer).toBe(true);
  });
});

describe('small readers', () => {
  it('reads a backup size from the command output', () => {
    expect(parseBackupBytes('Backed up x -> y\n  Source:    9 bytes\n  Backup:    1,234,567 bytes, verified\n')).toBe(1234567);
    expect(parseBackupBytes('nothing')).toBeNull();
  });

  it('answers only the dashboard on the running port', () => {
    expect(trustedSender('http://127.0.0.1:4100/settings', 4100)).toBe(true);
    expect(trustedSender('http://127.0.0.1:4101/', 4100)).toBe(false);
    expect(trustedSender('https://example.com/', 4100)).toBe(false);
    expect(trustedSender('http://127.0.0.1:4100/', null)).toBe(false);
    expect(trustedSender('data:text/html,x', 4100)).toBe(false);
    expect(trustedSender('', 4100)).toBe(false);
  });

  it('keeps the preload script on the same channels', () => {
    const source = fs.readFileSync(path.join(__dirname, 'preload.ts'), 'utf8');
    const block = /const CHANNEL = \{([\s\S]*?)\} as const;/.exec(source)?.[1] ?? '';
    const pairs = [...block.matchAll(/(\w+):\s*'([^']+)'/g)].map((m) => [m[1], m[2]]);
    expect(Object.fromEntries(pairs)).toEqual(CHANNELS);
    // and each member invokes the channel of its own name
    const uses = (member: string, key: string) => new RegExp(`${member}:[^\\n]*CHANNEL\\.${key}\\b`).test(source);
    expect(uses('save', 'save')).toBe(true);
    expect(uses('setKey', 'setKey')).toBe(true);
    expect(uses('backUpNow', 'backUpNow')).toBe(true);
    expect(uses('restoreFrom', 'restoreFrom')).toBe(true);
    expect(uses('showDataFolder', 'appShowDataFolder')).toBe(true);
    expect(uses('checkForUpdates', 'appCheckForUpdates')).toBe(true);
    expect(uses('restartToUpdate', 'appRestartToUpdate')).toBe(true);
  });
});

describe('diagnostics (D16)', () => {
  it('adds the Player.log flag only when its box was ticked', () => {
    const base = { out: '/o/d.zip', shellLog: '/data/logs/shell.log' };
    expect(diagnosticsArgs({ ...base, withPlayerLog: false })).toEqual(['diagnostics', '--out', '/o/d.zip', '--shell-log', '/data/logs/shell.log']);
    expect(diagnosticsArgs({ ...base, withPlayerLog: true })).toEqual([
      'diagnostics', '--out', '/o/d.zip', '--shell-log', '/data/logs/shell.log', '--with-player-log',
    ]);
  });

  it('shows the listing one entry per line', () => {
    expect(formatListing('sensei-top.log\t120\ndoctor.json\t30\n')).toBe('sensei-top.log (120 bytes)\ndoctor.json (30 bytes)');
  });
});

describe('a restore that stopped partway (D19)', () => {
  it('blocks the server when the database is gone and its files are aside', () => {
    const files = restoreLeftovers('a.db', false, ['a.db.replaced', 'a.db-wal.replaced', 'a.db.replaced.1', 'a.db-wal.replaced.1', 'a.db-shm.replaced.1', 'other', 'b.db.replaced']);
    expect(files).toEqual(['a.db-shm.replaced.1 \u2192 a.db-shm', 'a.db-wal.replaced.1 \u2192 a.db-wal', 'a.db.replaced.1 \u2192 a.db']);
    expect(restoreLeftoversMessage(['a.db.replaced \u2192 a.db'])).toBe(
      'A restore stopped partway, so the server was not started. Rename these files back first: a.db.replaced \u2192 a.db.',
    );
  });

  it('lists a lone first set with its targets', () => {
    expect(restoreLeftovers('a.db', false, ['a.db.replaced', 'a.db-wal.replaced'])).toEqual(['a.db-wal.replaced \u2192 a.db-wal', 'a.db.replaced \u2192 a.db']);
  });

  it('logs only the file-pair lines of restore stderr', () => {
    const stderr = 'Restore stopped partway (could not copy /home/x/y).\nDo not start serve until these are renamed back:\n  a.db.replaced -> a.db\n';
    expect(filePairLines(stderr)).toEqual(['a.db.replaced -> a.db']);
  });

  it('does not block after a finished restore, which keeps .replaced beside the database', () => {
    expect(restoreLeftovers('a.db', true, ['a.db', 'a.db.replaced', 'a.db-wal.replaced'])).toEqual([]);
  });

  it('does not block a fresh folder', () => {
    expect(restoreLeftovers('a.db', false, ['logs'])).toEqual([]);
  });
});

class RunError extends Error {
  constructor(
    readonly code: number | null,
    readonly stderr: string,
  ) {
    super('failed');
  }
}

const BUSY = 'A backup started 2m ago (pid 123) is still running; nothing to do.\n';

function harness(failures: Record<string, RunError> = {}, extra: { backupOutput?: string; slot?: { at: string; bytes: number } | null; open?: string | Error } = {}) {
  const backupOutput = extra.backupOutput ?? '  Backup:    2,048 bytes, verified\n';
  const calls: Array<{ args: readonly string[]; stdin?: string }> = [];
  const events: string[] = [];
  const stored: ShellJson = {};
  const changes: BridgeSettings[] = [];
  const warnings: Array<{ message: string; fields?: unknown }> = [];
  const updates: { status: UpdateStatus; switched: boolean[] } = { status: { state: 'idle' }, switched: [] };
  const deps: SettingsDeps = {
    run: (args, options) => {
      calls.push({ args, ...(options?.stdin === undefined ? {} : { stdin: options.stdin }) });
      events.push(`run ${args[0]}`);
      const failure = failures[args[0] ?? ''];
      if (failure && !(args[0] === 'config' && args[1] === '--json')) return Promise.reject(failure);
      if (args[0] === 'config' && args[1] === '--json') return Promise.resolve(JSON.stringify(CONFIG));
      if (args[0] === 'doctor') return Promise.resolve(JSON.stringify(DOCTOR));
      if (args[0] === 'backup') return Promise.resolve(backupOutput);
      return Promise.resolve('');
    },
    stopServer: () => {
      events.push('stop');
      return Promise.resolve();
    },
    startServer: () => {
      events.push('start');
      return Promise.resolve();
    },
    reloadWindow: () => events.push('reload'),
    store: {
      get: () => stored,
      update: (patch) => {
        Object.assign(stored, patch);
        return true;
      },
    },
    dataDir: '/data',
    version: '9.9.9',
    platform: 'linux',
    countBackups: () => 1,
    newestBackup: () => extra.slot ?? null,
    now: () => new Date('2026-10-08T10:00:00Z'),
    pickFolder: () => Promise.resolve(null),
    pickFile: () => Promise.resolve(null),
    showLogs: () => {},
    openDataFolder: () => (extra.open instanceof Error ? Promise.reject(extra.open) : Promise.resolve(extra.open ?? '')),
    changed: (settings) => changes.push(settings),
    updateStatus: () => updates.status,
    setUpdateChecks: (on) => void updates.switched.push(on),
    log: {
      debug: () => {},
      info: () => {},
      warn: (message, fields) => void warnings.push({ message, ...(fields ? { fields } : {}) }),
      error: () => {},
    },
  };
  return { service: new SettingsService(deps), calls, events, stored, changes, warnings, updates };
}

describe('the service', () => {
  it('opens the data folder, and answers a sentence when it cannot', async () => {
    const opened = harness();
    expect(await opened.service.showDataFolder()).toEqual({ ok: true });
    expect(opened.warnings).toEqual([]);
    const refused = harness({}, { open: 'Failed to open path' });
    expect(await refused.service.showDataFolder()).toEqual({ ok: false, error: 'The folder could not be opened.' });
    expect(refused.warnings).toEqual([{ message: 'could not open the data folder', fields: { error: 'Failed to open path' } }]);
  });

  it('answers the same sentence when opening the folder throws', async () => {
    const thrown = harness({}, { open: new Error('boom') });
    expect(await thrown.service.showDataFolder()).toEqual({ ok: false, error: 'The folder could not be opened.' });
    expect(thrown.warnings).toHaveLength(1);
    expect(thrown.warnings[0]?.message).toBe('could not open the data folder');
  });

  it('sends a key on stdin and nothing of it in any argument', async () => {
    const { service, calls } = harness();
    expect(await service.setKey('claude', 'sk-test-secret')).toEqual({ ok: true });
    const call = calls.find((c) => c.args[1] === '--set-key');
    expect(call?.stdin).toBe('sk-test-secret\n');
    for (const c of calls) expect(c.args.join(' ')).not.toContain('secret');
  });

  it('restarts the server after a changed Arena log, and never sets Saved.restart', async () => {
    const { service, events, changes } = harness();
    const saved = await service.save({ sources: { arenaLog: { path: '/a/Player.log' } } });
    expect(saved).toEqual({ ok: true });
    expect(events.indexOf('stop')).toBeGreaterThan(events.indexOf('run config'));
    expect(events.indexOf('start')).toBeGreaterThan(events.indexOf('stop'));
    expect(changes).toHaveLength(1);
    expect(changes[0]?.app.version).toBe('9.9.9');
  });

  it('does not restart for the model, and a failed run saves nothing', async () => {
    const ok = harness();
    await ok.service.save({ writing: { model: 'claude-opus-5-5' } });
    expect(ok.events).not.toContain('stop');
    const bad = harness({ config: new RunError(1, 'Something is wrong.\nThe path is not allowed.\n') });
    const saved = await bad.service.save({ sources: { arenaLog: { path: '/x' } } });
    expect(saved).toEqual({ ok: false, error: 'The path is not allowed.' });
    expect(bad.events).not.toContain('stop');
  });

  it('restarts the server for diagnostic mode', async () => {
    const { service, events, stored } = harness();
    expect(await service.setApp({ diagnostic: true })).toEqual({ ok: true });
    expect(stored.diagnostic).toBe(true);
    expect(events).toContain('stop');
    expect(events).toContain('start');
  });

  it('remembers the backup it just made', async () => {
    const { service, changes } = harness();
    expect(await service.backUpNow()).toEqual({ ok: true });
    expect(changes[0]?.backup.last).toEqual({ at: '2026-10-08T10:00:00.000Z', ok: true, bytes: 2048 });
  });

  it('counts no backup when the command only says another is running', async () => {
    const { service, changes } = harness({}, { backupOutput: BUSY });
    expect(await service.backUpNow()).toEqual({ ok: false, error: BUSY.trim() });
    expect(changes).toHaveLength(0);
  });

  it('shows the whole message of a failed backup', async () => {
    const stderr = 'Backup failed: disk full\n  No backup exists yet.';
    const { service } = harness({ backup: new RunError(1, stderr + '\n') });
    expect(await service.backUpNow()).toEqual({ ok: false, error: stderr });
  });

  it('reads the last backup from the newest slot on disk after a launch', async () => {
    const { service } = harness({}, { slot: { at: '2026-10-01T00:00:00.000Z', bytes: 77 } });
    const settings = await service.refresh();
    expect(settings?.backup.last).toEqual({ at: '2026-10-01T00:00:00.000Z', ok: true, bytes: 77 });
  });

  it('prefers a backup made this session when it is newer than the slot', async () => {
    const { service, changes } = harness({}, { slot: { at: '2026-10-01T00:00:00.000Z', bytes: 77 } });
    await service.backUpNow();
    expect(changes[0]?.backup.last).toEqual({ at: '2026-10-08T10:00:00.000Z', ok: true, bytes: 2048 });
  });

  it('restores: stop, restore, start, reload', async () => {
    const { service, events } = harness();
    expect(await service.restoreFrom('/b/backup')).toEqual({ ok: true });
    expect(events.filter((e) => e !== 'run config' && e !== 'run doctor')).toEqual(['stop', 'run restore', 'start', 'reload']);
  });

  it('after status 3 leaves the server stopped and shows stderr', async () => {
    const stderr = 'Restore stopped partway.\n  x.db.replaced -> x.db\n';
    const { service, events } = harness({ restore: new RunError(3, stderr) });
    expect(await service.restoreFrom('/b/backup')).toEqual({ ok: false, error: stderr.trim() });
    expect(events).toEqual(['stop', 'run restore']);
  });

  it('after a refusal (status 1) starts the server again without a reload', async () => {
    const { service, events } = harness({ restore: new RunError(1, 'That backup is from a newer version.') });
    expect(await service.restoreFrom('/b/backup')).toEqual({ ok: false, error: 'That backup is from a newer version.' });
    expect(events).toContain('start');
    expect(events).not.toContain('reload');
  });

  it('carries the update status in the app part', async () => {
    const { service, updates } = harness();
    updates.status = { state: 'unavailable', reason: 'development' };
    expect((await service.refresh())?.app.update).toEqual({ state: 'unavailable', reason: 'development' });
  });

  it('sends the settings again when the update status changes, without reading the config', async () => {
    const { service, updates, changes, calls } = harness();
    service.updateChanged();
    expect(changes).toHaveLength(0);
    await service.refresh();
    const reads = calls.length;
    updates.status = { state: 'ready', version: '0.6.1' };
    service.updateChanged();
    expect(changes).toHaveLength(1);
    expect(changes[0]?.app.update).toEqual({ state: 'ready', version: '0.6.1' });
    expect(changes[0]?.sources.dataDir).toBe('/data');
    expect(service.current?.app.update).toEqual({ state: 'ready', version: '0.6.1' });
    expect(calls).toHaveLength(reads);
  });

  it('hands the update switch to the updater, and nothing else', async () => {
    const { service, updates, stored } = harness();
    expect(await service.setApp({ checkForUpdates: false })).toEqual({ ok: true });
    expect(stored.checkForUpdates).toBe(false);
    expect(updates.switched).toEqual([false]);
    await service.setApp({ startWithSystem: true });
    expect(updates.switched).toEqual([false]);
  });
});
