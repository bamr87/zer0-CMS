/**
 * Structure view — the folder-tree browser.
 *
 * The same pages the grid and the list draw, arranged the way they sit on
 * disk: one node per directory that contains content, expandable, with the
 * files underneath. Front Matter's version had a Home/Back/breadcrumb toolbar
 * above a disclosure tree, and both are here — the toolbar scopes the tree to
 * a subtree, the tree expands within it.
 *
 * Two implementation notes worth knowing before editing this file.
 *
 * **Indentation is content, not style.** A VS Code webview under
 * `style-src <cspSource> 'nonce-…'` blocks inline `style` attributes — a
 * nonce cannot apply to an attribute — so `style="padding-left: 40px"` would
 * silently do nothing. Rather than widen the CSP for a tree, depth is drawn
 * with a `z-tree__indent` span of non-breaking spaces. If a future stylesheet
 * gives that class a width, it takes over cleanly and this stays correct.
 *
 * **Creating content names a folder, not a path to write.** The button posts
 * `createContentInFolder` with the workspace-relative directory; the host
 * resolves it, picks the content type, applies the prefix chain and decides
 * the filename. The webview has named a place, not composed a write.
 */

import { el, icon, srOnly } from '../shared/dom';
import type { PageEntry } from '../shared/protocol';
import { dateLabel, itemMenu, selectionBox, statusBadge } from './contents';
import type { DashboardContext } from './main';

/** Files that sit directly in the workspace root get their own heading. */
const ROOT_LABEL = 'Root files';

/** One level of nesting, as non-breaking spaces. */
const INDENT_UNIT = '\u00a0\u00a0\u00a0';

interface FolderNode {
  name: string;
  /** Workspace-relative POSIX directory path; `''` at the root. */
  relPath: string;
  children: Map<string, FolderNode>;
  pages: PageEntry[];
}

function newNode(name: string, relPath: string): FolderNode {
  return { name, relPath, children: new Map(), pages: [] };
}

function dirOf(relPath: string): string {
  const cut = relPath.lastIndexOf('/');
  return cut === -1 ? '' : relPath.slice(0, cut);
}

/** Every file under a node, including its descendants. */
function countPages(node: FolderNode): number {
  let total = node.pages.length;
  for (const child of node.children.values()) {
    total += countPages(child);
  }
  return total;
}

/** Build the directory tree the pages imply. Directories with no content do
 *  not appear: this is a map of the content, not of the repository. */
function buildTree(pages: readonly PageEntry[]): FolderNode {
  const root = newNode(ROOT_LABEL, '');
  for (const page of pages) {
    const dir = dirOf(page.relPath);
    if (dir === '') {
      root.pages.push(page);
      continue;
    }
    let node = root;
    let walked = '';
    for (const segment of dir.split('/')) {
      if (segment === '') {
        continue;
      }
      walked = walked === '' ? segment : `${walked}/${segment}`;
      let child = node.children.get(segment);
      if (child === undefined) {
        child = newNode(segment, walked);
        node.children.set(segment, child);
      }
      node = child;
    }
    node.pages.push(page);
  }
  return root;
}

/** Descend to the node the toolbar has scoped to, or the root. */
function nodeAt(root: FolderNode, relPath: string | null): FolderNode | undefined {
  if (relPath === null || relPath === '') {
    return root;
  }
  let node: FolderNode | undefined = root;
  for (const segment of relPath.split('/')) {
    node = node?.children.get(segment);
    if (node === undefined) {
      return undefined;
    }
  }
  return node;
}

