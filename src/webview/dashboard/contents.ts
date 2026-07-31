/**
 * The Contents route: the page pipeline, and the three ways of drawing it.
 *
 * ### The pipeline
 *
 * `processPages()` is the whole data path, and it is a straight line:
 *
 * ```
 * pages ──▶ draft-state tab ──▶ filter dimensions ──▶ sort ──▶ group ──▶ page
 *   └── replaced wholesale by the host's search hits when a query is running
 * ```
 *
 * Two rules in there are load-bearing rather than decorative. **Search skips
 * sorting**, because the host returns hits in relevance order and re-sorting
 * them by filename would throw that away — which is also why the sort control
 * is disabled while a query is active. And **grouping disables paging**,
 * because a page boundary drawn through the middle of a year is a page
 * boundary that means nothing.
 *
 * `header.ts` calls the same function to draw the pagination bar, so the strip
 * that says "page 3 of 7" and the list that shows page 3 can never disagree
 * about what a page is.
 *
 * ### Grid, list, structure
 *
 * The three view types are Front Matter's, reproduced: a responsive card grid
 * at 1/2/3/4/5 columns (0/640/768/1024/1536px, in `media/dashboard.css`), a
 * twelve-column list whose Title spans eight and whose Date and Status span
 * two each, and the folder-tree browser that lives in `structure.ts`.
 *
 * ### Card images are remote-only, on purpose
 *
 * A card renders `<img>` only for an `https:` or `data:` reference. The
 * webview's `localResourceRoots` are `media/` and `dist/` and nothing else
 * (PLAN §4.4), so a workspace image has no loadable URI here — and widening
 * the roots to the whole repository to put a thumbnail on a card is not a
 * trade worth making. Everything else gets the markdown glyph.
 */

import { alert, menuButton } from '../shared/components';
import { el, icon, srOnly } from '../shared/dom';
import type { PageEntry } from '../shared/protocol';
import type { DashboardContext } from './main';
import { renderStructure } from './structure';

/** A grouping bucket: the pages under one heading. */
export interface PageGroup {
  id: string;
  label: string;
  pages: PageEntry[];
}

export interface ProcessedPages {
  /** After the draft-state tab, the filter dimensions and the search. */
  matched: PageEntry[];
  /** `matched`, sorted — unless a search is running, which orders by relevance. */
  ordered: PageEntry[];
  /** Buckets when grouping is on; `null` when it is not. */
  groups: PageGroup[] | null;
  /** The slice on screen. Equal to `ordered` when paging does not apply. */
  paged: PageEntry[];
  total: number;
  pageSize: number;
  /** Zero-based index of the last page. `0` when everything fits on one. */
  lastPage: number;
  /** Paging is off while grouping, in Structure view, and at `pageSize: 0`. */
  paginated: boolean;
}

// ---------------------------------------------------------------------------
// Classification
// ---------------------------------------------------------------------------

/**
 * A page's draft state, as the navigation tabs and the status badge see it.
 *
 * `PageEntry.draft` already has the configured `invert` applied to booleans
 * and keeps a `choice` field's raw status word, so this is the whole rule.
 * `src/dashboard/dashboardPanel.ts` holds an identical copy for the tab counts
 * — the webview cannot import from the host — and the two must agree or a tab
 * will promise a count it does not deliver.
 */
export function draftStateOf(page: PageEntry, now: number): string {
  if (typeof page.draft === 'string') {
    return page.draft;
  }
  if (page.draft) {
    return 'draft';
  }
  return page.published !== null && page.published > now ? 'scheduled' : 'published';
}

/** The year a page belongs to, from its publish date or its written date. */
export function yearOf(page: PageEntry): number | null {
  if (page.published !== null) {
    return new Date(page.published).getUTCFullYear();
  }
  const match = /^(\d{4})/.exec((page.date ?? '').trim());
  return match?.[1] === undefined ? null : Number(match[1]);
}

/** The basename of a page's workspace-relative path. */
function fileName(page: PageEntry): string {
  const cut = page.relPath.lastIndexOf('/');
  return cut === -1 ? page.relPath : page.relPath.slice(cut + 1);
}

/**
 * `yyyy-MM-dd`, from the publish timestamp when there is one and from the
 * written date otherwise. An unparseable date is shown verbatim rather than
 * replaced with `Invalid Date` — the raw string is at least a fact about the
 * file.
 */
