/**
 * One rule, and nothing else: **which of the open folders is the active site?**
 *
 * It lives alone in this file for one reason — it has to be testable without an
 * extension host. `src/sites.ts` owns the registry, and a registry needs
 * `vscode.EventEmitter`, `vscode.workspace` and a `WorkspaceStore` per folder;
 * the moment the rule shares a module with any of those, asking "what happens
 * when the explicitly picked site is closed?" costs a VS Code download and a
 * minute. So the rule is pure, takes three plain arguments, and is exercised by
 * the fast plain-Mocha suite in `src/test/core.test.ts`. `src/sites.ts`
 * re-exports it, so the public surface is still `sites.ts`'s.
 *
 * The rule acquires a fourth case sooner or later — "the folder the dashboard
 * is pinned to", "the folder the last publish went to" — and a rule nobody can
 * test is a rule nobody can change.
 */

/**
 * The active site's id, in order of precedence:
 *
 *   1. **An explicit pick that still exists.** Someone chose this site; a file
 *      opening in a sibling folder is not a reason to overrule them. The
 *      "still exists" half is the load-bearing one — a picked folder can be
 *      closed, and a stale id must fall through rather than blank the console.
 *   2. **The folder that owns the active editor.** With no explicit pick, the
 *      file in front of the person is the best available statement of intent.
 *   3. **The first folder.** The single-root answer, and the one this extension
 *      gave for its whole life before multi-root existed.
 *
 * `undefined` only when there are no folders at all — a folderless window,
 * where every surface renders its empty state and nothing is watched.
 *
 * `folderIds` is the *authority* on what exists: neither of the other two
 * arguments can name a site that is not in it.
 */
export function resolveActiveSite(
  folderIds: readonly string[],
  explicit: string | undefined,
  editorFolderId: string | undefined,
): string | undefined {
  if (folderIds.length === 0) {
    return undefined;
  }
  if (explicit !== undefined && folderIds.includes(explicit)) {
    return explicit;
  }
  if (editorFolderId !== undefined && folderIds.includes(editorFolderId)) {
    return editorFolderId;
  }
  return folderIds[0];
}
