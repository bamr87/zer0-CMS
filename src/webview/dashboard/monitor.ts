/**
 * The Monitor route — the whole roster as a matrix: every repository this
 * console is operating, every lane inside it, and one column per question an
 * operator actually asks. Is the switch on? What did it last do? What is in
 * flight? What has it cost? What does the rulebook think of it?
 *
 * ## Honesty is the whole design here
 *
 * Every other tab in this dashboard describes one repository a person has open,
 * where "I do not know" is rare. This one describes up to a dozen, most of
 * which nobody has read, so **most cells are unknown most of the time** — and a
 * matrix whose unknown cells look like "off" is not a monitor, it is a
 * hallucination with a grid around it. Three rules follow, and every cell in
 * this file obeys them:
 *
 *   1. **A cell nobody has read renders `unknown`,** through `statusPill`'s
 *      `unknown` variant — dashed, unfilled, italic, and visibly not the same
 *      shape as the filled `neutral` badge that means "the answer is no".
 *   2. **Never render a `0` where the truth is "nobody measured".** An open
 *      pull-request count of `null` is not zero; a cost of `null` is not free.
 *      The host sends `null` for both precisely so this file can tell them
 *      apart, and `core/fleet/cost.ts` omits a lane entirely rather than
 *      handing over a `LaneCost` full of zeroes.
 *   3. **Two absences are different, and both are named.** A repository with a
 *      checkout but no refresh has real lane rows — the manifest is on disk, so
 *      the lanes are known and only the answers are missing. A repository with
 *      no checkout and no refresh has no rows at all, and says so in words
 *      rather than drawing an empty table that looks like "no lanes".
 *
 * ## It is a view, and it opens nothing
 *
 * Rendering this tab makes no request. Reading a repository is a button on that
 * repository's own row — four calls, for the one row a person clicked, and five
 * when the row has no checkout and its manifest has to be read too — because a
 * tab that fanned out forty requests on open would be exactly the ambient
 * traffic decision D11 forbids. The hub is read only by the explicit "Import
 * hub roster" action, and the GitFactory link is assembled locally and handed
 * to the browser.
 *
 * Every button posts an intent and a target (`{repo}`) and nothing else; the
 * host re-reads and re-gates. There are no lane verbs on this screen, and that
 * is not an oversight: step 2 of every gate is "re-read the manifest from
 * disk", so the console acts only on a repository it has a checkout of — and
 * this tab exists to show the ones it does not.
 */

import {
  dataTable,
  emptyState,
  keyValueList,
  statusPill,
  type StatusVariant,
} from '../shared/components';
import { clear, el, icon, type Child } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type {
  CommandId,
  DashboardState,
  FleetPullView,
  FleetRunView,
  MonitorRepoView,
  MonitorState,
} from '../shared/protocol';

function post(id: CommandId, args?: unknown): void {
  getMessenger().command(id, args);
}

/** The one pill this file reaches for more than any other. */
function unknownPill(text: string, why: string): HTMLElement {
  return statusPill({ variant: 'unknown', text, title: why });
}

// ---------------------------------------------------------------------------
// Cells — every one of them able to say "nobody asked"
// ---------------------------------------------------------------------------

/**
 * Five words, five meanings — and `ungated` is not `unset`.
 *
 * `true` and `ungated` are both amber, because both mean the lane will run on
 * its own and spend tokens; the difference is that one is armed and the other
 * has nothing to disarm. `unset` is the filled quiet badge (the repository
 * really does not have the variable, so the workflow's own `!= 'true'` gate
 * holds it off) and `unknown` is the dashed one that is not an answer at all.
 */
function switchVariant(value: string): StatusVariant {
  if (value === 'true' || value === 'ungated') {
    return 'warn';
  }
  return value === 'unknown' ? 'unknown' : 'neutral';
}

const SWITCH_TITLES: Readonly<Record<string, string>> = {
  unknown: 'nobody has read this repository’s Actions variables',
  unset: 'the variable is not set, so the lane’s own gate holds it off',
  ungated: 'this lane declares no *_ENABLED switch — nothing gates it',
};

