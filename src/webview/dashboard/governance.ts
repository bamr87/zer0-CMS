/**
 * The Drafts route — the governed queue on the left, the review pane on the
 * right. PLAN §3.2 calls this "the single highest-value screen in the product",
 * and it is the one screen where a rendering decision could be mistaken for a
 * permission decision. It is not.
 *
 * **Decision D5, restated because this is where it matters.** Approve and
 * Publish post `{type:'command', id, args:{draftPath}}` — an intent and a
 * target. There is no `force`, no `skipGuard`, no resolved artifact travelling
 * back up the wire. The host re-reads the draft from disk, re-runs the brand
 * guard, re-evaluates `evaluateGates()` and asks for confirmation inside the
 * *same* `doApprove` / `doPublish` the command palette calls. A button that
 * renders enabled when the gate says otherwise is a cosmetic bug; it is not an
 * escalation, and nothing here can make it one.
 *
 * Two rendering rules come straight out of `core/governance/`:
 *
 *  - **`info` findings are filtered from the list and drawn as the fold.**
 *    `guardText()` always emits exactly one `info` — the fold preview — so
 *    listing it would hang a permanent "finding" under every clean draft. The
 *    honest rendering of "the hook has to land before character 140" is a rule
 *    drawn across the commentary at character 140, which is what this does.
 *  - **The blocker note is the gate's own order, verbatim.** `evaluateGates()`
 *    returns blockers cheapest-and-most-fundamental first, so the sentence
 *    already leads with what to fix first. Re-sorting or de-duplicating it here
 *    would make this screen and the confirmation modal disagree about the same
 *    draft.
 */

import { clear, el, icon } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type {
  BlockerView,
  CommandId,
  DashboardState,
  DraftSummary,
  DraftsState,
  GuardFindingView,
  ReviewState,
} from '../shared/protocol';

/**
 * Where a long post is visually truncated. Mirrors `FOLD` in
 * `src/core/governance/guard.ts`; that module reads the filesystem, so a
 * browser bundle cannot import it. If one moves, move the other — and the
 * third copy, in `src/webview/panel/governance.ts`, moves with them.
 */
export const FOLD = 140;

/**
 * The dashed rule drawn across the commentary at the fold.
 *
 * Byte-identical to `FOLD_LABEL` in `src/webview/panel/governance.ts`: the two
 * surfaces describe one rule, and a reader who sees both must not be told two
 * different things. No vendor is named — decision D8 generalises publish away
 * from any single network, so the sentence says "feeds", not "LinkedIn".
 */
export const FOLD_LABEL = `… see more (feeds fold around ${FOLD} characters)`;

/** Lifecycle order, matching `DRAFT_STATUSES` in `core/governance/drafts.ts`. */
const GROUPS: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'pending', label: 'Pending' },
  { id: 'approved', label: 'Approved' },
  { id: 'published', label: 'Published' },
  { id: 'other', label: 'Other' },
];

// ---------------------------------------------------------------------------
// Small shared pieces
// ---------------------------------------------------------------------------

function post(id: CommandId, args?: unknown): void {
  getMessenger().command(id, args);
}

function statusOf(draft: DraftSummary): string {
  return draft.status.trim().toLowerCase();
}

/**
 * The status badge.
 *
 * `pending` borrows the "scheduled" amber because it is the one status that
 * asks something of the reader; an unrecognised status borrows the "draft" red
 * because it means the queue holds a file nobody's lifecycle knows about. The
 * dashboard bundle does not load `panel.css`, so the panel's `.z-pill--*`
 * variants are deliberately not used here.
 */
function statusBadge(status: string): HTMLElement {
  const normalized = status === '' ? 'unknown' : status;
  const known = normalized === 'pending' || normalized === 'approved' || normalized === 'published';
  const variant =
    normalized === 'pending' ? ' z-status--scheduled' : known ? '' : ' z-status--draft';
  return el('span', { class: `z-status${variant}` }, normalized);
}

/** `counts` is a fixed four-key record; a switch keeps the access checked. */
function countFor(counts: DraftsState['counts'], group: string): number {
  switch (group) {
    case 'pending':
      return counts.pending;
    case 'approved':
      return counts.approved;
    case 'published':
      return counts.published;
    default:
      return counts.other;
  }
}

function inGroup(draft: DraftSummary, group: string): boolean {
  const status = statusOf(draft);
  if (group === 'other') {
    return status !== 'pending' && status !== 'approved' && status !== 'published';
  }
  return status === group;
}

export interface ActionOptions {
  label: string;
  id: CommandId;
  title?: string;
  args?: unknown;
  disabled?: boolean;
  secondary?: boolean;
}

function actionButton(options: ActionOptions): HTMLElement {
  return el(
    'button',
    {
      class: options.secondary === true ? 'z-btn z-btn--secondary' : 'z-btn',
      type: 'button',
      title: options.title ?? options.label,
      disabled: options.disabled === true,
      onclick: () => {
        post(options.id, options.args);
      },
    },
    options.label,
  );
}

