/**
 * The dashboard's entry point: the gate order, the route table, and the one
 * piece of state the host does not own.
 *
 * ### The gate order (PLAN §3.2)
 *
 * Three checks, in this order and no other:
 *
 *   1. **No snapshot yet** → the loader. Front Matter's `settings === null`
 *      spinner, with the same five-second escape hatch the panel has: a
 *      dropped `ready` must cost an empty page you can refresh, never a
 *      loading bar with no way out.
 *   2. **`showWelcome || !initialized || no content folders`** → Welcome, and
 *      nothing else — no tab bar, no toolbars. A workspace with no `zer0.json`
 *      and no registered folder has nothing for the other four routes to draw,
 *      and offering them would be four empty states instead of one instruction.
 *   3. Otherwise the route, which is `ui.route` when the host is willing to
 *      serve it and `contents` when it is not. The Distribution tab is absent
 *      from `state.tabs` when the `.cms/` contract is not present, so a
 *      persisted `catering` route degrades to Contents rather than to a blank
 *      page.
 *
 * ### Two kinds of state, kept apart on purpose
 *
 * Everything about *the workspace* — pages, drafts, lanes, settings, folders —
 * arrives as one full `DashboardState` snapshot (decision D4) and is never
 * mutated here. Everything about *this view of it* — which route, which
 * layout, which sort order, which page of results, which rows are ticked —
 * lives in `DashboardUi`, and is the only mutable state in the bundle.
 *
 * `patch()` is the single writer. It merges, mirrors the four durable
 * preferences into workspace state through `setUiState`, bumps a revision
 * counter and re-renders. The revision is what lets a section's `stale()`
 * stay a pair of cheap identity comparisons: a snapshot changes `state`, a
 * click changes `revision`, and nothing else can change either.
 *
 * ### Search is a request, not a filter
 *
 * The search box debounces at 500 ms and then asks the host to run
 * `searchPages` over the page index. Filtering the posted array in here would
 * search whatever slice happened to arrive; asking the host searches the
 * index. Replies are matched against a sequence number so a slow answer to an
 * abandoned query cannot overwrite a fast answer to the current one.
 */

import { spinner } from '../shared/components';
import { watchTheme } from '../shared/dom';
import { getMessenger, type Messenger } from '../shared/messenger';
import type {
  DashboardRoute,
  DashboardState,
  DashboardView,
  PageEntry,
  ViewState,
} from '../shared/protocol';
import { mountSections, staleOn, type Section } from '../shared/state';
import { renderContents } from './contents';
import { renderHeader } from './header';
import { render as renderCatering } from './catering';
import { render as renderDrafts } from './governance';
import { render as renderSettings } from './settings';
import { render as renderWelcome } from './welcome';

const msg = getMessenger();

/** How long the mount spinner may survive without a snapshot. */
export const LOADING_TIMEOUT_MS = 5000;

/** The search box's trailing debounce, as Front Matter had it. */
export const SEARCH_DEBOUNCE_MS = 500;

const ROUTES: ReadonlySet<string> = new Set<string>([
  'contents',
  'drafts',
  'catering',
  'settings',
  'welcome',
]);

// ---------------------------------------------------------------------------
// The view-local state
// ---------------------------------------------------------------------------

/**
 * Everything about *this view* of the workspace. None of it is authoritative:
 * losing all of it costs a scroll position and a tick box, never an edit.
 */
export interface DashboardUi {
  route: DashboardRoute;
  view: DashboardView;
  /** A `SortOption.id` — one of the six, or a user `<field>-<order>` entry. */
  sorting: string;
  /** A `GroupOption.id`; `none` means "do not group". */
  grouping: string;
  /** The draft-state navigation tab; `all` matches everything. */
  tab: string;
  /** Filter dimension id → selected value; `''` means "no filter". */
  filters: Record<string, string>;
  /** Zero-based page index. */
  page: number;
  search: string;
  /** Host-side search hits, or `null` when no search is running. */
  results: PageEntry[] | null;
  searching: boolean;
  /** Selected file paths, for the bulk actions bar. */
  selection: string[];
  /** Structure view: the workspace-relative folder being browsed. */
  folder: string | null;
  /** Structure view: which folder nodes are open, keyed by relative path. */
  expanded: Record<string, boolean>;
}

/**
 * What every section is handed. `state` is the host's snapshot, `ui` is a
 * shallow copy taken at render time — copied so a section's `stale()` can
 * compare `prev.ui.page` against `next.ui.page` and see a difference.
 */