export function dateLabel(page: PageEntry): string {
  if (page.published !== null) {
    return new Date(page.published).toISOString().slice(0, 10);
  }
  const raw = (page.date ?? '').trim();
  if (raw === '') {
    return '';
  }
  const iso = /^(\d{4}-\d{2}-\d{2})/.exec(raw);
  if (iso?.[1] !== undefined) {
    return iso[1];
  }
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? raw : new Date(parsed).toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Filtering, sorting, grouping, paging
// ---------------------------------------------------------------------------

function values(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.filter((item): item is string => typeof item === 'string');
  }
  return typeof raw === 'string' && raw !== '' ? [raw] : [];
}

function matchesFilters(page: PageEntry, ctx: DashboardContext): boolean {
  for (const [id, wanted] of Object.entries(ctx.ui.filters)) {
    if (wanted === '') {
      continue;
    }
    if (id === 'folder') {
      const folder = ctx.state.contents.folders.find((entry) => entry.title === wanted);
      if (folder === undefined || page.folder !== folder.path) {
        return false;
      }
    } else if (id === 'tags') {
      if (!page.tags.includes(wanted)) {
        return false;
      }
    } else if (id === 'categories') {
      if (!page.categories.includes(wanted)) {
        return false;
      }
    } else if (id.startsWith('taxonomy:')) {
      if (!values(page.data[id.slice('taxonomy:'.length)]).includes(wanted)) {
        return false;
      }
    }
  }
  return true;
}

/** Natural ordering for a front-matter value a custom sort names. */
function compareUnknown(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') {
    return a - b;
  }
  return String(a ?? '').localeCompare(String(b ?? ''));
}

/**
 * Sort by one of the six ids, or by a user entry.
 *
 * A custom id follows Front Matter's `<field>-<asc|desc>` convention, which is
 * what lets the webview honour an entry it has never seen: the suffix is the
 * direction and the stem is the front-matter key.
 */
export function sortPages(pages: readonly PageEntry[], sorting: string): PageEntry[] {
  const out = [...pages];
  switch (sorting) {
    case 'LastModifiedAsc':
      return out.sort((a, b) => a.modified - b.modified);
    case 'LastModifiedDesc':
      return out.sort((a, b) => b.modified - a.modified);
    case 'FileNameAsc':
      return out.sort((a, b) => fileName(a).localeCompare(fileName(b)));
    case 'FileNameDesc':
      return out.sort((a, b) => fileName(b).localeCompare(fileName(a)));
    case 'PublishedAsc':
      return out.sort((a, b) => (a.published ?? 0) - (b.published ?? 0));
    case 'PublishedDesc':
      return out.sort((a, b) => (b.published ?? 0) - (a.published ?? 0));
    default:
      break;
  }
  const cut = sorting.lastIndexOf('-');
  if (cut > 0) {
    const field = sorting.slice(0, cut);
    const direction = sorting.slice(cut + 1) === 'desc' ? -1 : 1;
    return out.sort((a, b) => direction * compareUnknown(a.data[field], b.data[field]));
  }
  // An id from a configuration this build does not understand. Newest first is
  // the least surprising answer, and it is also the shipped default.
  return out.sort((a, b) => b.modified - a.modified);
}

