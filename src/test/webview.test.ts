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
import { render as renderAudit } from '../webview/dashboard/audit';
import { render as renderCatering } from '../webview/dashboard/catering';
import { render as renderHarness } from '../webview/dashboard/harness';
import { render as renderMonitor } from '../webview/dashboard/monitor';
import { render as renderSites } from '../webview/dashboard/sites';
import { render as renderWorkflows } from '../webview/dashboard/workflows';
import { render as renderFleet } from '../webview/dashboard/fleet';
import { render as renderDrafts } from '../webview/dashboard/governance';
import { render as renderSettings } from '../webview/dashboard/settings';
import { render as renderWelcome } from '../webview/dashboard/welcome';
import { createFieldWidget } from '../webview/panel/fields/index';
import { dataTable, gatedButton, statusPill } from '../webview/shared/components';
import { resetStagedForm, stagedForm } from '../webview/shared/form';
import { getMessenger } from '../webview/shared/messenger';
import {
  DASHBOARD_ROUTES,
  type DashboardRoute,
  type DashboardState,
  type Field,
  type FleetLaneView,
  type FleetState,
  type MonitorRepoView,
  type FieldContext,
  type PanelState,
  type SettingItem,
} from '../webview/shared/protocol';
import { svgEl } from '../webview/shared/svg';
import type { DashboardContext, DashboardUi } from '../webview/dashboard/main';
import {
  apiUrl,
  linkTarget,
  platformOrigin,
  StudioBridge,
  studioPage,
  tokenKey,
  type BridgeDeps,
} from '../core';

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

/** The five routes that take a snapshot rather than the view-local context. */
function bySnapshot(render: (host: HTMLElement, state: DashboardState) => void): Renderer {
  return (host, ctx) => {
    render(host, ctx.state);
  };
}

