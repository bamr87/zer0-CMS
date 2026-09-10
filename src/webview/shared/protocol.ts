/**
 * The wire contract between the extension host and every webview.
 *
 * One file, both directions, all three surfaces (panel, dashboard, agent).
 * Host → webview is a single full `state` snapshot plus four genuinely
 * imperative messages; webview → host is six shapes whose only privileged
 * variant names a `CommandId` from a closed union. That closure is the
 * enforcement point for decision D5: a webview may name an intent and a
 * target, but it can never carry a payload that overrides a gate, and
 * `panelProvider`/`dashboardPanel` hold a `Record<CommandId, Handler>` so an
 * id outside the union is logged and dropped rather than dispatched.
 *
 * The state interfaces below are *view models*, not domain objects: they are
 * what the host has already resolved, flattened and made JSON-safe. They are
 * structurally compatible with the core types they are built from, so the
 * host can assign a `GuardFinding[]` straight into `guard` without a mapping
 * layer, but the webview never depends on a core module's internals.
 */

import type {
  AgentRecord,
  AuditFindingView,
  ContentRecord,
  DashboardView,
  Field,
  Freshness,
  HarnessJoin,
  PageEntry,
  PanelSectionId,
  SkillRecord,
  WorkflowRecord,
} from '../../core/shared/types';
// Type-only alias re-export: the field widgets in WP12 need the exact same
// `FmValue` the front-matter parser produces, and a second structural copy
// declared here would be a second name for one concept. `import type` is
// erased at build time, so this costs the webview bundle nothing.
import type { FmValue, FrontMatter } from '../../core/content/frontmatter';
import type { Messenger } from './messenger';

export type { FmValue, FrontMatter };
export type { ContentRecord, DashboardView, Field, Freshness, PageEntry, PanelSectionId };
export type { AgentRecord, AuditFindingView, HarnessJoin, SkillRecord, WorkflowRecord };

// ---------------------------------------------------------------------------
// Command ids — the closed intent vocabulary
// ---------------------------------------------------------------------------

/**
 * Every intent a webview button may name. The first group are the palette
 * commands (`zer0Cms.<id>`) verbatim; the trailing group are host operations
 * that exist only for a surface (settings writes, file operations, the agent
 * approval reply) and are registered as handlers rather than as commands.
 *
 * Adding a literal here does NOT grant it — the host still has to implement a
 * handler, and every gate is re-checked in the same function the palette calls.
 * Which is why the sixteen ids for PR2–PR5 can be declared now: a name with no
 * handler behind it is looked up, missed, logged and dropped, exactly like a
 * name that was never in the union at all. They are here so the packages that
 * build those surfaces compile against one vocabulary instead of six.
 */
export type CommandId =
  // project
  | 'init'
  | 'dashboard'
  | 'dashboard.close'
  | 'refresh'
  | 'cache.clear'
  | 'showOutput'
  | 'registerFolder'
  | 'unregisterFolder'
  // content
  | 'createContent'
  | 'createContentInFolder'
  | 'generateSlug'
  | 'setLastModified'
  | 'insertImage'
  | 'openFile'
  | 'collapseSections'
  | 'focusTags'
  | 'focusCategories'
  // content types
  | 'contentType.generate'
  | 'contentType.addMissingFields'
  | 'contentType.set'
  // governance
  | 'draft.new'
  | 'draft.review'
  | 'draft.approve'
  | 'draft.publish'
  | 'draft.guard'
  | 'draft.preview'
  // contract + distribution
  | 'catering.worklist'
  | 'contract.run'
  | 'contract.normalizePreview'
  | 'contract.normalizeApply'
  // agent
  | 'agent.open'
  | 'agent.start'
  | 'agent.stop'
  | 'mcp.writeWorkspaceConfig'
  // fleet
  | 'fleet.open'
  | 'fleet.refresh'
  | 'fleet.toggleSwitch'
  | 'fleet.dispatchLane'
  // sites (PR3)
  | 'site.pick'
  | 'site.setActive'
  | 'site.preview'
  // audit (PR2)
  | 'audit.open'
  | 'audit.fix'
  | 'audit.verify'
  // harness and lanes (PR3, PR4)
  | 'agent.runAsRole'
  | 'harness.open'
  | 'workflows.open'
  | 'lane.scaffold'
  // fleet slice 2 (PR5)
  | 'fleet.rerunLastFailure'
  | 'fleet.cancelNewest'
  | 'fleet.toggleWorkflowFile'
  | 'fleet.openInGitFactory'
  | 'fleet.importHubRoster'
  | 'monitor.open'
  // surface-only handlers
  | 'openLink'
  | 'openProject'
  | 'revealFile'
  | 'showProblems'
  | 'updateSetting'
  | 'deleteFile'
  | 'renameFile'
  | 'agent.send'
  | 'agent.approve'
  | 'agent.deny';

