/**
 * The only translator between VS Code and the core's `Zer0Config`.
 *
 * Three layers, exactly as decision D2 describes them:
 *
 *   1. VS Code settings  (`zer0Cms.*`) — the user's preferences
 *   2. `zer0.json`                     — the project's schema
 *   3. built-in defaults               — `core/shared/config.ts`
 *
 * The subtlety that makes those three layers real is `inspect()`. A plain
 * `getConfiguration('zer0Cms').get('governance.publishAllow')` never returns
 * `undefined`: every one of our 44 settings declares a default in
 * `package.json`, so `get()` hands back that default for keys the user has
 * never touched — and a settings layer that always has a value would silently
 * outrank `zer0.json` for every key it names. `explicit()` below reads only the
 * values a human actually set (folder → workspace → global), leaving the rest
 * absent so the file layer, and then the defaults, can win.
 *
 * Nothing here is cached. `currentConfig()` re-reads the settings and re-parses
 * `zer0.json` on every call, which is what makes "flip a setting and the next
 * publish gate sees it" true without a window reload. The file is a few
 * kilobytes and the call sites are user-driven, so the cost is a rounding
 * error next to the class of bug caching would buy.
 *
 * Every function that touches a folder takes an optional `scope`, and every one
 * of them behaves exactly as it did with no argument when none is given. That
 * is the seam multi-root support (decision D-B) is built on: the shell will
 * install an `ActiveFolderResolver` that answers "which folder is this call
 * about?", and until it does the answer stays `workspaceFolders[0]`.
 */

import * as fs from 'node:fs';
import * as fsp from 'node:fs/promises';
import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  DEFAULT_CONFIG_FILE,
  PANEL_SECTION_IDS,
  readJsonc,
  resolveConfig,
  type DashboardSorting,
  type DashboardView,
  type LogLevel,
  type PanelSectionId,
  type Zer0Config,
  type Zer0Settings,
} from './core';
import { describeError, log } from './logger';

/** The settings namespace. Everything the extension contributes lives under it. */
export const CONFIG_SECTION = 'zer0Cms';

/**
 * Where a project config may live, in search order. The first entry is the
 * value of `zer0Cms.configFile`; these two are the conventional fallbacks and
 * match the `workspaceContains` activation events in `package.json`.
 */
export const CONFIG_FILE_CANDIDATES: readonly string[] = [DEFAULT_CONFIG_FILE, '.zer0/config.json'];

/**
 * Every setting this extension contributes, fully qualified, in the order
 * `package.json` declares them across its eleven titled sections.
 *
 * Fully qualified because that is how VS Code, the manifest and
 * `capabilities.untrustedWorkspaces.restrictedConfigurations` all spell them,
 * and because the gate test compares this list to the manifest's own keys —
 * two lists that must agree, with a failing test rather than a shrug when they
 * do not. `explicit()` and `updateSetting()` take the suffix instead: strip
 * `CONFIG_SECTION + '.'`.
 */
export const SETTING_IDS: readonly string[] = [
  // Project file
  'zer0Cms.configFile',
  // Panel
  'zer0Cms.panel.openOnSupportedFile',
  'zer0Cms.panel.freeformTaxonomy',
  'zer0Cms.panel.sections',
  // Dashboard
  'zer0Cms.dashboard.openOnStartup',
  'zer0Cms.dashboard.defaultView',
  'zer0Cms.dashboard.defaultSorting',
  'zer0Cms.dashboard.pageSize',
  'zer0Cms.dashboard.cardFields',
  // Content
  'zer0Cms.content.autoUpdateModifiedDate',
  'zer0Cms.content.preserveCasing',
  'zer0Cms.content.defaultFileType',
  'zer0Cms.content.supportedFileTypes',
  'zer0Cms.content.publicFolder',
  // Dates
  'zer0Cms.date.format',
  'zer0Cms.date.timezone',
  // SEO and validation
  'zer0Cms.seo.enabled',
  'zer0Cms.validation.enabled',
  // Governance
  'zer0Cms.governance.enabled',
  'zer0Cms.governance.draftsFolder',
  'zer0Cms.governance.ledgerPath',
  'zer0Cms.governance.acceptStatuses',
  'zer0Cms.governance.publishAllow',
  'zer0Cms.governance.bannedPatternsFile',
  'zer0Cms.governance.target',
  // Content engine
  'zer0Cms.cms.root',
  'zer0Cms.cms.pythonPath',
  'zer0Cms.cms.engineScript',
  'zer0Cms.cms.normalizerScript',
  'zer0Cms.cms.contentDirs',
  'zer0Cms.cms.aiConfigPath',
  'zer0Cms.cms.verifyCommand',
  // AI agent
  'zer0Cms.agent.enabled',
  'zer0Cms.agent.model',
  'zer0Cms.agent.maxTurns',
  'zer0Cms.agent.permissionMode',
  // Fleet
  'zer0Cms.fleet.enabled',
  'zer0Cms.fleet.manifestPath',
  'zer0Cms.fleet.dispatchAllow',
  'zer0Cms.fleet.scaffoldAllow',
  'zer0Cms.fleet.roster',
  'zer0Cms.fleet.hub',
  'zer0Cms.fleet.gitfactoryUrl',
  // Logging
  'zer0Cms.logging.level',
];

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------

