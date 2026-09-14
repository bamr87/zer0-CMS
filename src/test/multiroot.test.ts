/**
 * Multi-root integration tests — the slice that makes "many sites" real.
 *
 * These run inside an extension host opened on `fixtures/multi.code-workspace`,
 * which is a **two-folder** window: `site-a` (Jekyll) and `site-b` (MkDocs).
 * That is a different window from the one every other integration test uses, so
 * `.vscode-test.mjs` carries a second `defineConfig` entry that runs only this
 * file. When this file is loaded by the *single*-root entry — its glob is
 * `out/test/**` and cannot exclude one file — every suite here skips itself and
 * says so, rather than failing against a window it was never about.
 *
 * Six questions, and each of them is a bug that shipped in some other editor
 * extension because nobody asked it:
 *
 *   1. do two folders get two stores, with two different cache keys?
 *   2. does the active site follow the active editor?
 *   3. does a command invoked on a file act on *that file's* site?
 *   4. does the MCP provider offer one server per folder, each with its own cwd?
 *   5. does a folder-scoped `publishAllow` arm one server and not the other?
 *   6. does a folderless answer still install zero watchers?
 *
 * Nothing here writes to either fixture folder, and nothing opens a socket.
 */

import * as assert from 'assert';
import * as path from 'path';
import * as vscode from 'vscode';

import { currentConfig, setActiveFolderResolver, workspaceTrusted } from '../config';
import { siteTarget } from '../commands/project';
import { mcpFolders, mcpPublishAllowed, mcpServerDefinitions } from '../mcpRegistration';
import { SiteRegistry } from '../sites';
import { indexCacheKeyFor, WorkspaceStore } from '../store';

const EXTENSION_ID = 'bamr87.zer0-cms';

/** `true` when this window is the two-folder one these tests are about. */
function isMultiRoot(): boolean {
  return (vscode.workspace.workspaceFolders ?? []).length >= 2;
}

function folderNamed(name: string): vscode.WorkspaceFolder {
  const found = (vscode.workspace.workspaceFolders ?? []).find((folder) => folder.name === name);
  assert.ok(found, `the fixture workspace should hold a folder named "${name}"`);
  return found;
}

/**
 * A `Memento` that lives for one test.
 *
 * The registry persists exactly one thing — the active site's id — and a test
 * that wrote it into the real `workspaceState` would leak a pinned site into
 * every later run of this suite.
 */
class MemoryMemento implements vscode.Memento {
  private readonly store = new Map<string, unknown>();

  keys(): readonly string[] {
    return [...this.store.keys()];
  }

  get<T>(key: string, defaultValue?: T): T | undefined {
    const value = this.store.get(key);
    return value === undefined ? defaultValue : (value as T);
  }

  update(key: string, value: unknown): Thenable<void> {
    if (value === undefined) {
      this.store.delete(key);
    } else {
      this.store.set(key, value);
    }
    return Promise.resolve();
  }
}

/** Wait for a predicate, or give up. Used only where VS Code fires an event. */
async function until(predicate: () => boolean, timeoutMs = 5000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return predicate();
}

// ---------------------------------------------------------------------------