/** The same union at runtime, for building whitelists and dev assertions. */
export const COMMAND_IDS: readonly CommandId[] = [
  'init',
  'dashboard',
  'dashboard.close',
  'refresh',
  'cache.clear',
  'showOutput',
  'registerFolder',
  'unregisterFolder',
  'createContent',
  'createContentInFolder',
  'generateSlug',
  'setLastModified',
  'insertImage',
  'openFile',
  'collapseSections',
  'focusTags',
  'focusCategories',
  'contentType.generate',
  'contentType.addMissingFields',
  'contentType.set',
  'draft.new',
  'draft.review',
  'draft.approve',
  'draft.publish',
  'draft.guard',
  'draft.preview',
  'catering.worklist',
  'contract.run',
  'contract.normalizePreview',
  'contract.normalizeApply',
  'agent.open',
  'agent.start',
  'agent.stop',
  'mcp.writeWorkspaceConfig',
  'fleet.open',
  'fleet.refresh',
  'fleet.toggleSwitch',
  'fleet.dispatchLane',
  'site.pick',
  'site.setActive',
  'site.preview',
  'audit.open',
  'audit.fix',
  'audit.verify',
  'agent.runAsRole',
  'harness.open',
  'workflows.open',
  'lane.scaffold',
  'fleet.rerunLastFailure',
  'fleet.cancelNewest',
  'fleet.toggleWorkflowFile',
  'fleet.openInGitFactory',
  'fleet.importHubRoster',
  'monitor.open',
  'openLink',
  'openProject',
  'revealFile',
  'showProblems',
  'updateSetting',
  'deleteFile',
  'renameFile',
  'agent.send',
  'agent.approve',
  'agent.deny',
];

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

/** The request/response operations a webview may ask the host to compute. */
export type RequestOp =
  | 'generateSlug'
  | 'searchContent'
  | 'resolvePlaceholder'
  | 'taxonomyOptions'
  | 'pickImage'
  | 'pickFile'
  | 'guardText'
  | 'previewDraft'
  // Declared for PR2/PR4/PR5. All three compute and return; none of them write.
  | 'auditDryRun'
  | 'lanePreview'
  | 'fleetRuns';

export type ViewState = PanelState | DashboardState | AgentState;

/** Host → webview. Everything that is data arrives as `state`. */
export type HostMsg =
  | { type: 'state'; state: ViewState }
  | { type: 'progress'; scope: 'panel' | 'field'; path?: string[]; message: string | null }
  | { type: 'focus'; target: 'tags' | 'categories' | 'search' }
  | { type: 'collapseAll' }
  | { type: 'result'; requestId: string; value?: unknown; error?: string };

/** Webview → host. Six shapes, no more. */
export type ViewMsg =
  | { type: 'ready' }
  | { type: 'updateField'; path: string[]; value: unknown }
  | {
      type: 'addTaxonomy';
      kind: 'tags' | 'categories' | 'custom';
      taxonomyId?: string;
      value: string;
    }
  | { type: 'command'; id: CommandId; args?: unknown }
  | { type: 'request'; requestId: string; op: RequestOp; payload?: unknown }
  | { type: 'setUiState'; key: string; value: string }
  | { type: 'log'; level: 'info' | 'warn' | 'error' | 'verbose'; message: string };

// ---------------------------------------------------------------------------
// Shared view-model fragments
// ---------------------------------------------------------------------------

/** Structurally `core/governance/guard.ts`'s `GuardFinding`. */
export interface GuardFindingView {
  level: 'error' | 'warning' | 'info';
  message: string;
}

/** Structurally `core/governance/approval.ts`'s `Blocker`, widened to string
 *  so a new `BlockerKind` never breaks the webview build. */
export interface BlockerView {
  kind: string;
  message: string;
}

/** What the ledger already knows about this draft's canonical URL. */
export interface LedgerStateView {
  url: string;
  urn: string;
  postedAt: string;
}

