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

import { currentConfig, hasProjectConfig } from '../config';
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
