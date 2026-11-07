import { describe, expect, it } from 'vitest';
import { planRelaunch, type RelaunchInput } from './relaunch';

const base: RelaunchInput = {
  stopping: false,
  relaunching: false,
  updateState: 'idle',
  argv: ['/opt/app/sensei-top', '--hidden', '--x'],
  env: {},
};

describe('planRelaunch', () => {
  it('strips --hidden and leaves the executable to Electron without APPIMAGE', () => {
    expect(planRelaunch(base)).toEqual({ action: 'relaunch', options: { args: ['--x'] } });
  });

  it('uses the AppImage path only when set', () => {
    expect(planRelaunch({ ...base, env: { APPIMAGE: '/x/app.AppImage' } })).toEqual({
      action: 'relaunch',
      options: { execPath: '/x/app.AppImage', args: ['--x'] },
    });
    expect(planRelaunch({ ...base, env: { APPIMAGE: '' } })).toEqual({ action: 'relaunch', options: { args: ['--x'] } });
  });

  it('is refused while a quit is stopping the server', () => {
    expect(planRelaunch({ ...base, stopping: true })).toEqual({ action: 'refused' });
  });

  it('routes a ready update to the update', () => {
    expect(planRelaunch({ ...base, updateState: 'ready' })).toEqual({ action: 'update' });
  });

  it('is a no-op while a relaunch is scheduled', () => {
    expect(planRelaunch({ ...base, relaunching: true, stopping: true })).toEqual({ action: 'noop' });
  });
});
