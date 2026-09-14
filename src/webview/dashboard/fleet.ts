/**
 * The Fleet route — one repository's AI lanes as `fleet.manifest.yml` declares
 * them, with what the repository last said about each: the switch value, the
 * newest run, the workflow's own enablement, the rulebook's grade, what it has
 * cost, and which open pull requests it opened.
 *
 * **Decision D5, again, because this screen now has five buttons that write to
 * another system.** Every one of them posts `{type:'command', id, args:{repo,
 * lane}}` — a repository slug and a lane id, and nothing else. Not the new
 * switch value (the host derives it from the variable it fetches a moment
 * later), not a run id (the host takes that from what the last Refresh read),
 * not a ref, not a `force`. The host re-reads the manifest from disk, re-runs
 * `evaluateFleetGates()` for that verb's own mode, obtains the credential
 * lazily and asks modally, inside the *same* `doToggleSwitch` /
 * `doDispatchLane` / `doRerunLastFailure` / `doCancelNewest` /
 * `doToggleWorkflowFile` the command palette calls. A button that renders
 * enabled when the gate says otherwise is a cosmetic bug, not an escalation.
 *
 * The `repo` in those args is a **target**, exactly like the lane: it names
 * which roster row the person clicked, and the host resolves it against a
 * roster it built itself from folders this window has open. A slug that names
 * nothing this window has a checkout of is refused, because step 2 of the gate
 * is "re-read the manifest from disk".
 *
 * ## Unknown is a state, and it is drawn as one
 *
 * The switch pill has four honest states. `true`/`false` are what the variable
 * holds; `unset` means the repository really does not have it (the lane is
 * off); `unknown` means nobody has asked — there is no credential, or the tab
 * was opened without one — and the note above the table says so rather than
 * letting a grey pill imply an answer. An ungated lane (`switch: null`) draws a
 * dash. That distinction lives in `statusPill`'s `unknown` variant rather than
 * in this file, because six tabs have to make it and three copies of "what does
 * a grey cell mean" is how two screens end up disagreeing about one lane.
 *
 * The same rule governs the two columns slice 2 adds. **Cost is `null` when
 * nobody measured, and it is never drawn as `$0.00`** — a zero in a cost column
 * reads as "this was free", and the ledger simply may not have a row. A grade
 * is absent when no checkout was audited, not `D`.
 *
 * ## The merge-policy block is a read, and cannot be anything else
 *
 * `AUTO_MERGE_ENABLED`, `AUTO_UPDATE_ENABLED` and `AUTO_FIX_ENABLED` decide
 * whether anything merges the queue below without a person. None of them is a
 * manifest lane, so the console reports them and **offers no control** — there
 * is no toggle here, and `fleetPlanHasNoMergeVerbs` in `core/fleet/github.ts`
 * is what makes that a boundary rather than an omission.
 *
 * The blocker notes under a disabled button come from the host's advisory
 * `evaluateFleetGates()` and are rendered in the gate's own order, verbatim,
 * for the same reason the Drafts route does it: re-sorting them here would
 * make this screen and the confirmation modal disagree about the same lane.
 * The three run verbs additionally carry a *courtesy* hint derived from the
 * wire — "nothing has been read yet" — because until the host fills their own
 * blocker lists there is nothing else to grey them out with, and a button that
 * is certain to be refused should look like one.
 */

