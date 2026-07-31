/**
 * The `{{…}}` token vocabulary — the one place that knows what a placeholder
 * means, used by field defaults, filename prefixes, folder paths and slug
 * templates alike.
 *
 * The full set:
 *
 * | Token | Resolves to |
 * |---|---|
 * | `{{now}}` | now, in `date.format` (raw ISO when that setting is empty) |
 * | `{{year}} {{month}} {{day}}` | `yyyy` `MM` `dd` |
 * | `{{hour12}} {{hour24}} {{minute}} {{second}} {{ampm}}` | `hh` `HH` `mm` `ss` `aaa` |
 * | `{{date\|<pattern>}}` | now, in an ad-hoc pattern |
 * | `{{title}}` | the article's title field, else the title being created |
 * | `{{slug}}` | `createSlug` against the content type's `slugTemplate` |
 * | `{{fm.<key>}}` | a front-matter value; `\| format:'<pattern>'` formats it as a date |
 * | `{{pathToken.<n>}}` | the n-th segment of the workspace-relative file path |
 * | `{{pathToken.relPath}}` | the file's directory, relative to its content folder |
 * | `{{filePrefix.index}}` | file count in the target folder + 1, zero-padded to 3 |
 * | `{{filePrefix.index\|zeros:<n>}}` | the same, padded to `<n>` |
 * | `{{<id>}}` | a `placeholders[]` entry: a static `value`, or a script's stdout |
 *
 * Two rules govern the whole module:
 *
 *   1. **An unresolvable token is left alone.** A missing front-matter key
 *      leaves `{{fm.author}}` sitting in the output rather than collapsing to
 *      an empty string. A visible `{{` in a filename is a bug somebody fixes;
 *      a silently-missing path segment is a bug nobody notices until two files
 *      collide.
 *   2. **One pipeline, one order.** FM ran the token groups in two different
 *      orders (one for field defaults, another for file prefixes) and the
 *      difference was undocumented. `processPlaceholders` runs them in a single
 *      order: article → front matter → path → file index → custom → time →
 *      `{{date|…}}`. Custom placeholders resolve *before* the time tokens on
 *      purpose, so a script may return text that still contains `{{now}}`.
 *
 * Custom scripts run through `execFile` with an argv array and **no shell**:
 * FM interpolated the workspace, file and title into a shell string, which a
 * path containing a quote turns into arbitrary command execution. A script that
 * fails, times out, or is simply missing yields `FAULTY_PLACEHOLDER`, which
 * `isEmpty` recognises — a broken placeholder must read as "no value", never as
 * a literal value that gets written into somebody's site.
 *
 * This module and `slug.ts` reference each other: `{{slug}}` is defined by the
 * slug template, and slug templates may contain time and front-matter tokens.
 * The recursion is in the domain, not in the layering — `createSlug` only ever
 * calls the *synchronous* token processors below, and none of those resolve
 * `{{slug}}`, so the cycle terminates in one step.
 */

import { execFile } from 'node:child_process';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { absPath } from '../shared/config';
import { formatDate, parseDate } from '../shared/dates';
import { toPosix } from '../shared/glob';
import {
  NOOP_LOG,
  type ContentFolder,
  type ContentType,
  type LogSink,
  type Zer0Config,
} from '../shared/types';
import type { FmValue, FrontMatter } from './frontmatter';
import { createSlug } from './slug';

/**
 * What a placeholder resolves to when its script fails. FM's sentinel, kept
 * because `isEmpty` treats it as empty and the panel renders it as "unset".
 *
 * Twin: `src/webview/panel/fields/index.ts#FAULTY_PLACEHOLDER`. This module
 * imports `node:child_process`, so the panel bundle cannot reach the constant
 * and restates the literal. Both are the same string or the panel shows
 * `<failed to process>` to an author as if it were text they typed.
 */
export const FAULTY_PLACEHOLDER = '<failed to process>';

/** Milliseconds a placeholder script may run before it is killed. */
export const PLACEHOLDER_SCRIPT_TIMEOUT_MS = 5000;

/** Bytes of stdout a placeholder script may produce. */
const SCRIPT_MAX_BUFFER = 1024 * 1024;

