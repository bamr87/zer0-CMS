/**
 * The idempotency ledger — one flat JSON file recording what has already been
 * published, keyed by canonical URL.
 *
 * The key *is* the coordination. Whichever lane publishes a URL first writes
 * the key; every other lane — this extension, the MCP server, the Python CI
 * job — looks it up and skips. No lock, no lease, no shared process. That is
 * the whole design, and it only works if the two lanes agree on the file byte
 * for byte, which is why writes go through `pyJsonDump` with Python's
 * `indent=2, sort_keys=True, ensure_ascii=True` plus a trailing newline, and
 * why they are atomic (a half-written ledger is a double publish waiting to
 * happen).
 *
 * Atomic writes are not the same as serializable updates, though: `record` and
 * `writeMeta` each read the whole file, change one key and write it back, and
 * two of those interleaved lose a key outright — which for the ledger means the
 * URL republishes. See `mutate` below for what closes that inside this process
 * and what it can only converge on across processes.
 *
 * Keys beginning with `_` are metadata, not shares. `_meta` is the only one
 * this codebase writes today; the prefix convention means a future lane can
 * add its own without breaking anyone's iteration — provided everyone
 * enumerates shares through `shareEntries` rather than `Object.entries`.
 *
 * A missing ledger and a corrupt ledger both read as `{}`. "Nothing has been
 * published" is the safe answer to both: it makes the caller check its other
 * gates rather than trust a file it could not read.
 */

import { atomicWriteFile } from '../shared/atomic';
import { pyJsonDump, readJsonFile } from '../shared/jsonio';
import { utcStamp } from '../shared/timestamp';

/** The metadata key this codebase writes. Never enumerated as a share. */
export const TOKEN_KEY = '_meta';

export interface LedgerEntry {
  /** Stable identity of the published artifact, e.g. `jekyll:posts/x.md`. */
  urn: string;
  /** `utcStamp()` — second precision, no milliseconds. */
  posted_at: string;
  /** `article` or `update`. */
  type: string;
  /** Workspace-relative path of the draft or source file it came from. */
  source_file?: string;
  /** Id of the `PublishTarget` that produced the artifact. */
  target?: string;
}

/**
 * The file's shape. Entries are `Partial<LedgerEntry>` because the Python lane
 * and older versions of this one write keys we do not model — and dropping
 * them on a rewrite would be data loss.
 */
export type Ledger = Record<string, Partial<LedgerEntry> & Record<string, unknown>>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Read the ledger. Missing, unreadable and corrupt all yield `{}`. */
export async function loadLedger(ledgerPath: string): Promise<Ledger> {
  const raw = await readJsonFile<unknown>(ledgerPath);
  if (!isPlainObject(raw)) {
    return {};
  }
  const out: Ledger = {};
  for (const [key, value] of Object.entries(raw)) {
    if (isPlainObject(value)) {
      // `defineProperty`, not `out[key] =`: a ledger carrying a `__proto__` key
      // would otherwise reach the accessor on `Object.prototype` and reshape
      // the object instead of recording an entry.
      Object.defineProperty(out, key, {
        value: value as Ledger[string],
        writable: true,
        enumerable: true,
        configurable: true,
      });
    }
  }
  return out;
}

/**
 * Write the ledger. Exactly `json.dump(data, f, indent=2, sort_keys=True)` plus
 * a trailing newline: `sort_keys` makes the file order-independent so two lanes
 * never produce a reordering diff, and `ensure_ascii` escapes non-ASCII URLs
 * the same way on both sides.
 */
export async function saveLedger(ledgerPath: string, data: Ledger): Promise<void> {
  await atomicWriteFile(
    ledgerPath,
    `${pyJsonDump(data, { indent: 2, sortKeys: true, ensureAscii: true })}\n`,
  );
}

// ---------------------------------------------------------------------------
// Serializing the read-modify-write cycles
// ---------------------------------------------------------------------------

/**
 * One promise chain per ledger file, so the read → mutate → write cycles below
 * never interleave *inside this process*.
 *
 * `atomicWriteFile` makes each write complete; it cannot make a cycle
 * serializable. Two `record()` calls that start together both read the same
 * ledger, both add their own key to that snapshot, and the second write
 * replaces the first — the first URL vanishes from the ledger even though its
 * artifact shipped, and the next publish of it sails past the `alreadyPublished`
 * gate and ships a duplicate. The extension, the panel and the dashboard all
 * run in one extension host, so this queue covers every lane that shares it.
 *
 * It does **not** cover the other processes named in the header — the bundled
 * MCP server and the Python CI job. Nothing in one process can lock a file
 * against another one that does not look for the lock, and inventing a lock
 * protocol the Python lane does not implement would be theatre. What covers
 * that case is the verify-and-retry in `mutate` below: after writing, the file
 * is read back, and a cycle whose key did not survive runs again on top of
 * whatever landed instead. Convergent rather than exclusive, which is the
 * strongest honest guarantee for a file with no lease.
 */