import {
  blockerNote,
  dataTable,
  emptyState,
  gatedButton,
  keyValueList,
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
  FleetPullView,
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
  const registered =
    lane.enabledState === undefined || lane.enabledState === 'active'
      ? null
      : statusPill({
          variant: 'danger',
          text: lane.enabledState,
          title: `GitHub has this workflow registered ${lane.enabledState} — the file is unchanged`,
        });
  if (lane.switch === null) {
    return el(
      'span',
      { class: 'z-fleet__switch' },
      el('span', { class: 'z-fleet__unknown', title: 'ungated — this lane has no *_ENABLED switch' }, '—'),
      registered,
    );
  }
  const value = lane.switchValue;
  return el(
    'span',
    { class: 'z-fleet__switch' },
    el('code', { class: 'z-fleet__var' }, lane.switch),
    statusPill({ variant: switchVariant(value), text: value, title: `${lane.switch} = ${value}` }),
    registered,
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

/**
 * The rulebook's answer for this lane's workflow.
 *
 * `undefined` is "no checkout was audited" and draws as unknown; an empty list
 * is a real pass and draws as one. The counts are the finding severities, not a
 * score, because a letter with no findings behind it is a number nobody can
 * argue with — and these are all arguable.
 */
function gradeCell(lane: FleetLaneView): Child {
  const findings = lane.audit;
  if (findings === undefined) {
    return statusPill({
      variant: 'unknown',
      text: 'unknown',
      title: 'no checkout of this repository was audited — the rulebook runs over the workflow files on disk',
    });
  }
  const fails = findings.filter((f) => f.severity === 'fail').length;
  const warns = findings.filter((f) => f.severity === 'warn').length;
  const infos = findings.length - fails - warns;
  const variant: StatusVariant = fails > 0 ? 'danger' : warns > 0 ? 'warn' : 'ok';
  const summary = fails > 0 || warns > 0 || infos > 0 ? `${fails}F ${warns}W ${infos}I` : 'clean';
  const detail = findings
    .slice(0, 6)
    .map((f) => `${f.severity}: ${f.rule} — ${f.message}`)
    .join('\n');
  return el(
    'span',
    { class: 'z-fleet__grade' },
    statusPill({ variant, text: summary, title: detail === '' ? 'no findings' : detail }),
  );
}

/**
 * All-time API-equivalent dollars from the repository's own committed ledger.
 *
 * Absent means the ledger has no row for this lane — **not** that it was free.
 * `core/fleet/cost.ts` returns no entry rather than a `LaneCost` full of
 * zeroes precisely so this cell can tell the two apart.
 */
function costCell(lane: FleetLaneView): Child {
  const cost = lane.cost;
  if (cost === undefined || cost === null) {
    return statusPill({
      variant: 'unknown',
      text: 'unmeasured',
      title: "no row in this repository's _data/ai_usage/summary.yml — nobody measured, which is not the same as free",
    });
  }
  return el(
    'span',
    { class: 'z-fleet__cost', title: 'all-time, API-equivalent dollars, from the repository’s committed ledger' },
    `$${cost.toFixed(2)}`,
  );
}

/**
 * The five verbs, each a courtesy over the host's advisory gate (D5).
 *
 * `unread` is derived here rather than sent: until the host fills per-verb
 * blocker lists for the three run verbs, "nothing has been read from GitHub
 * yet" is the one refusal this screen can state honestly from the wire, and a
 * button that is certain to be refused should look like one. A webview may
 * always disable more than the host would; it may never enable past it.
 */
function actionsCell(lane: FleetLaneView, fleet: FleetState): Child {
  const target = { repo: fleet.repo, lane: lane.id };
  const toggleLabel = lane.switchValue === 'true' ? 'Switch off' : 'Switch on';
  const unread: BlockerView[] =
    fleet.fetchedAt === null
      ? [
          {
            kind: 'noLiveRead',
            message: 'nothing has been read from this repository yet — press Refresh first',
          },
        ]
      : [];
  const noWorkflow: BlockerView[] =
    unread.length > 0
      ? unread
      : lane.enabledState === undefined
        ? [
            {
              kind: 'workflowUnknown',
              message: 'GitHub has no registered workflow for this lane — it may never have run',
            },
          ]
        : [];

  const button = (
    label: string,
    id: CommandId,
    blockers: readonly BlockerView[],
    verb: string,
    title: string,
  ): HTMLElement =>
    gatedButton({
      label,
      id,
      // A repository and a lane, and nothing else. See the module comment.
      args: target,
      blockers,
      verb,
      title,
      secondary: true,
    });

  return el(
    'div',
    { class: 'z-fleet__actions' },
    button(
      toggleLabel,
      'fleet.toggleSwitch',
      lane.toggleBlockers,
      // `Switch off disabled: …` is not a sentence; the verb the gate refuses
      // is the toggle, whatever the button happens to be offering right now.
      'Toggle',
      `${toggleLabel} "${lane.id}" — the host will ask first`,
    ),
    button(
      'Dispatch',
      'fleet.dispatchLane',
      lane.dispatchBlockers,
      'Dispatch',
      `Queue one run of "${lane.id}" on the default branch — the host will ask first`,
    ),
    button(
      'Re-run failure',
      'fleet.rerunLastFailure',
      unread,
      'Re-run',
      'Queue a NEW attempt of the newest failed run. The original attempt stays on the record.',
    ),
    button(
      'Cancel run',
      'fleet.cancelNewest',
      unread,
      'Cancel',
      'Stop what is in flight. The run stays on the record, concluded cancelled.',
    ),
    button(
      lane.enabledState === 'active' ? 'Disable workflow' : 'Enable workflow',
      'fleet.toggleWorkflowFile',
      noWorkflow,
      'Enable/disable workflow',
      'Registers the workflow active or disabled_manually with GitHub. It does not touch the file.',
    ),
  );
}

const LANE_COLUMNS = [
  'Lane',
  'Kind',
  'Harness',
  'Triggers · guardrails',
  'Switch',
  'Last run',
  'Audit',
  'Cost',
  'Actions',
] as const;

function laneRow(lane: FleetLaneView, fleet: FleetState): Child[] {
  const pulls = lane.pulls ?? [];
  return [
    el(
      'div',
      { class: 'z-fleet__lane' },
      el('strong', {}, lane.id),
      el('div', { class: 'z-fleet__description' }, lane.description),
      el('code', { class: 'z-fleet__file', title: lane.implementation }, lane.implementation || '(no workflow)'),
      pulls.length === 0
        ? null
        : el(
            'div',
            { class: 'z-fleet__lanepulls', title: pulls.map((n) => `#${n}`).join(', ') },
            `${pulls.length} open pull request${pulls.length === 1 ? '' : 's'}`,
          ),
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
    gradeCell(lane),
    costCell(lane),
    actionsCell(lane, fleet),
  ];
}

// ---------------------------------------------------------------------------
// The in-flight strip
// ---------------------------------------------------------------------------

/**
 * A pull request's stage, from `prStage()` — which reads the fleet's own label
 * vocabulary and nothing else. It is **not** a prediction that anything will
 * merge: every policy behind these labels is additionally gated on one of the
 * variables in the merge-policy block beside it, which is why the two are drawn
 * together and never combined into one green light.
 */
function stageVariant(stage: string): StatusVariant {
  switch (stage) {
    case 'needs-human':
      return 'danger';
    case 'auto-mergeable':
      return 'warn';
    case 'unknown':
      return 'unknown';
    default:
      return 'neutral';
  }
}

function pullRow(pull: FleetPullView): Child[] {
  return [
    el(
      'button',
      {
        class: 'z-fleet__link',
        type: 'button',
        title: pull.url,
        onclick: () => {
          post('openLink', { url: pull.url });
        },
      },
      `#${pull.number}`,
    ),
    el('div', { class: 'z-fleet__pulltitle' }, pull.title),
    statusPill({ variant: stageVariant(pull.stage), text: pull.stage, title: `stage: ${pull.stage}` }),
    pull.laneId === null
      ? el('span', { class: 'z-fleet__unknown', title: 'no lane claims this pull request' }, 'unattributed')
      : el('code', {}, pull.laneId),
  ];
}

/**
 * Everything in flight, and what would merge it.
 *
 * `pulls === null` (or absent) is "nobody read them", which is a different
 * screen from "there are none" — and both are different from "there are eleven
 * and nothing is going to merge them", which is the one an operator most needs
 * to see.
 */
function inFlight(fleet: FleetState): HTMLElement {
  const pulls = fleet.pulls ?? null;
  const policy = fleet.mergePolicy ?? null;

  const policyBlock =
    policy === null
      ? el(
          'p',
          { class: 'z-fleet__note' },
          'Merge policy unknown — nobody has read this repository’s Actions variables. Refresh reads them.',
        )
      : keyValueList(
          Object.entries(policy).map(([name, value]) => ({
            key: name,
            title: `${name} = ${value}`,
            value: statusPill({
              variant: value === 'true' ? 'warn' : value === 'unknown' ? 'unknown' : 'neutral',
              text: value,
              title: `${name} = ${value}`,
            }),
          })),
          'z-fleet__policy',
        );

  return el(
    'section',
    { class: 'z-lane z-fleet__inflight' },
    el('div', { class: 'z-lane__title' }, icon('git-pull-request'), 'In flight'),
    el(
      'div',
      { class: 'z-lane__hint' },
      'Open pull requests, with the stage the repository’s own labels put each in. This console never merges, approves, closes or relabels one.',
    ),
    pulls === null
      ? el(
          'p',
          { class: 'z-lane__empty' },
          'Open pull requests have not been read. Refresh reads one bounded page of them.',
        )
      : dataTable({
          columns: ['#', 'Title', 'Stage', 'Lane'],
          className: 'z-fleet__pulls',
          label: 'Open pull requests',
          rows: pulls.map(pullRow),
          empty: 'No open pull requests.',
        }),
    el(
      'div',
      { class: 'z-lane__title z-fleet__policyhead' },
      icon('shield'),
      'What merges without a person',
    ),
    el(
      'div',
      { class: 'z-lane__hint' },
      'These three repository variables decide the queue above. They are not manifest lanes, so this console reports them and cannot flip them — the switch is in the repository’s own settings.',
    ),
    policyBlock,
  );
}

/** Where the manifest and the workflow files disagree. Shown, never written. */
function drift(fleet: FleetState): HTMLElement | null {
  const rows = fleet.drift ?? [];
  if (rows.length === 0) {
    return null;
  }
  return el(
    'section',
    { class: 'z-lane z-fleet__drift' },
    el('div', { class: 'z-lane__title' }, icon('warning'), 'Manifest drift'),
    el(
      'div',
      { class: 'z-lane__hint' },
      'What `fleet.manifest.yml` says, and what the workflow file it names actually does. The console shows these; it never edits the manifest to match — deriving a manifest is `wtd`’s job.',
    ),
    dataTable({
      columns: ['Lane', 'Axis', 'The manifest says', 'The workflow says'],
      className: 'z-fleet__drifttable',
      label: 'Manifest drift',
      rows: rows.map((row) => [
        el('code', {}, row.laneId),
        row.kind,
        el('span', { class: 'z-fleet__driftsays' }, row.manifestSays),
        el('span', { class: 'z-fleet__driftsays' }, row.workflowSays),
      ]),
    }),
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
      title:
        'Read this repository from GitHub in four calls — variables, workflows, recent runs, open pull requests (may ask you to sign in)',
      onclick: () => {
        post('fleet.refresh', fleet.repo === null ? undefined : { repo: fleet.repo });
      },
    },
    icon('refresh'),
    ' Refresh',
  );
  const handoff = el(
    'button',
    {
      class: 'z-btn z-btn--secondary',
      type: 'button',
      title: 'Open this roster in GitFactory. Building the link opens no socket; your browser does.',
      onclick: () => {
        post('fleet.openInGitFactory');
      },
    },
    icon('link-external'),
    ' Open in GitFactory',
  );
  const where =
    fleet.fetchedAt === null
      ? 'Switch values, runs and pull requests have not been read — press Refresh to sign in and read them.'
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
        `${fleet.manifestPath} · provenance ${fleet.provenance} · ${fleet.lanes.length} lane${fleet.lanes.length === 1 ? '' : 's'}` +
          (fleet.grade === null || fleet.grade === undefined ? '' : ` · harness grade ${fleet.grade}`),
      ),
    ),
    el(
      'div',
      { class: 'z-fleet__status' },
      el('div', { class: 'z-fleet__buttons' }, refresh, handoff),
      el('div', { class: 'z-fleet__note' }, where),
      fleet.note === null ? null : el('div', { class: 'z-fleet__note z-fleet__note--warn' }, fleet.note),
      fleet.dispatchAllow
        ? null
        : blockerNote(
            'Every verb on this screen is',
            [
              {
                kind: 'dispatchDisabled',
                message:
                  'set "zer0Cms.fleet.dispatchAllow" to true in your own settings — a zer0.json cannot arm it',
              },
            ],
            'z-fleet__note',
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
        rows: fleet.lanes.map((lane) => laneRow(lane, fleet)),
        empty: 'The manifest declares no lanes.',
      }),
    ),
  );

  host.appendChild(inFlight(fleet));

  const driftTable = drift(fleet);
  if (driftTable !== null) {
    host.appendChild(driftTable);
  }

  const tokenTable = tokens(fleet);
  if (tokenTable !== null) {
    host.appendChild(tokenTable);
  }
}