function switchCell(value: string): Child {
  return statusPill({
    variant: switchVariant(value),
    text: value,
    title: SWITCH_TITLES[value] ?? `the variable holds "${value}"`,
  });
}

/**
 * The newest run — or the honest reason there is not one.
 *
 * `null` means two different things and the row knows which: with no read at
 * all it is `unknown`; with a read that simply found nothing, it is "no run on
 * record", which is a measurement.
 */
function runCell(run: FleetRunView | null, read: boolean): Child {
  if (run === null) {
    return read
      ? el('span', { class: 'z-monitor__none' }, 'no run on record')
      : unknownPill('unknown', 'this repository has not been read');
  }
  const label = run.conclusion === null ? run.status : `${run.status} · ${run.conclusion}`;
  const variant =
    run.conclusion === 'success'
      ? ' z-monitor__run--ok'
      : run.conclusion === 'failure' || run.conclusion === 'timed_out'
        ? ' z-monitor__run--bad'
        : '';
  const body =
    run.url === ''
      ? el('span', { class: `z-monitor__run${variant}` }, label)
      : el(
          'button',
          {
            class: `z-monitor__link z-monitor__run${variant}`,
            type: 'button',
            title: run.url,
            onclick: () => {
              post('openLink', { url: run.url });
            },
          },
          label,
        );
  return [body, ' ', el('span', { class: 'z-date' }, run.updatedAt)];
}

/** `null` is "nobody read the pull requests"; `0` is a measurement that says none. */
function countCell(value: number | null): Child {
  return value === null
    ? unknownPill('unknown', 'the open pull requests of this repository have not been read')
    : el('span', { class: 'z-table__num' }, String(value));
}

/** `null` is "nobody measured". It is never drawn as `$0.00`. */
function costCell(value: number | null): Child {
  return value === null
    ? unknownPill(
        'unmeasured',
        'no row in this repository’s _data/ai_usage/summary.yml — which is not the same as free',
      )
    : el('span', { class: 'z-table__num z-monitor__cost' }, `$${value.toFixed(2)}`);
}

/** The rulebook's letter, or unknown when no checkout of this repository was read. */
function gradeCell(grade: string | null): Child {
  if (grade === null) {
    return unknownPill(
      'unknown',
      'the audit runs over the workflow files on disk, and this window has no checkout of this repository',
    );
  }
  const variant: StatusVariant =
    grade === 'S' || grade === 'A' ? 'ok' : grade === 'B' ? 'neutral' : grade === 'C' ? 'warn' : 'danger';
  return statusPill({ variant, text: grade, title: `harness grade ${grade}` });
}

// ---------------------------------------------------------------------------
// One repository
// ---------------------------------------------------------------------------

const LANE_COLUMNS = ['Lane', 'Switch', 'Newest run', 'Open PRs', 'Cost', 'Grade'] as const;

/** How a repository got onto the roster. Shown, because it explains the gaps. */
function sourcePill(source: string, localRoot: string | null): HTMLElement {
  return statusPill({
    variant: source === 'workspace' ? 'ok' : 'neutral',
    text: source,
    title:
      localRoot === null
        ? `named by ${source} — this window has no checkout, so its manifest, cost and grade are unreadable here`
        : `open in this window at ${localRoot}`,
  });
}

