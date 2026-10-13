// The shell's own text in the user's language (release plan 18, D4, D8): the
// tray, the app menu, the loading page and the dialogs. `desktop/` cannot
// import from `web/`, so the shell keeps a small flat catalogue of its own,
// `locales/<language>.json`, one key per sentence, `{name}` for a value
// filled in at the call.
//
// The language follows shell.json's `language` (`main.ts` sets it at launch,
// `settings.ts` on every change); "system" is the first English or
// Portuguese tag among the system's preferred languages, the same rule as
// `web/src/i18n.ts`'s `systemLanguage`. Whatever shows text and outlives a
// change (the tray) subscribes with `onLanguageChange`; the rest reads `t`
// when it builds its text.
//
// Electron-free: vitest imports it directly. `main.ts` hands over the
// system's tags as a function.

import en from './locales/en.json';
import ptBR from './locales/pt-BR.json';
import type { LanguageChoice } from './store';

export const LANGUAGES = ['en', 'pt-BR'] as const;
export type Language = (typeof LANGUAGES)[number];

/** Every key the English catalogue has: a misspelt key fails `typecheck`. */
export type Key = keyof typeof en;

const FALLBACK: Language = 'en';

const CATALOGUES: Record<Language, Readonly<Record<string, string>>> = {
  en,
  'pt-BR': ptBR,
};

/** The first tag that is English or Portuguese decides; Portuguese of any
 *  region is `pt-BR`; none of either is English. */
export function systemLanguage(tags: readonly string[]): Language {
  for (const tag of tags) {
    const lower = tag.toLowerCase();
    if (lower === 'pt' || lower.startsWith('pt-')) return 'pt-BR';
    if (lower === 'en' || lower.startsWith('en-')) return 'en';
  }
  return FALLBACK;
}

/** The language a choice means, given the system's preferred tags. A value
 *  that is no choice at all (the IPC path is typed, not checked) is English. */
export function languageOf(choice: LanguageChoice, tags: readonly string[]): Language {
  if (choice === 'system') return systemLanguage(tags);
  return (LANGUAGES as readonly string[]).includes(choice) ? choice : FALLBACK;
}

/** `key` in `language`, every `{name}` filled from `params`. A key the
 *  language lacks reads in English, and one English lacks reads as the key.
 *  A placeholder with no value is left as written. */
export function translate(language: Language, key: Key, params?: Record<string, string | number>): string {
  const text = CATALOGUES[language]?.[key] ?? CATALOGUES[FALLBACK][key] ?? key;
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : placeholder,
  );
}

let systemTags: () => readonly string[] = () => [];
let current: Language = FALLBACK;
const listeners = new Set<(language: Language) => void>();

/** Where "system" reads the system's preferred languages from. */
export function setSystemTags(tags: () => readonly string[]): void {
  systemTags = tags;
}

/** The user's choice: the shell's text follows it. Listeners hear only a
 *  change of the language itself. */
export function setLanguage(choice: LanguageChoice): void {
  const next = languageOf(choice, systemTags());
  if (next === current) return;
  current = next;
  for (const listener of [...listeners]) listener(next);
}

export function currentLanguage(): Language {
  return current;
}

/** `key` in the current language. */
export function t(key: Key, params?: Record<string, string | number>): string {
  return translate(current, key, params);
}

/** Calls `listener` on every change of language; returns the unsubscribe. */
export function onLanguageChange(listener: (language: Language) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
