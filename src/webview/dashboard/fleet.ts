/**
 * The Fleet route — this repository's AI lanes as `fleet.manifest.yml`
 * declares them, with what the repository last said about each: the switch
 * value and the newest run.
 *
 * **Decision D5, again, because this screen has two buttons that write to
 * another system.** Toggle and Dispatch post `{type:'command', id, args:{lane}}`
 * — a lane id and nothing else. Not the new switch value (the host derives it
 * from the variable it fetches a moment later), not a ref, not a `force`. The
 * host re-reads the manifest from disk, re-runs `evaluateFleetGates()`, obtains
 * the credential lazily and asks modally, inside the *same* `doToggleSwitch` /
 * `doDispatchLane` the command palette calls. A button that renders enabled
 * when the gate says otherwise is a cosmetic bug, not an escalation.
 *
 * The switch pill has four honest states. `true`/`false` are what the
 * variable holds; `unset` means the API said 404 (the lane is off); `unknown`
 * means nobody has asked — there is no credential, or the tab was opened
 * without one — and the note above the table says so rather than letting a
 * grey pill imply an answer. An ungated lane (`switch: null`) draws a dash.
 *
 * The blocker notes under a disabled button come from the host's advisory
 * `evaluateFleetGates()` and are rendered in the gate's own order, verbatim,
 * for the same reason the Drafts route does it: re-sorting them here would
 * make this screen and the confirmation modal disagree about the same lane.
 */

import { clear, el, icon } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type {
  BlockerView,
  CommandId,
  DashboardState,
  FleetLaneView,
  FleetRunView,
  FleetState,
} from '../shared/protocol';

function post(id: CommandId, args?: unknown): void {
  getMessenger().command(id, args);
}

// ---------------------------------------------------------------------------
// Cells
// ---------------------------------------------------------------------------

/**
 * The switch pill. `true` borrows the "scheduled" amber because an armed lane
 * is one that will spend tokens on its own; `unknown` borrows the "draft" red
 * because it is the one state that is not an answer.
 */
function switchCell(lane: FleetLaneView): HTMLElement {
  if (lane.switch === null) {
    return el('td', { class: 'z-fleet__switch' }, el('span', { class: 'z-fleet__unknown', title: 'ungated — this lane has no *_ENABLED switch' }, '—'));
  }
  const value = lane.switchValue;
  const variant =
    value === 'true' ? ' z-status--scheduled' : value === 'unknown' ? ' z-status--draft' : '';
  return el(
    'td',
    { class: 'z-fleet__switch' },
    el('code', { class: 'z-fleet__var' }, lane.switch),
    el('span', { class: `z-status${variant}`, title: `${lane.switch} = ${value}` }, value),
  );
}

function runCell(run: FleetRunView | null): HTMLElement {
  if (run === null) {
    return el('td', {}, el('span', { class: 'z-fleet__unknown' }, 'no run on record'));
  }
  const label = run.conclusion === null ? run.status : `${run.status} · ${run.conclusion}`;
  const variant =
    run.conclusion === 'success'
      ? ' z-fleet__run--ok'
      : run.conclusion === 'failure' || run.conclusion === 'timed_out'
        ? ' z-fleet__run--bad'
        : '';
  const stamp = el('span', { class: 'z-date' }, run.updatedAt);
  if (run.url === '') {
    return el('td', {}, el('span', { class: `z-fleet__run${variant}` }, label), ' ', stamp);
  }
  return el(
    'td',
    {},
    el(
      'button',
      {
        class: `z-fleet__link z-fleet__run${variant}`,
        type: 'button',
        title: run.url,
        onclick: () => {
          post('openLink', { url: run.url });
        },
      },
      label,
    ),
    ' ',
    stamp,
  );
}

function blockerNote(verb: string, blockers: readonly BlockerView[]): HTMLElement | null {
  if (blockers.length === 0) {
    return null;
  }
  return el(
    'div',
    { class: 'z-fleet__blockers' },
    `${verb} disabled: ${blockers.map((b) => b.message).join('; ')}.`,
  );
}

function actionButton(label: string, id: CommandId, laneId: string, blockers: readonly BlockerView[]): HTMLElement {
  return el(
    'button',
    {
      class: 'z-btn z-btn--secondary',
      type: 'button',
      disabled: blockers.length > 0,
      title: blockers.length === 0 ? `${label} "${laneId}" — the host will ask first` : blockers.map((b) => b.message).join('; '),
      onclick: () => {
        // A lane id, and nothing else. See the module comment.
        post(id, { lane: laneId });
      },
    },
    label,
  );
}

function actionsCell(lane: FleetLaneView): HTMLElement {
  const toggleLabel = lane.switchValue === 'true' ? 'Switch off' : 'Switch on';
  return el(
    'td',
    { class: 'z-fleet__actions' },
    el(
      'div',
      { class: 'z-review__actions' },
      actionButton(toggleLabel, 'fleet.toggleSwitch', lane.id, lane.toggleBlockers),
      actionButton('Dispatch', 'fleet.dispatchLane', lane.id, lane.dispatchBlockers),
    ),
    blockerNote('Toggle', lane.toggleBlockers),
    blockerNote('Dispatch', lane.dispatchBlockers),
  );
}

