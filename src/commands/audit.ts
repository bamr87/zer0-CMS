/**
 * The site-wide front-matter audit's shell: scan the site, repair one finding,
 * run the repository's own verification command.
 *
 * **`doFixIssue` is the single authoritative gate for the fix-it**, exactly as
 * `doApprove`/`doPublish` are for publishing and `doToggleSwitch` is for a
 * fleet switch (decision D5). The dashboard's Audit tab posts
 * `{type:'command', id:'audit.fix', args:{path, kind}}` — a file and a rule id,
 * nothing else. No change set travels up the wire, no `before`/`after` text, no
 * "the user already looked at the diff". The host routes that intent into the
 * *same* function the command palette calls, and that function does the
 * following, in this order, before a byte is written:
 *
 *   1. **Re-read the configuration.** `currentConfig()` is uncached, so a
 *      `zer0.json` edited thirty seconds ago is honoured without a reload, and
 *      a stale copy can never decide what a fix looks like.
 *   2. **Re-read the site from disk**, including *that* file. Not the store
 *      snapshot, not the webview's row, not the audit the tab was drawn from.
 *   3. **Re-run `auditPage` for that file and find the finding again.** If the
 *      rule no longer fires, the fix is refused in words. This is the ordering
 *      the whole flow exists for: somebody may have fixed the file by hand
 *      between the scan and the click, and applying `missing-key:date` to a
 *      file that now has a date would write a second, wrong one.
 *   4. **Ask the core for the change set** — `fixFor`, which returns `null`
 *      for every finding that has no honest mechanical repair. `null` is a
 *      refusal with a reason, not a fallback into guessing.
 *   5. **Render the diff and show it**, through `dryRunFix`, which produces the
 *      exact bytes a write would produce and refuses TOML/JSON blocks, nested
 *      paths under a scalar, and any block the parser could not read. The two
 *      sides open in a real diff editor over a `zer0cms-audit:` content
 *      provider, so what is compared is what was read — never a dirty buffer.
 *   6. **Ask, modally**, naming the file, the rule and the change.
 *   7. Only then `writeArticle`, which is line surgery: untouched lines come
 *      out byte-identical.
 *
 * ### `verify` never spawns from here
 *
 * `node:child_process` is fenced by eslint to `src/core/contract/engine.ts` and
 * `src/core/content/placeholders.ts`. `audit.verify` therefore calls
 * `runVerifyCommand` in the first of those, which re-asserts the exec gate as a
 * value, and this file re-asks `workspaceTrusted()` before it even builds the
 * argv — two checks on purpose (decision D13): one so a person reads a sentence
 * naming Workspace Trust, one so no caller anywhere can spawn by forgetting.
 * An unset `zer0Cms.cms.verifyCommand` is a normal state, not an error, and it
 * is reported as the sentence that names the setting.
 *
 * ### What this file deliberately does not have
 *
 * No "fix all". No `force`. No way to apply a change set a message supplied.
 * The audit finds problems across a whole site; repairing them is still one
 * file, one rule, one diff, one human answer at a time.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  AUDIT_RULE_SPECS,
  auditPage,
  auditSite,
  buildIndex,
  detectPlatform,
  dryRunFix,
  engineConfigFor,
  engineLayer,
  fixFor,
  readArticle,
  readSiteSchema,
  relPath,
  resolveContentType,
  runVerifyCommand,
  splitFrontMatter,
  withPlatformDefaults,
  writeArticle,
  type Article,
  type AuditIssue,
  type EngineResult,
  type FmBlock,
  type KeyChange,
  type PageEntry,
  type PlatformIo,
  type PlatformProfile,
  type ResolvedPlatform,
  type SiteAudit,
  type SiteSchema,
  type Zer0Config,
} from '../core';
import {
  currentConfig,
  readConfigFileJson,
  settingsSnapshot,
  workspaceTrusted,
} from '../config';
import type { AuditIssueView, AuditState } from '../webview/shared/protocol';
import type { Zer0Shell } from '../extension';
import { describeError } from '../logger';
import { confirm, notifyError, notifyInfo, notifyWarning } from '../uiState';
import { register, toFilePath } from './project';

/** The workspace-state key the dashboard boots its route from. */
const ROUTE_STATE_KEY = 'zer0Cms:Dashboard:Route';

