/**
 * Configuration resolution — three layers, one value object.
 *
 * `zer0.json` describes the *project* (content folders, content types, field
 * groups, taxonomy, placeholders); VS Code settings describe the *user's*
 * preferences and override anything they name. Defaults are last. There is no
 * fourth layer, no `extends`, no split-config directory and no dynamic config
 * module — see decision D2.
 *
 * Everything here is pure: `resolveConfig` takes already-read JSON and an
 * already-read settings object, so the same function serves the extension, the
 * MCP server and the tests. `src/config.ts` (the only vscode-aware translator)
 * is a thin wrapper around it.
 *
 * `zer0.json` is untrusted input, so the file layer is *coerced*, not cast:
 * a field with a bogus `type` is dropped rather than smuggled into the domain
 * as a lie about its shape.
 */

import * as path from 'node:path';

import {
  FIELD_TYPES,
  PANEL_SECTION_IDS,
  type ContentFolder,
  type ContentType,
  type CustomTaxonomy,
  type DashboardSorting,
  type DashboardView,
  type Field,
  type FieldChoice,
  type FieldGroup,
  type FieldType,
  type NumberOptions,
  type PanelSectionId,
  type Placeholder,
  type WhenClause,
  type WhenOperator,
  type Zer0Config,
} from './types';

/** The token that stands for the workspace root inside configured paths. */
export const WORKSPACE_PLACEHOLDER = '[[workspace]]';

/** Default name of the project configuration file. */
export const DEFAULT_CONFIG_FILE = 'zer0.json';

/**
 * The settings layer. Every group is partial and every leaf may be `undefined`,
 * because that is exactly what `vscode.workspace.getConfiguration().get<T>()`
 * hands back for an unset key — the caller should not have to filter first.
 */
type SettingsGroup<T> = T extends readonly unknown[]
  ? T
  : T extends object
    ? { [P in keyof T]?: T[P] | undefined }
    : T;

export type Zer0Settings = {
  [K in keyof Zer0Config]?: SettingsGroup<Zer0Config[K]> | undefined;
};

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

/** The bottom layer. Mirrors the defaults declared in `package.json`. */
export function defaultConfig(root: string): Zer0Config {
  return {
    workspaceRoot: root,
    configFile: DEFAULT_CONFIG_FILE,
    contentFolders: [],
    contentTypes: [],
    fieldGroups: [],
    taxonomy: { tags: [], categories: [], custom: [] },
    draftField: { name: 'draft', type: 'boolean' },
    frontMatter: {
      format: 'yaml',
      indentArrays: true,
      quoteStringValues: false,
      commaSeparatedFields: [],
    },
    content: {
      defaultFileType: 'md',
      supportedFileTypes: ['md', 'mdx', 'markdown'],
      publicFolder: '',
      filePrefix: '',
      preserveCasing: false,
      autoUpdateModifiedDate: false,
    },
    seo: {
      enabled: true,
      titleField: 'title',
      titleLength: 60,
      descriptionField: 'description',
      descriptionLength: 160,
      slugLength: 75,
      contentLength: 1760,
    },
    slug: { template: null, prefix: '', suffix: '', alignFilename: false },
    placeholders: [],
    date: { format: 'yyyy-MM-dd', timezone: 'UTC' },
    governance: {
      enabled: true,
      draftsFolder: '.zer0/drafts',
      ledgerPath: '.zer0/ledger.json',
      acceptStatuses: ['pending', 'approved'],
      publishAllow: false,
      bannedPatternsFile: '',
      target: 'jekyll',
    },
    cms: {
      root: '.cms',
      python: 'python3',
      engineScript: 'scripts/cms/cms.py',
      normalizerScript: 'scripts/content/normalize-frontmatter.py',
      contentDirs: ['pages/'],
    },
    agent: { enabled: false, model: 'claude-opus-5', maxTurns: 40, permissionMode: 'default' },
    validation: { enabled: true },
    panel: {
      openOnSupportedFile: false,
      freeformTaxonomy: true,
      sections: ['governance', 'metadata', 'seo', 'actions', 'recent', 'other'],
    },
    dashboard: {
      openOnStartup: false,
      defaultView: 'grid',
      defaultSorting: 'LastModifiedDesc',
      pageSize: 16,
      cardFields: { state: true, date: true },
    },
    logging: { level: 'info' },
  };
}

