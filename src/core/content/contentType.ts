/**
 * Content types: which schema governs a file, what a new file of that type
 * starts life containing, and where on disk it goes.
 *
 * **This module computes; it does not write.** `createContent` resolves the
 * type, the prefix, the filename and the starting front matter, and refuses a
 * path that already exists — then hands the caller a `CreateContentResult`.
 * `renderContentFile` turns that into the exact bytes. The `fs.writeFile` is
 * the shell's, because `article.ts` is the only module in this codebase that
 * writes user markdown and creation is the one case it does not cover. Keeping
 * the decision and the write apart is also what lets the MCP server and the
 * tests exercise creation without producing files.
 *
 * The resolution chain has five steps, in this order:
 *
 *   1. the file's own `type` key, when it names a registered type;
 *   2. the content folder that owns the file, when it binds exactly one type;
 *   3. the sole registered type, when the workspace declares exactly one;
 *   4. the type named `default`;
 *   5. `DEFAULT_CONTENT_TYPE`, synthesized here.
 *
 * Step 1 is `type`, not FM's `fmContentType`: the branded key is gone with the
 * fork, and `type` is the key Jekyll, Hugo and Astro sites already carry.
 *
 * `DEFAULT_CONTENT_TYPE` resolves an inconsistency in the upstream fork, where
 * `constants/ContentType.ts` gave the draft field `type: 'draft'` and
 * `package.json` gave the same field `type: 'boolean'`. `draft` is correct: it
 * is the type that reads `draftField` and therefore honours a workspace whose
 * draft flag is a status string rather than a boolean.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { absPath } from '../shared/config';
import { encodeEmoji, humanize } from '../shared/text';
import {
  NOOP_LOG,
  type ContentType,
  type Field,
  type LogSink,
  type Zer0Config,
} from '../shared/types';
import { readArticle } from './article';
import { emptyValueFor, evaluateWhen, inlineFieldCollections, isEmpty } from './fields';
import { filePrefixFor, folderForFile } from './folders';
import type { FmValue, FrontMatter } from './frontmatter';
import { processPlaceholders } from './placeholders';
import { serializeFrontMatter, serializeOptions, stitch } from './serialize';

/** The name of the type used when nothing else matches. */
export const DEFAULT_CONTENT_TYPE_NAME = 'default';

/** The front-matter key that binds a file to its content type. */
export const CONTENT_TYPE_FIELD = 'type';

/** The fallback schema. Every workspace has this, configured or not. */
export const DEFAULT_CONTENT_TYPE: ContentType = {
  name: DEFAULT_CONTENT_TYPE_NAME,
  pageBundle: false,
  fields: [
    { title: 'Title', name: 'title', type: 'string', single: true },
    { title: 'Description', name: 'description', type: 'string' },
    {
      title: 'Publishing date',
      name: 'date',
      type: 'datetime',
      default: '{{now}}',
      isPublishDate: true,
    },
    { title: 'Content preview', name: 'preview', type: 'image', isPreviewImage: true },
    { title: 'Is in draft', name: 'draft', type: 'draft' },
    { title: 'Tags', name: 'tags', type: 'tags' },
    { title: 'Categories', name: 'categories', type: 'categories' },
  ],
};

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

/**
 * Every configured content type with its `fieldCollection`s already expanded —
 * the only form the rest of the codebase should ever see. A workspace with no
 * content types configured gets the default one, so "no config yet" is a
 * working CMS rather than an error.
 */
export function getContentTypes(cfg: Zer0Config): ContentType[] {
  const configured = cfg.contentTypes.length > 0 ? cfg.contentTypes : [DEFAULT_CONTENT_TYPE];
  return configured.map((ct) => ({
    ...ct,
    fields: inlineFieldCollections(ct.fields ?? [], cfg.fieldGroups),
  }));
}

/** The type named `name`, with collections expanded, or `undefined`. */
export function contentTypeByName(cfg: Zer0Config, name: string): ContentType | undefined {
  return getContentTypes(cfg).find((ct) => ct.name === name);
}

/** The content type governing this file — the five-step chain in the header. */
export function resolveContentType(
  cfg: Zer0Config,
  data: FrontMatter,
  filePath: string,
): ContentType {
  const types = getContentTypes(cfg);

  // 1. The file says so itself.
  const declared = data[CONTENT_TYPE_FIELD];
  if (typeof declared === 'string') {
    const named = types.find((ct) => ct.name === declared);
    if (named !== undefined) {
      return named;
    }
  }

  // 2. The folder binds exactly one type. More than one is ambiguous, and
  //    guessing between them would silently apply the wrong schema.
  const folder = folderForFile(cfg.contentFolders, filePath);
  const bound = folder?.contentTypes ?? [];
  if (bound.length === 1) {
    const name = bound[0];
    const byFolder = types.find((ct) => ct.name === name);
    if (byFolder !== undefined) {
      return byFolder;
    }
  }

  // 3. There is only one type in the whole workspace.
  const only = types[0];
  if (types.length === 1 && only !== undefined) {
    return only;
  }

  // 4. The type explicitly named `default`.
  const fallback = types.find((ct) => ct.name === DEFAULT_CONTENT_TYPE_NAME);
  if (fallback !== undefined) {
    return fallback;
  }

  // 5. The built-in schema.
  return DEFAULT_CONTENT_TYPE;
}

