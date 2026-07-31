/**
 * The page index — every registered content folder scanned into `PageEntry[]`,
 * and the `ContentRecord` projection that stands in for the `.cms/` contract
 * when a repository has not adopted the engine.
 *
 * Two jobs, both of them the CMS's answer to "what content exists here?".
 *
 * **The scan** walks each `ContentFolder` (honouring `excludeSubdir` and
 * `excludePaths`), reads the front matter of every supported file, and projects
 * it into the flat `PageEntry` the dashboard, the trees and the panel's
 * "recently modified" list all read. A file with no readable front matter is
 * *skipped*, not indexed: a CMS that lists a `README.md` alongside articles is
 * a CMS people stop trusting. The scan is keyed by mtime, so a refresh over an
 * unchanged tree re-reads nothing — the cached `PageEntry` objects are returned
 * by identity, which is both the cheap path and the property the tests assert.
 *
 * **The projection** (`pageToRecord`) is decision D9 made concrete. `.cms/`
 * absence is a normal state, so the same `ContentRecord` shape is produced from
 * the filesystem, with `health: -1` and `freshness: 'unknown'` announcing "not
 * measured" rather than inventing a score. Under those two values the
 * distributable rule degrades honestly to *not a draft and has a title* — the
 * only claim a front-matter scan can actually support. Ported from BASH-CMS's
 * `core/content/scan.ts`, widened from its single glob list to zer0-CMS's
 * registered folders and richer page model.
 *
 * Pure Node: no `vscode`, no npm, no editor state. The shell owns the cache's
 * storage (`zer0Cms:Pages:Cache` in `workspaceState`); this module only builds
 * and consumes it.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { relPath as toRelPath } from '../shared/config';
import { parseDate } from '../shared/dates';
import { compileGlob, globMatches, SKIP_DIRS, toPosix, type CompiledGlob } from '../shared/glob';
import {
  NOOP_LOG,
  type ContentFolder,
  type ContentRecord,
  type ContentType,
  type Field,
  type LogSink,
  type PageEntry,
  type Zer0Config,
} from '../shared/types';
import { CONVENTIONAL_MODIFIED_KEYS } from './article';
import { resolveContentType } from './contentType';
import { resolveFolders } from './folders';
import { asBool, asList, asString, splitFrontMatter, type FmValue, type FrontMatter } from './frontmatter';
import type { ArticleDetails } from './seo';
import { applyCommaSeparatedFields } from './serialize';

// ---------------------------------------------------------------------------
// The cache
// ---------------------------------------------------------------------------

/**
 * The mtime cache. Keys are absolute paths, so a cache is only meaningful for
 * the workspace that produced it — `fingerprint` catches the other way a cache
 * goes stale, a settings change that alters the projection (a different title
 * field, a different draft field) while every file's mtime stays put.
 *
 * `skipped` remembers the files that had no front matter. Without it, every
 * refresh would re-read every `README.md` in the tree forever, and "a second
 * run parses zero files" would be false in any real repository.
 */
export interface IndexCache {
  version: 1;
  entries: Record<string, { mtime: number; page: PageEntry }>;
  /** Absolute path → mtime of files that hold no front matter. */
  skipped?: Record<string, number>;
  /** Config bits that affect the projection; a change invalidates everything. */
  fingerprint?: string;
}

const CACHE_VERSION = 1;

export function emptyIndexCache(): IndexCache {
  return { version: CACHE_VERSION, entries: {}, skipped: {}, fingerprint: '' };
}

/**
 * Validate something that came back from `workspaceState` (or a JSON file).
 * Anything that is not a v1 cache is treated as no cache at all — a bad cache
 * must cost a rescan, never a crash or a wrong page list.
 */
export function asIndexCache(value: unknown): IndexCache | undefined {
  if (typeof value !== 'object' || value === null) {
    return undefined;
  }
  const candidate = value as Partial<IndexCache>;
  if (candidate.version !== CACHE_VERSION || typeof candidate.entries !== 'object') {
    return undefined;
  }
  if (candidate.entries === null) {
    return undefined;
  }
  return candidate as IndexCache;
}

/**
 * The configuration a cached `PageEntry` was built under. Cheap to compute,
 * readable in a log line, and unambiguous: two configs that differ in any of
 * these produce different pages from the same bytes.
 */