// ---------------------------------------------------------------------------
// Coercion helpers — `zer0.json` is untrusted JSON
// ---------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function asStringList(value: unknown): string[] | undefined {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : undefined;
}

function asArray(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined;
}

/** Nullable string setting: `null` is a meaningful value (`slug.template`). */
function asNullableString(value: unknown): string | null | undefined {
  if (value === null) {
    return null;
  }
  return asString(value);
}

function asEnum<T extends string>(value: unknown, allowed: readonly T[]): T | undefined {
  const s = asString(value);
  return s !== undefined && (allowed as readonly string[]).includes(s) ? (s as T) : undefined;
}

/** First defined candidate wins; the last argument is the guaranteed default. */
function pick<T>(setting: T | undefined, file: T | undefined, fallback: T): T {
  if (setting !== undefined) {
    return setting;
  }
  return file !== undefined ? file : fallback;
}

/**
 * Like `pick`, but an empty array falls through. Used for list settings whose
 * default is non-empty (`supportedFileTypes`, `acceptStatuses`, `contentDirs`,
 * `panel.sections`): an empty array there is always an accident, never intent.
 */
function pickList<T>(setting: T[] | undefined, file: T[] | undefined, fallback: T[]): T[] {
  if (setting !== undefined && setting.length > 0) {
    return setting;
  }
  if (file !== undefined && file.length > 0) {
    return file;
  }
  return fallback;
}

function coerceWhen(value: unknown): WhenClause | undefined {
  const raw = asRecord(value);
  if (!raw) {
    return undefined;
  }
  const fieldRef = asString(raw.fieldRef);
  const operator = asEnum<WhenOperator>(raw.operator, [
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
  ]);
  if (fieldRef === undefined || operator === undefined) {
    return undefined;
  }
  const clause: WhenClause = { fieldRef, operator, value: raw.value };
  const caseSensitive = asBoolean(raw.caseSensitive);
  if (caseSensitive !== undefined) {
    clause.caseSensitive = caseSensitive;
  }
  return clause;
}

function coerceNumberOptions(value: unknown): NumberOptions | undefined {
  const raw = asRecord(value);
  if (!raw) {
    return undefined;
  }
  const opts: NumberOptions = {};
  const isDecimal = asBoolean(raw.isDecimal);
  if (isDecimal !== undefined) {
    opts.isDecimal = isDecimal;
  }
  for (const key of ['min', 'max', 'step'] as const) {
    const n = asNumber(raw[key]);
    if (n !== undefined) {
      opts[key] = n;
    }
  }
  return opts;
}

function coerceChoices(value: unknown): FieldChoice[] | undefined {
  const raw = asArray(value);
  if (!raw) {
    return undefined;
  }
  const out: FieldChoice[] = [];
  for (const entry of raw) {
    const s = asString(entry);
    if (s !== undefined) {
      out.push(s);
      continue;
    }
    const rec = asRecord(entry);
    const id = rec ? asString(rec.id) : undefined;
    if (rec && id !== undefined) {
      out.push({ id, title: asString(rec.title) ?? id });
    }
  }
  return out;
}

function coerceField(value: unknown): Field | undefined {
  const raw = asRecord(value);
  if (!raw) {
    return undefined;
  }
  const name = asString(raw.name);
  const type = asEnum<FieldType>(raw.type, FIELD_TYPES);
  if (name === undefined || type === undefined) {
    return undefined;
  }
  const field: Field = { name, type };

  const strings = [
    'title',
    'description',
    'dateFormat',
    'taxonomyId',
    'fieldGroup',
    'contentTypeName',
  ] as const;
  for (const key of strings) {
    const v = asString(raw[key]);
    if (v !== undefined) {
      field[key] = v;
    }
  }

  const booleans = [
    'required',
    'hidden',
    'editable',
    'single',
    'encodeEmoji',
    'isPublishDate',
    'isModifiedDate',
    'multiple',
    'isPreviewImage',
    'singleValueAsString',
    'sameContentLocale',
  ] as const;
  for (const key of booleans) {
    const v = asBoolean(raw[key]);
    if (v !== undefined) {
      field[key] = v;
    }
  }

  const limit = asNumber(raw.taxonomyLimit);
  if (limit !== undefined) {
    field.taxonomyLimit = limit;
  }

  const def = raw.default;
  if (typeof def === 'string' || typeof def === 'number' || typeof def === 'boolean') {
    field.default = def;
  } else {
    const list = asStringList(def);
    if (list !== undefined) {
      field.default = list;
    }
  }

  const when = coerceWhen(raw.when);
  if (when !== undefined) {
    field.when = when;
  }
  const numberOptions = coerceNumberOptions(raw.numberOptions);
  if (numberOptions !== undefined) {
    field.numberOptions = numberOptions;
  }
  const fileExtensions = asStringList(raw.fileExtensions);
  if (fileExtensions !== undefined) {
    field.fileExtensions = fileExtensions;
  }
  const choices = coerceChoices(raw.choices);
  if (choices !== undefined) {
    field.choices = choices;
  }
  const nested = asArray(raw.fields);
  if (nested !== undefined) {
    field.fields = coerceFields(nested);
  }
  const ctValue = asEnum<'path' | 'slug'>(raw.contentTypeValue, ['path', 'slug']);
  if (ctValue !== undefined) {
    field.contentTypeValue = ctValue;
  }
  return field;
}