const inFlight = new Map<string, Promise<unknown>>();

const MAX_ATTEMPTS = 4;

async function mutate<T>(
  ledgerPath: string,
  apply: (data: Ledger) => T,
  survived: (data: Ledger, result: T) => boolean,
): Promise<T> {
  const run = async (): Promise<T> => {
    let last: T | undefined;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      const data = await loadLedger(ledgerPath);
      const result = apply(data);
      last = result;
      await saveLedger(ledgerPath, data);
      if (survived(await loadLedger(ledgerPath), result)) {
        return result;
      }
      // Another process wrote between our write and our read-back, and its
      // snapshot did not contain our change. Re-apply on top of theirs.
    }
    // `last` is assigned on the first iteration; `MAX_ATTEMPTS` is >= 1.
    return last as T;
  };

  // Chain onto whatever is already queued for this file, and keep the chain
  // alive across a rejection so one failure does not wedge the queue.
  const previous = inFlight.get(ledgerPath) ?? Promise.resolve();
  const next = previous.then(run, run);
  inFlight.set(
    ledgerPath,
    next.then(
      () => undefined,
      () => undefined,
    ),
  );
  return next;
}

export async function getEntry(ledgerPath: string, url: string): Promise<Ledger[string] | undefined> {
  return (await loadLedger(ledgerPath))[url];
}

/** Has this canonical URL already been published, by either lane? */
export async function isPublished(ledgerPath: string, url: string): Promise<boolean> {
  const entry = await getEntry(ledgerPath, url);
  return typeof entry?.urn === 'string' && entry.urn !== '';
}

/**
 * Record a publish.
 *
 * The entry is **replaced**, not merged: a re-publish of the same URL is a new
 * fact about that URL, and merging would leave the ledger claiming a target or
 * a source file that no longer produced it. Absent options are omitted
 * entirely rather than written as `null`, because the Python lane's readers
 * test for key presence.
 */
export async function record(
  ledgerPath: string,
  url: string,
  urn: string,
  opts: { sourceFile?: string; kind?: string; target?: string } = {},
): Promise<LedgerEntry> {
  const entry: LedgerEntry = {
    urn,
    posted_at: utcStamp(),
    type: opts.kind ?? 'article',
  };
  if (opts.sourceFile) {
    entry.source_file = opts.sourceFile;
  }
  if (opts.target) {
    entry.target = opts.target;
  }
  return mutate(
    ledgerPath,
    (data) => {
      Object.defineProperty(data, url, {
        value: { ...entry },
        writable: true,
        enumerable: true,
        configurable: true,
      });
      return entry;
    },
    (data) => data[url]?.urn === urn,
  );
}

/**
 * The published shares, and only those: `_`-prefixed metadata keys are skipped,
 * and so is any entry without a `urn` (a half-written record, or a key another
 * lane parked there). **This is the only correct way to enumerate the ledger.**
 */
export function shareEntries(ledger: Ledger): Array<[string, LedgerEntry]> {
  const out: Array<[string, LedgerEntry]> = [];
  for (const [key, value] of Object.entries(ledger)) {
    if (key.startsWith('_')) {
      continue;
    }
    if (typeof value.urn !== 'string' || value.urn === '') {
      continue;
    }
    out.push([
      key,
      {
        urn: value.urn,
        posted_at: typeof value.posted_at === 'string' ? value.posted_at : '',
        type: typeof value.type === 'string' ? value.type : 'article',
        ...(typeof value.source_file === 'string' ? { source_file: value.source_file } : {}),
        ...(typeof value.target === 'string' ? { target: value.target } : {}),
      },
    ]);
  }
  return out;
}

/** Workspace-relative source files that have already been published. */
export function publishedSourceFiles(ledger: Ledger): Set<string> {
  const out = new Set<string>();
  for (const [, entry] of shareEntries(ledger)) {
    if (entry.source_file) {
      out.add(entry.source_file);
    }
  }
  return out;
}

/** Read the `_meta` block. Never a share; always an object. */
export async function readMeta(ledgerPath: string): Promise<Record<string, unknown>> {
  const meta = (await loadLedger(ledgerPath))[TOKEN_KEY];
  return meta === undefined ? {} : { ...meta };
}

/**
 * Merge `patch` into the `_meta` block, leaving every share untouched.
 *
 * Same queue as `record`: this is a read-modify-write over the whole file, and
 * an unsynchronised one dropped whichever share a concurrent `record` had just
 * added.
 */
export async function writeMeta(ledgerPath: string, patch: Record<string, unknown>): Promise<void> {
  const keys = Object.keys(patch);
  await mutate(
    ledgerPath,
    (data) => {
      data[TOKEN_KEY] = { ...(data[TOKEN_KEY] ?? {}), ...patch } as Ledger[string];
      return undefined;
    },
    (data) => {
      const meta = data[TOKEN_KEY];
      return (
        meta !== undefined && keys.every((key) => Object.prototype.hasOwnProperty.call(meta, key))
      );
    },
  );
}
