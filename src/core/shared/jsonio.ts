/**
 * JSON in, JSON out.
 *
 * Reading: `zer0.json` and `.vscode/settings.json` are JSON *with comments*
 * (line and block) and trailing commas. `readJsonc` reads them with
 * `jsonc-parser` — the parser VS Code itself reads its settings with, bundled
 * at build time (ADR 0006 decision 9) — and throws an error naming the line
 * and column of the first problem in the original text.
 *
 * Writing: the ledger and everything under `.cms/distribution/` are written by
 * BOTH this extension and the stdlib-Python lane. If the two serialisers
 * disagree by a byte, every publish becomes a spurious git diff. `pyJsonDump`
 * reproduces `json.dumps` exactly: `sort_keys` ordering, `ensure_ascii`
 * escaping that starts at U+007F (not U+0080), Python's separators, and
 * Python's `Infinity`/`NaN` spellings. No library does that, so it stays here.
 *
 * The one unavoidable difference: JavaScript has a single number type, so a
 * Python float that happens to be integral (`2.0`) round-trips as `2`.
 */

import * as fs from 'node:fs/promises';

import { parse, printParseErrorCode, type ParseError } from 'jsonc-parser';

// ---------------------------------------------------------------------------
// Reading
// ---------------------------------------------------------------------------

/**
 * Parse JSON with comments and trailing commas. Throws an `Error` naming the
 * line and column, in the original text, of the first thing it could not read.
 */
export function readJsonc<T>(text: string): T {
  const errors: ParseError[] = [];
  const value = parse(text, errors, { allowTrailingComma: true }) as T;
  const first = errors[0];
  if (first !== undefined) {
    const lines = text.slice(0, first.offset).split('\n');
    const column = (lines[lines.length - 1] ?? '').length + 1;
    throw new Error(`Invalid JSON at line ${lines.length}, column ${column}: ${printParseErrorCode(first.error)}`);
  }
  return value;
}

/**
 * Read and parse a JSON/JSONC file. A missing, unreadable or corrupt file is a
 * normal state for every caller here (no `zer0.json` yet, no ledger yet), so it
 * yields `undefined` rather than an exception.
 */
export async function readJsonFile<T>(filePath: string): Promise<T | undefined> {
  let text: string;
  try {
    text = await fs.readFile(filePath, 'utf8');
  } catch {
    // Missing or unreadable: the caller's "not configured yet" branch.
    return undefined;
  }
  try {
    return readJsonc<T>(text);
  } catch {
    // Corrupt: same answer. Surfacing the parse error is the caller's job when
    // it has somewhere to show it (the config loader logs it; the ledger does
    // not, because a broken ledger must not block reading content).
    return undefined;
  }
}

// ---------------------------------------------------------------------------
// Writing — Python `json.dumps` parity
// ---------------------------------------------------------------------------

export interface PyJsonOptions {
  /** Spaces per level. Omit for Python's compact `{"a": 1, "b": 2}` form. */
  indent?: number;
  /** Python's `sort_keys=True`. */
  sortKeys?: boolean;
  /** Python's `ensure_ascii`; defaults to `true`, like Python. */
  ensureAscii?: boolean;
}

/** Python sorts keys by code point; `Array.prototype.sort` uses UTF-16 code
 *  units. They differ above the BMP, so compare code points explicitly. */
function compareCodePoints(a: string, b: string): number {
  const aPoints = [...a];
  const bPoints = [...b];
  const shared = Math.min(aPoints.length, bPoints.length);
  for (let i = 0; i < shared; i += 1) {
    const ax = (aPoints[i] ?? '').codePointAt(0) ?? 0;
    const bx = (bPoints[i] ?? '').codePointAt(0) ?? 0;
    if (ax !== bx) {
      return ax - bx;
    }
  }
  return aPoints.length - bPoints.length;
}

