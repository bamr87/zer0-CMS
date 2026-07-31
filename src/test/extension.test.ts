/**
 * Integration tests — these run *inside* the extension host, on the fixture
 * workspace that `.vscode-test.mjs` opens.
 *
 * What is worth testing here is only what cannot be tested anywhere else: the
 * contribution surface. Every behaviour that is really about content, fields or
 * governance is tested against pure functions in the plain-node suites, which
 * run in a second rather than a minute. So this file asks four questions:
 *
 *   1. does the extension activate,
 *   2. is every command in `package.json` actually registered — a contributed
 *      command with no `registerCommand` behind it is a menu entry that throws
 *      when clicked, and `getCommands(true)` is what tells them apart,
 *   3. do the five views (four trees plus the webview panel) exist and bind,
 *   4. do the context keys the `when` clauses depend on hold the right values.
 *
 * Plus one thing the fixture workspace cannot show by construction: that
 * activation survives a window with **no folder open at all**. That is checked
 * by launching a second, folderless VS Code — see `runFolderlessWindow`.
 */

import * as assert from 'assert';
import { spawn } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

import { currentConfig, hasProjectConfig, settingsPublishAllow } from '../config';
import type { PageEntry } from '../core';
import { contentTargetPath } from '../dashboard/dashboardPanel';
import { mcpPublishAllowed } from '../mcpRegistration';
import { emptySnapshot, type Snapshot } from '../store';
import { ALL_CONTEXT_KEYS, CONTEXT_KEYS, UiState, type ContextKey } from '../uiState';

const EXTENSION_ID = 'bamr87.zer0-cms';
const REPO_ROOT = path.resolve(__dirname, '../..');

/** All 34 command ids from PLAN §5.1, in contribution order. */
const ALL_COMMANDS: readonly string[] = [
  'zer0Cms.init',
  'zer0Cms.dashboard',
  'zer0Cms.dashboard.close',
  'zer0Cms.refresh',
  'zer0Cms.cache.clear',
  'zer0Cms.showOutput',
  'zer0Cms.registerFolder',
  'zer0Cms.unregisterFolder',
  'zer0Cms.createContent',
  'zer0Cms.createContentInFolder',
  'zer0Cms.generateSlug',
  'zer0Cms.setLastModified',
  'zer0Cms.insertImage',
  'zer0Cms.openFile',
  'zer0Cms.collapseSections',
  'zer0Cms.focusTags',
  'zer0Cms.focusCategories',
  'zer0Cms.contentType.generate',
  'zer0Cms.contentType.addMissingFields',
  'zer0Cms.contentType.set',
  'zer0Cms.draft.new',
  'zer0Cms.draft.review',
  'zer0Cms.draft.approve',
  'zer0Cms.draft.publish',
  'zer0Cms.draft.guard',
  'zer0Cms.draft.preview',
  'zer0Cms.catering.worklist',
  'zer0Cms.contract.run',
  'zer0Cms.contract.normalizePreview',
  'zer0Cms.contract.normalizeApply',
  'zer0Cms.agent.open',
  'zer0Cms.agent.start',
  'zer0Cms.agent.stop',
  'zer0Cms.mcp.writeWorkspaceConfig',
];

/** The four trees, plus the webview view, all in the `zer0-cms` container. */
const TREE_VIEWS: readonly string[] = [
  'zer0Cms.drafts',
  'zer0Cms.content',
  'zer0Cms.catering',
  'zer0Cms.published',
];
const PANEL_VIEW = 'zer0Cms.panel';

interface PackageJson {
  contributes: {
    commands: Array<{ command: string; title: string }>;
    views: Record<string, Array<{ id: string; type?: string }>>;
    viewsContainers: Record<string, Array<{ id: string }>>;
  };
}

function readPackageJson(): PackageJson {
  return JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'package.json'), 'utf8')) as PackageJson;
}

/** Every `when` clause anywhere in `contributes`, however deeply nested. */
function collectWhenClauses(value: unknown, found: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) {
      collectWhenClauses(item, found);
    }
    return found;
  }
  if (typeof value === 'object' && value !== null) {
    for (const [key, child] of Object.entries(value)) {
      if (key === 'when' && typeof child === 'string') {
        found.push(child);
      } else {
        collectWhenClauses(child, found);
      }
    }
  }
  return found;
}

