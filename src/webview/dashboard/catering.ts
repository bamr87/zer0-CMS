/**
 * The Catering route — four distribution lanes and the button that writes them
 * to disk.
 *
 * This screen and `.cms/distribution/worklists/<date>-catering.md` are two
 * renderings of one `CateringPlan`. They must never disagree, so:
 *
 *  - the lane headings and the descriptive hints are the same sentences
 *    `core/catering/worklist.ts` emits;
 *  - the empty states are the host's, sourced from that same module (the
 *    constants below are only a fallback for a host that sent none);
 *  - the number formatting is `formatThousands` / `formatPercent` re-derived
 *    here, including Python's round-half-to-even, because the worklist's
 *    formatters live behind a module that reads the filesystem and cannot be
 *    imported into a browser bundle. If one changes, change the other — the
 *    golden worklist test pins the Python side of the contract.
 *
 * A health of `-1` means "the engine never scored this page", not "this page
 * scored minus one". It renders as an em dash, exactly as the worklist's
 * `healthCell` writes it. `.cms/` absence is a normal state (decision D9), so
 * an absent contract is an empty state and not an error.
 *
 * **Generate worklist** posts `catering.worklist` and nothing else. The host
 * re-reads the contract, the ledger and the performance file, rebuilds the
 * plan and writes the file — this screen's numbers are never the input to it.
 */

import { clear, el, icon } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type {
  CateringState,
  CommandId,
  ContentRecord,
  DashboardState,
  TopicSignalView,
} from '../shared/protocol';

/** Mirrors `MIN_OBSERVATIONS` in `core/catering/catering.ts`. */
export const MIN_OBSERVATIONS = 2;

/**
 * The italic empty states, mirrored from `LANE_EMPTY_STATES` in
 * `core/catering/worklist.ts` with the markdown emphasis underscores stripped.
 *
 * That module imports `../contract/contract`, which imports `node:fs`, so this
 * bundle cannot reach it — this is the only copy of these sentences that is
 * not the export. (`src/dashboard/dashboardPanel.ts` imports the real one and
 * ships it in `CateringState.emptyStates`, which is what normally renders;
 * these are the fallback for a host that sent a blank.) Edit a sentence in
 * `worklist.ts` and edit it here in the same commit.
 */
export const EMPTY_STATES = {
  undistributed: 'Everything publishable has been distributed.',
  /** Lane B when there is no audience data at all. */
  noEvidence:
    'No audience data yet. Topic rankings need published posts with statistics read back; ' +
    'until then this lane is empty rather than guessed.',
  /** Lane B when there is data but no topic clears the observation floor. */
  proven:
    `Not enough observations yet — a topic needs ${MIN_OBSERVATIONS} posts before ` +
    'its average means anything.',
  quiet: 'Nothing to report.',
  refresh: 'Nothing published has gone stale.',
} as const;

/** The descriptive line each lane carries when it has rows, from `worklist.ts`. */
const HINTS = {
  undistributed:
    'Content that scores well and has never been published off-site. No writing required, ' +
    'so this is the cheapest work on the list.',
  proven:
    'Topics at or above the median engagement rate, each with at least ' +
    `${MIN_OBSERVATIONS} posts behind it. Evidence, not a guarantee.`,
  quiet:
    'Topics below the median. Worth naming, because the alternative is repeating them by ' +
    'default. Low engagement is not the same as low value — a compliance post can matter ' +
    'and still be unpopular.',
  refresh:
    'Content that earned engagement and has since gone stale. Updating a page that already ' +
    'found its readers beats starting from nothing.',
} as const;

// ---------------------------------------------------------------------------
// Number formatting — Python parity, re-derived
// ---------------------------------------------------------------------------

/** Python's `round()`: half-to-even. `Math.round` rounds half up and diverges. */
export function roundHalfEven(x: number, digits: number): number {
  const scale = Math.pow(10, digits);
  const scaled = x * scale;
  const floor = Math.floor(scaled);
  const diff = scaled - floor;
  const eps = 1e-9;
  if (Math.abs(diff - 0.5) < eps) {
    return (floor % 2 === 0 ? floor : floor + 1) / scale;
  }
  return Math.round(scaled) / scale;
}

