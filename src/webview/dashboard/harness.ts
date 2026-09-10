/**
 * The Harness route — what this repository's AI machinery *is*: the roles it
 * declares, the routines those roles follow, the workflows that run them, what
 * belongs to what, and where the four disagree.
 *
 * This is the tab that answers the question the rest of the console keeps
 * running into: **what will run, as whom, spending what.** Four artefacts hold
 * pieces of that answer and none of them holds all of it — `.claude/agents/`
 * names a role and a model, a workflow names a role and a switch,
 * `fleet.manifest.yml` names a lane and its tokens, `_data/ai_usage/` names what
 * it cost — so the useful screen is the join, plus an honest list of the places
 * the join does not line up.
 *
 * Three rules govern what it may say.
 *
 *  - **Tokens are names.** The manifest names the credentials a lane spends;
 *    this console shows those names and never a value. There is no code path
 *    from this bundle to a secret, and there is not going to be one.
 *  - **The resolved profile says which layer answered.** "The model" silently
 *    differing between the editor and CI is the confusion this whole slice
 *    exists to end, so `modelSource` is rendered as a sentence — *your
 *    settings*, *zer0.json*, *the repository's own `_data/ai.yml`*, *the
 *    built-in default* — beside the model itself. `MODEL_SOURCE_PROSE` is this
 *    bundle's copy of `describeSource` in `src/core/harness/profile.ts`; a
 *    browser bundle cannot import core, so the sentence is written twice. Edit
 *    both in one commit.
 *  - **An absent number is an em dash.** A repository with no usage ledger is
 *    unmetered, not free, and a cost column of `0` would be the quietest lie
 *    this screen could tell (decision D9).
 *
 * Read-only, entirely. Nothing on this route posts a command except the two
 * that reveal a file or a link.
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
import type { CommandId, DashboardState, HarnessState } from '../shared/protocol';

function post(id: CommandId, args?: unknown): void {
  getMessenger().command(id, args);
}

/** How many rows any one table draws before it says what it is not drawing. */
export const MAX_ROWS = 200;

/**
 * What each `modelSource` means, in a sentence.
 *
 * The twin of `describeSource` in `src/core/harness/profile.ts`, which the
 * output channel and the agent panel use. Two copies, one sentence each — this
 * bundle cannot import core.
 */
const MODEL_SOURCE_PROSE: Readonly<Record<string, string>> = {
  settings: 'from your own VS Code settings',
  'zer0.json': 'from this repository’s zer0.json',
  'ai.yml': 'inherited from the repository’s own _data/ai.yml — the same file its CI lanes read',
  default: 'the extension’s built-in default; nothing in this repository named a model',
};

/** `error` is danger, `warning` amber, anything else a plain note. */
export function severityVariant(severity: string): StatusVariant {
  if (severity === 'error' || severity === 'fail') {
    return 'danger';
  }
  return severity === 'warning' || severity === 'warn' ? 'warn' : 'neutral';
}

/** A runner shape that never calls a model is not a finding — it is a fact. */
function shapeVariant(shape: string): StatusVariant {
  if (shape === 'none') {
    return 'neutral';
  }
  return shape === 'ai-lane-caller' || shape === 'claude-run' ? 'ok' : 'warn';
}

/** `—`, never `0`: nobody measured this. */
function unknownCell(title: string): HTMLElement {
  return el('span', { class: 'z-harness__unknown', title }, '—');
}

function money(value: number | null, unit: string): Child {
  if (value === null) {
    return unknownCell('no ledger row for this lane');
  }
  return el('span', { title: unit }, `$${value.toFixed(2)}`);
}

function pathButton(rel: string): HTMLElement {
  return el(
    'button',
    {
      class: 'z-harness__path',
      type: 'button',
      title: `Reveal ${rel}`,
      onclick: () => {
        post('revealFile', { path: rel });
      },
    },
    rel,
  );
}

function truncated<T>(rows: readonly T[]): { shown: readonly T[]; hidden: number } {
  return rows.length <= MAX_ROWS
    ? { shown: rows, hidden: 0 }
    : { shown: rows.slice(0, MAX_ROWS), hidden: rows.length - MAX_ROWS };
}

function section(title: string, iconName: string, hint: string, ...body: Child[]): HTMLElement {
  return el(
    'section',
    { class: 'z-lane z-harness__section' },
    el('div', { class: 'z-lane__title' }, icon(iconName), title),
    el('div', { class: 'z-lane__hint' }, hint),
    ...body,
  );
}

// ---------------------------------------------------------------------------
// The summary strip
// ---------------------------------------------------------------------------

/** `1 agent`, `2 agents`. A count in a pill is prose too. */
function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