/** A draft as the queue and the review pane need it. */
export interface DraftSummary {
  path: string;
  /** Basename, for list rows. */
  name: string;
  title: string;
  description: string;
  status: string;
  type: string;
  source: string | null;
  /** `body.trim()` or `meta.commentary` — the text the fold rule applies to. */
  commentary: string;
}

export interface ActionItem {
  id: CommandId;
  label: string;
  title?: string;
  icon?: string;
  /** Passed straight back as `ViewMsg.args`; a target, never an override. */
  args?: unknown;
  disabled?: boolean;
  primary?: boolean;
}

// ---------------------------------------------------------------------------
// Panel view model
// ---------------------------------------------------------------------------

export interface SeoRowView {
  label: string;
  value: number;
  recommendation?: string;
  /** `undefined` means "reported, never validated" (the article-length row). */
  isValid?: boolean;
}

export interface KeywordCheckView {
  name: string;
  passed: boolean;
}

export interface KeywordInfoView {
  keyword: string;
  checks: KeywordCheckView[];
  passed: number;
  total: number;
  density: number | null;
}

export interface SeoState {
  titleField: string;
  descriptionField: string;
  /**
   * The character budgets from `zer0.json`'s `seo.titleLength` and
   * `seo.descriptionLength`, verbatim. `0` or less means the author switched
   * that check off — the panel shows no counter rather than a budget of zero.
   * They travel as numbers so `limitForField` never has to parse one back out
   * of a `rows[].recommendation` string.
   */
  titleLength: number;
  descriptionLength: number;
  hasTitle: boolean;
  hasDescription: boolean;
  rows: SeoRowView[];
  keywords: KeywordInfoView[];
  /** Known keyword options for the hidden-chrome picker. */
  suggestions: string[];
  wordCount: number;
  headings: number;
  paragraphs: number;
  images: number;
  internalLinks: number;
  externalLinks: number;
}

export interface GovernanceState {
  enabled: boolean;
  /** The draft matching the active file, when there is one. */
  draft: DraftSummary | null;
  guard: GuardFindingView[];
  approveBlockers: BlockerView[];
  publishBlockers: BlockerView[];
  ledger: LedgerStateView | null;
  publishAllow: boolean;
  target: string;
}

export interface RecentFile {
  path: string;
  name: string;
  /** Draw the markdown glyph rather than the generic file glyph. */
  markdown: boolean;
}

export interface RecentFolder {
  title: string;
  totalFiles: number;
  files: RecentFile[];
}

/** The content-type validator hint plus its remediation buttons. */
export interface ContentTypeHint {
  message: string;
  actions: ActionItem[];
}

export interface TaxonomyOptions {
  tags: string[];
  categories: string[];
  custom: Array<{ id: string; options: string[] }>;
  freeform: boolean;
}

export interface FieldViolationView {
  path: string[];
  message: string;
}

export interface PanelSettingsState {
  autoUpdateModifiedDate: boolean;
  openOnSupportedFile: boolean;
  seoEnabled: boolean;
  agentEnabled: boolean;
}

export interface PanelState {
  kind: 'panel';
  /** `zer0.json` exists and the project is set up. */
  initialized: boolean;
  /** `extensionMode !== Production` — gates the developer bar. */
  developer: boolean;
  /** Basename of the active supported file; `null` renders the "General" view. */
  fileName: string | null;
  filePath: string | null;
  /** Which sections the configuration enables, in render order. */
  sections: PanelSectionId[];
  contentTypeName: string | null;
  contentTypeHint: ContentTypeHint | null;
  fields: Field[];
  metadata: FrontMatter | null;
  /** Front-matter parse failure: the body becomes an error state. */
  fmError: string | null;
  violations: FieldViolationView[];
  taxonomy: TaxonomyOptions;
  seo: SeoState | null;
  governance: GovernanceState | null;
  recent: RecentFolder[];
  settings: PanelSettingsState;
  /** Date pattern + zone for the datetime widgets. */
  dateFormat: string;
  timezone: string;
}

// ---------------------------------------------------------------------------
// Dashboard view model
// ---------------------------------------------------------------------------