/** The virtual scheme the fix preview's two sides are served on. */
export const AUDIT_DIFF_SCHEME = 'zer0cms-audit';

/** How many files the scan reads at once when it re-reads blocks for lines. */
const READ_CONCURRENCY = 8;

/**
 * The three functions the dashboard host is handed.
 *
 * It gets the functions rather than the command ids, so that holding the gate
 * is visible in the type system: a surface that wants to repair a file has to
 * hold the whole gate, and there is no way to hold a partial one.
 */
export interface AuditActions {
  /** Scan the site, report the counts, and reveal the Audit tab. */
  open(): Promise<void>;
  /**
   * Repair one finding. The target is a file and a rule id — never a change
   * set. Resolves `true` only if a file was written.
   */
  fix(target: { path: string; kind: string }): Promise<boolean>;
  /** Run `zer0Cms.cms.verifyCommand` and report the outcome. */
  verify(): Promise<boolean>;
}

// ---------------------------------------------------------------------------
// The scan — everything the audit needs, all of it read fresh
// ---------------------------------------------------------------------------

/** One pass over the site: the profile that read it, the schema, the findings. */
export interface AuditScan {
  cfg: Zer0Config;
  platform: ResolvedPlatform;
  profile: PlatformProfile;
  schema: SiteSchema;
  pages: PageEntry[];
  /** Keyed by workspace-relative path, as `auditSite` expects. */
  blocks: Map<string, FmBlock>;
  audit: SiteAudit;
}

/** Platform detection reads relative paths under the workspace root. */
function platformIo(root: string): PlatformIo {
  return {
    exists: async (rel) => {
      try {
        await vscode.workspace.fs.stat(vscode.Uri.file(path.resolve(root, rel)));
        return true;
      } catch {
        // Missing, or unreadable. Both mean "this marker is not evidence",
        // which is the only distinction detection can act on.
        return false;
      }
    },
    read: async (rel) => {
      try {
        const bytes = await vscode.workspace.fs.readFile(
          vscode.Uri.file(path.resolve(root, rel)),
        );
        return Buffer.from(bytes).toString('utf8');
      } catch {
        return undefined;
      }
    },
  };
}

/** Read `count` items with bounded concurrency, in place, in index order. */
async function eachBounded(count: number, run: (index: number) => Promise<void>): Promise<void> {
  let cursor = 0;
  const worker = async (): Promise<void> => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= count) {
        return;
      }
      await run(index);
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(READ_CONCURRENCY, Math.max(count, 1)) }, () => worker()),
  );
}

/**
 * Read every page's raw front-matter block, so the audit can report line
 * numbers and the parser-warnings channel.
 *
 * A file that vanished between the index and this read is simply absent from
 * the map: `auditSite` then treats it as a projection, which reports one rule
 * fewer rather than inventing `no-front-matter` about a file nobody opened.
 */
async function readBlocks(pages: readonly PageEntry[]): Promise<Map<string, FmBlock>> {
  const blocks = new Map<string, FmBlock>();
  await eachBounded(pages.length, async (index) => {
    const page = pages[index];
    if (page === undefined) {
      return;
    }
    try {
      const bytes = await vscode.workspace.fs.readFile(vscode.Uri.file(page.filePath));
      const { block } = splitFrontMatter(Buffer.from(bytes).toString('utf8'));
      if (block !== null) {
        blocks.set(page.relPath, block);
      }
    } catch {
      // Gone, or unreadable. The index's projection still answers every rule
      // that does not need a line number.
    }
  });
  return blocks;
}