function counts(harness: HarnessState): HTMLElement {
  const errors = harness.findings.filter((f) => severityVariant(f.severity) === 'danger').length;
  const warnings = harness.findings.filter((f) => severityVariant(f.severity) === 'warn').length;
  return el(
    'div',
    { class: 'z-harness__counts' },
    statusPill({
      variant: errors > 0 ? 'danger' : 'ok',
      text: `${errors} error${errors === 1 ? '' : 's'}`,
      title: 'places the manifest, the workflows, the agents and the ledger disagree',
    }),
    statusPill({
      variant: warnings > 0 ? 'warn' : 'ok',
      text: `${warnings} warning${warnings === 1 ? '' : 's'}`,
    }),
    statusPill({ variant: 'neutral', text: plural(harness.agents.length, 'agent') }),
    statusPill({ variant: 'neutral', text: plural(harness.skills.length, 'skill') }),
    statusPill({ variant: 'neutral', text: plural(harness.workflows.length, 'workflow') }),
    statusPill({ variant: 'neutral', text: `${harness.joins.length} joined` }),
  );
}

/**
 * Provenance, and the ledger's one honest number.
 *
 * The unit is stated rather than assumed: the fleet's ledger records
 * API-equivalent dollars, which is not the same thing as money anybody was
 * charged, and a dashboard that forgets that lies quietly.
 */
function provenance(harness: HarnessState): HTMLElement {
  const ledger = harness.ledger;
  return keyValueList(
    [
      { key: 'Read at', value: el('span', { class: 'z-date' }, harness.readAt) },
      {
        key: 'Spend, last 7 days',
        value:
          ledger === null
            ? el(
                'span',
                { class: 'z-harness__unknown' },
                'unmetered — this repository keeps no usage ledger',
              )
            : el(
                'span',
                {},
                ledger.last7dUsd === null ? '—' : `$${ledger.last7dUsd.toFixed(2)}`,
                ' ',
                el('span', { class: 'z-muted' }, `(${ledger.unit}, ${ledger.path})`),
              ),
        title: 'API-equivalent dollars, from the repository’s own ledger',
      },
    ],
    'z-harness__provenance',
  );
}

/**
 * The resolved profile — the whole point of the tab, in six rows.
 *
 * `runnerLine` is the *same* projection `agent.runAsRole`'s "Copy the CI
 * equivalent" hands you, so the editor run and the lane invocation on this
 * screen cannot disagree about what they are.
 */
function profileSection(harness: HarnessState): HTMLElement {
  const profile = harness.profile;
  if (profile === null) {
    return section(
      'Resolved profile',
      'person',
      'The editor agent is off, so no profile was resolved. The workflows below still say what CI would run.',
      el(
        'p',
        { class: 'z-muted' },
        'Set "zer0Cms.agent.enabled" to true to see which model, role and MCP server an in-editor run would use.',
      ),
    );
  }
  return section(
    'Resolved profile',
    'person',
    'What an in-editor run resolves to right now — and, in the last row, the same run as CI would invoke it.',
    keyValueList([
      {
        key: 'Model',
        value: el(
          'span',
          {},
          el('code', {}, profile.model === '' ? '(inherit)' : profile.model),
          ' ',
          el(
            'span',
            { class: 'z-muted' },
            MODEL_SOURCE_PROSE[profile.modelSource] ?? profile.modelSource,
          ),
        ),
        title: 'which layer answered for the model',
      },
      {
        key: 'Role',
        value:
          profile.agent === null
            ? el('span', { class: 'z-harness__unknown' }, 'none — a plain run, no repository role')
            : el('code', {}, profile.agent),
      },
      {
        key: 'MCP servers',
        value:
          profile.mcpServers.length === 0
            ? el('span', { class: 'z-harness__unknown' }, 'none attached')
            : profile.mcpServers.join(', '),
      },
      {
        key: 'Settings files',
        value:
          profile.settingSources.length === 0
            ? el(
                'span',
                {},
                'none — ',
                el(
                  'span',
                  { class: 'z-muted' },
                  'this repository’s .claude/settings.json hooks do not apply to an editor run unless you opt in for that run',
                ),
              )
            : profile.settingSources.join(' + '),
      },
      {
        key: 'The same run in CI',
        value: el('code', { class: 'z-harness__runner' }, profile.runnerLine),
        title: 'what agent.runAsRole would hand you to paste into a workflow',
      },
    ]),
  );
}

// ---------------------------------------------------------------------------
// The four tables
// ---------------------------------------------------------------------------