export interface DashboardContext {
  state: DashboardState;
  ui: DashboardUi;
  msg: Messenger;
  /** Bumped by every `patch()`; the staleness signal for a local change. */
  revision: number;
  /** Merge into the view state, persist what is durable, and re-render. */
  patch(next: Partial<DashboardUi>): void;
  /** Set one filter dimension. `''` clears it. Resets to the first page. */
  setFilter(id: string, value: string): void;
  /** Add or remove one path from the bulk selection. */
  toggleSelection(filePath: string): void;
  clearSelection(): void;
  /** Run a search host-side. `''` clears the results and restores sorting. */
  runSearch(query: string): void;
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

function bootRoute(root: HTMLElement): DashboardRoute {
  const requested = root.dataset.route;
  return requested !== undefined && ROUTES.has(requested)
    ? (requested as DashboardRoute)
    : 'contents';
}

function initialUi(root: HTMLElement): DashboardUi {
  const stored = msg.getState();
  const route = stored.route !== undefined && ROUTES.has(stored.route)
    ? (stored.route as DashboardRoute)
    : bootRoute(root);
  return {
    route,
    view: stored.view ?? 'grid',
    sorting: stored.sorting ?? 'LastModifiedDesc',
    grouping: stored.grouping ?? 'none',
    tab: 'all',
    filters: { ...(stored.filters ?? {}) },
    page: stored.page ?? 0,
    search: '',
    results: null,
    searching: false,
    selection: [],
    folder: null,
    expanded: {},
  };
}

/** True when the workspace has nothing the other four routes could draw. */
function welcomeGate(state: DashboardState): boolean {
  return state.showWelcome || !state.initialized || state.contents.folders.length === 0;
}

/** The route actually rendered: the gate first, then what the host serves. */
export function effectiveRoute(state: DashboardState, ui: DashboardUi): DashboardRoute {
  if (welcomeGate(state)) {
    return 'welcome';
  }
  return state.tabs.some((tab) => tab.id === ui.route) ? ui.route : 'contents';
}

function boot(): void {
  const root = document.getElementById('z-dashboard');
  if (root === null) {
    msg.log('error', 'dashboard webview: #z-dashboard is missing from the page shell');
    return;
  }

  // Six design tokens are computed rather than aliased, and VS Code swaps a
  // theme by rewriting `document.body`'s attributes, so the observer has to be
  // running before the first snapshot paints.
  watchTheme();

  const ui = initialUi(root);
  let snapshot: DashboardState | undefined;
  let revision = 0;
  let searchSeq = 0;

  const context = (state: DashboardState): DashboardContext => ({
    state,
    // A shallow copy: the reconciler compares the *previous* context against
    // the next one, and a shared mutable object would compare equal to itself.
    ui: { ...ui, filters: { ...ui.filters }, expanded: { ...ui.expanded } },
    msg,
    revision,
    patch,
    setFilter,
    toggleSelection,
    clearSelection,
    runSearch,
  });

  const render = (): void => {
    if (snapshot === undefined) {
      return;
    }
    update(context(snapshot));
  };

  /**
   * The four preferences that must outlive this webview, mirrored into
   * workspace state under the keys PLAN §4.5 names. `Messenger.setState`
   * covers the rest, which only has to survive being hidden.
   */
  const persist = (next: Partial<DashboardUi>): void => {
    if (next.route !== undefined) {
      msg.post({ type: 'setUiState', key: 'Route', value: next.route });
    }
    if (next.view !== undefined) {
      msg.post({ type: 'setUiState', key: 'PagesView', value: next.view });
    }
    if (next.sorting !== undefined) {
      msg.post({ type: 'setUiState', key: 'Contents:Sorting', value: next.sorting });
    }
    if (next.grouping !== undefined) {
      msg.post({ type: 'setUiState', key: 'Contents:Grouping', value: next.grouping });
    }
    if (next.tab !== undefined) {
      msg.post({ type: 'setUiState', key: 'Contents:Tab', value: next.tab });
    }
    if (next.folder !== undefined && next.folder !== null) {
      msg.post({ type: 'setUiState', key: 'SelectedFolder', value: next.folder });
    }
  };

  function patch(next: Partial<DashboardUi>): void {
    Object.assign(ui, next);
    revision += 1;
    msg.setState({
      route: ui.route,
      view: ui.view,
      sorting: ui.sorting,
      grouping: ui.grouping,
      filters: ui.filters,
      page: ui.page,
      search: ui.search,
    });
    persist(next);
    render();
  }

  function setFilter(id: string, value: string): void {
    const filters = { ...ui.filters };
    if (value === '') {
      delete filters[id];
    } else {
      filters[id] = value;
    }
    patch({ filters, page: 0 });
  }

  function toggleSelection(filePath: string): void {
    const selection = ui.selection.includes(filePath)
      ? ui.selection.filter((entry) => entry !== filePath)
      : [...ui.selection, filePath];
    patch({ selection });
  }

  function clearSelection(): void {
    patch({ selection: [] });
  }

  /**
   * Ask the host to search. A reply is applied only when it is the answer to
   * the most recent question — otherwise a slow search for `a` would land on
   * top of a fast search for `abc` and show the wrong page count.
   */
  function runSearch(query: string): void {
    const trimmed = query.trim();
    const seq = ++searchSeq;
    if (trimmed === '') {
      patch({ search: '', results: null, searching: false, page: 0 });
      return;
    }
    patch({ search: trimmed, searching: true, page: 0 });
    msg
      .request<PageEntry[]>('searchContent', { query: trimmed })
      .then((pages) => {
        if (seq !== searchSeq) {
          return;
        }
        patch({ results: pages, searching: false });
      })
      .catch((error: unknown) => {
        if (seq !== searchSeq) {
          return;
        }
        msg.log('error', `search failed: ${error instanceof Error ? error.message : String(error)}`);
        patch({ results: [], searching: false });
      });
  }

  // --- sections ------------------------------------------------------------

  const headerSection: Section<DashboardContext> = {
    id: 'header',
    className: 'z-header',
    stale: staleOn<DashboardContext>(
      (ctx) => ctx.state,
      (ctx) => ctx.revision,
    ),
    render(ctx, host) {
      if (welcomeGate(ctx.state)) {
        // The welcome gate replaces the whole page, chrome included.
        return;
      }
      renderHeader(host, ctx);
    },
  };

  const bodySection: Section<DashboardContext> = {
    id: 'body',
    className: 'z-dash__content',
    stale: staleOn<DashboardContext>(
      (ctx) => ctx.state,
      (ctx) => ctx.revision,
    ),
    render(ctx, host) {
      const route = effectiveRoute(ctx.state, ctx.ui);
      switch (route) {
        case 'contents':
          renderContents(host, ctx);
          return;
        case 'drafts':
          renderDrafts(host, ctx.state);
          return;
        case 'catering':
          renderCatering(host, ctx.state);
          return;
        case 'settings':
          renderSettings(host, ctx.state);
          return;
        case 'welcome':
          renderWelcome(host, ctx.state);
          return;
      }
    },
  };

  const footerSection: Section<DashboardContext> = {
    id: 'footer',
    className: 'z-dash__footer',
    stale: staleOn<DashboardContext>((ctx) => ctx.state.version),
    render(ctx, host) {
      host.appendChild(document.createTextNode(`zer0-CMS v${ctx.state.version}`));
    },
  };

  const update = mountSections<DashboardContext>(root, [headerSection, bodySection, footerSection]);

  // --- the loader ----------------------------------------------------------

  const loader = spinner('Loading content');
  document.body.appendChild(loader);
  let cleared = false;
  const clearLoader = (): void => {
    if (!cleared) {
      cleared = true;
      loader.remove();
    }
  };
  setTimeout(() => {
    if (!cleared) {
      msg.log('warn', `dashboard: no state within ${LOADING_TIMEOUT_MS}ms; clearing the spinner`);
      clearLoader();
    }
  }, LOADING_TIMEOUT_MS);

  // --- the wire ------------------------------------------------------------

  msg.onMessage((message) => {
    if (message.type === 'focus' && message.target === 'search') {
      const box = root.querySelector('.z-search input');
      if (box instanceof HTMLInputElement) {
        box.focus();
      }
    }
  });

  msg.onState((state: ViewState) => {
    if (state.kind !== 'dashboard') {
      msg.log('warn', `dashboard webview: ignored a "${state.kind}" snapshot`);
      return;
    }
    clearLoader();
    // The host's defaults win exactly once — on the first snapshot — because
    // after that they are what the user last chose, echoed back.
    if (snapshot === undefined) {
      ui.view = state.contents.defaultView;
      ui.sorting = state.contents.defaultSorting;
    }
    snapshot = state;
    render();
    // Search hits are a copy of the index taken when the query ran. A new
    // snapshot means that copy may name a file that no longer exists, so the
    // query is asked again rather than left to show a page that is gone.
    if (ui.search !== '') {
      runSearch(ui.search);
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
