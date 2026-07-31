/**
 * The gate. **This file is the single source of truth for what stops a draft
 * from being approved or published.**
 *
 * Three callers ask it the same question and must get the same answer: the
 * webview (advisory — it renders the note under a disabled button), the
 * command the user actually invokes (authoritative — it re-runs every gate
 * against fresh state before it writes anything), and `publish.ts` (final —
 * immediately before the target sends). Decision D5: the webview is UI, never
 * the gate. A button that looks enabled is a rendering bug, not permission.
 *
 * The order of `Blocker[]` is fixed and tested:
 *
 *     noWorkspace, publishDisabled, guardError, alreadyPublished,
 *     statusNotAccepted, requiredFieldMissing, previewFailed
 *
 * It runs cheapest-and-most-fundamental first, so the note under a disabled
 * button leads with the thing the user has to fix first. Nothing here reads
 * the filesystem: every input is passed in, which is what lets the same
 * function run inside a webview render, a command, and a publish.
 */

import type { FieldViolation } from '../content/fields';
import type { Zer0Config } from '../shared/types';
import { STATUS_APPROVED, STATUS_PENDING, STATUS_PUBLISHED, type DraftFile } from './drafts';
import { errorMessages, type GuardFinding } from './guard';
import type { Ledger } from './ledger';

export type BlockerKind =
  | 'publishDisabled'
  | 'guardError'
  | 'alreadyPublished'
  | 'statusNotAccepted'
  | 'previewFailed'
  | 'requiredFieldMissing'
  | 'noWorkspace';

export interface Blocker {
  kind: BlockerKind;
  message: string;
}

export type GateMode = 'approve' | 'publish';

export interface GateInput {
  cfg: Zer0Config;
  /**
   * The draft under review. Optional because `publish.ts` gates a built
   * `Preview`, which may have come from a source page rather than a queue file
   * — the status gate simply does not apply there.
   */
  draft?: DraftFile;
  guard?: readonly GuardFinding[];
  /** The ledger entry for this draft's canonical URL, if any. */
  ledgerEntry?: Ledger[string];
  violations?: readonly FieldViolation[];
  /** Set when building the preview threw; the message is surfaced verbatim. */
  previewError?: string;
}

function noWorkspace(input: GateInput): Blocker | undefined {
  if (input.cfg.workspaceRoot.trim() !== '') {
    return undefined;
  }
  return { kind: 'noWorkspace', message: 'no workspace folder is open' };
}

/**
 * The master gate, and the one `force` must never override: publishing is off
 * by default and stays off until somebody deliberately turns it on for this
 * workspace. Governance being disabled entirely is reported the same way, with
 * its own message, because "nothing happened when I clicked Publish" needs to
 * name the setting that explains it.
 */
function publishDisabled(input: GateInput): Blocker | undefined {
  if (!input.cfg.governance.enabled) {
    return {
      kind: 'publishDisabled',
      message: 'governance is disabled (set "zer0Cms.governance.enabled" to true)',
    };
  }
  if (!input.cfg.governance.publishAllow) {
    return {
      kind: 'publishDisabled',
      message: 'publishing is disabled (set "zer0Cms.governance.publishAllow" to true)',
    };
  }
  return undefined;
}

/** Guard `error`s block; `warning` and `info` never do. */
function guardError(input: GateInput): Blocker | undefined {
  const errors = errorMessages(input.guard ?? []);
  if (errors.length === 0) {
    return undefined;
  }
  return { kind: 'guardError', message: `brand guard: ${errors.join('; ')}` };
}

function alreadyPublished(input: GateInput): Blocker | undefined {
  const entry = input.ledgerEntry;
  if (typeof entry?.urn !== 'string' || entry.urn === '') {
    return undefined;
  }
  const when = typeof entry.posted_at === 'string' && entry.posted_at !== '' ? ` on ${entry.posted_at}` : '';
  return { kind: 'alreadyPublished', message: `already published as ${entry.urn}${when}` };
}

/**
 * Approving accepts a `pending` draft and nothing else. Publishing accepts
 * whatever `governance.acceptStatuses` lists — the CI lane treats a merge as
 * the approval, so a workspace that trusts its review can publish `pending`
 * directly, and one that does not can require `approved`.
 */
function statusNotAccepted(mode: GateMode, input: GateInput): Blocker | undefined {
  const draft = input.draft;
  if (draft === undefined) {
    return undefined;
  }
  const status = draft.status.trim().toLowerCase() || STATUS_PENDING;

  if (mode === 'approve') {
    if (status === STATUS_PENDING) {
      return undefined;
    }
    const message =
      status === STATUS_APPROVED || status === STATUS_PUBLISHED
        ? `draft is already ${status}`
        : `draft status is "${status}" (approve accepts "${STATUS_PENDING}")`;
    return { kind: 'statusNotAccepted', message };
  }

  const accepted = input.cfg.governance.acceptStatuses.map((s) => s.trim().toLowerCase());
  if (accepted.includes(status)) {
    return undefined;
  }
  if (status === STATUS_PUBLISHED) {
    return { kind: 'statusNotAccepted', message: 'draft is already published' };
  }
  const list = accepted.length === 0 ? '(none configured)' : accepted.join(', ');
  return {
    kind: 'statusNotAccepted',
    message: `draft status is "${status}" (accepted: ${list})`,
  };
}

function requiredFieldMissing(input: GateInput): Blocker | undefined {
  const violations = input.violations ?? [];
  if (violations.length === 0) {
    return undefined;
  }
  const names = violations.map((v) => v.field.title ?? v.field.name);
  return {
    kind: 'requiredFieldMissing',
    message: `${names.length} required field${names.length === 1 ? '' : 's'} missing: ${names.join(', ')}`,
  };
}

function previewFailed(input: GateInput): Blocker | undefined {
  const error = input.previewError?.trim();
  if (!error) {
    return undefined;
  }
  return { kind: 'previewFailed', message: `preview failed: ${error}` };
}

/**
 * Every blocker that applies, in the fixed order. An empty array means the
 * action is allowed — by this gate. The caller still owns confirmation.
 */
export function evaluateGates(mode: GateMode, input: GateInput): Blocker[] {
  const checks: Array<Blocker | undefined> = [
    noWorkspace(input),
    mode === 'publish' ? publishDisabled(input) : undefined,
    guardError(input),
    alreadyPublished(input),
    statusNotAccepted(mode, input),
    requiredFieldMissing(input),
    previewFailed(input),
  ];
  return checks.filter((b): b is Blocker => b !== undefined);
}

/** Gates for flipping `pending` → `approved`. Publishing is not yet in play. */
export function evaluateApproveGates(input: GateInput): Blocker[] {
  return evaluateGates('approve', input);
}

/** Gates for sending a draft to a publish target. */
export function evaluatePublishGates(input: GateInput): Blocker[] {
  return evaluateGates('publish', input);
}

/** `true` when `kind` is among the blockers — for context keys and tests. */
export function hasBlocker(blockers: readonly Blocker[], kind: BlockerKind): boolean {
  return blockers.some((b) => b.kind === kind);
}

/**
 * The blocker note the UI renders: `a; b`. The caller supplies its own frame
 * (`Publish disabled: <note>.`) so the same summary works under a button, in a
 * modal, and in MCP prose.
 */
export function blockerSummary(blockers: readonly Blocker[]): string {
  return blockers.map((b) => b.message).join('; ');
}
