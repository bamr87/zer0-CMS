/**
 * The domain vocabulary of zer0-CMS.
 *
 * Every other module — the pure core, the bundled MCP server, the vscode shell
 * and the webviews — imports its cross-cutting types from here, so there is
 * exactly one definition of "a field", "a content type", "a page" and "the
 * resolved configuration". Nothing in this file executes at runtime except the
 * null log sink; it is types plus one constant, deliberately dependency-free so
 * that importing it can never drag `vscode` (or anything else) into the core.
 *
 * Types that belong to a single module live with that module instead:
 *   - `DraftFile` / `NewDraft`      → core/governance/drafts.ts
 *   - `GuardFinding` / `BannedPattern` → core/governance/guard.ts
 *   - `LedgerEntry` / `Ledger`      → core/governance/ledger.ts
 *   - `Blocker` / `BlockerKind`     → core/governance/approval.ts
 *   - `Contract` / `CmsSummary`     → core/contract/contract.ts
 *   - `FmValue` / `FrontMatter`     → core/content/frontmatter.ts
 * They are re-exported alongside these by `core/index.ts`, so a duplicate
 * declaration here would make the barrel ambiguous. Import them from their
 * module, not from this file.
 */

// ---------------------------------------------------------------------------
// Fields
// ---------------------------------------------------------------------------

/** The 18 supported field types. FM's `json`, `block`, `dataFile` and
 *  `customField` are deliberately absent (decision D6). */
export type FieldType =
  | 'string'
  | 'number'
  | 'boolean'
  | 'datetime'
  | 'image'
  | 'file'
  | 'choice'
  | 'tags'
  | 'categories'
  | 'taxonomy'
  | 'draft'
  | 'list'
  | 'slug'
  | 'fields'
  | 'fieldCollection'
  | 'divider'
  | 'heading'
  | 'contentRelationship';

/** Every field type, in declaration order — the enum the JSON schema mirrors. */
export const FIELD_TYPES: readonly FieldType[] = [
  'string',
  'number',
  'boolean',
  'datetime',
  'image',
  'file',
  'choice',
  'tags',
  'categories',
  'taxonomy',
  'draft',
  'list',
  'slug',
  'fields',
  'fieldCollection',
  'divider',
  'heading',
  'contentRelationship',
];

/** The 10 comparison operators a `when` clause may use. FM's four unimplemented
 *  operators are absent from the type rather than silently returning `true`. */
export type WhenOperator =
  | 'eq'
  | 'neq'
  | 'contains'
  | 'notContains'
  | 'startsWith'
  | 'endsWith'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte';

export const WHEN_OPERATORS: readonly WhenOperator[] = [
  'eq',
  'neq',
  'contains',
  'notContains',
  'startsWith',
  'endsWith',
  'gt',
  'gte',
  'lt',
  'lte',
];

/** Conditional visibility: show this field only when `fieldRef` satisfies the
 *  comparison. String comparisons are case-sensitive unless told otherwise. */
export interface WhenClause {
  fieldRef: string;
  operator: WhenOperator;
  value: unknown;
  caseSensitive?: boolean;
}

export interface NumberOptions {
  isDecimal?: boolean;
  min?: number;
  max?: number;
  step?: number;
}

/** A choice entry is either a bare value or an `{id, title}` pair. */
export type FieldChoice = string | { id: string; title: string };

export interface Field {
  name: string;
  type: FieldType;
  title?: string;
  description?: string;
  default?: string | number | boolean | string[];
  required?: boolean;
  hidden?: boolean;
  editable?: boolean;
  when?: WhenClause;