function agentsTable(harness: HarnessState): HTMLElement {
  const { shown, hidden } = truncated(harness.agents);
  return section(
    'Agents',
    'person',
    'The roles this repository declares under .claude/agents/. A lane runs one of these by name, and the runner resolves the filename literally.',
    dataTable({
      columns: ['Role', 'Model', 'Tools', 'Dialect', 'File'],
      className: 'z-harness__table',
      label: 'Agents this repository declares',
      empty: 'This repository declares no agents.',
      rows: shown.map((agent) => [
        el(
          'div',
          { class: 'z-harness__name' },
          el('strong', {}, agent.name),
          el('div', { class: 'z-harness__description' }, agent.description),
        ),
        agent.model === null
          ? unknownCell('the file names no model; the run inherits one')
          : el('code', {}, agent.model),
        agent.tools.length === 0
          ? unknownCell('the file names no tools')
          : el('span', { class: 'z-harness__tools' }, agent.tools.join(', ')),
        agent.dialect,
        pathButton(agent.path),
      ]),
    }),
    hidden === 0 ? null : el('p', { class: 'z-muted' }, `${hidden} more not drawn.`),
  );
}

function skillsTable(harness: HarnessState): HTMLElement {
  const { shown, hidden } = truncated(harness.skills);
  return section(
    'Skills',
    'book',
    'The routines under .claude/skills/. A skill is what an agent follows; its trigger phrases are how a model decides to.',
    dataTable({
      columns: ['Skill', 'Triggers', 'File'],
      className: 'z-harness__table',
      label: 'Skills this repository declares',
      empty: 'This repository declares no skills.',
      rows: shown.map((skill) => [
        el(
          'div',
          { class: 'z-harness__name' },
          el('strong', {}, skill.name),
          el('div', { class: 'z-harness__description' }, skill.description),
          skill.nameMatchesDir
            ? null
            : el(
                'div',
                { class: 'z-harness__warn' },
                'its own name does not match its directory — a reference by directory will not find it',
              ),
        ),
        skill.triggerPhrases.length === 0
          ? unknownCell('the description names no trigger phrases')
          : el('span', { class: 'z-harness__tools' }, skill.triggerPhrases.slice(0, 6).join(' · ')),
        pathButton(skill.path),
      ]),
    }),
    hidden === 0 ? null : el('p', { class: 'z-muted' }, `${hidden} more not drawn.`),
  );
}

/**
 * The workflows, grouped by how they actually call a model.
 *
 * `runnerShape` is the column that matters: a repository can have four
 * workflows that each reach a model a different way, and "which runner" decides
 * whether the call is metered, whether it has a timeout, and whether flipping a
 * switch stops it.
 */
function workflowsTable(harness: HarnessState): HTMLElement {
  const { shown, hidden } = truncated(harness.workflows);
  const ai = harness.workflows.filter((workflow) => workflow.runnerShape !== 'none').length;
  return section(
    'Workflows',
    'run-all',
    `${ai} of ${harness.workflows.length} reach a model. The runner shape is what decides whether a call is metered and whether a switch can stop it.`,
    dataTable({
      columns: ['Workflow', 'Runner', 'Switches', 'Schedule', 'Manual run'],
      className: 'z-harness__table',
      label: 'Workflows and how each reaches a model',
      empty: 'This repository has no workflows.',
      rows: shown.map((workflow) => [
        el(
          'div',
          { class: 'z-harness__name' },
          el('strong', {}, workflow.name),
          pathButton(workflow.path),
        ),
        statusPill({
          variant: shapeVariant(workflow.runnerShape),
          text: workflow.runnerShape,
          title: `${workflow.path} calls a model as ${workflow.runnerShape}`,
        }),
        workflow.switches.length === 0
          ? el('span', { class: 'z-harness__unknown' }, 'ungated')
          : el(
              'span',
              { class: 'z-harness__switches' },
              ...workflow.switches.map((name) => el('code', {}, name)),
            ),
        workflow.crons.length === 0
          ? el('span', { class: 'z-harness__unknown' }, 'no schedule')
          : el('span', { class: 'z-harness__tools' }, workflow.crons.join(' · ')),
        workflow.dispatchBypassesSwitch === null
          ? unknownCell('no dispatch trigger, or no switch — the question does not apply')
          : statusPill({
              variant: workflow.dispatchBypassesSwitch ? 'warn' : 'neutral',
              text: workflow.dispatchBypassesSwitch ? 'bypasses the switch' : 'respects the switch',
              title:
                'whether a manual workflow_dispatch runs the lane even with its *_ENABLED variable off',
            }),
      ]),
    }),
    hidden === 0 ? null : el('p', { class: 'z-muted' }, `${hidden} more not drawn.`),
  );
}

/**
 * The join: one row per workflow, with the lane, role, routine, switch, tokens
 * and cost attached to it.
 *
 * Tokens are **names**. The manifest declares which credentials a lane spends,
 * this column repeats those names, and no surface in this extension reads a
 * value.
 */
