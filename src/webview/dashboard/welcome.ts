/**
 * The Welcome route — four steps, not the fork's nine.
 *
 * Framework presets (eleven SSG heuristics), configuration templates fetched
 * over the network, the Astro collection walker, the taxonomy import, the Git
 * question and the sponsor links are all gone: zer0-CMS targets Jekyll, ships
 * no telemetry and asks for nothing. What is left is the honest sequence —
 * *Initialize project → Register a content folder → Create your first content
 * type → Open the dashboard* — and each step's completion is **derived from
 * real state**, never from a "you clicked it" flag:
 *
 * | Step | Complete when |
 * |---|---|
 * | Initialize project | `state.initialized` — the config file is on disk |
 * | Register a content folder | a folder is registered |
 * | Create your first content type | a content type is defined |
 * | Open the dashboard | there is content to show |
 *
 * That last row is why the step reads as done before it is clicked: the
 * dashboard is worth opening once it has something in it. The step's *action*
 * is what clears this screen — it drops the persisted `welcome` route, tells
 * the host to stop forcing the welcome gate, and asks for a fresh snapshot.
 *
 * The host may refine any of this by sending `WelcomeState.steps`: an entry
 * whose `id` matches one below overrides that step's name, description, status
 * and action. It cannot add or remove steps — four is the shape of the screen.
 */

import { clear, el, icon } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type {
  ActionItem,
  CommandId,
  DashboardState,
  WelcomeStep,
} from '../shared/protocol';

/** The step ids the host may override, in render order. */
export const STEP_IDS = ['init', 'folder', 'contentType', 'dashboard'] as const;

/** The workspace-state key the host reads to decide whether to force Welcome. */
export const WELCOME_KEY = 'welcome';

type StepStatus = WelcomeStep['status'];

function post(id: CommandId, args?: unknown): void {
  getMessenger().command(id, args);
}

/**
 * Leave the welcome screen for good: forget the persisted route, tell the host
 * this workspace has been through onboarding, then ask for a snapshot. The
 * host still owns the gate — if the project is genuinely not set up it will
 * send `showWelcome` again and we land right back here, which is correct.
 */
function openDashboard(): void {
  const messenger = getMessenger();
  messenger.setState({ route: 'contents' });
  messenger.post({ type: 'setUiState', key: WELCOME_KEY, value: 'false' });
  messenger.command('refresh');
}

// ---------------------------------------------------------------------------
// The four steps
// ---------------------------------------------------------------------------

interface StepModel {
  id: string;
  name: string;
  description: string;
  status: StepStatus;
  action?: ActionItem;
  /** Runs instead of posting `action`; only the last step needs one. */
  onClick?: () => void;
}

function derive(state: DashboardState): StepModel[] {
  const hasFolder = state.settings.folders.length > 0;
  const hasContentType = state.settings.contentTypes.length > 0;
  const hasContent = state.contents.pages.length > 0;

  const done = (complete: boolean): StepStatus => (complete ? 'completed' : 'notStarted');

  const steps: StepModel[] = [
    {
      id: 'init',
      name: 'Initialize project',
      description:
        'Create the project configuration file and the folders zer0-CMS needs. ' +
        'Everything else is written into it.',
      status: done(state.initialized),
      action: { id: 'init', label: 'Initialize project' },
    },
    {
      id: 'folder',
      name: 'Register a content folder',
      description:
        'Tell zer0-CMS where your content lives. You can also right-click a folder in the ' +
        'explorer and register it from there.',
      status: done(hasFolder),
      action: { id: 'registerFolder', label: 'Register a folder' },
    },
    {
      id: 'contentType',
      name: 'Create your first content type',
      description:
        'A content type describes a page’s front matter: which fields exist, which are ' +
        'required, and how each one is edited in the panel.',
      status: done(hasContentType),
      action: { id: 'contentType.generate', label: 'Generate from the open file' },
    },
    {
      id: 'dashboard',
      name: 'Open the dashboard',
      description:
        'Once the steps above are done, your content shows up here — cards, filters, ' +
        'the draft queue and the distribution lanes.',
      status: done(hasContent),
    },
  ];

  // Exactly one step is "active": the first that is not finished. The rest
  // stay `notStarted` so the connector line reads as progress rather than as
  // four simultaneous invitations.
  const next = steps.find((step) => step.status !== 'completed');
  if (next !== undefined) {
    next.status = 'active';
  }
  return steps;
}

