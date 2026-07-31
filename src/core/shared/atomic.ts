/**
 * Atomic file write: temp file in the same directory, then `rename` over the
 * target. A killed process never leaves a half-written ledger, worklist or
 * index cache — a reader either sees the old file or the new one, never a
 * truncated one. Mirrors `ledger.py:_save` in the Python lane.
 *
 * The temp file lives in the *same* directory on purpose: `rename` is only
 * atomic within a filesystem, and `os.tmpdir()` is routinely a different one.
 *
 * Deliberately NOT used for user-edited markdown: replacing an article's inode
 * detaches open editors and file watchers from the file they were following.
 */

import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

/** Best-effort cleanup. Never throws: the caller is already handling a real
 *  failure and an undeletable temp file must not mask it. */
async function removeQuietly(filePath: string): Promise<void> {
  try {
    await fs.rm(filePath, { force: true });
  } catch {
    // Intentionally swallowed — see above. `force: true` already ignores a
    // missing file, so reaching here means the filesystem refused the unlink,
    // which is not something this layer can act on.
  }
}

/**
 * Write `data` to `filePath` atomically, creating parent directories as needed.
 * On any failure the temp file is removed and the original error is re-thrown,
 * so a failed write leaves no `.tmp` residue next to the target.
 */
export async function atomicWriteFile(filePath: string, data: string): Promise<void> {
  const dir = path.dirname(filePath);
  await fs.mkdir(dir, { recursive: true });

  const unique = `${process.pid.toString(36)}.${crypto.randomBytes(4).toString('hex')}`;
  const tmp = path.join(dir, `.${path.basename(filePath)}.${unique}.tmp`);

  try {
    await fs.writeFile(tmp, data, 'utf8');
    await fs.rename(tmp, filePath);
  } catch (error) {
    await removeQuietly(tmp);
    throw error;
  }
}

/** `atomicWriteFile` for JSON-ish payloads that must end with a newline. */
export async function atomicWriteText(filePath: string, data: string): Promise<void> {
  await atomicWriteFile(filePath, data.endsWith('\n') ? data : `${data}\n`);
}
