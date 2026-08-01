/**
 * The governed queue: draft → brand guard → human approval → publish → ledger.
 *
 * **`doApprove` and `doPublish` in this file are the single authoritative
 * gate.** Decision D5 in one sentence: the webview is UI, never permission. A
 * button in the panel or the dashboard posts `{type:'command', id:'draft.publish',
 * args:{draftPath}}` — an intent and a target, no payload, no override — and
 * the host routes it into the *same* function the command palette calls. There
 * is one gate to audit, not three, and no surface can reach a shorter path than
 * any other.
 *
 * Every privileged action here does the same four things, in this order, before
 * a single byte is written:
 *
 *   1. **Re-read the configuration.** `currentConfig()` is uncached, so a
 *      `publishAllow` that was flipped thirty seconds ago is honoured without a
 *      window reload — and a stale in-memory copy can never authorise a publish
 *      the settings no longer allow.
 *   2. **Re-read the draft from disk.** Not from `store.current()`, not from
 *      the webview's copy. The file may have been edited, approved by a
 *      colleague, or rewritten by a script since the snapshot was taken.
 *   3. **Re-run the brand guard and re-evaluate `evaluateGates()`.** The
 *      webview already rendered an advisory version of this to grey out a
 *      button. That render is decoration; this evaluation is the decision.
 *   4. **Ask, modally.** `confirm()` is `showWarningMessage({modal:true})`,
 *      which cannot be missed the way a toast can, and the message names the
 *      target and the destination path so the answer is to a specific act
 *      rather than to the word "Publish".
 *
 * `publishPreview` then re-runs the publish gates a *third* time immediately
 * before the target sends. That is not redundancy for its own sake — it is the
 * only check that runs inside the function that performs the write, and it is
 * what makes the core safe to call from the MCP server, where none of the
 * above exists.
 *
 * What this file deliberately does **not** have: a `force` flag, a `quiet`
 * mode, or a batch publisher. The core's `publishPreview` accepts `force`
 * because a human who has read the guard findings may overrule them, but no
 * command here passes it — overruling the brand guard is not something a
 * keyboard shortcut should be able to do by accident.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  STATUS_APPROVED,
  STATUS_PENDING,
  STATUS_PUBLISHED,
  absPath,
  asString,
  blockerSummary,
  buildPreview,
  commentaryOf,
  evaluateApproveGates,
  evaluatePublishGates,
  getArticleDetails,
  getEntry,
  guardWithWorkspace,
  hasBlocker,
  markStatus,
  previewRequestFromDraft,
  publishPreview,
  readArticle,
  readDraft,
  relPath,
  resolveContentType,
  targetFor,
  validateFields,
  writeDraft,
  type Blocker,
  type ContentRecord,
  type DraftFile,
  type FieldViolation,
  type GuardFinding,
  type Ledger,
  type Preview,
  type Zer0Config,
} from '../core';
import { currentConfig } from '../config';
import type { Zer0Shell } from '../extension';
import { describeError } from '../logger';
import { confirm, notifyError, notifyInfo, notifyWarning } from '../uiState';
import { activeFilePath, openInEditor, register, showReport, toFilePath } from './project';

/**
 * The two functions the webview hosts are handed.
 *
 * `PanelProvider` and `DashboardPanel` receive this object and call it for the
 * governance intents. They are given the functions rather than the command ids
 * so that the injection is visible in the type system: a surface that wants to
 * approve something has to hold the gate, and there is no way to hold a
 * partial one.
 */
export interface GovernanceActions {
  /** `pending` → `approved`, gated and confirmed. Resolves `true` if it happened. */
  approve(draftPath: string): Promise<boolean>;
  /** Build, gate, confirm, send, record, then flip the draft to `published`. */
  publish(draftPath: string): Promise<boolean>;
  /** Open the draft and the review surface. */
  review(draftPath: string): Promise<void>;
  /** Report the brand guard's findings for a draft. */
  guard(draftPath: string): Promise<void>;
  /** Show exactly what would publish. No writes, no network. */
  preview(draftPath: string): Promise<void>;
}

