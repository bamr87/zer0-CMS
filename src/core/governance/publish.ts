/**
 * Publishing — the one composition of guard + gates + target + ledger, shared
 * by the command palette, the dashboard, and the MCP server. **There is no
 * second publish path**, which is what makes the gate auditable.
 *
 * Two halves, split along the only line that matters:
 *
 *   - `buildPreview` answers "what exactly would this produce?" It reads
 *     files and it computes; it performs **zero writes and zero network
 *     calls**. Every screen and every dry run goes through it, so what a
 *     reviewer approves is the literal artifact, not a description of one.
 *   - `publishPreview` takes that artifact and makes it real: gates, then the
 *     target, then the ledger record.
 *
 * Four ordered rules, inherited from BASH-CMS and preserved verbatim:
 *
 *   1. guard **errors** block unless `force` — and `force` never overrides the
 *      publish-allow flag, which is the master gate, not an inconvenience;
 *   2. a canonical URL already in the ledger returns `{ skipped }`, **not** an
 *      error, unless `force` — publishing twice is the failure, being asked to
 *      twice is not;
 *   3. a non-fatal target problem pushes a warning and continues, so a
 *      cosmetic failure never costs a publish;
 *   4. every publish that has a canonical URL is recorded, so the other lane
 *      skips it.
 *
 * Decision D8: `PublishTarget` is an interface. The built-in target is
 * `jekyll` — an approved draft becomes a file in a registered content folder
 * plus a ledger record. Nothing in this module knows about any social network.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { readArticle, type Article } from '../content/article';
import {
  asBool,
  asString,
  splitFrontMatter,
  type FmValue,
  type FrontMatter,
} from '../content/frontmatter';
import { serializeFrontMatter, serializeOptions, stitch } from '../content/serialize';
import { createSlug } from '../content/slug';
import { absPath, relPath, requireContentFolders, requireLedgerPath } from '../shared/config';
import { formatDate, parseDate } from '../shared/dates';
import { toPosix, walkGlobs } from '../shared/glob';
import { slugify, transliterate, truncate } from '../shared/text';
import type { ContentFolder, PageEntry, Zer0Config } from '../shared/types';
import { evaluatePublishGates } from './approval';
import {
  commentaryOf,
  descriptionOf,
  linkOf,
  noThumbnail,
  slugOf,
  sourceOf,
  titleOf,
  type DraftFile,
} from './drafts';
import { guardText, workspacePatterns, type GuardFinding } from './guard';
import { getEntry, record } from './ledger';

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

export interface PreviewRequest {
  /** `article` (default) | `text` | `update`. */
  type?: string;
  /** Article: a reference to the source content — a path, or a slug. */
  ref?: string;
  /** Text: the update body. */
  message?: string;
  /** Override the commentary derived from the source. */
  commentary?: string;
  noThumbnail?: boolean;
  /** The draft's own metadata, used when `ref` names no existing page. */
  title?: string;
  description?: string;
  link?: string;
  slug?: string;
  /** Destination content folder, by title or path. Defaults to the first. */
  folder?: string;
  /** Provenance recorded in the ledger; normalised to a workspace-relative path. */
  sourceFile?: string;
}

/**
 * What the file-writing targets intend to produce. Advisory: `send` resolves
 * the destination again against the disk, because between preview and publish
 * somebody may have created the same filename.
 */
export interface PublishPlan {
  title: string;
  description: string;
  slug: string;
  link: string;
  /** Raw front-matter value of the source's preview image, if any. */
  image: string;
  /** Absolute path of the destination content folder. */
  folder: string;
  /** Workspace-relative POSIX destination path. */
  destination: string;
}

export interface Preview {
  kind: 'article' | 'text';
  /** Exactly what the configured target would produce. Built by `target.build`. */
  artifact: unknown;
  guard: GuardFinding[];
  commentary: string;
  /** Canonical URL — the ledger key. Absent for text updates (no identity). */
  url?: string;
  /** The resolved source page, when the request named one that exists. */
  page?: PageEntry;
  /** Absolute path of a local preview image, when one resolves. */
  thumbnailPath?: string;
  plan?: PublishPlan;
  /** Workspace-relative path recorded as `source_file` in the ledger. */
  sourceFile?: string;
}

export interface PublishOutcome {
  /** Set when the artifact went out. */
  urn?: string;
  /** Set when the ledger already had this URL. Not an error. */
  skipped?: string;
  /** Set when a gate stopped the publish. */
  blocked?: string[];
  warnings: string[];
}