const RENDERERS: Record<DashboardRoute, Renderer> = {
  sites: bySnapshot(renderSites),
  contents: renderContents,
  drafts: bySnapshot(renderDrafts),
  audit: bySnapshot(renderAudit),
  catering: bySnapshot(renderCatering),
  fleet: bySnapshot(renderFleet),
  harness: bySnapshot(renderHarness),
  workflows: bySnapshot(renderWorkflows),
  monitor: bySnapshot(renderMonitor),
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

// ---------------------------------------------------------------------------
// An unread run list is unknown, never "no run on record"
// ---------------------------------------------------------------------------

suite('webview: a run list GitHub refused renders unknown', () => {
  setup(() => {
    resetDom();
    resetStagedForm();
  });

  function monitorRow(runsReadable: boolean): MonitorRepoView {
    return {
      slug: 'bamr87/irony-works',
      source: 'workspace',
      localRoot: '/w',
      fetchedAt: '2026-09-14T00:00:00Z',
      runsReadable,
      note: null,
      grade: null,
      mergePolicy: null,
      cost: null,
      lanes: [{ id: 'germinate', switchValue: 'true', lastRun: null, openPulls: 0, cost: null, grade: null }],
      pulls: [],
    };
  }

  function renderMonitorRow(row: MonitorRepoView): FakeElement {
    const mount = host();
    renderMonitor(mount.el, {
      ...emptyDashboardState(),
      monitor: {
        roster: [row],
        hub: { slug: 'bamr87/bamr87', readAt: null, note: null, scorecard: null },
        gitfactoryUrl: 'https://example.invalid/',
      },
    });
    return mount.node;
  }

  test('Monitor: a read with a refused run page draws unknown; a read that listed none draws "no run on record"', () => {
    const refused = renderMonitorRow(monitorRow(false));
    assert.doesNotMatch(text(refused), /no run on record/, 'an unread run page must not claim a measurement');
    assert.ok(
      findAll(refused, '.z-status--unknown').some((pill) => text(pill) === 'unknown'),
      'the run cell is an unknown pill',
    );

    resetDom();
    const read = renderMonitorRow(monitorRow(true));
    assert.match(text(read), /no run on record/, 'a 200 with no runs is a real answer');
  });

  function fleetState(fetchedAt: string | null, runsReadable: boolean, workflowsReadable: boolean): FleetState {
    const lane: FleetLaneView = {
      id: 'germinate',
      kind: 'content',
      harness: 'claude-cli',
      implementation: '.github/workflows/germinate.yml',
      description: 'germinate',
      triggers: 'schedule',
      switch: 'GERMINATE_ENABLED',
      switchValue: 'true',
      usesTokens: [],
      guardrails: 'never merges',
      lastRun: null,
      toggleBlockers: [],
      dispatchBlockers: [],
    };
    return {
      enabled: true,
      dispatchAllow: true,
      manifestPath: 'fleet.manifest.yml',
      repo: 'bamr87/irony-works',
      summary: '',
      provenance: 'derived',
      reason: null,
      lanes: [lane],
      tokens: [],
      fetchedAt,
      note: null,
      pulls: [],
      runsReadable,
      workflowsReadable,
    };
  }

  function renderFleetState(state: FleetState): FakeElement {
    const mount = host();
    renderFleet(mount.el, { ...emptyDashboardState(), fleet: state });
    return mount.node;
  }

  test('Fleet tab: unread and refused runs are not "no run on record"; a refused workflow list is not "not registered"', () => {
    assert.doesNotMatch(text(renderFleetState(fleetState(null, false, false))), /no run on record/, 'nothing read yet');

    resetDom();
    const refused = renderFleetState(fleetState('2026-09-14T00:00:00Z', false, false));
    assert.doesNotMatch(text(refused), /no run on record/);
    assert.match(text(refused), /runs unreadable/);
    const disabled = findAll(refused, 'button').map((button) => button.getAttribute('title') ?? '');
    assert.ok(
      !disabled.some((title) => /GitHub has no registered workflow/.test(title)),
      'a refused workflow list must not be described as an unregistered workflow',
    );

    resetDom();
    const read = renderFleetState(fleetState('2026-09-14T00:00:00Z', true, true));
    assert.match(text(read), /no run on record/, 'a 200 with no runs is a real answer');
  });
});


// ---------------------------------------------------------------------------
// The studio in a webview (PLAN G10): the host side of its transport
// ---------------------------------------------------------------------------

/**
 * `StudioBridge` is everything between a studio webview and the platform, so
 * these are the gates decisions D5, D11 and D13 ask of it, proved from outside
 * with a fetch that records instead of connecting: the token reaches the
 * configured platform and nothing else, a request that could leave the API —
 * or reach a route other than the one the gates read — is refused before a
 * socket opens, a live-site change asks the person every time, only the
 * headers the platform reads pass either way, and nothing the webview hears
 * carries the token.
 */
suite('studio: the host side of the webview transport (G10)', () => {
  const ORIGIN = 'https://cms.test';
  const TOKEN = 'zer0u_secret-token';

  interface FakeStream {
    url: string;
    headers: Record<string, string>;
    events: readonly string[];
    emit: (event: string, data: string | null) => void;
    closed: boolean;
  }

  interface Fake {
    deps: BridgeDeps;
    posted: Record<string, unknown>[];
    sent: Array<{ url: string; init: RequestInit }>;
    asked: string[];
    went: Record<string, unknown>[];
    opened: string[];
    streams: FakeStream[];
  }

  interface FakeOptions {
    origin?: string | undefined;
    answer?: boolean;
    respond?: () => Promise<Response>;
  }

  function fake(options: FakeOptions = {}): Fake {
    const posted: Record<string, unknown>[] = [];
    const sent: Array<{ url: string; init: RequestInit }> = [];
    const asked: string[] = [];
    const went: Record<string, unknown>[] = [];
    const opened: string[] = [];
    const streams: FakeStream[] = [];
    const origin = 'origin' in options ? options.origin : ORIGIN;
    const deps: BridgeDeps = {
      post: (message) => void posted.push(message as Record<string, unknown>),
      origin: () => origin,
      token: (asked) => Promise.resolve(asked === ORIGIN ? TOKEN : undefined),
      confirm: (question) => {
        asked.push(question);
        return Promise.resolve(options.answer ?? true);
      },
      fetch: (url, init) => {
        sent.push({ url, init });
        return (
          options.respond?.() ??
          Promise.resolve(new Response('{"ok":true}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
        );
      },
      openStream: (url, headers, events, onEvent) => {
        const stream: FakeStream = { url, headers, events, emit: onEvent, closed: false };
        streams.push(stream);
        return () => {
          stream.closed = true;
        };
      },
      go: (to) => void went.push(to),
      openExternal: (url) => void opened.push(url),
    };
    return { deps, posted, sent, asked, went, opened, streams };
  }

  const api = (path: string, method = 'GET', body?: string) => ({
    type: 'api',
    id: 1,
    method,
    path,
    ...(body === undefined ? {} : { body }),
  });

  test('a request goes to the configured platform with the token, and the webview hears only the status, the body and the headers it reads', async () => {
    const f = fake();
    await new StudioBridge(f.deps).receive(api("/api/v2/content/pages/?source=demo%2F_posts%2Fbackups.md&q=don't"));
    assert.equal(f.sent.length, 1);
    assert.equal(f.sent[0]?.url, `${ORIGIN}/api/v2/content/pages/?source=demo%2F_posts%2Fbackups.md&q=don%27t`);
    assert.deepEqual(f.sent[0]?.init.headers, { Accept: 'application/json', Authorization: `Bearer ${TOKEN}` });
    assert.equal(f.sent[0]?.init.redirect, 'error', 'a redirect could carry the token to another origin');
    assert.deepEqual(f.posted, [{ type: 'api', id: 1, status: 200, body: '{"ok":true}', headers: { 'Content-Type': 'application/json' } }]);

    await new StudioBridge(f.deps).receive(api('/api/v2/content/pages/5/', 'PATCH', '{"fields":{}}'));
    assert.equal(f.sent[1]?.init.body, '{"fields":{}}');
    assert.equal((f.sent[1]?.init.headers as Record<string, string>)['Content-Type'], 'application/json');
    assert.ok(!JSON.stringify(f.posted).includes(TOKEN), 'the token reached the webview');
  });

  test('a request that could leave the API, or reach another route than the gates read, is refused before a socket opens', async () => {
    const paths: unknown[] = [
      '/admin/pages/5/',
      '/api/v2/../admin/',
      '/api/v2/%2e%2e/admin/',
      '/api/v2/a%2Fb/',
      'https://evil.test/api/v2/me',
      '//evil.test/api/v2/me',
      '/api/v2/session/login',
      '/api/v2/session',
      '/api/v2/me#x',
      '/api/v2\\..\\admin',
      42,
      // Spellings the URL parser, a proxy or the platform would turn into a
      // publish, an unpublish or a sign-in that the gates never saw.
      '/api/v2/content/./pages/9/unpublish/',
      '/api/v2/./content/pages/5/publish/',
      '/api/v2/content/pages/5/./publish/',
      '/api/v2/content/pages/9/publish/.',
      '/api/v2/content/pages/9/%70ublish/',
      '/api/v2/content/pages/%35/publish/',
      '/api/v2/content/pages/5//publish/',
      '/api/v2//content/pages/5/publish/',
      '/api/v2/./session/login',
      '/api/v2/%73ession/login',
      '/api/v2/content/pages/5/pub\tlish/',
      '/api/v2/content/pages/5/pub\u00e9/',
    ];
    for (const method of ['GET', 'POST']) {
      for (const path of paths) {
        const f = fake({ answer: false });
        await new StudioBridge(f.deps).receive({ type: 'api', id: 1, method, path });
        assert.equal(f.sent.length, 0, `${method} ${String(path)} reached the network`);
        assert.equal(f.posted[0]?.status, 403, `${method} ${String(path)}`);
        assert.deepEqual(f.asked, [], `${method} ${String(path)} was asked about instead of refused`);
      }
    }
    for (const method of ['TRACE', 'OPTIONS', 'CONNECT', '']) {
      const f = fake();
      await new StudioBridge(f.deps).receive(api('/api/v2/me', method));
      assert.equal(f.sent.length, 0, method);
    }
    const withBody = fake();
    await new StudioBridge(withBody.deps).receive(api('/api/v2/me', 'GET', '{}'));
    assert.equal(withBody.posted[0]?.status, 422);
    assert.equal(withBody.sent.length, 0);
  });

  test('no platform, or no token for this platform, is said plainly and sends nothing', async () => {
    const none = fake({ origin: undefined });
    await new StudioBridge(none.deps).receive(api('/api/v2/me'));
    assert.equal(none.posted[0]?.status, 503);
    assert.match(String(none.posted[0]?.body), /zer0Cms\.platform\.url/);

    // The token is kept per origin: a platform URL changed under the person finds none.
    const elsewhere = fake({ origin: 'https://elsewhere.test' });
    await new StudioBridge(elsewhere.deps).receive(api('/api/v2/me'));
    assert.equal(elsewhere.posted[0]?.status, 401);
    assert.match(String(elsewhere.posted[0]?.body), /Set platform token/);
    assert.equal(none.sent.length + elsewhere.sent.length, 0);
  });

  test('publishing, unpublishing and scheduling ask the person every time, whatever the webview showed', async () => {
    const declined = fake({ answer: false });
    await new StudioBridge(declined.deps).receive(api('/api/v2/content/pages/5/publish/', 'POST'));
    assert.deepEqual(declined.asked, [`Publish page 5 on ${ORIGIN}?`]);
    assert.equal(declined.sent.length, 0, 'a declined publish reached the platform');
    assert.equal(declined.posted[0]?.status, 409);
    // A page id that is a UUID (P-D6) still asks; it does not slip past the pattern.
    const uuid = '0b9f6f4e-1c2d-4e5f-8a9b-0c1d2e3f4a5b';
    const byUuid = fake({ answer: false });
    await new StudioBridge(byUuid.deps).receive(api(`/api/v2/content/pages/${uuid}/unpublish/?next=1`, 'POST'));
    assert.deepEqual(byUuid.asked, [`Take page ${uuid} off the live site on ${ORIGIN}?`]);
    assert.equal(byUuid.sent.length, 0);

    const agreed = fake({ answer: true });
    const bridge = new StudioBridge(agreed.deps);
    await bridge.receive(api('/api/v2/content/pages/5/unpublish/', 'POST'));
    await bridge.receive(api('/api/v2/content/pages/5/schedule/', 'POST', '{"go_live_at":null}'));
    await bridge.receive(api('/api/v2/content/pages/5/', 'PATCH', '{}'));
    await bridge.receive(api('/api/v2/review/runs/7/accept/', 'POST', '{}'));
    assert.equal(agreed.asked.length, 2, 'only the live-site changes ask');
    assert.equal(agreed.sent.length, 4);
  });

  test('only the headers the platform reads cross, each way', async () => {
    const f = fake({
      respond: () =>
        Promise.resolve(
          new Response('{"run":7}', {
            status: 202,
            headers: { 'Content-Type': 'application/json', Location: '/api/v2/agent-runs/7/', 'Retry-After': '3', 'Set-Cookie': 'sessionid=x', 'X-Request-Id': 'r-1' },
          }),
        ),
    });
    const bridge = new StudioBridge(f.deps);
    const run = { ...api('/api/v2/ai/pipelines/p-1/run/', 'POST', '{}'), headers: { 'idempotency-key': 'k-1' } };
    await bridge.receive(run);
    assert.deepEqual(f.sent[0]?.init.headers, {
      'Idempotency-Key': 'k-1',
      Accept: 'application/json',
      Authorization: `Bearer ${TOKEN}`,
      'Content-Type': 'application/json',
    });
    assert.deepEqual(f.posted[0], {
      type: 'api',
      id: 1,
      status: 202,
      body: '{"run":7}',
      headers: { 'Content-Type': 'application/json', Location: '/api/v2/agent-runs/7/', 'Retry-After': '3', 'X-Request-Id': 'r-1' },
    });
    for (const headers of [{ Authorization: 'Bearer other' }, { Cookie: 'sessionid=x' }, { 'Idempotency-Key': 'a\r\nX-Evil: 1' }, { 'Idempotency-Key': 7 }, 'k-1']) {
      const refused = fake();
      await new StudioBridge(refused.deps).receive({ ...run, headers });
      assert.equal(refused.sent.length, 0, JSON.stringify(headers));
      assert.equal(refused.posted[0]?.status, 422, JSON.stringify(headers));
    }
  });

  test('a platform the network cannot reach is a 503 naming the platform, never the token', async () => {
    const f = fake({ respond: () => Promise.reject(new Error(`ECONNREFUSED while sending Bearer ${TOKEN}`)) });
    await new StudioBridge(f.deps).receive(api('/api/v2/me'));
    assert.equal(f.posted[0]?.status, 503);
    assert.match(String(f.posted[0]?.body), /cms\.test/);
    assert.ok(!JSON.stringify(f.posted).includes(TOKEN));
  });

  test('a stream is followed with the token, relayed by its id, closed at its end, and refused off the API', async () => {
    const f = fake();
    const bridge = new StudioBridge(f.deps);
    await bridge.receive({ type: 'stream', id: 3, path: '/api/v2/agent-runs/7/stream/', events: ['step', 'status', 'end'] });
    const stream = f.streams[0];
    assert.ok(stream !== undefined);
    assert.equal(stream.url, `${ORIGIN}/api/v2/agent-runs/7/stream/`);
    assert.deepEqual(stream.headers, { Authorization: `Bearer ${TOKEN}` });
    stream.emit('step', '{"idx":0}');
    stream.emit('end', null);
    assert.deepEqual(f.posted, [
      { type: 'event', id: 3, event: 'step', data: '{"idx":0}' },
      { type: 'event', id: 3, event: 'end', data: null },
    ]);
    assert.equal(stream.closed, true);

    await bridge.receive({ type: 'stream', id: 4, path: '/admin/', events: ['step'] });
    assert.equal(f.streams.length, 1);
    assert.deepEqual(f.posted.at(-1), { type: 'event', id: 4, event: 'error', data: null });

    await bridge.receive({ type: 'stream', id: 5, path: '/api/v2/agent-runs/8/stream/', events: ['step'] });
    bridge.dispose();
    assert.equal(f.streams[1]?.closed, true, 'a closed webview leaves no stream open');
  });

  test('a destination is handed on as data, and a link opens against the platform or not at all', async () => {
    const f = fake();
    const bridge = new StudioBridge(f.deps);
    await bridge.receive({ type: 'go', to: { to: 'page', id: 5 } });
    await bridge.receive({ type: 'go', to: 'page' });
    await bridge.receive({ type: 'go', to: { to: 'x', pad: 'y'.repeat(600) } });
    assert.deepEqual(f.went, [{ to: 'page', id: 5 }]);
    const hrefs = ['/admin/pages/5/view_draft/', 'https://example.org/a', 'javascript:alert(1)', '//evil.test/x', 'file:///etc/passwd'];
    for (const href of hrefs) {
      await bridge.receive({ type: 'open', href });
    }
    assert.deepEqual(f.opened, [`${ORIGIN}/admin/pages/5/view_draft/`, 'https://example.org/a']);
    await bridge.receive({ type: 'nonsense' });
    await bridge.receive(null);
    assert.equal(f.sent.length, 0);
  });

  test('the platform is https, or http on this machine; its token is kept per origin, and a path cannot leave it', () => {
    assert.equal(platformOrigin('https://cms.test/studio/'), ORIGIN);
    for (const local of ['http://127.0.0.1:8000', 'http://localhost:8000', 'http://[::1]:8000', 'http://127.1.2.3']) {
      assert.equal(platformOrigin(local), new URL(local).origin, local);
    }
    // Plain http anywhere else would carry the token across a network in clear text.
    for (const bad of ['', 'cms.test', 'ftp://cms.test', 'javascript:alert(1)', undefined, 'http://cms.test', 'http://10.0.0.5:8000', 'http://localhost.evil.test', 'http://127.0.0.1.evil.test']) {
      assert.equal(platformOrigin(bad), undefined, String(bad));
    }
    assert.notEqual(tokenKey(ORIGIN), tokenKey('https://other.test'));
    assert.equal(apiUrl(ORIGIN, '/api/v2/me')?.toString(), `${ORIGIN}/api/v2/me`);
    assert.equal(apiUrl(ORIGIN, '/api/v2/')?.toString(), `${ORIGIN}/api/v2/`);
    assert.equal(apiUrl(ORIGIN, '/api/v2/../me'), undefined);
    assert.equal(linkTarget('/x', undefined), undefined);
  });

  test('the page a studio webview loads: no connection, scripts and styles by nonce only, the editor theme first', () => {
    const html = studioPage({
      cspSource: 'vscode-webview://abc',
      nonce: 'N0nce',
      asset: (...parts) => `vscode-webview://abc/${parts.join('/')}`,
      view: 'page',
      surface: 'sidebar',
      origin: ORIGIN,
    });
    const policy = /Content-Security-Policy" content="([^"]+)"/.exec(html)?.[1] ?? '';
    assert.match(policy, /^default-src 'none'; /);
    assert.match(policy, /script-src 'nonce-N0nce'/);
    assert.match(policy, /style-src vscode-webview:\/\/abc 'nonce-N0nce'/);
    assert.match(policy, /img-src vscode-webview:\/\/abc https:\/\/cms\.test data: blob:(;|$)/);
    // An image is a request: from any other host it could carry what the page shows anywhere.
    assert.ok(!/(^|\s)(https?:|\*)(\s|;|$)/.test(policy), policy);
    assert.ok(!/unsafe-inline|unsafe-eval|connect-src/.test(policy), policy);
    assert.ok(html.indexOf('dist/media/tokens.css') < html.indexOf('dist/studio.css'), 'the theme map loads first');
    assert.match(html, /<script nonce="N0nce" src="vscode-webview:\/\/abc\/dist\/studio\.js"><\/script>/);
    assert.match(html, /data-view="page"/);
    assert.match(html, /<meta property="csp-nonce" nonce="N0nce">/);
    assert.ok(!/<script>|<style>/.test(html), 'no inline script or style');
  });
});