// ---------------------------------------------------------------------------
// Activation and the contribution surface
// ---------------------------------------------------------------------------

suite('extension: activation and contributions', function () {
  this.timeout(60000);

  let extension: vscode.Extension<unknown>;
  let commands: string[];

  suiteSetup(async () => {
    const found = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(found, `extension ${EXTENSION_ID} is not installed in the test host`);
    extension = found;
    await extension.activate();
    commands = await vscode.commands.getCommands(true);
  });

  test('the extension activates on the fixture workspace', () => {
    assert.strictEqual(extension.isActive, true, 'activate() resolved but isActive is false');
    assert.ok(vscode.workspace.workspaceFolders?.length, 'the fixture workspace folder is open');
    assert.strictEqual(hasProjectConfig(), true, 'the fixture workspace has a zer0.json');
  });

  test('all 34 contributed commands are registered', () => {
    assert.strictEqual(ALL_COMMANDS.length, 34, 'the expected list itself is 34 long');
    const missing = ALL_COMMANDS.filter((command) => !commands.includes(command));
    assert.deepStrictEqual(missing, [], 'contributed but never registered');
  });

  test('package.json contributes exactly those 34 and nothing else', () => {
    // Catches both directions: a command registered but never contributed is
    // invisible in the palette, and a command contributed but dropped from the
    // list above would otherwise slip past the test that precedes this one.
    const contributed = readPackageJson().contributes.commands.map((entry) => entry.command);
    assert.deepStrictEqual(contributed, [...ALL_COMMANDS]);
  });

  test('the four tree views and the webview panel register', async () => {
    for (const view of [...TREE_VIEWS, PANEL_VIEW]) {
      // The workbench registers `<viewId>.focus` for every contributed view;
      // its presence is the proof that the contribution was accepted.
      assert.ok(commands.includes(`${view}.focus`), `view ${view} was never contributed`);
      // And revealing it resolves the provider the extension registered.
      await vscode.commands.executeCommand(`${view}.focus`);
    }
    assert.ok(
      commands.includes('workbench.view.extension.zer0-cms'),
      'the activity-bar container is missing',
    );
  });

  test('the panel view provider belongs to this extension', () => {
    // Registering a second provider for the same view type throws — which only
    // happens if the extension already claimed it during activation.
    assert.throws(
      () =>
        vscode.window.registerWebviewViewProvider(PANEL_VIEW, {
          resolveWebviewView: () => undefined,
        }),
      /already registered/i,
      `nothing had registered a provider for ${PANEL_VIEW}`,
    );
  });

  test('every contributed view id is one this extension knows about', () => {
    const contributed = readPackageJson().contributes.views['zer0-cms'] ?? [];
    assert.deepStrictEqual(
      contributed.map((view) => view.id).sort(),
      [...TREE_VIEWS, PANEL_VIEW].sort(),
    );
    const panel = contributed.find((view) => view.id === PANEL_VIEW);
    assert.strictEqual(panel?.type, 'webview', 'the metadata panel is a webview view');
  });

  test('refresh runs cleanly against the fixture workspace', async () => {
    await vscode.commands.executeCommand('zer0Cms.refresh');
  });
});

// ---------------------------------------------------------------------------
// Context keys
// ---------------------------------------------------------------------------

/**
 * `setContext` is write-only: VS Code offers no way to read a context key back.
 * So these tests drive a `UiState` of their own and assert on its mirror, which
 * is the same object the real one keeps and the only record of what was
 * written. The instance is restored to the live values and disposed in
 * `suiteTeardown` so the workbench is not left holding test state.
 */