export interface PlaceholderContext {
  cfg: Zer0Config;
  /** The file the value belongs to; may not exist yet during creation. */
  filePath?: string;
  /** The directory new content is being created in — `{{filePrefix.index}}`
   *  counts the files here. Falls back to the directory of `filePath`. */
  folderPath?: string;
  data?: FrontMatter;
  contentType?: ContentType;
  folder?: ContentFolder;
  /** The title being entered, for content that has no front matter yet. */
  title?: string;
  /** The article's own date, when the tokens should not mean "now". */
  date?: Date;
  log?: LogSink;
}

/** Does this value contain a `{{…}}` token at all? */
export function hasPlaceholder(value: unknown): boolean {
  return typeof value === 'string' && value.includes('{{') && value.includes('}}');
}

/** Replace every literal occurrence of `token` — no regex, no escaping bugs. */
function replaceAll(value: string, token: string, replacement: string): string {
  return value.split(token).join(replacement);
}

/** A front-matter value as text: lists join with `, `, objects do not render. */
function renderValue(value: FmValue | undefined): string | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    const parts = value.map(renderValue).filter((part): part is string => part !== undefined);
    return parts.length > 0 ? parts.join(', ') : undefined;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Time
// ---------------------------------------------------------------------------

const TIME_TOKENS: ReadonlyArray<[string, string]> = [
  ['{{year}}', 'yyyy'],
  ['{{month}}', 'MM'],
  ['{{day}}', 'dd'],
  ['{{hour12}}', 'hh'],
  ['{{hour24}}', 'HH'],
  ['{{minute}}', 'mm'],
  ['{{second}}', 'ss'],
  ['{{ampm}}', 'aaa'],
];

/**
 * `{{now}}` and the seven calendar-part tokens, formatted in the configured
 * timezone. `{{now}}` falls back to a raw ISO timestamp when `date.format` is
 * empty, which is the only way to say "give me the machine-readable form".
 */
export function processTimePlaceholders(value: string, cfg: Zer0Config, date?: Date): string {
  if (!hasPlaceholder(value)) {
    return value;
  }
  const when = date ?? new Date();
  let out = value;

  if (out.includes('{{now}}')) {
    const now = cfg.date.format
      ? formatDate(when, cfg.date.format, cfg.date.timezone)
      : when.toISOString();
    out = replaceAll(out, '{{now}}', now);
  }

  for (const [token, pattern] of TIME_TOKENS) {
    if (out.includes(token)) {
      out = replaceAll(out, token, formatDate(when, pattern, cfg.date.timezone));
    }
  }

  return out;
}

const DATE_TOKEN_RE = /\{\{date\|([^}]*)\}\}/g;

/** `{{date|yyyy-MM-dd}}` — an ad-hoc pattern, formatted in the configured zone. */
export function processDatePlaceholders(value: string, cfg: Zer0Config, date?: Date): string {
  if (!value.includes('{{date|')) {
    return value;
  }
  const when = date ?? new Date();
  return value.replace(DATE_TOKEN_RE, (match, pattern: string) => {
    const trimmed = pattern.trim();
    return trimmed ? formatDate(when, trimmed, cfg.date.timezone) : match;
  });
}

// ---------------------------------------------------------------------------
// Front matter
// ---------------------------------------------------------------------------

const FM_TOKEN_RE = /\{\{fm\.([^}|]+)(?:\|([^}]*))?\}\}/g;

/**
 * `{{fm.<key>}}`, optionally `{{fm.<key> | format:'<pattern>'}}`. The value is
 * looked up by literal key first and by dotted path second, so a front matter
 * that really does have a key called `image.alt` still resolves.
 */
export function processFmPlaceholders(value: string, data: FrontMatter, cfg: Zer0Config): string {
  if (!value.includes('{{fm.')) {
    return value;
  }

  return value.replace(FM_TOKEN_RE, (match, rawKey: string, rawFormat?: string) => {
    const key = rawKey.trim();
    let found: FmValue | undefined = data[key];

    if (found === undefined && key.includes('.')) {
      let node: FmValue | undefined = data;
      for (const segment of key.split('.')) {
        if (node === null || node === undefined || typeof node !== 'object') {
          node = undefined;
          break;
        }
        if (Array.isArray(node)) {
          node = undefined;
          break;
        }
        node = node[segment];
      }
      found = node;
    }

    const rendered = renderValue(found);
    if (rendered === undefined || rendered === '') {
      return match;
    }

    const formatting = rawFormat?.trim() ?? '';
    if (!formatting.startsWith('format')) {
      return rendered;
    }

    let pattern = formatting.replace(/^format\s*:?/, '').trim();
    if (pattern.startsWith("'") && pattern.endsWith("'") && pattern.length > 1) {
      pattern = pattern.slice(1, -1);
    }
    const parsed = parseDate(rendered, pattern || undefined);
    if (parsed === null || !pattern) {
      return rendered;
    }
    return formatDate(parsed, pattern, cfg.date.timezone);
  });
}

