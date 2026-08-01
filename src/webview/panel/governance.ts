/**
 * The governance section — the one row of the panel that Front Matter never
 * had. It replaces the Git actions block with the state of the governed queue
 * for whatever file is open: draft status, what the brand guard found, whether
 * the ledger already knows this URL, and the three buttons that move a draft
 * along.
 *
 * **This section is advisory. It is not the gate.** Decision D5: every button
 * here posts `{type:'command', id, args:{draftPath}}` — an intent and a target,
 * nothing else. There is no payload that could carry `force`, no flag that
 * could say "skip the guard", and no way to name a draft that is not on disk.
 * The host then re-reads the draft, re-runs the brand guard, re-evaluates
 * `evaluatePublishGates()` and asks modally, inside the *same* `doApprove` /
 * `doPublish` the command palette calls. A button that renders enabled when it
 * should not is a cosmetic bug, not an escalation.
 *
 * Two rendering rules come straight from the core:
 *
 *  - **`info` findings are filtered out of the list and drawn as the fold.**
 *    `guardText()` always emits exactly one `info` — the fold marker — so
 *    listing it would put a permanent "finding" under every clean draft. The
 *    honest rendering of "your hook has to land before character 140" is a rule
 *    drawn across the commentary at character 140, which is what this does.
 *  - **The blocker note is `blockerSummary()` verbatim**, framed as
 *    `Publish disabled: a; b.` The gate orders its blockers cheapest-and-most-
 *    fundamental first, so the sentence already leads with what to fix first;
 *    re-sorting or de-duplicating it here would make the panel and the modal
 *    disagree about the same draft.
 */

import { el, icon } from '../shared/dom';
import type {
  BlockerView,
  GovernanceState,
  GuardFindingView,
  PanelState,
} from '../shared/protocol';
import { staleOn, type Section } from '../shared/state';
import { commandButton, panelSection } from './chrome';

/**
 * Where a long post is visually truncated. Mirrors `FOLD` in
 * `src/core/governance/guard.ts` — the core module cannot be imported here
 * because it reads the filesystem, and a browser bundle must not. The
 * dashboard's `src/webview/dashboard/governance.ts` holds the third copy;
 * all three move together.
 */
export const FOLD = 140;

/**
 * The dashed rule drawn across the commentary at the fold.
 *
 * Byte-identical to `FOLD_LABEL` in `src/webview/dashboard/governance.ts`.
 * Deliberately names no vendor: decision D8 generalises publish away from any
 * single network, so the sentence says "feeds".
 */
const FOLD_LABEL = `… see more (feeds fold around ${FOLD} characters)`;

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

function statusPill(status: string): HTMLElement {
  const normalized = status.trim().toLowerCase();
  const known =
    normalized === 'pending' || normalized === 'approved' || normalized === 'published'
      ? `z-pill z-pill--${normalized}`
      : 'z-pill';
  return el('span', { class: known }, normalized === '' ? 'unknown' : normalized);
}

/**
 * The findings list: `error` and `warning` only.
 *
 * `info` is the fold marker and is drawn separately — see the header. A draft
 * with nothing to report gets one muted line rather than an empty box, because
 * "the guard ran and found nothing" and "the guard did not run" look identical
 * otherwise.
 */
function findings(guard: readonly GuardFindingView[]): HTMLElement {
  const listed = guard.filter((finding) => finding.level !== 'info');
  if (listed.length === 0) {
    return el('p', { class: 'z-muted' }, 'Brand guard: nothing to report.');
  }
  const list = el('ul', { class: 'governance__findings' });
  for (const finding of listed) {
    list.appendChild(
      el(
        'li',
        { class: `governance__finding governance__finding--${finding.level}` },
        icon(finding.level === 'error' ? 'error' : 'warning'),
        el('span', {}, finding.message),
      ),
    );
  }
  return list;
}

/**
 * The commentary with the fold rule drawn at 140 characters.
 *
 * Below the fold the text is muted rather than hidden: the author still needs
 * to read it, they just need to know which half of it a reader will see before
 * deciding whether to keep going. The rule is only drawn when there *is* a
 * second half.
 */
function commentary(text: string): HTMLElement | null {
  const trimmed = text.trim();
  if (trimmed === '') {
    return null;
  }
  const head = trimmed.slice(0, FOLD);
  const tail = trimmed.slice(FOLD);
  return el(
    'div',
    { class: 'governance__commentary' },
    el('p', {}, head),
    tail === '' ? null : el('div', { class: 'governance__fold' }, FOLD_LABEL),
    tail === '' ? null : el('p', { class: 'z-muted' }, tail),
  );
}