/**
 * Scan the whole site, from disk, right now.
 *
 * Detection, the page index, the schema and the audit are all recomputed —
 * nothing here consults the store's snapshot, because the point of this
 * function is that every caller of it (the tab, the palette, the fix-it) is
 * looking at the same bytes the filesystem holds at the moment they asked.
 *
 * `withPlatformDefaults` is what makes this work on a repository that has never
 * been opened in this extension: with no `contentFolders` of its own, the
 * resolved profile's content roots (Jekyll's `_posts` and the collections
 * `_config.yml` names, MkDocs' `docs_dir`, …) fill the gap, and the audit reads
 * the 382 pages a sister site actually has instead of the zero it registered.
 * The returned `cfg` is that filled-in one — every caller downstream, the
 * fix-it included, has to be looking at the same folder list this scan used.
 */
export async function scanSite(shell: Zer0Shell, base: Zer0Config): Promise<AuditScan> {
  const io = platformIo(base.workspaceRoot);
  const platform = await detectPlatform(base.workspaceRoot, io, base.platform);
  const profile = platform.profile;
  const cfg = withPlatformDefaults(base, platform);

  const { pages, cache } = await buildIndex(cfg, undefined, shell.log, profile);
  const blocks = await readBlocks(pages);
  const schema = await readSiteSchema(cfg.workspaceRoot, profile, io.read, shell.log);
  const skipped = Object.keys(cache.skipped ?? {}).map((filePath) => relPath(cfg, filePath));

  const audit = auditSite(
    cfg,
    profile,
    pages,
    skipped,
    schema,
    new Date(),
    shell.log,
    blocks,
  );
  return { cfg, platform, profile, schema, pages, blocks, audit };
}

// ---------------------------------------------------------------------------
// The view model — built here so the tab and the palette cannot disagree
// ---------------------------------------------------------------------------

/**
 * The collection a finding belongs to: the last segment of its page's
 * registered content folder.
 *
 * `AuditIssue` carries a path and not a collection, and the derivation is
 * `collectionNameOf` in `src/core/content/audit.ts` — private there, mirrored
 * here over the page index rather than re-invented, so the Collection filter on
 * the tab groups findings exactly the way the audit's own duplicate-slug rule
 * groups pages.
 */
function collectionsByPath(pages: readonly PageEntry[]): Map<string, string> {
  const index = new Map<string, string>();
  for (const page of pages) {
    const folder = page.folder.split('\\').join('/').replace(/\/+$/, '');
    index.set(page.relPath, folder.split('/').pop() ?? '');
  }
  return index;
}

/** Everything `AuditState` needs that a `SiteAudit` alone does not carry. */
export interface AuditViewInput {
  audit: SiteAudit;
  pages: readonly PageEntry[];
  schema: SiteSchema;
  /** `cfg.cms.verifyCommand`; an empty string becomes `null` on the wire. */
  verifyCommand: string;
  /** `false` only for a slice built before anything was ever scanned. */
  ran?: boolean;
}

/**
 * `SiteAudit` → `AuditState`, the slice the dashboard renders.
 *
 * It lives beside the command rather than in the panel because two things in it
 * are derivations rather than copies — the collection per finding, and the
 * `scanned` count folded in beside the three severities — and a second copy of
 * either would be a second answer to the same question. `counts` is a
 * `Record<string, number>` precisely so `scanned` can travel with them; the
 * webview draws an em dash when it is absent rather than a zero.
 */
export function auditStateFrom(input: AuditViewInput): AuditState {
  const collections = collectionsByPath(input.pages);
  const issues: AuditIssueView[] = input.audit.issues.map((issue) => ({
    path: issue.path,
    relPath: issue.path,
    collection: collections.get(issue.path) ?? '',
    rule: issue.rule,
    kind: issue.kind,
    severity: issue.severity,
    lane: issue.lane,
    field: issue.field,
    message: issue.message,
    suggestion: issue.suggestion,
    fixable: issue.fixable,
  }));

  const named = new Set<string>();
  for (const issue of issues) {
    if (issue.collection !== '') {
      named.add(issue.collection);
    }
  }

  return {
    ran: input.ran ?? true,
    generatedAt: input.audit.generatedAt,
    counts: { ...input.audit.counts, scanned: input.audit.scanned },
    issues,
    schemaSource: input.schema.source,
    collections: [...named].sort(),
    verifyCommand: input.verifyCommand.trim() === '' ? null : input.verifyCommand,
  };
}

