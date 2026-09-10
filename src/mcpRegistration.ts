/**
 * Registers the bundled MCP server with VS Code, so Copilot agent mode — and
 * anything else that speaks MCP through the editor — gets the zer0-CMS tools
 * without the user hand-editing a JSON file. The tool list is whatever
 * `src/mcp/tools.ts` exports and it grows every release; `tools/list` is the
 * only honest count, which is why one is not written down here.
 *
 * **The two phases are the security design, not a formality.**
 *
 * `provideMcpServerDefinitions` is called *eagerly*, whenever the editor feels
 * like enumerating servers, and the API documentation is explicit that it must
 * not take actions requiring user interaction. Whatever it returns is a static
 * description that the editor may cache and show. So it returns a definition
 * with an **empty `env`**: a command, an argv, a cwd, a version. Nothing else.
 *
 * `resolveMcpServerDefinition` is called at *start* time, once, for a server
 * that is about to run. Only there are the publish-allow flag and the secret
 * read, and only there is `env` populated. A secret therefore never exists in a
 * cached definition, never in a setting, never in `.vscode/mcp.json`, and never
 * in a log line — the log records that a value was injected, not the value.
 *
 * The publish flag comes from the **settings** layer, never from `zer0.json`.
 * `zer0.json` ships with the repository; the environment variable it would set
 * is the one thing `src/mcp/tools.ts` promises a `zer0.json` cannot reach, and
 * the only gate past it is `confirm: true`, which an agent supplies to itself.
 * See `publishAllowed()`.
 *
 * The publish flag has one more property worth stating: when publishing is off,
 * `ZER0_CMS_MCP_ALLOW_PUBLISH` is set to `null`, which the API defines as
 * *remove this variable from the child's environment*. Not `"0"` — a string
 * that some future parser might read as present — and not merely omitted, which
 * would let an inherited `ZER0_CMS_MCP_ALLOW_PUBLISH=1` in the extension host's
 * own environment leak through into a server that is not allowed to publish.
 *
 * **Two more variables follow the same pattern exactly** (decision D13).
 * `ZER0_CMS_MCP_ALLOW_EXEC` carries Workspace Trust across the process
 * boundary: the server cannot ask `vscode` anything, so `zer0_contract` — the
 * one tool that starts a process — refuses unless it was told, and it is told
 * only in a trusted workspace. `ZER0_CMS_PYTHON` pins the *interpreter* to the
 * settings layer, because choosing which binary runs is not a decision a
 * `zer0.json` that arrived with a clone gets to make. Both are `null` when they
 * do not apply, and both are read at resolve time and nowhere else.
 *
 * **And in an untrusted workspace there is no server at all.**
 * `provideMcpServerDefinitions` returns `[]`, because a registered server would
 * inherit this extension's whole reach over the folder — the trust decision has
 * to happen before an agent is offered the tools, not inside each one.
 *
 * **One server per site, and the two phases survive it.** A multi-root window
 * holds many repositories, and a single server rooted in folder zero could only
 * ever answer for one of them — so the provider returns one definition per
 * *configured* folder (plus the active one, whether or not it carries a project
 * config, which is what keeps a fresh single-folder workspace working exactly
 * as it always did). Each definition names its own `cwd` and carries the folder
 * in its label, and each still carries an **empty `env`**.
 *
 * `resolveMcpServerDefinition` then resolves the folder back *from the server's
 * own `cwd`* and reads every flag scoped to it. That is what makes
 * `zer0Cms.governance.publishAllow` — a `resource`-scoped setting — mean what
 * it says: arming publishing for the one repository you operate does not arm it
 * for the other eleven folders that happen to be open in the same window. The
 * rule is unchanged in every other respect: settings layer only, trusted
 * workspaces only, read at start time and nowhere else.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  configFileName,
  CONFIG_SECTION,
  currentConfig,
  hasProjectConfig,
  settingsPublishAllow,
  settingsSnapshot,
  workspaceFolder,
  workspaceTrusted,
} from './config';
import { describeError, log } from './logger';
import { notifyError, notifyInfo } from './uiState';

/** Must match `contributes.mcpServerDefinitionProviders[0].id` in package.json. */
export const MCP_PROVIDER_ID = 'zer0Cms.mcp';

/** The label shown in the editor's MCP server list. */
export const MCP_SERVER_LABEL = 'zer0-CMS';

/** The server id written into `.vscode/mcp.json` by the fallback command. */
export const MCP_WORKSPACE_SERVER_ID = 'zer0-cms';

/** Path of the bundled server, relative to the extension install directory. */
export const MCP_SERVER_RELATIVE_PATH = 'dist/mcp-server.js';

