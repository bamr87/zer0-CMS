/**
 * The dashboard's chrome: one tab bar, and — on Contents only — the five-row
 * toolbar stack Front Matter had.
 *
 * ```
 * ┌ row 1 ── tab bar ──────────────── Contents · Drafts · Distribution · … ┐
 * │ row 2   Create content  ⟳                                     [Search] │
 * │ row 3   All articles (12)  Published (9)  In draft (3)     ▦ ▤ ⊞       │
 * │ row 4   ✕ Clear   Showing: All types   Tag: …   Group by: …   Sort by: │
 * │ row 5   Showing 1 to 16 of 41 results        First ‹ 1 2 3 › Last      │
 * │ row 6   👁 View   ✎ Rename   🗑 Delete              2 selected  ☑ All   │
 * └───────────────────────────────────────────────────────────────────────┘
 * ```
 *
 * Row 1's action strip also carries the **site switcher** in a multi-root
 * window — "which repository am I about to publish into?" is a question every
 * tab needs answered, not only the Sites one.
 *
 * Rows 2-6 exist only on `/contents`; the other routes get the tab bar and —
 * if they registered one — a single toolbar row of their own, because a sort
 * control above a draft queue would be a control that does nothing, and Audit,
 * Workflows and Monitor each have filters that are not Contents' filters.
 *
 * That is what `setRouteToolbar()` is for. A route module registers its own
 * toolbar at import time and this file never learns what is in it; the
 * alternative — `header.ts` importing every route — is a cycle the moment a
 * route wants a shared control back. A route that registers nothing gets the
 * tab bar and nothing else, exactly as before.
 *
 * Three behaviours here are contracts rather than preferences:
 *
 *   - **Sorting is disabled while a search query is active.** The host returns
 *     hits in relevance order; a sort would discard that ranking, so the
 *     control is greyed rather than silently ignored.
 *   - **Pagination is hidden while grouping is active**, and in Structure
 *     view. A page boundary through the middle of a year means nothing, and a
 *     folder tree is not a list of pages.
 *   - **View and Rename are enabled at exactly one selection.** Not zero, not
 *     two. Delete works on any non-empty selection and always asks first.
 *
 * The search box debounces at 500 ms and hands the query to `ctx.runSearch`,
 * which asks the host. Nothing here filters an array.
 */

import { alert, menuButton, pagination, textField, type MenuItem } from '../shared/components';
import { el, icon, srOnly } from '../shared/dom';
import type { DashboardRoute, FilterDimension } from '../shared/protocol';
import { processPages } from './contents';
import { SEARCH_DEBOUNCE_MS, type DashboardContext } from './main';

/** Where "Documentation" goes. The repository, not a marketing site. */
const DOCS_URL = 'https://github.com/bamr87/zer0-CMS#readme';

// ---------------------------------------------------------------------------
// The per-route toolbar slot
// ---------------------------------------------------------------------------

/** Build one route's toolbar row, or `null` when it has nothing to show. */
export type RouteToolbar = (ctx: DashboardContext) => HTMLElement | null;

const ROUTE_TOOLBARS = new Map<DashboardRoute, RouteToolbar>();

/**
 * Register a route's toolbar. Called at module scope by the route that owns it,
 * so the registry is populated by the same import `main.ts`'s route table needs
 * anyway — and `header.ts` never imports a route.
 *
 * `contents` is not registerable: its five-row stack is this file's, and its
 * persisted keys (`sorting`, `grouping`, `page`, `view`) are read here.
 */
export function setRouteToolbar(route: DashboardRoute, toolbar: RouteToolbar): void {
  if (route === 'contents') {
    throw new Error('header: the Contents toolbar is owned by header.ts, not by a route');
  }
  ROUTE_TOOLBARS.set(route, toolbar);
}

/** What a route registered, if anything. Exported for the route table's tests. */
export function routeToolbar(route: DashboardRoute): RouteToolbar | undefined {
  return ROUTE_TOOLBARS.get(route);
}

/** The codicon each layout is drawn with, in switch order. */
const VIEW_ICONS: ReadonlyArray<{ id: 'grid' | 'list' | 'structure'; glyph: string; label: string }> = [
  { id: 'grid', glyph: 'layout', label: 'Grid view' },
  { id: 'list', glyph: 'list-flat', label: 'List view' },
  { id: 'structure', glyph: 'list-tree', label: 'Structure view' },
];

