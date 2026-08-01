/**
 * Read and write one content file. **This is the only module in the codebase
 * that writes user markdown**, which is why it is small, boring, and paranoid.
 *
 * Three properties it guarantees:
 *
 *   1. **An empty change set never touches the disk.** `writeArticle` with no
 *      changes returns before it opens the file, and even with changes it
 *      compares the assembled bytes against what it read and skips a write that
 *      would be a no-op. Saving a panel where nothing was edited must not churn
 *      the file's mtime, because a watcher is listening and a git diff is
 *      watching after that.
 *   2. **Writes are not atomic, on purpose.** `atomicWriteFile` replaces the
 *      inode, which detaches open editors and file watchers from the file they
 *      were following. Ledgers and caches get atomic writes; the article the
 *      user is looking at gets a plain `writeFile`.
 *   3. **The dialect and the byte prefix come from the file.** A BOM survives,
 *      CRLF survives, and a TOML file stays TOML even when the workspace is
 *      configured for YAML.
 *
 * `writeArticle` refreshes the `Article` it was handed to match what was
 * written, so a caller can apply two edits in a row without re-reading. That is
 * mutation of an argument, which is normally a smell; here the alternative is a
 * second disk read after every field edit, or a stale `block` silently
 * addressing the wrong line ranges.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { formatDate } from '../shared/dates';
import type { ContentType, Field, Zer0Config } from '../shared/types';
import {
  asString,
  ownValue,
  setOwn,
  splitFrontMatter,
  type FmBlock,
  type FmValue,
  type FrontMatter,
} from './frontmatter';
import {
  applyChanges,
  serializeFrontMatter,
  serializeOptions,
  stitch,
  updateFrontMatterKeys,
  type KeyChange,
} from './serialize';

export interface Article {
  filePath: string;
  /** `null` when the file has no readable front matter — a normal state. */
  block: FmBlock | null;
  data: FrontMatter;
  /** Everything after the closing fence; the whole file when `block` is null. */
  body: string;
  /** The exact bytes read from disk. */
  raw: string;
}

const BOM = '\uFEFF';

/**
 * Keys stamped as the modified date when the content type marks no field with
 * `isModifiedDate`. Only stamped when the article *already* carries the key —
 * we update what a site is using, never introduce a convention it isn't.
 */
export const CONVENTIONAL_MODIFIED_KEYS: readonly string[] = [
  'lastmod',
  'last_modified_at',
  'lastModified',
  'modified',
  'updated',
];

/** Build an `Article` from text already in memory. Never throws. */
export function parseArticle(filePath: string, text: string): Article {
  const { block, body } = splitFrontMatter(text);
  return {
    filePath,
    block,
    data: block === null ? {} : { ...block.data },
    body,
    raw: text,
  };
}

/** Read and parse a content file. Throws only if the file cannot be read. */
export async function readArticle(filePath: string): Promise<Article> {
  return parseArticle(filePath, await fs.readFile(filePath, 'utf8'));
}

/**
 * Apply `changes` to the article's front matter and write the file.
 *
 * Line surgery first (`updateFrontMatterKeys`), so only the changed keys' lines
 * move. A full re-serialization is the fallback, and it is deliberately **not**
 * available for an existing YAML block.
 *
 * Re-emitting rebuilds the block out of what the parser understood, and
 * `frontmatter.ts` documents a list of YAML it does not understand: anchors and
 * aliases, tags, comments, plain scalars wrapped onto a second line. Those
 * survive on disk only because surgery never re-emits them. Falling back for a
 * YAML block turned "a construct we cannot read is a construct we cannot
 * corrupt" into its opposite — a file with `defaults: &series` came back with
 * the anchored mapping's contents deleted and `defaults` set to the literal
 * string `"&series"`, for the sake of an edit to an unrelated key.
 *
 * So: TOML and JSON blocks re-emit (their dialects carry no comments in any
 * file this CMS writes, and that trade is documented in `serialize.ts`), a file
 * with *no* block gets one built from scratch, and a YAML block that surgery
 * declines throws. The only thing surgery still declines is a nested path whose
 * parent holds a scalar or a sequence — which `applyChanges` refuses to apply
 * too, so the re-emit never even made the requested edit. Refusing loudly is
 * the honest answer; silently rewriting the file around a change we did not
 * make is not.
 */
export async function writeArticle(
  article: Article,
  changes: readonly KeyChange[],
  cfg: Zer0Config,
): Promise<void> {
  if (changes.length === 0) {
    return;
  }

  const format = article.block?.format ?? cfg.frontMatter.format;
  const opts = serializeOptions(cfg, format);

  const surgical =
    article.block === null
      ? null
      : updateFrontMatterKeys(article.block.raw, changes, opts, article.block.eol);
  if (surgical === null && article.block !== null && article.block.format === 'yaml') {
    throw new Error(
      `cannot write ${path.basename(article.filePath)}: ` +
        `${changes.map((c) => c.key).join(', ')} sits under a key that holds a scalar or a ` +
        'sequence, and rewriting the block to make room would discard front matter this ' +
        'parser cannot read back. Edit the file directly.',
    );
  }
  const nextRaw = surgical ?? serializeFrontMatter(applyChanges(article.data, changes), opts);

  const hadBom = article.raw.startsWith(BOM);
  const prefix = article.block === null ? (hadBom ? BOM : '') : article.raw.slice(0, article.block.start);
  const body = article.block === null ? article.body.slice(prefix.length) : article.body;

  const next = prefix + stitch(article.block, nextRaw, body, format);
  if (next === article.raw) {
    return;
  }

  await fs.writeFile(article.filePath, next, 'utf8');

  const written = parseArticle(article.filePath, next);
  article.block = written.block;
  article.data = written.data;
  article.body = written.body;
  article.raw = written.raw;
}