/** The same thing over a whole `scanSite` result. */
export function auditStateFromScan(scan: AuditScan): AuditState {
  return auditStateFrom({
    audit: scan.audit,
    pages: scan.pages,
    schema: scan.schema,
    verifyCommand: scan.cfg.cms.verifyCommand,
  });
}

// ---------------------------------------------------------------------------
// Prose the output channel and the modals share
// ---------------------------------------------------------------------------

/** Where "required" came from. Each source means something different. */
export function describeSchemaSource(schema: SiteSchema): string {
  switch (schema.source) {
    case 'zer0.json':
      return 'this project\'s own zer0.json content types';
    case 'frontmatter_schema.yml':
      return `the site's frontmatter_schema.yml${schema.path === null ? '' : ` (${schema.path})`}`;
    case 'cms-config':
      return `the .cms/ contract${schema.path === null ? '' : ` (${schema.path})`}`;
    case 'profile-default':
      return 'the platform profile\'s own defaults — the site declares no schema';
    case 'none':
      return 'nothing — no schema was found and the profile declares no required keys';
  }
}

/** One `KeyChange`, as a sentence a person can answer yes or no to. */
export function describeChange(change: KeyChange): string {
  if (change.value === undefined) {
    return `remove \`${change.key}\``;
  }
  const rendered =
    typeof change.value === 'string' ? change.value : JSON.stringify(change.value);
  return `set \`${change.key}\` to ${rendered}`;
}

function ruleLine(issue: AuditIssue): string {
  return `${issue.rule} — ${AUDIT_RULE_SPECS[issue.rule].what}`;
}

/** The audit's counts, as one line for the output channel and a toast. */
export function summarise(audit: SiteAudit): string {
  return (
    `${audit.scanned} file(s) scanned — ${audit.counts.error} error(s), ` +
    `${audit.counts.warning} warning(s), ${audit.counts.info} note(s)`
  );
}

// ---------------------------------------------------------------------------
// The fix preview — two virtual documents, never a dirty buffer
// ---------------------------------------------------------------------------

/**
 * The `zer0cms-audit:` documents the diff editor compares.
 *
 * Both sides are virtual on purpose. Diffing against `file:` would compare the
 * proposal with whatever an unsaved editor buffer happens to hold, and the
 * bytes this flow read from disk are the bytes it is proposing to rewrite.
 * Showing anything else would be showing a diff of a different question.
 */
class FixPreviewProvider implements vscode.TextDocumentContentProvider {
  private readonly documents = new Map<string, string>();
  private readonly emitter = new vscode.EventEmitter<vscode.Uri>();
  private seq = 0;

  readonly onDidChange = this.emitter.event;

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.documents.get(uri.toString()) ?? '';
  }

  /** Publish one before/after pair and return the two URIs to compare. */
  stage(relative: string, before: string, after: string): { before: vscode.Uri; after: vscode.Uri } {
    this.seq += 1;
    const token = String(this.seq);
    const left = this.uriFor(relative, 'before', token);
    const right = this.uriFor(relative, 'after', token);
    this.documents.set(left.toString(), before);
    this.documents.set(right.toString(), after);
    this.emitter.fire(left);
    this.emitter.fire(right);
    return { before: left, after: right };
  }

  /** Drop a staged pair once the person has answered. */
  release(uris: { before: vscode.Uri; after: vscode.Uri }): void {
    this.documents.delete(uris.before.toString());
    this.documents.delete(uris.after.toString());
  }

  dispose(): void {
    this.documents.clear();
    this.emitter.dispose();
  }

  private uriFor(relative: string, side: string, token: string): vscode.Uri {
    return vscode.Uri.from({
      scheme: AUDIT_DIFF_SCHEME,
      path: `/${relative.replace(/^\/+/, '')}`,
      query: `side=${side}&n=${token}`,
    });
  }
}