/**
 * Keys in `context.secrets`. Nothing else in this extension may read them, and
 * nothing at all may write them to disk, a setting or the output channel.
 *
 * `anthropicApiKey` is optional everywhere: the twelve MCP tools never call a
 * model, and the agent layer falls back to the ambient environment. It exists
 * so that a user who prefers SecretStorage over a shell profile has one, and so
 * the two-phase contract above has something real to protect.
 */
export const SECRET_KEYS = {
  anthropicApiKey: 'zer0Cms.anthropicApiKey',
} as const;

/** The extension's version, read defensively out of the manifest. */
function extensionVersion(context: vscode.ExtensionContext): string {
  const manifest: unknown = context.extension.packageJSON;
  if (typeof manifest === 'object' && manifest !== null && 'version' in manifest) {
    const version = (manifest as { version: unknown }).version;
    if (typeof version === 'string') {
      return version;
    }
  }
  return '0.0.0';
}

/**
 * Whether an MCP client may publish. Two switches, read from two layers on
 * purpose.
 *
 * `governance.enabled` is the feature, and the fully merged value answers it: a
 * `zer0.json` that turns governance *off* is a restriction, and honouring a
 * restriction from the project file is always safe.
 *
 * `governance.publishAllow` is read from the **settings layer only** —
 * `settingsPublishAllow()`, not `currentConfig()`. `zer0.json` is a file in the
 * repository. Reading the merged value here meant that cloning a repo whose
 * `zer0.json` said `{"governance":{"publishAllow":true}}` armed
 * `ZER0_CMS_MCP_ALLOW_PUBLISH` on the bundled server, and the only remaining
 * gate on `zer0_publish` is `confirm: true` — which an agent passes to itself.
 * A file that arrives with the source tree is not a human turning publishing
 * on, and this is the gate `src/mcp/tools.ts` documents as the one a `zer0.json`
 * cannot reach. The in-editor gates keep using the merged value: they are
 * behind a modal that a person answers.
 */
export function mcpPublishAllowed(scope?: vscode.ConfigurationScope): boolean {
  if (!currentConfig(scope).governance.enabled) {
    return false;
  }
  if (settingsPublishAllow(scope) === true) {
    return true;
  }
  if (currentConfig(scope).governance.publishAllow) {
    log.info(
      `${configFileName(scope)} enables governance.publishAllow, but the MCP server's publish flag ` +
        'comes from the "zer0Cms.governance.publishAllow" setting only — a file in the ' +
        'repository cannot arm an agent to publish. Set it in your settings to allow it.',
    );
  }
  return false;
}

/**
 * Whether the bundled server may start a process — `zer0_contract`'s gate.
 *
 * Workspace Trust and nothing else. There is deliberately no setting here: a
 * fourth switch to forget would be worse than the one decision VS Code already
 * asks a person to make about a folder, and the tool's own refusal names the
 * variable rather than a preference nobody would find. The value of the gate is
 * what it denies: a server started by hand, or from a committed
 * `.vscode/mcp.json`, gets no `env` at all and therefore never spawns.
 */
export function mcpExecAllowed(): boolean {
  return workspaceTrusted();
}

/**
 * The interpreter **as a human set it**, or `undefined`.
 *
 * `settingsPublishAllow`'s reasoning pointed at `cms.pythonPath`. A `zer0.json`
 * ships with the repository and can name any binary on the machine; the three
 * settings scopes are written by the person sitting at the editor. When nobody
 * set one, nothing is injected and the server resolves the interpreter through
 * its normal layers — behind `ZER0_CMS_MCP_ALLOW_EXEC`, which is the gate that
 * decides whether anything runs at all.
 */
export function mcpPythonPath(scope?: vscode.ConfigurationScope): string | undefined {
  if (!workspaceTrusted()) {
    return undefined;
  }
  const python = settingsSnapshot(scope).cms?.python?.trim();
  return python === undefined || python === '' ? undefined : python;
}

/**
 * The folders that get their own server, in workspace order.
 *
 * Every folder that carries a project config, plus the active site whether or
 * not it does. The second half is what keeps a fresh, unconfigured, one-folder
 * workspace working exactly as it did before multi-root: `zer0.json` has always
 * been optional (decision D9), and refusing a server because a folder has not
 * been initialised yet would be a regression dressed up as a filter.
 *
 * The first half is what makes a twelve-folder window usable: six of this
 * fleet's folders are sites this extension knows about and six are not, and
 * offering a server for all twelve would bury the ones that matter.
 */
export function mcpFolders(): vscode.WorkspaceFolder[] {
  const folders = vscode.workspace.workspaceFolders ?? [];
  const active = workspaceFolder();
  const chosen = folders.filter(
    (folder) => hasProjectConfig(folder) || folder.uri.toString() === active?.uri.toString(),
  );
  return chosen.length > 0 ? chosen : active === undefined ? [] : [active];
}