  // --- per type -----------------------------------------------------------
  /** string: render a single-line input instead of a textarea. */
  single?: boolean;
  /** string: encode emoji as `\uXXXX` escapes on write. */
  encodeEmoji?: boolean;
  /** number */
  numberOptions?: NumberOptions;
  /** datetime */
  isPublishDate?: boolean;
  /** datetime */
  isModifiedDate?: boolean;
  /** datetime: token pattern understood by core/shared/dates.ts. */
  dateFormat?: string;
  /** image | file | choice | list | contentRelationship */
  multiple?: boolean;
  /** image: this image is the page's preview/hero image. */
  isPreviewImage?: boolean;
  /** file: required — the extensions the picker accepts. */
  fileExtensions?: string[];
  /** choice */
  choices?: FieldChoice[];
  /** taxonomy: id of a `taxonomy.custom[]` entry. */
  taxonomyId?: string;
  /** taxonomy | tags | categories: maximum number of selections. */
  taxonomyLimit?: number;
  /** taxonomy | tags | categories: write a lone value as a string, not a list. */
  singleValueAsString?: boolean;
  /** fields: the nested field set. */
  fields?: Field[];
  /** fieldCollection: id of a `fieldGroups[]` entry, inlined at compile time. */
  fieldGroup?: string;
  /** contentRelationship: required — the content type being referenced. */
  contentTypeName?: string;
  /** contentRelationship: store the referenced page's path or its slug. */
  contentTypeValue?: 'path' | 'slug';
  /** contentRelationship: restrict choices to the current locale. */
  sameContentLocale?: boolean;
}

/** A reusable set of fields, spliced in wherever a `fieldCollection` names it. */
export interface FieldGroup {
  id: string;
  labelField?: string;
  fields: Field[];
}

// ---------------------------------------------------------------------------
// Content types and folders
// ---------------------------------------------------------------------------

export interface ContentType {
  name: string;
  fields: Field[];
  fileType?: string;
  /** `null` disables slug generation for this type. */
  slugTemplate?: string | null;
  pageBundle?: boolean;
  defaultFileName?: string;
  /** Path to a template file used as the body seed. */
  template?: string;
  filePrefix?: string | null;
  /** Drop keys whose value is empty when writing. */
  clearEmpty?: boolean;
}

