// The cloud settings this build was made with: the only reader of the
// generated `build-config.ts` (`scripts/build-config.mjs`). A build made
// with none of the variables set has no Supabase project and no DSN, and
// every caller treats `null` as "this build has no account and sends
// nothing".
//
// Electron-free: vitest imports it directly.

import { BUILD_CONFIG } from './build-config';

export interface RawBuildConfig {
  readonly supabaseUrl?: string;
  readonly supabaseAnonKey?: string;
  readonly sentryDsnDesktop?: string;
  readonly sentryDsnLocalApi?: string;
}

export interface SupabaseConfig {
  /** The project's base URL, no trailing slash. */
  readonly url: string;
  readonly anonKey: string;
}

export interface CloudConfig {
  /** `null` when the URL or the anon key is missing, or the URL is not http(s). */
  readonly supabase: SupabaseConfig | null;
  readonly sentryDsnDesktop: string | null;
  readonly sentryDsnLocalApi: string | null;
}

function present(value: string | undefined): string | null {
  const trimmed = value?.trim() ?? '';
  return trimmed === '' ? null : trimmed;
}

/** The settings `raw` holds, each blank or malformed one absent. */
export function parseBuildConfig(raw: RawBuildConfig): CloudConfig {
  const url = present(raw.supabaseUrl);
  const anonKey = present(raw.supabaseAnonKey);
  let supabase: SupabaseConfig | null = null;
  if (url && anonKey) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === 'https:' || parsed.protocol === 'http:') {
        supabase = { url: url.replace(/\/+$/, ''), anonKey };
      }
    } catch {
      // not a URL: no project
    }
  }
  return {
    supabase,
    sentryDsnDesktop: present(raw.sentryDsnDesktop),
    sentryDsnLocalApi: present(raw.sentryDsnLocalApi),
  };
}

/** This build's settings. */
export const cloudConfig: CloudConfig = parseBuildConfig(BUILD_CONFIG);
