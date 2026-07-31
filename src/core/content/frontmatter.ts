/**
 * Reading a front-matter block: which dialect a file uses, where the block
 * starts and stops, and what its keys mean.
 *
 * This is the deliberate, documented cost of decision D3 (zero runtime
 * dependencies): a hand-rolled YAML *subset* instead of js-yaml. The subset is
 * chosen from what content front matter actually contains, and the parser is
 * tolerant by construction — a malformed block degrades to "no front matter" or
 * to "these keys, minus the ones I could not read". It never throws, because
 * the panel renders on every keystroke of a file somebody is mid-edit.
 *
 * Two rules matter more than everything else here:
 *
 *   1. **Dates stay strings.** Nothing in this file constructs a `Date`.
 *      Round-tripping `2026-07-31` through a JS `Date` is how a CMS silently
 *      rewrites every date in a repository to a timezone-shifted timestamp.
 *   2. **The dialect comes from the file, not from configuration.**
 *      `detectFormat` looks at the leading characters (`---`, `+++`, `{`). A
 *      workspace whose `zer0.json` says `frontMatter.format: "yaml"` still
 *      reads its one TOML file correctly; that key only decides what *new*
 *      blocks look like. It is a `zer0.json` key, not a VS Code setting.
 *
 * ## The YAML subset — what is supported
 *
 * - Scalars, quoted (`"…"`, `'…'`) and plain, with coercion (below).
 * - Nested mappings to any depth, by indentation.
 * - Block sequences, indented or at the parent's own indentation, including
 *   sequences of mappings (`- name: a` / `  role: b`).
 * - Flow sequences (`[a, b]`) and flow mappings (`{a: 1, b: 2}`) on one line,
 *   nested, with quoted commas handled correctly.
 * - Block scalars: `|`, `>`, all chomping indicators (`-`, `+`) and an explicit
 *   indentation indicator (`|2`).
 * - `#` comments (at line start and after a value), blank lines, CRLF, a BOM.
 * - Duplicate keys: last one wins.
 * - Quoted-string escapes: `\\ \" \/ \n \r \t \b \f` in double quotes and `''`
 *   in single quotes. `\uXXXX`, `\xNN` and octal escapes are **not** decoded —
 *   they survive as the literal characters that were written.
 *
 * ## What is NOT supported, and what happens instead
 *
 * | Construct | Result |
 * |---|---|
 * | Anchors, aliases, merge keys (`&a`, `*a`, `<<:`) | Kept as the literal string (`"*base"`); never resolved. |
 * | Tags (`!!str`, `!Custom`) | Kept as part of the literal string value. |
 * | Multi-document (`---` inside, `...`) | Unreachable — the second `---` closes the block. A `...` line is skipped. |
 * | Complex keys (`? key` / `: value`) | The lines are skipped; the key is absent from the result. |
 * | Multi-line flow collections | The value is the literal first line; the continuation lines are skipped. |
 * | Multi-line plain scalars (a value continued on an indented line) | Only the first line is read; the continuation lines are skipped. |
 * | Sequences at the document root | Skipped — front matter must be a mapping. |
 *
 * In every one of those cases the *raw text is untouched on disk*: nothing in
 * this file writes, and `serialize.ts` rewrites only the lines of keys the user
 * actually changed. A construct we cannot read is a construct we cannot
 * corrupt.
 *
 * ## Scalar coercion
 *
 * `true`/`false` (and `True`/`TRUE`) → boolean. `null`/`~` (and `Null`/`NULL`,
 * and an empty value) → `null`. Integers and decimals → number. Everything
 * else stays a string, including:
 *
 * - `yes` / `no` / `on` / `off` — YAML 1.1 booleans, but a field whose value is
 *   the *word* "no" is far more common in prose than a YAML 1.1 purist,
 * - zero-padded integers (`007`) — an id, not the number seven,
 * - integers beyond `Number.MAX_SAFE_INTEGER` — coercing would lose digits,
 * - anything date-shaped, per rule 1 above.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Every value a front-matter block can hold, after coercion. */
