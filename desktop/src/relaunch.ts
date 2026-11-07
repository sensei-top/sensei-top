// Restart now (release 41 S8): what the shell does when the page asks to start
// again. Electron-free so the decision is testable; `main.ts` executes it.

import { HIDDEN_FLAG } from './autostart';

export interface RelaunchInput {
  /** A quit is already stopping the server. */
  stopping: boolean;
  /** A relaunch was already scheduled. */
  relaunching: boolean;
  /** `UpdateStatus.state`. */
  updateState: string;
  /** `process.argv`. */
  argv: readonly string[];
  /** `process.env`. */
  env: Readonly<Record<string, string | undefined>>;
}

export type RelaunchPlan =
  | { action: 'refused' }
  | { action: 'noop' }
  | { action: 'update' }
  | { action: 'relaunch'; options: { execPath?: string; args: string[] } };

/** A downloaded update is installed by `restartToUpdate`, not by a quit with
 *  install-on-quit armed: on Windows the silent installer and the relaunched
 *  app would race. `--hidden` is dropped so a copy started at login does not
 *  restart looking closed. */
export function planRelaunch(input: RelaunchInput): RelaunchPlan {
  if (input.relaunching) return { action: 'noop' };
  if (input.stopping) return { action: 'refused' };
  if (input.updateState === 'ready') return { action: 'update' };
  const options: { execPath?: string; args: string[] } = {
    args: input.argv.slice(1).filter((arg) => arg !== HIDDEN_FLAG),
  };
  if (input.env.APPIMAGE) options.execPath = input.env.APPIMAGE;
  return { action: 'relaunch', options };
}