/** The "no filter" entry each dimension leads with. */
function defaultFilterLabel(dimension: FilterDimension): string {
  return dimension.id === 'folder' ? 'All types' : 'No filter';
}

// ---------------------------------------------------------------------------
// Row 1 — the tab bar
// ---------------------------------------------------------------------------

/**
 * The site switcher — a menu of open folders, in the tab bar's action strip.
 *
 * Present only in a multi-root window, because a menu with one entry is a
 * control that cannot do anything. Selecting an entry posts
 * `site.setActive {site: '<id>'}`: an intent and a target, exactly like every
 * other button in this webview. The host validates that id against
 * `SiteRegistry`, which is the only place that knows which folders are open —
 * this menu is drawing a list the host sent, and a list can go stale between a
 * render and a click (decision D5).
 *
 * It lives beside the output and documentation buttons rather than inside the
 * Sites tab, because "which repository am I about to publish into?" is a
 * question every tab needs answered, not only that one.
 */
function siteSwitcher(ctx: DashboardContext): HTMLElement | null {
  const sites = ctx.state.sites;
  if (sites === undefined || !sites.multi) {
    return null;
  }
  const active = sites.sites.find((site) => site.active);
  return menuButton({
    label: 'Site',
    value: active?.name ?? '(none)',
    align: 'end',
    triggerTitle: 'Switch the active site',
    items: sites.sites.map((site) => ({
      id: site.id,
      label: site.name,
      icon: 'book',
      checked: site.active,
    })),
    onSelect: (id) => {
      ctx.msg.command('site.setActive', { site: id });
    },
  });
}

function tabBar(ctx: DashboardContext): HTMLElement {
  const active = ctx.state.tabs.some((tab) => tab.id === ctx.ui.route) ? ctx.ui.route : 'contents';

  const tabs = ctx.state.tabs.map((tab) =>
    el(
      'li',
      { attrs: { role: 'none' } },
      el(
        'button',
        {
          class: tab.id === active ? 'z-tab is-active' : 'z-tab',
          type: 'button',
          attrs: { role: 'tab', 'aria-selected': tab.id === active ? 'true' : 'false' },
          onclick: () => {
            ctx.patch({ route: tab.id as DashboardRoute, selection: [] });
          },
        },
        icon(tab.icon),
        tab.label,
      ),
    ),
  );

  const actions = el(
    'div',
    { class: 'z-tabbar__actions' },
    // The site switcher, only when there is more than one site to switch
    // between. It posts an id and nothing else; see `siteSwitcher`.
    siteSwitcher(ctx),
    // Reload and DevTools, on the two `command:` URIs the host's allow-list
    // contains. Present only outside a released build.
    ctx.state.developer
      ? [
          el(
            'a',
            {
              class: 'z-icon-btn',
              href: 'command:workbench.action.webview.reloadWebviewAction',
              title: 'Reload the dashboard',
            },
            icon('refresh'),
            srOnly('Reload the dashboard'),
          ),
          el(
            'a',
            {
              class: 'z-icon-btn',
              href: 'command:workbench.action.webview.openDeveloperTools',
              title: 'Open the DevTools',
            },
            icon('debug'),
            srOnly('Open the DevTools'),
          ),
        ]
      : null,
    el(
      'button',
      {
        class: 'z-icon-btn',
        type: 'button',
        title: 'Show the zer0-CMS output',
        onclick: () => {
          ctx.msg.command('showOutput');
        },
      },
      icon('output'),
      srOnly('Show the zer0-CMS output'),
    ),
    el(
      'button',
      {
        class: 'z-icon-btn',
        type: 'button',
        title: 'Documentation',
        onclick: () => {
          ctx.msg.command('openLink', { url: DOCS_URL });
        },
      },
      icon('book'),
      srOnly('Documentation'),
    ),
  );

  return el(
    'div',
    { class: 'z-tabbar' },
    el('ul', { class: 'z-tabbar__list', attrs: { role: 'tablist' } }, tabs),
    actions,
  );
}

