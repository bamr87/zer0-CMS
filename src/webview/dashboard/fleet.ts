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
 * That distinction now lives in `statusPill`'s `unknown` variant rather than in
 * this file, because five more tabs have to make it and three copies of "what
 * does a grey cell mean" is how two screens end up disagreeing about one lane.
 *
 * The blocker notes under a disabled button come from the host's advisory
 * `evaluateFleetGates()` and are rendered in the gate's own order, verbatim,
 * for the same reason the Drafts route does it: re-sorting them here would
 * make this screen and the confirmation modal disagree about the same lane.
 */

import {
  dataTable,
  emptyState,
  gatedButton,
  statusPill,
  type StatusVariant,
} from '../shared/components';
import { clear, el, icon, type Child } from '../shared/dom';
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
 * The switch pill. `true` is `warn` amber because an armed lane is one that
 * will spend tokens on its own; `unknown` is the variant that is not an answer.
 */
function switchVariant(value: string): StatusVariant {
  if (value === 'true') {
    return 'warn';
  }
  return value === 'unknown' ? 'unknown' : 'neutral';
}

function switchCell(lane: FleetLaneView): Child {
  if (lane.switch === null) {
    return el('span', { class: 'z-fleet__unknown', title: 'ungated — this lane has no *_ENABLED switch' }, '—');
  }
  const value = lane.switchValue;
  return el(
    'span',
    { class: 'z-fleet__switch' },
    el('code', { class: 'z-fleet__var' }, lane.switch),
    statusPill({ variant: switchVariant(value), text: value, title: `${lane.switch} = ${value}` }),
  );
}

function runCell(run: FleetRunView | null): Child {
  if (run === null) {
    return el('span', { class: 'z-fleet__unknown' }, 'no run on record');
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
    return [el('span', { class: `z-fleet__run${variant}` }, label), ' ', stamp];
  }
  return [
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
  ];
}

/** Toggle and Dispatch, each a courtesy over the host's advisory gate (D5). */
function actionsCell(lane: FleetLaneView): Child {
  const toggleLabel = lane.switchValue === 'true' ? 'Switch off' : 'Switch on';
  const button = (label: string, id: CommandId, blockers: readonly BlockerView[]): HTMLElement =>
    gatedButton({
      label,
      id,
      // A lane id, and nothing else. See the module comment.
      args: { lane: lane.id },
      blockers,
      // `Switch off disabled: …` is not a sentence; the verb the gate refuses
      // is the toggle, whatever the button happens to be offering right now.
      verb: id === 'fleet.toggleSwitch' ? 'Toggle' : label,
      title: `${label} "${lane.id}" — the host will ask first`,
      secondary: true,
    });
  return el(
    'div',
    { class: 'z-fleet__actions' },
    button(toggleLabel, 'fleet.toggleSwitch', lane.toggleBlockers),
    button('Dispatch', 'fleet.dispatchLane', lane.dispatchBlockers),
  );
}

const LANE_COLUMNS = [
  'Lane',
  'Kind',
  'Harness',
  'Triggers · guardrails',
  'Switch',
  'Last run',
  'Actions',
] as const;

function laneRow(lane: FleetLaneView): Child[] {
  return [
    el(
      'div',
      { class: 'z-fleet__lane' },
      el('strong', {}, lane.id),
      el('div', { class: 'z-fleet__description' }, lane.description),
      el('code', { class: 'z-fleet__file', title: lane.implementation }, lane.implementation || '(no workflow)'),
    ),
    lane.kind,
    el('code', {}, lane.harness),
    el(
      'div',
      { class: 'z-fleet__triggers' },
      lane.triggers,
      el('div', { class: 'z-fleet__guardrails', title: 'guardrails, as the manifest declares them' }, lane.guardrails),
    ),
    switchCell(lane),
    runCell(lane.lastRun),
    actionsCell(lane),
  ];
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
  return el(
    'section',
    { class: 'z-lane z-fleet__tokens' },
    el('div', { class: 'z-lane__title' }, icon('key'), 'Tokens'),
    el('div', { class: 'z-lane__hint' }, 'Declared by the manifest. Names only — no value is ever read by this console.'),
    dataTable({
      columns: ['Name', 'Scope', 'Required', 'Purpose', 'Used by'],
      label: 'Tokens the manifest declares',
      rows: fleet.tokens.map((token) => [
        el('code', {}, token.name),
        token.scope,
        token.required ? 'required' : 'optional',
        token.purpose,
        token.usedBy.join(', '),
      ]),
    }),
  );
}

export function render(host: HTMLElement, state: DashboardState): void {
  clear(host);
  const fleet = state.fleet;

  if (fleet === null || !fleet.enabled) {
    host.appendChild(
      emptyState({
        icon: 'server-process',
        message: 'The Fleet console is off.',
        hint: 'Set "zer0Cms.fleet.enabled" to true to read this repository\'s lanes.',
      }),
    );
    return;
  }

  if (fleet.repo === null) {
    host.appendChild(
      emptyState({
        icon: 'server-process',
        message: 'No fleet manifest.',
        hint: `${fleet.manifestPath}: ${fleet.reason ?? 'not found'}. Run "wtd fleet adopt" in the repository to write one, or point "zer0Cms.fleet.manifestPath" at it.`,
      }),
    );
    return;
  }

  host.appendChild(toolbar(fleet));

  host.appendChild(
    el(
      'section',
      { class: 'z-lane z-fleet' },
      dataTable({
        columns: [...LANE_COLUMNS],
        className: 'z-fleet__table',
        label: 'Fleet lanes',
        rows: fleet.lanes.map(laneRow),
        empty: 'The manifest declares no lanes.',
      }),
    ),
  );

  const tokenTable = tokens(fleet);
  if (tokenTable !== null) {
    host.appendChild(tokenTable);
  }
}
