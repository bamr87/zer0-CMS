/**
 * The webview bundles, rendered.
 *
 * Three claims the documentation makes and nothing has ever checked:
 *
 *  - **Every route renders.** All eleven `DASHBOARD_ROUTES`, six with a real
 *    renderer and five with the `notAvailable` placeholder that stands in until
 *    the PR that fills them. A route that throws on an empty snapshot is a
 *    blank tab in somebody's editor, and the failure looks exactly like a
 *    working build.
 *  - **The operator primitives keep their promises.** `unknown` does not render
 *    like `neutral`; a wide table scrolls inside its own box; a gated button is
 *    disabled and posts an intent and a target only (decision D5); a staged
 *    form is keyed, so two of them cannot share a half-typed value.
 *  - **`createFieldWidget` mounts and disposes without leaking.**
 *    `src/webview/README.md` has promised "there is a leak test that mounts and
 *    disposes 500 times" since the panel was written. This is that test.
 *
 * `./support/dom` is the **first** import on purpose: it installs the mini-DOM
 * and the stub `acquireVsCodeApi` as a module side effect, and a webview module
 * may reach for either while it is being evaluated. See that file's header for
 * what the shim does and does not model — no layout, no cascade, no selector
 * engine beyond compound simple selectors.
 */

import './support/dom';

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as path from 'node:path';

import {
  FakeEvent,
  find,
  findAll,
  mountPoint,
  persistentListenerCount,
  posted,
  resetDom,
  SVG_NS,
  type FakeElement,
} from './support/dom';

import { FIELD_TYPES } from '../core/shared/types';
import { renderContents } from '../webview/dashboard/contents';
import { render as renderCatering } from '../webview/dashboard/catering';
import { render as renderFleet } from '../webview/dashboard/fleet';
import { render as renderDrafts } from '../webview/dashboard/governance';
import { render as renderSettings } from '../webview/dashboard/settings';
import { render as renderWelcome } from '../webview/dashboard/welcome';
import { createFieldWidget } from '../webview/panel/fields/index';
import { dataTable, gatedButton, statusPill } from '../webview/shared/components';
import { el } from '../webview/shared/dom';
import { resetStagedForm, stagedForm } from '../webview/shared/form';
import { getMessenger } from '../webview/shared/messenger';
import {
  DASHBOARD_ROUTES,
  type DashboardRoute,
  type DashboardState,
  type Field,
  type FieldContext,
  type PanelState,
  type SettingItem,
} from '../webview/shared/protocol';
import { svgEl } from '../webview/shared/svg';
import type { DashboardContext, DashboardUi } from '../webview/dashboard/main';

// ---------------------------------------------------------------------------
// Fixtures — the emptiest honest snapshot the host could send
// ---------------------------------------------------------------------------

function emptyDashboardState(): DashboardState {
  return {
    kind: 'dashboard',
    initialized: true,
    showWelcome: false,
    developer: false,
    tabs: [],
    contents: {
      pages: [],
      folders: [],
      tabs: [],
      sortOptions: [],
      groupOptions: [],
      filters: [],
      pageSize: 16,
      defaultView: 'grid',
      defaultSorting: 'lastModified-desc',
      cardFields: {},
    },
    drafts: {
      enabled: true,
      drafts: [],
      counts: { pending: 0, approved: 0, published: 0, other: 0 },
      selected: null,
      review: null,
    },
    catering: null,
    fleet: null,
    settings: { general: [], folders: [], contentTypes: [] },
    welcome: { steps: [] },
    version: '0.0.0-test',
  };
}

function emptyUi(): DashboardUi {
  return {
    route: 'contents',
    view: 'grid',
    sorting: 'lastModified-desc',
    grouping: 'none',
    tab: 'all',
    filters: {},
    page: 0,
    search: '',
    results: null,
    searching: false,
    selection: [],
    folder: null,
    expanded: {},
  };
}