// ---------------------------------------------------------------------------
// audit.open
// ---------------------------------------------------------------------------

/** The per-rule tally, sorted by count then id, for the output channel. */
function ruleLines(audit: SiteAudit): string[] {
  return Object.entries(audit.byRule)
    .sort(([leftId, left], [rightId, right]) => right - left || leftId.localeCompare(rightId))
    .map(([rule, count]) => `  ${String(count).padStart(4)}  ${rule}`);
}

/**
 * Scan the site, say what it found, and reveal the Audit tab.
 *
 * The scan happens here rather than only in the store because this command is
 * reachable from the palette in a window where the dashboard was never opened,
 * and "the audit ran and found nothing" has to be distinguishable from "the
 * audit never ran" on every surface (decision D9).
 */
export async function doOpenAudit(shell: Zer0Shell): Promise<void> {
  const cfg = currentConfig();
  if (cfg.workspaceRoot === '') {
    await notifyWarning('open a folder before auditing a site.');
    return;
  }

  const scan = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'zer0-CMS: auditing the site…' },
    () => scanSite(shell, cfg),
  );

  shell.log.info(`audit — ${summarise(scan.audit)}`);
  shell.log.info(
    `  platform: ${scan.profile.id}${scan.profile.overlay === null ? '' : ` + ${scan.profile.overlay}`} ` +
      `(${scan.platform.source})`,
  );
  shell.log.info(`  schema: ${describeSchemaSource(scan.schema)}`);
  if (scan.audit.skipped.length > 0) {
    shell.log.verbose(`  skipped ${scan.audit.skipped.length} file(s) as generated or vendored`);
  }
  for (const line of ruleLines(scan.audit)) {
    shell.log.info(line);
  }

  await shell.context.workspaceState.update(ROUTE_STATE_KEY, 'audit');
  await vscode.commands.executeCommand('zer0Cms.dashboard');

  if (scan.audit.issues.length === 0) {
    await notifyInfo(`audit: ${summarise(scan.audit)}. The site is clean.`);
  }
}

// ---------------------------------------------------------------------------
// audit.fix — the gate
// ---------------------------------------------------------------------------

/** `{path, kind}` from a webview, or a bare path from the palette. */
export function fixTargetFrom(arg: unknown): { path: string; kind: string } | undefined {
  if (typeof arg !== 'object' || arg === null) {
    return undefined;
  }
  const record = arg as { path?: unknown; kind?: unknown };
  if (typeof record.path !== 'string' || record.path.trim() === '') {
    return undefined;
  }
  if (typeof record.kind !== 'string' || record.kind.trim() === '') {
    return undefined;
  }
  return { path: record.path.trim(), kind: record.kind.trim() };
}

async function refuse(shell: Zer0Shell, message: string): Promise<false> {
  shell.log.warn(`audit fix refused: ${message}`);
  await notifyError(`Fix refused: ${message}.`);
  return false;
}

/** Steps 1–5 of the fix flow, resolved. Either a refusal, or a real proposal. */
export type FixDerivation =
  | { refused: string }
  | {
      cfg: Zer0Config;
      scan: AuditScan;
      filePath: string;
      /** The workspace-relative path, as every message names it. */
      shown: string;
      article: Article;
      issue: AuditIssue;
      changes: KeyChange[];
      before: string;
      after: string;
    };

/**
 * Re-read everything and derive the change set for one finding, or refuse.
 *
 * Steps 1–5 of the file header, in one function, because there are two callers
 * and they must never disagree: `doFixIssue`, which then shows a diff and asks;
 * and `auditDryRun`, the read-only request the webview's "Preview the fix"
 * button makes. A preview computed by a different code path from the write it
 * previews is a preview of a different question.
 */
