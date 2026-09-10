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
 *   - `FleetBlocker` / `FleetLaneState` → core/fleet/fleet.ts
 *   - `FleetCall` / `FleetClient`   → core/fleet/github.ts
 * They are re-exported alongside these by `core/index.ts`, so a duplicate
 * declaration here would make the barrel ambiguous. Import them from their
 * module, not from this file.
 *
 * The four `import type` lines below are the one exception to "dependency-free",
 * and they are not really one: `import type` is erased before a single byte is
 * emitted, so nothing here executes, nothing is bundled, and no cycle exists at
 * runtime. Borrowing the four names is strictly better than the alternative,
 * which would be a second structural copy of each — and a second name for one
 * concept is exactly what the rule above exists to prevent.
 */

import type { FmFormat } from '../content/frontmatter';
import type { FleetRun, FleetSwitchValue } from '../fleet/fleet';
import type { ParsedFleetManifest } from '../fleet/manifest';

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
  /** The site's own `_data/ai.yml` — the model its CI lanes run on. */
  aiConfigPath: string;
  /** The repository's own verification command; `''` means it has none. */
  verifyCommand: string;
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

/**
 * The Fleet console — this repository's AI lanes, read from its
 * `fleet.manifest.yml`. `dispatchAllow` and `scaffoldAllow`, the master gates
 * for writing to another system and to this folder, are deliberately NOT here:
 * both are read from the VS Code settings layer alone
 * (`settingsFleetDispatchAllow()` / `settingsFleetScaffoldAllow()` in
 * `src/config.ts`), so a `zer0.json` arriving with a cloned repository can
 * never arm either one.
 */
export interface FleetConfig {
  enabled: boolean;
  /** Workspace-relative path of the manifest. */
  manifestPath: string;
  /** Extra `owner/name` repositories the Monitor watches. Reads nothing itself. */
  roster: string[];
  /** The fleet's hub repository, as `owner/name`. */
  hub: string;
  /** Base URL of the GitFactory console the hand-off link points at. */
  gitfactoryUrl: string;
}

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
  /**
   * Which generator this site is, as the project declared it. A `zer0.json`
   * key with no settings twin: the *resolved* `PlatformProfile` is never
   * embedded here, because it is derived from the disk and this object is
   * rebuilt on every call.
   */
  platform: PlatformConfig;
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
  fleet: FleetConfig;
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

// ---------------------------------------------------------------------------
// Fleet — `fleet.manifest.yml`, spec `fleet/v1` (bamr87/wtd docs/FLEET-SPEC.md)
// ---------------------------------------------------------------------------

/** How a lane runs its model. Anything the spec does not name coerces to `none`. */
export type FleetHarness = 'claude-code-action' | 'claude-cli' | 'wtd-fleet' | 'engine' | 'none';

export const FLEET_HARNESSES: readonly FleetHarness[] = [
  'claude-code-action',
  'claude-cli',
  'wtd-fleet',
  'engine',
  'none',
];

export type FleetTriggerKind = 'schedule' | 'dispatch' | 'event';

export const FLEET_TRIGGER_KINDS: readonly FleetTriggerKind[] = ['schedule', 'dispatch', 'event'];

export type FleetProvenance = 'declared' | 'derived' | 'unknown';

export interface FleetTrigger {
  kind: FleetTriggerKind;
  /** `schedule` only. */
  cron: string | null;
  /** `event` only: the GitHub event names. */
  events: string[];
}

/**
 * What the manifest promises about a lane's blast radius. `null` means the
 * manifest did not say — which is an honest answer, and a different one from
 * `false`.
 */
export interface FleetGuardrails {
  neverMerges: boolean | null;
  opensPullRequests: boolean | null;
  writesDirectlyToDefaultBranch: boolean | null;
  writablePaths: string[];
}

export interface FleetLane {
  id: string;
  /** Free vocabulary in the spec (`content`, `other`, …); `other` when absent. */
  kind: string;
  harness: FleetHarness;
  /** The workflow file, e.g. `.github/workflows/germinate.yml`. */
  implementation: string;
  description: string;
  triggers: FleetTrigger[];
  /** The `*_ENABLED` repository variable that gates the lane; `null` = ungated. */
  switch: string | null;
  usesTokens: string[];
  guardrails: FleetGuardrails;
}

