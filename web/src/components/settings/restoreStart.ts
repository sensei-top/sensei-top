import type { BackupSnapshot } from '../../bridge'

/** Where a restore starts: the list of dated copies, or the file picker
 *  when the button has no list call, the list is empty, or the call is
 *  rejected. */
export async function restoreStart(
  listBackups?: () => Promise<BackupSnapshot[]>,
): Promise<{ kind: 'list'; snapshots: BackupSnapshot[] } | { kind: 'picker' }> {
  const snapshots = listBackups ? await listBackups().catch(() => []) : []
  return snapshots.length > 0 ? { kind: 'list', snapshots } : { kind: 'picker' }
}