suite('multi-root: the site registry', function () {
  this.timeout(60000);

  let registry: SiteRegistry | undefined;

  suiteSetup(async function () {
    if (!isMultiRoot()) {
      console.log('multiroot: skipped — this window has fewer than two folders open');
      this.skip();
      return;
    }
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, 'extension not found');
    await extension.activate();
  });

  teardown(() => {
    // Every test builds its own registry, and disposing it puts `config.ts`'s
    // resolver back on its default — this is module state, and it outlives the
    // object that set it.
    registry?.dispose();
    registry = undefined;
  });

  /** A registry over the fixture's two folders, with a throwaway Memento. */
  function build(): SiteRegistry {
    const state = new MemoryMemento();
    registry = new SiteRegistry(
      { workspaceState: state } as unknown as vscode.ExtensionContext,
      { state },
    );
    return registry;
  }

  test('two folders produce two stores, with distinct cache keys', () => {
    const sites = build().all();
    assert.strictEqual(sites.length, 2, 'one site per open folder');
    assert.deepStrictEqual(
      sites.map((site) => site.name),
      ['site-a', 'site-b'],
      'in the workspace file’s own order',
    );

    const [a, b] = sites;
    assert.ok(a && b);
    assert.notStrictEqual(a.store, b.store, 'each folder gets its own store');

    const keyA = indexCacheKeyFor(a.folder.uri.fsPath);
    const keyB = indexCacheKeyFor(b.folder.uri.fsPath);
    assert.notStrictEqual(
      keyA,
      keyB,
      'one cache key for twelve roots would rewrite every root on any refresh',
    );
    assert.ok(!keyA.includes(a.folder.uri.fsPath), 'the key is a hash, not somebody’s home directory');

    // Both are configured, and each reads its OWN zer0.json: site-a registers
    // `pages/_posts`, site-b registers `docs`.
    assert.strictEqual(a.configured(), true);
    assert.strictEqual(b.configured(), true);
    const cfgA = currentConfig(a.folder);
    const cfgB = currentConfig(b.folder);
    assert.ok(
      cfgA.contentFolders[0]?.path.endsWith(path.join('pages', '_posts')),
      `site-a should register pages/_posts, got ${cfgA.contentFolders[0]?.path ?? '(none)'}`,
    );
    assert.ok(
      cfgB.contentFolders[0]?.path.endsWith('docs'),
      `site-b should register docs, got ${cfgB.contentFolders[0]?.path ?? '(none)'}`,
    );
  });

  test('constructing the registry watches, and scans nothing', () => {
    const sites = build().all();
    for (const site of sites) {
      assert.ok(site.store.watcherCount > 0, `${site.name} should be watching its own folder`);
      assert.strictEqual(
        site.store.peek(),
        undefined,
        'no store may have built a snapshot: N stores must not be N scans at activation',
      );
    }
  });

  test('the active site follows the active editor', async () => {
    const bDoc = await vscode.workspace.openTextDocument(
      vscode.Uri.file(path.join(folderNamed('site-b').uri.fsPath, 'docs', 'index.md')),
    );
    await vscode.window.showTextDocument(bDoc, { preview: true });

    // Built with site-b's file already in front: the rule is evaluated in the
    // constructor, so this half needs no event at all.
    const sites = build();
    assert.strictEqual(sites.active()?.name, 'site-b', 'the editor’s folder is the active site');

    const aDoc = await vscode.workspace.openTextDocument(
      vscode.Uri.file(
        path.join(folderNamed('site-a').uri.fsPath, 'pages', '_posts', '2026-01-01-alpha.md'),
      ),
    );
    await vscode.window.showTextDocument(aDoc, { preview: true });
    assert.ok(
      await until(() => sites.active()?.name === 'site-a'),
      `switching editors should move the active site, got ${sites.active()?.name ?? '(none)'}`,
    );

    // …until somebody picks one. An explicit pick outranks the editor, which is
    // the first clause of `resolveActiveSite`.
    const siteB = sites.all().find((site) => site.name === 'site-b');
    assert.ok(siteB);
    assert.strictEqual(sites.setActive(siteB.id), true);
    await vscode.window.showTextDocument(aDoc, { preview: true });
    assert.strictEqual(sites.active()?.name, 'site-b', 'an explicit pick is not overruled by an editor');

    assert.strictEqual(sites.setActive('file:///nowhere'), false, 'an unknown id changes nothing');
    assert.strictEqual(sites.active()?.name, 'site-b');

    await vscode.commands.executeCommand('workbench.action.closeAllEditors');
  });

  test('a file-targeted command resolves its own site, not the active one', () => {
    const sites = build();
    const siteA = sites.all().find((site) => site.name === 'site-a');
    const siteB = sites.all().find((site) => site.name === 'site-b');
    assert.ok(siteA && siteB);

    assert.strictEqual(sites.setActive(siteA.id), true, 'point the console at site-a');
    assert.strictEqual(currentConfig().workspaceRoot, siteA.folder.uri.fsPath);

    // The same argument shapes the commands accept: a Uri from a tree row, and
    // an absolute path from a webview.
    const bFile = path.join(siteB.folder.uri.fsPath, 'docs', 'index.md');
    const fromUri = siteTarget(vscode.Uri.file(bFile));
    assert.ok(fromUri, 'a Uri argument should resolve');
    assert.strictEqual(
      fromUri.cfg.workspaceRoot,
      siteB.folder.uri.fsPath,
      'a command invoked on site-b’s file must act on site-b',
    );

    const fromPath = siteTarget(bFile);
    assert.strictEqual(fromPath?.cfg.workspaceRoot, siteB.folder.uri.fsPath);
    assert.strictEqual(fromPath?.filePath, bFile);

    // A *relative* path is the active site's, by construction: a webview names
    // the paths of the site it is showing.
    const relative = siteTarget(path.join('pages', '_posts', '2026-01-01-alpha.md'));
    assert.strictEqual(relative?.cfg.workspaceRoot, siteA.folder.uri.fsPath);

    // And the site's own registered content folder came with it.
    assert.ok(
      fromUri.cfg.contentFolders[0]?.path.endsWith('docs'),
      'site-b’s config, not site-a’s',
    );
    assert.strictEqual(sites.forUri(vscode.Uri.file(bFile))?.name, 'site-b');
  });

  test('the sites view model reports each folder honestly', async () => {
    const sites = build();
    const views = await sites.views();
    assert.strictEqual(views.length, 2);

    const a = views.find((view) => view.name === 'site-a');
    const b = views.find((view) => view.name === 'site-b');
    assert.ok(a && b);
    assert.strictEqual(a.platform, 'jekyll', 'site-a carries a _config.yml');
    assert.strictEqual(b.platform, 'mkdocs', 'site-b carries a mkdocs.yml');
    assert.strictEqual(a.configured, true);
    assert.strictEqual(b.configured, true);
    assert.strictEqual(a.scheme, 'file');
    // Nothing has been scanned, and the counts say so rather than saying zero.
    assert.match(a.detectionSource, /not scanned/);
    assert.strictEqual(a.counts.pages, 0);
    assert.strictEqual(views.filter((view) => view.active).length, 1, 'exactly one active site');
  });
});