// ---------------------------------------------------------------------------
// The queue
// ---------------------------------------------------------------------------

function queueItem(draft: DraftSummary, selected: boolean): HTMLElement {
  const title = draft.title.trim() === '' ? draft.name : draft.title.trim();
  const button = el(
    'button',
    {
      class: selected ? 'z-drafts__item is-selected' : 'z-drafts__item',
      type: 'button',
      title: draft.path,
      attrs: { 'aria-current': selected ? 'true' : 'false' },
      onclick: () => {
        // Remember the selection locally so a reload lands on the same draft,
        // then ask the host to build the review. The host owns `selected` —
        // this is a hint, not a decision.
        getMessenger().setState({ draft: draft.path });
        post('draft.review', { draftPath: draft.path });
      },
    },
    el('span', {}, title),
    el('span', { class: 'z-date' }, draft.name),
  );
  return el('li', {}, button);
}

function queueGroup(group: { id: string; label: string }, drafts: DraftsState): HTMLElement | null {
  const items = drafts.drafts.filter((draft) => inGroup(draft, group.id));
  // An empty `other` bucket is noise; the three lifecycle groups are always
  // drawn so the queue's shape is legible even when a stage is empty.
  if (items.length === 0 && group.id === 'other') {
    return null;
  }
  const list = el('ul', { class: 'z-drafts__list' });
  for (const draft of items) {
    list.appendChild(queueItem(draft, draft.path === drafts.selected));
  }
  if (items.length === 0) {
    list.appendChild(el('li', { class: 'z-muted' }, 'Nothing here.'));
  }
  return el(
    'div',
    { class: 'z-drafts__group' },
    el(
      'div',
      { class: 'z-drafts__grouptitle' },
      el('span', {}, group.label),
      el('span', {}, String(countFor(drafts.counts, group.id))),
    ),
    list,
  );
}

function queue(drafts: DraftsState): HTMLElement {
  const root = el('div', { class: 'z-drafts__queue' });
  root.appendChild(
    el(
      'div',
      { class: 'z-drafts__grouptitle' },
      el('span', {}, 'Draft queue'),
      actionButton({ label: 'New draft', id: 'draft.new', secondary: true }),
    ),
  );
  for (const group of GROUPS) {
    const rendered = queueGroup(group, drafts);
    if (rendered !== null) {
      root.appendChild(rendered);
    }
  }
  return root;
}

// ---------------------------------------------------------------------------
// The review pane
// ---------------------------------------------------------------------------

/** A small uppercase label; `.z-drafts__grouptitle` is the bare version. */
function heading(text: string): HTMLElement {
  return el('div', { class: 'z-drafts__grouptitle' }, el('span', {}, text));
}

/**
 * The commentary, with the fold rule drawn at exactly 140 characters.
 *
 * Below the fold the text is muted rather than hidden: the author still has to
 * read it, they just need to know which half a reader sees before deciding
 * whether to keep going. The rule is drawn **only** when there is a second
 * half — a 90-character post has no fold, and drawing one would be a lie.
 */
export function commentaryBlock(text: string): HTMLElement | null {
  const trimmed = text.trim();
  if (trimmed === '') {
    return null;
  }
  const head = trimmed.slice(0, FOLD);
  const tail = trimmed.slice(FOLD);
  return el(
    'div',
    {},
    heading('Commentary'),
    el('p', { class: 'z-review__commentary' }, head),
    tail === '' ? null : el('div', { class: 'z-review__fold' }, FOLD_LABEL),
    tail === '' ? null : el('p', { class: 'z-review__commentary z-muted' }, tail),
  );
}

/**
 * The findings list: `error` and `warning` only.
 *
 * The single `info` is the fold preview and is drawn as the rule above. A draft
 * with nothing to report gets one muted line, because "the guard ran and found
 * nothing" and "the guard never ran" look identical otherwise.
 */
export function findingsList(guard: readonly GuardFindingView[]): HTMLElement {
  const listed = guard.filter((finding) => finding.level !== 'info');
  if (listed.length === 0) {
    return el('p', { class: 'z-muted' }, 'Brand guard: nothing to report.');
  }
  const list = el('ul', { class: 'z-drafts__list' });
  for (const finding of listed) {
    list.appendChild(
      el(
        'li',
        // The level travels as data, not as a class: `dashboard.css` has no
        // finding rules, and the two codicons already carry the distinction.
        { dataset: { level: finding.level } },
        el('span', { class: 'z-valid z-valid--warn' }, icon(finding.level === 'error' ? 'error' : 'warning')),
        el('span', {}, finding.message),
      ),
    );
  }
  return list;
}