// ---------------------------------------------------------------------------
// Gate context — everything `evaluateGates` needs, all of it read fresh
// ---------------------------------------------------------------------------

interface GateContext {
  cfg: Zer0Config;
  draft: DraftFile;
  guard: GuardFinding[];
  violations: FieldViolation[];
  preview?: Preview;
  previewError?: string;
  ledgerEntry?: Ledger[string];
}

/**
 * Read everything the gate depends on, from disk, right now.
 *
 * `buildPreview` is the expensive part and it is not optional: it resolves the
 * source page, renders the artifact the configured target would produce, and
 * runs the brand guard over the real commentary — so the guard findings and
 * the canonical URL used by the gate are the ones the publish would actually
 * use, not an approximation of them.
 *
 * A preview that throws is not an exception here, it is a `previewError`, which
 * `evaluateGates` turns into an ordered blocker like any other. Guard findings
 * are still computed in that case, so a draft with both a broken source
 * reference *and* a banned phrase reports both instead of hiding the second
 * behind the first.
 */
async function collectGateContext(draftPath: string): Promise<GateContext> {
  const cfg = currentConfig();
  const draft = await readDraft(draftPath);

  let preview: Preview | undefined;
  let previewError: string | undefined;
  try {
    preview = await buildPreview(cfg, previewRequestFromDraft(draft));
  } catch (error) {
    previewError = describeError(error);
  }

  const guard = preview?.guard ?? (await guardWithWorkspace(cfg, commentaryOf(draft)));

  let ledgerEntry: Ledger[string] | undefined;
  if (preview?.url !== undefined && preview.url !== '' && cfg.workspaceRoot !== '') {
    ledgerEntry = await getEntry(absPath(cfg, cfg.governance.ledgerPath), preview.url);
  }

  // Required-field violations belong to the *source page*, not to the draft, so
  // they are read from the page's own bytes rather than from the page index —
  // the index may be a snapshot older than the last save.
  let violations: FieldViolation[] = [];
  if (preview?.page !== undefined) {
    try {
      const article = await readArticle(preview.page.filePath);
      const contentType = resolveContentType(cfg, article.data, article.filePath);
      violations = validateFields(contentType.fields, article.data, cfg);
    } catch {
      // The page vanished between the preview and now. `previewFailed` is not
      // the right story for that, and an empty violation list is honest: we do
      // not know of any. The publish itself will fail loudly if it matters.
      violations = [];
    }
  }

  return {
    cfg,
    draft,
    guard,
    violations,
    ...(preview === undefined ? {} : { preview }),
    ...(previewError === undefined ? {} : { previewError }),
    ...(ledgerEntry === undefined ? {} : { ledgerEntry }),
  };
}

/** The gate input, assembled so no key is ever present-but-undefined. */
function gateInput(ctx: GateContext): Parameters<typeof evaluatePublishGates>[0] {
  return {
    cfg: ctx.cfg,
    draft: ctx.draft,
    guard: ctx.guard,
    violations: ctx.violations,
    ...(ctx.previewError === undefined ? {} : { previewError: ctx.previewError }),
    ...(ctx.ledgerEntry === undefined ? {} : { ledgerEntry: ctx.ledgerEntry }),
  };
}

/** Report blockers in their fixed order — the first one is what to fix first. */
async function reportBlockers(
  shell: Zer0Shell,
  action: string,
  draftPath: string,
  blockers: readonly Blocker[],
): Promise<void> {
  const summary = blockerSummary(blockers);
  shell.log.warn(`${action} blocked for ${path.basename(draftPath)}: ${summary}`);
  await notifyError(`${action} blocked: ${summary}.`);
}

/** `warning`-level guard findings, for the confirmation's detail line. */
function warningCount(guard: readonly GuardFinding[]): number {
  return guard.filter((finding) => finding.level === 'warning').length;
}

// ---------------------------------------------------------------------------
// The gate
// ---------------------------------------------------------------------------

/**
 * `pending` → `approved`.
 *
 * Approving does not publish and does not touch the ledger — it records that a
 * human read the thing. It is still gated, because approving a draft whose
 * source page is missing its required fields, or whose commentary trips a hard
 * brand ban, would be approving something that can never publish.
 */