export interface PublishDeps {
  log?: (message: string) => void;
  /** Injected by remote targets and by tests that assert nothing calls out. */
  fetchImpl?: typeof fetch;
}

export interface PublishTarget {
  id: string;
  /** Pure: render the artifact. Must not write and must not call out. */
  build(cfg: Zer0Config, preview: Preview): Promise<unknown>;
  /** Make it real. May report non-fatal problems as warnings. */
  send(
    cfg: Zer0Config,
    preview: Preview,
    deps: PublishDeps,
  ): Promise<{ urn: string; warnings?: string[] }>;
}

// ---------------------------------------------------------------------------
// Canonical URLs — the ledger key
// ---------------------------------------------------------------------------

const PERMALINK_KEYS = ['permalink', 'canonical_url', 'canonicalUrl', 'url'];

/**
 * The stable identity of a page, used as the ledger key.
 *
 * There is no site base URL in `zer0.json` — inventing one would make the key
 * change the day somebody moves a domain, which is exactly what a ledger must
 * never do. So the key is the site-*relative* permalink: a `permalink` (or
 * `canonical_url`) in the front matter wins verbatim; otherwise it is derived
 * from the file's path with the extension, a `YYYY-MM-DD-` filename prefix and
 * the leading underscore of Jekyll collection folders removed.
 *
 * `pages/_posts/2026-07-31-hello.md` → `/pages/posts/hello/`.
 */
export function canonicalUrl(cfg: Zer0Config, filePath: string, data: FrontMatter = {}): string {
  for (const key of PERMALINK_KEYS) {
    const value = asString(data[key]).trim();
    if (value !== '') {
      return value;
    }
  }
  const rel = toPosix(path.isAbsolute(filePath) ? relPath(cfg, filePath) : filePath);
  const segments = rel.split('/').filter((s) => s !== '' && s !== '.');
  const file = segments.pop() ?? '';
  const stem = file.replace(/\.[^./]+$/, '').replace(/^\d{4}-\d{2}-\d{2}-/, '');
  const dirs = segments.map((s) => (s.startsWith('_') ? s.slice(1) : s));
  return `/${[...dirs, stem].filter((s) => s !== '').join('/')}/`;
}

// ---------------------------------------------------------------------------
// Resolving the source page
// ---------------------------------------------------------------------------

interface SourcePage {
  filePath: string;
  /** Workspace-relative POSIX. */
  relPath: string;
  folder: ContentFolder | undefined;
  article: Article;
  modified: number;
}

function isUrl(value: string): boolean {
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(value);
}

/** Filename stem with a date prefix and extension removed. */
function fileSlug(relPosix: string): string {
  const base = relPosix.split('/').pop() ?? '';
  return base.replace(/\.[^./]+$/, '').replace(/^\d{4}-\d{2}-\d{2}-/, '');
}

function folderOf(cfg: Zer0Config, filePath: string): ContentFolder | undefined {
  let best: ContentFolder | undefined;
  for (const folder of cfg.contentFolders) {
    const prefix = folder.path.endsWith(path.sep) ? folder.path : folder.path + path.sep;
    if (filePath.startsWith(prefix) && (best === undefined || folder.path.length > best.path.length)) {
      best = folder;
    }
  }
  return best;
}

async function readSource(cfg: Zer0Config, filePath: string): Promise<SourcePage | undefined> {
  let modified = 0;
  try {
    const stat = await fs.stat(filePath);
    if (!stat.isFile()) {
      return undefined;
    }
    modified = stat.mtimeMs;
  } catch {
    // Not a file we can see. The caller falls back to a workspace search, and
    // then to the draft's own metadata — a missing source is not fatal.
    return undefined;
  }
  return {
    filePath,
    relPath: toPosix(relPath(cfg, filePath)),
    folder: folderOf(cfg, filePath),
    article: await readArticle(filePath),
    modified,
  };
}

/**
 * Find the content file a draft's `source` refers to. Read-only, and cheapest
 * first: an exact path, then the same path with each supported extension, then
 * a search of the registered content folders by relative path or by slug.
 *
 * Returns `undefined` rather than throwing. A draft may be original content
 * with no source at all, and a `source` that is an external URL is a link, not
 * a file. When the reference matters — because nothing else supplies a title —
 * the missing metadata is what reports it, naming the ref.
 */
