/**
 * The command layer's barrel, plus the manifest that keeps it honest.
 *
 * `activate()` calls the six `register*` functions below in a fixed order —
 * governance first, because it returns the `GovernanceActions` that both
 * webview hosts are built around (decision D5).
 *
 * ### `ALL_COMMAND_IDS` is a cross-check, not a source of truth
 *
 * There are two places a command id has to appear — `contributes.commands` in
 * `package.json`, and a `registerCommand` call somewhere in this directory —
 * and nothing in TypeScript connects them. A contributed id with no handler is
 * a palette entry that does nothing; a handler with no contribution is a
 * command nobody can find. Both are silent.
 *
 * So the ids are listed here once, and `extension.test.ts` compares this list
 * against `package.json` *and* against `vscode.commands.getCommands()`. Adding
 * a command means touching three places on purpose, which is the point: the
 * third one fails loudly if you skip either of the others.
 *
 * The two `dashboard` ids are registered by `extension.ts` itself, next to the
 * panel it owns. They are listed here because the manifest is about the
 * contribution surface, not about which file happens to hold the closure.
 */

export {
  activeFilePath,
  isRegisteredFolder,
  openInEditor,
  register,
  registerProjectCommands,
  showReport,
  starterConfig,
  toFilePath,
} from './project';

export {
  activeArticle,
  panelBridgeInstalled,
  registerContentCommands,
  setPanelBridge,
  type ActiveArticle,
  type PanelBridge,
} from './content';

export { registerContentTypeCommands } from './contentType';

export {
  doApprove,
  doPublish,
  draftPathFrom,
  registerGovernanceCommands,
  type GovernanceActions,
} from './governance';

export { registerContractCommands } from './contract';

export {
  agentHostInstalled,
  registerAgentCommands,
  setAgentHost,
  type AgentHost,
} from './agent';

/**
 * Every id `package.json` contributes, without the `zer0Cms.` prefix, grouped
 * the way the manifest groups them. Thirty-four.
 */
export const ALL_COMMAND_IDS: readonly string[] = [
  // project — src/commands/project.ts (+ dashboard pair in src/extension.ts)
  'init',
  'dashboard',
  'dashboard.close',
  'refresh',
  'cache.clear',
  'showOutput',
  'registerFolder',
  'unregisterFolder',
  // content — src/commands/content.ts
  'createContent',
  'createContentInFolder',
  'generateSlug',
  'setLastModified',
  'insertImage',
  'openFile',
  'collapseSections',
  'focusTags',
  'focusCategories',
  // content types — src/commands/contentType.ts
  'contentType.generate',
  'contentType.addMissingFields',
  'contentType.set',
  // governance — src/commands/governance.ts
  'draft.new',
  'draft.review',
  'draft.approve',
  'draft.publish',
  'draft.guard',
  'draft.preview',
  // contract and distribution — src/commands/contract.ts
  'catering.worklist',
  'contract.run',
  'contract.normalizePreview',
  'contract.normalizeApply',
  // agent — src/commands/agent.ts
  'agent.open',
  'agent.start',
  'agent.stop',
  'mcp.writeWorkspaceConfig',
];

/** The fully qualified ids, for comparing against `getCommands()`. */
export const ALL_COMMAND_NAMES: readonly string[] = ALL_COMMAND_IDS.map((id) => `zer0Cms.${id}`);