/**
 * Every route the dashboard can render, in final display order.
 *
 * Eleven now, six of them served today: the rest arrive with the packages that
 * build them (`sites` in PR3, `audit` in PR2, `harness`/`workflows` in PR3–PR4,
 * `monitor` in PR5). Declaring the whole union up front is what lets those
 * packages be written in parallel against one vocabulary, and what makes the
 * order a decision taken once rather than an accident of merge sequence.
 *
 * A route existing here grants nothing. `DASHBOARD_TABS` below is the list the
 * host is willing to route to, and `DashboardState.tabs` is what it actually
 * served this render — the webview draws that, never this.
 */
export type DashboardRoute =
  | 'sites'
  | 'contents'
  | 'drafts'
  | 'audit'
  | 'catering'
  | 'fleet'
  | 'harness'
  | 'workflows'
  | 'monitor'
  | 'settings'
  | 'welcome';

/** The same union at runtime — the route registry (decision D-H). */
export const DASHBOARD_ROUTES: readonly DashboardRoute[] = [
  'sites',
  'contents',
  'drafts',
  'audit',
  'catering',
  'fleet',
  'harness',
  'workflows',
  'monitor',
  'settings',
  'welcome',
];

export interface DashboardTab {
  id: DashboardRoute;
  label: string;
  icon: string;
}

/**
 * The tabs the host may offer, with their labels and codicons — moved out of
 * `dashboardPanel.ts` so the table lives beside the union it draws from.
 *
 * Six entries today, and it grows one PR at a time: a tab appears here only
 * when something can render it. `catering` is dropped from a given snapshot
 * without a `.cms/` contract and `fleet` while `zer0Cms.fleet.enabled` is off,
 * which is a per-render decision the host makes — not a property of this table.
 * The ids are a subset of `DASHBOARD_ROUTES`, in the same relative order.
 */
export const DASHBOARD_TABS: readonly DashboardTab[] = [
  { id: 'sites', label: 'Sites', icon: 'book' },
  { id: 'contents', label: 'Contents', icon: 'files' },
  { id: 'drafts', label: 'Drafts', icon: 'checklist' },
  { id: 'audit', label: 'Audit', icon: 'report' },
  { id: 'catering', label: 'Distribution', icon: 'graph' },
  { id: 'fleet', label: 'Fleet', icon: 'server-process' },
  { id: 'harness', label: 'Harness', icon: 'circuit-board' },
  { id: 'workflows', label: 'Workflows', icon: 'run-all' },
  { id: 'settings', label: 'Settings', icon: 'settings-gear' },
  { id: 'welcome', label: 'Welcome', icon: 'rocket' },
];

// ---------------------------------------------------------------------------
// Sites — one row per workspace folder (decision D-B, filled by PR3)
// ---------------------------------------------------------------------------

/**
 * One open folder as the Sites tab draws it. Every enum is a string on the
 * wire: `platform`, `detectionSource` and `scheme` are all things the host
 * resolved, and a new platform id must never break the webview's build.
 */
export interface SiteView {
  id: string;
  name: string;
  root: string;
  /** `file`, `vscode-vfs`, … — a virtual folder cannot run a process. */
  scheme: string;
  platform: string;
  overlay: string | null;
  detectionSource: string;
  /** A project config was found in this folder. */
  configured: boolean;
  contentRoots: string[];
  manifestPresent: boolean;
  trusted: boolean;
  counts: { pages: number; drafts: number };
  active: boolean;
}

export interface SitesState {
  sites: SiteView[];
  activeId: string | null;
  /** More than one folder is open — the switcher is worth drawing. */
  multi: boolean;
}

export interface CountedTab {
  id: string;
  label: string;
  count: number;
}

export interface SortOption {
  id: string;
  label: string;
}

export interface GroupOption {
  id: string;
  label: string;
}

export interface FilterDimension {
  id: string;
  label: string;
  values: string[];
}

export interface FolderView {
  title: string;
  path: string;
  relPath: string;
  contentTypes: string[];
  disableCreation: boolean;
}

export interface ContentsState {
  pages: PageEntry[];
  folders: FolderView[];
  /** Draft-state navigation tabs with their counts. */
  tabs: CountedTab[];
  sortOptions: SortOption[];
  groupOptions: GroupOption[];
  filters: FilterDimension[];
  /** `0` disables pagination entirely. */
  pageSize: number;
  defaultView: DashboardView;
  defaultSorting: string;
  cardFields: Record<string, boolean>;
}