export async function resolveSource(cfg: Zer0Config, ref: string): Promise<SourcePage | undefined> {
  const wanted = ref.trim();
  if (wanted === '' || isUrl(wanted)) {
    return undefined;
  }

  const direct = await readSource(cfg, absPath(cfg, wanted));
  if (direct) {
    return direct;
  }
  if (!/\.[^./]+$/.test(wanted)) {
    for (const ext of cfg.content.supportedFileTypes) {
      const withExt = await readSource(cfg, absPath(cfg, `${wanted}.${ext}`));
      if (withExt) {
        return withExt;
      }
    }
  }

  if (cfg.contentFolders.length === 0) {
    return undefined;
  }
  const globs: string[] = [];
  for (const folder of cfg.contentFolders) {
    const base = toPosix(relPath(cfg, folder.path));
    for (const ext of cfg.content.supportedFileTypes) {
      globs.push(`${base}/**/*.${ext}`);
    }
  }
  const wantedPosix = toPosix(wanted).replace(/^\.?\//, '');
  const wantedSlug = slugify(fileSlug(wantedPosix), cfg.slug.stopWords);
  for (const candidate of await walkGlobs(cfg.workspaceRoot, globs)) {
    const matches =
      candidate === wantedPosix ||
      candidate.endsWith(`/${wantedPosix}`) ||
      (wantedSlug !== '' && slugify(fileSlug(candidate), cfg.slug.stopWords) === wantedSlug);
    if (matches) {
      return readSource(cfg, absPath(cfg, candidate));
    }
  }
  return undefined;
}

/**
 * Front-matter keys that may carry a page's social image, in priority order.
 *
 * Exported so `core/media` resolves an image the same way publishing does. A
 * second copy would mean a page that looks covered in the media report and
 * publishes without a thumbnail.
 */
export const THUMBNAIL_KEYS = ['image', 'preview', 'thumbnail', 'cover', 'featured_image', 'banner'];

export function previewImageValue(data: FrontMatter): string {
  for (const key of THUMBNAIL_KEYS) {
    const value = data[key];
    if (typeof value === 'string' && value.trim() !== '') {
      return value.trim();
    }
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      const src = asString((value as FrontMatter).src ?? (value as FrontMatter).path).trim();
      if (src !== '') {
        return src;
      }
    }
  }
  return '';
}