// ---------------------------------------------------------------------------
// Field defaults
// ---------------------------------------------------------------------------

async function expand(
  value: string,
  cfg: Zer0Config,
  ct: ContentType,
  title: string,
  filePath: string | undefined,
  data: FrontMatter,
  log: LogSink,
): Promise<string> {
  return processPlaceholders(value, {
    cfg,
    contentType: ct,
    title,
    data,
    log,
    ...(filePath === undefined ? {} : { filePath }),
  });
}

async function fill(
  fields: readonly Field[],
  cfg: Zer0Config,
  ct: ContentType,
  seed: FrontMatter,
  title: string,
  filePath: string | undefined,
  isRoot: boolean,
  log: LogSink,
): Promise<FrontMatter> {
  const clearEmpty = ct.clearEmpty === true;
  const titleField = cfg.seo.titleField;
  const out: FrontMatter = {};

  for (const field of fields) {
    if (field.type === 'divider' || field.type === 'heading') {
      // Presentation only — they name no front-matter key.
      continue;
    }

    // What is known so far: the template's values, overlaid with the fields
    // already filled. `when` clauses and `{{fm.…}}` defaults both read this, so
    // a field may condition on, or interpolate, a field declared above it.
    const known: FrontMatter = { ...seed, ...out };

    if (!evaluateWhen(field, known, fields)) {
      // A field the author would not be shown is a field the file should not
      // carry: writing it would create a value nobody can edit.
      continue;
    }

    const existing = seed[field.name];

    if (field.type === 'fields') {
      const nestedSeed =
        existing !== null &&
        existing !== undefined &&
        typeof existing === 'object' &&
        !Array.isArray(existing)
          ? existing
          : {};
      const group = field.fields ?? [];
      const nested = await fill(group, cfg, ct, nestedSeed, title, filePath, false, log);
      if (!(clearEmpty && Object.keys(nested).length === 0)) {
        out[field.name] = nested;
      }
      continue;
    }

    // A template that supplied a value wins over the field's default: seeding
    // is the entire point of `contentType.template`. (FM overwrote it, which
    // made a template's values unreachable for any field with a default.)
    if (existing !== undefined && !isEmpty(field, existing)) {
      out[field.name] =
        typeof existing === 'string'
          ? await expand(existing, cfg, ct, title, filePath, known, log)
          : existing;
      continue;
    }

    if (field.name === titleField) {
      if (typeof field.default === 'string') {
        out[field.name] = await expand(field.default, cfg, ct, title, filePath, known, log);
      } else if (isRoot) {
        out[field.name] = title;
      } else if (!clearEmpty) {
        out[field.name] = '';
      }
      continue;
    }

    const fallback = field.default;
    if (typeof fallback === 'string') {
      out[field.name] = await expand(fallback, cfg, ct, title, filePath, known, log);
      continue;
    }
    if (Array.isArray(fallback)) {
      const values: FmValue[] = [];
      for (const item of fallback) {
        values.push(await expand(item, cfg, ct, title, filePath, known, log));
      }
      out[field.name] = values;
      continue;
    }
    if (fallback !== undefined) {
      out[field.name] = fallback;
      continue;
    }

    const empty = emptyValueFor(field, cfg);
    if (clearEmpty && isEmpty(field, empty)) {
      continue;
    }
    out[field.name] = empty;
  }

  // Keys the template carried that no field declares survive, appended in the
  // template's own order — dropping them would make a template a lossy source.
  for (const [key, value] of Object.entries(seed)) {
    if (!(key in out)) {
      out[key] = value;
    }
  }

  return out;
}

/**
 * The front matter a new file of this type starts with: every visible field
 * filled from the template seed, its `default` (placeholder-expanded), or its
 * typed empty value — in declaration order.
 *
 * `clearEmpty` on the content type omits the empties instead of writing them.
 */
export function processFields(
  ct: ContentType,
  cfg: Zer0Config,
  seed: FrontMatter,
  title: string,
  filePath?: string,
  log: LogSink = NOOP_LOG,
): Promise<FrontMatter> {
  return fill(ct.fields ?? [], cfg, ct, seed, title, filePath, true, log);
}

// ---------------------------------------------------------------------------
// Creation
// ---------------------------------------------------------------------------