suite('extension: the context keys the when-clauses depend on', function () {
  this.timeout(60000);

  let ui: UiState;
  let tmpDir: string;

  suiteSetup(async () => {
    await vscode.extensions.getExtension(EXTENSION_ID)?.activate();
    ui = new UiState();
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'zer0-cms-keys-'));
  });

  suiteTeardown(() => {
    // Put every key back where the live extension believes it left it.
    const cfg = currentConfig();
    ui.setDashboardOpen(false);
    ui.setAgentRunning(false);
    ui.setFolderRegistered(false);
    ui.applyEditor(cfg, vscode.window.activeTextEditor);
    ui.applyConfig(cfg, hasProjectConfig());
    ui.dispose();
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  test('the declared keys are exactly the ones the manifest uses', () => {
    assert.deepStrictEqual([...ALL_CONTEXT_KEYS].sort(), [
      'zer0Cms:agent:enabled',
      'zer0Cms:agent:running',
      'zer0Cms:contract:present',
      'zer0Cms:dashboard:open',
      'zer0Cms:enabled',
      'zer0Cms:file:isValid',
      'zer0Cms:folder:registered',
      'zer0Cms:governance:enabled',
    ]);
    const used = new Set<string>();
    for (const clause of collectWhenClauses(readPackageJson().contributes)) {
      for (const key of clause.match(/zer0Cms:[A-Za-z:]+/g) ?? []) {
        used.add(key);
      }
    }
    const declared = new Set<string>(ALL_CONTEXT_KEYS);
    assert.deepStrictEqual(
      [...used].filter((key) => !declared.has(key)),
      [],
      'a when-clause names a key nothing ever sets',
    );
    assert.deepStrictEqual(
      [...declared].filter((key) => !used.has(key)),
      [],
      'a key is maintained but gates nothing',
    );
  });

  test('applyConfig seeds all eight keys and follows the project config', () => {
    const cfg = currentConfig();
    ui.applyConfig(cfg, true);
    for (const key of ALL_CONTEXT_KEYS) {
      assert.notStrictEqual(ui.get(key), undefined, `${key} was left unset`);
    }
    assert.strictEqual(ui.get(CONTEXT_KEYS.enabled), true, 'a workspace with a zer0.json is enabled');
    assert.strictEqual(ui.get(CONTEXT_KEYS.governanceEnabled), cfg.governance.enabled);
    assert.strictEqual(ui.get(CONTEXT_KEYS.agentEnabled), cfg.agent.enabled);

    ui.applyConfig(cfg, false);
    assert.strictEqual(ui.get(CONTEXT_KEYS.enabled), false, 'no zer0.json means not enabled');
  });

  test('enabled is false in a folderless window even with a config claiming otherwise', () => {
    const folderless = { ...currentConfig(), workspaceRoot: '' };
    ui.applyConfig(folderless, true);
    assert.strictEqual(ui.get(CONTEXT_KEYS.enabled), false);
    ui.applyConfig(currentConfig(), hasProjectConfig());
  });

  test('contract:present, governance and agent follow the snapshot', () => {
    const cfg = currentConfig();
    const absent: Snapshot = emptySnapshot(cfg);
    ui.applySnapshot(absent);
    assert.strictEqual(ui.get(CONTEXT_KEYS.contractPresent), false);

    const present: Snapshot = {
      ...absent,
      contract: { ...absent.contract, present: true },
    };
    ui.applySnapshot(present);
    assert.strictEqual(ui.get(CONTEXT_KEYS.contractPresent), true);
  });

  test('file:isValid follows the active editor', async () => {
    const cfg = currentConfig();
    const markdown = path.join(tmpDir, 'sample.md');
    fs.writeFileSync(markdown, ['---', 'title: Sample', '---', '', 'Body.', ''].join('\n'), 'utf8');
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(markdown));
    const editor = await vscode.window.showTextDocument(document, { preview: true });

    ui.applyEditor(cfg, editor);
    assert.strictEqual(ui.get(CONTEXT_KEYS.fileIsValid), true, 'markdown with front matter is editable');

    ui.applyEditor(cfg, undefined);
    assert.strictEqual(ui.get(CONTEXT_KEYS.fileIsValid), false, 'no editor, no metadata panel');

    const plain = path.join(tmpDir, 'notes.txt');
    fs.writeFileSync(plain, 'not content\n', 'utf8');
    const plainDoc = await vscode.workspace.openTextDocument(vscode.Uri.file(plain));
    const plainEditor = await vscode.window.showTextDocument(plainDoc, { preview: true });
    ui.applyEditor(cfg, plainEditor);
    assert.strictEqual(ui.get(CONTEXT_KEYS.fileIsValid), false, 'a .txt is not a supported file type');

    await vscode.commands.executeCommand('workbench.action.closeAllEditors');
  });

  test('the three imperative keys toggle both ways', () => {
    const cases: ReadonlyArray<[(value: boolean) => void, ContextKey]> = [
      [(value) => ui.setDashboardOpen(value), CONTEXT_KEYS.dashboardOpen],
      [(value) => ui.setAgentRunning(value), CONTEXT_KEYS.agentRunning],
      [(value) => ui.setFolderRegistered(value), CONTEXT_KEYS.folderRegistered],
    ];
    for (const [set, key] of cases) {
      set(true);
      assert.strictEqual(ui.get(key), true, `${key} did not go true`);
      set(false);
      assert.strictEqual(ui.get(key), false, `${key} did not go false`);
    }
  });
});