function dashboardContext(state: DashboardState): DashboardContext {
  return {
    state,
    ui: emptyUi(),
    msg: getMessenger(),
    revision: 0,
    patch: () => undefined,
    setFilter: () => undefined,
    toggleSelection: () => undefined,
    clearSelection: () => undefined,
    runSearch: () => undefined,
  };
}

function panelState(fields: Field[]): PanelState {
  return {
    kind: 'panel',
    initialized: true,
    developer: false,
    fileName: 'post.md',
    filePath: '/tmp/post.md',
    sections: [],
    contentTypeName: 'post',
    contentTypeHint: null,
    fields,
    metadata: {},
    fmError: null,
    violations: [],
    taxonomy: { tags: ['one'], categories: ['two'], custom: [], freeform: true },
    seo: null,
    governance: null,
    recent: [],
    settings: {
      autoUpdateModifiedDate: false,
      openOnSupportedFile: false,
      seoEnabled: false,
      agentEnabled: false,
    },
    dateFormat: 'yyyy-MM-dd',
    timezone: 'UTC',
  };
}

/** One field of every type, so the leak test covers all eighteen factories. */
function everyField(): Field[] {
  return FIELD_TYPES.map((type, index) => {
    const field: Field = { name: `f${index}`, type, title: `Field ${index}` };
    if (type === 'file') {
      field.fileExtensions = ['md'];
    }
    if (type === 'choice') {
      field.choices = ['a', 'b'];
    }
    return field;
  });
}

function fieldContext(field: Field, state: PanelState): FieldContext {
  return {
    field,
    parents: [],
    value: undefined,
    state,
    msg: getMessenger(),
    onChange: () => undefined,
  };
}

// ---------------------------------------------------------------------------
// The route table, including the placeholder for the five unfilled routes
// ---------------------------------------------------------------------------

type Renderer = (host: HTMLElement, ctx: DashboardContext) => void;

/**
 * The renderer `main.ts` uses for a route no package has filled yet.
 *
 * Compile-complete and unreachable in production — a route absent from
 * `state.tabs` degrades to Contents — but it has to exist, because
 * `Record<DashboardRoute, Renderer>` is not satisfiable without it, and
 * "unreachable" is a claim worth being able to watch fail.
 */
function notAvailable(route: DashboardRoute): Renderer {
  return (host) => {
    host.appendChild(
      el(
        'div',
        { class: 'z-emptystate' },
        el('p', {}, `The ${route} tab is not available in this build.`),
        el('p', { class: 'z-muted' }, 'The host does not offer this route yet.'),
      ),
    );
  };
}

/** The five routes that take a snapshot rather than the view-local context. */
function bySnapshot(render: (host: HTMLElement, state: DashboardState) => void): Renderer {
  return (host, ctx) => {
    render(host, ctx.state);
  };
}

const RENDERERS: Record<DashboardRoute, Renderer> = {
  sites: notAvailable('sites'),
  contents: renderContents,
  drafts: bySnapshot(renderDrafts),
  audit: notAvailable('audit'),
  catering: bySnapshot(renderCatering),
  fleet: bySnapshot(renderFleet),
  harness: notAvailable('harness'),
  workflows: notAvailable('workflows'),
  monitor: notAvailable('monitor'),
  settings: bySnapshot(renderSettings),
  welcome: bySnapshot(renderWelcome),
};

const BASE_CSS = path.resolve(__dirname, '..', '..', 'media', 'base.css');

function text(node: FakeElement): string {
  return node.textContent.trim();
}

/** A mount point typed the way the renderers ask for one. */
function host(): { node: FakeElement; el: HTMLElement } {
  const node = mountPoint();
  return { node, el: node as unknown as HTMLElement };
}