export async function deriveFix(
  shell: Zer0Shell,
  target: { path: string; kind: string },
): Promise<FixDerivation> {
  // 1 — the configuration, uncached.
  const base = currentConfig();
  if (base.workspaceRoot === '') {
    return { refused: 'there is no open folder to audit' };
  }

  // 2 — the site, and that file, from disk. The scan gives us the same
  //     `PageEntry` projection the audit itself reports on, so the finding we
  //     match is the finding the tab drew, re-derived rather than trusted. Its
  //     `cfg` — the one the profile filled in — is the one everything below
  //     uses, so the fix is computed against the folder list that found the file.
  const scan = await scanSite(shell, base);
  const cfg = scan.cfg;

  const filePath = toFilePath(cfg, target.path);
  if (filePath === undefined) {
    return { refused: `"${target.path}" is not a path in this workspace` };
  }
  const shown = relPath(cfg, filePath);

  const page = scan.pages.find((candidate) => candidate.filePath === filePath);
  if (page === undefined) {
    return {
      refused: `${shown} is not in the page index — it may have been deleted, or it is not in a registered content folder`,
    };
  }

  let article: Article;
  try {
    article = await readArticle(filePath);
  } catch (error) {
    return { refused: `${shown} could not be read (${describeError(error)})` };
  }

  // 3 — the finding, re-derived. A `kind` that no longer fires is the answer.
  const now = new Date();
  const ct = resolveContentType(cfg, article.data, filePath);
  const block = scan.blocks.get(page.relPath);
  const issues = auditPage(cfg, scan.profile, page, ct, block, scan.schema, now);
  const issue = issues.find((candidate) => candidate.kind === target.kind);
  if (issue === undefined) {
    return {
      refused:
        `"${target.kind}" no longer fires for ${shown} — the file changed since the audit ran. ` +
        'Re-run the audit and look again',
    };
  }

  // 4 — the change set, or an honest refusal.
  const changes = fixFor(issue, cfg, scan.profile, ct, article, now);
  if (changes === null) {
    return {
      refused: `${ruleLine(issue)} has no mechanical fix — ${issue.suggestion ?? 'it needs a person to decide the value'}`,
    };
  }

  // 5 — the exact bytes a write would produce.
  const rendered = dryRunFix(article, changes, cfg);
  if ('refused' in rendered) {
    return rendered;
  }
  if (rendered.before === rendered.after) {
    return { refused: `applying that change to ${shown} would not alter the file` };
  }

  return { cfg, scan, filePath, shown, article, issue, changes, ...rendered };
}

/**
 * The `auditDryRun` request: what the fix would change, and nothing else.
 *
 * Shaped exactly like `dryRunFix`'s own return — `{before, after}` or
 * `{refused}` — so the host handler is a pass-through and the webview never has
 * to learn a second vocabulary for the same answer. It writes nothing, and it
 * decides nothing: `doFixIssue` re-derives all of this from scratch.
 */
export async function auditDryRun(
  shell: Zer0Shell,
  target: { path: string; kind: string },
): Promise<{ before: string; after: string } | { refused: string }> {
  const derived = await deriveFix(shell, target);
  if ('refused' in derived) {
    return { refused: derived.refused };
  }
  return { before: derived.before, after: derived.after };
}

/**
 * Repair one finding on one file, or say in words why it will not.
 *
 * The ordering in the file header is the whole design. Note in particular that
 * the finding is looked up *again*, in a fresh `auditPage` over freshly-read
 * bytes: a `kind` that no longer fires means the file changed under the person,
 * and applying a repair for a finding that no longer exists is precisely the
 * bug this ordering prevents.
 */