/**
 * The definitions this window offers — phase one, and nothing but data.
 *
 * Extracted from the provider so it can be called from a test without an
 * `ExtensionContext`: "two folders, two servers, two different `cwd`s" is the
 * whole of the multi-root MCP contract, and it should not need an extension
 * host object to ask about. The provider is a one-line call to this.
 *
 * Every definition carries `env: {}`. That is the two-phase rule, and it does
 * not bend for multi-root: no flag, no secret and no per-folder decision is
 * read here, because whatever this returns may be cached and shown.
 */
export function mcpServerDefinitions(
  serverPath: string,
  version: string,
): vscode.McpStdioServerDefinition[] {
  if (!vscode.workspace.isTrusted) {
    // No server, rather than a server that refuses each tool one at a time.
    // Whatever this returns may be cached and shown, so "offered but inert"
    // would be a menu entry promising something the folder is not allowed to
    // do; `onDidGrantWorkspaceTrust` re-fires and the real list appears the
    // moment the person says yes.
    log.info('MCP server not offered: this workspace is not trusted');
    return [];
  }
  const folders = mcpFolders();
  if (folders.length === 0) {
    // The server reads the workspace it is rooted in. Without one there is
    // nothing to serve, and offering a server that would answer every tool
    // with "no workspace" is worse than offering none.
    return [];
  }
  const many = (vscode.workspace.workspaceFolders ?? []).length > 1;
  return folders.map((folder) => {
    const server = new vscode.McpStdioServerDefinition(
      // The folder is in the label only when there is more than one, so a
      // single-root window's server keeps the name it has always had.
      many ? `${MCP_SERVER_LABEL} · ${folder.name}` : MCP_SERVER_LABEL,
      // The editor's own Node.js: no assumption about what is on PATH.
      process.execPath,
      [serverPath],
      {}, // ← empty on purpose. See the header.
      version,
    );
    server.cwd = folder.uri;
    return server;
  });
}

/** The configuration scope a server definition speaks for: its own `cwd`. */
function scopeOf(server: vscode.McpStdioServerDefinition): vscode.ConfigurationScope | undefined {
  if (server.cwd === undefined) {
    return undefined;
  }
  return vscode.workspace.getWorkspaceFolder(server.cwd) ?? server.cwd;
}

/**
 * @param onSitesChanged fires when the site registry changes — a folder opened
 *   or closed, or the active site moved. Both can change *which* folders get a
 *   server (`mcpFolders()` includes the active one whether or not it is
 *   configured), so the editor is asked to re-enumerate. It is optional so a
 *   shell with no registry — and every existing call site — still compiles.
 */
