/**
 * Writing a front-matter block — the other half of `frontmatter.ts`, and the
 * file decision D7 exists for.
 *
 * There are two ways to write front matter, and this module offers both in a
 * deliberate order:
 *
 *   1. **`updateFrontMatterKeys` — line surgery.** Locate the line range each
 *      changed key occupies, rewrite exactly those lines, insert new keys
 *      before the closing fence, and delete a key by removing exactly its
 *      range. Every other byte of the block — comments, blank lines, key order,
 *      quoting style, indentation quirks — is carried through untouched,
 *      because it is never re-emitted. Flipping `status: pending` to
 *      `status: approved` produces a one-line diff, always.
 *
 *   2. **`serializeFrontMatter` — full emit.** The documented fallback, used
 *      when surgery cannot locate a change (and for TOML and JSON blocks, which
 *      are re-emitted wholesale). It honours `indentArrays`,
 *      `quoteStringValues` and `commaSeparatedFields`, and it does *not*
 *      preserve comments — nothing that re-serialises from a parsed object can.
 *
 * `updateFrontMatterKeys` returns `null` rather than guessing whenever it
 * cannot find where a change belongs, which is the caller's signal to fall back
 * to (2). Silently appending a duplicate key would be the worse failure.
 *
 * ## Change keys and dotted paths
 *
 * A `KeyChange.key` is a top-level key name, or a dotted path (`seo.title`)
 * addressing a nested mapping. A key that literally contains a dot wins over
 * the path reading, decided by looking at the block's own top-level keys — so a
 * file with `image.alt: x` keeps working. Path segments address mappings only;
 * there is no index syntax for reaching inside a sequence. A change whose
 * parent path does not exist in the block returns `null` (fall back to a full
 * emit, which will create the nesting).
 */

import type { Zer0Config } from '../shared/types';
import {
  isYamlSequenceItem,
  parseYamlKeyLine,
  type FmBlock,
  type FmFormat,
  type FmValue,
  type FrontMatter,
} from './frontmatter';

export interface SerializeOptions {
  format: FmFormat;
  /** `true` indents block-sequence items under their key; `false` aligns them. */
  indentArrays: boolean;
  /** `true` double-quotes every string value, even when it needs no quotes. */
  quoteStringValues: boolean;
  /** Keys written as `a, b, c` on one line instead of a block sequence. */
  commaSeparatedFields: string[];
  /** Spaces per nesting level. */
  indent: number;
}

export const DEFAULT_SERIALIZE_OPTIONS: SerializeOptions = {
  format: 'yaml',
  indentArrays: true,
  quoteStringValues: false,
  commaSeparatedFields: [],
  indent: 2,
};

/**
 * Serialization options for a workspace. `format` defaults to the configured
 * one, but callers editing an existing file must pass the format detected from
 * that file — the dialect belongs to the file, not to the setting.
 */
export function serializeOptions(cfg: Zer0Config, format?: FmFormat): SerializeOptions {
  return {
    format: format ?? cfg.frontMatter.format,
    indentArrays: cfg.frontMatter.indentArrays,
    quoteStringValues: cfg.frontMatter.quoteStringValues,
    commaSeparatedFields: [...cfg.frontMatter.commaSeparatedFields],
    indent: DEFAULT_SERIALIZE_OPTIONS.indent,
  };
}

/** One key to set (`value` present) or delete (`value` explicitly `undefined`). */
export interface KeyChange {
  key: string;
  value: FmValue | undefined;
}

// ---------------------------------------------------------------------------
// Applying changes to a parsed object
// ---------------------------------------------------------------------------

