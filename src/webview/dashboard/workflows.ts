/**
 * The Workflows route — the lane catalogue as read-only passports, and one form
 * for describing a lane that does not exist yet.
 *
 * **The catalogue is read-only by decision D-I.** This console operates lanes
 * inside the editor; it does not edit an arbitrary workflow's attributes in
 * place. A passport therefore says everything a person needs in order to
 * *understand* a lane — its workflow file, how it reaches a model, the variable
 * that stops it, whether a manual run bypasses that variable, its schedule, the
 * credentials it spends by name, the file its assertion reads — and offers no
 * button at all.
 *
 * The last column is the interesting one: **could this console have written this
 * lane?** For most of the fleet the answer is yes, and for some of it the answer
 * is no with reasons. Both are useful, and the reasons are the useful half:
 * "needs a dynamic matrix" is something a person can act on, and a bare
 * "unsupported" is not. lifehacker's content-review lane is the case worth
 * keeping in mind — it is bespoke because approximating it would silently drop a
 * loop-breaker guard that repository had to add after a workflow retriggered
 * itself forever. **Refusing well is the feature.**
 *
 * ### Decision D5, in a form
 *
 * The lane form is a `stagedForm` over `WorkflowsState.form` — rows the *host*
 * named, so this screen can only ever hand back a key the host itself offered.
 * Save posts one `{type:'setUiState', key, value}` per changed row into the
 * host's whitelist; nothing here posts a lane spec, a rendered file or a plan.
 * Preview asks the host to compute one with the `lanePreview` request and draws
 * exactly what comes back. Write posts `{spec:'<lane id>'}` — a lane id, and
 * nothing else — and the host re-reads the configuration, re-reads the inventory
 * and the manifest from disk, re-plans, re-runs `evaluateFleetGates('scaffold')`
 * and asks modally inside the same `doScaffoldLane` the command palette calls.
 *
 * Two consequences worth stating.
 *
 *  - **Preview is computed from what the host has, not from what is on the
 *    screen.** An unsaved edit therefore disables Preview with that sentence,
 *    rather than previewing a lane nobody described. The screen is not the
 *    source of truth, here as everywhere.
 *  - **The switch this action does not create is drawn beside the write
 *    button, not buried in the plan.** Writing a file somebody reviews and
 *    arming a loop to run are different powers; the host's modal says which one
 *    this is, and so does this screen.
 */

import {
  blockerNote,
  dataTable,
  diffView,
  emptyState,
  gatedButton,
  keyValueList,
  statusPill,
  type StatusVariant,
} from '../shared/components';
import { stagedChanges, stagedForm } from '../shared/form';
import { clear, el, icon, type Child } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type {
  BlockerView,
  CommandId,
  DashboardState,
  LanePassportView,
  WorkflowsState,
} from '../shared/protocol';

function post(id: CommandId, args?: unknown): void {
  getMessenger().command(id, args);
}

/** The `stagedForm` id. One form on this screen, and it says so out loud. */
export const LANE_FORM_KEY = 'lane';

/** How many diff lines one file shows before the rest is a count. */
export const MAX_DIFF_LINES = 400;

/** What each expressibility verdict means for a reader. */
const SHAPE_PROSE: Readonly<Record<string, string>> = {
  'ai-lane-caller':
    'a caller of the hub’s reusable ai-lane.yml — the gate, the bot guard, the concurrency group, the token probe and the result assertion all live upstream',
  'gate+claude-run':
    'the gate written out by hand plus the hub’s claude-run composite — what a fan-out or a switch that must hold for manual runs needs',
  bespoke:
    'this console will not generate it, and says why rather than rendering an approximation nobody asked for',
};

// ---------------------------------------------------------------------------
// View-local state
// ---------------------------------------------------------------------------

interface PreviewState {
  /** The lane id the reply belongs to. A late answer to another one is dropped. */
  spec: string;
  plan: NonNullable<WorkflowsState['plan']> | null;
  switchToCreateLater: string | null;
  refused: string | null;
}

interface WorkflowsUi {
  preview: PreviewState | null;
  /** The lane id a request is in flight for, so the button can say so. */
  pending: string | null;
  /** Which file's diff is expanded. One at a time; a whole plan is a lot of YAML. */
  openFile: string;
}

const ui: WorkflowsUi = { preview: null, pending: null, openFile: '' };

/** The host and snapshot of the last paint, so a click can repaint. */
let mounted: { host: HTMLElement; state: DashboardState } | undefined;

function repaint(): void {
  if (mounted !== undefined) {
    render(mounted.host, mounted.state);
  }
}