function groupPages(pages: readonly PageEntry[], ctx: DashboardContext): PageGroup[] | null {
  const grouping = ctx.ui.grouping;
  if (grouping === '' || grouping === 'none') {
    return null;
  }
  const now = Date.now();

  if (grouping === 'year') {
    const buckets = new Map<number, PageEntry[]>();
    for (const page of pages) {
      const year = yearOf(page);
      if (year === null) {
        continue;
      }
      const bucket = buckets.get(year);
      if (bucket === undefined) {
        buckets.set(year, [page]);
      } else {
        bucket.push(page);
      }
    }
    return [...buckets.entries()]
      .sort((a, b) => b[0] - a[0])
      .map(([year, entries]) => ({
        id: String(year),
        label: `Year: ${year} (${entries.length})`,
        pages: entries,
      }));
  }

  if (grouping === 'draft') {
    const order: Array<[string, string]> = [
      ['scheduled', 'Scheduled'],
      ['published', 'Published'],
      ['draft', 'Draft'],
    ];
    const buckets = new Map<string, PageEntry[]>();
    for (const page of pages) {
      const state = draftStateOf(page, now);
      const bucket = buckets.get(state);
      if (bucket === undefined) {
        buckets.set(state, [page]);
      } else {
        bucket.push(page);
      }
    }
    const known = order
      .filter(([id]) => (buckets.get(id)?.length ?? 0) > 0)
      .map(([id, label]) => ({
        id,
        label: `${label} (${buckets.get(id)?.length ?? 0})`,
        pages: buckets.get(id) ?? [],
      }));
    // A `choice` draft field produces status words nobody enumerated; they
    // still deserve a heading rather than silently vanishing.
    const extra = [...buckets.keys()]
      .filter((id) => !order.some(([known_]) => known_ === id))
      .sort((a, b) => a.localeCompare(b))
      .map((id) => ({
        id,
        label: `${id} (${buckets.get(id)?.length ?? 0})`,
        pages: buckets.get(id) ?? [],
      }));
    return [...known, ...extra];
  }

  if (grouping.startsWith('field:')) {
    const field = grouping.slice('field:'.length);
    const heading =
      ctx.state.contents.groupOptions.find((option) => option.id === grouping)?.label ?? field;
    const buckets = new Map<string, PageEntry[]>();
    for (const page of pages) {
      for (const value of values(page.data[field])) {
        const bucket = buckets.get(value);
        if (bucket === undefined) {
          buckets.set(value, [page]);
        } else {
          bucket.push(page);
        }
      }
    }
    return [...buckets.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([value, entries]) => ({
        id: value,
        label: `${heading}: ${value} (${entries.length})`,
        pages: entries,
      }));
  }
  return null;
}

/**
 * One result per render.
 *
 * `renderContents`, the pagination bar and the actions bar all need the same
 * answer, and a context object is built fresh for each render — so caching
 * against it is exact rather than approximate, and a stale entry is
 * unreachable by construction.
 */
const memo = new WeakMap<DashboardContext, ProcessedPages>();

/** The one data path, shared by the list, the pagination bar and the actions bar. */
export function processPages(ctx: DashboardContext): ProcessedPages {
  const cached = memo.get(ctx);
  if (cached !== undefined) {
    return cached;
  }
  const computed = computePages(ctx);
  memo.set(ctx, computed);
  return computed;
}

function computePages(ctx: DashboardContext): ProcessedPages {
  const { ui, state } = ctx;
  const now = Date.now();
  const base = ui.results ?? state.contents.pages;

  const matched = base.filter((page) => {
    if (ui.tab !== 'all' && draftStateOf(page, now) !== ui.tab) {
      return false;
    }
    return matchesFilters(page, ctx);
  });

  // Search hits arrive ranked; re-sorting them discards the ranking, which is
  // why the sort control is disabled while a query is active.
  const ordered = ui.results === null ? sortPages(matched, ui.sorting) : matched;
  const groups = groupPages(ordered, ctx);

  const pageSize = state.contents.pageSize;
  const paginated = pageSize > 0 && groups === null && ui.view !== 'structure';
  const lastPage = paginated ? Math.max(0, Math.ceil(ordered.length / pageSize) - 1) : 0;
  const page = Math.min(Math.max(0, ui.page), lastPage);
  const paged = paginated ? ordered.slice(page * pageSize, page * pageSize + pageSize) : ordered;

  return {
    matched,
    ordered,
    groups,
    paged,
    total: ordered.length,
    pageSize,
    lastPage,
    paginated,
  };
}

// ---------------------------------------------------------------------------
// Item chrome
// ---------------------------------------------------------------------------

/** The uppercase badge. Hidden entirely when the workspace marks no drafts. */
export function statusBadge(page: PageEntry, ctx: DashboardContext): HTMLElement | null {
  if (ctx.state.contents.tabs.length <= 1) {
    return null;
  }
  if (typeof page.draft === 'string') {
    return page.draft.trim() === ''
      ? null
      : el('span', { class: 'z-status' }, page.draft);
  }
  const state = draftStateOf(page, Date.now());
  if (state === 'draft') {
    return el('span', { class: 'z-status z-status--draft' }, 'Draft');
  }
  if (state === 'scheduled') {
    return el('span', { class: 'z-status z-status--scheduled' }, 'Scheduled');
  }
  return el('span', { class: 'z-status' }, 'Published');
}