// ---------------------------------------------------------------------------
// Row 2 — create, refresh, search
// ---------------------------------------------------------------------------

function createButton(ctx: DashboardContext): HTMLElement {
  const folders = ctx.state.contents.folders.filter((folder) => !folder.disableCreation);
  const primary = el(
    'button',
    {
      class: 'z-btn',
      type: 'button',
      disabled: !ctx.state.initialized,
      title: 'Create content',
      onclick: () => {
        ctx.msg.command('createContent');
      },
    },
    'Create content',
  );
  if (folders.length < 2) {
    return primary;
  }
  return el(
    'div',
    { class: 'z-toolbar__group' },
    primary,
    menuButton({
      triggerIcon: 'chevron-down',
      triggerTitle: 'Create in a specific folder',
      disabled: !ctx.state.initialized,
      items: folders.map((folder) => ({
        id: folder.path,
        label: `Create in ${folder.title}`,
        icon: 'new-file',
      })),
      onSelect: (folderPath) => {
        ctx.msg.command('createContentInFolder', folderPath);
      },
    }),
  );
}

function searchBox(ctx: DashboardContext): HTMLElement {
  const field = textField({
    value: ctx.ui.search,
    placeholder: 'Search',
    ariaLabel: 'Search',
    debounceMs: SEARCH_DEBOUNCE_MS,
    onChange: (value) => {
      ctx.runSearch(value);
    },
    onSubmit: (value) => {
      ctx.runSearch(value);
    },
  });
  return el(
    'div',
    { class: 'z-search' },
    icon(ctx.ui.searching ? 'loading' : 'search'),
    field.el,
    ctx.ui.search === ''
      ? null
      : el(
          'button',
          {
            class: 'z-icon-btn',
            type: 'button',
            title: 'Clear the search',
            onclick: () => {
              ctx.runSearch('');
            },
          },
          icon('close'),
          srOnly('Clear the search'),
        ),
  );
}

function toolbarRow(ctx: DashboardContext): HTMLElement {
  return el(
    'div',
    { class: 'z-toolbar' },
    el(
      'div',
      { class: 'z-toolbar__group' },
      createButton(ctx),
      el(
        'button',
        {
          class: 'z-icon-btn',
          type: 'button',
          title: 'Refresh the dashboard',
          onclick: () => {
            // Front Matter's refresh also reset the view state; a stale filter
            // surviving a refresh is what makes "nothing happened" reports.
            ctx.patch({ search: '', results: null, filters: {}, tab: 'all', page: 0 });
            ctx.msg.command('refresh');
          },
        },
        icon('refresh'),
        srOnly('Refresh the dashboard'),
      ),
    ),
    searchBox(ctx),
  );
}

// ---------------------------------------------------------------------------
// Row 3 — draft-state tabs and the view switch
// ---------------------------------------------------------------------------

function navigationRow(ctx: DashboardContext): HTMLElement {
  const tabs = ctx.state.contents.tabs.map((tab) =>
    el(
      'button',
      {
        class: tab.id === ctx.ui.tab ? 'z-navbar__tab is-active' : 'z-navbar__tab',
        type: 'button',
        attrs: tab.id === ctx.ui.tab ? { 'aria-current': 'page' } : {},
        onclick: () => {
          ctx.patch({ tab: tab.id, page: 0, selection: [] });
        },
      },
      tab.label,
      el('span', { class: 'z-navbar__count' }, String(tab.count)),
    ),
  );

  const views = VIEW_ICONS.map((entry) =>
    el(
      'button',
      {
        class: entry.id === ctx.ui.view ? 'z-icon-btn is-active' : 'z-icon-btn',
        type: 'button',
        title: entry.label,
        onclick: () => {
          ctx.patch({ view: entry.id, page: 0 });
        },
      },
      icon(entry.glyph),
      srOnly(entry.label),
    ),
  );

  return el(
    'div',
    { class: 'z-navbar' },
    el('nav', { class: 'z-toolbar__group', attrs: { 'aria-label': 'Draft state' } }, tabs),
    el('div', { class: 'z-viewswitch' }, views),
  );
}

// ---------------------------------------------------------------------------
// Row 4 — clear, filters, grouping, sorting
// ---------------------------------------------------------------------------