/** Test seam: forget the preview and the selection between suites. */
export function resetWorkflowsView(): void {
  ui.preview = null;
  ui.pending = null;
  ui.openFile = '';
  mounted = undefined;
}

// ---------------------------------------------------------------------------
// Cells
// ---------------------------------------------------------------------------

function shapeVariant(shape: string): StatusVariant {
  if (shape === 'bespoke') {
    return 'warn';
  }
  return shape === 'ai-lane-caller' || shape === 'gate+claude-run' ? 'ok' : 'neutral';
}

function severityVariant(severity: string): StatusVariant {
  if (severity === 'error' || severity === 'fail') {
    return 'danger';
  }
  return severity === 'warning' || severity === 'warn' ? 'warn' : 'neutral';
}

function unknown(text: string, title: string): HTMLElement {
  return el('span', { class: 'z-workflows__unknown', title }, text);
}

/** The expressibility verdict, with its reasons when it has any. */
function expressibilityCell(lane: LanePassportView): Child {
  const pill = statusPill({
    variant: shapeVariant(lane.expressibility),
    text: lane.expressibility,
    title: SHAPE_PROSE[lane.expressibility] ?? lane.expressibility,
  });
  if (lane.expressibilityReasons.length === 0) {
    return pill;
  }
  return el(
    'div',
    { class: 'z-workflows__shape' },
    pill,
    el(
      'ul',
      { class: 'z-workflows__reasons' },
      ...lane.expressibilityReasons.map((reason) => el('li', {}, reason)),
    ),
  );
}

function passportRow(lane: LanePassportView): Child[] {
  return [
    el(
      'div',
      { class: 'z-workflows__lane' },
      el('strong', {}, lane.id),
      lane.workflowPath === null
        ? unknown('no workflow file', 'the manifest names no implementation for this lane')
        : el(
            'button',
            {
              class: 'z-workflows__path',
              type: 'button',
              title: `Reveal ${lane.workflowPath}`,
              onclick: () => {
                post('revealFile', { path: lane.workflowPath });
              },
            },
            lane.workflowPath,
          ),
    ),
    el('code', {}, lane.runnerShape),
    lane.switch === null
      ? unknown('ungated', 'this lane has no *_ENABLED variable, so nothing stops it but editing the file')
      : el('code', {}, lane.switch),
    lane.dispatchBypassesSwitch === null
      ? unknown('—', 'no dispatch trigger, or no switch — the question does not apply')
      : statusPill({
          variant: lane.dispatchBypassesSwitch ? 'warn' : 'neutral',
          text: lane.dispatchBypassesSwitch ? 'bypasses' : 'respects',
          title: 'whether a manual run goes ahead with the switch off',
        }),
    lane.cron === null ? unknown('by hand only', 'no schedule') : el('code', {}, lane.cron),
    lane.tokens.length === 0
      ? unknown('none declared', 'the manifest declares no tokens for this lane')
      : el('span', { class: 'z-workflows__tokens' }, lane.tokens.join(', ')),
    lane.resultFile === null
      ? unknown('—', 'the workflow asserts on no result file')
      : el('code', {}, lane.resultFile),
    expressibilityCell(lane),
  ];
}

const PASSPORT_COLUMNS = [
  'Lane',
  'Runner',
  'Switch',
  'Manual run',
  'Schedule',
  { label: 'Tokens (names only)', title: 'the console shows names; it never reads a value' },
  'Result file',
  { label: 'Expressible?', title: 'could this console have generated this lane again?' },
];

function catalogue(workflows: WorkflowsState): HTMLElement {
  return el(
    'section',
    { class: 'z-lane z-workflows' },
    el('div', { class: 'z-lane__title' }, icon('run-all'), 'Lane passports'),
    el(
      'div',
      { class: 'z-lane__hint' },
      'Read-only: this console operates lanes, it does not rewrite somebody’s workflow in place. The last column is whether it could have generated the lane again — and for the ones it could not, why not.',
    ),
    dataTable({
      columns: PASSPORT_COLUMNS,
      className: 'z-workflows__table',
      label: 'The lane catalogue',
      rows: workflows.lanes.map(passportRow),
      empty:
        'This repository’s manifest declares no lanes. The form below is where the first one gets described.',
    }),
  );
}

// ---------------------------------------------------------------------------
// The plan
// ---------------------------------------------------------------------------