export interface FleetToken {
  name: string;
  scope: string;
  required: boolean;
  purpose: string;
  usedBy: string[];
}

export interface FleetManifest {
  specVersion: string;
  /** `owner/name`. */
  repo: string;
  provenance: FleetProvenance;
  summary: string;
  lanes: FleetLane[];
  tokens: FleetToken[];
  /** Free-form; the console reports it, it does not interpret it. */
  metering: Record<string, unknown>;
  agents: string[];
  skills: string[];
}

// ---------------------------------------------------------------------------
// Platform profiles — what kind of site this repository is (decision D-C)
// ---------------------------------------------------------------------------

/**
 * The seven generators zer0-CMS knows how to read, plus `generic` for the one
 * it does not. `zer0-mistakes` is deliberately absent: it is a *theme* laid
 * over jekyll, not a generator of its own, and modelling it as a sibling id is
 * how a profile table ends up with two entries that must be kept in sync.
 */
export type PlatformId =
  | 'jekyll'
  | 'mkdocs'
  | 'wikijs'
  | 'hugo'
  | 'docusaurus'
  | 'astro'
  | 'generic';

/** Every platform id, in detection order — the enum the JSON schema mirrors. */
export const PLATFORM_IDS: readonly PlatformId[] = [
  'jekyll',
  'mkdocs',
  'wikijs',
  'hugo',
  'docusaurus',
  'astro',
  'generic',
];

/** An overlay ON a platform. `null` is "no overlay", and a real answer. */
export type PlatformOverlay = 'zer0-mistakes' | null;

/**
 * The `platform` block of `zer0.json`. A `zer0.json` key with no `zer0Cms.*`
 * twin, because what a site *is* belongs to the site, not to whoever opened it.
 */
export interface PlatformConfig {
  /** `auto` detects from marker files; an explicit id skips detection. */
  id: 'auto' | PlatformId;
  /** `auto` probes for the overlay; `null` keeps the bare profile. */
  overlay?: PlatformOverlay | 'auto';
  /** Per-key replacements for the resolved profile. */
  overrides: Partial<PlatformProfileJson>;
}

/** A detection marker: a file that must exist, optionally containing a string. */
export interface PlatformProbe {
  file: string;
  contains?: string;
}

/**
 * What zer0-CMS may do with a content root. `generated` and `vendored` are read
 * without ever being written; `shared-writer` means something else — a CI lane,
 * another tool — also writes here, so an edit has to expect company.
 */
export type RootMode = 'authored' | 'generated' | 'vendored' | 'shared-writer';

export type DatePrefixRule = 'required' | 'optional' | 'forbidden';

export interface PlatformContentRoot {
  collection: string;
  path: string;
  mode: RootMode;
  filename: { datePrefix: DatePrefixRule; bundles: 'index' | '_index' | 'none' };
  permalink: string | null;
  requiredKeys: string[];
  recommendedKeys: string[];
  layoutAllowed: string[];
}

/**
 * Everything a platform decides: where content lives, what a filename means,
 * which front-matter keys are load-bearing, how to serve a preview, and which
 * command verifies the result. Data, not code — a profile is a value in a
 * table, which is what makes "support mkdocs" a table entry rather than a fork
 * in every reader.
 */
export interface PlatformProfile {
  id: PlatformId;
  overlay: PlatformOverlay;
  probes: PlatformProbe[];
  siteConfig: { file: string | null; format: 'yaml' | 'toml' | 'js' | 'none' };
  contentRoots: PlatformContentRoot[];
  outputDirs: string[];
  frontMatter: {
    dialects: FmFormat[];
    typeKey: string | null;
    draft: DraftFieldConfig;
    draftFolders: string[];
    dateKeys: { publish: string[]; modified: string[] };
    dateFormat: 'date' | 'iso-ms' | 'rfc3339';
    filenameDate: RegExp | null;
    taxonomyKeys: string[];
    slugKey: string;
    permalinkKeys: string[];
    thumbnailKeys: string[];
    structuralStems: string[];
    bundleNames: string[];
  };
  commands: {
    serve: string[] | null;
    build: string[] | null;
    previewUrl: string | null;
    port: number | null;
    previewImages: string | null;
  };
  /** `jekyll` for jekyll and its overlay; the platform id otherwise. */
  governanceTarget: string;
  validators: Array<{
    command: string[];
    findingsPath: string | null;
    format: 'findings.jsonl' | 'cms-index' | 'text';
  }>;
}