// Written as a source string so this file stays plain ASCII: the class has
// to cover the C0 control characters, which no filesystem accepts.
const INVALID_FILENAME_CHARS = new RegExp('[<>:"/\\\\|?*\\u0000-\\u001f]', 'g');
const RESERVED_WINDOWS_NAME = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$/i;

/**
 * A title turned into a filename: spaces to dashes, lowercased unless
 * `content.preserveCasing`, characters no filesystem accepts removed, and the
 * Windows device names sidestepped. Replaces FM's `sanitize-filename` dep.
 */
export function sanitizeFileName(value: string, preserveCasing = false): string {
  const cased = preserveCasing ? value : value.toLowerCase();
  let out = cased
    .replace(/\s+/g, '-')
    .replace(INVALID_FILENAME_CHARS, '')
    .replace(/^\.+/, '')
    .replace(/[.\s]+$/, '')
    .slice(0, 180);
  if (RESERVED_WINDOWS_NAME.test(out)) {
    out = `${out}-file`;
  }
  return out;
}

export interface CreateContentRequest {
  contentType: string;
  title: string;
  /** The registered folder to create in; `[[workspace]]` aware. */
  folderPath: string;
  /** An optional path *below* `folderPath`, as chosen in the picker. */
  subFolder?: string;
  /** Overrides the content type's `fileType`. */
  fileExtension?: string;
}

export interface CreateContentResult {
  filePath: string;
  data: FrontMatter;
  body: string;
  contentType: ContentType;
}

async function exists(target: string): Promise<boolean> {
  try {
    await fs.stat(target);
    return true;
  } catch {
    // `stat` throws for a missing path, which is the answer we wanted. Any
    // other failure (permissions) also means "we cannot use this path", and the
    // write that follows will report it in its own words.
    return false;
  }
}

/**
 * Everything needed to create a file, without creating it: the path, the front
 * matter and the body. Throws when the content type is unknown, the title
 * sanitizes to nothing, or the target path is already taken — never silently
 * overwrites.
 *
 * The prefix chain is `content.filePrefix` → the folder's `filePrefix` → the
 * content type's `filePrefix`, and the winner is then placeholder-expanded, so
 * `{{date|yyyy-MM-dd}}` and `{{filePrefix.index}}` both work in any of them.
 */