// ---------------------------------------------------------------------------

suite('multi-root: one MCP server per site', function () {
  this.timeout(60000);

  suiteSetup(async function () {
    if (!isMultiRoot()) {
      this.skip();
      return;
    }
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, 'extension not found');
    await extension.activate();
  });

  test('provideMcpServerDefinitions returns two, with distinct cwd and an empty env', () => {
    assert.strictEqual(workspaceTrusted(), true, 'the test host runs with trust granted');
    assert.strictEqual(mcpFolders().length, 2, 'both folders carry a project config');

    const servers = mcpServerDefinitions('/tmp/mcp-server.js', '9.9.9');
    assert.strictEqual(servers.length, 2, 'one server per configured folder');

    const cwds = servers.map((server) => server.cwd?.fsPath ?? '');
    assert.strictEqual(new Set(cwds).size, 2, 'each server is rooted in its own folder');
    for (const folder of vscode.workspace.workspaceFolders ?? []) {
      assert.ok(cwds.includes(folder.uri.fsPath), `no server for ${folder.name}`);
    }

    const labels = servers.map((server) => server.label);
    assert.strictEqual(new Set(labels).size, 2, 'two servers with one name would be unusable');
    for (const label of labels) {
      assert.match(label, /^zer0-CMS · site-[ab]$/);
    }

    // Phase one carries no decision at all. This is the whole two-phase rule,
    // and multi-root does not bend it.
    for (const server of servers) {
      assert.deepStrictEqual(server.env, {}, 'a definition may be cached and shown: no env');
      assert.strictEqual(server.version, '9.9.9');
    }
  });

  test('a folder-scoped publishAllow arms only its own server', () => {
    const a = folderNamed('site-a');
    const b = folderNamed('site-b');

    // site-a's own `.vscode/settings.json` sets the setting; site-b's
    // `zer0.json` sets the same key. Only the first is a person.
    assert.strictEqual(
      mcpPublishAllowed(a),
      true,
      'site-a’s folder-scoped setting should arm site-a’s server',
    );
    assert.strictEqual(
      mcpPublishAllowed(b),
      false,
      'site-b’s zer0.json must not arm anything — a file that arrives with a clone is not consent',
    );
    assert.strictEqual(
      currentConfig(b).governance.publishAllow,
      true,
      'the merged in-editor value still honours the file; only the MCP flag does not',
    );

    // And the unscoped call answers for the active site rather than for
    // whichever folder happens to be first — that is the whole resolver seam.
    assert.strictEqual(typeof mcpPublishAllowed(), 'boolean');
  });
});

// ---------------------------------------------------------------------------

suite('multi-root: a folderless answer installs zero watchers', function () {
  this.timeout(60000);

  /**
   * The folderless promise, tested without a second Electron process.
   *
   * `extension.test.ts` spawns a genuinely folderless window for the activation
   * half of this promise. What is new here — and what this slice could plausibly
   * break — is the *resolver seam*: `WorkspaceStore` now asks
   * `workspaceRoot(this.folder)`, which goes through whatever resolver the shell
   * installed. A resolver that quietly fell back to `workspaceFolders[0]` would
   * make a folderless store watch a folder it was never given, and the spawned
   * window would not catch it because there is no folder zero there to fall
   * back to. So this installs a resolver that answers "no folder" — exactly what
   * `SiteRegistry` answers with nothing open — and checks the store's own count.
   */
  test('a store whose resolver answers "no folder" watches nothing', () => {
    setActiveFolderResolver(() => undefined);
    let store: WorkspaceStore | undefined;
    try {
      assert.strictEqual(currentConfig().workspaceRoot, '', 'a folderless config is empty, not partial');
      store = new WorkspaceStore({});
      assert.strictEqual(store.watcherCount, 0, 'zero watchers, zero filesystem reads');
      assert.strictEqual(store.peek(), undefined);
    } finally {
      store?.dispose();
      setActiveFolderResolver(null);
    }
  });
});