/**
 * The JSON-shaped twin `zer0.json` overrides and `fingerprintOf` see: no
 * `RegExp`, no functions. A profile that can be serialised is a profile a
 * cache key can be computed from and a person can read in their own config.
 */
export type PlatformProfileJson = Omit<PlatformProfile, 'frontMatter' | 'probes'> & {
  probes: Array<{ file: string; contains?: string }>;
  frontMatter: Omit<PlatformProfile['frontMatter'], 'filenameDate'> & {
    filenameDate: string | null;
  };
};

/**
 * What the site's own config file actually says. Every field is `null` when the
 * file did not say, and an alias or an include the subset parser cannot follow
 * becomes a `warnings` line — never a guessed value.
 */
export interface SiteConfigFacts {
  title: string | null;
  url: string | null;
  baseurl: string | null;
  collectionsDir: string | null;
  collections: Record<string, { permalink: string | null; output: boolean }>;
  permalink: string | null;
  docsDir: string | null;
  useDirectoryUrls: boolean | null;
  warnings: string[];
}

/** A profile plus why zer0-CMS believes it. `evidence` is the files it read. */
export interface ResolvedPlatform {
  profile: PlatformProfile;
  source: 'zer0.json' | 'detected' | 'default';
  evidence: string[];
  siteConfig: SiteConfigFacts;
}

// ---------------------------------------------------------------------------
// Site audit — every page's front matter, checked at once (decision D-D)
// ---------------------------------------------------------------------------

/**
 * The rule vocabulary, lifted verbatim from lifehacker.dev's front-matter lint
 * so a finding means the same thing in the editor and in CI. A rule id is a
 * contract: renaming one silently invalidates every suppression a site wrote.
 */
export const AUDIT_RULE_IDS = [
  'missing-key',
  'invalid-date',
  'future-date',
  'filename-date-mismatch',
  'tags-not-array',
  'unknown-choice',
  'title-too-long',
  'description-too-long',
  'unknown-key',
  'duplicate-slug',
  'duplicate-permalink',
  'unreadable-frontmatter',
  'no-front-matter',
] as const;

export type AuditRuleId = (typeof AUDIT_RULE_IDS)[number];

/**
 * One finding on one file. `kind` keeps `CmsIssue`'s free-form spelling — it is
 * the rule id, or `missing-key:<key>` — while `rule` is the coarse id the
 * counters and the filter chips group by.
 */
export interface AuditIssue extends CmsIssue {
  path: string;
  rule: AuditRuleId;
  /** 1-based line inside the front-matter block, or `null` when it has none. */
  line: number | null;
  /** `fixFor()` would return a change set for this issue. Advisory. */
  fixable: boolean;
}

export interface SiteAudit {
  root: string;
  /** ISO stamp of the scan, so a stale panel can say how stale. */
  generatedAt: string;
  issues: AuditIssue[];
  counts: Record<Severity, number>;
  byRule: Record<string, number>;
  scanned: number;
  /** Paths deliberately not scanned — vendored, generated, ignored. */
  skipped: string[];
}

/** Where a site's front-matter schema came from. `none` is a normal state. */
export type SchemaSource =
  | 'zer0.json'
  | 'frontmatter_schema.yml'
  | 'cms-config'
  | 'profile-default'
  | 'none';

export interface CollectionSchema {
  pathPattern: string | null;
  required: string[];
  optional: string[];
  layoutAllowed: string[] | null;
  fmContentType: string | null;
  dateFormat: 'date' | 'iso-ms' | null;
}

export interface SiteSchema {
  source: SchemaSource;
  path: string | null;
  global: { required: string[]; draftType: 'boolean' | 'choice' | null };
  collections: Record<string, CollectionSchema>;
  constraints: {
    titleMax: number | null;
    descriptionMin: number | null;
    descriptionMax: number | null;
  };
}

/**
 * Structurally the fleet engines' `AuditFinding`, declared here so that the
 * core's scaffold planner and the webview protocol can both name it without
 * either one importing `@bamr87/fleet-engines`. The engines package is bundled
 * into `dist/extension.js` alone (decision D-A); a type that crossed into the
 * MCP graph would be a type the layering gate could not see.
 */