/** Absolute path of a preview image that actually exists on disk, or nothing. */
async function resolveThumbnail(cfg: Zer0Config, value: string): Promise<string | undefined> {
  if (value === '' || isUrl(value)) {
    return undefined;
  }
  const candidates = [absPath(cfg, value.replace(/^\//, ''))];
  if (cfg.content.publicFolder !== '') {
    candidates.push(path.join(absPath(cfg, cfg.content.publicFolder), value.replace(/^\//, '')));
  }
  for (const candidate of candidates) {
    try {
      const stat = await fs.stat(candidate);
      if (stat.isFile()) {
        return candidate;
      }
    } catch {
      // Not there. A preview image that does not resolve locally is a warning
      // the UI can draw from the front matter itself, not a publish failure.
      continue;
    }
  }
  return undefined;
}

function toPageEntry(cfg: Zer0Config, source: SourcePage): PageEntry {
  const data = source.article.data;
  const rawDraft = data[cfg.draftField.name];
  const dateValue = asString(data.date).trim();
  const published = parseDate(dateValue === '' ? undefined : dateValue);
  return {
    filePath: source.filePath,
    relPath: source.relPath,
    folder: source.folder?.path ?? '',
    contentType: asString(data.type),
    title: asString(data[cfg.seo.titleField]).trim(),
    description: asString(data[cfg.seo.descriptionField]).trim(),
    slug: fileSlug(source.relPath),
    date: dateValue === '' ? null : dateValue,
    modified: source.modified,
    published: published === null ? null : published.getTime(),
    draft:
      typeof rawDraft === 'string'
        ? rawDraft
        : cfg.draftField.invert
          ? !asBool(rawDraft)
          : asBool(rawDraft),
    tags: toStringList(data.tags),
    categories: toStringList(data.categories),
    previewImage: previewImageValue(data),
    data: { ...data },
  };
}

function toStringList(value: FmValue | undefined): string[] {
  if (Array.isArray(value)) {
    return value.filter((v): v is string => typeof v === 'string');
  }
  return typeof value === 'string' && value.trim() !== '' ? [value.trim()] : [];
}

// ---------------------------------------------------------------------------
// Planning the destination
// ---------------------------------------------------------------------------

/** The content folder a publish writes into: the named one, else the first
 *  that allows creation. */
export function destinationFolder(cfg: Zer0Config, hint?: string): ContentFolder {
  const folders = requireContentFolders(cfg);
  const wanted = (hint ?? '').trim().toLowerCase();
  if (wanted !== '') {
    const match = folders.find(
      (f) =>
        f.title.toLowerCase() === wanted ||
        toPosix(f.originalPath ?? '').toLowerCase() === toPosix(wanted) ||
        toPosix(relPath(cfg, f.path)).toLowerCase() === toPosix(wanted),
    );
    if (match) {
      return match;
    }
    throw new Error(`no content folder named '${hint}' is registered`);
  }
  const creatable = folders.find((f) => f.disableCreation !== true);
  if (creatable === undefined) {
    throw new Error('every registered content folder has "disableCreation": true');
  }
  return creatable;
}

/**
 * The filename prefix for a new file in `folder`.
 *
 * `filePrefix` is a date pattern, optionally wrapped as `{{date|yyyy-MM-dd}}`.
 * When nothing is configured, a Jekyll `_posts` folder still gets a date —
 * Jekyll refuses to build a post without one, and silently writing a file the
 * site will not publish is the worst of the available failures.
 */
function filePrefixFor(cfg: Zer0Config, folder: ContentFolder, now: Date): string {
  const raw = (folder.filePrefix ?? cfg.content.filePrefix ?? '').trim();
  const wrapped = /^\{\{\s*date\s*\|\s*([^}]+?)\s*\}\}$/.exec(raw);
  const pattern = wrapped?.[1] ?? raw;
  if (pattern === '') {
    return path.basename(folder.path) === '_posts'
      ? formatDate(now, 'yyyy-MM-dd', cfg.date.timezone)
      : '';
  }
  return formatDate(now, pattern, cfg.date.timezone);
}

function planDestination(
  cfg: Zer0Config,
  folder: ContentFolder,
  slug: string,
  now: Date,
): string {
  const prefix = filePrefixFor(cfg, folder, now);
  const name = `${prefix === '' ? '' : `${prefix}-`}${slug}.${cfg.content.defaultFileType}`;
  return toPosix(path.join(relPath(cfg, folder.path), name));
}

// ---------------------------------------------------------------------------
// buildPreview
// ---------------------------------------------------------------------------

function defaultCommentary(title: string, description: string): string {
  return [title, description].filter((s) => s !== '').join('\n\n');
}

/** First non-empty line of a text update, as its title. */
function titleFromMessage(message: string): string {
  const line = message.split('\n').find((l) => l.trim() !== '') ?? 'Update';
  return truncate(line.trim().replace(/^#+\s*/, ''), 80);
}

/**
 * Render exactly what would publish. No writes, no network.
 *
 * The artifact is produced by the *configured* target's `build`, so a preview
 * screen and the MCP `zer0_preview` tool show the literal bytes a publish
 * would write — not a summary that can drift from them.
 */
export async function buildPreview(cfg: Zer0Config, req: PreviewRequest): Promise<Preview> {
  const kind = (req.type ?? 'article').trim().toLowerCase();
  const patterns = await workspacePatterns(cfg);
  const now = new Date();
  const target = targetFor(cfg);
  const sourceFile = req.sourceFile ? toPosix(relPath(cfg, req.sourceFile)) : undefined;

  if (kind === 'text' || kind === 'update') {
    const message = (req.message ?? req.commentary ?? '').trim();
    if (message === '') {
      throw new Error("a text update needs 'message'");
    }
    const title = (req.title ?? '').trim() || titleFromMessage(message);
    const slug = slugFor(cfg, req.slug, title, now);
    const folder = destinationFolder(cfg, req.folder);
    const preview: Preview = {
      kind: 'text',
      artifact: undefined,
      guard: guardText(message, { extraPatterns: patterns }),
      commentary: message,
      // No canonical URL on purpose: a free-text update has no stable identity
      // to dedupe against, so it is never ledgered. Deliberate, inherited.
      plan: {
        title,
        description: (req.description ?? '').trim(),
        slug,
        link: (req.link ?? '').trim(),
        image: '',
        folder: folder.path,
        destination: planDestination(cfg, folder, slug, now),
      },
      ...(sourceFile ? { sourceFile } : {}),
    };
    preview.artifact = await target.build(cfg, preview);
    return preview;
  }

  if (kind !== 'article') {
    throw new Error(`unknown type '${kind}' (use 'article' or 'text')`);
  }

  const ref = (req.ref ?? '').trim();
  const source = ref === '' ? undefined : await resolveSource(cfg, ref);
  const data = source?.article.data ?? {};

  const title = (req.title ?? '').trim() || asString(data[cfg.seo.titleField]).trim();
  const description =
    (req.description ?? '').trim() || asString(data[cfg.seo.descriptionField]).trim();
  if (title === '' || description === '') {
    const where = source?.relPath ?? (ref === '' ? 'draft' : ref);
    throw new Error(`article is missing title/description (${where})`);
  }

  const link = (req.link ?? '').trim() || (isUrl(ref) ? ref : '');
  const image = req.noThumbnail ? '' : previewImageValue(data);
  const thumbnailPath = image === '' ? undefined : await resolveThumbnail(cfg, image);
  // Not the source page's body: a full article routinely exceeds MAX_LEN, and
  // "your 5,000-character post is over the commentary limit" is a nonsense
  // gate. An empty draft body means "publish the summary".
  const commentary = (req.commentary ?? '').trim() || defaultCommentary(title, description);

  const slug = slugFor(cfg, req.slug, title, now, source?.relPath);
  const folder = destinationFolder(cfg, req.folder);
  const destination = planDestination(cfg, folder, slug, now);

  const preview: Preview = {
    kind: 'article',
    artifact: undefined,
    guard: guardText(commentary, { extraPatterns: patterns }),
    commentary,
    // Keyed on the source when there is one, so the same source is never
    // published twice by either lane; otherwise on the intended destination,
    // which is the draft's own identity.
    url: source ? canonicalUrl(cfg, source.relPath, data) : canonicalUrl(cfg, destination),
    ...(source ? { page: toPageEntry(cfg, source) } : {}),
    ...(thumbnailPath ? { thumbnailPath } : {}),
    plan: { title, description, slug, link, image, folder: folder.path, destination },
    ...(sourceFile ?? source?.relPath ? { sourceFile: sourceFile ?? source?.relPath ?? '' } : {}),
  };
  preview.artifact = await target.build(cfg, preview);
  return preview;
}

/**
 * Make a string safe to use as a filename stem — and nothing else.
 *
 * `slugify` drops stop words, which is right for turning a *title* into a slug
 * and wrong for a slug somebody already chose — under the `smart` preset a
 * hand-written `the-value-of-x` would come back as `x`. An explicit slug is a
 * decision, so it is only transliterated and punctuation-collapsed here.
 */
function sanitizeSlug(cfg: Zer0Config, value: string): string {
  const cleaned = transliterate(value.trim())
    .replace(/[^\p{Letter}\p{Number}]+/gu, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
  return cfg.content.preserveCasing ? cleaned : cleaned.toLowerCase();
}

function slugFor(
  cfg: Zer0Config,
  requested: string | undefined,
  title: string,
  now: Date,
  sourceRel?: string,
): string {
  const explicit = sanitizeSlug(cfg, requested ?? '');
  if (explicit !== '') {
    return explicit;
  }
  const generated = createSlug(cfg, title, undefined, sourceRel).trim();
  return (
    generated ||
    slugify(title, cfg.slug.stopWords) ||
    sanitizeSlug(cfg, title) ||
    `post-${formatDate(now, 'yyyy-MM-dd', cfg.date.timezone)}`
  );
}

/** Map a queue draft onto a preview request. */
export function previewRequestFromDraft(draft: DraftFile): PreviewRequest {
  const shared = {
    commentary: commentaryOf(draft),
    title: titleOf(draft),
    description: descriptionOf(draft),
    link: linkOf(draft),
    slug: slugOf(draft),
    sourceFile: draft.path,
    noThumbnail: noThumbnail(draft),
    ...(typeof draft.meta.folder === 'string' ? { folder: draft.meta.folder } : {}),
  };
  if (draft.type === 'update') {
    return { ...shared, type: 'text', message: commentaryOf(draft) };
  }
  return { ...shared, type: 'article', ref: sourceOf(draft) };
}

// ---------------------------------------------------------------------------
// The built-in jekyll target
// ---------------------------------------------------------------------------

export interface JekyllArtifact {
  target: 'jekyll';
  /** Workspace-relative POSIX path the file would be written to. */
  path: string;
  frontMatter: FrontMatter;
  body: string;
  /** The exact bytes. */
  contents: string;
}

function isJekyllArtifact(value: unknown): value is JekyllArtifact {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { target?: unknown }).target === 'jekyll' &&
    typeof (value as { contents?: unknown }).contents === 'string'
  );
}

function requirePlan(preview: Preview): PublishPlan {
  if (preview.plan === undefined) {
    throw new Error('preview has no publish plan (build it with buildPreview)');
  }
  return preview.plan;
}

function errnoCode(error: unknown): string | undefined {
  if (typeof error === 'object' && error !== null && 'code' in error) {
    const code = (error as { code?: unknown }).code;
    return typeof code === 'string' ? code : undefined;
  }
  return undefined;
}

/**
 * Everything in an artifact except the moment it was built.
 *
 * `build` stamps `date` from `new Date()`, so the same publish retried a minute
 * later produces different bytes for identical content. Every other key, and
 * the body, are functions of the draft alone — which is what makes this a
 * usable answer to "did I already write this exact page?".
 */
/** Whether the file already at `rel` is the artifact we were about to write. */
async function sameArtifactOnDisk(
  cfg: Zer0Config,
  rel: string,
  identity: string,
): Promise<boolean> {
  try {
    return artifactIdentity(await fs.readFile(absPath(cfg, rel), 'utf8')) === identity;
  } catch {
    // The name is taken by something we cannot read — a directory, or a file
    // whose permissions say no. "Not ours" is the safe answer: the caller bumps
    // to the next name instead of assuming a match it could not verify.
    return false;
  }
}

function artifactIdentity(text: string): string {
  const { block, body } = splitFrontMatter(text);
  const keys = Object.entries(block?.data ?? {})
    .filter(([key]) => key !== 'date')
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return JSON.stringify([keys, body.trim()]);
}

/**
 * The built-in target: an approved draft becomes a content file plus a ledger
 * record. `build` renders the bytes; `send` writes them **exclusively** —
 * `wx` fails rather than overwriting, and the destination bumps to `-2`, `-3`
 * on collision. Publishing must never silently replace somebody's page.
 *
 * **The `-2` bump is for a different page that wants the same name, and only
 * that.** Writing the file and recording the ledger entry are two steps, and a
 * crash — or a read-only `.zer0/` — between them leaves an artifact on disk
 * that no ledger key mentions. The next attempt passes every gate, reaches
 * `wx`, gets `EEXIST` and used to bump: two live pages for one canonical URL,
 * with the ledger naming the `-2` file under the URL the `-1` file is served
 * at. So an existing file whose content is this artifact's is *adopted* — the
 * publish is completed by recording it, not duplicated.
 */
export const jekyllTarget: PublishTarget = {
  id: 'jekyll',

  async build(cfg: Zer0Config, preview: Preview): Promise<JekyllArtifact> {
    const plan = requirePlan(preview);
    const opts = serializeOptions(cfg);
    const now = new Date();

    const data: FrontMatter = {};
    data[cfg.seo.titleField] = plan.title;
    if (plan.description !== '') {
      data[cfg.seo.descriptionField] = plan.description;
    }
    data.date = formatDate(now, cfg.date.format, cfg.date.timezone);
    if (cfg.draftField.type === 'boolean') {
      // Publishing means "not a draft" — inverted when the field marks published.
      data[cfg.draftField.name] = cfg.draftField.invert === true;
    }
    if (plan.link !== '') {
      data.link = plan.link;
    }
    if (plan.image !== '') {
      data.image = plan.image;
    }

    const body = `\n${preview.commentary.trim()}\n`;
    return {
      target: 'jekyll',
      path: plan.destination,
      frontMatter: data,
      body,
      contents: stitch(null, serializeFrontMatter(data, opts), body, opts.format),
    };
  },

  async send(
    cfg: Zer0Config,
    preview: Preview,
    deps: PublishDeps,
  ): Promise<{ urn: string; warnings?: string[] }> {
    const artifact = isJekyllArtifact(preview.artifact)
      ? preview.artifact
      : ((await jekyllTarget.build(cfg, preview)) as JekyllArtifact);

    const intended = artifact.path;
    const dir = path.dirname(absPath(cfg, intended));
    await fs.mkdir(dir, { recursive: true });

    const ext = path.extname(intended);
    const stem = intended.slice(0, intended.length - ext.length);
    const warnings: string[] = [];
    const identity = artifactIdentity(artifact.contents);

    for (let n = 1; ; n += 1) {
      const rel = n === 1 ? intended : `${stem}-${n}${ext}`;
      try {
        // `wx`: create or fail. Never overwrite an existing page.
        await fs.writeFile(absPath(cfg, rel), artifact.contents, { encoding: 'utf8', flag: 'wx' });
        if (rel !== intended) {
          warnings.push(`warning: ${intended} already existed; wrote ${rel} instead`);
        }
        deps.log?.(`published ${rel}`);
        return { urn: `jekyll:${rel}`, warnings };
      } catch (error) {
        if (errnoCode(error) !== 'EEXIST') {
          throw error;
        }
        if (await sameArtifactOnDisk(cfg, rel, identity)) {
          // An earlier attempt wrote this exact page and did not get as far as
          // the ledger. Adopt it and let the caller record it, rather than
          // shipping a second copy of the same canonical URL.
          warnings.push(
            `warning: ${rel} was already on disk with this exact content but had no ledger ` +
              'record — an interrupted publish. Recording it instead of writing a second copy.',
          );
          deps.log?.(`adopted the existing ${rel}`);
          return { urn: `jekyll:${rel}`, warnings };
        }
        if (n > 50) {
          throw new Error(`cannot find a free filename for ${intended}`);
        }
      }
    }
  },
};

const TARGETS = new Map<string, PublishTarget>([[jekyllTarget.id, jekyllTarget]]);

/** Register an additional target. The interface is the extension point (D8). */
export function registerTarget(target: PublishTarget): void {
  TARGETS.set(target.id, target);
}

export function listTargets(): string[] {
  return [...TARGETS.keys()].sort();
}

export function targetById(id: string): PublishTarget {
  const target = TARGETS.get(id.trim().toLowerCase());
  if (target === undefined) {
    throw new Error(`unknown publish target '${id}' (known: ${listTargets().join(', ')})`);
  }
  return target;
}

/** The target this workspace is configured to use. */
export function targetFor(cfg: Zer0Config): PublishTarget {
  return targetById(cfg.governance.target || jekyllTarget.id);
}

// ---------------------------------------------------------------------------
// publishPreview
// ---------------------------------------------------------------------------

/**
 * Publish a built preview: gates, then the target, then the ledger.
 *
 * `force` overrides the guard and the ledger — a human who has read the
 * findings and decided is allowed to say so. It does **not** override
 * `publishDisabled`: a workspace that has not turned publishing on has not
 * turned it on, and a flag on a call site is not consent (D5).
 *
 * The draft's status gate runs here too when the caller passes the draft. The
 * queue file itself is not touched: flipping `status: approved` →
 * `status: published` belongs to the caller that owns the queue, so a target
 * failure never leaves a draft claiming it published.
 */
export async function publishPreview(
  cfg: Zer0Config,
  preview: Preview,
  target: PublishTarget,
  opts: { force?: boolean; draft?: DraftFile } = {},
  deps: PublishDeps = {},
): Promise<PublishOutcome> {
  const warnings: string[] = [];
  const ledgerPath = requireLedgerPath(cfg);

  const entry = preview.url === undefined ? undefined : await getEntry(ledgerPath, preview.url);
  if (!opts.force && typeof entry?.urn === 'string' && entry.urn !== '') {
    const when = typeof entry.posted_at === 'string' && entry.posted_at !== '' ? ` on ${entry.posted_at}` : '';
    return { skipped: `skip: already published as ${entry.urn}${when}`, warnings };
  }

  const blockers = evaluatePublishGates({
    cfg,
    guard: preview.guard,
    ...(opts.draft ? { draft: opts.draft } : {}),
  }).filter((b) => (opts.force ? b.kind === 'publishDisabled' : true));
  if (blockers.length > 0) {
    return { blocked: blockers.map((b) => b.message), warnings };
  }

  const sent = await target.send(cfg, preview, deps);
  warnings.push(...(sent.warnings ?? []));

  if (preview.url !== undefined && preview.url !== '') {
    await record(ledgerPath, preview.url, sent.urn, {
      kind: preview.kind === 'article' ? 'article' : 'update',
      target: target.id,
      ...(preview.sourceFile ? { sourceFile: preview.sourceFile } : {}),
    });
  }
  return { urn: sent.urn, warnings };
}