/** `Publish disabled: a; b.` — `blockerSummary()` in its UI frame. */
function blockedNote(label: string, blockers: readonly BlockerView[]): HTMLElement | null {
  if (blockers.length === 0) {
    return null;
  }
  const summary = blockers.map((blocker) => blocker.message).join('; ');
  return el('p', { class: 'governance__blocked' }, `${label} disabled: ${summary}.`);
}

function ledgerNote(governance: GovernanceState): HTMLElement | null {
  const ledger = governance.ledger;
  if (ledger === null) {
    return null;
  }
  const when = ledger.postedAt === '' ? '' : ` on ${ledger.postedAt}`;
  return el(
    'p',
    { class: 'governance__ledger', title: ledger.url },
    `Already published as ${ledger.urn}${when}.`,
  );
}

// ---------------------------------------------------------------------------
// The section
// ---------------------------------------------------------------------------

function body(state: PanelState, governance: GovernanceState): HTMLElement[] {
  const draft = governance.draft;
  const parts: HTMLElement[] = [];

  if (draft === null) {
    parts.push(
      el(
        'p',
        { class: 'z-muted' },
        state.filePath === null
          ? 'Open a content file to draft an update about it.'
          : 'No draft in the queue for this file.',
      ),
    );
  } else {
    parts.push(
      el(
        'div',
        { class: 'governance__status' },
        statusPill(draft.status),
        el('span', { title: draft.path }, draft.name),
      ),
    );
    const fold = commentary(draft.commentary);
    if (fold !== null) {
      parts.push(fold);
    }
    parts.push(findings(governance.guard));
    const ledger = ledgerNote(governance);
    if (ledger !== null) {
      parts.push(ledger);
    }
  }

  // The approve note is only interesting once there is something to approve;
  // with no draft the publish note would just repeat "there is no draft".
  if (draft !== null) {
    const approveNote = blockedNote('Approve', governance.approveBlockers);
    if (approveNote !== null) {
      parts.push(approveNote);
    }
    const publishNote = blockedNote('Publish', governance.publishBlockers);
    if (publishNote !== null) {
      parts.push(publishNote);
    }
  }

  const actions = el('div', { class: 'governance__actions governance__block' });
  actions.appendChild(
    commandButton({
      label: 'Create draft',
      id: 'draft.new',
      title: 'Draft an update about this file',
      disabled: state.filePath === null,
      // The target: which file the draft is about. Nothing else travels.
      ...(state.filePath === null ? {} : { args: { path: state.filePath } }),
    }),
  );
  actions.appendChild(
    commandButton({
      label: 'Approve',
      id: 'draft.approve',
      title: 'Approve this draft for publishing',
      secondary: true,
      disabled: draft === null || draft.status.trim().toLowerCase() !== 'pending',
      ...(draft === null ? {} : { args: { draftPath: draft.path } }),
    }),
  );
  actions.appendChild(
    commandButton({
      label: 'Publish',
      id: 'draft.publish',
      title: `Publish with the "${governance.target}" target`,
      secondary: true,
      disabled: draft === null || governance.publishBlockers.length > 0,
      ...(draft === null ? {} : { args: { draftPath: draft.path } }),
    }),
  );
  parts.push(actions);

  return parts;
}

export const governanceSection: Section<PanelState> = {
  id: 'governance',
  stale: staleOn(
    (state) => state.sections.includes('governance'),
    (state) => state.filePath,
    (state) => state.governance?.enabled ?? false,
    (state) => state.governance?.draft?.path ?? null,
    (state) => state.governance?.draft?.status ?? null,
    (state) => state.governance?.draft?.commentary ?? null,
    (state) => state.governance?.guard.map((f) => `${f.level}:${f.message}`).join('|') ?? '',
    (state) => state.governance?.approveBlockers.map((b) => b.message).join('|') ?? '',
    (state) => state.governance?.publishBlockers.map((b) => b.message).join('|') ?? '',
    (state) => state.governance?.ledger?.urn ?? null,
    (state) => state.governance?.target ?? '',
  ),
  render(state, host) {
    const governance = state.governance;
    if (!state.sections.includes('governance') || governance === null || !governance.enabled) {
      return;
    }
    host.appendChild(
      panelSection(
        {
          id: 'governance',
          title: 'Governance',
          hasFile: state.filePath !== null,
          className: 'governance__block',
        },
        ...body(state, governance),
      ),
    );
  },
};