function clearFilters(ctx: DashboardContext): HTMLElement | null {
  const dirty =
    Object.values(ctx.ui.filters).some((value) => value !== '') ||
    ctx.ui.search !== '' ||
    ctx.ui.tab !== 'all' ||
    (ctx.ui.grouping !== 'none' && ctx.ui.grouping !== '');
  if (!dirty) {
    return null;
  }
  return el(
    'button',
    {
      class: 'z-actionsbar__item z-actionsbar__item--danger',
      type: 'button',
      title: 'Clear filters, grouping, and search',
      onclick: () => {
        ctx.patch({
          filters: {},
          search: '',
          results: null,
          tab: 'all',
          grouping: 'none',
          sorting: ctx.state.contents.defaultSorting,
          page: 0,
        });
      },
    },
    icon('close'),
    'Clear',
  );
}

function filterMenu(dimension: FilterDimension, ctx: DashboardContext): HTMLElement | null {
  if (dimension.values.length === 0) {
    return null;
  }
  const current = ctx.ui.filters[dimension.id] ?? '';
  const items: MenuItem[] = [
    { id: '', label: defaultFilterLabel(dimension), checked: current === '' },
    ...dimension.values.map((value) => ({
      id: value,
      label: value,
      checked: value === current,
      separatorBefore: false,
    })),
  ];
  return menuButton({
    label: dimension.label,
    value: current === '' ? defaultFilterLabel(dimension) : current,
    items,
    onSelect: (value) => {
      ctx.setFilter(dimension.id, value);
    },
  });
}

function groupingMenu(ctx: DashboardContext): HTMLElement | null {
  const options = ctx.state.contents.groupOptions;
  if (options.length === 0) {
    return null;
  }
  const current = options.find((option) => option.id === ctx.ui.grouping) ?? options[0];
  return menuButton({
    label: 'Group by',
    value: current?.label ?? 'None',
    items: options.map((option) => ({
      id: option.id,
      label: option.label,
      checked: option.id === ctx.ui.grouping,
    })),
    onSelect: (id) => {
      ctx.patch({ grouping: id, page: 0 });
    },
  });
}

function sortingMenu(ctx: DashboardContext): HTMLElement {
  const options = ctx.state.contents.sortOptions;
  const current = options.find((option) => option.id === ctx.ui.sorting);
  const searching = ctx.ui.search !== '';
  return menuButton({
    label: 'Sort by',
    value: searching ? 'Relevance' : (current?.label ?? 'Last modified (desc)'),
    // Search results arrive ranked. Sorting them would discard the ranking, so
    // the control says so by being unavailable rather than by being ignored.
    disabled: searching,
    items: options.map((option) => ({
      id: option.id,
      label: option.label,
      checked: option.id === ctx.ui.sorting,
    })),
    onSelect: (id) => {
      ctx.patch({ sorting: id, page: 0 });
    },
  });
}

function filterRow(ctx: DashboardContext): HTMLElement | null {
  const controls = [
    clearFilters(ctx),
    ...ctx.state.contents.filters.map((dimension) => filterMenu(dimension, ctx)),
    groupingMenu(ctx),
    sortingMenu(ctx),
  ].filter((node): node is HTMLElement => node !== null);
  return controls.length === 0 ? null : el('div', { class: 'z-filterbar' }, controls);
}

// ---------------------------------------------------------------------------
// Row 5 — pagination
// ---------------------------------------------------------------------------

function paginationRow(ctx: DashboardContext): HTMLElement | null {
  const processed = processPages(ctx);
  if (!processed.paginated || processed.lastPage <= 0) {
    return null;
  }
  const page = Math.min(Math.max(0, ctx.ui.page), processed.lastPage);
  const from = page * processed.pageSize + 1;
  const to = Math.min(processed.total, from + processed.pageSize - 1);
  return el(
    'div',
    { class: 'z-paginationbar' },
    el(
      'p',
      { class: 'z-pagination__status' },
      `Showing ${from} to ${to} of ${processed.total} results`,
    ),
    pagination({
      page,
      lastPage: processed.lastPage,
      onGo: (next) => {
        ctx.patch({ page: next });
      },
    }),
  );
}