function coerceFields(value: unknown): Field[] {
  const raw = asArray(value) ?? [];
  const out: Field[] = [];
  for (const entry of raw) {
    const field = coerceField(entry);
    if (field) {
      out.push(field);
    }
  }
  return out;
}

function coerceContentTypes(value: unknown): ContentType[] | undefined {
  const raw = asArray(value);
  if (!raw) {
    return undefined;
  }
  const out: ContentType[] = [];
  for (const entry of raw) {
    const rec = asRecord(entry);
    const name = rec ? asString(rec.name) : undefined;
    if (!rec || name === undefined) {
      continue;
    }
    const ct: ContentType = { name, fields: coerceFields(rec.fields) };
    for (const key of ['fileType', 'defaultFileName', 'template'] as const) {
      const v = asString(rec[key]);
      if (v !== undefined) {
        ct[key] = v;
      }
    }
    for (const key of ['pageBundle', 'clearEmpty'] as const) {
      const v = asBoolean(rec[key]);
      if (v !== undefined) {
        ct[key] = v;
      }
    }
    for (const key of ['slugTemplate', 'filePrefix'] as const) {
      const v = asNullableString(rec[key]);
      if (v !== undefined) {
        ct[key] = v;
      }
    }
    out.push(ct);
  }
  return out;
}

function coerceFolders(value: unknown): ContentFolder[] | undefined {
  const raw = asArray(value);
  if (!raw) {
    return undefined;
  }
  const out: ContentFolder[] = [];
  for (const entry of raw) {
    const rec = asRecord(entry);
    const folderPath = rec ? asString(rec.path) : undefined;
    if (!rec || folderPath === undefined) {
      continue;
    }
    const folder: ContentFolder = {
      title: asString(rec.title) ?? path.posix.basename(folderPath.replace(/\\/g, '/')),
      path: folderPath,
    };
    const contentTypes = asStringList(rec.contentTypes);
    if (contentTypes !== undefined) {
      folder.contentTypes = contentTypes;
    }
    const excludePaths = asStringList(rec.excludePaths);
    if (excludePaths !== undefined) {
      folder.excludePaths = excludePaths;
    }
    for (const key of ['excludeSubdir', 'disableCreation'] as const) {
      const v = asBoolean(rec[key]);
      if (v !== undefined) {
        folder[key] = v;
      }
    }
    const filePrefix = asNullableString(rec.filePrefix);
    if (filePrefix !== undefined) {
      folder.filePrefix = filePrefix;
    }
    out.push(folder);
  }
  return out;
}

function coerceFieldGroups(value: unknown): FieldGroup[] | undefined {
  const raw = asArray(value);
  if (!raw) {
    return undefined;
  }
  const out: FieldGroup[] = [];
  for (const entry of raw) {
    const rec = asRecord(entry);
    const id = rec ? asString(rec.id) : undefined;
    if (!rec || id === undefined) {
      continue;
    }
    const group: FieldGroup = { id, fields: coerceFields(rec.fields) };
    const labelField = asString(rec.labelField);
    if (labelField !== undefined) {
      group.labelField = labelField;
    }
    out.push(group);
  }
  return out;
}

function coercePlaceholders(value: unknown): Placeholder[] | undefined {
  const raw = asArray(value);
  if (!raw) {
    return undefined;
  }
  const out: Placeholder[] = [];
  for (const entry of raw) {
    const rec = asRecord(entry);
    const id = rec ? asString(rec.id) : undefined;
    if (!rec || id === undefined) {
      continue;
    }
    const placeholder: Placeholder = { id };
    for (const key of ['value', 'script', 'command'] as const) {
      const v = asString(rec[key]);
      if (v !== undefined) {
        placeholder[key] = v;
      }
    }
    out.push(placeholder);
  }
  return out;
}