/** Apply host overrides for any step whose `id` matches one of ours. */
function merge(steps: StepModel[], overrides: readonly WelcomeStep[]): StepModel[] {
  const byId = new Map(overrides.map((step) => [step.id, step] as const));
  return steps.map((step) => {
    const override = byId.get(step.id);
    if (override === undefined) {
      return step;
    }
    const merged: StepModel = {
      ...step,
      name: override.name.trim() === '' ? step.name : override.name,
      description: override.description.trim() === '' ? step.description : override.description,
      status: override.status,
    };
    if (override.action !== undefined) {
      merged.action = override.action;
    }
    return merged;
  });
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function stepAction(step: StepModel, state: DashboardState): HTMLElement | null {
  if (step.id === 'dashboard') {
    const ready = state.initialized && state.settings.folders.length > 0;
    return el(
      'div',
      { class: 'z-settings__buttons' },
      el(
        'button',
        {
          class: 'z-btn',
          type: 'button',
          disabled: !ready,
          title: ready
            ? 'Leave the welcome screen'
            : 'Initialize the project and register a content folder first',
          onclick: openDashboard,
        },
        'Open the dashboard',
      ),
    );
  }

  const action = step.action;
  if (action === undefined) {
    return null;
  }
  return el(
    'div',
    { class: 'z-settings__buttons' },
    el(
      'button',
      {
        class: step.status === 'completed' ? 'z-btn z-btn--secondary' : 'z-btn',
        type: 'button',
        disabled: action.disabled === true,
        title: action.title ?? action.label,
        onclick: () => {
          post(action.id, action.args);
        },
      },
      action.label,
    ),
  );
}

function stepItem(step: StepModel, state: DashboardState): HTMLElement {
  const modifier =
    step.status === 'completed' ? ' is-completed' : step.status === 'active' ? ' is-active' : '';
  return el(
    'li',
    { class: `z-step${modifier}`, dataset: { step: step.id } },
    el(
      'span',
      { class: 'z-step__marker', attrs: { 'aria-hidden': 'true' } },
      step.status === 'completed' ? icon('check') : null,
    ),
    el('h3', { class: 'z-step__name' }, step.name),
    el('p', { class: 'z-step__description' }, step.description),
    stepAction(step, state),
  );
}

export function render(host: HTMLElement, state: DashboardState): void {
  clear(host);
  const steps = merge(derive(state), state.welcome.steps);

  const hero = el(
    'div',
    { class: 'z-welcome__hero' },
    el('h1', {}, 'Manage your static site with zer0-CMS'),
    el(
      'p',
      {},
      'Front matter in a side panel, a dashboard over your content, and a governed path ' +
        'from draft to published — with no runtime dependencies and nothing phoning home.',
    ),
    el(
      'p',
      { class: 'z-muted' },
      'Work through the steps below. Each one is marked done from what is actually on ' +
        'disk, so you can leave and come back.',
    ),
  );

  const list = el('ol', { class: 'z-steps', attrs: { role: 'list' } });
  for (const step of steps) {
    list.appendChild(stepItem(step, state));
  }

  host.appendChild(
    el(
      'div',
      { class: 'z-welcome' },
      hero,
      el(
        'nav',
        { class: 'z-welcome__hero', attrs: { 'aria-label': 'Progress' } },
        el('h2', {}, 'Perform the next steps to get started'),
        list,
      ),
    ),
  );
}
