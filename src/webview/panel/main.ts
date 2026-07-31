/**
 * The panel's entry point: boot, section order, scroll restore, and the three
 * imperative host messages.
 *
 * The ten rows of PLAN §3.1 are mounted once, in the plan's order, and each one
 * decides for itself whether this snapshot gives it anything to draw. Nothing
 * is created or destroyed on a route change because the panel has no routes —
 * there is one page, and `zer0Cms.panel.sections` says which of its parts
 * exist.
 *
 * ### Order comes from configuration, position from the plan
 *
 * The seven configurable sections are mounted in §3.1's canonical order, and
 * then re-ordered to match `state.sections` whenever that list itself changes.
 * A setting that lists `["metadata", "governance"]` therefore gets metadata
 * first, while a workspace that never touches the setting gets the plan's
 * order. Re-ordering moves existing hosts rather than rebuilding them, and only
 * fires when the joined id list differs, so it costs nothing on a normal
 * snapshot and never runs under a keystroke.
 *
 * ### The spinner has an escape hatch
 *
 * `mountLoading` paints the loader immediately and clears it either when the
 * first snapshot arrives or after five seconds, whichever comes first. A
 * dropped `ready` — the host was mid-refresh, the view was hidden while the
 * message was in flight — then costs an empty panel that the next state fills
 * in, instead of a loading bar with no way out.
 *
 * ### Three messages are not state
 *
 * `collapseAll` (the title-bar command), `focus` (the tags/categories
 * keybindings) and `progress` are genuinely imperative: they address a control
 * or an animation, not a value. Everything else the panel knows arrives as one
 * full `PanelState` snapshot (decision D4).
 */

import { debounce, watchTheme } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type { PanelSectionId, PanelState, ViewState } from '../shared/protocol';
import { mountSections, staleOn, type Section } from '../shared/state';
import {
  actionsSection,
  otherActionsSection,
  recentSection,
  settingsSection,
} from './actions';
import { closeAllSections, developerBar, emptyState, initializeAction, mountLoading } from './chrome';
import { governanceSection } from './governance';
import { focusTaxonomyField, metadataSection, setFieldProgress } from './metadata';
import { seoSection } from './seo';

const msg = getMessenger();

/** Sections whose presence keeps the `.base__empty` state away. */
const ACTION_SECTIONS: readonly PanelSectionId[] = [
  'governance',
  'actions',
  'recent',
  'settings',
  'other',
];

// ---------------------------------------------------------------------------
// The three fixed rows
// ---------------------------------------------------------------------------

const developerSection: Section<PanelState> = {
  id: 'developer',
  stale: staleOn((state) => state.developer),
  render(state, host) {
    if (state.developer) {
      host.appendChild(developerBar());
    }
  },
};

const initializeSection: Section<PanelState> = {
  id: 'initialize',
  stale: staleOn((state) => state.initialized),
  render(state, host) {
    if (!state.initialized) {
      host.appendChild(initializeAction());
    }
  },
};

const emptySection: Section<PanelState> = {
  id: 'empty',
  stale: staleOn((state) => ACTION_SECTIONS.some((id) => state.sections.includes(id))),
  render(state, host) {
    if (!ACTION_SECTIONS.some((id) => state.sections.includes(id))) {
      host.appendChild(emptyState());
    }
  },
};

/** §3.1, top to bottom. The middle seven are re-ordered from configuration. */
const SECTIONS: Array<Section<PanelState>> = [
  developerSection,
  initializeSection,
  governanceSection,
  metadataSection,
  seoSection,
  actionsSection,
  recentSection,
  settingsSection,
  otherActionsSection,
  emptySection,
];

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

function boot(): void {
  const root = document.getElementById('z-panel');
  if (root === null) {
    msg.log('error', 'panel webview: #z-panel is missing from the page shell');
    return;
  }

  // Six design tokens are computed rather than aliased and VS Code swaps a
  // theme by rewriting `document.body`'s attributes, so the observer has to be
  // running before the first snapshot paints.
  watchTheme();

  const update = mountSections<PanelState>(root, SECTIONS);

  // `mountSections` appends one host per section, in array order. Index them
  // now so re-ordering never has to build a selector from a state value.
  const hosts = new Map<string, HTMLElement>();
  for (const node of Array.from(root.querySelectorAll('.z-section'))) {
    if (node instanceof HTMLElement && node.dataset.section !== undefined) {
      hosts.set(node.dataset.section, node);
    }
  }
  const tail = hosts.get('empty') ?? null;

  let order = '';
  const applyOrder = (state: PanelState): void => {
    const next = state.sections.join(',');
    if (next === order) {
      return;
    }
    order = next;
    for (const id of state.sections) {
      const host = hosts.get(id);
      if (host !== undefined) {
        // `insertBefore` on an attached node moves it; the empty-state host is
        // the anchor so the configurable block always ends above it.
        root.insertBefore(host, tail);
      }
    }
  };

  // Restore the scroll offset once, after the first paint, and record it from
  // then on. Front Matter restored on returning from its media screen; there is
  // no such screen any more, but a panel that jumps to the top every time the
  // host refreshes is the same annoyance from a different cause.
  const saveScroll = debounce(() => {
    msg.setState({ scroll: window.scrollY });
  }, 250);
  window.addEventListener('scroll', saveScroll, { capture: true, passive: true });

  const loading = mountLoading(document.body);
  let restored = false;

  msg.onMessage((message) => {
    switch (message.type) {
      case 'collapseAll':
        closeAllSections();
        return;
      case 'focus':
        focusTaxonomyField(message.target);
        return;
      case 'progress':
        if (message.scope === 'panel') {
          if (message.message === null) {
            loading.done();
          } else {
            loading.show(message.message);
          }
        } else {
          setFieldProgress(message.path, message.message);
        }
        return;
      default:
        // `state` has its own subscriber and `result` is the messenger's own.
        return;
    }
  });

  msg.onState((state: ViewState) => {
    if (state.kind !== 'panel') {
      msg.log('warn', `panel webview: ignored a "${state.kind}" snapshot`);
      return;
    }
    loading.done();
    update(state);
    applyOrder(state);
    if (!restored) {
      restored = true;
      const offset = msg.getState().scroll;
      if (typeof offset === 'number' && offset > 0) {
        // After the paint, or the document is not yet tall enough to scroll.
        requestAnimationFrame(() => {
          window.scrollTo({ top: offset });
        });
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