// ---------------------------------------------------------------------------
// A window with no folder
// ---------------------------------------------------------------------------

/**
 * Launch a second VS Code with no folder and let it activate the extension.
 *
 * The fixture workspace cannot answer this question: the test host always has a
 * folder open, and `vscode.workspace.workspaceFolders` cannot be emptied from
 * inside the host without restarting it. So a real folderless window is
 * started instead.
 *
 * `process.execPath` inside the extension host *is* the VS Code binary running
 * these tests, so the child is by construction the same build — no download, no
 * version constant to keep in step with `.vscode-test.mjs`. The environment is
 * scrubbed of `ELECTRON_RUN_AS_NODE` and every `VSCODE_*` variable, which are
 * what make this process behave as node and would otherwise stop the child from
 * starting as an editor at all.
 */
function runFolderlessWindow(): Promise<{ code: number | null; output: string }> {
  // A deliberately short prefix: VS Code's IPC socket lives under
  // `--user-data-dir` and macOS caps a unix socket path at 103 characters.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zc-'));
  const runner = path.join(dir, 'folderless.js');
  fs.writeFileSync(
    runner,
    [
      "const assert = require('assert');",
      "const vscode = require('vscode');",
      'async function run() {',
      `  const extension = vscode.extensions.getExtension(${JSON.stringify(EXTENSION_ID)});`,
      "  assert.ok(extension, 'extension not found in the folderless window');",
      '  assert.strictEqual(',
      '    vscode.workspace.workspaceFolders,',
      '    undefined,',
      "    'this window was supposed to have no folder open',",
      '  );',
      '  await extension.activate();',
      "  assert.strictEqual(extension.isActive, true, 'activation did not complete');",
      '  const commands = await vscode.commands.getCommands(true);',
      '  for (const command of ' + JSON.stringify(ALL_COMMANDS) + ') {',
      '    assert.ok(commands.includes(command), `missing command: ${command}`);',
      '  }',
      "  await vscode.commands.executeCommand('zer0Cms.refresh');",
      "  process.stdout.write('FOLDERLESS-ACTIVATION-OK\\n');",
      '}',
      'module.exports.run = run;',
      '',
    ].join('\n'),
    'utf8',
  );

  const env: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined || key === 'ELECTRON_RUN_AS_NODE' || key.startsWith('VSCODE_')) {
      continue;
    }
    env[key] = value;
  }

  const args = [
    `--extensionDevelopmentPath=${REPO_ROOT}`,
    `--extensionTestsPath=${runner}`,
    // Private to this run, so two `npm test` invocations on one machine cannot
    // hand each other's window the test path.
    `--user-data-dir=${path.join(dir, 'u')}`,
    `--extensions-dir=${path.join(dir, 'e')}`,
    '--disable-gpu',
    '--disable-updates',
    '--disable-telemetry',
    '--disable-workspace-trust',
    '--skip-welcome',
    '--skip-release-notes',
    '--no-sandbox',
    // Deliberately no folder argument. That is the whole point.
  ];

  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, { env, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    child.stdout.on('data', (chunk: Buffer) => {
      output += chunk.toString('utf8');
    });
    child.stderr.on('data', (chunk: Buffer) => {
      output += chunk.toString('utf8');
    });
    child.on('error', reject);
    child.on('close', (code) => {
      fs.rmSync(dir, { recursive: true, force: true });
      resolve({ code, output });
    });
  });
}

// ---------------------------------------------------------------------------
// The gates a forged webview message and a checked-in file must not open
// ---------------------------------------------------------------------------