/**
 * Answers "which folder is this call about?".
 *
 * The default below is today's behaviour, unchanged: the folder that owns the
 * scope when the scope names one, and otherwise the first workspace folder.
 * A multi-root shell replaces it with one that knows about the *active* site,
 * so `currentConfig()` with no argument stops meaning "folder zero" and starts
 * meaning "the site the person is looking at" — without a single call site
 * having to pass anything.
 */
export type ActiveFolderResolver = (
  scope?: vscode.ConfigurationScope,
) => vscode.WorkspaceFolder | undefined;

/** The `uri` every `ConfigurationScope` variant either is or carries. */
function scopeUri(scope: vscode.ConfigurationScope | undefined): vscode.Uri | undefined {
  if (scope === undefined || scope === null) {
    return undefined;
  }
  if (scope instanceof vscode.Uri) {
    return scope;
  }
  // `WorkspaceFolder`, `TextDocument` and `{ uri?, languageId }` all expose it.
  return (scope as { uri?: vscode.Uri }).uri;
}

function defaultActiveFolderResolver(
  scope?: vscode.ConfigurationScope,
): vscode.WorkspaceFolder | undefined {
  const folders = vscode.workspace.workspaceFolders;
  if (folders === undefined || folders.length === 0) {
    return undefined;
  }
  const uri = scopeUri(scope);
  if (uri !== undefined) {
    const owner = vscode.workspace.getWorkspaceFolder(uri);
    if (owner !== undefined) {
      return owner;
    }
  }
  return folders[0];
}

let activeFolderResolver: ActiveFolderResolver = defaultActiveFolderResolver;

/**
 * Install the shell's resolver, or `null` to restore the default. Called once
 * at activation; a test that installs one must restore it, because this is
 * module state and it outlives the object that set it.
 */
export function setActiveFolderResolver(resolver: ActiveFolderResolver | null): void {
  activeFolderResolver = resolver ?? defaultActiveFolderResolver;
}

/** The folder this call is about, or `undefined` in a folderless window. */
export function workspaceFolder(
  scope?: vscode.ConfigurationScope,
): vscode.WorkspaceFolder | undefined {
  return activeFolderResolver(scope);
}

/** Absolute path of that folder's root, or `undefined`. */
export function workspaceRoot(scope?: vscode.ConfigurationScope): string | undefined {
  return workspaceFolder(scope)?.uri.fsPath;
}

/**
 * `true` when this window is a trusted workspace.
 *
 * The gate, not the courtesy. `capabilities.untrustedWorkspaces` in
 * `package.json` makes VS Code ignore the *workspace-scoped* value of every
 * restricted setting in an untrusted folder — but a value a person put in their
 * **user** settings still arrives, and a `when` clause is a hint to the UI, not
 * an enforcement point. Anything that spawns a process, arms a write, or hands
 * a path to an agent re-asks this function in the same breath it acts.
 */
export function workspaceTrusted(): boolean {
  return vscode.workspace.isTrusted;
}

/**
 * `true` when there is somewhere to read content from. Every surface that
 * touches the disk checks this first; the core's `requireWorkspaceRoot(cfg)`
 * is the version that throws a message worth showing a user.
 */
