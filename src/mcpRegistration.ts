/**
 * Registers the bundled MCP server with VS Code, so Copilot agent mode — and
 * anything else that speaks MCP through the editor — gets the eight zer0-CMS
 * tools without the user hand-editing a JSON file.
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
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  configFileName,
  CONFIG_SECTION,
  currentConfig,
  settingsPublishAllow,
  workspaceFolder,
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
 * `anthropicApiKey` is optional everywhere: the eight MCP tools never call a
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
export function mcpPublishAllowed(): boolean {
  if (!currentConfig().governance.enabled) {
    return false;
  }
  if (settingsPublishAllow() === true) {
    return true;
  }
  if (currentConfig().governance.publishAllow) {
    log.info(
      `${configFileName()} enables governance.publishAllow, but the MCP server's publish flag ` +
        'comes from the "zer0Cms.governance.publishAllow" setting only — a file in the ' +
        'repository cannot arm an agent to publish. Set it in your settings to allow it.',
    );
  }
  return false;
}

export function registerMcpProvider(context: vscode.ExtensionContext): void {
  const didChange = new vscode.EventEmitter<void>();

  const provider: vscode.McpServerDefinitionProvider<vscode.McpStdioServerDefinition> = {
    onDidChangeMcpServerDefinitions: didChange.event,

    provideMcpServerDefinitions: () => {
      const folder = workspaceFolder();
      if (folder === undefined) {
        // The server reads the workspace it is rooted in. Without one there is
        // nothing to serve, and offering a server that would answer every tool
        // with "no workspace" is worse than offering none.
        return [];
      }
      const server = new vscode.McpStdioServerDefinition(
        MCP_SERVER_LABEL,
        // The editor's own Node.js: no assumption about what is on PATH.
        process.execPath,
        [context.asAbsolutePath(MCP_SERVER_RELATIVE_PATH)],
        {}, // ← empty on purpose. See the header.
        extensionVersion(context),
      );
      server.cwd = folder.uri;
      return [server];
    },

    resolveMcpServerDefinition: async (server) => {
      // Start time. Secrets may be read *here* and nowhere else.
      const allow = mcpPublishAllowed();
      const apiKey = await context.secrets.get(SECRET_KEYS.anthropicApiKey);
      server.env = {
        // Which project file the server should read, relative to its cwd.
        ZER0_CMS_CONFIG: configFileName(),
        // `null` = remove the variable from the child environment entirely.
        ZER0_CMS_MCP_ALLOW_PUBLISH: allow ? '1' : null,
        ANTHROPIC_API_KEY: apiKey ?? null,
      };
      log.info(
        `MCP server starting — publish ${allow ? 'ENABLED' : 'disabled'}, ` +
          `config ${configFileName()}, api key ${apiKey === undefined ? 'absent' : 'injected'}`,
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
      if (event.affectsConfiguration(`${CONFIG_SECTION}.governance`)) {
        didChange.fire();
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => didChange.fire()),
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