export interface ReviewState {
  draft: DraftSummary;
  guard: GuardFindingView[];
  /** The exact artifact `buildPreview` produced, pretty-printed. */
  artifact: string;
  ledger: LedgerStateView | null;
  approveBlockers: BlockerView[];
  publishBlockers: BlockerView[];
}

export interface DraftsState {
  enabled: boolean;
  drafts: DraftSummary[];
  counts: { pending: number; approved: number; published: number; other: number };
  selected: string | null;
  review: ReviewState | null;
}

// ---------------------------------------------------------------------------
// Audit — every page's front matter, checked at once (decision D-D, PR2)
// ---------------------------------------------------------------------------

/** Structurally `core/shared/types`' `AuditIssue`, flattened for a table row. */
export interface AuditIssueView {
  path: string;
  relPath: string;
  collection: string;
  /** The coarse rule id; `kind` keeps the `missing-key:<key>` spelling. */
  rule: string;
  kind: string;
  severity: string;
  lane: string;
  field: string | null;
  message: string;
  suggestion: string | null;
  /** A fix exists. Advisory — the host re-derives it before writing anything. */
  fixable: boolean;
}

export interface AuditState {
  /** `false` before the first scan: no issues is not the same as not looked. */
  ran: boolean;
  generatedAt: string | null;
  counts: Record<string, number>;
  issues: AuditIssueView[];
  schemaSource: string;
  collections: string[];
  /** `zer0Cms.cms.verifyCommand`, or `null` when the site declares none. */
  verifyCommand: string | null;
}

export interface TopicSignalView {
  topic: string;
  posts: number;
  impressions: number;
  engagements: number;
}

export interface CateringState {
  present: boolean;
  observations: number;
  undistributed: ContentRecord[];
  proven: TopicSignalView[];
  quiet: TopicSignalView[];
  refresh: ContentRecord[];
  /** The italic empty-state sentences, sourced from `catering/worklist.ts` so
   *  the screen and the generated file can never disagree. */
  emptyStates: {
    undistributed: string;
    proven: string;
    quiet: string;
    refresh: string;
  };
  lastWorklist: string | null;
}

// ---------------------------------------------------------------------------
// Fleet view model
// ---------------------------------------------------------------------------

/** Structurally `core/fleet/fleet.ts`'s `FleetRun`. */
export interface FleetRunView {
  status: string;
  conclusion: string | null;
  url: string;
  updatedAt: string;
}

/** One manifest lane plus what the repository last said about it. */
export interface FleetLaneView {
  id: string;
  kind: string;
  harness: string;
  implementation: string;
  description: string;
  /** `describeTriggers()` — one line. */
  triggers: string;
  /** The `*_ENABLED` variable, or `null` when the lane is ungated. */
  switch: string | null;
  /** `core/fleet/fleet.ts`'s `FleetSwitchValue`, widened to string. */
  switchValue: string;
  usesTokens: string[];
  /** `describeGuardrails()` — one line. */
  guardrails: string;
  lastRun: FleetRunView | null;
  /** Advisory. The host re-evaluates in `doToggleSwitch` / `doDispatchLane`. */
  toggleBlockers: BlockerView[];
  dispatchBlockers: BlockerView[];
  // --- slice 2 (PR5). Optional until the host fills them, so the six routes
  //     that ship today keep building against the same interface.
  /** The engines' rulebook on this lane's workflow file. */
  audit?: AuditFindingView[];
  /** API-equivalent dollars, all-time, from the repository's own ledger. */
  cost?: number | null;
  /** Open pull requests attributed to this lane, by number. */
  pulls?: number[];
  /** The workflow file's own enablement — `active`, `disabled_manually`, … */
  enabledState?: string;
}

/** A pull request as the read-only strip draws it. Never a merge verb. */
export interface FleetPullView {
  number: number;
  title: string;
  /** `prStage()` — derived from labels, widened to string on the wire. */
  stage: string;
  url: string;
  laneId: string | null;
}

/** Structurally `core/shared/types`' `ManifestDrift`. */
export interface ManifestDriftView {
  laneId: string;
  kind: string;
  manifestSays: string;
  workflowSays: string;
}