export function hasWorkspace(): boolean {
  return workspaceRoot() !== undefined;
}

// ---------------------------------------------------------------------------
// The settings layer
// ---------------------------------------------------------------------------

/**
 * The value a human set, or `undefined`. Folder scope beats workspace scope
 * beats user scope; the `package.json` default is deliberately ignored,
 * because that is the third layer's job, not the first's.
 */
function explicit<T>(config: vscode.WorkspaceConfiguration, key: string): T | undefined {
  const found = config.inspect<T>(key);
  if (found === undefined) {
    return undefined;
  }
  if (found.workspaceFolderValue !== undefined) {
    return found.workspaceFolderValue;
  }
  if (found.workspaceValue !== undefined) {
    return found.workspaceValue;
  }
  return found.globalValue;
}

function explicitEnum<T extends string>(
  config: vscode.WorkspaceConfiguration,
  key: string,
  allowed: readonly T[],
): T | undefined {
  const raw = explicit<string>(config, key);
  return raw !== undefined && (allowed as readonly string[]).includes(raw) ? (raw as T) : undefined;
}

function explicitSections(config: vscode.WorkspaceConfiguration): PanelSectionId[] | undefined {
  const raw = explicit<string[]>(config, 'panel.sections');
  if (raw === undefined) {
    return undefined;
  }
  // An unknown id is dropped rather than smuggled into the panel's route
  // table, where it would render as an empty section with no explanation.
  return raw.filter((id): id is PanelSectionId =>
    (PANEL_SECTION_IDS as readonly string[]).includes(id),
  );
}

/**
 * Every `zer0Cms.*` setting, shaped as the core's settings layer.
 *
 * Only the two-layer ids appear here — 41 of the 44 `package.json` contributes.
 * The other three (`governance.publishAllow`, `fleet.dispatchAllow`,
 * `fleet.scaffoldAllow`) never enter the merged configuration at all; see the
 * settings-only readers below. The project
 * *schema* — content folders, content types, field groups, taxonomy,
 * placeholders, SEO thresholds, the slug template, the front-matter dialect —
 * has no settings at all and is read exclusively from `zer0.json`. That split
 * is why 89 upstream settings became 44.
 */