function fingerprintOf(cfg: Zer0Config): string {
  return JSON.stringify({
    root: toPosix(cfg.workspaceRoot),
    title: cfg.seo.titleField,
    description: cfg.seo.descriptionField,
    draft: cfg.draftField,
    csv: cfg.frontMatter.commaSeparatedFields,
    types: cfg.contentTypes.map((ct) => ct.name),
    files: cfg.content.supportedFileTypes,
  });
}

// ---------------------------------------------------------------------------
// Walking the folders
// ---------------------------------------------------------------------------

interface Candidate {
  filePath: string;
  relPath: string;
  folder: ContentFolder;
}

/** `['md','mdx']` → `.md`, `.mdx`, lower-cased and dot-prefixed. */
function extensionSet(cfg: Zer0Config): ReadonlySet<string> {
  const out = new Set<string>();
  for (const type of cfg.content.supportedFileTypes) {
    const ext = type.trim().toLowerCase();
    if (ext !== '') {
      out.add(ext.startsWith('.') ? ext : `.${ext}`);
    }
  }
  return out.size === 0 ? new Set(['.md']) : out;
}

async function walkFolder(
  dir: string,
  recurse: boolean,
  extensions: ReadonlySet<string>,
  out: string[],
): Promise<void> {
  let entries;
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    // A registered folder that does not exist yet is a normal state — an empty
    // result says so, and the caller reports it in its own words.
    return;
  }

  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!recurse || SKIP_DIRS.has(entry.name) || entry.name.startsWith('.')) {
        continue;
      }
      await walkFolder(full, recurse, extensions, out);
    } else if (entry.isFile() && extensions.has(path.extname(entry.name).toLowerCase())) {
      out.push(full);
    }
  }
}

/** Everything `excludePaths` says to leave alone, compiled once per folder. */
function excludesOf(folder: ContentFolder): CompiledGlob[] {
  return (folder.excludePaths ?? [])
    .filter((value) => value.trim() !== '')
    .map((value) => compileGlob(value.trim()));
}

/**
 * The files worth reading, deduplicated across overlapping folders.
 *
 * When two registered folders both contain a file, the *deeper* one owns it —
 * `pages/_posts/tech` is a more specific answer to "where does this live" than
 * `pages/_posts`, and it is the folder whose `contentTypes` should apply.
 */
async function collectCandidates(
  cfg: Zer0Config,
  folders: readonly ContentFolder[],
  log: LogSink,
): Promise<Candidate[]> {
  const extensions = extensionSet(cfg);
  const byPath = new Map<string, Candidate>();

  for (const folder of folders) {
    if (folder.path === '') {
      continue;
    }
    const excludes = excludesOf(folder);
    const folderRoot = toPosix(folder.path).replace(/\/+$/, '');
    const files: string[] = [];
    await walkFolder(folder.path, folder.excludeSubdir !== true, extensions, files);

    for (const filePath of files) {
      const posix = toPosix(filePath);
      const relative = toRelPath(cfg, filePath);
      const withinFolder = posix.startsWith(`${folderRoot}/`)
        ? posix.slice(folderRoot.length + 1)
        : posix;
      if (excludes.length > 0 && (globMatches(relative, excludes) || globMatches(withinFolder, excludes))) {
        continue;
      }
      const existing = byPath.get(filePath);
      if (existing === undefined || folder.path.length > existing.folder.path.length) {
        byPath.set(filePath, { filePath, relPath: relative, folder });
      }
    }
    log.verbose(`page index: ${files.length} candidate file(s) under ${folderRoot}`);
  }

  return [...byPath.values()].sort((a, b) => (a.relPath < b.relPath ? -1 : a.relPath > b.relPath ? 1 : 0));
}

// ---------------------------------------------------------------------------
// Projecting a file into a PageEntry
// ---------------------------------------------------------------------------

const FILENAME_DATE_RE = /^(\d{4}-\d{2}-\d{2})-/;

/** Filename stem with a date prefix and the extension removed. */
function fileSlug(relPosix: string): string {
  const base = relPosix.split('/').pop() ?? '';
  return base.replace(/\.[^./]+$/, '').replace(FILENAME_DATE_RE, '');
}

/**
 * Keys a site conventionally uses for its card image, in preference order.
 * Only consulted when no field is marked `isPreviewImage` — an explicit
 * declaration in the content type always wins.
 */
const THUMBNAIL_KEYS: readonly string[] = [
  'image',
  'preview',
  'thumbnail',
  'cover',
  'featured_image',
  'banner',
];