/** `Publish disabled: a; b.` — the gate's own summary, in its UI frame. */
export function blockerNote(label: string, blockers: readonly BlockerView[]): HTMLElement | null {
  if (blockers.length === 0) {
    return null;
  }
  return el(
    'p',
    { class: 'z-review__blockers' },
    `${label} disabled: ${blockers.map((blocker) => blocker.message).join('; ')}.`,
  );
}

function ledgerNote(review: ReviewState): HTMLElement | null {
  const ledger = review.ledger;
  if (ledger === null) {
    return null;
  }
  const when = ledger.postedAt === '' ? '' : ` on ${ledger.postedAt}`;
  return el(
    'p',
    { class: 'z-muted', title: ledger.url },
    `Already published as ${ledger.urn}${when}.`,
  );
}

/**
 * Approve is enabled only for a `pending` draft and relabels to `Approved`
 * once the draft has moved on — a disabled button whose label still reads
 * "Approve" reads as "refused", which is the wrong story for a draft that has
 * already been approved.
 */
function approveLabel(status: string): string {
  return status === 'approved' || status === 'published' ? 'Approved' : 'Approve';
}

function reviewPane(review: ReviewState): HTMLElement {
  const draft = review.draft;
  const status = statusOf(draft);
  const title = draft.title.trim() === '' ? draft.name : draft.title.trim();

  const root = el('div', { class: 'z-review' });

  root.appendChild(
    el(
      'div',
      { class: 'z-drafts__grouptitle' },
      el('span', {}, title),
      statusBadge(status),
    ),
  );
  root.appendChild(el('p', { class: 'z-date', title: draft.path }, draft.name));
  if (draft.description.trim() !== '') {
    root.appendChild(el('p', {}, draft.description.trim()));
  }
  if (draft.source !== null && draft.source.trim() !== '') {
    root.appendChild(el('p', { class: 'z-muted' }, `Source: ${draft.source.trim()}`));
  }

  const commentary = commentaryBlock(draft.commentary);
  if (commentary !== null) {
    root.appendChild(commentary);
  }

  root.appendChild(heading('Brand guard'));
  root.appendChild(findingsList(review.guard));

  const ledger = ledgerNote(review);
  if (ledger !== null) {
    root.appendChild(ledger);
  }

  if (review.artifact.trim() !== '') {
    root.appendChild(heading('Artifact'));
    root.appendChild(el('pre', { class: 'z-review__artifact' }, review.artifact));
  }

  const approveBlocked = blockerNote('Approve', review.approveBlockers);
  if (approveBlocked !== null) {
    root.appendChild(approveBlocked);
  }
  const publishBlocked = blockerNote('Publish', review.publishBlockers);
  if (publishBlocked !== null) {
    root.appendChild(publishBlocked);
  }

  root.appendChild(
    el(
      'div',
      { class: 'z-review__actions' },
      // Exactly one argument travels: which draft. See the file header.
      actionButton({
        label: approveLabel(status),
        id: 'draft.approve',
        title: 'Approve this draft for publishing',
        disabled: status !== 'pending',
        args: { draftPath: draft.path },
      }),
      actionButton({
        label: 'Publish',
        id: 'draft.publish',
        title: 'Publish this draft',
        secondary: true,
        disabled: review.publishBlockers.length > 0,
        args: { draftPath: draft.path },
      }),
      actionButton({
        label: 'Open draft',
        id: 'openFile',
        title: draft.path,
        secondary: true,
        args: { path: draft.path },
      }),
    ),
  );

  return root;
}

// ---------------------------------------------------------------------------
// The route
// ---------------------------------------------------------------------------

function emptyState(message: string, hint: string): HTMLElement {
  return el(
    'div',
    { class: 'z-emptystate' },
    icon('inbox'),
    el('p', {}, message),
    el('p', { class: 'z-muted' }, hint),
  );
}

export function render(host: HTMLElement, state: DashboardState): void {
  clear(host);
  const drafts = state.drafts;

  if (!drafts.enabled) {
    host.appendChild(
      emptyState(
        'Governance is off.',
        'Set "zer0Cms.governance.enabled" to true to use the draft queue.',
      ),
    );
    return;
  }

  if (drafts.drafts.length === 0) {
    const empty = emptyState(
      'The draft queue is empty.',
      'A draft is a markdown file in the queue folder: front matter, a status, and the text that publishes.',
    );
    empty.appendChild(
      el('div', { class: 'z-review__actions' }, actionButton({ label: 'New draft', id: 'draft.new' })),
    );
    host.appendChild(empty);
    return;
  }

  const root = el('div', { class: 'z-drafts' }, queue(drafts));
  root.appendChild(
    drafts.review === null
      ? el(
          'div',
          { class: 'z-review' },
          el('p', { class: 'z-muted' }, 'Select a draft to review it.'),
        )
      : reviewPane(drafts.review),
  );
  host.appendChild(root);
}