export async function doFixIssue(
  shell: Zer0Shell,
  preview: FixPreviewProvider,
  target: { path: string; kind: string },
): Promise<boolean> {
  const derived = await deriveFix(shell, target);
  if ('refused' in derived) {
    return refuse(shell, derived.refused);
  }
  const { cfg, scan, filePath, shown, article, issue, changes } = derived;

  // 6 — the diff editor, then the human.
  const staged = preview.stage(shown, derived.before, derived.after);
  try {
    await vscode.commands.executeCommand(
      'vscode.diff',
      staged.before,
      staged.after,
      `${path.basename(filePath)} — audit fix: ${issue.rule}`,
      { preview: true },
    );

    // 6 — the human, modally, naming the file, the rule and the change.
    const detail = [
      `File: ${shown}`,
      `Rule: ${ruleLine(issue)}`,
      `Finding: ${issue.message}`,
      `Change: ${changes.map(describeChange).join('; ')}`,
      `Required by: ${describeSchemaSource(scan.schema)}`,
      'Only the lines belonging to the changed keys are rewritten; everything else comes out byte-identical.',
    ].join('\n');

    const ok = await confirm(`Apply this fix to "${path.basename(filePath)}"?`, 'Apply fix', detail);
    if (!ok) {
      shell.log.verbose(`audit fix declined for ${shown} (${issue.kind})`);
      return false;
    }
  } finally {
    preview.release(staged);
  }

  // 7 — the write.
  try {
    await writeArticle(article, changes, cfg);
  } catch (error) {
    return refuse(shell, `${shown} could not be written (${describeError(error)})`);
  }

  shell.log.info(`audit fix: ${shown} — ${issue.kind} → ${changes.map(describeChange).join('; ')}`);
  await shell.store.refresh();
  await notifyInfo(`Fixed ${issue.kind} in ${shown}.`);
  return true;
}

// ---------------------------------------------------------------------------
// audit.verify — the repository's own harness, through the fenced runner
// ---------------------------------------------------------------------------

/**
 * Split a configured command into an argv array, honouring quotes.
 *
 * There is no shell anywhere in this path: `argv[0]` is the executable and the
 * rest are its arguments, so a repository path containing a quote is an
 * argument and never a second command. Quotes group; a backslash escapes the
 * next character inside a double-quoted run and outside quotes.
 */