/** The hover-revealed tick box in the corner of a card, or column 1 of a row. */
export function selectionBox(page: PageEntry, ctx: DashboardContext): HTMLElement {
  const box = el('input', {
    type: 'checkbox',
    checked: ctx.ui.selection.includes(page.filePath),
    title: `Select ${page.title}`,
    onchange: () => {
      ctx.toggleSelection(page.filePath);
    },
  });
  box.addEventListener('click', (event) => {
    event.stopPropagation();
  });
  return el('label', { class: 'z-card__select' }, box, srOnly(`Select ${page.title}`));
}

/** Ask before deleting, then post the intent. The host owns the deletion. */
export function confirmDelete(page: PageEntry, ctx: DashboardContext): void {
  const dialog = alert({
    title: `Delete: ${page.title}`,
    description: `Are you sure you want to delete the "${page.title}" content?`,
    okLabel: 'Delete',
    cancelLabel: 'Cancel',
    danger: true,
    onOk: () => {
      ctx.msg.command('deleteFile', { path: page.filePath });
    },
  });
  document.body.appendChild(dialog.el);
}

/** The per-item ellipsis menu: View, Rename, Reveal, Delete. */
export function itemMenu(page: PageEntry, ctx: DashboardContext): HTMLElement {
  return menuButton({
    triggerIcon: 'ellipsis',
    triggerTitle: `Actions for ${page.title}`,
    align: 'end',
    items: [
      { id: 'view', label: 'View', icon: 'eye' },
      { id: 'rename', label: 'Rename', icon: 'edit' },
      { id: 'reveal', label: 'Reveal in file explorer', icon: 'folder-opened' },
      { id: 'delete', label: 'Delete', icon: 'trash', danger: true, separatorBefore: true },
    ],
    onSelect: (id) => {
      if (id === 'view') {
        ctx.msg.command('openFile', page.filePath);
      } else if (id === 'rename') {
        ctx.msg.command('renameFile', { path: page.filePath });
      } else if (id === 'reveal') {
        ctx.msg.command('revealFile', { path: page.filePath });
      } else if (id === 'delete') {
        confirmDelete(page, ctx);
      }
    },
  });
}

function iconAction(
  label: string,
  glyph: string,
  danger: boolean,
  onClick: () => void,
): HTMLElement {
  return el(
    'button',
    {
      class: danger ? 'z-icon-btn z-icon-btn--danger' : 'z-icon-btn',
      type: 'button',
      title: label,
      onclick: (event: Event) => {
        event.stopPropagation();
        onClick();
      },
    },
    icon(glyph),
    srOnly(label),
  );
}

/** Only a remote reference is loadable under the CSP; see the file header. */
function remoteImage(reference: string): string | null {
  const value = reference.trim();
  return value.startsWith('https://') || value.startsWith('data:') ? value : null;
}

// ---------------------------------------------------------------------------
// Cards and rows
// ---------------------------------------------------------------------------

function card(page: PageEntry, ctx: DashboardContext): HTMLElement {
  const fields = ctx.state.contents.cardFields;
  const badge = fields.state === false ? null : statusBadge(page, ctx);
  const date = fields.date === false ? '' : dateLabel(page);
  const image = remoteImage(page.previewImage);
  const open = (): void => {
    ctx.msg.command('openFile', page.filePath);
  };

  const chips = [...page.tags, ...page.categories].slice(0, 8);

  const body = el(
    'div',
    { class: 'z-card__body' },
    badge !== null || date !== ''
      ? el('div', { class: 'z-card__meta' }, badge, date === '' ? null : el('span', { class: 'z-date' }, date))
      : null,
    el('div', { class: 'z-card__actions' }, itemMenu(page, ctx)),
    el(
      'button',
      { class: 'z-card__title', type: 'button', title: `Open: ${page.title}`, onclick: open },
      page.title === '' ? fileName(page) : page.title,
    ),
    page.description === ''
      ? null
      : el('button', { class: 'z-card__description', type: 'button', onclick: open }, page.description),
    chips.length === 0
      ? null
      : el(
          'div',
          { class: 'z-chips' },
          chips.map((value) =>
            el(
              'button',
              {
                class: 'z-chip',
                type: 'button',
                title: `Filter by ${value}`,
                onclick: () => {
                  ctx.setFilter(page.tags.includes(value) ? 'tags' : 'categories', value);
                },
              },
              `#${value}`,
            ),
          ),
        ),
  );

  const article = el(
    'div',
    {
      class: ctx.ui.selection.includes(page.filePath) ? 'z-card is-selected' : 'z-card',
    },
    el(
      'button',
      {
        class: 'z-card__image',
        type: 'button',
        title: page.title === '' ? 'Open' : `Open: ${page.title}`,
        onclick: open,
      },
      image === null
        ? el('span', { class: 'z-card__image__fallback' }, icon('markdown'))
        : el('img', { src: image, alt: '', loading: 'lazy' }),
    ),
    selectionBox(page, ctx),
    body,
    el(
      'div',
      { class: 'z-card__footer' },
      iconAction('View', 'eye', false, open),
      iconAction('Delete', 'trash', true, () => {
        confirmDelete(page, ctx);
      }),
    ),
  );
  return el('li', {}, article);
}