suite('webview', () => {
  setup(() => {
    resetDom();
    resetStagedForm();
  });

  test('every route renders an empty state without throwing', () => {
    const state = emptyDashboardState();
    const ctx = dashboardContext(state);
    assert.equal(Object.keys(RENDERERS).length, DASHBOARD_ROUTES.length);

    for (const route of DASHBOARD_ROUTES) {
      const mount = host();
      assert.doesNotThrow(() => {
        RENDERERS[route](mount.el, ctx);
      }, `route "${route}" threw on an empty snapshot`);
      assert.ok(
        text(mount.node) !== '',
        `route "${route}" rendered nothing — a blank tab is indistinguishable from a crash`,
      );
    }

    // An empty state has to say *why*, or it is indistinguishable from a
    // failure. Fleet off names the setting that turns it on...
    const fleet = host();
    renderFleet(fleet.el, state);
    assert.ok(find(fleet.node, '.z-emptystate') !== null);
    assert.match(text(fleet.node), /zer0Cms\.fleet\.enabled/);

    // ...`.cms/` absence is a normal state (D9), so it offers the way out...
    const catering = host();
    renderCatering(catering.el, state);
    const action = find(catering.node, '.z-emptystate button');
    assert.ok(action !== null, 'the catering empty state offers no action');
    assert.equal(text(action), 'Run CMS engine');

    // ...and the queue is empty rather than broken.
    const drafts = host();
    renderDrafts(drafts.el, state);
    assert.match(text(drafts.node), /The draft queue is empty\./);

    // The five routes later PRs fill say so, rather than rendering a blank tab.
    for (const route of ['sites', 'audit', 'harness', 'workflows', 'monitor'] as const) {
      const mount = host();
      RENDERERS[route](mount.el, ctx);
      assert.match(
        text(mount.node),
        new RegExp(`The ${route} tab is not available`),
        `the ${route} placeholder does not say the route is unfilled`,
      );
    }
  });

  test('statusPill renders `unknown` differently from `neutral`', () => {
    const neutral = statusPill({ variant: 'neutral', text: 'false' }) as unknown as FakeElement;
    const unknown = statusPill({ variant: 'unknown', text: 'unknown' }) as unknown as FakeElement;

    assert.ok(neutral.classList.contains('z-status--neutral'));
    assert.ok(unknown.classList.contains('z-status--unknown'));
    assert.notEqual(
      neutral.className,
      unknown.className,
      'a cell nobody has asked about must not render like a cell whose answer is "no"',
    );

    // And the stylesheet has to distinguish them, or the class is a promise the
    // CSS does not keep and the Fleet route's four honest states become three.
    const base = fs.readFileSync(BASE_CSS, 'utf8');
    const rule = /\.z-status--unknown \{([^}]*)\}/.exec(base);
    assert.ok(rule !== null, 'media/base.css has no .z-status--unknown rule');
    assert.match(rule[1] ?? '', /border:\s*1px dashed/);
    assert.match(rule[1] ?? '', /background:\s*transparent/);
  });

  test('dataTable scrolls in its own box and marks its numeric columns', () => {
    const node = dataTable({
      columns: ['Topic', { label: 'Posts', numeric: true }],
      rows: [
        ['governance', '3'],
        ['fleet', '11'],
      ],
    }) as unknown as FakeElement;

    // Wide content scrolls in its own box; the page body never goes sideways.
    assert.ok(node.classList.contains('z-table__scroll'));
    assert.ok(find(node, 'table.z-table') !== null);

    const headers = findAll(node, 'th');
    assert.equal(headers.length, 2);
    assert.ok(headers[0]?.classList.contains('z-table__num') === false);
    assert.ok(headers[1]?.classList.contains('z-table__num') === true);

    const cells = findAll(node, 'td');
    assert.equal(cells.length, 4);
    for (const index of [1, 3]) {
      assert.ok(
        cells[index]?.classList.contains('z-table__num'),
        'a numeric column must carry tabular figures so the eye can compare them',
      );
    }
    assert.match(fs.readFileSync(BASE_CSS, 'utf8'), /\.z-table__num \{[^}]*tabular-nums/);

    // An empty table says so rather than drawing a header over nothing.
    const empty = dataTable({ columns: ['A'], rows: [], empty: 'The manifest declares no lanes.' });
    assert.equal(text(empty as unknown as FakeElement), 'The manifest declares no lanes.');

    // Same namespace question, other module: an SVG built with `createElement`
    // is inert, which is the whole reason `svgEl` exists.
    const chart = svgEl('svg', { viewBox: '0 0 10 10' }) as unknown as FakeElement;
    assert.equal(chart.namespaceURI, SVG_NS);
    assert.equal(chart.getAttribute('viewBox'), '0 0 10 10');
  });

  test('gatedButton is a courtesy, and stagedForm is keyed by form id', () => {
    posted.splice(0, posted.length);

    const blocked = gatedButton({
      label: 'Dispatch',
      id: 'fleet.dispatchLane',
      args: { lane: 'content-factory' },
      blockers: [{ kind: 'dispatchDisabled', message: 'dispatch is disabled' }],
    }) as unknown as FakeElement;
    const disabledButton = find(blocked, 'button');
    assert.ok(disabledButton !== null);
    assert.equal(disabledButton.disabled, true);
    assert.match(text(blocked), /Dispatch disabled: dispatch is disabled\./);

    const open = gatedButton({
      label: 'Dispatch',
      id: 'fleet.dispatchLane',
      args: { lane: 'content-factory' },
      blockers: [],
    }) as unknown as FakeElement;
    assert.equal(open.disabled, false);
    open.click();
    assert.deepEqual(posted.at(-1), {
      type: 'command',
      id: 'fleet.dispatchLane',
      // An intent and a target. No value, no force, no resolved artifact (D5).
      args: { lane: 'content-factory' },
    });

    // Two forms, one setting key, no shared state — the bug the module-level
    // `pending` map guaranteed the moment a second form existed.
    const item: SettingItem = { key: 'cms.pageSize', label: 'Page size', kind: 'number', value: 16 };
    const left = stagedForm({ key: 'settings.general', items: [item], onSave: () => undefined });
    const right = stagedForm({ key: 'lane.scaffold', items: [item], onSave: () => undefined });

    const leftInput = find(left.el as unknown as FakeElement, 'input');
    assert.ok(leftInput !== null);
    leftInput.value = '24';
    leftInput.dispatchEvent(new FakeEvent('input', { bubbles: true }));

    assert.deepEqual(left.changes(), [{ key: 'cms.pageSize', value: 24 }]);
    assert.deepEqual(right.changes(), [], "a second form saw the first form's staged edit");
    assert.equal(right.dirty(), false);
  });

  test('createFieldWidget mounts and disposes 500 times without leaking listeners', () => {
    const fields = everyField();
    const state = panelState(fields);
    const mount = host();

    // One warm-up pass: the first mount of a widget may register a singleton,
    // and the question is whether the *steady state* grows — not whether it
    // started at zero. (The messenger's own `message` listener is already one.)
    for (const field of fields) {
      const widget = createFieldWidget(fieldContext(field, state));
      widget?.dispose();
    }

    const before = persistentListenerCount();
    let mounted = 0;
    for (let round = 0; round < 500; round++) {
      const field = fields[round % fields.length];
      if (field === undefined) {
        continue;
      }
      const widget = createFieldWidget(fieldContext(field, state));
      if (widget === null) {
        continue;
      }
      mounted++;
      mount.el.appendChild(widget.el);
      widget.dispose();
      while (mount.node.firstChild) {
        mount.node.removeChild(mount.node.firstChild);
      }
    }

    assert.ok(mounted >= 400, `only ${mounted} of 500 rounds mounted a widget`);
    assert.equal(
      persistentListenerCount(),
      before,
      `${persistentListenerCount() - before} listeners were left on document/window after ` +
        `${mounted} mount/dispose cycles — dispose() has to release what it registered`,
    );
    assert.equal(mount.node.childNodes.length, 0, 'the host was not emptied between rounds');
  });
});