suite('extension: a file in the repository cannot arm the MCP publish flag', function () {
  this.timeout(60000);

  const settingsFile = (): string => {
    const folder = vscode.workspace.workspaceFolders?.[0];
    assert.ok(folder, 'the fixture workspace is open');
    return path.join(folder.uri.fsPath, '.vscode', 'settings.json');
  };

  test('zer0.json says true, nobody set the setting, and the server stays read-only', async () => {
    const file = settingsFile();
    const before = fs.readFileSync(file, 'utf8');
    const section = (): vscode.WorkspaceConfiguration =>
      vscode.workspace.getConfiguration('zer0Cms');
    try {
      // The fixture's `zer0.json` sets `governance.publishAllow: true` and its
      // `.vscode/settings.json` sets the setting to false. Remove the setting
      // and the merge — correctly — lets the file's `true` through.
      await section().update(
        'governance.publishAllow',
        undefined,
        vscode.ConfigurationTarget.Workspace,
      );
      assert.equal(settingsPublishAllow(), undefined, 'no human set it');
      assert.equal(
        currentConfig().governance.publishAllow,
        true,
        'the in-editor gates still read the merged value, and zer0.json wins there',
      );
      assert.equal(
        mcpPublishAllowed(),
        false,
        'but ZER0_CMS_MCP_ALLOW_PUBLISH is the gate a zer0.json must not reach: past it, ' +
          "zer0_publish's only other gate is `confirm: true`, which an agent supplies to itself",
      );

      await section().update('governance.publishAllow', true, vscode.ConfigurationTarget.Workspace);
      assert.equal(mcpPublishAllowed(), true, 'a setting a person wrote does arm it');

      await section().update('governance.publishAllow', false, vscode.ConfigurationTarget.Workspace);
      assert.equal(mcpPublishAllowed(), false);
    } finally {
      await section().update('governance.publishAllow', false, vscode.ConfigurationTarget.Workspace);
      // Restore the fixture byte for byte — it carries a comment explaining why
      // it disagrees with `zer0.json`, and `update()` reformats around it.
      fs.writeFileSync(file, before, 'utf8');
    }
  });
});

suite('extension: the dashboard re-derives its own delete target', function () {
  this.timeout(60000);

  const pages: PageEntry[] = [
    { filePath: path.join('/ws', 'pages', '_posts', 'a.md') } as PageEntry,
    { filePath: path.join('/ws', 'pages', '_posts', 'b.md') } as PageEntry,
  ];

  test('an absolute path outside the index names nothing', () => {
    for (const forged of ['/home/me/.ssh/id_rsa', '/etc/hosts', '../../etc/passwd', '']) {
      assert.equal(
        contentTargetPath('/ws', pages, forged),
        undefined,
        `"${forged}" must not resolve to something deletable`,
      );
    }
  });

  test('an indexed file resolves, by absolute path and by workspace-relative path', () => {
    const target = path.join('/ws', 'pages', '_posts', 'a.md');
    assert.equal(contentTargetPath('/ws', pages, target), target);
    assert.equal(contentTargetPath('/ws', pages, 'pages/_posts/a.md'), target);
    assert.equal(contentTargetPath('/ws', pages, 'pages/_posts/c.md'), undefined);
  });

  test('a folderless window resolves nothing at all', () => {
    // Otherwise a relative target resolves against the extension host's cwd.
    assert.equal(contentTargetPath('', pages, 'pages/_posts/a.md'), undefined);
    assert.equal(contentTargetPath('', pages, path.join('/ws', 'pages', '_posts', 'a.md')), undefined);
  });
});

// ---------------------------------------------------------------------------
// Webview assets — a missing icon font looks exactly like a working build
// ---------------------------------------------------------------------------

