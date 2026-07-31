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
 * `undefined`: every one of our 35 settings declares a default in
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

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------

/** The first workspace folder, or `undefined` in a folderless window. */
export function workspaceFolder(): vscode.WorkspaceFolder | undefined {
  return vscode.workspace.workspaceFolders?.[0];
}

/** Absolute path of the workspace root, or `undefined`. */
export function workspaceRoot(): string | undefined {
  return workspaceFolder()?.uri.fsPath;
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
 * Only the 35 ids that `package.json` contributes appear here. The project
 * *schema* — content folders, content types, field groups, taxonomy,
 * placeholders, SEO thresholds, the slug template, the front-matter dialect —
 * has no settings at all and is read exclusively from `zer0.json`. That split
 * is why 89 upstream settings became 35.
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
    logging: { level: explicitEnum<LogLevel>(c, 'logging.level', ['error', 'warn', 'info', 'verbose']) },
  };
}

/** Write a single setting. Used by the dashboard's settings page. */
export function updateSetting(
  id: string,
  value: unknown,
  target: vscode.ConfigurationTarget = vscode.ConfigurationTarget.Workspace,
): Thenable<void> {
  return vscode.workspace.getConfiguration(CONFIG_SECTION).update(id, value, target);
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
  const root = workspaceRoot();
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
  const root = workspaceRoot();
  return root === undefined ? undefined : path.resolve(root, configFileName(scope));
}

/**
 * `true` when this workspace has a project config on disk. Drives the
 * `zer0Cms:enabled` context key and, through it, the "Initialize project"
 * welcome view.
 */
export function hasProjectConfig(): boolean {
  const target = configFilePath();
  return target !== undefined && fs.existsSync(target);
}

/**
 * The raw `zer0.json` object. A missing file is `{}`; an unparseable one is
 * `{}` plus a log line naming the parse error — the panel must still render
 * while someone is halfway through typing a comma.
 */
export function readConfigFileJson(): Record<string, unknown> {
  const target = configFilePath();
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
    log.warn(`${configFileName()} is not a JSON object; ignoring it.`);
  } catch (error) {
    log.warn(`${configFileName()}: ${describeError(error)}`);
  }
  return {};
}

/** Overwrite `zer0.json` with `json`, pretty-printed the way people write it. */
export async function writeConfigFileJson(json: Record<string, unknown>): Promise<string> {
  const target = configFilePath();
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
): Promise<string> {
  const json = readConfigFileJson();
  mutate(json);
  return writeConfigFileJson(json);
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
  const root = workspaceRoot() ?? '';
  const settings = settingsSnapshot(scope);
  // Pin `configFile` to the file we actually resolved, so `configPath(cfg)`
  // and the MCP server's `ZER0_CMS_CONFIG` name the same bytes this call read.
  settings.configFile = configFileName(scope);
  return resolveConfig(root, readConfigFileJson(), settings);
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