export async function doApprove(shell: Zer0Shell, draftPath: string): Promise<boolean> {
  const ctx = await collectGateContext(draftPath);
  const blockers = evaluateApproveGates(gateInput(ctx));
  if (blockers.length > 0) {
    await reportBlockers(shell, 'Approve', draftPath, blockers);
    return false;
  }

  const warnings = warningCount(ctx.guard);
  const detail = [
    `Draft: ${relPath(ctx.cfg, draftPath)}`,
    `Target: ${targetFor(ctx.cfg).id}`,
    ...(ctx.preview?.plan === undefined ? [] : [`Destination: ${ctx.preview.plan.destination}`]),
    warnings === 0
      ? 'The brand guard found nothing to warn about.'
      : `The brand guard raised ${warnings} warning${warnings === 1 ? '' : 's'} — they do not block, but read them first.`,
  ].join('\n');

  const ok = await confirm(
    `Approve "${path.basename(draftPath)}" for publishing?`,
    'Approve',
    detail,
  );
  if (!ok) {
    return false;
  }

  await markStatus(draftPath, STATUS_APPROVED);
  shell.log.info(`approved ${relPath(ctx.cfg, draftPath)}`);
  await shell.store.refresh();
  return true;
}

/**
 * Approved (or whatever `governance.acceptStatuses` allows) → published.
 *
 * The draft's own status is flipped *after* the target reports success, never
 * before: a target failure must not leave a queue file claiming it published.
 * A ledger skip — the URL is already recorded — still flips it, because the
 * artifact genuinely is out there and the queue would otherwise offer it again
 * forever. That is the CI lane's behaviour too, and the two must agree.
 */
export async function doPublish(shell: Zer0Shell, draftPath: string): Promise<boolean> {
  const ctx = await collectGateContext(draftPath);
  const blockers = evaluatePublishGates(gateInput(ctx));

  if (blockers.length > 0) {
    // One blocker deserves a way forward rather than a dead end: the artifact
    // is already in the ledger, so the only thing out of step is the queue
    // file. Offering to reconcile it is not a bypass — nothing gets published.
    if (blockers.length === 1 && hasBlocker(blockers, 'alreadyPublished')) {
      const answer = await notifyWarning(
        `${blockerSummary(blockers)}.`,
        'Mark draft as published',
      );
      if (answer === 'Mark draft as published') {
        await markStatus(draftPath, STATUS_PUBLISHED);
        shell.log.info(`reconciled ${relPath(ctx.cfg, draftPath)} with the ledger`);
        await shell.store.refresh();
        return true;
      }
      return false;
    }
    await reportBlockers(shell, 'Publish', draftPath, blockers);
    return false;
  }

  const preview = ctx.preview;
  if (preview === undefined) {
    // Unreachable while `previewFailed` is in the gate order, and cheap
    // insurance if that ever changes: no preview means nothing to publish.
    await notifyError('publish blocked: the preview could not be built.');
    return false;
  }

  const target = targetFor(ctx.cfg);
  const warnings = warningCount(ctx.guard);
  const detail = [
    `Draft: ${relPath(ctx.cfg, draftPath)}`,
    `Target: ${target.id}`,
    ...(preview.plan === undefined ? [] : [`Destination: ${preview.plan.destination}`]),
    ...(preview.url === undefined ? [] : [`Canonical URL: ${preview.url}`]),
    ...(warnings === 0
      ? []
      : [`Brand guard warnings: ${warnings} (they do not block).`]),
    'This writes the artifact and records it in the ledger.',
  ].join('\n');

  const ok = await confirm(
    `Publish "${path.basename(draftPath)}" with the "${target.id}" target?`,
    'Publish',
    detail,
  );
  if (!ok) {
    return false;
  }

  const outcome = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'zer0-CMS: publishing…' },
    () =>
      publishPreview(
        ctx.cfg,
        preview,
        target,
        { draft: ctx.draft },
        { log: (message: string) => shell.log.info(message) },
      ),
  );

  for (const warning of outcome.warnings) {
    shell.log.warn(warning);
  }

  if (outcome.blocked !== undefined) {
    // The core re-ran the gates immediately before sending and stopped. That
    // is the third evaluation, and it wins.
    shell.log.warn(`publish blocked by the core: ${outcome.blocked.join('; ')}`);
    await notifyError(`publish blocked: ${outcome.blocked.join('; ')}.`);
    return false;
  }

  await markStatus(draftPath, STATUS_PUBLISHED);
  await shell.store.refresh();

  if (outcome.skipped !== undefined) {
    shell.log.info(`${outcome.skipped} (${relPath(ctx.cfg, draftPath)})`);
    await notifyInfo(outcome.skipped);
    return true;
  }

  shell.log.info(`published ${outcome.urn ?? '(no urn)'} <- ${relPath(ctx.cfg, draftPath)}`);
  // A warning here means the artifact did not land where the plan said — a name
  // collision bumped it, or an interrupted publish was adopted. That is exactly
  // the kind of drift a log line alone lets someone miss.
  const note = outcome.warnings.length === 0 ? '' : ` — ${outcome.warnings.join(' ')}`;
  const answer = await notifyInfo(`${`published ${outcome.urn ?? ''}`.trim()}${note}`, 'Open artifact');
  if (answer === 'Open artifact' && preview.plan !== undefined) {
    await openInEditor(absPath(ctx.cfg, preview.plan.destination));
  }
  return true;
}