/** Python escapes U+007F too, not just U+0080 and above. */
function escapeNonAscii(json: string): string {
  return json.replace(
    /[\u007f-\uffff]/g,
    (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`,
  );
}

function emitString(value: string, ensureAscii: boolean): string {
  const json = JSON.stringify(value);
  return ensureAscii ? escapeNonAscii(json) : json;
}

function emitNumber(value: number): string {
  if (Number.isNaN(value)) {
    return 'NaN';
  }
  if (value === Number.POSITIVE_INFINITY) {
    return 'Infinity';
  }
  if (value === Number.NEGATIVE_INFINITY) {
    return '-Infinity';
  }
  if (Number.isInteger(value)) {
    return String(value);
  }
  // Python's repr pads the exponent to two digits: 1e-7 -> 1e-07.
  return String(value).replace(/e([+-])(\d)$/, 'e$10$2');
}

interface EmitContext {
  indent: number | undefined;
  sortKeys: boolean;
  ensureAscii: boolean;
  seen: Set<object>;
}

function unwrap(value: unknown): unknown {
  if (value !== null && typeof value === 'object') {
    const candidate = (value as { toJSON?: unknown }).toJSON;
    if (typeof candidate === 'function') {
      return (candidate as (this: unknown) => unknown).call(value);
    }
  }
  return value;
}

function emit(raw: unknown, level: number, ctx: EmitContext): string {
  const value = unwrap(raw);

  if (value === null) {
    return 'null';
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false';
  }
  if (typeof value === 'number') {
    return emitNumber(value);
  }
  if (typeof value === 'bigint') {
    return value.toString();
  }
  if (typeof value === 'string') {
    return emitString(value, ctx.ensureAscii);
  }
  if (typeof value !== 'object') {
    // undefined, function, symbol — JSON.stringify drops these; so do we.
    return 'null';
  }

  if (ctx.seen.has(value)) {
    throw new TypeError('pyJsonDump: circular structure cannot be serialised');
  }
  ctx.seen.add(value);
  try {
    const pad = ctx.indent === undefined ? '' : ' '.repeat(ctx.indent * (level + 1));
    const closePad = ctx.indent === undefined ? '' : ' '.repeat(ctx.indent * level);
    const open = ctx.indent === undefined ? '' : '\n';
    const separator = ctx.indent === undefined ? ', ' : `,\n${pad}`;
    const close = ctx.indent === undefined ? '' : `\n${closePad}`;

    if (Array.isArray(value)) {
      if (value.length === 0) {
        return '[]';
      }
      // `undefined`/functions inside an array become `null`, as in JSON.stringify
      // and as in Python (which has no such values to begin with).
      const items = value.map((item) => emit(item, level + 1, ctx));
      return `[${open}${pad}${items.join(separator)}${close}]`;
    }

    const entries = Object.entries(value as Record<string, unknown>).filter(
      ([, v]) => unwrap(v) !== undefined && typeof unwrap(v) !== 'function',
    );
    if (ctx.sortKeys) {
      entries.sort(([a], [b]) => compareCodePoints(a, b));
    }
    if (entries.length === 0) {
      return '{}';
    }
    const items = entries.map(
      ([key, item]) => `${emitString(key, ctx.ensureAscii)}: ${emit(item, level + 1, ctx)}`,
    );
    return `{${open}${pad}${items.join(separator)}${close}}`;
  } finally {
    ctx.seen.delete(value);
  }
}

/**
 * Serialise `value` the way Python's `json.dumps` would.
 *
 * `pyJsonDump(v, { indent: 2, sortKeys: true, ensureAscii: true })` is the
 * exact call the ledger and the `.cms/distribution/` writers use; the Python
 * lane's counterpart is `json.dump(v, f, indent=2, sort_keys=True)` plus a
 * trailing newline, which callers add themselves.
 */
export function pyJsonDump(value: unknown, opts: PyJsonOptions = {}): string {
  const ctx: EmitContext = {
    indent: opts.indent,
    sortKeys: opts.sortKeys ?? false,
    ensureAscii: opts.ensureAscii ?? true,
    seen: new Set<object>(),
  };
  return emit(value, 0, ctx);
}