// ---------------------------------------------------------------------------
// Row 6 — the bulk actions bar
// ---------------------------------------------------------------------------

function actionItem(options: {
  label: string;
  glyph: string;
  disabled: boolean;
  danger?: boolean;
  onClick(): void;
}): HTMLElement {
  return el(
    'button',
    {
      class: options.danger === true
        ? 'z-actionsbar__item z-actionsbar__item--danger'
        : 'z-actionsbar__item',
      type: 'button',
      disabled: options.disabled,
      title: options.label,
      onclick: options.onClick,
    },
    icon(options.glyph),
    options.label,
  );
}

function actionsRow(ctx: DashboardContext): HTMLElement {
  const selection = ctx.ui.selection;
  const one = selection.length === 1 ? selection[0] : undefined;
  const processed = processPages(ctx);
  const onPage = processed.paged.map((page) => page.filePath);
  const allSelected = onPage.length > 0 && onPage.every((file) => selection.includes(file));

  const left = el(
    'div',
    { class: 'z-actionsbar__group' },
    actionItem({
      label: 'View',
      glyph: 'eye',
      disabled: one === undefined,
      onClick: () => {
        if (one !== undefined) {
          ctx.msg.command('openFile', one);
        }
      },
    }),
    actionItem({
      label: 'Rename',
      glyph: 'edit',
      disabled: one === undefined,
      onClick: () => {
        if (one !== undefined) {
          ctx.msg.command('renameFile', { path: one });
          ctx.clearSelection();
        }
      },
    }),
    actionItem({
      label: 'Delete',
      glyph: 'trash',
      danger: true,
      disabled: selection.length === 0,
      onClick: () => {
        const dialog = alert({
          title: 'Delete selected files',
          description: `Are you sure you want to delete the ${selection.length} selected file(s)?`,
          okLabel: 'Delete',
          cancelLabel: 'Cancel',
          danger: true,
          onOk: () => {
            ctx.msg.command('deleteFile', { paths: selection });
            ctx.clearSelection();
          },
        });
        document.body.appendChild(dialog.el);
      },
    }),
  );

  const right = el(
    'div',
    { class: 'z-toolbar__group' },
    selection.length === 0
      ? null
      : el(
          'button',
          {
            class: 'z-actionsbar__item z-actionsbar__count',
            type: 'button',
            title: 'Clear the selection',
            onclick: () => {
              ctx.clearSelection();
            },
          },
          `${selection.length} selected`,
          icon('close'),
        ),
    el(
      'button',
      {
        class: 'z-actionsbar__item',
        type: 'button',
        disabled: allSelected || onPage.length === 0,
        title: 'Select everything on this page',
        onclick: () => {
          ctx.patch({ selection: [...new Set([...selection, ...onPage])] });
        },
      },
      icon('check-all'),
      'Select all',
    ),
  );

  return el(
    'div',
    { class: 'z-actionsbar', attrs: { 'aria-label': 'Item actions' } },
    left,
    right,
  );
}

// ---------------------------------------------------------------------------
// The header
// ---------------------------------------------------------------------------

/** Render the chrome for the current route into `host`. */
export function renderHeader(host: HTMLElement, ctx: DashboardContext): void {
  host.appendChild(tabBar(ctx));
  const route = ctx.state.tabs.some((tab) => tab.id === ctx.ui.route) ? ctx.ui.route : 'contents';
  if (route !== 'contents') {
    // Whatever the route registered, or nothing. A route with no filters still
    // gets a bare tab bar, which is what every route but Contents had.
    const own = ROUTE_TOOLBARS.get(route)?.(ctx) ?? null;
    if (own !== null) {
      host.appendChild(own);
    }
    return;
  }
  host.appendChild(toolbarRow(ctx));
  host.appendChild(navigationRow(ctx));
  const filters = filterRow(ctx);
  if (filters !== null) {
    host.appendChild(filters);
  }
  // Structure view browses folders rather than paging through a list, and a
  // page boundary drawn through the middle of a group means nothing.
  const pager = ctx.ui.view === 'structure' ? null : paginationRow(ctx);
  if (pager !== null) {
    host.appendChild(pager);
  }
  host.appendChild(actionsRow(ctx));
}
