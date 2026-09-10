/**
 * The MCP server's page-index cache — one `IndexCache` per workspace root, for
 * the life of the process.
 *
 * The server is a long-lived process answering many tool calls against one
 * repository, and eight of the twelve tools begin with `loadContractOrScan`.
 * With no `.cms/` contract present — the common case, and a normal state
 * (decision D9) — every one of those calls was a full filesystem walk that
 * re-read and re-parsed every content file. Measured over lifehacker.dev's 382
 * pages: 44–123 ms per call. Handing the previous cache back in turns the walk
 * into a `stat` per candidate and no reads at all: 7–22 ms.
 *
 * Three things make it safe to keep, and none of them are a timer:
 *
 *   - **`buildIndex` invalidates itself.** The cache is keyed by mtime, and
 *     `IndexCache.fingerprint` covers the other staleness — a configuration
 *     change that alters the projection (a different title field, a different
 *     draft field) while every mtime stays put. A stale entry is detected by
 *     the same code path a cold start uses, so there is nothing here to get
 *     wrong.
 *   - **It is keyed by workspace root.** The server is launched with a `cwd`
 *     per folder, so in practice this map holds one entry; keying it anyway
 *     means a hand-run server pointed at a second repository cannot answer
 *     from the first one's pages.
 *   - **Nothing outside this file owns it.** `src/mcp/tools.ts` calls
 *     `loadContractCached` and never sees the map, which is what keeps that
 *     file's cache handling to a single import.
 *
 * The cache never leaves the process — it is not written to disk here. The
 * *extension* persists its own in `workspaceState` (`src/store.ts`); this one
 * is born with the server and dies with it.
 */

import { loadContractOrScan, type ContractScan, type IndexCache, type LogSink, type Zer0Config } from '../core';

/** Process-lifetime, keyed by `cfg.workspaceRoot`. Never persisted. */
const caches = new Map<string, IndexCache>();

/**
 * `loadContractOrScan`, with the previous scan's cache handed back in and the
 * one it produced kept.
 *
 * A `.cms/` contract that is present short-circuits before any scan, and
 * `loadContractOrScan` returns the cache it was given untouched — so storing
 * the result unconditionally is correct in both branches and never invents an
 * entry for a repository that was never scanned.
 */
export async function loadContractCached(cfg: Zer0Config, log?: LogSink): Promise<ContractScan> {
  const root = cfg.workspaceRoot;
  const contract = await loadContractOrScan(cfg, log, caches.get(root));
  if (contract.cache !== undefined) {
    caches.set(root, contract.cache);
  }
  return contract;
}

/**
 * Forget everything. Exists for tests and for a caller that has just told the
 * repository to rewrite itself — `zer0_contract normalize-apply` changes files
 * under this process's feet, and while the mtime check would catch that on the
 * next call anyway, dropping the entry makes the next answer unambiguous.
 */
export function clearIndexCaches(): void {
  caches.clear();
}

/** How many roots are cached. For a test that wants to prove reuse. */
export function cachedRootCount(): number {
  return caches.size;
}