function joinsTable(harness: HarnessState): HTMLElement {
  const { shown, hidden } = truncated(harness.joins);
  const unit = harness.ledger?.unit ?? 'api-equivalent-usd';
  return section(
    'What belongs to what',
    'references',
    'One row per workflow that reaches a model: the lane that declares it, the role it runs as, the routine it follows, the variable that stops it, and the credentials it spends — by name.',
    dataTable({
      columns: [
        'Workflow',
        'Lane',
        'Role',
        'Skill',
        'Switch',
        'Tokens (names only)',
        { label: 'Spend', numeric: true },
      ],
      className: 'z-harness__table',
      label: 'The harness join',
      empty: 'Nothing in this repository joins a workflow to a lane, a role or a routine.',
      rows: shown.map((join) => [
        pathButton(join.workflowPath),
        join.laneId === null
          ? unknownCell('no manifest lane declares this workflow')
          : el('code', {}, join.laneId),
        join.agent === null ? unknownCell('the workflow names no role') : el('code', {}, join.agent),
        join.skill === null ? unknownCell('the workflow names no skill') : el('code', {}, join.skill),
        join.switch === null
          ? el('span', { class: 'z-harness__unknown' }, 'ungated')
          : el('code', {}, join.switch),
        join.tokens.length === 0
          ? unknownCell('no token declared')
          : el('span', { class: 'z-harness__tools' }, join.tokens.join(', ')),
        money(join.costUsd, unit),
      ]),
    }),
    hidden === 0 ? null : el('p', { class: 'z-muted' }, `${hidden} more not drawn.`),
  );
}

/**
 * Where the four artefacts disagree.
 *
 * Every row is a sentence about two files that say different things — a lane
 * whose workflow is gone, a role nothing runs, a switch read somewhere else, a
 * model call nothing meters. None of them is a build failure, which is exactly
 * why a screen has to be the place they show up.
 */
function findingsSection(harness: HarnessState): HTMLElement | null {
  if (harness.findings.length === 0) {
    return section(
      'Disagreements',
      'check',
      'The manifest, the workflows, the agents and the ledger all say the same things about each other.',
      el('p', { class: 'z-muted' }, 'Nothing to report.'),
    );
  }
  const { shown, hidden } = truncated(harness.findings);
  return section(
    'Disagreements',
    'warning',
    'Places two of this repository’s own files say different things. None of these fails a build, which is why they need somewhere to show up.',
    dataTable({
      columns: ['Severity', 'Kind', 'Where', 'What'],
      className: 'z-harness__table z-harness__findings',
      label: 'Harness findings',
      rows: shown.map((finding) => [
        statusPill({ variant: severityVariant(finding.severity), text: finding.severity }),
        el('code', {}, finding.kind),
        finding.path === null ? unknownCell('no single file') : pathButton(finding.path),
        finding.message,
      ]),
    }),
    hidden === 0 ? null : el('p', { class: 'z-muted' }, `${hidden} more not drawn.`),
  );
}

// ---------------------------------------------------------------------------
// The route
// ---------------------------------------------------------------------------

export function render(host: HTMLElement, state: DashboardState): void {
  clear(host);
  const harness = state.harness ?? null;

  if (harness === null) {
    host.appendChild(
      emptyState({
        icon: 'circuit-board',
        message: 'This site’s AI harness has not been read yet.',
        hint: 'It reads the repository’s own files — .claude/agents/, .claude/skills/, .github/workflows/, fleet.manifest.yml and the usage ledger — joins them, and reports where they disagree. It writes nothing and opens no socket.',
        actions: [
          el(
            'button',
            {
              class: 'z-btn',
              type: 'button',
              title: 'Read the harness from disk',
              onclick: () => {
                post('harness.open');
              },
            },
            'Read the harness',
          ),
        ],
      }),
    );
    return;
  }

  host.appendChild(
    el(
      'div',
      { class: 'z-harness__summary' },
      el(
        'div',
        { class: 'z-harness__heading' },
        el('span', { class: 'z-lane__title' }, icon('circuit-board'), 'AI harness'),
        el(
          'div',
          { class: 'z-lane__hint' },
          'What will run, as whom, spending what — joined from this repository’s own files.',
        ),
      ),
      counts(harness),
      provenance(harness),
    ),
  );

  host.appendChild(profileSection(harness));
  host.appendChild(agentsTable(harness));
  host.appendChild(skillsTable(harness));
  host.appendChild(workflowsTable(harness));
  host.appendChild(joinsTable(harness));
  const findings = findingsSection(harness);
  if (findings !== null) {
    host.appendChild(findings);
  }
}

/** The name the dashboard's renderer table uses. */
export const renderHarness = render;