export type FmValue = string | number | boolean | null | FmValue[] | { [key: string]: FmValue };

/** A parsed front-matter block. Keys are in file order; duplicates: last wins. */
export type FrontMatter = Record<string, FmValue>;

export type FmFormat = 'yaml' | 'toml' | 'json';

export interface FmBlock {
  format: FmFormat;
  /** The block body with the fences excluded and no trailing newline. */
  raw: string;
  /** Character offset of the opening fence (past a BOM, if any). */
  start: number;
  /** Character offset just past the closing fence and its newline. */
  end: number;
  data: FrontMatter;
}

const YAML_FENCE = '---';
const TOML_FENCE = '+++';
const BOM = 0xfeff;

// ---------------------------------------------------------------------------
// Splitting the block out of a file
// ---------------------------------------------------------------------------

/**
 * Which dialect the file's front matter is written in, decided by its leading
 * characters. Returns `yaml` for a file with no front matter at all — the
 * dialect is a guess about *notation*, not a claim that a block exists.
 * `splitFrontMatter` is what decides whether there is one.
 */
export function detectFormat(text: string): FmFormat {
  const at = text.charCodeAt(0) === BOM ? 1 : 0;
  if (text.startsWith(TOML_FENCE, at)) {
    return 'toml';
  }
  if (text.charAt(at) === '{') {
    return 'json';
  }
  return 'yaml';
}

/**
 * Locate and parse the front-matter block. A file with no block, an unclosed
 * fence, or an unparseable body all return `{ block: null, body: text }` —
 * "this file has no front matter" is a normal answer, not an error.
 */
export function splitFrontMatter(text: string): { block: FmBlock | null; body: string } {
  if (text.length === 0) {
    return { block: null, body: text };
  }
  const offset = text.charCodeAt(0) === BOM ? 1 : 0;
  const format = detectFormat(text);
  if (format === 'json') {
    return splitJsonBlock(text, offset);
  }
  return splitFencedBlock(text, offset, format === 'toml' ? TOML_FENCE : YAML_FENCE, format);
}

/** End (exclusive) and start-of-next-line offsets for the line beginning at `from`. */
function lineBounds(text: string, from: number): { end: number; next: number } {
  const newline = text.indexOf('\n', from);
  if (newline === -1) {
    return { end: text.length, next: text.length };
  }
  return { end: newline, next: newline + 1 };
}

function dropTrailingNewline(value: string): string {
  if (value.endsWith('\r\n')) {
    return value.slice(0, -2);
  }
  if (value.endsWith('\n')) {
    return value.slice(0, -1);
  }
  return value;
}

function splitFencedBlock(
  text: string,
  offset: number,
  fence: string,
  format: FmFormat,
): { block: FmBlock | null; body: string } {
  const opening = lineBounds(text, offset);
  // `line.trim() === fence` also rejects `----`, which is a setext rule in a
  // markdown file that happens to start with one, not a front-matter fence.
  if (text.slice(offset, opening.end).trim() !== fence) {
    return { block: null, body: text };
  }

  let cursor = opening.next;
  while (cursor < text.length) {
    const line = lineBounds(text, cursor);
    if (text.slice(cursor, line.end).trim() === fence) {
      const raw = dropTrailingNewline(text.slice(opening.next, cursor));
      const block: FmBlock = {
        format,
        raw,
        start: offset,
        end: line.next,
        data: parseFrontMatterBlock(raw, format),
      };
      return { block, body: text.slice(line.next) };
    }
    if (line.next === cursor) {
      break;
    }
    cursor = line.next;
  }
  return { block: null, body: text };
}

/** Hugo-style JSON front matter: a bare object at the very top of the file. */
function splitJsonBlock(text: string, offset: number): { block: FmBlock | null; body: string } {
  const close = matchingBrace(text, offset);
  if (close < 0) {
    return { block: null, body: text };
  }
  const raw = text.slice(offset, close + 1);
  let end = close + 1;
  if (text.startsWith('\r\n', end)) {
    end += 2;
  } else if (text.charAt(end) === '\n') {
    end += 1;
  }
  const block: FmBlock = { format: 'json', raw, start: offset, end, data: parseFrontMatterBlock(raw, 'json') };
  return { block, body: text.slice(end) };
}