function listHead(): HTMLElement {
  return el(
    'li',
    { class: 'z-list__head' },
    el('div', { class: 'z-col-title' }, 'Title'),
    el('div', { class: 'z-col-date' }, 'Date'),
    el('div', { class: 'z-col-status' }, 'Status'),
  );
}

function listRow(page: PageEntry, ctx: DashboardContext): HTMLElement {
  const open = (): void => {
    ctx.msg.command('openFile', page.filePath);
  };
  const row = el(
    'div',
    { class: ctx.ui.selection.includes(page.filePath) ? 'z-list__row is-selected' : 'z-list__row' },
    el(
      'div',
      { class: 'z-col-title' },
      selectionBox(page, ctx),
      el(
        'button',
        { class: 'z-card__title', type: 'button', title: `Open: ${page.title}`, onclick: open },
        page.title === '' ? fileName(page) : page.title,
      ),
      itemMenu(page, ctx),
    ),
    el('div', { class: 'z-col-date z-date' }, dateLabel(page)),
    el('div', { class: 'z-col-status' }, statusBadge(page, ctx)),
  );
  return el('li', {}, row);
}

function listOf(pages: readonly PageEntry[], ctx: DashboardContext): HTMLElement {
  if (ctx.ui.view === 'list') {
    return el(
      'ul',
      { class: 'z-list' },
      listHead(),
      pages.map((page) => listRow(page, ctx)),
    );
  }
  return el(
    'ul',
    { class: 'z-cards' },
    pages.map((page) => card(page, ctx)),
  );
}

// ---------------------------------------------------------------------------
// Empty states
// ---------------------------------------------------------------------------

/**
 * Two different problems need two different sentences.
 *
 * "No markdown found" is a search or a filter that matched nothing, and the
 * fix is to change it. "No content folder registered" is a project that has
 * never been pointed at its own content, and the fix is a different action
 * entirely — so it gets the button as well as the words.
 */
function emptyState(ctx: DashboardContext): HTMLElement {
  const unregistered = ctx.state.contents.folders.length === 0;
  return el(
    'div',
    { class: 'z-emptystate' },
    icon(unregistered ? 'folder-opened' : 'book'),
    el(
      'p',
      {},
      unregistered
        ? 'Register a content folder so zer0-CMS can find the markdown in this project.'
        : 'No Markdown to show',
    ),
    unregistered
      ? el(
          'button',
          {
            class: 'z-btn',
            type: 'button',
            onclick: () => {
              ctx.msg.command('registerFolder');
            },
          },
          'Register a content folder',
        )
      : ctx.ui.search !== '' || Object.keys(ctx.ui.filters).length > 0
        ? el(
            'button',
            {
              class: 'z-btn z-btn--secondary',
              type: 'button',
              onclick: () => {
                ctx.patch({ search: '', results: null, filters: {}, tab: 'all', page: 0 });
              },
            },
            'Clear the search and filters',
          )
        : null,
  );
}

// ---------------------------------------------------------------------------
// The route
// ---------------------------------------------------------------------------

/** Render the Contents route into `host`. */
export function renderContents(host: HTMLElement, ctx: DashboardContext): void {
  const processed = processPages(ctx);

  if (ctx.ui.view === 'structure') {
    renderStructure(host, ctx, processed.matched);
    return;
  }

  if (processed.total === 0) {
    host.appendChild(emptyState(ctx));
    return;
  }

  if (processed.groups !== null) {
    for (const group of processed.groups) {
      host.appendChild(
        el(
          'section',
          { class: 'z-lane' },
          el('h2', { class: 'z-lane__title' }, icon('chevron-down'), group.label),
          listOf(group.pages, ctx),
        ),
      );
    }
    return;
  }

  host.appendChild(listOf(processed.paged, ctx));
}