function isPlainObject(value: unknown): value is FrontMatter {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function cloneMap(value: FrontMatter): FrontMatter {
  const out: FrontMatter = {};
  for (const [key, item] of Object.entries(value)) {
    setOwn(out, key, cloneValue(item));
  }
  return out;
}

function cloneValue(value: FmValue): FmValue {
  if (Array.isArray(value)) {
    return value.map(cloneValue);
  }
  if (isPlainObject(value)) {
    return cloneMap(value);
  }
  return value;
}

/**
 * Express "set the value at `path`" as changes `writeArticle` can apply.
 *
 * A single-segment path is a plain key change. A deeper path becomes a dotted
 * key, which the line surgery resolves to the exact leaf line — a one-line diff
 * for a nested field, not a rewrite of the whole parent block.
 *
 * A segment that itself contains a `.` cannot be written as a dotted key, so
 * the whole top-level container is rebuilt instead. Paths address mappings
 * only; there is no syntax for indexing into a sequence.
 */
export function setFieldValue(data: FrontMatter, path: readonly string[], value: FmValue): KeyChange[] {
  const head = path[0];
  if (head === undefined) {
    return [];
  }
  if (path.length === 1) {
    return [{ key: head, value }];
  }
  if (!path.some((segment) => segment.includes('.'))) {
    return [{ key: path.join('.'), value }];
  }

  const existing = ownValue(data, head);
  const container: FrontMatter = isPlainObject(existing) ? cloneMap(existing) : {};
  let node = container;
  const inner = path.slice(1);
  for (const segment of inner.slice(0, -1)) {
    const next = ownValue(node, segment);
    if (isPlainObject(next)) {
      node = next;
      continue;
    }
    const created: FrontMatter = {};
    setOwn(node, segment, created);
    node = created;
  }
  const leaf = inner[inner.length - 1];
  if (leaf !== undefined) {
    setOwn(node, leaf, value);
  }
  return [{ key: head, value: container }];
}

interface DateTarget {
  path: string[];
  format: string | undefined;
}

/** Walk a field tree collecting the dotted paths of `isModifiedDate` fields. */
function modifiedDateFields(fields: readonly Field[], prefix: readonly string[]): DateTarget[] {
  const found: DateTarget[] = [];
  for (const field of fields) {
    const here = [...prefix, field.name];
    if (field.type === 'datetime' && field.isModifiedDate === true) {
      found.push({ path: here, format: field.dateFormat });
    }
    if (field.type === 'fields' && field.fields !== undefined) {
      found.push(...modifiedDateFields(field.fields, here));
    }
  }
  return found;
}

function valueAt(data: FrontMatter, path: readonly string[]): FmValue | undefined {
  let node: FmValue | undefined = data;
  for (const segment of path) {
    if (!isPlainObject(node)) {
      return undefined;
    }
    node = ownValue(node, segment);
  }
  return node;
}

/**
 * The changes that stamp the article's modified date with `now`.
 *
 * Source of the target key, in order: a `datetime` field the content type marks
 * with `isModifiedDate`, else a conventional key (`CONVENTIONAL_MODIFIED_KEYS`)
 * the article already carries. Nothing is stamped when neither exists — this
 * function does not invent a date field a site never asked for.
 *
 * Format: the field's `dateFormat`, else `zer0Cms.date.format`. The result is
 * always a *string*; per the front-matter rule, dates never round-trip through
 * a `Date` on their way back to disk.
 *
 * The `content.autoUpdateModifiedDate` setting is the *caller's* gate — the
 * explicit "set last modified" command stamps regardless of it.
 */
export function stampModified(
  article: Article,
  cfg: Zer0Config,
  ct: ContentType | undefined,
  now: Date = new Date(),
): KeyChange[] {
  const targets = modifiedDateFields(ct?.fields ?? [], []);

  if (targets.length === 0) {
    for (const key of CONVENTIONAL_MODIFIED_KEYS) {
      if (Object.prototype.hasOwnProperty.call(article.data, key)) {
        targets.push({ path: [key], format: undefined });
        break;
      }
    }
  }

  const changes: KeyChange[] = [];
  for (const target of targets) {
    const stamp = formatDate(now, target.format ?? cfg.date.format, cfg.date.timezone);
    if (asString(valueAt(article.data, target.path)) === stamp) {
      continue; // already current — an unchanged key is not a change
    }
    changes.push({ key: target.path.join('.'), value: stamp });
  }
  return changes;
}

/** Whether this file's extension is one the workspace treats as content. */
export function isSupported(cfg: Zer0Config, filePath: string): boolean {
  const ext = path.extname(filePath).replace(/^\./, '').toLowerCase();
  if (ext.length === 0) {
    return false;
  }
  return cfg.content.supportedFileTypes.some(
    (type) => type.replace(/^\./, '').toLowerCase() === ext,
  );
}
