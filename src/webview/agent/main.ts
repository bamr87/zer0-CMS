/**
 * The agent panel's front end: transcript, status bar, approval card, composer.
 *
 * Four projections mounted on the shared reconciler — header, notice,
 * transcript, approval — plus one live control.
 *
 * The composer is deliberately **not** a `Section`. The reconciler rebuilds a
 * stale section by clearing it, and exempts a section that currently holds
 * focus so a keystroke is never interrupted; park a focused textarea in there
 * and the two rules combine badly. The composer takes focus on open, so it
 * would then own the focus indefinitely and every later snapshot would be
 * deferred until the user clicked somewhere else — meaning the box never
 * disables and never says "the agent is working" while a run is in flight.
 * A control whose value the user owns does not want to be re-derived from a
 * snapshot at all: it is built once and its `disabled` and `placeholder` are
 * synced in place. That also makes the draft safe for free, with no shadow copy
 * of the text living outside the DOM.
 *
 * Two rules this file exists to keep:
 *
 *  - **Nothing becomes markup.** Every character of agent output — a file body,
 *    a shell command, a diff hunk, an error — is written with `textContent`
 *    through `el()`. The diff is coloured by giving each *line* its own `<span>`
 *    and choosing a class from the line's first character, never by building
 *    HTML from the text. That is what lets the page ship under
 *    `default-src 'none'` with a real guarantee behind it rather than a hope.
 *  - **The buttons name intents.** Approve, Deny, Stop and Send post a
 *    `command` with an id from the closed `CommandId` union and, at most, the
 *    id of the card being answered or the prompt being sent. The host re-reads
 *    configuration and re-checks the enabled flag before acting (D5); disabling
 *    a button here is a courtesy to the user, not a control.
 */

import { append, el, icon, srOnly, watchTheme } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type { AgentState, TranscriptEntry, TranscriptRole, ViewState } from '../shared/protocol';
import { mountSections, staleOn, type Section } from '../shared/state';

const msg = getMessenger();

const ROLE_LABEL: Record<TranscriptRole, string> = {
  user: 'you',
  assistant: 'claude',
  tool: 'tool',
  system: 'system',
  result: 'result',
  error: 'error',
};

/** `2026-07-31T14:05:22Z` → `14:05:22`. */
function clockOf(stamp: string): string {
  return stamp.length >= 19 ? stamp.slice(11, 19) : stamp;
}


// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

const header: Section<AgentState> = {
  id: 'header',
  className: 'z-agent__bar',
  stale: staleOn(
    (state) => state.running,
    (state) => state.status,
    (state) => state.model,
    (state) => state.enabled,
  ),
  render(state, host) {
    const pill = el(
      'span',
      { class: state.running ? 'z-agent__status is-running' : 'z-agent__status' },
      state.running ? 'running' : state.status,
    );
    append(
      host,
      el('h1', {}, 'AI agent'),
      pill,
      el('span', { class: 'z-agent__spacer' }),
      el('span', { class: 'z-muted' }, state.model),
      el(
        'button',
        {
          class: 'z-icon-btn',
          type: 'button',
          title: 'Stop the agent',
          disabled: !state.running,
          onclick: () => {
            msg.command('agent.stop');
          },
        },
        icon('debug-stop'),
        srOnly('Stop the agent'),
      ),
    );
  },
};

const notice: Section<AgentState> = {
  id: 'notice',
  stale: staleOn((state) => state.notice),
  render(state, host) {
    if (state.notice === null) {
      return;
    }
    host.appendChild(el('p', { class: 'z-agent__notice' }, state.notice));
  },
};

function transcriptLine(entry: TranscriptEntry): HTMLElement {
  return el(
    'div',
    { class: `z-agent__line z-agent__line--${entry.role}` },
    el(
      'div',
      { class: 'z-agent__gutter' },
      el('span', { class: 'z-agent__role' }, ROLE_LABEL[entry.role]),
      el('span', {}, clockOf(entry.at)),
    ),
    // `textContent` via a text node, and `white-space: pre-wrap` in the
    // stylesheet: the model's newlines survive without a single tag.
    el('p', { class: 'z-agent__text' }, entry.text),
  );
}

const transcript: Section<AgentState> = {
  id: 'transcript',
  stale: staleOn(
    (state) => state.transcript.length,
    (state) => state.transcript[state.transcript.length - 1]?.at,
    (state) => state.transcript[state.transcript.length - 1]?.text,
  ),
  render(state, host) {
    if (state.transcript.length === 0) {
      host.appendChild(
        el(
          'p',
          { class: 'z-empty' },
          state.enabled
            ? 'Ask the agent to draft, review or reorganise content. Every file change is shown for approval before it happens.'
            : 'The agent is off.',
        ),
      );
      return;
    }
    const log = el('div', { class: 'z-agent__log' });
    for (const entry of state.transcript) {
      log.appendChild(transcriptLine(entry));
    }
    host.appendChild(log);
  },
};