export interface AuditFindingView {
  rule: string;
  severity: string;
  message: string;
  path: string | null;
}

// ---------------------------------------------------------------------------
// Harness — the agents, skills, workflows and lanes a repository runs on
// (decisions D-E and D-F)
// ---------------------------------------------------------------------------

/** How a workflow actually calls a model. `none` means it does not. */
export type RunnerShape =
  | 'ai-lane-caller'
  | 'claude-run'
  | 'claude-code-action'
  | 'claude-cli'
  | 'agentic-engine'
  | 'engine'
  | 'none';

/** Which house dialect an agent file is written in. Descriptive, never gating. */
export type AgentDialect = 'lifehacker' | 'it-journey' | 'zer0-mistakes' | 'bash-365' | 'unknown';

export interface AgentRecord {
  name: string;
  path: string;
  description: string;
  tools: string[];
  model: string | null;
  /** The generated-by-kit stamp, when the file carries one. */
  kitStamp: string | null;
  skillRefs: string[];
  /** The file cites the shared quarantine guardrails for untrusted text. */
  citesQuarantine: boolean;
  dialect: AgentDialect;
  /** Front-matter `name` matches the filename — a dangling reference otherwise. */
  nameMatchesFile: boolean;
}

export interface SkillRecord {
  name: string;
  path: string;
  description: string;
  triggerPhrases: string[];
  nameMatchesDir: boolean;
}

/** The site's own `_data/ai.yml`: which model its CI lanes actually run on. */
export interface AiConfig {
  path: string;
  provider: string | null;
  model: string | null;
  fallbackModel: string | null;
  maxTokens: number | null;
  /** Everything else the file said, flattened and stringified. */
  extra: Record<string, string>;
}

export interface WorkflowRecord {
  path: string;
  name: string;
  runnerShape: RunnerShape;
  agentRefs: string[];
  skillRefs: string[];
  switches: string[];
  /** The repository or environment that holds the switch, when it says. */
  switchHost: string | null;
  switchPolarity: 'enabled-when-true' | 'disabled-when-false' | 'unknown';
  /** `null` when the workflow has no dispatch trigger to bypass with. */
  dispatchBypassesSwitch: boolean | null;
  crons: string[];
  /** Crons that are present but commented out — a lane someone parked. */
  dormantCrons: string[];
  events: string[];
  secrets: string[];
  resultFile: string | null;
  labels: string[];
  branchPattern: string | null;
  setup: { ruby: string | null; node: string | null; python: string | null };
  matrix: 'none' | 'static' | 'dynamic';
  continueOnError: boolean;
  timeoutMinutes: number | null;
  permissions: Record<string, string>;
  kitStamp: string | null;
  generatedByGitFactory: boolean;
}

/**
 * What the AI-usage ledger adds up to. `unit` is stated rather than assumed:
 * the numbers are API-equivalent dollars, which is not the same thing as money
 * anybody was charged, and a dashboard that forgets that lies quietly.
 */
export interface LedgerSummary {
  path: string;
  records: number;
  byRole: Record<string, { calls: number; costUsd: number }>;
  byWorkflow: Record<string, { calls: number; costUsd: number }>;
  last7dUsd: number | null;
  last30dUsd: number | null;
  allTimeUsd: number | null;
  unit: 'api-equivalent-usd';
}

/** One row of the harness join: a workflow and everything attached to it. */
export interface HarnessJoin {
  laneId: string | null;
  workflowPath: string;
  agent: string | null;
  skill: string | null;
  switch: string | null;
  tokens: string[];
  costUsd: number | null;
}

export type HarnessFindingKind =
  | 'dangling-agent'
  | 'dangling-skill'
  | 'agent-name-mismatch'
  | 'switch-hosted-elsewhere'
  | 'lane-without-workflow'
  | 'workflow-without-lane'
  | 'manifest-drift'
  | 'token-presence-chain'
  | 'unmetered-model-call';

export interface HarnessFinding {
  kind: HarnessFindingKind;
  severity: Severity;
  path: string | null;
  message: string;
}