export interface ContentFolder {
  title: string;
  /** Absolute after `resolveConfig`; `originalPath` keeps the configured form. */
  path: string;
  contentTypes?: string[];
  excludeSubdir?: boolean;
  excludePaths?: string[];
  disableCreation?: boolean;
  filePrefix?: string | null;
  /** Runtime only: the path exactly as it appeared in `zer0.json`. */
  originalPath?: string;
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface CustomTaxonomy {
  id: string;
  options: string[];
}

export interface TaxonomyConfig {
  tags: string[];
  categories: string[];
  custom: CustomTaxonomy[];
}

/** Which front-matter key marks a draft, and how its value is read. */
export interface DraftFieldConfig {
  name: string;
  type: 'boolean' | 'choice';
  choices?: string[];
  /** `true` means the field marks *published*, not draft. */
  invert?: boolean;
}

export interface FrontMatterConfig {
  format: 'yaml' | 'toml' | 'json';
  indentArrays: boolean;
  quoteStringValues: boolean;
  /** Keys written as `a, b, c` on one line instead of a block sequence. */
  commaSeparatedFields: string[];
}

export interface ContentConfig {
  defaultFileType: string;
  supportedFileTypes: string[];
  /** Folder served at the site root; media paths are made relative to it. */
  publicFolder: string;
  /** Default filename prefix template, e.g. `{{date|yyyy-MM-dd}}`. */
  filePrefix: string;
  preserveCasing: boolean;
  autoUpdateModifiedDate: boolean;
}

export interface SeoConfig {
  enabled: boolean;
  titleField: string;
  titleLength: number;
  descriptionField: string;
  descriptionLength: number;
  slugLength: number;
  /** Recommended article length in words. Never validated, only reported. */
  contentLength: number;
}

export interface SlugConfig {
  /** `null` means "slugify the title". */
  template: string | null;
  prefix: string;
  suffix: string;
  /** Rename the file to match the generated slug. */
  alignFilename: boolean;
  /**
   * Words dropped when a title becomes a slug, already resolved from the
   * `"smart"` / `"minimal"` / `"none"` preset or the literal array in
   * `zer0.json`. A `Set`, not a list, because it is only ever asked "is this
   * word in you"; it never crosses `postMessage` and is not part of the page
   * index fingerprint, so nothing needs it to be JSON.
   */
  stopWords: ReadonlySet<string>;
}

/** A `{{id}}` token resolved from a static value, a script, or a command. */
export interface Placeholder {
  id: string;
  value?: string;
  script?: string;
  command?: string;
}

export interface DateConfig {
  /** Token pattern understood by core/shared/dates.ts. */
  format: string;
  /** IANA zone id, e.g. `UTC` or `America/New_York`. */
  timezone: string;
}

export interface GovernanceConfig {
  enabled: boolean;
  draftsFolder: string;
  ledgerPath: string;
  /** Draft statuses that may be approved/published. */
  acceptStatuses: string[];
  /** The master publish switch — off blocks every surface, including MCP. */
  publishAllow: boolean;
  bannedPatternsFile: string;
  /** Id of the `PublishTarget` to use. */
  target: string;
}

/** Where the `.cms/` contract lives and how to run the Python engine. */
export interface CmsEngineConfig {
  root: string;
  python: string;
  engineScript: string;
  normalizerScript: string;
  contentDirs: string[];
}

export type AgentPermissionMode = 'default' | 'acceptEdits' | 'plan';

export interface AgentConfig {
  enabled: boolean;
  model: string;
  maxTurns: number;
  /** One of `AgentPermissionMode`; kept as a string so an unknown value from
   *  settings degrades to the SDK's own handling instead of a type error. */
  permissionMode: string;
}

export interface ValidationConfig {
  enabled: boolean;
}

export type PanelSectionId =
  | 'governance'
  | 'metadata'
  | 'seo'
  | 'actions'
  | 'recent'
  | 'settings'
  | 'other';

export const PANEL_SECTION_IDS: readonly PanelSectionId[] = [
  'governance',
  'metadata',
  'seo',
  'actions',
  'recent',
  'settings',
  'other',
];

export interface PanelConfig {
  openOnSupportedFile: boolean;
  /** Allow typing taxonomy values that are not in the configured list. */
  freeformTaxonomy: boolean;
  sections: PanelSectionId[];
}

export type DashboardView = 'grid' | 'list' | 'structure';

export type DashboardSorting =
  | 'LastModifiedDesc'
  | 'LastModifiedAsc'
  | 'FileNameAsc'
  | 'FileNameDesc'
  | 'PublishedDesc'
  | 'PublishedAsc';

export interface DashboardConfig {
  openOnStartup: boolean;
  defaultView: DashboardView;
  defaultSorting: DashboardSorting;
  /** 0 disables pagination. */
  pageSize: number;
  /** Which metadata chips a card shows, e.g. `{ state: true, date: true }`. */
  cardFields: Record<string, boolean>;
}

export type LogLevel = 'error' | 'warn' | 'info' | 'verbose';

export interface LoggingConfig {
  level: LogLevel;
}

/**
 * The fully resolved configuration: VS Code settings over `zer0.json` over
 * built-in defaults, with `[[workspace]]` already expanded. Always a complete
 * value — every key is present, so no consumer writes `?? default` again.
 */
export interface Zer0Config {
  workspaceRoot: string;
  /** Workspace-relative name of the project config file. */
  configFile: string;
  contentFolders: ContentFolder[];
  contentTypes: ContentType[];
  fieldGroups: FieldGroup[];
  taxonomy: TaxonomyConfig;
  draftField: DraftFieldConfig;
  frontMatter: FrontMatterConfig;
  content: ContentConfig;
  seo: SeoConfig;
  slug: SlugConfig;
  placeholders: Placeholder[];
  date: DateConfig;
  governance: GovernanceConfig;
  cms: CmsEngineConfig;
  agent: AgentConfig;
  validation: ValidationConfig;
  panel: PanelConfig;
  dashboard: DashboardConfig;
  logging: LoggingConfig;
}

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

/** The core never imports an OutputChannel; the shell injects one of these. */
export interface LogSink {
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
  verbose(message: string): void;
}

function discard(_message: string): void {
  // The null sink exists so core functions can take an optional LogSink
  // without every call site guarding on `log?.`. Discarding is the point.
}

export const NOOP_LOG: LogSink = {
  info: discard,
  warn: discard,
  error: discard,
  verbose: discard,
};

// ---------------------------------------------------------------------------
// Content records — the `.cms/` contract's view of a page
// ---------------------------------------------------------------------------

export type Severity = 'error' | 'warning' | 'info';

/** `mechanical` issues are safely auto-fixable; `substantive` need a human. */
export type Lane = 'mechanical' | 'substantive';

export type Freshness = 'fresh' | 'aging' | 'stale' | 'critical' | 'unknown';

export interface CmsIssue {
  kind: string;
  severity: Severity;
  field: string | null;
  message: string;
  lane: Lane;
  suggestion: string | null;
}

/**
 * "Nobody measured this" — the sentinel `health`, `wordCount` and
 * `headingCount` all share.
 *
 * It is negative rather than `null` so the fields stay plain numbers that sort
 * and compare without a type guard at every use, and `-1` rather than `0`
 * because `0` is a legitimate measurement: an article really can have no
 * headings. It lives here, beside `ContentRecord`, rather than in
 * `contract/contract.ts` where the rest of the record vocabulary sits, because
 * `pageIndex` needs it too and those two modules already import each other.
 */
export const UNKNOWN_COUNT = -1;

/** Is this a real measurement, or the `UNKNOWN_COUNT` stand-in? */
export function isMeasured(value: number): boolean {
  return Number.isFinite(value) && value >= 0;
}

/**
 * Render a possibly-unmeasured count for a human.
 *
 * Every surface that prints `wordCount` or `headingCount` goes through this,
 * so "we did not count" never reaches a person disguised as "we counted zero".
 */
export function countLabel(value: number, unknown = 'unknown'): string {
  return isMeasured(value) ? String(value) : unknown;
}

/**
 * One page as the engine sees it. Produced by `.cms/index/content-index.json`
 * when the contract is present, and by `pageIndex.pageToRecord` when it is not
 * — in which case `health` is `-1` and `freshness` is `unknown`, and the
 * distributable rule honestly degrades to "not a draft and has a title".
 */
export interface ContentRecord {
  path: string;
  collection: string;
  title: string;
  descriptionLen: number;
  titleLen: number;
  /**
   * Words in the body, or `-1` when nobody counted them — the same sentinel
   * `health` uses, and for the same reason. A filesystem scan does not read
   * bodies, and reporting `0` there would state that a 2,000-word article is
   * empty. Render it with `countLabel`, never raw.
   */
  wordCount: number;
  /** Headings in the body, or `-1` when unknown. See `wordCount`. */
  headingCount: number;
  /** 0–100, or `-1` when unknown. */
  health: number;
  freshness: Freshness;
  draft: boolean | null;
  generated: boolean;
  structural: boolean;
  readOnly: boolean;
  isNotebook: boolean;
  frontmatterPresent: boolean;
  date: string | null;
  lastmod: string | null;
  ageDays: number;
  brokenLinks: number;
  issues: CmsIssue[];
}

/** Per-content engagement metrics; `engagements` is derived, never read raw. */
export interface PerfStats {
  impressions: number;
  clicks: number;
  reactions: number;
  comments: number;
  shares: number;
  engagements: number;
}

// ---------------------------------------------------------------------------
// Page index — the extension's own view of a file on disk
// ---------------------------------------------------------------------------

export interface PageEntry {
  filePath: string;
  /** Workspace-relative POSIX path. */
  relPath: string;
  /** `path` of the owning content folder. */
  folder: string;
  contentType: string;
  title: string;
  description: string;
  slug: string;
  date: string | null;
  /** File mtime in epoch milliseconds. */
  modified: number;
  /** Publish date in epoch milliseconds, or `null` when unset. */
  published: number | null;
  draft: boolean | string;
  tags: string[];
  categories: string[];
  previewImage: string;
  /** The full front matter, for fields the projection above does not name. */
  data: Record<string, unknown>;
}