function repoHead(row: MonitorRepoView): HTMLElement {
  const refresh = el(
    'button',
    {
      class: 'z-btn z-btn--secondary',
      type: 'button',
      title:
        row.localRoot === null
          ? 'Read this repository in five calls — its manifest, then variables, workflows, recent runs and open pull requests. The grade, the drift rows and the cost need a checkout and stay unknown.'
          : 'Read this repository in four calls — variables, workflows, recent runs, open pull requests (may ask you to sign in)',
      onclick: () => {
        post('fleet.refresh', { repo: row.slug });
      },
    },
    icon('refresh'),
    ' Refresh',
  );
  const cost =
    row.cost === null
      ? unknownPill('cost unmeasured', 'this repository has committed no AI-usage ledger the console could read')
      : el(
          'span',
          { class: 'z-monitor__total', title: `${row.cost.window} · ${row.cost.note}` },
          `$${row.cost.costUsd.toFixed(2)} all-time`,
        );

  return el(
    'div',
    { class: 'z-monitor__head' },
    el(
      'div',
      { class: 'z-monitor__ident' },
      el('span', { class: 'z-lane__title' }, icon('repo'), row.slug),
      el(
        'div',
        { class: 'z-monitor__badges' },
        sourcePill(row.source, row.localRoot),
        gradeCell(row.grade),
        cost,
      ),
      el(
        'div',
        { class: 'z-lane__hint' },
        row.fetchedAt === null ? 'Never read from GitHub in this window.' : `Read at ${row.fetchedAt}.`,
      ),
      row.note === null ? null : el('div', { class: 'z-monitor__note' }, row.note),
    ),
    el('div', { class: 'z-monitor__actions' }, refresh),
  );
}

/**
 * The three merge-policy variables, per repository.
 *
 * Read-only here for the same reason they are read-only on the Fleet tab: none
 * of them is a manifest lane, and the verbs that would change what they decide
 * are refused at the level of URLs by `fleetPlanHasNoMergeVerbs`.
 */
function policyRow(row: MonitorRepoView): HTMLElement {
  if (row.mergePolicy === null) {
    return el(
      'p',
      { class: 'z-monitor__note' },
      'Merge policy unknown — nobody has read this repository’s Actions variables.',
    );
  }
  return keyValueList(
    Object.entries(row.mergePolicy).map(([name, value]) => ({
      key: name,
      title: `${name} = ${value}`,
      value: statusPill({
        variant: value === 'true' ? 'warn' : value === 'unknown' ? 'unknown' : 'neutral',
        text: value,
        title: `${name} = ${value}`,
      }),
    })),
    'z-monitor__policy',
  );
}

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

function pullStrip(pulls: FleetPullView[] | null): HTMLElement {
  if (pulls === null) {
    return el(
      'p',
      { class: 'z-monitor__note' },
      'Open pull requests have not been read for this repository.',
    );
  }
  if (pulls.length === 0) {
    return el('p', { class: 'z-lane__empty' }, 'No open pull requests.');
  }
  return el(
    'div',
    { class: 'z-monitor__pulls' },
    ...pulls.map((pull) =>
      el(
        'button',
        {
          class: 'z-monitor__pull',
          type: 'button',
          title: `${pull.title} — ${pull.stage}${pull.laneId === null ? ' (unattributed)' : ` (${pull.laneId})`}`,
          onclick: () => {
            post('openLink', { url: pull.url });
          },
        },
        `#${pull.number}`,
        statusPill({ variant: stageVariant(pull.stage), text: pull.stage }),
      ),
    ),
  );
}

function repoSection(row: MonitorRepoView): HTMLElement {
  const read = row.fetchedAt !== null;
  const table =
    row.lanes.length === 0
      ? el(
          'p',
          { class: 'z-lane__empty' },
          row.localRoot === null
            ? 'No lanes are known: nothing in this window has read this repository’s manifest.'
            : 'The manifest on disk declares no lanes.',
        )
      : dataTable({
          columns: [...LANE_COLUMNS],
          className: 'z-monitor__table',
          label: `${row.slug} lanes`,
          numeric: [3, 4],
          rows: row.lanes.map((lane) => [
            el('code', {}, lane.id),
            switchCell(lane.switchValue),
            runCell(lane.lastRun, read),
            countCell(lane.openPulls),
            costCell(lane.cost),
            gradeCell(lane.grade),
          ]),
        });

  return el(
    'section',
    { class: 'z-lane z-monitor__repo' },
    repoHead(row),
    table,
    policyRow(row),
    pullStrip(row.pulls),
  );
}

// ---------------------------------------------------------------------------
// The hub
// ---------------------------------------------------------------------------