export interface FleetState {
  /** `zer0Cms.fleet.enabled`. */
  enabled: boolean;
  /** `zer0Cms.fleet.dispatchAllow`, from the settings layer. Advisory here. */
  dispatchAllow: boolean;
  /** Workspace-relative path the host read. */
  manifestPath: string;
  /** `null` when the manifest is absent or refused; `reason` says why. */
  repo: string | null;
  summary: string;
  provenance: string;
  reason: string | null;
  lanes: FleetLaneView[];
  tokens: Array<{ name: string; scope: string; required: boolean; purpose: string; usedBy: string[] }>;
  /** ISO stamp of the last live read, or `null` when the switches are unknown. */
  fetchedAt: string | null;
  /** Why the live columns are what they are — "not signed in", a partial failure, … */
  note: string | null;
  // --- slice 2 (PR5), optional for the same reason as `FleetLaneView`'s.
  /** The read-only pull strip. `null` when nobody has read them yet. */
  pulls?: FleetPullView[] | null;
  /** `MERGE_POLICY_SWITCHES` and what the repository says about each. */
  mergePolicy?: Record<string, string> | null;
  /** The engines' letter grade for this repository's harness. */
  grade?: string | null;
  /** Where the manifest and the workflows disagree. */
  drift?: ManifestDriftView[];
}

// ---------------------------------------------------------------------------
// Harness, Workflows and Monitor (decisions D-E/D-F/D-G; PR3–PR5)
// ---------------------------------------------------------------------------

/**
 * What a repository says about its own AI harness. The records are `Pick`ed
 * from the core types rather than restated, so a field added there reaches the
 * screen by widening one line instead of two structures that drift apart.
 */
export interface HarnessState {
  readAt: string;
  agents: Array<Pick<AgentRecord, 'name' | 'path' | 'description' | 'tools' | 'model' | 'dialect'>>;
  skills: SkillRecord[];
  workflows: Array<
    Pick<
      WorkflowRecord,
      'path' | 'name' | 'runnerShape' | 'switches' | 'crons' | 'dispatchBypassesSwitch'
    >
  >;
  joins: HarnessJoin[];
  findings: Array<{ kind: string; severity: string; path: string | null; message: string }>;
  ledger: { path: string; last7dUsd: number | null; unit: string } | null;
  /** The resolved profile, or `null` when the agent is off. */
  profile: {
    model: string;
    modelSource: string;
    agent: string | null;
    mcpServers: string[];
    settingSources: string[];
    /** The runner flag line the same profile would produce in CI. */
    runnerLine: string;
  } | null;
}

/**
 * One lane's passport: everything read out of a hand-written workflow, plus
 * whether the generators could express it again. Read-only by decision D-I —
 * zer0-CMS never edits an arbitrary workflow's attributes in place.
 */
export interface LanePassportView {
  id: string;
  workflowPath: string | null;
  runnerShape: string;
  switch: string | null;
  dispatchBypassesSwitch: boolean | null;
  cron: string | null;
  tokens: string[];
  resultFile: string | null;
  expressibility: string;
  expressibilityReasons: string[];
  /** `null` until someone asks for run history — no network at activation. */
  runs: FleetRunView[] | null;
}

export interface WorkflowsState {
  lanes: LanePassportView[];
  /** The scaffold form, as settings rows the webview already knows how to draw. */
  form: SettingItem[];
  kitVersion: string;
  /** `zer0Cms.fleet.scaffoldAllow`, from the settings layer. Advisory here. */
  scaffoldAllow: boolean;
  scaffoldBlockers: BlockerView[];
  /** The computed plan, with nothing written. `null` before a preview. */
  plan: {
    shape: string;
    reasons: string[];
    files: Array<{ rel: string; exists: boolean; diff: string }>;
    audit: Array<{ rule: string; severity: string; message: string }>;
  } | null;
}

/** One repository on the roster × its lanes. Every column may be unknown. */
export interface MonitorRepoView {
  slug: string;
  source: string;
  localRoot: string | null;
  fetchedAt: string | null;
  note: string | null;
  grade: string | null;
  mergePolicy: Record<string, string> | null;
  cost: { costUsd: number; window: string; note: string } | null;
  lanes: Array<{
    id: string;
    switchValue: string;
    lastRun: FleetRunView | null;
    openPulls: number | null;
    cost: number | null;
    grade: string | null;
  }>;
  pulls: FleetPullView[] | null;
}

export interface MonitorState {
  roster: MonitorRepoView[];
  hub: {
    slug: string;
    readAt: string | null;
    note: string | null;
    scorecard: Array<{ key: string; value: string; status: string }> | null;
  };
  /** Base URL for the hand-off link, assembled locally and opened in a browser. */
  gitfactoryUrl: string;
}