export function settingsSnapshot(scope?: vscode.ConfigurationScope): Zer0Settings {
  const c = vscode.workspace.getConfiguration(CONFIG_SECTION, scope);
  return {
    configFile: explicit<string>(c, 'configFile'),
    panel: {
      openOnSupportedFile: explicit<boolean>(c, 'panel.openOnSupportedFile'),
      freeformTaxonomy: explicit<boolean>(c, 'panel.freeformTaxonomy'),
      sections: explicitSections(c),
    },
    dashboard: {
      openOnStartup: explicit<boolean>(c, 'dashboard.openOnStartup'),
      defaultView: explicitEnum<DashboardView>(c, 'dashboard.defaultView', [
        'grid',
        'list',
        'structure',
      ]),
      defaultSorting: explicitEnum<DashboardSorting>(c, 'dashboard.defaultSorting', [
        'LastModifiedDesc',
        'LastModifiedAsc',
        'FileNameAsc',
        'FileNameDesc',
        'PublishedDesc',
        'PublishedAsc',
      ]),
      pageSize: explicit<number>(c, 'dashboard.pageSize'),
      cardFields: explicit<Record<string, boolean>>(c, 'dashboard.cardFields'),
    },
    content: {
      autoUpdateModifiedDate: explicit<boolean>(c, 'content.autoUpdateModifiedDate'),
      preserveCasing: explicit<boolean>(c, 'content.preserveCasing'),
      defaultFileType: explicit<string>(c, 'content.defaultFileType'),
      supportedFileTypes: explicit<string[]>(c, 'content.supportedFileTypes'),
      publicFolder: explicit<string>(c, 'content.publicFolder'),
    },
    date: {
      format: explicit<string>(c, 'date.format'),
      timezone: explicit<string>(c, 'date.timezone'),
    },
    seo: { enabled: explicit<boolean>(c, 'seo.enabled') },
    validation: { enabled: explicit<boolean>(c, 'validation.enabled') },
    governance: {
      enabled: explicit<boolean>(c, 'governance.enabled'),
      draftsFolder: explicit<string>(c, 'governance.draftsFolder'),
      ledgerPath: explicit<string>(c, 'governance.ledgerPath'),
      acceptStatuses: explicit<string[]>(c, 'governance.acceptStatuses'),
      publishAllow: explicit<boolean>(c, 'governance.publishAllow'),
      bannedPatternsFile: explicit<string>(c, 'governance.bannedPatternsFile'),
      target: explicit<string>(c, 'governance.target'),
    },
    cms: {
      root: explicit<string>(c, 'cms.root'),
      // The setting is `pythonPath`; the domain calls it `python`. This line is
      // the whole of the mapping — do not rename either half without it.
      python: explicit<string>(c, 'cms.pythonPath'),
      engineScript: explicit<string>(c, 'cms.engineScript'),
      normalizerScript: explicit<string>(c, 'cms.normalizerScript'),
      contentDirs: explicit<string[]>(c, 'cms.contentDirs'),
      aiConfigPath: explicit<string>(c, 'cms.aiConfigPath'),
      verifyCommand: explicit<string>(c, 'cms.verifyCommand'),
    },
    agent: {
      enabled: explicit<boolean>(c, 'agent.enabled'),
      model: explicit<string>(c, 'agent.model'),
      maxTurns: explicit<number>(c, 'agent.maxTurns'),
      permissionMode: explicitEnum<string>(c, 'agent.permissionMode', [
        'default',
        'acceptEdits',
        'plan',
      ]),
    },
    fleet: {
      enabled: explicit<boolean>(c, 'fleet.enabled'),
      manifestPath: explicit<string>(c, 'fleet.manifestPath'),
      roster: explicit<string[]>(c, 'fleet.roster'),
      hub: explicit<string>(c, 'fleet.hub'),
      gitfactoryUrl: explicit<string>(c, 'fleet.gitfactoryUrl'),
      // `fleet.dispatchAllow` and `fleet.scaffoldAllow` are deliberately not
      // here: neither ever enters the merged configuration. See
      // `settingsFleetDispatchAllow` / `settingsFleetScaffoldAllow`.
    },
    logging: { level: explicitEnum<LogLevel>(c, 'logging.level', ['error', 'warn', 'info', 'verbose']) },
  };
}

/**
 * `zer0Cms.governance.publishAllow` **as a human set it**, or `undefined`.
 *
 * The merged value (`currentConfig().governance.publishAllow`) is the right one
 * for every in-editor gate: a project that says `publishAllow: true` in its
 * `zer0.json` is a project whose owner typed that, and the panel's publish
 * button is behind a modal a person has to answer.
 *
 * Arming the bundled MCP server is different. `ZER0_CMS_MCP_ALLOW_PUBLISH` is
 * the gate `src/mcp/tools.ts` describes as the one a `zer0.json` cannot reach,
 * and on the other side of it `zer0_publish`'s second gate is `confirm: true`
 * — a value the model supplies to itself. If the flag could be turned on by a
 * file, cloning a repository and opening it in an editor with an agent
 * connected would be enough to publish, with no human act anywhere in the
 * chain. So this reads the settings layer only: user, workspace or folder
 * scope, which are the three places a person, not a repository, writes.
 *
 * An untrusted workspace answers `undefined` before any of that, which is what
 * puts `workspaceTrusted()` inside `mcpPublishAllowed()` — this function is the
 * only thing it consults that can say yes. `restrictedConfigurations` alone
 * would not do it: VS Code drops the *workspace-scoped* value in an untrusted
 * folder, but a `true` sitting in someone's user settings still arrives, and it
 * was never meant as consent to publish from a repository they just cloned.
 */
export function settingsPublishAllow(scope?: vscode.ConfigurationScope): boolean | undefined {
  if (!workspaceTrusted()) {
    return undefined;
  }
  return explicit<boolean>(
    vscode.workspace.getConfiguration(CONFIG_SECTION, scope),
    'governance.publishAllow',
  );
}