/** The first field marked `isPreviewImage`, at any nesting depth. */
function previewField(fields: readonly Field[]): Field | undefined {
  for (const field of fields) {
    if (field.isPreviewImage === true && field.type === 'image') {
      return field;
    }
    const nested = previewField(field.fields ?? []);
    if (nested !== undefined) {
      return nested;
    }
  }
  return undefined;
}

/** An image value that may be a bare path or an `{ src, alt }` object. */
function imagePath(value: FmValue | undefined): string {
  if (typeof value === 'string') {
    return value.trim();
  }
  if (Array.isArray(value)) {
    return imagePath(value[0]);
  }
  if (value !== null && typeof value === 'object') {
    return asString(value.src ?? value.path).trim();
  }
  return '';
}

function previewImageOf(data: FrontMatter, ct: ContentType): string {
  const declared = previewField(ct.fields);
  if (declared !== undefined) {
    const value = imagePath(data[declared.name]);
    if (value !== '') {
      return value;
    }
  }
  for (const key of THUMBNAIL_KEYS) {
    const value = imagePath(data[key]);
    if (value !== '') {
      return value;
    }
  }
  return '';
}

/**
 * The draft flag as the workspace has configured it. A `choice` draft field
 * keeps its raw string — `status: in-review` is information the dashboard's
 * state tabs need, and flattening it to `true` would throw it away.
 */
function draftValue(cfg: Zer0Config, data: FrontMatter): boolean | string {
  const raw = data[cfg.draftField.name];
  if (typeof raw === 'string') {
    return raw;
  }
  const flag = asBool(raw);
  return cfg.draftField.invert === true ? !flag : flag;
}

/** The publish date as written, preferring front matter over the filename. */
function dateValue(data: FrontMatter, relPosix: string): string | null {
  const written = asString(data.date).trim();
  if (written !== '') {
    return written;
  }
  const base = relPosix.split('/').pop() ?? '';
  const match = FILENAME_DATE_RE.exec(base);
  return match?.[1] ?? null;
}

function toPageEntry(
  cfg: Zer0Config,
  candidate: Candidate,
  data: FrontMatter,
  modified: number,
): PageEntry {
  const ct = resolveContentType(cfg, data, candidate.filePath);
  const date = dateValue(data, candidate.relPath);
  const published = date === null ? null : parseDate(date);
  // `seo.titleField` first, then the conventional `title`: a workspace that
  // points SEO at `seoTitle` still has pages whose *name* is `title`, and a
  // dashboard full of untitled cards would be the alternative.
  const title = asString(data[cfg.seo.titleField], asString(data.title)).trim();
  const description = asString(data[cfg.seo.descriptionField], asString(data.description)).trim();

  return {
    filePath: candidate.filePath,
    relPath: candidate.relPath,
    folder: candidate.folder.path,
    contentType: ct.name,
    title,
    description,
    slug: asString(data.slug).trim() || fileSlug(candidate.relPath),
    date,
    modified,
    published: published === null ? null : published.getTime(),
    draft: draftValue(cfg, data),
    tags: asList(data.tags),
    categories: asList(data.categories),
    previewImage: previewImageOf(data, ct),
    data: { ...data },
  };
}

// ---------------------------------------------------------------------------
// buildIndex
// ---------------------------------------------------------------------------

/**
 * Scan every registered content folder into pages, reusing `prev` for files
 * whose mtime has not moved.
 *
 * The returned cache is built fresh rather than mutated: a file that was
 * deleted, renamed or excluded since the last run simply does not appear in it,
 * so the cache can never grow into a graveyard of pages that no longer exist.
 *
 * Nothing here throws for a bad file. An unreadable file, a folder that does
 * not exist and a file whose front matter will not parse are all just absent
 * from the result, with a line in the log — the panel and the dashboard render
 * during someone's mid-edit keystroke, and an exception is not an answer.
 */
