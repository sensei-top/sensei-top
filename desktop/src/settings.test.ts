import * as fs from 'node:fs';
import * as path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import {
  asksAutostart,
  CHANNELS,
  diagnosticsArgs,
  formatListing,
  interpretRestore,
  keyCommand,
  parseBackupBytes,
  parseConfigJson,
  parseDoctorArena,
  parseProgress,
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
  type FirstData,
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
const DOCTOR = {
  arena_log: { path: '/games/Player.log', source: 'autodetect', detailed_logs: 'unknown' },
  mtgo: { discovered: null },
  cards: { arena_ids: 10, rules_text: 5 },
};
const NO_APP_EXTRAS = { askAutostart: false, rulesText: null, firstData: { state: 'idle' } } as const;

describe('config --json to ShellSettings', () => {
  it('carries mtgo.deck_dir into sources.mtgoDeckDir, null when unset', () => {
    const extras = { dataDir: '/data', backupInFolder: 2, lastBackup: null };
    const doctor = parseDoctorArena(JSON.stringify(DOCTOR));
    const withDir = { ...CONFIG, mtgo: { ...CONFIG.mtgo, deck_dir: '/mtgo/decks' } };
    expect(toShellSettings(parseConfigJson(JSON.stringify(withDir)), doctor, extras).sources.mtgoDeckDir).toBe('/mtgo/decks');
    expect(toShellSettings(parseConfigJson(JSON.stringify(CONFIG)), doctor, extras).sources.mtgoDeckDir).toBeNull();
  });

  it('maps every field the page shows', () => {
    const settings = toShellSettings(parseConfigJson(JSON.stringify(CONFIG)), parseDoctorArena(JSON.stringify(DOCTOR)), {
      dataDir: '/data',
      backupInFolder: 2,
      lastBackup: null,
    });
    expect(settings).toEqual({
      sources: {
        arenaLog: { path: '/games/Player.log', found: true, detailedLogs: 'unknown' },
        dateOrder: 'auto',
        mtgoHandle: 'someone',
        mtgoDir: '/mtgo/logs',
        mtgoDeckDir: null,
        mtgoFound: null,
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
    const chosen = toShellSettings(config, { path: '/mine/Player.log', source: 'config', detailedLogs: 'unknown', mtgoFound: null, rulesText: null }, extras);
    expect(chosen.sources.arenaLog).toEqual({ path: '/mine/Player.log', found: false, detailedLogs: 'unknown' });
    expect(chosen.sources.dateOrder).toBe('dmy');
    // doctor failing costs `found` and nothing else
    const noDoctor = toShellSettings(config, null, extras);
    expect(noDoctor.sources.arenaLog).toEqual({ path: '/mine/Player.log', found: false, detailedLogs: 'unknown' });
    expect(noDoctor.sources.mtgoFound).toBeNull();
  });

  it('is not found when a path is configured, even if doctor says autodetect', () => {
    const config = parseConfigJson(JSON.stringify({ ...CONFIG, arena: { log: '/mine/Player.log', date_order: 'auto' } }));
    const settings = toShellSettings(config, { path: '/mine/Player.log', source: 'autodetect', detailedLogs: 'unknown', mtgoFound: null, rulesText: null }, { dataDir: '/d', backupInFolder: 0, lastBackup: null });
    expect(settings.sources.arenaLog.found).toBe(false);
  });

  it('reports no path when there is none anywhere', () => {
    const settings = toShellSettings(
      parseConfigJson(JSON.stringify(CONFIG)),
      parseDoctorArena(JSON.stringify({ arena_log: { path: null, source: 'none' } })),
      { dataDir: '/d', backupInFolder: 0, lastBackup: null },
    );
    expect(settings.sources.arenaLog).toEqual({ path: null, found: false, detailedLogs: 'unknown' });
  });

  it('refuses a shape it does not know instead of guessing', () => {
    expect(() => parseConfigJson(JSON.stringify({ ...CONFIG, backup: { dir: 'x', keep: 'many' } }))).toThrow(/backup.keep/);
    expect(() => parseConfigJson(JSON.stringify({ ...CONFIG, arena: { log: null, date_order: 'ymd' } }))).toThrow(/date_order/);
    expect(() => parseConfigJson('[]')).toThrow();
  });

  it('reads the shell preferences with their defaults', () => {
    const info = { version: '1.2.3', platform: 'linux', update: { state: 'idle' } as const, ...NO_APP_EXTRAS };
    expect(toAppSettings({}, info)).toEqual({
      startWithSystem: false,
      keepRunningOnClose: false,
      checkForUpdates: true,
      diagnostic: false,
      language: 'system',
      plays: ['arena', 'mtgo'],
      update: { state: 'idle' },
      onboarded: false,
      askAutostart: false,
      rulesText: null,
      firstData: { state: 'idle' },
      version: '1.2.3',
      platform: 'linux',
    });
    const prefs: ShellJson = { autostart: true, checkForUpdates: false, diagnostic: true, keepRunningOnClose: true };
    expect(toAppSettings(prefs, info)).toMatchObject({ startWithSystem: true, checkForUpdates: false, diagnostic: true, keepRunningOnClose: true });
  });

  it('carries a stored language through', () => {
    const info = { version: '1', platform: 'linux', update: { state: 'idle' } as const, ...NO_APP_EXTRAS };
    expect(toAppSettings({ language: 'pt-BR' }, info).language).toBe('pt-BR');
    expect(toAppSettings({ language: 'en' }, info).language).toBe('en');
  });
});

describe('doctor --json for onboarding (S15)', () => {
  it('reads Detailed Logs, the MTGO folder doctor found and the rules-text count', () => {
    const doctor = parseDoctorArena(
      JSON.stringify({
        arena_log: { path: '/a/Player.log', source: 'config', detailed_logs: 'enabled' },
        mtgo: { discovered: '/mtgo/found' },
        cards: { arena_ids: 3, rules_text: 27000 },
      }),
    );
    expect(doctor).toEqual({ path: '/a/Player.log', source: 'config', detailedLogs: 'enabled', mtgoFound: '/mtgo/found', rulesText: 27000 });
    const settings = toShellSettings(parseConfigJson(JSON.stringify(CONFIG)), doctor, { dataDir: '/d', backupInFolder: 0, lastBackup: null });
    expect(settings.sources.arenaLog.detailedLogs).toBe('enabled');
    expect(settings.sources.mtgoFound).toBe('/mtgo/found');
  });

  it('reads disabled, and anything unrecognised or missing as unknown or null', () => {
    const disabled = parseDoctorArena(JSON.stringify({ arena_log: { path: null, source: 'none', detailed_logs: 'disabled' } }));
    expect(disabled.detailedLogs).toBe('disabled');
    expect(disabled.mtgoFound).toBeNull();
    expect(disabled.rulesText).toBeNull();
    const odd = parseDoctorArena(
      JSON.stringify({
        arena_log: { path: null, source: 'none', detailed_logs: 'maybe' },
        mtgo: { discovered: 7 },
        cards: { rules_text: null },
      }),
    );
    expect(odd).toMatchObject({ detailedLogs: 'unknown', mtgoFound: null, rulesText: null });
  });

  it('is unknown and null in the settings when doctor could not be read', () => {
    const settings = toShellSettings(parseConfigJson(JSON.stringify(CONFIG)), null, { dataDir: '/d', backupInFolder: 0, lastBackup: null });
    expect(settings.sources.arenaLog.detailedLogs).toBe('unknown');
    expect(settings.sources.mtgoFound).toBeNull();
  });

  it('asks about autostart on Linux and the Store build only (D25)', () => {
    expect(asksAutostart('linux', false)).toBe(true);
    expect(asksAutostart('win32', true)).toBe(true);
    expect(asksAutostart('win32', false)).toBe(false);
    expect(asksAutostart('darwin', false)).toBe(false);
  });

  it('reads onboarded from shell.json, false by default', () => {
    const info = { version: '1', platform: 'linux', update: { state: 'idle' } as const, ...NO_APP_EXTRAS };
    expect(toAppSettings({ onboarded: true }, info).onboarded).toBe(true);
    expect(toAppSettings({}, info).onboarded).toBe(false);
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
    expect(planChange({ sources: { mtgoDeckDir: '/mtgo/decks' } }).args).toEqual(['config', '--set-mtgo-deck-dir', '/mtgo/decks']);
    expect(planChange({ sources: { mtgoDeckDir: null } }).args).toEqual(['config', '--set-mtgo-deck-dir', '']);
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
    expect(planChange({ sources: { mtgoDeckDir: '/m' } }).restart).toBe(true);
    expect(planChange({ sources: { mtgoHandle: 'x' } }).restart).toBe(true);
    expect(planChange({ backup: { dir: '/b' } }).restart).toBe(true);
    expect(planChange({ backup: { keep: 2 } }).restart).toBe(true);
  });

  it('does not restart for the model', () => {
    expect(planChange({ writing: { model: 'claude-opus-5-5' } }).restart).toBe(false);
  });

  it('patches a language change without a restart', () => {
    const current = toAppSettings({}, { version: '1', platform: 'linux', update: { state: 'idle' }, ...NO_APP_EXTRAS });
    expect(planAppChange(current, { language: 'pt-BR' })).toEqual({ patch: { language: 'pt-BR' }, restart: false });
  });

  it('restarts for diagnostic mode only when it changes', () => {
    const current = toAppSettings({ diagnostic: false }, { version: '1', platform: 'linux', update: { state: 'idle' }, ...NO_APP_EXTRAS });
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

  it('words an unknown status, and a missing one, in their own sentences', () => {
    const none = interpretRestore(null, '');
    expect(none.restartServer).toBe(false);
    expect(none.saved).toEqual({ ok: false, error: 'The restore ended without a status code.' });
    expect(interpretRestore(7, '').saved).toEqual({ ok: false, error: 'The restore ended with status 7.' });
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
    expect(uses('recheck', 'appRecheck')).toBe(true);
    expect(uses('firstData', 'appFirstData')).toBe(true);
    expect(uses('finishOnboarding', 'appFinishOnboarding')).toBe(true);
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

type Cards = { lines: string[]; fail?: RunError; finish?: Promise<void> };

function harness(failures: Record<string, RunError> = {}, extra: { backupOutput?: string; slot?: { at: string; bytes: number } | null; open?: string | Error; storeFails?: boolean; cards?: Cards; doctor?: () => string; configFails?: { on: boolean }; restoreHold?: Promise<void> } = {}) {
  const backupOutput = extra.backupOutput ?? '  Backup:    2,048 bytes, verified\n';
  const calls: Array<{ args: readonly string[]; stdin?: string }> = [];
  const events: string[] = [];
  const languages: string[] = [];
  const stored: ShellJson = {};
  const changes: BridgeSettings[] = [];
  const warnings: Array<{ message: string; fields?: unknown }> = [];
  const infos: string[] = [];
  let cardsActive = 0;
  const overlap = { restoreDuringCards: false };
  const updates: { status: UpdateStatus; switched: boolean[] } = { status: { state: 'idle' }, switched: [] };
  let rules = 5;
  const late: Array<() => void> = [];
  const deps: SettingsDeps = {
    run: async (args, options) => {
      calls.push({ args, ...(options?.stdin === undefined ? {} : { stdin: options.stdin }) });
      events.push(`run ${args[0]}`);
      if (args[0] === 'restore' && cardsActive > 0) overlap.restoreDuringCards = true;
      if (args[0] === 'restore' && extra.restoreHold) await extra.restoreHold;
      if (args[0] === 'config' && args[1] === '--json' && extra.configFails?.on) return Promise.reject(new RunError(1, 'no'));
      if (args[0] === 'cards' && extra.cards) {
        cardsActive += 1;
        try {
          for (const line of extra.cards.lines) options?.onLine?.(line);
          const aborted = new Promise<never>((_, reject) =>
            options?.signal?.addEventListener('abort', () => {
              // a real child's output can still arrive after the rejection
              late.push(() => options.onLine?.('late line'));
              reject(new Error('aborted'));
            }),
          );
          if (extra.cards.finish) await Promise.race([extra.cards.finish, aborted]);
          if (extra.cards.fail) throw extra.cards.fail;
          rules = 27000;
        return extra.cards.lines.join('\n');
        } finally {
          cardsActive -= 1;
        }
      }
      const failure = failures[args[0] ?? ''];
      if (failure && !(args[0] === 'config' && args[1] === '--json')) return Promise.reject(failure);
      if (args[0] === 'config' && args[1] === '--json') return Promise.resolve(JSON.stringify(CONFIG));
      if (args[0] === 'doctor') return Promise.resolve(extra.doctor ? extra.doctor() : JSON.stringify({ ...DOCTOR, cards: { arena_ids: 10, rules_text: rules } }));
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
        if (extra.storeFails) return false;
        Object.assign(stored, patch);
        return true;
      },
    },
    setLanguage: (choice) => void languages.push(choice),
    dataDir: '/data',
    version: '9.9.9',
    platform: 'linux',
    askAutostart: true,
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
      info: (message) => void infos.push(message),
      warn: (message, fields) => void warnings.push({ message, ...(fields ? { fields } : {}) }),
      error: () => {},
    },
  };
  return { service: new SettingsService(deps), languages, late, calls, events, stored, changes, warnings, infos, overlap, updates };
}

describe('the service', () => {
  it('hands a language change to the shell after the store took it, and not when the store refused', async () => {
    const ok = harness();
    expect(await ok.service.setApp({ language: 'pt-BR' })).toEqual({ ok: true });
    expect(ok.languages).toEqual(['pt-BR']);
    const refused = harness({}, { storeFails: true });
    expect(await refused.service.setApp({ language: 'pt-BR' })).toEqual({ ok: false, error: 'The setting could not be saved.' });
    expect(refused.languages).toEqual([]);
  });

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

  it('reads the new doctor fields into the settings and the app part', async () => {
    const { service } = harness({}, {
      doctor: () =>
        JSON.stringify({
          arena_log: { path: '/a/Player.log', source: 'autodetect', detailed_logs: 'enabled' },
          mtgo: { discovered: '/mtgo/found' },
          cards: { rules_text: 12 },
        }),
    });
    const settings = await service.refresh();
    expect(settings?.sources.arenaLog.detailedLogs).toBe('enabled');
    expect(settings?.sources.mtgoFound).toBe('/mtgo/found');
    expect(settings?.app).toMatchObject({ rulesText: 12, askAutostart: true, onboarded: false, firstData: { state: 'idle' } });
  });

  it('reads unknown and null when doctor fails', async () => {
    const { service } = harness({ doctor: new RunError(1, 'no') });
    const settings = await service.refresh();
    expect(settings?.sources.arenaLog.detailedLogs).toBe('unknown');
    expect(settings?.sources.mtgoFound).toBeNull();
    expect(settings?.app.rulesText).toBeNull();
  });

  it('warns, naming the field and never its value, for a wrong type in doctor', async () => {
    const { service, warnings } = harness({}, {
      doctor: () =>
        JSON.stringify({
          arena_log: { path: null, source: 'none', detailed_logs: 'SECRET-VALUE' },
          mtgo: { discovered: 7 },
          cards: { rules_text: 'many' },
        }),
    });
    await service.refresh();
    expect(warnings.map((w) => w.fields)).toEqual([
      { field: 'arena_log.detailed_logs' },
      { field: 'mtgo.discovered' },
      { field: 'cards.rules_text' },
    ]);
    expect(JSON.stringify(warnings)).not.toContain('SECRET-VALUE');
  });

  it('stays silent for absent or null doctor fields', async () => {
    const { service, warnings } = harness({}, {
      doctor: () => JSON.stringify({ arena_log: { path: null, source: 'none', detailed_logs: null }, mtgo: { discovered: null }, cards: { rules_text: null } }),
    });
    await service.refresh();
    expect(warnings).toEqual([]);
  });

  it('rechecks: reads the config and doctor again and publishes', async () => {
    const { service, calls, changes } = harness();
    expect(await service.recheck()).toEqual({ ok: true });
    expect(calls.map((c) => c.args[0])).toEqual(['config', 'doctor']);
    expect(changes).toHaveLength(1);
  });

  it('finishOnboarding writes onboarded and publishes it', async () => {
    const { service, stored, changes } = harness();
    expect(await service.finishOnboarding()).toEqual({ ok: true });
    expect(stored.onboarded).toBe(true);
    expect(changes.at(-1)?.app.onboarded).toBe(true);
  });

  describe('card data on its own (D5)', () => {
    const doctorWith = (...counts: Array<number | null>) => {
      let n = 0;
      return () => JSON.stringify({ ...DOCTOR, cards: { arena_ids: 10, rules_text: counts[Math.min(n++, counts.length - 1)] } });
    };
    const cardCalls = (calls: Array<{ args: readonly string[] }>) => calls.filter((c) => c.args[0] === 'cards').length;

    it('starts when doctor counted zero, and logs one line', async () => {
      const { service, calls, infos } = harness({}, { doctor: doctorWith(0), cards: { lines: ['x'] } });
      await service.refresh();
      await service.startFirstDataIfMissing();
      expect(cardCalls(calls)).toBe(1);
      expect(infos).toEqual(['no card data yet; starting the download on its own']);
    });

    it('does not start on a positive count', async () => {
      const { service, calls, infos } = harness({}, { doctor: doctorWith(27000) });
      await service.refresh();
      await service.startFirstDataIfMissing();
      expect(cardCalls(calls)).toBe(0);
      expect(infos).toEqual([]);
    });

    it('reads an unknown count again, and starts when the second read is zero', async () => {
      const { service, calls, infos } = harness({}, { doctor: doctorWith(null, 0), cards: { lines: ['x'] } });
      await service.refresh();
      await service.startFirstDataIfMissing();
      expect(cardCalls(calls)).toBe(1);
      expect(infos).toHaveLength(1);
    });

    it('does not start when the count is still unknown after the second read', async () => {
      const { service, calls, infos } = harness({}, { doctor: doctorWith(null), cards: { lines: ['x'] } });
      await service.refresh();
      await service.startFirstDataIfMissing();
      expect(cardCalls(calls)).toBe(0);
      expect(infos).toEqual([]);
    });

    it('does not start a second download while one runs', async () => {
      let release!: () => void;
      const finish = new Promise<void>((resolve) => (release = resolve));
      const { service, calls, infos } = harness({}, { doctor: doctorWith(0), cards: { lines: ['x'], finish } });
      await service.refresh();
      await service.startFirstDataIfMissing();
      await service.startFirstDataIfMissing();
      // firstData() would refuse a second run itself, so the cards count cannot tell;
      // the single info line does: the state check returned before logging.
      expect(cardCalls(calls)).toBe(1);
      expect(infos).toHaveLength(1);
      release();
    });

    it('does not retry after a failure', async () => {
      const { service, calls, infos } = harness({}, { doctor: doctorWith(0), cards: { lines: [], fail: new RunError(1, 'no') } });
      await service.refresh();
      expect(await service.firstData()).toMatchObject({ ok: false });
      await service.startFirstDataIfMissing();
      expect(cardCalls(calls)).toBe(1);
      expect(infos).toEqual([]);
    });

    it('a restore stops a running download without an error, restores, then checks again', async () => {
      let release!: () => void;
      const finish = new Promise<void>((resolve) => (release = resolve));
      const { service, calls, events, changes } = harness({}, { doctor: doctorWith(5, 0), cards: { lines: [], finish } });
      await service.refresh();
      const download = service.firstData();
      expect(await service.restoreFrom('/b/backup')).toEqual({ ok: true });
      await download;
      const order = events.filter((e) => e === 'run cards' || e === 'stop' || e === 'run restore');
      expect(order.slice(0, 3)).toEqual(['run cards', 'stop', 'run restore']);
      expect(changes.some((c) => c.app.firstData.state === 'failed')).toBe(false);
      expect(service.current?.app.firstData).not.toMatchObject({ state: 'failed' });
      expect(cardCalls(calls)).toBe(2);
      release();
    });
  });

  describe('card data and restore (D5)', () => {
    const doctorWith = (...counts: Array<number | null>) => {
      let n = 0;
      return () => JSON.stringify({ ...DOCTOR, cards: { arena_ids: 10, rules_text: counts[Math.min(n++, counts.length - 1)] } });
    };
    const cardCalls = (calls: Array<{ args: readonly string[] }>) => calls.filter((c) => c.args[0] === 'cards').length;
    const hold = () => {
      let release!: () => void;
      const finish = new Promise<void>((resolve) => (release = resolve));
      return { finish, release };
    };

    it('a restore queued behind the launch re-read never runs beside a download', async () => {
      const { finish, release } = hold();
      const { service, calls, overlap, infos } = harness({}, { doctor: doctorWith(null, 0), cards: { lines: [], finish } });
      await service.refresh();
      const start = service.startFirstDataIfMissing();
      const restore = service.restoreFrom('/b/backup');
      await Promise.all([start, restore]);
      expect(overlap.restoreDuringCards).toBe(false);
      expect(cardCalls(calls)).toBe(1);
      expect(infos).toHaveLength(1);
      release();
    });

    it('a second restore queued behind one whose check starts a download never overlaps it', async () => {
      const { finish, release } = hold();
      const { service, calls, overlap, infos } = harness({}, { doctor: doctorWith(0), cards: { lines: [], finish } });
      await service.refresh();
      const first = service.restoreFrom('/b/one');
      const second = service.restoreFrom('/b/two');
      await Promise.all([first, second]);
      expect(overlap.restoreDuringCards).toBe(false);
      expect(calls.filter((c) => c.args[0] === 'restore')).toHaveLength(2);
      expect(cardCalls(calls)).toBe(1);
      expect(infos).toHaveLength(1);
      release();
    });

    it('a restore after a finished download checks again against the restored database', async () => {
      const { service, calls } = harness({}, { doctor: doctorWith(0), cards: { lines: ['x'] } });
      await service.refresh();
      await service.firstData();
      expect(await service.restoreFrom('/b/backup')).toEqual({ ok: true });
      expect(cardCalls(calls)).toBe(2);
    });

    it('a restore after a failed download checks again too', async () => {
      const { service, calls } = harness({}, { doctor: doctorWith(0), cards: { lines: [], fail: new RunError(1, 'no') } });
      await service.refresh();
      await service.firstData();
      expect(await service.restoreFrom('/b/backup')).toEqual({ ok: true });
      expect(cardCalls(calls)).toBe(2);
    });

    it('refuses a Download pressed while a restore runs, and the check afterwards still starts one', async () => {
      const { finish: restoreHold, release } = hold();
      const { service, calls } = harness({}, { doctor: doctorWith(0), cards: { lines: ['x'] }, restoreHold });
      await service.refresh();
      const restore = service.restoreFrom('/b/backup');
      await vi.waitFor(() => expect(calls.some((c) => c.args[0] === 'restore')).toBe(true));
      expect(await service.firstData()).toEqual({ ok: false, error: 'A restore is running. Download once it has finished.' });
      expect(cardCalls(calls)).toBe(0);
      release();
      expect(await restore).toEqual({ ok: true });
      expect(cardCalls(calls)).toBe(1);
    });

    it('starts nothing after a restore when the settings could not be read', async () => {
      const configFails = { on: false };
      const { service, calls } = harness({}, { doctor: doctorWith(0), cards: { lines: ['x'] }, configFails });
      await service.refresh();
      configFails.on = true;
      expect(await service.restoreFrom('/b/backup')).toEqual({ ok: true });
      expect(cardCalls(calls)).toBe(0);
    });
  });

  describe('plays', () => {
    it('is written by a change and read back', async () => {
      const { service, stored } = harness();
      await service.refresh();
      expect(await service.setApp({ plays: ['mtgo'] })).toEqual({ ok: true });
      expect(stored.plays).toEqual(['mtgo']);
      expect(service.current?.app.plays).toEqual(['mtgo']);
      expect(planAppChange(service.current!.app, { plays: ['arena'] }).patch).toEqual({ plays: ['arena'] });
    });
  });

  describe('first data (D21)', () => {
    const lines = ['Downloading 78 MB from Scryfall…', '', '30000 cards stored in DB'];

    it('streams the lines as running, then is done with the last one and a refreshed count', async () => {
      const { service, changes, calls } = harness({}, { cards: { lines } });
      await service.refresh();
      const saved = await service.firstData();
      expect(saved).toEqual({ ok: true });
      expect(calls.find((c) => c.args[0] === 'cards')?.args).toEqual(['cards', '--scryfall', '--progress']);
      // running with no line, each non-blank line once in order, done at once,
      // then the queued refresh sends the settings again
      const done: FirstData = { state: 'done', line: '30000 cards stored in DB' };
      expect(changes.map((c) => c.app.firstData)).toEqual([
        { state: 'running', line: null },
        { state: 'running', line: 'Downloading 78 MB from Scryfall…' },
        { state: 'running', line: '30000 cards stored in DB' },
        done,
        done,
      ]);
      expect(changes.at(-1)?.app.rulesText).toBe(27000);
    });

    it('parses --progress JSON lines into progress, forwards other lines, and keeps JSON out of done', async () => {
      const download = '{"progress": {"stage": "download", "done": 34000000, "total": 79000000}}';
      const unknown = '{"progress": {"stage": "download", "done": 5, "total": null}}';
      const save = '{"progress": {"stage": "save"}}';
      const closing = '30000 cards stored in DB';
      const { service, changes } = harness({}, { cards: { lines: [download, unknown, 'a plain line', save, closing] } });
      await service.refresh();
      await service.firstData();
      const states = changes.map((c) => c.app.firstData);
      expect(states.slice(0, 7)).toEqual([
        { state: 'running', line: null },
        { state: 'running', line: null, progress: { stage: 'download', done: 34000000, total: 79000000 } },
        { state: 'running', line: null, progress: { stage: 'download', done: 5, total: null } },
        { state: 'running', line: 'a plain line', progress: { stage: 'download', done: 5, total: null } },
        { state: 'running', line: 'a plain line', progress: { stage: 'save' } },
        { state: 'running', line: closing, progress: { stage: 'save' } },
        { state: 'done', line: closing },
      ]);
    });

    it('keeps the last plain line for done when the stream ends on a progress line', async () => {
      const save = '{"progress": {"stage": "save"}}';
      const { service, changes } = harness({}, { cards: { lines: ['plain one', 'plain two', save] } });
      await service.refresh();
      await service.firstData();
      expect(changes.map((c) => c.app.firstData)).toContainEqual({ state: 'done', line: 'plain two' });
    });

    it('treats malformed or foreign JSON as an ordinary line', () => {
      expect(parseProgress('{"progress": 3}')).toBeNull();
      expect(parseProgress('{"listening": 8000}')).toBeNull();
      expect(parseProgress('{"progress": {"stage": "download"}}')).toBeNull();
      expect(parseProgress('{not json')).toBeNull();
    });

    it('never sends a line containing the database path as running, but keeps it for done', async () => {
      const closing = '30000 cards stored in /data/sensei-top.db';
      const { service, changes } = harness({}, { cards: { lines: [closing] } });
      await service.refresh();
      await service.firstData();
      const states = changes.map((c) => c.app.firstData);
      expect(states.filter((f) => f.state === 'running')).toEqual([{ state: 'running', line: null }]);
      expect(states.at(-1)).toEqual({ state: 'done', line: closing });
    });

    it('sends a line without the path as running at once, before the run ends', async () => {
      let release!: () => void;
      const finish = new Promise<void>((resolve) => (release = resolve));
      const { service, changes } = harness({}, { cards: { lines: ['Downloading 78 MB from Scryfall…'], finish } });
      await service.refresh();
      const download = service.firstData();
      expect(changes.at(-1)?.app.firstData).toEqual({ state: 'running', line: 'Downloading 78 MB from Scryfall…' });
      release();
      await download;
    });

    it('says no reason was given when stderr is empty', async () => {
      const { service, changes } = harness({}, { cards: { lines: [], fail: new RunError(1, '') } });
      await service.refresh();
      expect(await service.firstData()).toEqual({ ok: false, error: 'No reason was given.' });
      expect(changes.at(-1)?.app.firstData).toEqual({ state: 'failed', error: 'No reason was given.' });
    });

    it('fails with the last line of stderr', async () => {
      const { service, changes } = harness({}, { cards: { lines: [], fail: new RunError(1, 'Traceback\nCould not reach Scryfall.\n') } });
      await service.refresh();
      expect(await service.firstData()).toEqual({ ok: false, error: 'Could not reach Scryfall.' });
      expect(changes.at(-1)?.app.firstData).toEqual({ state: 'failed', error: 'Could not reach Scryfall.' });
    });

    it('refuses a second call while one runs, without a second run', async () => {
      let release!: () => void;
      const finish = new Promise<void>((resolve) => (release = resolve));
      const { service, calls } = harness({}, { cards: { lines: [], finish } });
      const first = service.firstData();
      expect(await service.firstData()).toEqual({ ok: false, error: 'The download is already running.' });
      release();
      expect(await first).toEqual({ ok: true });
      expect(calls.filter((c) => c.args[0] === 'cards')).toHaveLength(1);
    });

    it('ends a running download as failed when it is stopped, and does nothing otherwise', async () => {
      const idle = harness({}, { cards: { lines: [] } });
      expect(() => idle.service.stopFirstData()).not.toThrow();
      expect(idle.changes).toHaveLength(0);
      const { service, changes } = harness({}, { cards: { lines: [], finish: new Promise<void>(() => {}) } });
      await service.refresh();
      const download = service.firstData();
      service.stopFirstData();
      expect(await download).toEqual({ ok: false, error: 'The download was stopped.' });
      expect(changes.at(-1)?.app.firstData).toEqual({ state: 'failed', error: 'The download was stopped.' });
    });

    it('ignores a line that arrives after the abort, and runs again afterwards', async () => {
      const { service, changes, late, calls } = harness({}, { cards: { lines: [], finish: new Promise<void>(() => {}) } });
      await service.refresh();
      const download = service.firstData();
      service.stopFirstData();
      await download;
      for (const send of late) send();
      expect(changes.at(-1)?.app.firstData).toEqual({ state: 'failed', error: 'The download was stopped.' });
      void service.firstData();
      expect(calls.filter((c) => c.args[0] === 'cards')).toHaveLength(2);
    });

    it('does not queue a save behind the download', async () => {
      let release!: () => void;
      const finish = new Promise<void>((resolve) => (release = resolve));
      const { service, calls } = harness({}, { cards: { lines: [], finish } });
      const download = service.firstData();
      expect(await service.save({ writing: { model: 'claude-opus-5-5' } })).toEqual({ ok: true });
      expect(calls.some((c) => c.args[1] === '--set-model')).toBe(true);
      release();
      await download;
    });
  });
});