// ---------------------------------------------------------------------------
// Picking a draft
// ---------------------------------------------------------------------------

/**
 * The draft a command should act on, from whatever it was handed: a tree row,
 * a `Uri`, a bare path, or the webview's `{ draftPath }`.
 */
export function draftPathFrom(cfg: Zer0Config, arg: unknown): string | undefined {
  if (typeof arg === 'object' && arg !== null) {
    const record = arg as { draft?: { path?: unknown }; draftPath?: unknown };
    if (typeof record.draftPath === 'string' && record.draftPath.trim() !== '') {
      return toFilePath(cfg, record.draftPath);
    }
    if (typeof record.draft?.path === 'string') {
      return toFilePath(cfg, record.draft.path);
    }
  }
  return toFilePath(cfg, arg);
}

/** Ask which draft, optionally narrowed to the statuses an action accepts. */
async function pickDraft(
  shell: Zer0Shell,
  filter?: (status: string) => boolean,
): Promise<string | undefined> {
  const snapshot = await shell.store.current();
  const drafts = snapshot.drafts.filter((draft) => (filter === undefined ? true : filter(draft.status)));
  if (drafts.length === 0) {
    await notifyInfo('nothing matching in the draft queue.');
    return undefined;
  }
  const picked = await vscode.window.showQuickPick(
    drafts.map((draft) => ({
      label: path.basename(draft.path),
      description: `${draft.status} · ${draft.type}`,
      detail: commentaryOf(draft).replace(/\s+/g, ' ').slice(0, 120),
      draftPath: draft.path,
    })),
    { placeHolder: 'Select a draft', ignoreFocusOut: true },
  );
  return picked?.draftPath;
}

/** Resolve the argument, falling back to a picker. */
async function resolveDraft(
  shell: Zer0Shell,
  arg: unknown,
  filter?: (status: string) => boolean,
): Promise<string | undefined> {
  const fromArgument = draftPathFrom(currentConfig(), arg);
  if (fromArgument !== undefined) {
    return fromArgument;
  }
  return pickDraft(shell, filter);
}

// ---------------------------------------------------------------------------
// Drafting from content
// ---------------------------------------------------------------------------