// ---------------------------------------------------------------------------
// Article and path
// ---------------------------------------------------------------------------

/** `{{title}}` and `{{slug}}`, both derived from the article's title field. */
export function processArticlePlaceholders(value: string, ctx: PlaceholderContext): string {
  if (!hasPlaceholder(value)) {
    return value;
  }

  const data = ctx.data ?? {};
  const titleValue = renderValue(data[ctx.cfg.seo.titleField]);
  const title = titleValue !== undefined && titleValue !== '' ? titleValue : (ctx.title ?? '');

  let out = value;
  if (out.includes('{{title}}') && title !== '') {
    out = replaceAll(out, '{{title}}', title);
  }
  if (out.includes('{{slug}}') && title !== '') {
    const slug = createSlug(ctx.cfg, title, ctx.contentType, ctx.filePath, data);
    if (slug !== '') {
      out = replaceAll(out, '{{slug}}', slug);
    }
  }
  return out;
}

const PATH_TOKEN_RE = /\{\{pathToken\.(\d+|relPath)\}\}/g;

/**
 * `{{pathToken.<n>}}` is the n-th segment of the file's workspace-relative
 * path; `{{pathToken.relPath}}` is its directory relative to the content
 * folder that owns it (empty for a file sitting directly in the folder).
 */
export function processPathPlaceholders(value: string, ctx: PlaceholderContext): string {
  const filePath = ctx.filePath;
  if (!value.includes('{{pathToken.') || filePath === undefined) {
    return value;
  }

  const relative = toPosix(path.relative(ctx.cfg.workspaceRoot, filePath));
  const segments = relative.split('/');

  return value.replace(PATH_TOKEN_RE, (match, token: string) => {
    if (token === 'relPath') {
      const base = ctx.folder?.path;
      if (base === undefined) {
        return match;
      }
      return toPosix(path.relative(base, path.dirname(filePath)));
    }
    return segments[Number(token)] ?? match;
  });
}

// ---------------------------------------------------------------------------
// File index
// ---------------------------------------------------------------------------

const FILE_INDEX_RE = /\{\{filePrefix\.index(\|[^}]*)?\}\}/g;

/** The directory `{{filePrefix.index}}` counts: an explicit one, else the
 *  directory the file lives in. */
function indexFolder(ctx: PlaceholderContext): string | undefined {
  if (ctx.folderPath !== undefined) {
    return ctx.folderPath;
  }
  if (ctx.filePath === undefined) {
    return undefined;
  }
  return path.extname(ctx.filePath) === '' ? ctx.filePath : path.dirname(ctx.filePath);
}

async function countContentFiles(folderPath: string, cfg: Zer0Config): Promise<number> {
  let entries;
  try {
    entries = await fs.readdir(folderPath, { withFileTypes: true });
  } catch {
    // The folder is about to be created — it holds no files yet, so the next
    // index is 1. Returning zero says exactly that.
    return 0;
  }

  const extensions = new Set(cfg.content.supportedFileTypes.map((ext) => ext.toLowerCase()));
  let count = 0;
  for (const entry of entries) {
    if (!entry.isFile() || entry.name.startsWith('.') || entry.name.includes('_index.')) {
      continue;
    }
    if (extensions.has(path.extname(entry.name).replace(/^\./, '').toLowerCase())) {
      count += 1;
    }
  }
  return count;
}

/**
 * `{{filePrefix.index}}` → the number of content files already in the target
 * folder, plus one, zero-padded to three digits. `|zeros:<n>` overrides the
 * width; `|zeros:0` leaves the number unpadded.
 */
