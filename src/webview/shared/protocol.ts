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
  ContentRecord,
  DashboardView,
  Field,
  Freshness,
  PageEntry,
  PanelSectionId,
} from '../../core/shared/types';
// Type-only alias re-export: the field widgets in WP12 need the exact same
// `FmValue` the front-matter parser produces, and a second structural copy
// declared here would be a second name for one concept. `import type` is
// erased at build time, so this costs the webview bundle nothing.
import type { FmValue, FrontMatter } from '../../core/content/frontmatter';
import type { Messenger } from './messenger';

export type { FmValue, FrontMatter };
export type { ContentRecord, DashboardView, Field, Freshness, PageEntry, PanelSectionId };

// ---------------------------------------------------------------------------
// Command ids — the closed intent vocabulary
// ---------------------------------------------------------------------------

/**
 * Every intent a webview button may name. The first 34 are the palette
 * commands (`zer0Cms.<id>`) verbatim; the trailing group are host operations
 * that exist only for a surface (settings writes, file operations, the agent
 * approval reply) and are registered as handlers rather than as commands.
 *
 * Adding a literal here does NOT grant it — the host still has to implement a
 * handler, and every gate is re-checked in the same function the palette calls.
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
  | 'previewDraft';

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

export type DashboardRoute = 'contents' | 'drafts' | 'catering' | 'settings' | 'welcome';

export interface DashboardTab {
  id: DashboardRoute;
  label: string;
  icon: string;
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

export interface SettingItem {
  key: string;
  label: string;
  description?: string;
  kind: 'boolean' | 'string' | 'number' | 'choice';
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
  settings: SettingsState;
  welcome: WelcomeState;
  version: string;
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