/** Python's `{:,}`. Hand-rolled: `toLocaleString` changes with the machine. */
export function formatThousands(n: number): string {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** Python's `{:.2%}` — rate × 100, two decimals, half-to-even. */
export function formatPercent(rate: number): string {
  const hundredths = rate * 10000;
  const floor = Math.floor(hundredths);
  const diff = hundredths - floor;
  const eps = 1e-9;
  const cents =
    Math.abs(diff - 0.5) < eps ? (floor % 2 === 0 ? floor : floor + 1) : Math.round(hundredths);
  return `${(cents / 100).toFixed(2)}%`;
}

/** Engagements per impression — the only rate comparable across topics. */
export function rateOf(signal: TopicSignalView): number {
  return signal.impressions ? roundHalfEven(signal.engagements / signal.impressions, 4) : 0;
}

// ---------------------------------------------------------------------------
// Cells
// ---------------------------------------------------------------------------

/** The score, or an em dash when the engine never scored it. Never `-1`. */
export function healthCell(health: number): HTMLElement {
  if (health >= 0) {
    return el('td', { class: 'z-table__num' }, String(health));
  }
  return el(
    'td',
    { class: 'z-table__num z-lane__unknown', title: 'The engine has not scored this page' },
    '—',
  );
}

function post(id: CommandId, args?: unknown): void {
  getMessenger().command(id, args);
}

/** The file cell: a monospaced path that opens the file when clicked. */
function fileCell(contentPath: string): HTMLElement {
  return el(
    'td',
    {},
    el(
      'button',
      {
        class: 'z-chip',
        type: 'button',
        title: `Open ${contentPath}`,
        onclick: () => {
          post('openFile', { path: contentPath });
        },
      },
      contentPath,
    ),
  );
}

function headRow(labels: readonly string[]): HTMLElement {
  const row = el('tr', {});
  for (const label of labels) {
    row.appendChild(el('th', { attrs: { scope: 'col' } }, label));
  }
  return el('thead', {}, row);
}

function table(labels: readonly string[], rows: readonly HTMLElement[]): HTMLElement {
  const body = el('tbody', {});
  for (const row of rows) {
    body.appendChild(row);
  }
  return el('div', { class: 'z-table__scroll' }, el('table', { class: 'z-table' }, headRow(labels), body));
}

/** Strip the worklist's markdown emphasis: `_sentence._` → `sentence.` */
function plain(sentence: string): string {
  const trimmed = sentence.trim();
  if (trimmed.length > 1 && trimmed.startsWith('_') && trimmed.endsWith('_')) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function emptyLine(sentence: string, fallback: string): HTMLElement {
  const text = plain(sentence) === '' ? fallback : plain(sentence);
  return el('p', { class: 'z-lane__empty' }, text);
}

function lane(title: string, hint: string, content: HTMLElement): HTMLElement {
  return el(
    'section',
    { class: 'z-lane' },
    el('h2', { class: 'z-lane__title' }, title),
    el('p', { class: 'z-lane__hint' }, hint),
    content,
  );
}

// ---------------------------------------------------------------------------
// The four lanes
// ---------------------------------------------------------------------------

function laneA(state: CateringState): HTMLElement {
  if (state.undistributed.length === 0) {
    return lane(
      'Lane A — Distribute what already exists',
      HINTS.undistributed,
      emptyLine(state.emptyStates.undistributed, EMPTY_STATES.undistributed),
    );
  }
  const rows = state.undistributed.map((record: ContentRecord, index: number) =>
    el(
      'tr',
      {},
      el('td', { class: 'z-table__num' }, String(index + 1)),
      healthCell(record.health),
      el('td', {}, record.freshness),
      el('td', {}, record.collection),
      fileCell(record.path),
    ),
  );
  return lane(
    'Lane A — Distribute what already exists',
    HINTS.undistributed,
    table(['#', 'Health', 'Fresh', 'Collection', 'File'], rows),
  );
}

function signalRows(signals: readonly TopicSignalView[]): HTMLElement[] {
  return signals.map((signal) =>
    el(
      'tr',
      {},
      el('td', {}, signal.topic),
      el('td', { class: 'z-table__num' }, String(signal.posts)),
      el('td', { class: 'z-table__num' }, formatThousands(signal.impressions)),
      el('td', { class: 'z-table__num' }, formatPercent(rateOf(signal))),
    ),
  );
}

const SIGNAL_COLUMNS = ['Topic', 'Posts', 'Impressions', 'Engagement rate'] as const;

function laneB(state: CateringState): HTMLElement {
  const title = 'Lane B — Write more of what landed';
  // The evidence gate comes first: with no observations at all, "not enough
  // observations" would be the wrong sentence — there is nothing to be short of.
  if (state.observations === 0) {
    return lane(title, HINTS.proven, emptyLine(state.emptyStates.proven, EMPTY_STATES.noEvidence));
  }
  if (state.proven.length === 0) {
    return lane(title, HINTS.proven, emptyLine(state.emptyStates.proven, EMPTY_STATES.proven));
  }
  return lane(title, HINTS.proven, table(SIGNAL_COLUMNS, signalRows(state.proven)));
}

function laneC(state: CateringState): HTMLElement {
  const title = 'Lane C — Say the quiet part';
  if (state.quiet.length === 0) {
    return lane(title, HINTS.quiet, emptyLine(state.emptyStates.quiet, EMPTY_STATES.quiet));
  }
  return lane(title, HINTS.quiet, table(SIGNAL_COLUMNS, signalRows(state.quiet)));
}

function laneD(state: CateringState): HTMLElement {
  const title = 'Lane D — Refresh what worked';
  if (state.refresh.length === 0) {
    return lane(title, HINTS.refresh, emptyLine(state.emptyStates.refresh, EMPTY_STATES.refresh));
  }
  const rows = state.refresh.map((record: ContentRecord) =>
    el('tr', {}, healthCell(record.health), el('td', {}, record.freshness), fileCell(record.path)),
  );
  return lane(title, HINTS.refresh, table(['Health', 'Fresh', 'File'], rows));
}

// ---------------------------------------------------------------------------
// The route
// ---------------------------------------------------------------------------

function toolbar(state: CateringState): HTMLElement {
  const observed =
    state.observations === 1
      ? '1 piece of content has statistics.'
      : `${formatThousands(state.observations)} pieces of content have statistics.`;
  const bar = el(
    'div',
    { class: 'z-toolbar' },
    el('div', { class: 'z-toolbar__group' }, el('p', { class: 'z-muted' }, observed)),
  );
  const actions = el(
    'div',
    { class: 'z-toolbar__group' },
    el(
      'button',
      {
        class: 'z-btn',
        type: 'button',
        title: 'Write the four lanes to .cms/distribution/worklists/',
        onclick: () => {
          post('catering.worklist');
        },
      },
      'Generate worklist',
    ),
  );
  if (state.lastWorklist !== null && state.lastWorklist.trim() !== '') {
    const last = state.lastWorklist;
    actions.appendChild(
      el(
        'button',
        {
          class: 'z-btn z-btn--secondary',
          type: 'button',
          title: last,
          onclick: () => {
            post('openFile', { path: last });
          },
        },
        'Open last worklist',
      ),
    );
  }
  bar.appendChild(actions);
  return bar;
}

export function render(host: HTMLElement, state: DashboardState): void {
  clear(host);
  const catering = state.catering;

  // `.cms/` absence is a normal state, not a failure — decision D9.
  if (catering === null || !catering.present) {
    host.appendChild(
      el(
        'div',
        { class: 'z-emptystate' },
        icon('graph'),
        el('p', {}, 'No content contract yet.'),
        el(
          'p',
          { class: 'z-muted' },
          'Run the CMS engine to build ".cms/", and distribution lanes appear here.',
        ),
        el(
          'div',
          { class: 'z-review__actions' },
          el(
            'button',
            {
              class: 'z-btn',
              type: 'button',
              onclick: () => {
                post('contract.run');
              },
            },
            'Run CMS engine',
          ),
        ),
      ),
    );
    return;
  }

  host.appendChild(toolbar(catering));
  host.appendChild(laneA(catering));
  host.appendChild(laneB(catering));
  host.appendChild(laneC(catering));
  host.appendChild(laneD(catering));
}