function laneRow(lane: FleetLaneView): HTMLElement {
  return el(
    'tr',
    {},
    el(
      'td',
      { class: 'z-fleet__lane' },
      el('strong', {}, lane.id),
      el('div', { class: 'z-fleet__description' }, lane.description),
      el('code', { class: 'z-fleet__file', title: lane.implementation }, lane.implementation || '(no workflow)'),
    ),
    el('td', {}, lane.kind),
    el('td', {}, el('code', {}, lane.harness)),
    el(
      'td',
      { class: 'z-fleet__triggers' },
      lane.triggers,
      el('div', { class: 'z-fleet__guardrails', title: 'guardrails, as the manifest declares them' }, lane.guardrails),
    ),
    switchCell(lane),
    runCell(lane.lastRun),
    actionsCell(lane),
  );
}

function headRow(): HTMLElement {
  return el(
    'thead',
    {},
    el(
      'tr',
      {},
      ...['Lane', 'Kind', 'Harness', 'Triggers · guardrails', 'Switch', 'Last run', 'Actions'].map((label) =>
        el('th', { scope: 'col' }, label),
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// The route
// ---------------------------------------------------------------------------

function toolbar(fleet: FleetState): HTMLElement {
  const refresh = el(
    'button',
    {
      class: 'z-btn',
      type: 'button',
      title: 'Read the switches and newest runs from GitHub (may ask you to sign in)',
      onclick: () => {
        post('fleet.refresh');
      },
    },
    icon('refresh'),
    ' Refresh',
  );
  const where =
    fleet.fetchedAt === null
      ? 'Switch values and runs have not been read — press Refresh to sign in and read them.'
      : `Read from GitHub at ${fleet.fetchedAt}.`;
  return el(
    'div',
    { class: 'z-fleet__toolbar' },
    el(
      'div',
      { class: 'z-fleet__heading' },
      el('span', { class: 'z-lane__title' }, icon('server-process'), fleet.repo ?? 'Fleet'),
      el('div', { class: 'z-lane__hint' }, fleet.summary),
      el(
        'div',
        { class: 'z-lane__hint' },
        `${fleet.manifestPath} · provenance ${fleet.provenance} · ${fleet.lanes.length} lane${fleet.lanes.length === 1 ? '' : 's'}`,
      ),
    ),
    el(
      'div',
      { class: 'z-fleet__status' },
      refresh,
      el('div', { class: 'z-fleet__note' }, where),
      fleet.note === null ? null : el('div', { class: 'z-fleet__note z-fleet__note--warn' }, fleet.note),
      fleet.dispatchAllow
        ? null
        : el(
            'div',
            { class: 'z-fleet__note' },
            'Read-only: set "zer0Cms.fleet.dispatchAllow" in your own settings to enable Switch and Dispatch.',
          ),
    ),
  );
}

function tokens(fleet: FleetState): HTMLElement | null {
  if (fleet.tokens.length === 0) {
    return null;
  }
  const body = el('tbody', {});
  for (const token of fleet.tokens) {
    body.appendChild(
      el(
        'tr',
        {},
        el('td', {}, el('code', {}, token.name)),
        el('td', {}, token.scope),
        el('td', {}, token.required ? 'required' : 'optional'),
        el('td', {}, token.purpose),
        el('td', {}, token.usedBy.join(', ')),
      ),
    );
  }
  return el(
    'section',
    { class: 'z-lane z-fleet__tokens' },
    el('div', { class: 'z-lane__title' }, icon('key'), 'Tokens'),
    el('div', { class: 'z-lane__hint' }, 'Declared by the manifest. Names only — no value is ever read by this console.'),
    el(
      'div',
      { class: 'z-table__scroll' },
      el(
        'table',
        { class: 'z-table' },
        el('thead', {}, el('tr', {}, ...['Name', 'Scope', 'Required', 'Purpose', 'Used by'].map((h) => el('th', { scope: 'col' }, h)))),
        body,
      ),
    ),
  );
}

export function render(host: HTMLElement, state: DashboardState): void {
  clear(host);
  const fleet = state.fleet;

  if (fleet === null || !fleet.enabled) {
    host.appendChild(
      el(
        'div',
        { class: 'z-emptystate' },
        icon('server-process'),
        el('p', {}, 'The Fleet console is off.'),
        el('p', { class: 'z-muted' }, 'Set "zer0Cms.fleet.enabled" to true to read this repository\'s lanes.'),
      ),
    );
    return;
  }

  if (fleet.repo === null) {
    host.appendChild(
      el(
        'div',
        { class: 'z-emptystate' },
        icon('server-process'),
        el('p', {}, 'No fleet manifest.'),
        el('p', { class: 'z-muted' }, `${fleet.manifestPath}: ${fleet.reason ?? 'not found'}.`),
        el('p', { class: 'z-muted' }, 'Run "wtd fleet adopt" in the repository to write one, or point "zer0Cms.fleet.manifestPath" at it.'),
      ),
    );
    return;
  }

  host.appendChild(toolbar(fleet));

  const body = el('tbody', {});
  for (const lane of fleet.lanes) {
    body.appendChild(laneRow(lane));
  }
  host.appendChild(
    el(
      'section',
      { class: 'z-lane z-fleet' },
      fleet.lanes.length === 0
        ? el('p', { class: 'z-lane__empty' }, 'The manifest declares no lanes.')
        : el('div', { class: 'z-table__scroll' }, el('table', { class: 'z-table z-fleet__table' }, headRow(), body)),
    ),
  );

  const tokenTable = tokens(fleet);
  if (tokenTable !== null) {
    host.appendChild(tokenTable);
  }
}