/** Offset of the `}` closing the `{` at `from`, or -1 when unbalanced. */
function matchingBrace(text: string, from: number): number {
  let depth = 0;
  let quoted = false;
  for (let i = from; i < text.length; i++) {
    const ch = text.charAt(i);
    if (quoted) {
      if (ch === '\\') {
        i++;
      } else if (ch === '"') {
        quoted = false;
      }
      continue;
    }
    if (ch === '"') {
      quoted = true;
    } else if (ch === '{') {
      depth++;
    } else if (ch === '}') {
      depth--;
      if (depth === 0) {
        return i;
      }
    }
  }
  return -1;
}

/**
 * Parse a block body in the given dialect. Never throws: an unreadable block
 * yields `{}` so the caller sees "no keys" rather than an exception during a
 * panel render.
 */
export function parseFrontMatterBlock(raw: string, format: FmFormat): FrontMatter {
  try {
    if (format === 'toml') {
      return parseTomlFlat(raw);
    }
    if (format === 'json') {
      return parseJsonBlock(raw);
    }
    return parseYamlSubset(raw);
  } catch {
    // Deliberately swallowed. The parsers below are written not to throw, so
    // reaching here means an input pathological enough that "this file has no
    // readable front matter" is the only honest answer we can give a UI that
    // has to render something. The file itself is never modified as a result.
    return {};
  }
}

function isPlainObject(value: unknown): value is Record<string, FmValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseJsonBlock(raw: string): FrontMatter {
  const parsed: unknown = JSON.parse(raw);
  return isPlainObject(parsed) ? { ...parsed } : {};
}

// ---------------------------------------------------------------------------
// Shared scalar scanning
// ---------------------------------------------------------------------------

/**
 * Offset of the quote closing the one at `from`, or -1 when unterminated.
 * Understands `\"` inside double quotes and `''` inside single quotes.
 */
function closingQuote(text: string, from: number): number {
  const quote = text.charAt(from);
  for (let i = from + 1; i < text.length; i++) {
    const ch = text.charAt(i);
    if (quote === '"' && ch === '\\') {
      i++;
      continue;
    }
    if (ch !== quote) {
      continue;
    }
    if (quote === "'" && text.charAt(i + 1) === "'") {
      i++;
      continue;
    }
    return i;
  }
  return -1;
}

const DOUBLE_ESCAPES: Readonly<Record<string, string>> = {
  '\\': '\\',
  '"': '"',
  '/': '/',
  n: '\n',
  r: '\r',
  t: '\t',
  b: '\b',
  f: '\f',
};

/** Strip the surrounding quotes of `text` and decode the escapes we support. */
function unquote(text: string): string {
  const quote = text.charAt(0);
  const inner = text.slice(1, -1);
  if (quote === "'") {
    return inner.split("''").join("'");
  }
  let out = '';
  for (let i = 0; i < inner.length; i++) {
    const ch = inner.charAt(i);
    if (ch !== '\\') {
      out += ch;
      continue;
    }
    const next = inner.charAt(i + 1);
    const decoded = DOUBLE_ESCAPES[next];
    if (decoded === undefined) {
      // An escape we do not decode (`\uXXXX`, `\xNN`, octal) survives verbatim,
      // which is the documented behaviour — better a visible backslash than a
      // wrong character.
      out += ch;
      continue;
    }
    out += decoded;
    i++;
  }
  return out;
}

/**
 * Remove a trailing `#` comment from a value. A `#` only opens a comment when
 * it is outside quotes and flow brackets and preceded by whitespace, so
 * `url: http://x/#anchor` and `title: "a # b"` both survive intact.
 */