function indent(depth: number): HTMLElement | null {
  return depth === 0
    ? null
    : el('span', { class: 'z-tree__indent' }, INDENT_UNIT.repeat(depth));
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

function fileRow(page: PageEntry, ctx: DashboardContext, depth: number): HTMLElement {
  const open = (): void => {
    ctx.msg.command('openFile', page.filePath);
  };
  const selected = ctx.ui.selection.includes(page.filePath);
  return el(
    'li',
    {},
    el(
      'div',
      { class: selected ? 'z-tree__node is-selected' : 'z-tree__node' },
      indent(depth),
      selectionBox(page, ctx),
      icon('markdown'),
      el(
        'button',
        { class: 'z-card__title', type: 'button', title: `Open: ${page.title}`, onclick: open },
        page.title === '' ? page.relPath : page.title,
      ),
      el('span', { class: 'z-date' }, dateLabel(page)),
      statusBadge(page, ctx),
      itemMenu(page, ctx),
    ),
  );
}

function folderRow(node: FolderNode, ctx: DashboardContext, depth: number, open: boolean): HTMLElement {
  const total = countPages(node);
  return el(
    'div',
    { class: open ? 'z-tree__node is-open' : 'z-tree__node' },
    indent(depth),
    el(
      'button',
      {
        class: 'z-icon-btn',
        type: 'button',
        title: open ? `Collapse ${node.name}` : `Expand ${node.name}`,
        onclick: () => {
          ctx.patch({ expanded: { ...ctx.ui.expanded, [node.relPath]: !open } });
        },
      },
      icon('chevron-right', 'z-tree__chevron'),
      srOnly(open ? `Collapse ${node.name}` : `Expand ${node.name}`),
    ),
    icon(open ? 'folder-opened' : 'folder'),
    el(
      'button',
      {
        class: 'z-card__title',
        type: 'button',
        title: `Browse ${node.relPath}`,
        onclick: () => {
          ctx.patch({ folder: node.relPath });
        },
      },
      node.name,
    ),
    el('span', { class: 'z-tree__count' }, `(${total} ${total === 1 ? 'file' : 'files'})`),
  );
}

/**
 * A folder and everything under it. Depth ≤ 1 is open unless the user has said
 * otherwise, which is Front Matter's `defaultOpen` rule.
 */
function branch(node: FolderNode, ctx: DashboardContext, depth: number): HTMLElement[] {
  const stored = ctx.ui.expanded[node.relPath];
  const open = stored === undefined ? depth <= 1 : stored;
  const rows: HTMLElement[] = [el('li', {}, folderRow(node, ctx, depth, open))];
  if (!open) {
    return rows;
  }
  for (const child of [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name))) {
    rows.push(...branch(child, ctx, depth + 1));
  }
  for (const page of [...node.pages].sort((a, b) => a.relPath.localeCompare(b.relPath))) {
    rows.push(fileRow(page, ctx, depth + 1));
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Toolbar
// ---------------------------------------------------------------------------

function toolbar(ctx: DashboardContext, scope: string | null): HTMLElement {
  const parent = scope === null ? null : dirOf(scope);
  const label = scope === null ? 'Create content' : 'Create content here';

  return el(
    'div',
    { class: 'z-tree__toolbar' },
    scope === null
      ? null
      : [
          el(
            'button',
            {
              class: 'z-icon-btn',
              type: 'button',
              title: 'Home',
              onclick: () => {
                ctx.patch({ folder: null });
              },
            },
            icon('home'),
            srOnly('Home'),
          ),
          el(
            'button',
            {
              class: 'z-btn z-btn--secondary',
              type: 'button',
              title: 'Up one folder',
              onclick: () => {
                ctx.patch({ folder: parent === '' ? null : parent });
              },
            },
            icon('arrow-left'),
            'Back',
          ),
          el('span', { class: 'z-tree__crumbs' }, `/ ${scope.split('/').join(' / ')}`),
        ],
    el(
      'button',
      {
        class: 'z-btn',
        type: 'button',
        disabled: !ctx.state.initialized,
        title: scope === null ? label : `${label} in ${scope}`,
        onclick: () => {
          if (scope === null) {
            ctx.msg.command('createContent');
          } else {
            ctx.msg.command('createContentInFolder', scope);
          }
        },
      },
      label,
    ),
    scope === null ? null : el('span', { class: 'z-tree__count' }, `in ${scope}`),
  );
}

// ---------------------------------------------------------------------------
// The view
// ---------------------------------------------------------------------------

/** Render the structure browser for `pages` — the already-filtered set. */
export function renderStructure(
  host: HTMLElement,
  ctx: DashboardContext,
  pages: readonly PageEntry[],
): void {
  const root = buildTree(pages);
  const scoped = nodeAt(root, ctx.ui.folder);
  // A folder that disappeared — deleted, renamed, filtered out — must not
  // leave the view stranded on nothing.
  const scope = scoped === undefined ? null : ctx.ui.folder;
  const node = scoped ?? root;

  host.appendChild(toolbar(ctx, scope));

  const rows: HTMLElement[] = [];
  if (node === root) {
    for (const child of [...root.children.values()].sort((a, b) => a.name.localeCompare(b.name))) {
      rows.push(...branch(child, ctx, 0));
    }
    if (root.pages.length > 0) {
      rows.push(el('li', {}, el('h3', { class: 'z-lane__title' }, ROOT_LABEL)));
      for (const page of [...root.pages].sort((a, b) => a.relPath.localeCompare(b.relPath))) {
        rows.push(fileRow(page, ctx, 0));
      }
    }
  } else {
    rows.push(...branch(node, ctx, 0));
  }

  if (rows.length === 0) {
    host.appendChild(
      el(
        'div',
        { class: 'z-emptystate' },
        icon('folder'),
        el('p', {}, 'No Markdown to show'),
      ),
    );
    return;
  }
  host.appendChild(el('ul', { class: 'z-tree' }, rows));
}