/**
 * The diff pane. One `<span>` per line, classed from the line's first
 * character — the only place the text influences the DOM at all, and it
 * influences the *class*, never the structure.
 */
function diffPane(detail: string): HTMLElement {
  const pre = el('pre', { class: 'z-agent__diff' });
  for (const line of detail.split('\n')) {
    const first = line.charAt(0);
    const className = first === '+' ? 'is-add' : first === '-' ? 'is-del' : first === '#' ? 'is-meta' : '';
    pre.appendChild(className ? el('span', { class: className }, line) : el('span', {}, line));
  }
  return pre;
}

const approval: Section<AgentState> = {
  id: 'approval',
  stale: staleOn((state) => state.approval?.id ?? null),
  render(state, host) {
    const card = state.approval;
    if (!card) {
      return;
    }
    const answer = (id: string, approved: boolean): void => {
      msg.command(approved ? 'agent.approve' : 'agent.deny', { id });
    };
    append(
      host,
      el(
        'section',
        { class: 'z-agent__card', attrs: { 'aria-label': `Approve ${card.tool}` } },
        el(
          'div',
          { class: 'z-agent__card__head' },
          el('span', { class: 'z-agent__card__tool' }, card.tool),
          el('span', { class: 'z-agent__card__summary' }, card.summary),
        ),
        diffPane(card.detail),
        el(
          'div',
          { class: 'z-agent__card__actions' },
          el(
            'button',
            {
              class: 'z-btn z-btn--secondary',
              type: 'button',
              onclick: () => {
                answer(card.id, false);
              },
            },
            'Deny',
          ),
          el(
            'button',
            {
              class: 'z-btn',
              type: 'button',
              onclick: () => {
                answer(card.id, true);
              },
            },
            'Approve',
          ),
        ),
      ),
    );
  },
};

// ---------------------------------------------------------------------------
// The composer — a live control, built once
// ---------------------------------------------------------------------------

interface Composer {
  el: HTMLElement;
  sync(state: AgentState): void;
}

function buildComposer(): Composer {
  const input = el('textarea', {
    rows: 3,
    placeholder: 'What should the agent do?',
    attrs: { 'aria-label': 'Agent prompt' },
  });
  const button = el('button', { class: 'z-btn', type: 'button' }, 'Send');

  const submit = (): void => {
    const text = input.value.trim();
    if (text.length === 0 || input.disabled) {
      return;
    }
    input.value = '';
    msg.command('agent.send', { prompt: text });
  };

  const refresh = (): void => {
    button.disabled = input.disabled || input.value.trim().length === 0;
  };

  button.addEventListener('click', submit);
  input.addEventListener('input', refresh);
  input.addEventListener('keydown', (event) => {
    if (event instanceof KeyboardEvent && event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submit();
    }
  });

  const root = el(
    'div',
    { class: 'z-section z-agent__composer', dataset: { section: 'composer' } },
    input,
    el(
      'div',
      { class: 'z-agent__composer__row' },
      el('span', { class: 'z-agent__hint' }, 'Ctrl/Cmd + Enter to send'),
      el('span', { class: 'z-agent__spacer' }),
      button,
    ),
  );

  let focused = false;
  return {
    el: root,
    sync(state) {
      // Blocking is a courtesy, not a gate: the host re-checks `enabled` on
      // every start regardless of what this element says (D5).
      const blocked = !state.enabled || !state.available || state.running;
      input.disabled = blocked;
      input.placeholder = state.running ? 'The agent is working…' : 'What should the agent do?';
      refresh();
      if (!blocked && !focused) {
        focused = true;
        input.focus();
      }
    },
  };
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

function boot(): void {
  const root = document.getElementById('z-agent');
  if (!root) {
    msg.log('error', 'agent webview: #z-agent is missing from the page shell');
    return;
  }

  // Six of the design tokens are computed rather than aliased, and VS Code
  // swaps a theme by rewriting `document.body`'s attributes — so the observer
  // has to be running before the first snapshot paints.
  watchTheme();

  // `mountSections` clears the root, so the composer is appended after it.
  const update = mountSections<AgentState>(root, [header, notice, transcript, approval]);
  const composer = buildComposer();
  root.appendChild(composer.el);
  let lines = -1;

  msg.onState((state: ViewState) => {
    if (state.kind !== 'agent') {
      // The host only ever posts `AgentState` here; anything else means two
      // surfaces are sharing a webview, which is worth a line in the log.
      msg.log('warn', `agent webview: ignored a "${state.kind}" snapshot`);
      return;
    }
    update(state);
    composer.sync(state);
    if (state.transcript.length !== lines) {
      lines = state.transcript.length;
      const pane = root.querySelector('[data-section="transcript"]');
      if (pane instanceof HTMLElement) {
        pane.scrollTop = pane.scrollHeight;
      }
    }
  });

  msg.ready();
}

// The bundle is an IIFE injected at the end of `<body>`, so the element exists;
// the readyState guard covers a future move into `<head>`.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}