export async function buildIndex(
  cfg: Zer0Config,
  prev?: IndexCache,
  log: LogSink = NOOP_LOG,
): Promise<{ pages: PageEntry[]; cache: IndexCache }> {
  const started = Date.now();
  const fingerprint = fingerprintOf(cfg);
  const usable = prev !== undefined && (prev.fingerprint ?? fingerprint) === fingerprint ? prev : undefined;
  if (prev !== undefined && usable === undefined) {
    log.verbose('page index: configuration changed, cache discarded');
  }

  const folders = await resolveFolders(cfg);
  const candidates = await collectCandidates(cfg, folders, log);

  const entries: IndexCache['entries'] = {};
  const skipped: Record<string, number> = {};
  const pages: PageEntry[] = [];
  let parsed = 0;
  let reused = 0;
  let ignored = 0;

  for (const candidate of candidates) {
    let modified: number;
    try {
      modified = (await fs.stat(candidate.filePath)).mtimeMs;
    } catch {
      // Vanished between the walk and the stat. It is not content any more.
      continue;
    }

    const cached = usable?.entries[candidate.filePath];
    if (cached !== undefined && cached.mtime === modified) {
      // Reused by identity on purpose: it is the cheapest correct answer, and
      // it is how a test proves nothing was re-parsed.
      entries[candidate.filePath] = cached;
      pages.push(cached.page);
      reused += 1;
      continue;
    }

    if (usable?.skipped?.[candidate.filePath] === modified) {
      skipped[candidate.filePath] = modified;
      ignored += 1;
      continue;
    }

    let text: string;
    try {
      text = await fs.readFile(candidate.filePath, 'utf8');
    } catch {
      log.verbose(`page index: cannot read ${candidate.relPath}`);
      continue;
    }

    parsed += 1;
    const { block } = splitFrontMatter(text);
    if (block === null) {
      // No front matter is not a failure; it means "this file is not a page".
      skipped[candidate.filePath] = modified;
      ignored += 1;
      continue;
    }

    const data = applyCommaSeparatedFields(block.data, cfg.frontMatter.commaSeparatedFields);
    const page = toPageEntry(cfg, candidate, data, modified);
    entries[candidate.filePath] = { mtime: modified, page };
    pages.push(page);
  }

  log.verbose(
    `page index: pages=${pages.length} parsed=${parsed} cached=${reused} skipped=${ignored} ` +
      `folders=${folders.length} ms=${Date.now() - started}`,
  );

  return { pages, cache: { version: CACHE_VERSION, entries, skipped, fingerprint } };
}

// ---------------------------------------------------------------------------
// The ContentRecord projection (decision D9)
// ---------------------------------------------------------------------------

const DAY_MS = 86_400_000;

/** Files whose job is structure, not prose. Excluded from distribution. */
const STRUCTURAL_STEMS: ReadonlySet<string> = new Set(['index', '_index', 'readme']);

function boolField(value: unknown): boolean {
  return value === true;
}