function diffBlock(file: { rel: string; exists: boolean; diff: string }): HTMLElement {
  const open = ui.openFile === file.rel;
  const lines = file.diff.split('\n');
  const shown = open ? lines.slice(0, MAX_DIFF_LINES).join('\n') : '';
  const header = el(
    'button',
    {
      class: 'z-workflows__file',
      type: 'button',
      title: open ? 'Hide this file' : 'Show every line this file would contain',
      onclick: () => {
        ui.openFile = open ? '' : file.rel;
        repaint();
      },
    },
    icon(open ? 'chevron-down' : 'chevron-right'),
    el('code', {}, file.rel),
    statusPill({
      variant: file.exists ? 'danger' : 'ok',
      text: file.exists ? 'already exists' : 'new file',
      title: file.exists
        ? 'the host refuses to write over a file that is already there'
        : 'nothing is at this path yet',
    }),
    el('span', { class: 'z-muted' }, `${lines.length} line${lines.length === 1 ? '' : 's'}`),
  );
  if (!open) {
    return el('div', { class: 'z-workflows__fileblock' }, header);
  }
  return el(
    'div',
    { class: 'z-workflows__fileblock' },
    header,
    diffView(shown),
    lines.length > MAX_DIFF_LINES
      ? el('p', { class: 'z-muted' }, `${lines.length - MAX_DIFF_LINES} more line(s) not drawn.`)
      : null,
  );
}

/** The findings the plan carries — the house rules and the engines' rulebook. */
function planFindings(plan: NonNullable<WorkflowsState['plan']>): HTMLElement | null {
  if (plan.audit.length === 0) {
    return el(
      'p',
      { class: 'z-muted' },
      'The lane passes its own preflight and the fleet’s audit rulebook — the same fifteen rules the Fleet tab grades other repositories with.',
    );
  }
  return dataTable({
    columns: ['Severity', 'Rule', 'What'],
    className: 'z-workflows__table',
    label: 'What the audit says about what would be written',
    rows: plan.audit.map((finding) => [
      statusPill({ variant: severityVariant(finding.severity), text: finding.severity }),
      el('code', {}, finding.rule),
      finding.message,
    ]),
  });
}

/**
 * The plan, or the refusal, or nothing yet.
 *
 * A `bespoke` shape gets its reasons and **no write button**. That is not a
 * degraded state to apologise for: the alternative is generating an
 * approximation of a workflow somebody wrote by hand for reasons this console
 * cannot see.
 */
function planSection(workflows: WorkflowsState, specId: string): HTMLElement {
  const preview = ui.preview;
  const body: Child[] = [];

  if (ui.pending !== null) {
    body.push(el('p', { class: 'z-muted' }, `Planning "${ui.pending}"…`));
  } else if (preview === null || preview.spec !== specId) {
    body.push(
      el(
        'p',
        { class: 'z-muted' },
        'Nothing has been planned yet. Preview renders every byte this would write, from the same computation the write itself uses.',
      ),
    );
  } else if (preview.refused !== null) {
    body.push(el('p', { class: 'z-workflows__refused' }, preview.refused));
  } else if (preview.plan !== null) {
    const plan = preview.plan;
    body.push(
      keyValueList([
        {
          key: 'Shape',
          value: el(
            'span',
            {},
            statusPill({ variant: shapeVariant(plan.shape), text: plan.shape }),
            ' ',
            el('span', { class: 'z-muted' }, SHAPE_PROSE[plan.shape] ?? ''),
          ),
        },
        {
          key: 'Files',
          value:
            plan.files.length === 0
              ? unknown('none', 'a bespoke lane renders nothing')
              : `${plan.files.length}`,
        },
        {
          key: 'Kill switch',
          value:
            preview.switchToCreateLater === null
              ? el(
                  'span',
                  { class: 'z-workflows__refused' },
                  'this lane declares none — which is why the audit below refuses it',
                )
              : el(
                  'span',
                  {},
                  el('code', {}, preview.switchToCreateLater),
                  ' ',
                  el(
                    'strong',
                    { class: 'z-workflows__notcreated' },
                    'is NOT created by this action.',
                  ),
                  ' ',
                  el(
                    'span',
                    { class: 'z-muted' },
                    'Writing files a person reviews and arming a loop to run are different powers. The lane stays inert until you create that repository variable yourself.',
                  ),
                ),
          title: 'the *_ENABLED variable the lane idles behind',
        },
      ]),
    );
    if (plan.reasons.length > 0) {
      body.push(
        el(
          'div',
          { class: 'z-workflows__shape' },
          el(
            'p',
            { class: 'z-lane__hint' },
            plan.shape === 'bespoke'
              ? 'Why this console will not write it:'
              : 'Why this shape rather than the simplest one:',
          ),
          el('ul', { class: 'z-workflows__reasons' }, ...plan.reasons.map((r) => el('li', {}, r))),
        ),
      );
    }
    body.push(...plan.files.map(diffBlock));
    const findings = planFindings(plan);
    if (findings !== null) {
      body.push(findings);
    }
  }

  return el(
    'section',
    { class: 'z-lane z-workflows__plan' },
    el('div', { class: 'z-lane__title' }, icon('diff'), 'What would be written'),
    el(
      'div',
      { class: 'z-lane__hint' },
      'Computed with nothing written, by the same planner the write uses — so this and the confirmation dialog cannot show you two different things.',
    ),
    ...body,
  );
}

