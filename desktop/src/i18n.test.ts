import type { Menu, NativeImage, Tray } from 'electron';
import { afterEach, describe, expect, it } from 'vitest';
import {
  currentLanguage,
  languageOf,
  onLanguageChange,
  setLanguage,
  setSystemTags,
  systemLanguage,
  t,
  translate,
  type Key,
  type Language,
} from './i18n';
import en from './locales/en.json';
import ptBR from './locales/pt-BR.json';
import type { Logger } from './log';
import type { LanguageChoice } from './store';
import { StatusTray } from './tray';

afterEach(() => {
  setSystemTags(() => []);
  setLanguage('en');
});

describe('the system language', () => {
  it('is decided by the first English or Portuguese tag', () => {
    expect(systemLanguage(['en-US', 'pt-BR'])).toBe('en');
    expect(systemLanguage(['de-DE', 'pt-BR', 'en'])).toBe('pt-BR');
  });

  it('reads Portuguese of any region as pt-BR', () => {
    expect(systemLanguage(['pt-PT'])).toBe('pt-BR');
    expect(systemLanguage(['PT'])).toBe('pt-BR');
  });

  it('is English when no tag is English or Portuguese', () => {
    expect(systemLanguage(['de-DE', 'ja'])).toBe('en');
    expect(systemLanguage([])).toBe('en');
  });
});

describe('a choice', () => {
  it('means the language named, or the system language for "system"', () => {
    expect(languageOf('en', ['pt-BR'])).toBe('en');
    expect(languageOf('pt-BR', ['en-GB'])).toBe('pt-BR');
    expect(languageOf('system', ['pt-PT'])).toBe('pt-BR');
    expect(languageOf('system', ['fr-FR'])).toBe('en');
  });

  it('means English for a value that is no choice at all', () => {
    expect(languageOf('fr' as LanguageChoice, ['pt-BR'])).toBe('en');
    setLanguage('pt-BR');
    setLanguage('x" a="' as LanguageChoice);
    expect(currentLanguage()).toBe('en');
  });
});

describe('a sentence', () => {
  it('fills every placeholder from the values given', () => {
    expect(translate('en', 'page.logFile', { path: '/x/shell.log' })).toBe('What went wrong is written to the log file: /x/shell.log');
    expect(translate('pt-BR', 'restore.status', { code: 3 })).toBe('A restauração terminou com status 3.');
  });

  it('leaves a placeholder with no value as written', () => {
    expect(translate('en', 'tray.tooltip')).toBe('Sensei Top: {state}');
    expect(translate('en', 'tray.tooltip', {})).toBe('Sensei Top: {state}');
  });

  it('reads in English when the language lacks the key', () => {
    const catalogue = ptBR as Record<string, string>;
    const saved = catalogue['menu.edit'];
    delete catalogue['menu.edit'];
    try {
      expect(translate('pt-BR', 'menu.edit')).toBe('Edit');
    } finally {
      catalogue['menu.edit'] = saved!;
    }
  });

  it('reads as the key itself when no catalogue has it, and never throws', () => {
    expect(translate('pt-BR', 'no.such.key' as Key)).toBe('no.such.key');
    expect(translate('en', 'no.such.key' as Key, { state: 'x' })).toBe('no.such.key');
  });
});

describe('the catalogues', () => {
  const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

  it('have exactly the same keys', () => {
    expect(Object.keys(ptBR).sort()).toEqual(Object.keys(en).sort());
  });

  it('have the same placeholders for every key', () => {
    const portuguese = ptBR as Record<string, string>;
    for (const [key, text] of Object.entries(en)) {
      expect({ key, placeholders: placeholders(portuguese[key] ?? '') }).toEqual({ key, placeholders: placeholders(text) });
    }
  });
});

describe('the current language', () => {
  it('is English before anything is set', () => {
    expect(currentLanguage()).toBe('en');
    expect(t('tray.menu.quit')).toBe('Quit');
  });

  it('follows the choice, "system" through the system tags', () => {
    setLanguage('pt-BR');
    expect(currentLanguage()).toBe('pt-BR');
    expect(t('tray.menu.quit')).toBe('Sair');
    setSystemTags(() => ['en-US']);
    setLanguage('system');
    expect(currentLanguage()).toBe('en');
  });

  it('tells a listener once per real change, never for a no-op, and not after it unsubscribes', () => {
    const heard: Language[] = [];
    const unsubscribe = onLanguageChange((language) => heard.push(language));
    setLanguage('en');
    expect(heard).toEqual([]);
    setLanguage('pt-BR');
    setLanguage('pt-BR');
    setSystemTags(() => ['pt-PT']);
    setLanguage('system');
    expect(heard).toEqual(['pt-BR']);
    setLanguage('en');
    expect(heard).toEqual(['pt-BR', 'en']);
    unsubscribe();
    setLanguage('pt-BR');
    expect(heard).toEqual(['pt-BR', 'en']);
  });
});

class FakeTray {
  static last: FakeTray | null = null;
  readonly tooltips: string[] = [];
  readonly menus: Array<Array<{ label?: string }>> = [];
  constructor() {
    FakeTray.last = this;
  }
  on(): void {}
  setImage(): void {}
  setToolTip(text: string): void {
    this.tooltips.push(text);
  }
  setContextMenu(menu: Array<{ label?: string }>): void {
    this.menus.push(menu);
  }
  destroy(): void {}
}

describe('the tray on a change of language', () => {
  const silentLog: Logger = { debug: () => {}, info: () => {}, warn: () => {}, error: () => {} };
  const noop = () => {};
  const makeTray = () =>
    new StatusTray(
      {
        Tray: FakeTray as unknown as typeof Tray,
        Menu: { buildFromTemplate: (template: unknown) => template } as unknown as typeof Menu,
        icon: (name) => name as unknown as NativeImage,
        fetch: (() => new Promise<Response>(() => {})) as typeof globalThis.fetch,
      },
      { open: noop, settings: noop, checkForUpdates: noop, restartToUpdate: noop, showLogs: noop, exportDiagnostics: noop, quit: noop },
      silentLog,
      'linux',
    );

  it('rebuilds the tooltip and the menu in the new language', () => {
    const tray = makeTray();
    const fake = FakeTray.last!;
    expect(fake.tooltips.at(-1)).toBe('Sensei Top: Starting the tracker');
    setLanguage('pt-BR');
    expect(fake.tooltips.at(-1)).toBe('Sensei Top: Iniciando o tracker');
    const labels = fake.menus.at(-1)!.map((item) => item.label);
    expect(labels[0]).toBe('Iniciando o tracker');
    expect(labels).toContain('Sair');
    tray.destroy();
  });

  it('stops listening once destroyed', () => {
    const tray = makeTray();
    const fake = FakeTray.last!;
    tray.destroy();
    const tooltips = fake.tooltips.length;
    const menus = fake.menus.length;
    setLanguage('pt-BR');
    expect(fake.tooltips).toHaveLength(tooltips);
    expect(fake.menus).toHaveLength(menus);
  });
});