/**
 * `zer0Cms.fleet.dispatchAllow` **as a human set it**, else `false`.
 *
 * The master gate for the Fleet console's two privileged actions — flipping a
 * lane's `*_ENABLED` variable and dispatching a lane — and the one fleet key
 * with no `zer0.json` twin and no place in `Zer0Config`. The reasoning is
 * `settingsPublishAllow`'s: on the other side of this gate is a write to
 * another system that a cloned repository must not be able to authorise. A
 * `fleet.manifest.yml` and a `zer0.json` both arrive with the clone; only the
 * three settings scopes are written by the person sitting at the editor.
 * `evaluateFleetGates` reads this value and nothing overrides it.
 */
export function settingsFleetDispatchAllow(scope?: vscode.ConfigurationScope): boolean {
  if (!workspaceTrusted()) {
    return false;
  }
  return (
    explicit<boolean>(vscode.workspace.getConfiguration(CONFIG_SECTION, scope), 'fleet.dispatchAllow') ===
    true
  );
}

/**
 * `zer0Cms.fleet.scaffoldAllow` **as a human set it**, else `false`.
 *
 * The master gate for generating a lane into the open folder — a workflow file,
 * an agent file, a skill stub and a line in the manifest. `dispatchAllow`'s
 * reasoning, pointed the other way: that gate guards a write to GitHub, this
 * one guards a write to the working tree, and a repository that could arm it
 * would be a repository that writes its own next workflow. Settings layer only,
 * trusted workspaces only, and the `*_ENABLED` variable is never created by the
 * same action that writes the files.
 */
export function settingsFleetScaffoldAllow(scope?: vscode.ConfigurationScope): boolean {
  if (!workspaceTrusted()) {
    return false;
  }
  return (
    explicit<boolean>(vscode.workspace.getConfiguration(CONFIG_SECTION, scope), 'fleet.scaffoldAllow') ===
    true
  );
}

/**
 * `zer0Cms.fleet.roster` **as a human set it**, else `[]`.
 *
 * Unlike the two gates above this key is genuinely two-layer — a project may
 * name its own siblings in `zer0.json`, and `currentConfig().fleet.roster` is
 * the merged answer. This reader exists because the roster builder has to know
 * which entries came from a person's settings and which came from a file, and
 * it reports that provenance in the console rather than flattening it away.
 */
export function settingsFleetRoster(scope?: vscode.ConfigurationScope): string[] {
  return (
    explicit<string[]>(vscode.workspace.getConfiguration(CONFIG_SECTION, scope), 'fleet.roster') ?? []
  );
}

/**
 * Write a single setting. Used by the dashboard's settings page.
 *
 * `id` is the suffix (`governance.target`), not the qualified id. `scope`
 * selects the folder for a `resource`-scoped key in a multi-root window; with
 * none, the write lands where it always has.
 */
export function updateSetting(
  id: string,
  value: unknown,
  target: vscode.ConfigurationTarget = vscode.ConfigurationTarget.Workspace,
  scope?: vscode.ConfigurationScope,
): Thenable<void> {
  return vscode.workspace.getConfiguration(CONFIG_SECTION, scope).update(id, value, target);
}

// ---------------------------------------------------------------------------
// The file layer
// ---------------------------------------------------------------------------

function toPosix(value: string): string {
  return value.split(path.sep).join('/');
}

/**
 * Workspace-relative path of the project config file *in use* — the configured
 * name when it exists, else the first conventional fallback that exists, else
 * the configured name as the place `zer0Cms.init` would create.
 *
 * Always relative and always POSIX, because it is stored in `Zer0Config`,
 * handed to the MCP server as `ZER0_CMS_CONFIG`, and shown to people.
 */
export function configFileName(scope?: vscode.ConfigurationScope): string {
  const configured =
    explicit<string>(vscode.workspace.getConfiguration(CONFIG_SECTION, scope), 'configFile')?.trim() ??
    '';
  const root = workspaceRoot(scope);
  const preferred = configured.length > 0 ? toPosix(configured) : DEFAULT_CONFIG_FILE;
  if (root === undefined) {
    return preferred;
  }
  for (const candidate of [preferred, ...CONFIG_FILE_CANDIDATES]) {
    if (fs.existsSync(path.resolve(root, candidate))) {
      return toPosix(candidate);
    }
  }
  return preferred;
}