// ---------------------------------------------------------------------------
// The form and the two buttons
// ---------------------------------------------------------------------------

/** The staged `Lane:id`, which is the target every intent on this screen names. */
function stagedSpecId(workflows: WorkflowsState): string {
  const pending = stagedChanges(LANE_FORM_KEY).find((change) => change.key === 'Lane:id');
  if (pending !== undefined) {
    return String(pending.value).trim();
  }
  const item = workflows.form.find((row) => row.key === 'Lane:id');
  return item === undefined ? '' : String(item.value).trim();
}

function requestPreview(specId: string): void {
  ui.pending = specId;
  ui.preview = null;
  repaint();
  getMessenger()
    .request<unknown>('lanePreview', { spec: specId })
    .then((value) => {
      if (ui.pending !== specId) {
        // The person moved on. A late answer to an abandoned question is
        // dropped rather than painted over the current one.
        return;
      }
      const reply = value as Partial<PreviewState> | null;
      ui.pending = null;
      ui.preview = {
        spec: specId,
        plan: reply?.plan ?? null,
        switchToCreateLater: reply?.switchToCreateLater ?? null,
        refused:
          reply?.refused ??
          (reply?.plan === null || reply?.plan === undefined ? 'the host returned no plan' : null),
      };
      repaint();
    })
    .catch((error: unknown) => {
      if (ui.pending !== specId) {
        return;
      }
      ui.pending = null;
      ui.preview = {
        spec: specId,
        plan: null,
        switchToCreateLater: null,
        refused: error instanceof Error ? error.message : String(error),
      };
      repaint();
    });
}

/**
 * Every reason the write button is disabled, in the host's own order, plus the
 * two this screen owns.
 *
 * The host's blockers come first and unchanged — re-sorting them here would make
 * this screen and the confirmation modal disagree about the same lane. The two
 * appended ones are facts about *this view*: no plan has been drawn yet, and the
 * plan that was drawn is one this console refuses to generate.
 */
function writeBlockers(workflows: WorkflowsState, specId: string): BlockerView[] {
  const blockers: BlockerView[] = [...workflows.scaffoldBlockers];
  const preview = ui.preview;
  if (preview === null || preview.spec !== specId || preview.plan === null) {
    blockers.push({
      kind: 'noPlan',
      message: 'preview it first — a person reads every line before this writes one',
    });
    return blockers;
  }
  if (preview.plan.shape === 'bespoke') {
    blockers.push({
      kind: 'notExpressible',
      message: `this lane needs a hand-written workflow: ${preview.plan.reasons.join('; ')}`,
    });
  }
  const fatal = preview.plan.audit.filter(
    (finding) => finding.severity === 'error' || finding.severity === 'fail',
  );
  if (fatal.length > 0) {
    blockers.push({
      kind: 'auditFailed',
      message: `the lane does not pass its own audit: ${fatal.map((f) => f.rule).join(', ')}`,
    });
  }
  return blockers;
}

