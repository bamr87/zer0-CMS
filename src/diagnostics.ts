/**
 * Required-field diagnostics, drawn inside the front-matter block.
 *
 * Two rules define this file.
 *
 * **One: the range is always inside the block.** A squiggle under a paragraph
 * of prose because `description` is missing from the front matter is worse
 * than no squiggle at all — it points at the wrong thing and it moves as the
 * author types. Every range here is clamped to the lines between the fences,
 * and when the key does not exist yet the diagnostic lands on the line where it
 * would be written.
 *
 * **Two: SEO is not a diagnostic.** Title length, description length and
 * keyword density are *advice*, and advice belongs in the panel, where it can
 * be read, weighed and ignored. Upstream put them in the Problems panel next to
 * compiler errors, which trained everyone to ignore the Problems panel. What
 * lands here is only what a content type declares `required` — a schema
 * violation, the same class of thing as a missing field in a JSON schema.
 */

import * as vscode from 'vscode';

import {
  isSupported,
  parseYamlKeyLine,
  resolveContentType,
  splitFrontMatter,
  validateFields,
  type FieldViolation,
  type FmBlock,
  type FmFormat,
  type LogSink,
  type Zer0Config,
} from './core';
import { affectsUs, currentConfig } from './config';
import { describeError, log as sharedLog } from './logger';

/** Shown in the Problems panel's "source" column. */
export const DIAGNOSTIC_SOURCE = 'zer0-CMS';

/** The one code this file emits. Quick-fix providers can key off it. */
export const REQUIRED_FIELD_CODE = 'zer0Cms.requiredField';

/** Typing pause before re-validating, so a keystroke is not a full re-parse. */
const DEBOUNCE_MS = 400;

// ---------------------------------------------------------------------------
// Locating a key inside the block
// ---------------------------------------------------------------------------

interface KeyLine {
  line: number;
  /** Column the key token starts at. */
  column: number;
  /** Length of the key token as written, quotes included. */
  length: number;
  /** Leading-whitespace width, used to decide what nests under what. */
  indent: number;
}

const TOML_KEY = /^(\s*)([A-Za-z0-9_.-]+)\s*=/;
const JSON_KEY = /^(\s*)("(?:[^"\\]|\\.)*")\s*:/;

/** The key this line declares, or `undefined` when it declares none. */
function keyOnLine(text: string, format: FmFormat): KeyLine | undefined {
  if (format === 'toml') {
    const match = TOML_KEY.exec(text);
    if (match === null) {
      return undefined;
    }
    const indent = match[1] ?? '';
    const key = match[2] ?? '';
    return { line: 0, column: indent.length, length: key.length, indent: indent.length };
  }
  if (format === 'json') {
    const match = JSON_KEY.exec(text);
    if (match === null) {
      return undefined;
    }
    const indent = match[1] ?? '';
    const token = match[2] ?? '';
    return { line: 0, column: indent.length, length: token.length, indent: indent.length };
  }
  // YAML: reuse the parser's own rule. If this file and the parser ever
  // disagreed about what a key line is, the squiggle would land on a line the
  // parser never read.
  const indent = text.length - text.trimStart().length;
  const content = text.slice(indent).trimEnd();
  const parsed = parseYamlKeyLine(content);
  if (parsed === null) {
    return undefined;
  }
  // `parseYamlKeyLine` unquotes; the written token may be longer than the key.
  const written = content.startsWith('"') || content.startsWith("'") ? parsed.key.length + 2 : parsed.key.length;
  return { line: 0, column: indent, length: written, indent };
}

/** Inclusive line range that holds the block's *content*, fences excluded. */
function innerLines(document: vscode.TextDocument, block: FmBlock): { first: number; last: number } {
  const startLine = document.positionAt(block.start).line;
  const endLine = document.positionAt(Math.max(block.start, block.end - 1)).line;
  if (block.format === 'json') {
    // A JSON block has no fence lines to skip; the braces are the block.
    return { first: startLine, last: endLine };
  }
  const first = Math.min(startLine + 1, endLine);
  return { first, last: Math.max(first, endLine - 1) };
}

/** Last line that nests under a key opened at `indent` on `line`. */
function lastChildLine(
  document: vscode.TextDocument,
  line: number,
  indent: number,
  limit: number,
): number {
  let last = line;
  for (let i = line + 1; i <= limit; i++) {
    const text = document.lineAt(i).text;
    if (text.trim().length === 0) {
      continue; // a blank line does not close a block
    }
    if (text.length - text.trimStart().length <= indent) {
      break;
    }
    last = i;
  }
  return last;
}