function stripComment(value: string): string {
  let depth = 0;
  let quote = '';
  for (let i = 0; i < value.length; i++) {
    const ch = value.charAt(i);
    if (quote !== '') {
      if (quote === '"' && ch === '\\') {
        i++;
      } else if (ch === quote) {
        if (quote === "'" && value.charAt(i + 1) === "'") {
          i++;
        } else {
          quote = '';
        }
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '[' || ch === '{') {
      depth++;
      continue;
    }
    if ((ch === ']' || ch === '}') && depth > 0) {
      depth--;
      continue;
    }
    if (ch === '#' && depth === 0 && (i === 0 || /\s/.test(value.charAt(i - 1)))) {
      return value.slice(0, i).trimEnd();
    }
  }
  return value.trimEnd();
}

const INTEGER_RE = /^[-+]?\d+$/;
const DECIMAL_RE = /^[-+]?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?$|^[-+]?\d+[eE][-+]?\d+$/;

/** Number coercion, or `null` when the text should stay a string. */
function toNumber(value: string): number | null {
  if (INTEGER_RE.test(value)) {
    const digits = value.replace(/^[-+]/, '');
    if (digits.length > 1 && digits.startsWith('0')) {
      return null; // `007` is an identifier, not seven.
    }
    const parsed = Number(value);
    return Number.isSafeInteger(parsed) ? parsed : null;
  }
  if (DECIMAL_RE.test(value)) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** Coerce one plain or quoted scalar. Never throws; never builds a `Date`. */
function parseScalar(text: string): FmValue {
  const value = text.trim();
  if (value.length === 0) {
    return '';
  }
  const first = value.charAt(0);
  if (first === '"' || first === "'") {
    const close = closingQuote(value, 0);
    if (close > 0) {
      // Anything after the closing quote is malformed YAML; drop it rather
      // than guess what the author meant.
      return unquote(value.slice(0, close + 1));
    }
    return value; // unterminated quote → the literal text
  }
  if (value === '~' || value === 'null' || value === 'Null' || value === 'NULL') {
    return null;
  }
  if (value === 'true' || value === 'True' || value === 'TRUE') {
    return true;
  }
  if (value === 'false' || value === 'False' || value === 'FALSE') {
    return false;
  }
  return toNumber(value) ?? value;
}

// ---------------------------------------------------------------------------
// Flow collections
// ---------------------------------------------------------------------------

/** Offset of the `]`/`}` closing the bracket at `from`, or -1 when unbalanced. */
function closingBracket(text: string, from: number): number {
  const open = text.charAt(from);
  const close = open === '[' ? ']' : '}';
  let depth = 0;
  let quote = '';
  for (let i = from; i < text.length; i++) {
    const ch = text.charAt(i);
    if (quote !== '') {
      if (quote === '"' && ch === '\\') {
        i++;
      } else if (ch === quote) {
        quote = '';
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === open) {
      depth++;
      continue;
    }
    if (ch === close) {
      depth--;
      if (depth === 0) {
        return i;
      }
    }
  }
  return -1;
}

/** Split flow-collection contents on top-level commas, respecting quotes. */
function splitFlow(inner: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let quote = '';
  let start = 0;
  for (let i = 0; i < inner.length; i++) {
    const ch = inner.charAt(i);
    if (quote !== '') {
      if (quote === '"' && ch === '\\') {
        i++;
      } else if (ch === quote) {
        quote = '';
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '[' || ch === '{') {
      depth++;
      continue;
    }
    if (ch === ']' || ch === '}') {
      depth--;
      continue;
    }
    if (ch === ',' && depth === 0) {
      parts.push(inner.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(inner.slice(start));
  return parts.map((part) => part.trim()).filter((part) => part.length > 0);
}

function parseFlowValue(text: string): FmValue {
  const value = text.trim();
  if (value.startsWith('[')) {
    const close = closingBracket(value, 0);
    if (close < 0) {
      return value; // multi-line flow sequence → the literal first line
    }
    const inner = value.slice(1, close).trim();
    return inner.length === 0 ? [] : splitFlow(inner).map(parseFlowValue);
  }
  if (value.startsWith('{')) {
    const close = closingBracket(value, 0);
    if (close < 0) {
      return value;
    }
    const inner = value.slice(1, close).trim();
    const map: FrontMatter = {};
    if (inner.length === 0) {
      return map;
    }
    for (const part of splitFlow(inner)) {
      const pair = splitFlowPair(part);
      map[pair.key] = pair.rest === null ? null : parseFlowValue(pair.rest);
    }
    return map;
  }
  return parseScalar(value);
}

/** `a: 1` inside a flow mapping. Unlike block context, `a:1` is accepted too. */
function splitFlowPair(part: string): { key: string; rest: string | null } {
  const text = part.trim();
  if (text.charAt(0) === '"' || text.charAt(0) === "'") {
    const close = closingQuote(text, 0);
    if (close > 0) {
      const after = text.slice(close + 1).trimStart();
      const key = unquote(text.slice(0, close + 1));
      return after.startsWith(':') ? { key, rest: after.slice(1).trim() } : { key, rest: null };
    }
  }
  const colon = text.indexOf(':');
  if (colon < 0) {
    return { key: text, rest: null };
  }
  return { key: text.slice(0, colon).trim(), rest: text.slice(colon + 1).trim() };
}

// ---------------------------------------------------------------------------
// The YAML subset parser
// ---------------------------------------------------------------------------

interface YamlLine {
  /** The line with any trailing CR removed. */
  text: string;
  /** Count of leading space/tab characters. */
  indent: number;
  /** `text` with its indentation removed. */
  content: string;
  blank: boolean;
  comment: boolean;
}

/** A shared read position, so the recursive parsers advance one cursor. */
interface Cursor {
  i: number;
}

function makeLine(content: string, indent: number): YamlLine {
  return {
    text: ' '.repeat(indent) + content,
    indent,
    content,
    blank: content.length === 0,
    comment: content.startsWith('#'),
  };
}

function toLines(raw: string): YamlLine[] {
  return raw.split('\n').map((line) => {
    const text = line.endsWith('\r') ? line.slice(0, -1) : line;
    let indent = 0;
    while (indent < text.length) {
      const ch = text.charAt(indent);
      if (ch !== ' ' && ch !== '\t') {
        break;
      }
      indent++;
    }
    const content = text.slice(indent);
    return { text, indent, content, blank: content.length === 0, comment: content.startsWith('#') };
  });
}

/**
 * Split a block-context `key: value` line. Returns `null` when the line is not
 * a key line (a sequence item, a comment, a continuation, a complex key).
 *
 * Exported because `serialize.ts` locates the line range of a key with exactly
 * the same rule the parser uses — if the two ever disagreed, line surgery would
 * rewrite the wrong lines.
 */
export function parseYamlKeyLine(content: string): { key: string; rest: string } | null {
  if (content.length === 0 || content.startsWith('#') || isYamlSequenceItem(content)) {
    return null;
  }
  const first = content.charAt(0);
  if (first === '"' || first === "'") {
    const close = closingQuote(content, 0);
    if (close < 0) {
      return null;
    }
    const after = content.slice(close + 1);
    if (!after.startsWith(':')) {
      return null;
    }
    const rest = after.slice(1);
    if (rest.length > 0 && rest.charAt(0) !== ' ' && rest.charAt(0) !== '\t') {
      return null;
    }
    return { key: unquote(content.slice(0, close + 1)), rest: rest.trim() };
  }
  for (let i = 0; i < content.length; i++) {
    if (content.charAt(i) !== ':') {
      continue;
    }
    const next = content.charAt(i + 1);
    if (i + 1 !== content.length && next !== ' ' && next !== '\t') {
      continue;
    }
    const key = content.slice(0, i).trim();
    if (key.length === 0 || / #/.test(key)) {
      return null;
    }
    return { key, rest: content.slice(i + 1).trim() };
  }
  return null;
}

/** Whether a line's content opens a block-sequence item. */
export function isYamlSequenceItem(content: string): boolean {
  return content === '-' || content.startsWith('- ') || content.startsWith('-\t');
}

function skipIgnorable(lines: YamlLine[], cur: Cursor): void {
  while (cur.i < lines.length) {
    const line = lines[cur.i];
    if (line === undefined || !(line.blank || line.comment)) {
      return;
    }
    cur.i++;
  }
}

function peekSignificant(lines: YamlLine[], from: number): { line: YamlLine; index: number } | null {
  for (let i = from; i < lines.length; i++) {
    const line = lines[i];
    if (line === undefined) {
      continue;
    }
    if (!line.blank && !line.comment) {
      return { line, index: i };
    }
  }
  return null;
}

const BLOCK_SCALAR_RE = /^[|>](?:[+-]?\d*|\d*[+-]?)$/;

/**
 * Parse the value that follows `key:` (or `-`), consuming any continuation
 * lines that belong to it.
 */
function readValue(lines: YamlLine[], cur: Cursor, parentIndent: number, rest: string): FmValue {
  const text = stripComment(rest);

  if (text.length === 0) {
    const next = peekSignificant(lines, cur.i);
    if (next === null) {
      return null;
    }
    // A block sequence may sit at its parent's own indentation, which is why
    // this is `>=` for sequences but `>` for nested mappings.
    if (next.line.indent >= parentIndent && isYamlSequenceItem(next.line.content)) {
      cur.i = next.index;
      return parseSequence(lines, cur, next.line.indent);
    }
    if (next.line.indent > parentIndent && parseYamlKeyLine(next.line.content) !== null) {
      cur.i = next.index;
      return parseMapping(lines, cur, next.line.indent);
    }
    return null;
  }

  if (BLOCK_SCALAR_RE.test(text)) {
    return parseBlockScalar(lines, cur, parentIndent, text);
  }
  if (text.startsWith('[') || text.startsWith('{')) {
    return parseFlowValue(text);
  }
  return parseScalar(text);
}

function parseMapping(lines: YamlLine[], cur: Cursor, indent: number): FrontMatter {
  const map: FrontMatter = {};
  while (cur.i < lines.length) {
    skipIgnorable(lines, cur);
    const line = lines[cur.i];
    if (line === undefined || line.indent < indent) {
      break;
    }
    const pair = parseYamlKeyLine(line.content);
    if (pair === null || line.indent > indent) {
      if (line.indent > indent) {
        // A continuation line, an over-indented key, or a construct from the
        // "not supported" table. Skipping keeps the enclosing mapping intact.
        cur.i++;
        continue;
      }
      break;
    }
    cur.i++;
    map[pair.key] = readValue(lines, cur, line.indent, pair.rest);
  }
  return map;
}

function parseSequence(lines: YamlLine[], cur: Cursor, indent: number): FmValue[] {
  const items: FmValue[] = [];
  while (cur.i < lines.length) {
    skipIgnorable(lines, cur);
    const line = lines[cur.i];
    if (line === undefined || line.indent !== indent || !isYamlSequenceItem(line.content)) {
      break;
    }
    const after = line.content.slice(1);
    const rest = after.trim();
    const restColumn = indent + 1 + (after.length - after.trimStart().length);
    cur.i++;

    if (rest.length === 0) {
      const next = peekSignificant(lines, cur.i);
      if (next !== null && next.line.indent > indent) {
        cur.i = next.index;
        items.push(
          isYamlSequenceItem(next.line.content)
            ? parseSequence(lines, cur, next.line.indent)
            : parseMapping(lines, cur, next.line.indent),
        );
      } else {
        items.push(null);
      }
      continue;
    }

    if (parseYamlKeyLine(rest) !== null) {
      // `- name: a` opens a mapping whose keys are aligned to the column the
      // first key starts at. Re-indenting the line in this local copy lets the
      // ordinary mapping parser handle it — `lines` is built fresh per parse,
      // so the rewrite is invisible outside this call.
      lines[cur.i - 1] = makeLine(rest, restColumn);
      cur.i--;
      items.push(parseMapping(lines, cur, restColumn));
      continue;
    }

    items.push(readValue(lines, cur, indent, rest));
  }
  return items;
}

function parseBlockScalar(lines: YamlLine[], cur: Cursor, parentIndent: number, header: string): string {
  const folded = header.charAt(0) === '>';
  const modifiers = header.slice(1);
  const chomp = modifiers.includes('-') ? 'strip' : modifiers.includes('+') ? 'keep' : 'clip';
  const explicit = /(\d+)/.exec(modifiers)?.[1];
  let contentIndent = explicit === undefined ? -1 : parentIndent + Number(explicit);

  const collected: string[] = [];
  while (cur.i < lines.length) {
    const line = lines[cur.i];
    if (line === undefined) {
      break;
    }
    if (line.blank) {
      collected.push('');
      cur.i++;
      continue;
    }
    if (line.indent <= parentIndent) {
      break;
    }
    if (contentIndent < 0) {
      contentIndent = line.indent;
    }
    if (line.indent < contentIndent) {
      break;
    }
    collected.push(line.text.slice(contentIndent));
    cur.i++;
  }

  // Blank lines trailing the block belong to whatever follows it, so hand them
  // back to the caller and let chomping decide how many newlines they mean.
  let trailingBlanks = 0;
  while (collected.length > 0 && collected[collected.length - 1] === '') {
    collected.pop();
    trailingBlanks++;
  }
  cur.i -= trailingBlanks;

  const body = folded ? foldLines(collected) : collected.join('\n');
  if (chomp === 'strip' || body.length === 0) {
    return body;
  }
  return chomp === 'keep' ? body + '\n'.repeat(trailingBlanks + 1) : body + '\n';
}

/** Folded (`>`) joining: line breaks become spaces, blank lines become breaks. */
function foldLines(collected: readonly string[]): string {
  let out = '';
  let pending = false;
  for (const line of collected) {
    if (line.length === 0) {
      out += '\n';
      pending = false;
      continue;
    }
    if (pending) {
      out += ' ';
    }
    out += line;
    pending = true;
  }
  return out;
}

/**
 * Parse a YAML-subset front-matter body. Front matter is a mapping, so a
 * document-level sequence or scalar yields `{}`. Never throws.
 */
export function parseYamlSubset(raw: string): FrontMatter {
  const lines = toLines(raw);
  const cur: Cursor = { i: 0 };
  const data: FrontMatter = {};
  while (cur.i < lines.length) {
    const before = cur.i;
    Object.assign(data, parseMapping(lines, cur, 0));
    if (cur.i === before) {
      // parseMapping refused this line (a root-level sequence item, a `...`
      // document end, a complex key). Step over it and keep reading.
      cur.i++;
    }
  }
  return data;
}

// ---------------------------------------------------------------------------
// Flat TOML
// ---------------------------------------------------------------------------

/**
 * A small TOML reader for front matter: `key = value` pairs, `[table]` and
 * `[a.b]` headers, dotted keys, inline arrays and tables, multi-line basic
 * strings, and `#` comments.
 *
 * Not supported: `[[array-of-tables]]` (read as a plain `[table]`), multi-line
 * literal strings (`'''`), and date coercion — per the module rule, dates stay
 * strings. Nothing here throws.
 */
export function parseTomlFlat(raw: string): FrontMatter {
  const root: FrontMatter = {};
  let table: FrontMatter = root;
  const lines = raw.split('\n').map((line) => (line.endsWith('\r') ? line.slice(0, -1) : line));

  for (let i = 0; i < lines.length; i++) {
    const line = (lines[i] ?? '').trim();
    if (line.length === 0 || line.startsWith('#')) {
      continue;
    }

    if (line.startsWith('[')) {
      const close = line.lastIndexOf(']');
      if (close <= 0) {
        continue;
      }
      const arrayTable = line.startsWith('[[');
      const name = line.slice(arrayTable ? 2 : 1, arrayTable && close > 1 ? close - 1 : close).trim();
      const path = splitTomlKey(name);
      table = path.length === 0 ? root : descend(root, path);
      continue;
    }

    const eq = tomlAssignmentAt(line);
    if (eq < 0) {
      continue;
    }
    const path = splitTomlKey(line.slice(0, eq));
    const leaf = path[path.length - 1];
    if (leaf === undefined) {
      continue;
    }
    let text = line.slice(eq + 1).trim();

    if (text.startsWith('"""')) {
      const chunk: string[] = [text.slice(3)];
      while (!chunk.join('\n').includes('"""') && i + 1 < lines.length) {
        i++;
        chunk.push(lines[i] ?? '');
      }
      const joined = chunk.join('\n');
      const end = joined.indexOf('"""');
      const container = path.length > 1 ? descend(table, path.slice(0, -1)) : table;
      container[leaf] = end < 0 ? joined : joined.slice(0, end);
      continue;
    }

    // An inline array may wrap across lines; join until the brackets balance.
    while (text.startsWith('[') && closingBracket(text, 0) < 0 && i + 1 < lines.length) {
      i++;
      text += ' ' + (lines[i] ?? '').trim();
    }

    const container = path.length > 1 ? descend(table, path.slice(0, -1)) : table;
    container[leaf] = parseFlowValue(stripComment(text));
  }
  return root;
}

/** Index of the `=` that separates a TOML key from its value, or -1. */
function tomlAssignmentAt(line: string): number {
  let quote = '';
  for (let i = 0; i < line.length; i++) {
    const ch = line.charAt(i);
    if (quote !== '') {
      if (quote === '"' && ch === '\\') {
        i++;
      } else if (ch === quote) {
        quote = '';
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '=') {
      return i;
    }
  }
  return -1;
}

/** `a.b."c.d"` → `['a', 'b', 'c.d']`. */
function splitTomlKey(name: string): string[] {
  const parts: string[] = [];
  let current = '';
  let quote = '';
  for (let i = 0; i < name.length; i++) {
    const ch = name.charAt(i);
    if (quote !== '') {
      if (ch === quote) {
        quote = '';
      } else {
        current += ch;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '.') {
      parts.push(current.trim());
      current = '';
      continue;
    }
    current += ch;
  }
  parts.push(current.trim());
  return parts.filter((part) => part.length > 0);
}

/** Walk (creating as needed) to the nested map at `path`. */
function descend(root: FrontMatter, path: readonly string[]): FrontMatter {
  let node = root;
  for (const segment of path) {
    const existing = node[segment];
    if (isPlainObject(existing)) {
      node = existing;
      continue;
    }
    const created: FrontMatter = {};
    node[segment] = created;
    node = created;
  }
  return node;
}

// ---------------------------------------------------------------------------
// Reading values back out
// ---------------------------------------------------------------------------

/** A front-matter value as a string. Collections and `null` give `fallback`. */
export function asString(value: FmValue | undefined, fallback = ''): string {
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return fallback;
}

/**
 * A front-matter value as a list of strings. A lone scalar becomes a
 * single-item list, because `tags: draft` and `tags: [draft]` mean the same
 * thing to every static-site generator. Splitting a comma-separated *string*
 * into items is a field-level concern driven by
 * `frontMatter.commaSeparatedFields` — see `serialize.applyCommaSeparatedFields`.
 */
export function asList(value: FmValue | undefined): string[] {
  if (Array.isArray(value)) {
    const out: string[] = [];
    for (const item of value) {
      if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean') {
        out.push(String(item));
      }
    }
    return out;
  }
  if (typeof value === 'string') {
    return value.length === 0 ? [] : [value];
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return [String(value)];
  }
  return [];
}

const TRUTHY = new Set(['true', 'yes', 'y', '1', 'on']);

/** A front-matter value as a boolean. Anything unrecognised is `false`. */
export function asBool(value: FmValue | undefined): boolean {
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'number') {
    return value !== 0;
  }
  if (typeof value === 'string') {
    return TRUTHY.has(value.trim().toLowerCase());
  }
  return false;
}