export async function processFilePrefixIndex(
  value: string,
  ctx: PlaceholderContext,
): Promise<string> {
  if (!value.includes('{{filePrefix.index')) {
    return value;
  }
  const folderPath = indexFolder(ctx);
  if (folderPath === undefined) {
    return value;
  }

  const next = (await countContentFiles(folderPath, ctx.cfg)) + 1;

  return value.replace(FILE_INDEX_RE, (_match, rawOptions?: string) => {
    let width = 3;
    for (const option of (rawOptions ?? '').replace(/^\|/, '').split(',')) {
      const trimmed = option.trim();
      if (trimmed.startsWith('zeros:')) {
        const parsed = Number.parseInt(trimmed.slice('zeros:'.length), 10);
        if (Number.isFinite(parsed) && parsed >= 0) {
          width = parsed;
        }
      }
    }
    return String(next).padStart(width, '0');
  });
}

// ---------------------------------------------------------------------------
// Custom placeholders
// ---------------------------------------------------------------------------

function runScript(
  command: string,
  args: readonly string[],
  cwd: string,
): Promise<{ ok: boolean; output: string }> {
  return new Promise((resolve) => {
    execFile(
      command,
      [...args],
      {
        cwd,
        timeout: PLACEHOLDER_SCRIPT_TIMEOUT_MS,
        maxBuffer: SCRIPT_MAX_BUFFER,
        windowsHide: true,
      },
      (error, stdout) => {
        if (error) {
          resolve({ ok: false, output: error.message });
          return;
        }
        resolve({ ok: true, output: stdout.trim() });
      },
    );
  });
}

/**
 * `{{<id>}}` for every entry in `placeholders[]`: a static `value`, or the
 * stdout of `script` run by `command` (default `node`) with the workspace root,
 * the file path and the title as its three arguments.
 *
 * Unlike FM, the output is used verbatim as text — it is not parsed as JSON and
 * not split into an array. `processPlaceholders` returns a string, so a script
 * returning a structure had nowhere to put it anyway; saying so plainly beats a
 * type that changes shape depending on what a subprocess printed.
 */
export async function processCustomPlaceholders(
  value: string,
  ctx: PlaceholderContext,
): Promise<string> {
  const placeholders = ctx.cfg.placeholders;
  if (!hasPlaceholder(value) || placeholders.length === 0) {
    return value;
  }

  const log = ctx.log ?? NOOP_LOG;
  let out = value;

  for (const placeholder of placeholders) {
    const token = `{{${placeholder.id}}}`;
    if (!out.includes(token)) {
      continue;
    }

    let resolved = placeholder.value ?? '';

    if (placeholder.script) {
      const scriptPath = absPath(ctx.cfg, placeholder.script);
      const command = placeholder.command ?? 'node';
      const result = await runScript(
        command,
        [scriptPath, ctx.cfg.workspaceRoot, ctx.filePath ?? '', ctx.title ?? ''],
        ctx.cfg.workspaceRoot,
      );

      if (!result.ok) {
        log.warn(`Placeholder "${placeholder.id}" failed: ${result.output}`);
        resolved = FAULTY_PLACEHOLDER;
      } else {
        resolved = result.output;
      }
    }

    if (resolved !== FAULTY_PLACEHOLDER) {
      resolved = processTimePlaceholders(resolved, ctx.cfg, ctx.date);
      resolved = processDatePlaceholders(resolved, ctx.cfg, ctx.date);
    }

    // A value that *is* the token becomes the resolved value wholesale;
    // otherwise the token is substituted where it appears.
    out = out === token ? resolved : replaceAll(out, token, resolved);
  }

  return out;
}

// ---------------------------------------------------------------------------
// The pipeline
// ---------------------------------------------------------------------------

/**
 * Resolve every token in `value`, in the documented order. A string with no
 * `{{` is returned untouched without touching the disk or spawning anything.
 */
export async function processPlaceholders(
  value: string,
  ctx: PlaceholderContext,
): Promise<string> {
  if (!hasPlaceholder(value)) {
    return value;
  }

  let out = processArticlePlaceholders(value, ctx);
  out = processFmPlaceholders(out, ctx.data ?? {}, ctx.cfg);
  out = processPathPlaceholders(out, ctx);
  out = await processFilePrefixIndex(out, ctx);
  out = await processCustomPlaceholders(out, ctx);
  out = processTimePlaceholders(out, ctx.cfg, ctx.date);
  out = processDatePlaceholders(out, ctx.cfg, ctx.date);
  return out;
}