function findKey(
  document: vscode.TextDocument,
  from: number,
  to: number,
  name: string,
  minIndent: number,
  format: FmFormat,
): KeyLine | undefined {
  for (let i = from; i <= to; i++) {
    const text = document.lineAt(i).text;
    const found = keyOnLine(text, format);
    if (found === undefined || found.indent <= minIndent) {
      continue;
    }
    const written = text.slice(found.column, found.column + found.length);
    const key = written.replace(/^["']|["']$/g, '');
    if (key === name) {
      return { ...found, line: i };
    }
  }
  return undefined;
}

/**
 * Where to draw the violation.
 *
 * Walks the key path segment by segment, narrowing the search to each parent's
 * children. A path that resolves fully highlights the leaf key; a path that
 * stops early highlights the deepest parent that does exist; a path that
 * resolves to nothing lands on the block's first content line — which is
 * exactly where the missing key would be written.
 */
export function rangeForViolation(
  document: vscode.TextDocument,
  block: FmBlock,
  keyPath: readonly string[],
): vscode.Range {
  const span = innerLines(document, block);
  let from = span.first;
  let to = span.last;
  let minIndent = -1;
  let found: KeyLine | undefined;

  for (const segment of keyPath) {
    const hit = findKey(document, from, to, segment, minIndent, block.format);
    if (hit === undefined) {
      break;
    }
    found = hit;
    from = hit.line + 1;
    to = lastChildLine(document, hit.line, hit.indent, span.last);
    minIndent = hit.indent;
  }

  const range =
    found === undefined
      ? document.lineAt(span.first).range
      : new vscode.Range(found.line, found.column, found.line, found.column + found.length);

  // Belt and braces: whatever the arithmetic above did, the squiggle stays
  // between the fences.
  const clamped = new vscode.Range(
    Math.min(Math.max(range.start.line, span.first), span.last),
    range.start.character,
    Math.min(Math.max(range.end.line, span.first), span.last),
    range.end.character,
  );
  return document.validateRange(clamped);
}

// ---------------------------------------------------------------------------
// The manager
// ---------------------------------------------------------------------------

/** Turn one core `FieldViolation` into a `Diagnostic` anchored in the block. */
function toDiagnostic(
  document: vscode.TextDocument,
  block: FmBlock,
  violation: FieldViolation,
): vscode.Diagnostic {
  const diagnostic = new vscode.Diagnostic(
    rangeForViolation(document, block, violation.path),
    violation.message,
    // A warning, not an error: an unfinished draft is a normal state, and a
    // red squiggle on every new file teaches people to stop looking.
    vscode.DiagnosticSeverity.Warning,
  );
  diagnostic.source = DIAGNOSTIC_SOURCE;
  diagnostic.code = REQUIRED_FIELD_CODE;
  return diagnostic;
}

export class DiagnosticsManager implements vscode.Disposable {
  private readonly collection: vscode.DiagnosticCollection;
  private readonly subscriptions: vscode.Disposable[] = [];
  private readonly log: LogSink;
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(log: LogSink = sharedLog) {
    this.log = log;
    this.collection = vscode.languages.createDiagnosticCollection('zer0Cms');
    this.subscriptions.push(
      this.collection,
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (editor !== undefined) {
          this.validate(editor.document);
        }
      }),
      vscode.workspace.onDidChangeTextDocument((event) => {
        if (event.document === vscode.window.activeTextEditor?.document) {
          this.schedule(event.document);
        }
      }),
      vscode.workspace.onDidSaveTextDocument((document) => this.validate(document)),
      vscode.workspace.onDidCloseTextDocument((document) => this.collection.delete(document.uri)),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (affectsUs(event)) {
          this.validateVisible();
        }
      }),
    );
  }

  /** Re-validate after the typing pause. */
  private schedule(document: vscode.TextDocument): void {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
    }
    this.timer = setTimeout(() => {
      this.timer = undefined;
      this.validate(document);
    }, DEBOUNCE_MS);
  }

  /** Validate every editor the user can currently see. */
  validateVisible(): void {
    for (const editor of vscode.window.visibleTextEditors) {
      this.validate(editor.document);
    }
  }

  /**
   * Validate one document. Anything that is not editable content — the wrong
   * extension, no front matter, no workspace — clears its diagnostics instead
   * of leaving a stale set behind.
   */
  validate(document: vscode.TextDocument, cfg: Zer0Config = currentConfig()): void {
    if (
      cfg.workspaceRoot === '' ||
      document.uri.scheme !== 'file' ||
      !isSupported(cfg, document.uri.fsPath)
    ) {
      this.collection.delete(document.uri);
      return;
    }

    try {
      const { block } = splitFrontMatter(document.getText());
      if (block === null) {
        // No block means no place to put a range, and a file with no front
        // matter has not violated a schema — it has not claimed one.
        this.collection.delete(document.uri);
        return;
      }
      const contentType = resolveContentType(cfg, block.data, document.uri.fsPath);
      // `validateFields` returns nothing when `zer0Cms.validation.enabled` is
      // off, so the one setting governs the panel, the Problems panel and the
      // MCP status tool together.
      const violations = validateFields(contentType.fields, block.data, cfg);
      if (violations.length === 0) {
        this.collection.delete(document.uri);
        return;
      }
      this.collection.set(
        document.uri,
        violations.map((violation) => toDiagnostic(document, block, violation)),
      );
    } catch (error) {
      // Validation runs mid-keystroke. A parse that trips over a half-typed
      // line must clear the squiggles, not take the extension down.
      this.collection.delete(document.uri);
      this.log.verbose(`diagnostics skipped for ${document.uri.fsPath}: ${describeError(error)}`);
    }
  }

  /** Everything we have published to the Problems panel, gone. */
  clearAll(): void {
    this.collection.clear();
  }

  dispose(): void {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    for (const subscription of this.subscriptions) {
      subscription.dispose();
    }
    this.subscriptions.length = 0;
  }
}