function isPlainObject(value: unknown): value is FrontMatter {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function cloneValue(value: FmValue): FmValue {
  if (Array.isArray(value)) {
    return value.map(cloneValue);
  }
  if (isPlainObject(value)) {
    const out: FrontMatter = {};
    for (const [key, item] of Object.entries(value)) {
      out[key] = cloneValue(item);
    }
    return out;
  }
  return value;
}

/**
 * The path a change addresses. A dotted key that also exists literally in
 * `data` is treated as literal — the same rule the line surgery applies to the
 * block's own top-level key lines, so the two never disagree.
 */
function changePath(data: FrontMatter, key: string): string[] {
  if (!key.includes('.') || Object.prototype.hasOwnProperty.call(data, key)) {
    return [key];
  }
  return key.split('.');
}

/**
 * Apply `changes` to a deep copy of `data`. Pure: the input is never mutated,
 * so a caller can render the result before deciding to write it.
 */
export function applyChanges(data: FrontMatter, changes: readonly KeyChange[]): FrontMatter {
  const out = cloneValue(data);
  if (!isPlainObject(out)) {
    return {};
  }
  for (const change of changes) {
    const path = changePath(data, change.key);
    const leaf = path[path.length - 1];
    if (leaf === undefined) {
      continue;
    }
    let node = out;
    let reachable = true;
    for (const segment of path.slice(0, -1)) {
      const next = node[segment];
      if (isPlainObject(next)) {
        node = next;
        continue;
      }
      if (next === undefined || next === null || next === '') {
        const created: FrontMatter = {};
        node[segment] = created;
        node = created;
        continue;
      }
      // The parent holds a scalar or a sequence; overwriting it to make room
      // for a nested key would silently discard data.
      reachable = false;
      break;
    }
    if (!reachable) {
      continue;
    }
    if (change.value === undefined) {
      delete node[leaf];
    } else {
      node[leaf] = change.value;
    }
  }
  return out;
}

/**
 * Read side of `frontMatter.commaSeparatedFields`: the named keys hold
 * `a, b, c` on one line in the file and a list everywhere else. Returns a new
 * object; keys not named, and keys that are already lists, are untouched.
 */
export function applyCommaSeparatedFields(data: FrontMatter, fields: readonly string[]): FrontMatter {
  if (fields.length === 0) {
    return data;
  }
  const out: FrontMatter = { ...data };
  for (const field of fields) {
    const value = out[field];
    if (typeof value !== 'string') {
      continue;
    }
    out[field] = value
      .split(',')
      .map((part) => part.trim())
      .filter((part) => part.length > 0);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Scalar and key emission (shared by full emit and line surgery)
// ---------------------------------------------------------------------------

/** Words a YAML reader would coerce. Wider than what *our* parser coerces on
 *  purpose: Jekyll reads YAML 1.1, where `no` and `off` are booleans, and a
 *  string that means "no" must not become `false` downstream. The single-letter
 *  `y`/`n` shorthand is excluded — a tag literally spelled `y` is likelier than
 *  a YAML 1.1 purist reading it. */
const RESERVED_RE = /^(?:true|false|null|~|yes|no|on|off)$/i;
const NUMBER_LIKE_RE = /^[-+]?(?:\d+|\d*\.\d+|\d+\.\d*)(?:[eE][-+]?\d+)?$/;
const LEADING_INDICATOR_RE = /^[,[\]{}#&*!|>'"%@`]/;
const INDICATOR_PAIR_RE = /^[-?:](?:\s|$)/;

/** Structural quoting: the text would not survive as a plain scalar at all. */
function needsStructuralQuotes(value: string): boolean {
  return (
    value.length === 0 ||
    value !== value.trim() ||
    LEADING_INDICATOR_RE.test(value) ||
    INDICATOR_PAIR_RE.test(value) ||
    /:(?:\s|$)/.test(value) ||
    /\s#/.test(value)
  );
}

/** Values additionally need quotes when a reader would coerce them to a
 *  non-string — the difference between `version: "3"` and `version: 3`. */
function needsQuotes(value: string): boolean {
  return needsStructuralQuotes(value) || RESERVED_RE.test(value) || NUMBER_LIKE_RE.test(value);
}

/**
 * A double-quoted YAML scalar.
 *
 * Backslashes escape FIRST, then quotes — the other order double-escapes the
 * backslash it just introduced, and a value ending in `\` then closes its own
 * string and swallows the rest of the block. Exported so nothing else in the
 * codebase hand-rolls a second, subtly different version of this.
 */
export function quoteScalar(value: string): string {
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

const quote = quoteScalar;

function emitString(value: string, opts: SerializeOptions): string {
  return opts.quoteStringValues || needsQuotes(value) ? quote(value) : value;
}

/** One scalar as it appears after `key: ` or `- `. Multi-line strings are
 *  handled by the caller as block scalars and never reach this. */
function emitScalar(value: FmValue, opts: SerializeOptions): string {
  if (value === null) {
    return 'null';
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false';
  }
  if (typeof value === 'number') {
    // YAML's `.inf`/`.nan` are not in the subset the parser reads, so emitting
    // them would create a block we could not read back.
    return Number.isFinite(value) ? String(value) : 'null';
  }
  if (typeof value === 'string') {
    return emitString(value, opts);
  }
  return JSON.stringify(value);
}

/** Keys are quoted only when they would not parse back as themselves. A key is
 *  never coerced by a reader, so `n:` and `2026:` stay bare. */
function emitKeyToken(key: string): string {
  return needsStructuralQuotes(key) ? quote(key) : key;
}

/** A multi-line string as a literal block scalar rooted at `indent`. */
function emitBlockScalar(value: string, opts: SerializeOptions, indent: number): { head: string; lines: string[] } {
  const keepsTrailing = value.endsWith('\n') && !value.endsWith('\n\n');
  const body = keepsTrailing ? value.slice(0, -1) : value;
  const pad = ' '.repeat(indent);
  const parts = body.split('\n');
  const first = parts[0] ?? '';
  // A first line that starts with whitespace needs an explicit indentation
  // indicator, or a reader cannot tell content from indentation.
  const indicator = first.startsWith(' ') || first.startsWith('\t') ? String(opts.indent) : '';
  return {
    head: `|${indicator}${keepsTrailing ? '' : '-'}`,
    lines: parts.map((line) => (line.length === 0 ? '' : pad + line)),
  };
}

/**
 * Emit `key: value` and everything under it, as lines without line endings.
 * `indent` is the column the key itself sits at.
 */
function emitKeyLines(key: string, value: FmValue, opts: SerializeOptions, indent: number): string[] {
  const label = `${' '.repeat(indent)}${emitKeyToken(key)}:`;
  const childIndent = indent + opts.indent;

  if (value === null) {
    return [label];
  }

  if (Array.isArray(value)) {
    if (opts.commaSeparatedFields.includes(key)) {
      const joined = value.map((item) => (item === null ? '' : emitScalarText(item))).join(', ');
      return [`${label} ${emitString(joined, opts)}`];
    }
    if (value.length === 0) {
      return [`${label} []`];
    }
    const itemIndent = opts.indentArrays ? childIndent : indent;
    const out = [label];
    for (const item of value) {
      out.push(...emitSequenceItem(item, opts, itemIndent));
    }
    return out;
  }

  if (isPlainObject(value)) {
    const keys = Object.keys(value);
    if (keys.length === 0) {
      return [`${label} {}`];
    }
    const out = [label];
    for (const child of keys) {
      out.push(...emitKeyLines(child, value[child] ?? null, opts, childIndent));
    }
    return out;
  }

  if (typeof value === 'string' && value.includes('\n')) {
    const block = emitBlockScalar(value, opts, childIndent);
    return [`${label} ${block.head}`, ...block.lines];
  }

  return [`${label} ${emitScalar(value, opts)}`];
}

/** The text of a scalar for a comma-separated field: never quoted per item. */
function emitScalarText(value: FmValue): string {
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '';
}

function emitSequenceItem(item: FmValue, opts: SerializeOptions, indent: number): string[] {
  const pad = ' '.repeat(indent);

  if (isPlainObject(item)) {
    const keys = Object.keys(item);
    if (keys.length === 0) {
      return [`${pad}- {}`];
    }
    const inner: string[] = [];
    for (const key of keys) {
      inner.push(...emitKeyLines(key, item[key] ?? null, opts, indent + 2));
    }
    // Hoist the first child onto the dash, which is how every hand-written
    // sequence of mappings looks.
    inner[0] = `${pad}- ${(inner[0] ?? '').slice(indent + 2)}`;
    return inner;
  }

  if (Array.isArray(item)) {
    if (item.length === 0) {
      return [`${pad}- []`];
    }
    const inner: string[] = [];
    for (const sub of item) {
      inner.push(...emitSequenceItem(sub, opts, indent + opts.indent));
    }
    inner[0] = `${pad}- ${(inner[0] ?? '').trimStart()}`;
    return inner;
  }

  if (typeof item === 'string' && item.includes('\n')) {
    const block = emitBlockScalar(item, opts, indent + 2);
    return [`${pad}- ${block.head}`, ...block.lines];
  }

  return [`${pad}- ${emitScalar(item, opts)}`];
}

// ---------------------------------------------------------------------------
// Full emit
// ---------------------------------------------------------------------------

/**
 * Emit a whole front-matter body (no fences, no trailing newline). Key order is
 * the object's own insertion order. Comments cannot survive this path — that is
 * what `updateFrontMatterKeys` is for.
 */
export function serializeFrontMatter(data: FrontMatter, opts: SerializeOptions): string {
  if (opts.format === 'json') {
    return JSON.stringify(data, null, opts.indent);
  }
  if (opts.format === 'toml') {
    return emitToml(data, opts).join('\n');
  }
  const lines: string[] = [];
  for (const [key, value] of Object.entries(data)) {
    if (value === undefined) {
      continue;
    }
    lines.push(...emitKeyLines(key, value, opts, 0));
  }
  return lines.join('\n');
}

function emitTomlScalar(value: FmValue): string {
  if (typeof value === 'string') {
    return quote(value);
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false';
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : '0';
  }
  if (Array.isArray(value)) {
    return `[${value.map(emitTomlScalar).join(', ')}]`;
  }
  if (isPlainObject(value)) {
    return `{ ${Object.entries(value)
      .map(([key, item]) => `${key} = ${emitTomlScalar(item)}`)
      .join(', ')} }`;
  }
  return '""';
}

/** TOML has no null, so a null-valued key is omitted rather than invented. */
function emitToml(data: FrontMatter, opts: SerializeOptions, prefix: readonly string[] = []): string[] {
  const scalars: string[] = [];
  const tables: string[] = [];
  for (const [key, value] of Object.entries(data)) {
    if (value === null || value === undefined) {
      continue;
    }
    if (isPlainObject(value)) {
      const path = [...prefix, key];
      tables.push('', `[${path.join('.')}]`, ...emitToml(value, opts, path));
      continue;
    }
    scalars.push(`${key} = ${emitTomlScalar(value)}`);
  }
  return [...scalars, ...tables];
}

// ---------------------------------------------------------------------------
// Line surgery
// ---------------------------------------------------------------------------

/** A block under edit. `lines` may carry trailing CRs; joining on `\n`
 *  reproduces the original bytes exactly. */
interface Doc {
  lines: string[];
  crlf: boolean;
}

interface LineInfo {
  indent: number;
  content: string;
  blank: boolean;
  comment: boolean;
}

/** The line range one key occupies, its own line first. */
interface KeyRange {
  key: string;
  start: number;
  end: number;
  indent: number;
}

function analyze(doc: Doc, index: number): LineInfo {
  const raw = doc.lines[index] ?? '';
  const text = raw.endsWith('\r') ? raw.slice(0, -1) : raw;
  let indent = 0;
  while (indent < text.length) {
    const ch = text.charAt(indent);
    if (ch !== ' ' && ch !== '\t') {
      break;
    }
    indent++;
  }
  const content = text.slice(indent);
  return { indent, content, blank: content.length === 0, comment: content.startsWith('#') };
}

function withCrlf(doc: Doc, lines: readonly string[]): string[] {
  return doc.crlf ? lines.map((line) => `${line}\r`) : [...lines];
}

/**
 * Every key at `indent` within `[from, to]`, with the line range each occupies.
 *
 * A key's range runs from its own line through the last line that belongs to
 * its value — deeper-indented lines, and sequence items at the key's own indent
 * (the un-indented block-sequence style). Blank lines and comments between two
 * keys stay *outside* both ranges, which is what makes "everything untouched is
 * byte-identical" true rather than aspirational.
 */
function scanKeys(doc: Doc, from: number, to: number, indent: number): KeyRange[] {
  const found: KeyRange[] = [];
  let i = Math.max(0, from);
  const last = Math.min(to, doc.lines.length - 1);
  while (i <= last) {
    const info = analyze(doc, i);
    if (info.blank || info.comment || info.indent !== indent) {
      i++;
      continue;
    }
    const pair = parseYamlKeyLine(info.content);
    if (pair === null) {
      i++;
      continue;
    }
    let end = i;
    let j = i + 1;
    while (j <= last) {
      const next = analyze(doc, j);
      if (next.blank || next.comment) {
        j++;
        continue;
      }
      if (next.indent > indent || (next.indent === indent && isYamlSequenceItem(next.content))) {
        end = j;
        j++;
        continue;
      }
      break;
    }
    found.push({ key: pair.key, start: i, end, indent });
    i = end + 1;
  }
  return found;
}

/** Duplicate keys: last wins, matching the parser. */
function pick(ranges: readonly KeyRange[], key: string): KeyRange | null {
  let match: KeyRange | null = null;
  for (const range of ranges) {
    if (range.key === key) {
      match = range;
    }
  }
  return match;
}

/** What sits under a key line, from the point of view of "can a nested key go
 *  in here?": a mapping we can descend into, nothing at all, or something we
 *  must not disturb. */
type Descent = { kind: 'mapping'; indent: number } | { kind: 'empty' } | { kind: 'blocked' };

/** Whether a key line's value sits on the line itself — a scalar, a flow
 *  collection or a block-scalar header we must not bury under a child key. */
function holdsInlineValue(doc: Doc, range: KeyRange): boolean {
  const pair = parseYamlKeyLine(analyze(doc, range.start).content);
  return pair !== null && pair.rest.length > 0 && !pair.rest.startsWith('#');
}

function descentOf(doc: Doc, range: KeyRange): Descent {
  if (holdsInlineValue(doc, range)) {
    return { kind: 'blocked' };
  }
  for (let i = range.start + 1; i <= range.end; i++) {
    const info = analyze(doc, i);
    if (info.blank || info.comment) {
      continue;
    }
    if (info.indent <= range.indent || isYamlSequenceItem(info.content)) {
      return { kind: 'blocked' };
    }
    return parseYamlKeyLine(info.content) === null
      ? { kind: 'blocked' }
      : { kind: 'mapping', indent: info.indent };
  }
  return { kind: 'empty' };
}

function locate(doc: Doc, path: readonly string[]): KeyRange | null {
  let from = 0;
  let to = doc.lines.length - 1;
  let indent = 0;
  for (let depth = 0; depth < path.length; depth++) {
    const segment = path[depth];
    if (segment === undefined) {
      return null;
    }
    const match = pick(scanKeys(doc, from, to, indent), segment);
    if (match === null) {
      return null;
    }
    if (depth === path.length - 1) {
      return match;
    }
    const descent = descentOf(doc, match);
    if (descent.kind !== 'mapping') {
      return null;
    }
    from = match.start + 1;
    to = match.end;
    indent = descent.indent;
  }
  return null;
}

/** Insert after the last line that carries content, so a new key lands before
 *  trailing blank lines rather than after them. */
function insertionPoint(doc: Doc, from: number, to: number): number {
  let at = from;
  for (let i = from; i <= Math.min(to, doc.lines.length - 1); i++) {
    const info = analyze(doc, i);
    if (!info.blank) {
      at = i + 1;
    }
  }
  return at;
}

function applyOne(doc: Doc, change: KeyChange, opts: SerializeOptions): boolean {
  const topLevel = scanKeys(doc, 0, doc.lines.length - 1, 0);
  const literal = pick(topLevel, change.key) !== null;
  const path = !change.key.includes('.') || literal ? [change.key] : change.key.split('.');
  const leaf = path[path.length - 1];
  if (leaf === undefined) {
    return false;
  }

  const target = locate(doc, path);

  if (change.value === undefined) {
    if (target !== null) {
      doc.lines.splice(target.start, target.end - target.start + 1);
    }
    // Deleting a key that is not there is a success, not a fallback trigger.
    return true;
  }

  if (target !== null) {
    const replacement = withCrlf(doc, emitKeyLines(leaf, change.value, opts, target.indent));
    doc.lines.splice(target.start, target.end - target.start + 1, ...replacement);
    return true;
  }

  if (path.length === 1) {
    const at = insertionPoint(doc, 0, doc.lines.length - 1);
    doc.lines.splice(at, 0, ...withCrlf(doc, emitKeyLines(leaf, change.value, opts, 0)));
    return true;
  }

  const parent = locate(doc, path.slice(0, -1));
  if (parent === null) {
    return false; // unlocatable nested change → the caller re-serialises
  }
  const descent = descentOf(doc, parent);
  if (descent.kind === 'blocked') {
    return false; // the parent holds a scalar, a sequence, or something unreadable
  }
  const indent = descent.kind === 'mapping' ? descent.indent : parent.indent + opts.indent;
  const at =
    descent.kind === 'mapping' ? insertionPoint(doc, parent.start + 1, parent.end) : parent.start + 1;
  doc.lines.splice(at, 0, ...withCrlf(doc, emitKeyLines(leaf, change.value, opts, indent)));
  return true;
}

/**
 * Rewrite only the lines belonging to `changes`. Every other byte of `raw` is
 * carried through unchanged.
 *
 * Returns `null` when a change cannot be placed — an unlocatable nested path,
 * or a non-YAML block, both of which the caller resolves by re-serialising with
 * `serializeFrontMatter`. An empty change set returns `raw` unchanged, which is
 * what makes an edit-free save byte-identical.
 */
export function updateFrontMatterKeys(
  raw: string,
  changes: readonly KeyChange[],
  opts: SerializeOptions,
): string | null {
  if (changes.length === 0) {
    return raw;
  }
  if (opts.format !== 'yaml') {
    // TOML and JSON blocks are re-emitted wholesale. They carry no comments in
    // any file this CMS creates, and a second surgical dialect is not worth the
    // extra failure mode.
    return null;
  }

  const doc: Doc = {
    lines: raw.length === 0 ? [] : raw.split('\n'),
    crlf: raw.includes('\r\n'),
  };

  for (const change of changes) {
    if (!applyOne(doc, change, opts)) {
      return null;
    }
  }
  return doc.lines.join('\n');
}

// ---------------------------------------------------------------------------
// Putting a file back together
// ---------------------------------------------------------------------------

function detectEol(block: FmBlock | null, newRaw: string, body: string): string {
  if (newRaw.includes('\r\n') || body.includes('\r\n') || (block?.raw.includes('\r\n') ?? false)) {
    return '\r\n';
  }
  return '\n';
}

/**
 * Reassemble a file from a front-matter body and a document body, re-adding the
 * fences the dialect uses. `block` is consulted only for its line-ending style;
 * pass `null` to add front matter to a file that had none.
 */
export function stitch(block: FmBlock | null, newRaw: string, body: string, fmt: FmFormat): string {
  const eol = detectEol(block, newRaw, body);
  let raw = newRaw;
  while (raw.endsWith('\n') || raw.endsWith('\r')) {
    raw = raw.slice(0, -1);
  }

  if (fmt === 'json') {
    return raw.length === 0 ? body : `${raw}${eol}${body}`;
  }
  const fence = fmt === 'toml' ? '+++' : '---';
  if (raw.length === 0) {
    return `${fence}${eol}${fence}${eol}${body}`;
  }
  return `${fence}${eol}${raw}${eol}${fence}${eol}${body}`;
}