export function registerMcpProvider(
  context: vscode.ExtensionContext,
  onSitesChanged?: vscode.Event<void>,
): void {
  const didChange = new vscode.EventEmitter<void>();

  /** The folder set the editor was last told about, so a no-op change is one. */
  let lastFolders = mcpFolders()
    .map((folder) => folder.uri.toString())
    .join('\u0000');

  const provider: vscode.McpServerDefinitionProvider<vscode.McpStdioServerDefinition> = {
    onDidChangeMcpServerDefinitions: didChange.event,

    provideMcpServerDefinitions: () =>
      mcpServerDefinitions(
        context.asAbsolutePath(MCP_SERVER_RELATIVE_PATH),
        extensionVersion(context),
      ),

    resolveMcpServerDefinition: async (server) => {
      // Start time. Secrets may be read *here* and nowhere else.
      //
      // The scope is the server's **own** `cwd` — the folder this definition
      // was created for, not whichever site happens to be active when the
      // editor decides to start it. Resolving it any other way would mean a
      // server rooted in folder B being armed by folder A's settings, which is
      // exactly the confusion a `resource`-scoped gate exists to prevent.
      const scope = scopeOf(server);
      const allow = mcpPublishAllowed(scope);
      const exec = mcpExecAllowed();
      const python = mcpPythonPath(scope);
      const apiKey = await context.secrets.get(SECRET_KEYS.anthropicApiKey);
      server.env = {
        // Which project file the server should read, relative to its cwd.
        ZER0_CMS_CONFIG: configFileName(scope),
        // `null` = remove the variable from the child environment entirely.
        ZER0_CMS_MCP_ALLOW_PUBLISH: allow ? '1' : null,
        ZER0_CMS_MCP_ALLOW_EXEC: exec ? '1' : null,
        ZER0_CMS_PYTHON: python ?? null,
        ANTHROPIC_API_KEY: apiKey ?? null,
      };
      log.info(
        `MCP server starting for ${server.cwd?.fsPath ?? '(no cwd)'} — ` +
          `publish ${allow ? 'ENABLED' : 'disabled'}, ` +
          `exec ${exec ? 'ENABLED' : 'disabled'}, ` +
          `interpreter ${python === undefined ? 'from the project layers' : 'pinned from settings'}, ` +
          `config ${configFileName(scope)}, api key ${apiKey === undefined ? 'absent' : 'injected'}`,
      );
      return server;
    },
  };

  context.subscriptions.push(
    didChange,
    // A change to any of these changes what a *running* server would be told,
    // so the editor is asked to re-resolve.
    context.secrets.onDidChange((event) => {
      if (event.key === SECRET_KEYS.anthropicApiKey) {
        didChange.fire();
      }
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      // Three sections change what a *running* server would be told:
      // `governance` (the publish flag), `cms` (the pinned interpreter and the
      // config file name), and `fleet` — whose master gates are settings-only
      // and whose scaffolding opt-in a later package injects here too.
      if (
        event.affectsConfiguration(`${CONFIG_SECTION}.governance`) ||
        event.affectsConfiguration(`${CONFIG_SECTION}.cms`) ||
        event.affectsConfiguration(`${CONFIG_SECTION}.fleet`)
      ) {
        didChange.fire();
      }
    }),
    // Granting trust turns an empty server list into a real one, and arms the
    // exec flag on a server that is already running. Trust cannot be revoked
    // without a window reload, so there is no matching "revoked" event.
    vscode.workspace.onDidGrantWorkspaceTrust(() => didChange.fire()),
    vscode.workspace.onDidChangeWorkspaceFolders(() => didChange.fire()),
    // The registry fires for a folder change, an active-site change **and**
    // every site's rebuild, which is far more often than the server list
    // actually changes — so this compares the list before asking the editor to
    // re-enumerate. A dozen watcher-driven rebuilds a minute must not become a
    // dozen MCP re-enumerations.
    ...(onSitesChanged === undefined
      ? []
      : [
          onSitesChanged(() => {
            const next = mcpFolders()
              .map((folder) => folder.uri.toString())
              .join('\u0000');
            if (next === lastFolders) {
              return;
            }
            lastFolders = next;
            didChange.fire();
          }),
        ]),
    vscode.lm.registerMcpServerDefinitionProvider(MCP_PROVIDER_ID, provider),
  );
}

/**
 * The fallback for MCP clients that are not this editor: write the server into
 * `.vscode/mcp.json`.
 *
 * This file gets an absolute path into the *versioned* extension install
 * directory, which breaks the next time the extension updates. That is why the
 * provider above is the primary mechanism and this is a command a user has to
 * ask for; the notification says so rather than leaving them to find out.
 *
 * Note what is **not** written: no `env`, no secret, no publish flag. A file
 * committed to a repository is the last place a publish opt-in belongs — a
 * client launched from it gets a read-and-draft server, which is the
 * doctrine-preferred shape anyway.
 */
export async function configureWorkspaceMcpJson(context: vscode.ExtensionContext): Promise<void> {
  const folder = workspaceFolder();
  if (folder === undefined) {
    void notifyError('open a workspace folder first.');
    return;
  }

  const target = vscode.Uri.joinPath(folder.uri, '.vscode', 'mcp.json');
  let existing: Record<string, unknown> = {};
  try {
    const bytes = await vscode.workspace.fs.readFile(target);
    const parsed: unknown = JSON.parse(Buffer.from(bytes).toString('utf8'));
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      existing = parsed as Record<string, unknown>;
    }
  } catch (error) {
    // No file yet, or one we cannot parse. Either way we are writing a fresh
    // `servers` map rather than refusing; the log says which it was.
    log.verbose(`.vscode/mcp.json not read: ${describeError(error)}`);
  }

  const servers =
    typeof existing.servers === 'object' && existing.servers !== null
      ? (existing.servers as Record<string, unknown>)
      : {};
  servers[MCP_WORKSPACE_SERVER_ID] = {
    type: 'stdio',
    command: 'node',
    args: [context.asAbsolutePath(MCP_SERVER_RELATIVE_PATH)],
  };
  existing.servers = servers;

  await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(folder.uri, '.vscode'));
  await vscode.workspace.fs.writeFile(
    target,
    Buffer.from(`${JSON.stringify(existing, null, 2)}\n`, 'utf8'),
  );

  const answer = await notifyInfo(
    `wrote ${path.join('.vscode', 'mcp.json')}. The server path points into the current ` +
      'extension install and breaks on update — prefer the built-in provider where it is supported. ' +
      'Publishing is not enabled for clients started from this file.',
    'Open',
  );
  if (answer === 'Open') {
    await vscode.window.showTextDocument(target);
  }
}