function formSection(workflows: WorkflowsState): HTMLElement {
  const form = stagedForm({
    key: LANE_FORM_KEY,
    items: workflows.form,
    className: 'z-workflows__form',
    saveLabel: 'Save the description',
    onSave: (changes) => {
      // One `setUiState` per changed row, into the host's own whitelist. The
      // values are a draft, not a setting — which is why they go here rather
      // than through `updateSetting`.
      for (const change of changes) {
        getMessenger().post({ type: 'setUiState', key: change.key, value: String(change.value) });
      }
      // The description changed, so the plan on screen is of a different
      // question. Dropping it is cheaper than explaining it.
      ui.preview = null;
      ui.pending = null;
    },
    onCancel: () => {
      ui.preview = null;
      repaint();
    },
  });

  const specId = stagedSpecId(workflows);
  const dirty = stagedChanges(LANE_FORM_KEY).length > 0;

  const previewBlockers: BlockerView[] = [];
  if (specId === '') {
    previewBlockers.push({ kind: 'noLane', message: 'the lane has no id yet' });
  }
  if (dirty) {
    previewBlockers.push({
      kind: 'unsaved',
      message:
        'save the description first — the preview is computed from what the host has, not from what is on the screen',
    });
  }

  const preview = el(
    'button',
    {
      class: 'z-btn z-btn--secondary',
      type: 'button',
      disabled: previewBlockers.length > 0 || ui.pending !== null,
      title:
        previewBlockers.length > 0
          ? previewBlockers.map((blocker) => blocker.message).join('; ')
          : 'Render every byte this would write. Writes nothing.',
      onclick: () => {
        // Checked again at click time: typing does not repaint, so the disabled
        // state above can be one keystroke stale.
        if (stagedChanges(LANE_FORM_KEY).length > 0) {
          ui.preview = {
            spec: specId,
            plan: null,
            switchToCreateLater: null,
            refused:
              'there are unsaved edits — save the description, then preview. The host plans from its own copy, never from the screen.',
          };
          repaint();
          return;
        }
        requestPreview(specId);
      },
    },
    'Preview what would be written',
  );

  const note = blockerNote('Preview', previewBlockers, 'z-blockers');

  return el(
    'section',
    { class: 'z-lane z-workflows__describe' },
    el('div', { class: 'z-lane__title' }, icon('add'), 'Describe a new lane'),
    el(
      'div',
      { class: 'z-lane__hint' },
      `Generated against the vendored ai-runner kit${workflows.kitVersion === '' ? '' : ` v${workflows.kitVersion}`}. Everything else a lane needs — the project name, the platform, the runtime to set up, the permissions — is derived from this repository rather than asked for.`,
    ),
    form.el,
    el('div', { class: 'z-workflows__actions' }, preview, note),
  );
}

function writeSection(workflows: WorkflowsState, specId: string): HTMLElement {
  const blockers = writeBlockers(workflows, specId);
  const switchName = ui.preview?.spec === specId ? ui.preview.switchToCreateLater : null;
  return el(
    'section',
    { class: 'z-lane z-workflows__write' },
    el('div', { class: 'z-lane__title' }, icon('save'), 'Write the files'),
    el(
      'div',
      { class: 'z-lane__hint' },
      'The host re-reads the configuration, the inventory and the manifest from disk, plans again, re-runs the gate and asks you — naming every file and the variable it is not creating — before a byte lands.',
    ),
    switchName === null
      ? null
      : el(
          'p',
          { class: 'z-workflows__switchnote' },
          'This writes files only. ',
          el('code', {}, switchName),
          ' is ',
          el('strong', { class: 'z-workflows__notcreated' }, 'not'),
          ' created: the lane cannot run until you make that repository variable yourself.',
        ),
    gatedButton({
      label: 'Write these files',
      id: 'lane.scaffold',
      // A lane id, and nothing else. See the module comment, and decision D5.
      args: { spec: specId },
      blockers,
      verb: 'Write',
      title: `Write the files for "${specId}" — the host will ask first`,
    }),
    workflows.scaffoldAllow
      ? null
      : el(
          'p',
          { class: 'z-muted' },
          'Read-only: set "zer0Cms.fleet.scaffoldAllow" in your own settings to allow this console to write a lane into this folder.',
        ),
  );
}

// ---------------------------------------------------------------------------
// The route
// ---------------------------------------------------------------------------

export function render(host: HTMLElement, state: DashboardState): void {
  mounted = { host, state };
  clear(host);
  const workflows = state.workflows ?? null;

  if (workflows === null) {
    host.appendChild(
      emptyState({
        icon: 'run-all',
        message: 'The lane catalogue has not been read yet.',
        hint: 'It reads this repository’s fleet manifest and its workflow files and reports each lane as a read-only passport — plus whether this console could have generated it again.',
        actions: [
          el(
            'button',
            {
              class: 'z-btn',
              type: 'button',
              title: 'Read the manifest and the workflows from disk',
              onclick: () => {
                post('workflows.open');
              },
            },
            'Read the lanes',
          ),
        ],
      }),
    );
    return;
  }

  const specId = stagedSpecId(workflows);
  host.appendChild(catalogue(workflows));
  host.appendChild(formSection(workflows));
  host.appendChild(planSection(workflows, specId));
  host.appendChild(writeSection(workflows, specId));
}

/** The name the dashboard's renderer table uses. */
export const renderWorkflows = render;