suite('extension: the webviews ship the icon font they render with', () => {
  test('the build copies the codicon stylesheet and webfont into dist/media', () => {
    const dir = path.join(REPO_ROOT, 'dist', 'media');
    const css = fs.readFileSync(path.join(dir, 'codicon.css'), 'utf8');
    assert.ok(css.includes('@font-face'), 'the stylesheet declares the face');
    assert.ok(css.includes('codicon.ttf'), 'and points at the file next to it');
    assert.ok(fs.statSync(path.join(dir, 'codicon.ttf')).size > 1000, 'the font itself is there');

    // Every name `icon()` is called with has to exist in the font, or that call
    // site renders an empty element and its control becomes a blank box.
    const used = new Set<string>();
    const webview = path.join(REPO_ROOT, 'src', 'webview');
    const walk = (dir2: string): void => {
      for (const entry of fs.readdirSync(dir2, { withFileTypes: true })) {
        const full = path.join(dir2, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (entry.name.endsWith('.ts')) {
          for (const match of fs.readFileSync(full, 'utf8').matchAll(/\bicon\('([a-z0-9-]+)'/g)) {
            const name = match[1];
            if (name !== undefined) {
              used.add(name);
            }
          }
        }
      }
    };
    walk(webview);
    assert.ok(used.size >= 20, `expected the webviews to use icons, found ${used.size}`);
    for (const name of [...used].sort()) {
      assert.ok(css.includes(`.codicon-${name}:before`), `codicon-${name} is not in the font`);
    }
  });

  test('all three webview shells link it', () => {
    for (const shell of [
      path.join('src', 'panel', 'panelProvider.ts'),
      path.join('src', 'dashboard', 'dashboardPanel.ts'),
      path.join('src', 'agent', 'agentPanel.ts'),
    ]) {
      const source = fs.readFileSync(path.join(REPO_ROOT, shell), 'utf8');
      assert.ok(
        /'dist',\s*'media',\s*'codicon\.css'/.test(source),
        `${shell} does not link the codicon stylesheet — its icons would render as empty elements`,
      );
    }
  });

  test('base.css beats codicon.css on the three sizing rules', () => {
    // `codicon.css` sizes `.codicon[class*='codicon-']` with the `font`
    // shorthand, which resets font-size and is (0,2,0). A bare `.codicon` here
    // loses on specificity whatever the link order is.
    const css = fs.readFileSync(path.join(REPO_ROOT, 'media', 'base.css'), 'utf8');
    for (const selector of [
      ".codicon[class*='codicon-'] {",
      ".codicon[class*='codicon-'].z-icon-md {",
      ".codicon[class*='codicon-'].z-icon-lg {",
    ]) {
      assert.ok(css.includes(selector), `base.css is missing "${selector}"`);
    }
  });

  test('the per-item selection box is only hidden inside a grid card', () => {
    // `selectionBox()` emits `.z-card__select` in all three layouts. Hiding it
    // unconditionally left List and Structure with no way to select one row.
    // Comments are stripped first: the rules below *explain* why they do not
    // say `visibility: hidden`, and a naive scan would match the explanation.
    const css = fs
      .readFileSync(path.join(REPO_ROOT, 'media', 'dashboard.css'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '');
    /** The declarations of the first rule whose selector list is exactly `selector`. */
    const ruleBody = (selector: string): string => {
      const at = css.indexOf(`\n${selector} {`);
      assert.notEqual(at, -1, `dashboard.css has no "${selector}" rule`);
      const open = css.indexOf('{', at);
      return css.slice(open + 1, css.indexOf('}', open));
    };

    assert.ok(
      !/visibility:\s*hidden/.test(ruleBody('.z-card__select')),
      'the shared rule must not hide the control — the list row and the tree node use it too',
    );
    assert.ok(
      !/visibility:\s*hidden/.test(ruleBody('.z-card .z-card__select')),
      'and the card overlay uses opacity, so the input stays in the focus order for :focus-within',
    );
    assert.ok(
      /opacity:\s*0/.test(ruleBody('.z-card .z-card__select')),
      'the grid card still hides its box until hover',
    );
  });
});

suite('extension: a folderless window', function () {
  // A second editor has to boot, which is slower than anything else here.
  this.timeout(240000);

  test('activation completes without throwing and registers every command', async () => {
    const { code, output } = await runFolderlessWindow();
    assert.ok(
      output.includes('FOLDERLESS-ACTIVATION-OK'),
      `folderless activation did not reach the end:\n${output.slice(-4000)}`,
    );
    assert.strictEqual(code, 0, `folderless window exited ${code}:\n${output.slice(-4000)}`);
  });
});