/** The content this draft is about: a tree row, the active file, or a pick. */
async function resolveContentRef(shell: Zer0Shell, arg: unknown): Promise<string | undefined> {
  const cfg = currentConfig();

  if (typeof arg === 'object' && arg !== null) {
    const record = arg as { record?: { path?: unknown } };
    if (typeof record.record?.path === 'string') {
      return toFilePath(cfg, record.record.path);
    }
  }
  const direct = toFilePath(cfg, arg);
  if (direct !== undefined) {
    return direct;
  }

  const snapshot = await shell.store.current();
  const candidates: ContentRecord[] = snapshot.distributable;
  if (candidates.length === 0) {
    const active = activeFilePath();
    if (active !== undefined) {
      return active;
    }
    await notifyInfo('no distributable content found to draft from.');
    return undefined;
  }

  const picked = await vscode.window.showQuickPick(
    candidates.map((record) => ({
      label: record.title || record.path,
      description: [
        record.health >= 0 ? `health ${record.health}` : 'health —',
        snapshot.publishedSourceFiles.has(record.path) ? 'posted' : '',
      ]
        .filter((part) => part !== '')
        .join(' · '),
      detail: record.path,
      recordPath: record.path,
    })),
    { placeHolder: 'Draft an update about…', ignoreFocusOut: true },
  );
  return picked === undefined ? undefined : absPath(cfg, picked.recordPath);
}