/** Absolute path of the project config file in use — existing or not. */
export function configFilePath(scope?: vscode.ConfigurationScope): string | undefined {
  const root = workspaceRoot(scope);
  return root === undefined ? undefined : path.resolve(root, configFileName(scope));
}

/**
 * `true` when this workspace has a project config on disk. Drives the
 * `zer0Cms:enabled` context key and, through it, the "Initialize project"
 * welcome view.
 */
export function hasProjectConfig(scope?: vscode.ConfigurationScope): boolean {
  const target = configFilePath(scope);
  return target !== undefined && fs.existsSync(target);
}

/**
 * The raw `zer0.json` object. A missing file is `{}`; an unparseable one is
 * `{}` plus a log line naming the parse error — the panel must still render
 * while someone is halfway through typing a comma.
 */
export function readConfigFileJson(scope?: vscode.ConfigurationScope): Record<string, unknown> {
  const target = configFilePath(scope);
  if (target === undefined) {
    return {};
  }
  let text: string;
  try {
    text = fs.readFileSync(target, 'utf8');
  } catch {
    // No config file yet. That is the normal state of a fresh workspace, and
    // `hasProjectConfig()` is how a caller asks about it deliberately.
    return {};
  }
  try {
    const parsed = readJsonc<unknown>(text);
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    log.warn(`${configFileName(scope)} is not a JSON object; ignoring it.`);
  } catch (error) {
    log.warn(`${configFileName(scope)}: ${describeError(error)}`);
  }
  return {};
}

/** Overwrite `zer0.json` with `json`, pretty-printed the way people write it. */
export async function writeConfigFileJson(
  json: Record<string, unknown>,
  scope?: vscode.ConfigurationScope,
): Promise<string> {
  const target = configFilePath(scope);
  if (target === undefined) {
    throw new Error('zer0-CMS: open a workspace folder before writing a project config.');
  }
  await fsp.mkdir(path.dirname(target), { recursive: true });
  // Deliberately not an atomic write: this file is edited by humans and open in
  // their editor. A rename underneath an open document is how you lose their
  // unsaved changes.
  await fsp.writeFile(target, `${JSON.stringify(json, null, 2)}\n`, 'utf8');
  return target;
}

/** Read-modify-write `zer0.json`. The mutator sees a plain object. */
export async function updateConfigFileJson(
  mutate: (json: Record<string, unknown>) => void,
  scope?: vscode.ConfigurationScope,
): Promise<string> {
  const json = readConfigFileJson(scope);
  mutate(json);
  return writeConfigFileJson(json, scope);
}

// ---------------------------------------------------------------------------
// The merge
// ---------------------------------------------------------------------------

/**
 * The resolved configuration, read fresh.
 *
 * Never throws, and never returns a partial object. In a folderless window
 * `workspaceRoot` is `''` — the shape every consumer expects, with the core's
 * `requireWorkspaceRoot(cfg)` / the `noWorkspace` gate as the places that turn
 * that emptiness into a message.
 */
export function currentConfig(scope?: vscode.ConfigurationScope): Zer0Config {
  const root = workspaceRoot(scope) ?? '';
  const settings = settingsSnapshot(scope);
  // Pin `configFile` to the file we actually resolved, so `configPath(cfg)`
  // and the MCP server's `ZER0_CMS_CONFIG` name the same bytes this call read.
  settings.configFile = configFileName(scope);
  return resolveConfig(root, readConfigFileJson(scope), settings);
}

// ---------------------------------------------------------------------------
// Change notification
// ---------------------------------------------------------------------------

/** `true` when a configuration change touched anything in our namespace. */
export function affectsUs(event: vscode.ConfigurationChangeEvent): boolean {
  return event.affectsConfiguration(CONFIG_SECTION);
}

/**
 * Fire when a `zer0Cms.*` setting changes. The project *file* is not watched
 * here — `WorkspaceStore` owns that watcher, because a change to it also
 * changes which folders need watching.
 */
export function onConfigChange(listener: () => void): vscode.Disposable {
  return vscode.workspace.onDidChangeConfiguration((event) => {
    if (affectsUs(event)) {
      listener();
    }
  });
}