export async function createContent(
  cfg: Zer0Config,
  req: CreateContentRequest,
  log: LogSink = NOOP_LOG,
): Promise<CreateContentResult> {
  const ct = contentTypeByName(cfg, req.contentType);
  if (ct === undefined) {
    throw new Error(
      `zer0-CMS: unknown content type "${req.contentType}". ` +
        `Configured types: ${getContentTypes(cfg)
          .map((type) => type.name)
          .join(', ')}.`,
    );
  }

  const title = req.title.trim();
  if (title === '') {
    throw new Error('zer0-CMS: a title is required to create content.');
  }

  const base = absPath(cfg, req.folderPath);
  const folderPath = req.subFolder ? path.join(base, req.subFolder) : base;
  const folder = folderForFile(cfg.contentFolders, folderPath);

  // The title field may ask for emoji to be escaped; do it before the title is
  // used for the filename *and* the front matter, so the two agree.
  const titleField = ct.fields.find((field) => field.name === cfg.seo.titleField);
  const titleValue = titleField?.encodeEmoji === true ? encodeEmoji(title) : title;

  const prefix = await processPlaceholders(filePrefixFor(cfg, folder, ct), {
    cfg,
    contentType: ct,
    title: titleValue,
    folderPath,
    filePath: folderPath,
    log,
    ...(folder === undefined ? {} : { folder }),
  });

  const sanitized = sanitizeFileName(titleValue, cfg.content.preserveCasing);
  if (sanitized === '') {
    throw new Error(`zer0-CMS: "${title}" does not produce a usable file name.`);
  }

  const extension = req.fileExtension ?? ct.fileType ?? cfg.content.defaultFileType;
  let filePath: string;

  if (ct.pageBundle === true) {
    const dirName = prefix
      ? prefix.endsWith('/')
        ? `${prefix}${sanitized}`
        : `${prefix}-${sanitized}`
      : sanitized;
    const bundle = path.join(folderPath, dirName);
    if (await exists(bundle)) {
      throw new Error(`zer0-CMS: "${dirName}" already exists in ${folderPath}.`);
    }
    const fileName = sanitizeFileName(ct.defaultFileName ?? 'index', true) || 'index';
    filePath = path.join(bundle, `${fileName}.${extension}`);
  } else {
    const fileName = prefix
      ? `${prefix}-${sanitized}.${extension}`
      : `${sanitized}.${extension}`;
    filePath = path.join(folderPath, fileName);
  }

  if (await exists(filePath)) {
    throw new Error(`zer0-CMS: ${filePath} already exists.`);
  }

  let seed: FrontMatter = {};
  let body = '';
  if (ct.template) {
    const templatePath = absPath(cfg, ct.template);
    try {
      const template = await readArticle(templatePath);
      seed = { ...template.data };
      body = template.body;
    } catch (error) {
      // A missing template is a warning, not a failure: the author still gets
      // their file, just without the seed. Silently swallowing it would leave
      // them wondering why the template did nothing.
      log.warn(
        `Content type "${ct.name}" template ${templatePath} could not be read: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }
  }

  const data = await processFields(ct, cfg, seed, titleValue, filePath, log);
  if (ct.name !== DEFAULT_CONTENT_TYPE_NAME && data[CONTENT_TYPE_FIELD] === undefined) {
    data[CONTENT_TYPE_FIELD] = ct.name;
  }

  return { filePath, data, body, contentType: ct };
}

/** The exact bytes of a newly created file. The caller does the `mkdir` + write. */
export function renderContentFile(result: CreateContentResult, cfg: Zer0Config): string {
  const opts = serializeOptions(cfg);
  return stitch(null, serializeFrontMatter(result.data, opts), result.body, opts.format);
}

// ---------------------------------------------------------------------------
// Generating a content type from an existing file
// ---------------------------------------------------------------------------

const DATE_LIKE = /^\d{4}-\d{2}-\d{2}(?:[T ]|$)/;
const MODIFIED_KEYS: ReadonlySet<string> = new Set([
  'lastmod',
  'last_modified_at',
  'lastmodified',
  'modified',
  'updated',
]);

function inferField(name: string, value: FmValue): Field | undefined {
  const key = name.toLowerCase();
  const title = humanize(name) || name;

  if (key === 'tag' || key === 'tags') {
    return { title, name, type: 'tags' };
  }
  if (key === 'category' || key === 'categories') {
    return { title, name, type: 'categories' };
  }
  if (key === 'draft') {
    return { title, name, type: 'draft' };
  }
  if (key === 'slug') {
    return { title, name, type: 'slug' };
  }

  if (Array.isArray(value)) {
    // A list of strings is a list. A list of objects would have been FM's
    // `block` type, which D6 dropped — so it is left undeclared rather than
    // described by a field type that cannot round-trip it. Undeclared keys are
    // preserved on write; a wrong field type would not be.
    return value.every((item) => typeof item === 'string')
      ? { title, name, type: 'list', multiple: true }
      : undefined;
  }

  if (value !== null && typeof value === 'object') {
    const nested: Field[] = [];
    for (const [childKey, childValue] of Object.entries(value)) {
      const child = inferField(childKey, childValue);
      if (child !== undefined) {
        nested.push(child);
      }
    }
    return { title, name, type: 'fields', fields: nested };
  }

  if (key.includes('image') || key === 'preview' || key === 'cover') {
    return { title, name, type: 'image' };
  }
  if (typeof value === 'number') {
    return { title, name, type: 'number' };
  }
  if (typeof value === 'boolean') {
    return { title, name, type: 'boolean' };
  }
  if (typeof value === 'string' && DATE_LIKE.test(value)) {
    const field: Field = { title, name, type: 'datetime' };
    if (key === 'date' || key === 'publishdate' || key === 'published') {
      field.isPublishDate = true;
    } else if (MODIFIED_KEYS.has(key)) {
      field.isModifiedDate = true;
    }
    return field;
  }

  return { title, name, type: 'string' };
}

/**
 * A content type inferred from a file that already exists — the starting point
 * the author then edits, not an authority.
 *
 * Type inference is by key name first (`tags`, `draft`, `slug`, anything
 * `*image*`) and by value shape second. A date is recognised by an ISO-shaped
 * prefix rather than FM's `new Date(value)` check, which accepted `"7"` as the
 * year 2001 and turned arbitrary strings into datetime fields.
 */
export function generateContentTypeFrom(data: FrontMatter, name: string): ContentType {
  const fields: Field[] = [];
  for (const [key, value] of Object.entries(data)) {
    if (key === CONTENT_TYPE_FIELD) {
      continue;
    }
    const field = inferField(key, value);
    if (field !== undefined) {
      fields.push(field);
    }
  }
  return { name, fields };
}

/**
 * Fields this file carries that its content type does not declare — what
 * "Add missing fields" would append, in the file's own key order.
 */
export function missingFields(ct: ContentType, data: FrontMatter): Field[] {
  const declared = new Set((ct.fields ?? []).map((field) => field.name));
  const out: Field[] = [];

  for (const [key, value] of Object.entries(data)) {
    if (key === CONTENT_TYPE_FIELD || declared.has(key)) {
      continue;
    }
    const field = inferField(key, value);
    if (field !== undefined) {
      out.push(field);
    }
  }

  return out;
}