/** Everything a repository says about its own AI harness, read from disk. */
export interface HarnessInventory {
  root: string;
  readAt: string;
  manifest: ParsedFleetManifest;
  workflows: WorkflowRecord[];
  agents: AgentRecord[];
  skills: SkillRecord[];
  aiConfig: AiConfig | null;
  guardrailsDoc: { path: string; kit: string | null } | null;
  ledger: LedgerSummary | null;
  joins: HarnessJoin[];
  findings: HarnessFinding[];
  /** Two counts the scorecard reports separately from `skills.length`. */
  skillCount: { lintAgents: number; wtdAdopt: number };
}

/** How to launch an MCP server over stdio. The shape the SDK and `mcp.json` share. */
export interface McpStdioSpec {
  command: string;
  args: string[];
  env: Record<string, string>;
}

/**
 * One vocabulary for the editor agent and for CI: the model, the persona, the
 * skills and the tools a run gets, resolved once and projected two ways —
 * `toSdkOptions` for the in-editor SDK, `toRunnerInvocation` for the hub's
 * runner. Two projections of one value cannot drift the way two configurations
 * can.
 */
export interface HarnessProfile {
  model: string;
  modelSource: 'settings' | 'zer0.json' | 'ai.yml' | 'default';
  fallbackModel: string | null;
  maxTurns: number;
  permissionMode: AgentPermissionMode;
  agent: AgentRecord | null;
  agents: readonly AgentRecord[];
  skills: readonly SkillRecord[];
  systemAppend: string;
  mcpServers: Record<string, McpStdioSpec>;
  /** `[]` unless the workspace is trusted AND the user opted in. */
  settingSources: Array<'user' | 'project' | 'local'>;
  strictMcpConfig: true;
  readOnlyTools: readonly string[];
}

/**
 * One metered run, written as JSONL beside the ledger the CI lanes write. The
 * shape is the fleet's, not ours, so an in-editor run and a lane run add up.
 */
export interface UsageRecord {
  id: string;
  ts: string;
  source: 'zer0-cms-agent';
  status: 'success' | 'error';
  agent: string | null;
  model: string;
  auth: 'sdk';
  tokens: { input: number; output: number; cache_read: number; cache_creation: number };
  cost_usd: number | null;
  cost_source: 'reported' | 'estimated';
  duration_ms: number;
  num_turns: number;
  session_id: string;
  repo: string;
  workspaceRoot: string;
}

/** What a lane does, in one word. The verb half of `kind`. */
export type LaneKindVerb = 'create' | 'improve' | 'review' | 'scout' | 'triage' | 'fix' | 'audit';

export interface LaneSetup {
  ruby: string | null;
  node: string | null;
  python: string | null;
}

/**
 * A lane as a value: everything the generators need to render a workflow, an
 * agent file, a skill stub and a manifest entry, with nothing left implicit.
 * `classifyExpressibility` reads this and says which of the three shapes it
 * fits — and `bespoke` is an honest answer, not a failure.
 */
export interface LaneSpec {
  id: string;
  kind: string;
  verb: LaneKindVerb;
  description: string;
  agent: string;
  skill: string | null;
  projectName: string;
  platform: PlatformId;
  switch: string | null;
  dispatchBypassesSwitch: boolean;
  cron: string | null;
  events: string[];
  prompt: string;
  system: string;
  tools: string[];
  mcp: string | null;
  model: string | null;
  maxTurns: number | null;
  setup: LaneSetup;
  preRun: string | null;
  postRun: string | null;
  resultFile: string;
  artifactPath: string | null;
  timeoutMinutes: number;
  cancelInProgress: boolean;
  continueOnError: boolean;
  permissions: Record<string, string>;
  matrix: null | { static: string[] } | { dynamic: true };
  crossRepoCheckout: boolean;
  prHeadCheckout: boolean;
  modelPasses: number;
  labels: string[];
  branchPattern: string | null;
  kitVersion: string;
}

/** Which of the three renderers can express a spec without losing anything. */
export type Expressibility = 'ai-lane-caller' | 'gate+claude-run' | 'bespoke';

export interface ScaffoldFile {
  rel: string;
  contents: string;
  /** A file already at `rel`; the preview shows a diff rather than a creation. */
  exists: boolean;
}