export interface SettingItem {
  key: string;
  label: string;
  description?: string;
  /**
   * `multichoice`, `path` and `secretName` are the three the lane form needs:
   * a set of tools rather than one, a workspace-relative file the host resolves
   * and the picker browses, and the *name* of a secret — never its value, which
   * this process has no business holding.
   */
  kind: 'boolean' | 'string' | 'number' | 'choice' | 'multichoice' | 'path' | 'secretName';
  value: string | number | boolean;
  choices?: string[];
}

export interface SettingsState {
  general: SettingItem[];
  folders: FolderView[];
  contentTypes: string[];
}

export interface WelcomeStep {
  id: string;
  name: string;
  description: string;
  status: 'active' | 'completed' | 'notStarted';
  action?: ActionItem;
}

export interface WelcomeState {
  steps: WelcomeStep[];
}

export interface DashboardState {
  kind: 'dashboard';
  initialized: boolean;
  showWelcome: boolean;
  developer: boolean;
  /** Tabs the host is willing to route to; `catering` is absent when the
   *  `.cms/` contract is not present. */
  tabs: DashboardTab[];
  contents: ContentsState;
  drafts: DraftsState;
  catering: CateringState | null;
  /** `null` when `zer0Cms.fleet.enabled` is off; the tab is absent too. */
  fleet: FleetState | null;
  settings: SettingsState;
  welcome: WelcomeState;
  version: string;
  // --- the five slices PR2–PR5 fill. Optional until the host builds each one,
  //     so this interface can be complete before any of them exists; the PR
  //     that starts serving a slice is the PR that makes it required.
  /** One row per open workspace folder (PR3). */
  sites?: SitesState;
  /** `null` when the site has not been audited this session (PR2). */
  audit?: AuditState | null;
  /** `null` when nothing has read the harness yet (PR3/PR4). */
  harness?: HarnessState | null;
  /** `null` until the Workflows tab is opened (PR4). */
  workflows?: WorkflowsState | null;
  /** `null` until the Monitor tab is opened (PR5). */
  monitor?: MonitorState | null;
}

// ---------------------------------------------------------------------------
// Agent view model
// ---------------------------------------------------------------------------

export type TranscriptRole = 'user' | 'assistant' | 'tool' | 'system' | 'result' | 'error';

export interface TranscriptEntry {
  role: TranscriptRole;
  text: string;
  /** UTC second-precision stamp, for the transcript gutter. */
  at: string;
}

export interface ApprovalCard {
  id: string;
  tool: string;
  summary: string;
  detail: string;
}

export interface AgentState {
  kind: 'agent';
  /** `zer0Cms.agent.enabled`. */
  enabled: boolean;
  /** The optional SDK resolved. */
  available: boolean;
  running: boolean;
  status: string;
  model: string;
  transcript: TranscriptEntry[];
  approval: ApprovalCard | null;
  /** A one-line explanation shown above the composer (why it is disabled…). */
  notice: string | null;
}

// ---------------------------------------------------------------------------
// Persisted webview state (§4.5)
// ---------------------------------------------------------------------------

export interface ViewUiState {
  /** Panel section collapse map, keyed `collapse_<id>`. */
  collapse: Record<string, 'true' | 'false'>;
  route?: string;
  view?: DashboardView;
  sorting?: string;
  grouping?: string;
  filters?: Record<string, string>;
  page?: number;
  search?: string;
  /** Panel scroll offset, restored on remount. */
  scroll?: number;
  /** Currently selected draft path in the Drafts view. */
  draft?: string;
}

// ---------------------------------------------------------------------------
// Field widget contract (implemented by WP12, consumed by WP11)
// ---------------------------------------------------------------------------

export interface FieldWidget {
  el: HTMLElement;
  setValue(v: FmValue | undefined): void;
  setLoading(msg: string | null): void;
  setError(msg: string | null): void;
  focus(): void;
  dispose(): void;
}

export interface FieldContext {
  field: Field;
  /** The chain of enclosing group names; `[]` at the top level. */
  parents: string[];
  value: FmValue | undefined;
  state: PanelState;
  msg: Messenger;
  onChange(v: FmValue | undefined): void;
}

export type FieldFactory = (ctx: FieldContext) => FieldWidget;