/** A filename stem with a Jekyll date prefix and the extension removed. */
function draftSlugFor(filePath: string): string {
  return path
    .basename(filePath)
    .replace(/\.[^./]+$/, '')
    .replace(/^\d{4}-\d{2}-\d{2}-/, '');
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

function renderGuard(guard: readonly GuardFinding[]): string[] {
  const findings = guard.filter((finding) => finding.level !== 'info');
  if (findings.length === 0) {
    return ['clean — no errors, no warnings.'];
  }
  return findings.map((finding) => `- **${finding.level}** — ${finding.message}`);
}

/** The publish preview, as a markdown document nobody has to keep. */
function renderPreviewReport(ctx: GateContext, draftPath: string): string {
  const blockers = evaluatePublishGates(gateInput(ctx));
  const artifact = ctx.preview?.artifact;
  const contents =
    typeof artifact === 'object' && artifact !== null && 'contents' in artifact
      ? String((artifact as { contents: unknown }).contents)
      : JSON.stringify(artifact ?? null, null, 2);

  return [
    `# Publish preview — ${path.basename(draftPath)}`,
    '',
    '_Nothing was written and nothing was sent. This is the artifact the configured target would produce._',
    '',
    '## Gate',
    '',
    blockers.length === 0
      ? 'No blockers. Publishing is allowed from this state.'
      : blockers.map((blocker) => `- \`${blocker.kind}\` — ${blocker.message}`).join('\n'),
    '',
    '## Brand guard',
    '',
    ...renderGuard(ctx.guard),
    '',
    ...(ctx.previewError === undefined
      ? [
          '## Artifact',
          '',
          ...(ctx.preview?.plan === undefined
            ? []
            : [`Destination: \`${ctx.preview.plan.destination}\``, '']),
          ...(ctx.preview?.url === undefined ? [] : [`Canonical URL: \`${ctx.preview.url}\``, '']),
          '```markdown',
          contents,
          '```',
        ]
      : ['## Artifact', '', `The preview could not be built: ${ctx.previewError}`]),
    '',
    '## Ledger',
    '',
    ctx.ledgerEntry === undefined
      ? 'No ledger entry for this URL — it has never been published.'
      : `Already published as \`${String(ctx.ledgerEntry.urn ?? '')}\` on ${String(
          ctx.ledgerEntry.posted_at ?? 'an unknown date',
        )}.`,
    '',
  ].join('\n');
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerGovernanceCommands(shell: Zer0Shell): GovernanceActions {
  const actions: GovernanceActions = {
    approve: (draftPath) => doApprove(shell, draftPath),
    publish: (draftPath) => doPublish(shell, draftPath),
    review: (draftPath) => doReview(shell, draftPath),
    guard: (draftPath) => doGuard(shell, draftPath),
    preview: (draftPath) => doPreview(shell, draftPath),
  };

  // --- New draft from content ----------------------------------------------
  register(shell, 'draft.new', async (arg: unknown) => {
    const cfg = currentConfig();
    if (cfg.workspaceRoot === '') {
      await notifyWarning('open a folder before drafting.');
      return;
    }

    const source = await resolveContentRef(shell, arg);
    if (source === undefined) {
      return;
    }

    const article = await readArticle(source);
    const details = getArticleDetails(article.body);
    const title = asString(article.data[cfg.seo.titleField]).trim();
    const description = asString(article.data[cfg.seo.descriptionField]).trim();

    // The commentary seed is the article's own opening, then its description,
    // then its title — the first of those that exists. It is a starting point
    // for a human to rewrite, which is why the draft opens in the editor.
    const body = details.firstParagraph.trim() || description || title;

    const dest = await writeDraft(absPath(cfg, cfg.governance.draftsFolder), {
      type: 'article',
      slug: draftSlugFor(source),
      body,
      source: relPath(cfg, source),
      ...(title === '' ? {} : { title }),
      ...(description === '' ? {} : { description }),
    });

    shell.log.info(`drafted ${relPath(cfg, dest)} from ${relPath(cfg, source)}`);
    await shell.store.refresh();
    await openInEditor(dest);
  });

  // --- Review --------------------------------------------------------------
  register(shell, 'draft.review', async (arg: unknown) => {
    const draftPath = await resolveDraft(shell, arg);
    if (draftPath !== undefined) {
      await doReview(shell, draftPath);
    }
  });

  // --- Approve -------------------------------------------------------------
  register(shell, 'draft.approve', async (arg: unknown) => {
    const draftPath = await resolveDraft(shell, arg, (status) => status === STATUS_PENDING);
    if (draftPath !== undefined) {
      await doApprove(shell, draftPath);
    }
  });

  // --- Publish -------------------------------------------------------------
  register(shell, 'draft.publish', async (arg: unknown) => {
    const accepted = currentConfig().governance.acceptStatuses.map((status) =>
      status.trim().toLowerCase(),
    );
    const draftPath = await resolveDraft(shell, arg, (status) => accepted.includes(status));
    if (draftPath !== undefined) {
      await doPublish(shell, draftPath);
    }
  });

  // --- Guard ---------------------------------------------------------------
  register(shell, 'draft.guard', async (arg: unknown) => {
    const draftPath = await resolveDraft(shell, arg);
    if (draftPath !== undefined) {
      await doGuard(shell, draftPath);
    }
  });

  // --- Preview -------------------------------------------------------------
  register(shell, 'draft.preview', async (arg: unknown) => {
    const draftPath = await resolveDraft(shell, arg);
    if (draftPath !== undefined) {
      await doPreview(shell, draftPath);
    }
  });

  return actions;
}

/**
 * Open the draft beside the review surface.
 *
 * The dashboard's Drafts tab is where a draft is actually reviewed — fold
 * marker, guard findings, artifact, ledger state, the two gated buttons. The
 * file itself opens too, because reviewing usually turns into editing.
 */
async function doReview(shell: Zer0Shell, draftPath: string): Promise<void> {
  await openInEditor(draftPath);
  await vscode.commands.executeCommand('zer0Cms.dashboard');
  shell.log.verbose(`review ${path.basename(draftPath)}`);
}

/** Run the brand guard and say what it found. Reads; never writes. */
async function doGuard(shell: Zer0Shell, draftPath: string): Promise<void> {
  const cfg = currentConfig();
  const draft = await readDraft(draftPath);
  const guard = await guardWithWorkspace(cfg, commentaryOf(draft));

  const errors = guard.filter((finding) => finding.level === 'error');
  const warnings = guard.filter((finding) => finding.level === 'warning');

  shell.log.info(`brand guard — ${path.basename(draftPath)}:`);
  if (errors.length === 0 && warnings.length === 0) {
    shell.log.info('  clean');
  }
  for (const finding of [...errors, ...warnings]) {
    shell.log.info(`  ${finding.level}: ${finding.message}`);
  }
  shell.log.show(false);

  const summary = `brand guard: ${errors.length} error(s), ${warnings.length} warning(s).`;
  if (errors.length > 0) {
    await notifyWarning(summary);
  } else {
    await notifyInfo(summary);
  }
}

/** Show exactly what would publish. No writes, no network — by construction. */
async function doPreview(shell: Zer0Shell, draftPath: string): Promise<void> {
  const ctx = await collectGateContext(draftPath);
  await showReport(renderPreviewReport(ctx, draftPath));
  shell.log.verbose(`preview ${path.basename(draftPath)}`);
}