function stringField(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** The folder-relative first segment, BASH-CMS style: `_posts/corp/x.md` → `corp`. */
function collectionOf(cfg: Zer0Config, page: PageEntry): string {
  const folder = page.folder === '' ? '' : toRelPath(cfg, page.folder).replace(/\/+$/, '');
  const within =
    folder !== '' && page.relPath.startsWith(`${folder}/`)
      ? page.relPath.slice(folder.length + 1)
      : page.relPath;
  const slash = within.indexOf('/');
  return slash === -1 ? '' : within.slice(0, slash);
}

/**
 * The draft flag as a tri-state. A `choice` draft field carries a status word,
 * and only some words answer the question: `draft` and `true` mean yes,
 * `published` and `false` mean no, and anything else — `in-review`, `scheduled`
 * — is `null`, because guessing is how a governed queue publishes something it
 * should not have.
 */
function draftFlag(value: boolean | string): boolean | null {
  if (typeof value === 'boolean') {
    return value;
  }
  const word = value.trim().toLowerCase();
  if (word === 'draft' || word === 'true' || word === 'yes') {
    return true;
  }
  if (word === 'published' || word === 'false' || word === 'no' || word === 'live' || word === '') {
    return false;
  }
  return null;
}

/** The newest modification date the page admits to, in epoch milliseconds. */
function lastTouched(page: PageEntry, lastmod: string | null): number {
  for (const value of [lastmod, page.date]) {
    if (value !== null && value !== '') {
      const parsed = parseDate(value);
      if (parsed !== null) {
        return parsed.getTime();
      }
    }
  }
  return page.modified;
}

/**
 * A `PageEntry` in the contract's vocabulary — the fallback record for a
 * workspace with no `.cms/`.
 *
 * `health: -1` and `freshness: 'unknown'` are the whole point: a front-matter
 * scan cannot measure link rot, coverage or decay, so it says so instead of
 * inventing a number that would then be sorted, filtered and acted on. Under
 * those two values `isDistributable` falls back to "not a draft and has a
 * title", which is the strongest claim this data supports.
 *
 * `details` is optional and only affects `wordCount` / `headingCount`; without
 * it they are `0`, since the scan does not read bodies. Pass the result of
 * `getArticleDetails` when the caller already has one.
 */
export function pageToRecord(cfg: Zer0Config, page: PageEntry, details?: ArticleDetails): ContentRecord {
  const lastmod = conventionalLastmod(page);
  const age = Math.max(0, Math.floor((Date.now() - lastTouched(page, lastmod)) / DAY_MS));
  const stem = (page.relPath.split('/').pop() ?? '').replace(/\.[^./]+$/, '').toLowerCase();

  return {
    path: page.relPath,
    collection: collectionOf(cfg, page),
    title: page.title,
    descriptionLen: page.description.length,
    titleLen: page.title.length,
    wordCount: details?.wordCount ?? 0,
    headingCount: details?.headings ?? 0,
    health: -1,
    freshness: 'unknown',
    draft: draftFlag(page.draft),
    generated: boolField(page.data.generated),
    structural: STRUCTURAL_STEMS.has(stem),
    readOnly: boolField(page.data.readOnly) || boolField(page.data.read_only),
    isNotebook: page.relPath.toLowerCase().endsWith('.ipynb'),
    // Every PageEntry comes from a file whose front-matter block parsed; that
    // is the entry condition of the scan, not an assumption about the caller.
    frontmatterPresent: true,
    date: page.date,
    lastmod,
    ageDays: age,
    brokenLinks: 0,
    issues: [],
  };
}

/** The first of the conventional modified-date keys the page actually carries. */
function conventionalLastmod(page: PageEntry): string | null {
  for (const key of CONVENTIONAL_MODIFIED_KEYS) {
    const value = stringField(page.data[key]).trim();
    if (value !== '') {
      return value;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

/**
 * Weighted haystacks. The weights are ordinal, not tuned: a title hit should
 * outrank a path hit, and a path hit should still be a hit — that is the whole
 * requirement, and it is why this is 30 lines instead of a fuzzy-search
 * dependency with a `threshold` nobody can explain.
 */
const SEARCH_FIELDS: readonly { weight: number; of: (page: PageEntry) => string }[] = [
  { weight: 10, of: (p) => p.title },
  { weight: 6, of: (p) => p.slug },
  { weight: 5, of: (p) => p.relPath.split('/').pop() ?? '' },
  { weight: 3, of: (p) => p.description },
  { weight: 3, of: (p) => [...p.tags, ...p.categories].join(' ') },
  { weight: 2, of: (p) => p.contentType },
  { weight: 1, of: (p) => p.relPath },
];

/** Score one term against one page; `0` means "this page does not match". */
function scoreTerm(page: PageEntry, term: string): number {
  let score = 0;
  for (const field of SEARCH_FIELDS) {
    const value = field.of(page).toLowerCase();
    if (value === '' || !value.includes(term)) {
      continue;
    }
    score += field.weight;
    if (value === term) {
      score += field.weight * 2;
    } else if (value.startsWith(term) || value.split(/[\s/_-]+/).includes(term)) {
      score += field.weight;
    }
  }
  return score;
}

/**
 * Substring search over the index, scored and sorted — the host-side answer to
 * the dashboard's search box.
 *
 * Every term must hit something (AND, not OR): typing a second word narrows,
 * which is what a search box is for. An empty query returns everything, so a
 * cleared box is the identity operation rather than an empty page list.
 */
export function searchPages(pages: PageEntry[], query: string): PageEntry[] {
  const terms = query.toLowerCase().trim().split(/\s+/).filter((term) => term !== '');
  if (terms.length === 0) {
    return [...pages];
  }

  const scored: { page: PageEntry; score: number }[] = [];
  for (const page of pages) {
    let total = 0;
    let matchedAll = true;
    for (const term of terms) {
      const score = scoreTerm(page, term);
      if (score === 0) {
        matchedAll = false;
        break;
      }
      total += score;
    }
    if (matchedAll) {
      scored.push({ page, score: total });
    }
  }

  scored.sort((a, b) => {
    if (a.score !== b.score) {
      return b.score - a.score;
    }
    if (a.page.modified !== b.page.modified) {
      return b.page.modified - a.page.modified;
    }
    return a.page.relPath < b.page.relPath ? -1 : a.page.relPath > b.page.relPath ? 1 : 0;
  });

  return scored.map((entry) => entry.page);
}