export function splitCommand(command: string): string[] {
  const argv: string[] = [];
  let current = '';
  let quote: '"' | "'" | null = null;
  let started = false;

  for (let index = 0; index < command.length; index += 1) {
    const char = command.charAt(index);
    if (quote === null && (char === ' ' || char === '\t' || char === '\n' || char === '\r')) {
      if (started) {
        argv.push(current);
        current = '';
        started = false;
      }
      continue;
    }
    if (quote === null && (char === '"' || char === "'")) {
      quote = char;
      started = true;
      continue;
    }
    if (quote !== null && char === quote) {
      quote = null;
      continue;
    }
    if (char === '\\' && quote !== "'" && index + 1 < command.length) {
      current += command.charAt(index + 1);
      index += 1;
      started = true;
      continue;
    }
    current += char;
    started = true;
  }
  if (started) {
    argv.push(current);
  }
  return argv;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

/** Everything the verification run said, in the output channel. */
function logVerify(shell: Zer0Shell, argv: readonly string[], result: EngineResult): void {
  shell.log.info(`verify: ${argv.join(' ')} — exit ${result.code}`);
  if (result.stdout.trim() !== '') {
    shell.log.info(result.stdout.trimEnd());
  }
  if (result.stderr.trim() !== '') {
    shell.log.warn(result.stderr.trimEnd());
  }
}

/**
 * Run `zer0Cms.cms.verifyCommand` and report what it said.
 *
 * Two refusals, both in words, both before anything is built: an unset command
 * (a normal state — most sites have no single verification entry point) and an
 * untrusted workspace (decision D13 — a verify command is a command this
 * repository named, which is exactly what Workspace Trust exists to decide).
 */
export async function doVerify(shell: Zer0Shell): Promise<boolean> {
  const cfg = currentConfig();
  if (cfg.workspaceRoot === '') {
    await notifyWarning('open a folder before running the verification command.');
    return false;
  }

  const argv = splitCommand(cfg.cms.verifyCommand);
  if (argv.length === 0) {
    shell.log.info('verify: no command configured');
    await notifyWarning(
      'this site declares no verification command — set "zer0Cms.cms.verifyCommand" to the ' +
        'harness this repository runs in CI (for example "scripts/ci/run-all.sh").',
    );
    return false;
  }

  if (!workspaceTrusted()) {
    shell.log.warn('verify: refused — this workspace is not trusted');
    const answer = await notifyWarning(
      'this workspace is not trusted, so the verification command will not run. It executes a ' +
        'command named by this repository, which is exactly what Workspace Trust exists to decide.',
      'Manage trust',
    );
    if (answer === 'Manage trust') {
      await vscode.commands.executeCommand('workbench.trust.manage');
    }
    return false;
  }

  const engine = engineConfigFor(cfg, {
    trusted: true,
    layer: engineLayer(settingsSnapshot().cms, asRecord(readConfigFileJson().cms)),
  });

  const result = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `zer0-CMS: ${argv[0] ?? 'verify'}…` },
    () => runVerifyCommand(engine, argv, shell.log),
  );

  logVerify(shell, argv, result);
  shell.log.show(false);

  if (result.code === 0) {
    await notifyInfo(`verify: ${argv.join(' ')} passed.`);
    return true;
  }
  await notifyError(
    `verify: ${argv.join(' ')} exited ${result.code}. The output channel has what it said.`,
  );
  return false;
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerAuditCommands(shell: Zer0Shell): AuditActions {
  const preview = new FixPreviewProvider();
  shell.context.subscriptions.push(
    preview,
    vscode.workspace.registerTextDocumentContentProvider(AUDIT_DIFF_SCHEME, preview),
  );

  const actions: AuditActions = {
    open: () => doOpenAudit(shell),
    fix: (target) => doFixIssue(shell, preview, target),
    verify: () => doVerify(shell),
  };

  // --- Open the Audit tab (and scan) ---------------------------------------
  register(shell, 'audit.open', async () => {
    await doOpenAudit(shell);
  });

  // --- Fix one finding -----------------------------------------------------
  // The palette has no finding to name, so it offers the ones the site has.
  register(shell, 'audit.fix', async (arg: unknown) => {
    const target = fixTargetFrom(arg) ?? (await pickIssue(shell));
    if (target !== undefined) {
      await doFixIssue(shell, preview, target);
    }
  });

  // --- Run the site's own verification command -----------------------------
  register(shell, 'audit.verify', async () => {
    await doVerify(shell);
  });

  return actions;
}

/**
 * Ask which finding, from a fresh scan, narrowed to the fixable ones.
 *
 * `fixable` is the core's own advisory flag, and it is only used to decide what
 * to offer — `doFixIssue` re-derives the change set from scratch either way, so
 * a stale `true` here costs a refusal and never a bad write.
 */
async function pickIssue(shell: Zer0Shell): Promise<{ path: string; kind: string } | undefined> {
  const cfg = currentConfig();
  if (cfg.workspaceRoot === '') {
    await notifyWarning('open a folder before auditing a site.');
    return undefined;
  }

  const scan = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'zer0-CMS: auditing the site…' },
    () => scanSite(shell, cfg),
  );
  const fixable = scan.audit.issues.filter((issue) => issue.fixable);
  if (fixable.length === 0) {
    await notifyInfo(
      scan.audit.issues.length === 0
        ? `audit: ${summarise(scan.audit)}. The site is clean.`
        : `audit: ${summarise(scan.audit)} — none of them has a mechanical fix.`,
    );
    return undefined;
  }

  const picked = await vscode.window.showQuickPick(
    fixable.map((issue) => ({
      label: issue.kind,
      description: issue.path,
      detail: issue.message,
      target: { path: issue.path, kind: issue.kind },
    })),
    { placeHolder: 'Which finding should be repaired?', ignoreFocusOut: true },
  );
  return picked?.target;
}