function hubBlock(monitor: MonitorState): HTMLElement {
  const scorecard = monitor.hub.scorecard;
  const importer = el(
    'button',
    {
      class: 'z-btn z-btn--secondary',
      type: 'button',
      title:
        'Read the hub’s project registry and its harness scorecard. One explicit action, never a tab open.',
      onclick: () => {
        post('fleet.importHubRoster');
      },
    },
    icon('cloud-download'),
    ' Import hub roster',
  );

  return el(
    'section',
    { class: 'z-lane z-monitor__hub' },
    el(
      'div',
      { class: 'z-monitor__head' },
      el(
        'div',
        { class: 'z-monitor__ident' },
        el('span', { class: 'z-lane__title' }, icon('organization'), monitor.hub.slug),
        el(
          'div',
          { class: 'z-lane__hint' },
          monitor.hub.readAt === null ? 'The hub has not been read.' : `Read at ${monitor.hub.readAt}.`,
        ),
        monitor.hub.note === null ? null : el('div', { class: 'z-monitor__note' }, monitor.hub.note),
      ),
      el('div', { class: 'z-monitor__actions' }, importer),
    ),
    scorecard === null
      ? el(
          'p',
          { class: 'z-lane__empty' },
          'No scorecard: the hub’s harness signals have not been read in this window.',
        )
      : keyValueList(
          scorecard.map((metric) => ({
            key: metric.key,
            title: `${metric.key}: ${metric.value} (${metric.status})`,
            value:
              metric.value === 'unknown'
                ? unknownPill('unknown', 'the hub published no value for this metric')
                : statusPill({
                    variant:
                      metric.status === 'ok' ? 'ok' : metric.status === 'warn' ? 'warn' : 'unknown',
                    text: metric.value,
                    title: `${metric.key} = ${metric.value}`,
                  }),
          })),
          'z-monitor__scorecard',
        ),
  );
}

// ---------------------------------------------------------------------------
// The route
// ---------------------------------------------------------------------------

function toolbar(monitor: MonitorState): HTMLElement {
  const unread = monitor.roster.filter((row) => row.fetchedAt === null).length;
  const handoff = el(
    'button',
    {
      class: 'z-btn z-btn--secondary',
      type: 'button',
      title: `Open this roster in GitFactory (${monitor.gitfactoryUrl}). Building the link opens no socket; your browser does.`,
      onclick: () => {
        post('fleet.openInGitFactory');
      },
    },
    icon('link-external'),
    ' Open in GitFactory',
  );
  return el(
    'div',
    { class: 'z-monitor__toolbar' },
    el(
      'div',
      { class: 'z-monitor__heading' },
      el('span', { class: 'z-lane__title' }, icon('dashboard'), 'Monitor'),
      el(
        'div',
        { class: 'z-lane__hint' },
        `${monitor.roster.length} repositor${monitor.roster.length === 1 ? 'y' : 'ies'} on the roster, ${unread} of them never read here.`,
      ),
      el(
        'div',
        { class: 'z-lane__hint' },
        'Nothing on this screen is read until you ask for it: Refresh reads one repository in four calls — five for one this window has no checkout of, whose manifest has to be read too. A dashed, italic cell means nobody has asked; it is not an “off”.',
      ),
    ),
    el('div', { class: 'z-monitor__actions' }, handoff),
  );
}

export function render(host: HTMLElement, state: DashboardState): void {
  clear(host);
  const monitor = state.monitor ?? null;

  if (monitor === null) {
    host.appendChild(
      emptyState({
        icon: 'dashboard',
        message: 'The Monitor has nothing to draw.',
        hint: 'It lists every repository with a fleet manifest open in this window, plus anything in "zer0Cms.fleet.roster". Set "zer0Cms.fleet.enabled" to true and open a folder that carries one.',
      }),
    );
    return;
  }

  host.appendChild(toolbar(monitor));

  if (monitor.roster.length === 0) {
    host.appendChild(
      emptyState({
        icon: 'dashboard',
        message: 'No repositories on the roster.',
        hint: 'A folder open in this window joins the roster when it carries a readable fleet.manifest.yml. You can also name repositories in "zer0Cms.fleet.roster", or import the hub’s registry below.',
      }),
    );
  } else {
    for (const row of monitor.roster) {
      host.appendChild(repoSection(row));
    }
  }

  host.appendChild(hubBlock(monitor));
}