function coerceCustomTaxonomy(value: unknown): CustomTaxonomy[] | undefined {
  const raw = asArray(value);
  if (!raw) {
    return undefined;
  }
  const out: CustomTaxonomy[] = [];
  for (const entry of raw) {
    const rec = asRecord(entry);
    const id = rec ? asString(rec.id) : undefined;
    if (!rec || id === undefined) {
      continue;
    }
    out.push({ id, options: asStringList(rec.options) ?? [] });
  }
  return out;
}

function coerceBooleanMap(value: unknown): Record<string, boolean> | undefined {
  const raw = asRecord(value);
  if (!raw) {
    return undefined;
  }
  const out: Record<string, boolean> = {};
  for (const [key, v] of Object.entries(raw)) {
    const b = asBoolean(v);
    if (b !== undefined) {
      out[key] = b;
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

/** `true` when the value uses the `[[workspace]]` token. */
export function hasWorkspacePlaceholder(value: string): boolean {
  return value.includes(WORKSPACE_PLACEHOLDER);
}

/**
 * Absolute, platform-native path for a configured value. Handles the
 * `[[workspace]]` token, already-absolute paths, and plain relative paths.
 */
export function absPath(cfg: Zer0Config, value: string): string {
  const expanded = value.split(WORKSPACE_PLACEHOLDER).join(cfg.workspaceRoot);
  const native = expanded.split('/').join(path.sep).split('\\').join(path.sep);
  return path.isAbsolute(native) ? path.normalize(native) : path.resolve(cfg.workspaceRoot, native);
}

/** Workspace-relative POSIX path — the form stored in `zer0.json` and shown in the UI. */
export function relPath(cfg: Zer0Config, value: string): string {
  const abs = absPath(cfg, value);
  const rel = path.relative(cfg.workspaceRoot, abs);
  return rel.split(path.sep).join('/');
}

/** Absolute path of the project configuration file. */
export function configPath(cfg: Zer0Config): string {
  return absPath(cfg, cfg.configFile);
}

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

/**
 * Merge the three layers into one complete `Zer0Config`.
 *
 * Precedence per key: `settings` (VS Code) → `file` (`zer0.json`) → default.
 * Arrays and free-form objects replace wholesale — there is no item-level
 * merging (that was FM's `extendConfig`, and it made "where did this content
 * type come from?" unanswerable).
 *
 * Content-folder paths are expanded here: `path` becomes absolute and
 * `originalPath` keeps the configured spelling, so a round-trip back into
 * `zer0.json` writes what the author typed.
 */
export function resolveConfig(root: string, file: unknown, settings: Zer0Settings = {}): Zer0Config {
  const defaults = defaultConfig(root);
  const json = asRecord(file) ?? {};

  const fileTaxonomy = asRecord(json.taxonomy) ?? {};
  const fileDraftField = asRecord(json.draftField) ?? {};
  const fileFrontMatter = asRecord(json.frontMatter) ?? {};
  const fileContent = asRecord(json.content) ?? {};
  const fileSeo = asRecord(json.seo) ?? {};
  const fileSlug = asRecord(json.slug) ?? {};
  const fileDate = asRecord(json.date) ?? {};
  const fileGovernance = asRecord(json.governance) ?? {};
  const fileCms = asRecord(json.cms) ?? {};
  const fileAgent = asRecord(json.agent) ?? {};
  const fileValidation = asRecord(json.validation) ?? {};
  const filePanel = asRecord(json.panel) ?? {};
  const fileDashboard = asRecord(json.dashboard) ?? {};

  const cfg: Zer0Config = {
    workspaceRoot: root,
    configFile: pick(settings.configFile, asString(json.configFile), defaults.configFile),
    contentFolders: pick(
      settings.contentFolders,
      coerceFolders(json.contentFolders),
      defaults.contentFolders,
    ),
    contentTypes: pick(
      settings.contentTypes,
      coerceContentTypes(json.contentTypes),
      defaults.contentTypes,
    ),
    fieldGroups: pick(
      settings.fieldGroups,
      coerceFieldGroups(json.fieldGroups),
      defaults.fieldGroups,
    ),
    taxonomy: {
      tags: pick(settings.taxonomy?.tags, asStringList(fileTaxonomy.tags), defaults.taxonomy.tags),
      categories: pick(
        settings.taxonomy?.categories,
        asStringList(fileTaxonomy.categories),
        defaults.taxonomy.categories,
      ),
      custom: pick(
        settings.taxonomy?.custom,
        coerceCustomTaxonomy(fileTaxonomy.custom),
        defaults.taxonomy.custom,
      ),
    },
    draftField: {
      name: pick(
        settings.draftField?.name,
        asString(fileDraftField.name),
        defaults.draftField.name,
      ),
      type: pick(
        settings.draftField?.type,
        asEnum<'boolean' | 'choice'>(fileDraftField.type, ['boolean', 'choice']),
        defaults.draftField.type,
      ),
    },
    frontMatter: {
      format: pick(
        settings.frontMatter?.format,
        asEnum<'yaml' | 'toml' | 'json'>(fileFrontMatter.format, ['yaml', 'toml', 'json']),
        defaults.frontMatter.format,
      ),
      indentArrays: pick(
        settings.frontMatter?.indentArrays,
        asBoolean(fileFrontMatter.indentArrays),
        defaults.frontMatter.indentArrays,
      ),
      quoteStringValues: pick(
        settings.frontMatter?.quoteStringValues,
        asBoolean(fileFrontMatter.quoteStringValues),
        defaults.frontMatter.quoteStringValues,
      ),
      commaSeparatedFields: pick(
        settings.frontMatter?.commaSeparatedFields,
        asStringList(fileFrontMatter.commaSeparatedFields),
        defaults.frontMatter.commaSeparatedFields,
      ),
    },
    content: {
      defaultFileType: pick(
        settings.content?.defaultFileType,
        asString(fileContent.defaultFileType),
        defaults.content.defaultFileType,
      ),
      supportedFileTypes: pickList(
        settings.content?.supportedFileTypes,
        asStringList(fileContent.supportedFileTypes),
        defaults.content.supportedFileTypes,
      ),
      publicFolder: pick(
        settings.content?.publicFolder,
        asString(fileContent.publicFolder),
        defaults.content.publicFolder,
      ),
      filePrefix: pick(
        settings.content?.filePrefix,
        asString(fileContent.filePrefix),
        defaults.content.filePrefix,
      ),
      preserveCasing: pick(
        settings.content?.preserveCasing,
        asBoolean(fileContent.preserveCasing),
        defaults.content.preserveCasing,
      ),
      autoUpdateModifiedDate: pick(
        settings.content?.autoUpdateModifiedDate,
        asBoolean(fileContent.autoUpdateModifiedDate),
        defaults.content.autoUpdateModifiedDate,
      ),
    },
    seo: {
      enabled: pick(settings.seo?.enabled, asBoolean(fileSeo.enabled), defaults.seo.enabled),
      titleField: pick(
        settings.seo?.titleField,
        asString(fileSeo.titleField),
        defaults.seo.titleField,
      ),
      titleLength: pick(
        settings.seo?.titleLength,
        asNumber(fileSeo.titleLength),
        defaults.seo.titleLength,
      ),
      descriptionField: pick(
        settings.seo?.descriptionField,
        asString(fileSeo.descriptionField),
        defaults.seo.descriptionField,
      ),
      descriptionLength: pick(
        settings.seo?.descriptionLength,
        asNumber(fileSeo.descriptionLength),
        defaults.seo.descriptionLength,
      ),
      slugLength: pick(
        settings.seo?.slugLength,
        asNumber(fileSeo.slugLength),
        defaults.seo.slugLength,
      ),
      contentLength: pick(
        settings.seo?.contentLength,
        asNumber(fileSeo.contentLength),
        defaults.seo.contentLength,
      ),
    },
    slug: {
      template: pick(
        settings.slug?.template,
        asNullableString(fileSlug.template),
        defaults.slug.template,
      ),
      prefix: pick(settings.slug?.prefix, asString(fileSlug.prefix), defaults.slug.prefix),
      suffix: pick(settings.slug?.suffix, asString(fileSlug.suffix), defaults.slug.suffix),
      alignFilename: pick(
        settings.slug?.alignFilename,
        asBoolean(fileSlug.alignFilename),
        defaults.slug.alignFilename,
      ),
    },
    placeholders: pick(
      settings.placeholders,
      coercePlaceholders(json.placeholders),
      defaults.placeholders,
    ),
    date: {
      format: pick(settings.date?.format, asString(fileDate.format), defaults.date.format),
      timezone: pick(settings.date?.timezone, asString(fileDate.timezone), defaults.date.timezone),
    },
    governance: {
      enabled: pick(
        settings.governance?.enabled,
        asBoolean(fileGovernance.enabled),
        defaults.governance.enabled,
      ),
      draftsFolder: pick(
        settings.governance?.draftsFolder,
        asString(fileGovernance.draftsFolder),
        defaults.governance.draftsFolder,
      ),
      ledgerPath: pick(
        settings.governance?.ledgerPath,
        asString(fileGovernance.ledgerPath),
        defaults.governance.ledgerPath,
      ),
      acceptStatuses: pickList(
        settings.governance?.acceptStatuses,
        asStringList(fileGovernance.acceptStatuses),
        defaults.governance.acceptStatuses,
      ),
      publishAllow: pick(
        settings.governance?.publishAllow,
        asBoolean(fileGovernance.publishAllow),
        defaults.governance.publishAllow,
      ),
      bannedPatternsFile: pick(
        settings.governance?.bannedPatternsFile,
        asString(fileGovernance.bannedPatternsFile),
        defaults.governance.bannedPatternsFile,
      ),
      target: pick(
        settings.governance?.target,
        asString(fileGovernance.target),
        defaults.governance.target,
      ),
    },
    cms: {
      root: pick(settings.cms?.root, asString(fileCms.root), defaults.cms.root),
      python: pick(settings.cms?.python, asString(fileCms.python), defaults.cms.python),
      engineScript: pick(
        settings.cms?.engineScript,
        asString(fileCms.engineScript),
        defaults.cms.engineScript,
      ),
      normalizerScript: pick(
        settings.cms?.normalizerScript,
        asString(fileCms.normalizerScript),
        defaults.cms.normalizerScript,
      ),
      contentDirs: pickList(
        settings.cms?.contentDirs,
        asStringList(fileCms.contentDirs),
        defaults.cms.contentDirs,
      ),
    },
    agent: {
      enabled: pick(settings.agent?.enabled, asBoolean(fileAgent.enabled), defaults.agent.enabled),
      model: pick(settings.agent?.model, asString(fileAgent.model), defaults.agent.model),
      maxTurns: pick(
        settings.agent?.maxTurns,
        asNumber(fileAgent.maxTurns),
        defaults.agent.maxTurns,
      ),
      permissionMode: pick(
        settings.agent?.permissionMode,
        asString(fileAgent.permissionMode),
        defaults.agent.permissionMode,
      ),
    },
    validation: {
      enabled: pick(
        settings.validation?.enabled,
        asBoolean(fileValidation.enabled),
        defaults.validation.enabled,
      ),
    },
    panel: {
      openOnSupportedFile: pick(
        settings.panel?.openOnSupportedFile,
        asBoolean(filePanel.openOnSupportedFile),
        defaults.panel.openOnSupportedFile,
      ),
      freeformTaxonomy: pick(
        settings.panel?.freeformTaxonomy,
        asBoolean(filePanel.freeformTaxonomy),
        defaults.panel.freeformTaxonomy,
      ),
      sections: pickList(
        settings.panel?.sections,
        asStringList(filePanel.sections)?.filter((id): id is PanelSectionId =>
          (PANEL_SECTION_IDS as readonly string[]).includes(id),
        ),
        defaults.panel.sections,
      ),
    },
    dashboard: {
      openOnStartup: pick(
        settings.dashboard?.openOnStartup,
        asBoolean(fileDashboard.openOnStartup),
        defaults.dashboard.openOnStartup,
      ),
      defaultView: pick(
        settings.dashboard?.defaultView,
        asEnum<DashboardView>(fileDashboard.defaultView, ['grid', 'list', 'structure']),
        defaults.dashboard.defaultView,
      ),
      defaultSorting: pick(
        settings.dashboard?.defaultSorting,
        asEnum<DashboardSorting>(fileDashboard.defaultSorting, [
          'LastModifiedDesc',
          'LastModifiedAsc',
          'FileNameAsc',
          'FileNameDesc',
          'PublishedDesc',
          'PublishedAsc',
        ]),
        defaults.dashboard.defaultSorting,
      ),
      pageSize: pick(
        settings.dashboard?.pageSize,
        asNumber(fileDashboard.pageSize),
        defaults.dashboard.pageSize,
      ),
      cardFields: pick(
        settings.dashboard?.cardFields,
        coerceBooleanMap(fileDashboard.cardFields),
        defaults.dashboard.cardFields,
      ),
    },
    logging: {
      // Two layers, not three, and deliberately so: how loud your output
      // channel is is a preference belonging to whoever is reading it, not
      // something a checked-in repository gets to decide for every contributor.
      // `src/logger.ts` reads the VS Code setting directly for the same reason,
      // and `zer0.json` has no `logging` key for this to disagree with.
      level: pick(settings.logging?.level, undefined, defaults.logging.level),
    },
  };

  // `draftField.choices` / `invert` are optional; only set when configured, so
  // `exactOptionalPropertyTypes` stays honest about "absent" vs "undefined".
  const draftChoices = pick(
    settings.draftField?.choices,
    asStringList(fileDraftField.choices),
    undefined,
  );
  if (draftChoices !== undefined) {
    cfg.draftField.choices = draftChoices;
  }
  const draftInvert = pick(
    settings.draftField?.invert,
    asBoolean(fileDraftField.invert),
    undefined,
  );
  if (draftInvert !== undefined) {
    cfg.draftField.invert = draftInvert;
  }

  cfg.contentFolders = cfg.contentFolders.map((folder) => ({
    ...folder,
    path: absPath(cfg, folder.path),
    originalPath: folder.originalPath ?? folder.path,
  }));

  return cfg;
}

// ---------------------------------------------------------------------------
// Required-value accessors
// ---------------------------------------------------------------------------

/**
 * Every `requireX` message names BOTH places the value can come from — the
 * `zer0.json` key and the VS Code setting id — because "not configured" is
 * useless when there are two configuration surfaces.
 *
 * Project *schema* keys (content folders, content types) have no setting of
 * their own: they live only in `zer0.json`, and the setting that matters is
 * the one naming that file. Say so explicitly rather than inventing a setting
 * id that does not exist.
 */
function missing(cfg: Zer0Config, jsonKey: string, settingId: string | null, hint: string): Error {
  const file = cfg.configFile || DEFAULT_CONFIG_FILE;
  const where =
    settingId === null
      ? `Add "${jsonKey}" to ${file} (the project config file named by the "zer0Cms.configFile" setting).`
      : `Set "${jsonKey}" in ${file} (named by the "zer0Cms.configFile" setting) or the "${settingId}" setting.`;
  return new Error(`zer0-CMS: "${jsonKey}" is not configured. ${where} ${hint}`);
}

export function requireWorkspaceRoot(cfg: Zer0Config): string {
  if (!cfg.workspaceRoot) {
    throw new Error(
      'zer0-CMS: no workspace folder is open. Open the folder that contains your site ' +
        `and its ${cfg.configFile || DEFAULT_CONFIG_FILE}.`,
    );
  }
  return cfg.workspaceRoot;
}

export function requireContentFolders(cfg: Zer0Config): ContentFolder[] {
  if (cfg.contentFolders.length === 0) {
    throw missing(
      cfg,
      'contentFolders',
      null,
      'Example: "contentFolders": [{ "title": "Posts", "path": "[[workspace]]/pages/_posts" }].',
    );
  }
  return cfg.contentFolders;
}

export function requireContentTypes(cfg: Zer0Config): ContentType[] {
  if (cfg.contentTypes.length === 0) {
    throw missing(
      cfg,
      'contentTypes',
      null,
      'Run "zer0-CMS: Generate content type" on an existing article to create one.',
    );
  }
  return cfg.contentTypes;
}

export function requireDraftsFolder(cfg: Zer0Config): string {
  if (!cfg.governance.draftsFolder) {
    throw missing(
      cfg,
      'governance.draftsFolder',
      'zer0Cms.governance.draftsFolder',
      'Example: ".zer0/drafts".',
    );
  }
  return absPath(cfg, cfg.governance.draftsFolder);
}

export function requireLedgerPath(cfg: Zer0Config): string {
  if (!cfg.governance.ledgerPath) {
    throw missing(
      cfg,
      'governance.ledgerPath',
      'zer0Cms.governance.ledgerPath',
      'Example: ".zer0/ledger.json".',
    );
  }
  return absPath(cfg, cfg.governance.ledgerPath);
}