/**
 * The whole of a scaffold, computed with nothing written. `switchToCreateLater`
 * names the `*_ENABLED` variable the lane will need — deliberately as a note
 * rather than an action, because arming a lane and writing its files in one
 * gesture is how a generated workflow starts running before anyone read it.
 */
export interface ScaffoldPlan {
  shape: Expressibility;
  reasons: string[];
  files: ScaffoldFile[];
  manifest: { rel: string; before: string; after: string } | null;
  switchToCreateLater: string | null;
  audit: AuditFindingView[];
}

// ---------------------------------------------------------------------------
// Fleet, slice 2 — the roster, the pull strip, cost and drift (decision D-G)
// ---------------------------------------------------------------------------

/** How a repository got onto the roster. Shown, because it explains the gaps. */
export type FleetRosterSource = 'workspace' | 'settings' | 'hub';

export interface FleetRosterEntry {
  /** `owner/name`. */
  slug: string;
  source: FleetRosterSource;
  /** The open folder, when this repository is one; `null` for a remote entry. */
  localRoot: string | null;
  manifestPath: string;
  branch: string | null;
}

export interface FleetPull {
  number: number;
  title: string;
  headRef: string;
  labels: string[];
  draft: boolean;
  authorLogin: string;
  url: string;
  updatedAt: string;
  /** A fork's head is a different blast radius from a branch on the repo. */
  sameRepoHead: boolean;
}

/** Where a pull request sits, derived from its labels — never from a merge API. */
export type PrStage =
  | 'draft'
  | 'auto-mergeable'
  | 'in-review'
  | 'needs-human'
  | 'data-refresh'
  | 'unknown';

export interface FleetWorkflowState {
  id: number;
  path: string;
  name: string;
  /** `active`, `disabled_manually`, `disabled_inactivity`, … verbatim. */
  state: string;
}

/** A `FleetRun` with the identity a rerun or a cancel needs to name it. */
export interface FleetRunRecord extends FleetRun {
  runId: number;
  name: string;
  path: string;
  event: string;
  createdAt: string;
  runStartedAt: string | null;
  runAttempt: number;
}

export interface UsageSummary {
  byWorkflow: Array<{ workflow: string; runs: number; costUsd: number }>;
  byRole: Array<{ role: string; runs: number; costUsd: number }>;
  last7dUsd: number | null;
  last30dUsd: number | null;
  allTimeUsd: number | null;
}

/**
 * One lane's share of the ledger. `window` and `note` are fields rather than
 * documentation because lifehacker's `_data/ai_usage/summary.yml` carries
 * ALL-TIME calls and cost only — a number labelled "this week" that is really
 * "since the beginning" is worse than no number.
 */
export interface LaneCost {
  laneId: string;
  workflowName: string;
  runs: number;
  costUsd: number;
  window: 'all_time';
  note: 'API-equivalent';
}

/** The three repository variables that decide what merges without a human. */
export const MERGE_POLICY_SWITCHES = [
  'AUTO_MERGE_ENABLED',
  'AUTO_UPDATE_ENABLED',
  'AUTO_FIX_ENABLED',
] as const;

export interface MergePolicy {
  switches: Record<(typeof MERGE_POLICY_SWITCHES)[number], FleetSwitchValue>;
}

/** Which axis a manifest and its workflow disagree on. */
export type DriftKind = 'switch' | 'triggers' | 'harness' | 'tokens' | 'implementation';

export interface ManifestDrift {
  laneId: string;
  kind: DriftKind;
  manifestSays: string;
  workflowSays: string;
}

// ---------------------------------------------------------------------------
// Workspace trust — the function is the gate, the `when` clause is a courtesy
// (decision D13)
// ---------------------------------------------------------------------------

/** The five ways zer0-CMS can cause something outside itself to execute. */
export type ExecVector = 'engine' | 'normalizer' | 'placeholder' | 'agent' | 'verify';

export interface ExecGateInput {
  trusted: boolean;
  workspaceRoot: string;
  scriptPath: string;
  interpreter: string;
  /** Which layer supplied the path — a file in the repo is not a human. */
  layer: 'settings' | 'zer0.json' | 'default';
  vector: ExecVector;
}

/** `undefined` from the gate means "allowed"; this is why it was not. */
export interface ExecBlocker {
  reason: 'untrusted-workspace' | 'outside-workspace';
  message: string;
}
