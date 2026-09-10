/**
 * A site's front-matter schema, read from the file the site already keeps.
 *
 * Three of the repositories this console operates already declare, in-tree,
 * which keys a page must carry — and none of them declares it the same way:
 *
 * | Site | File | What it is |
 * |---|---|---|
 * | zer0-mistakes | `.github/config/frontmatter_schema.yml` | per-collection `path_pattern` / `required` / `optional` / `layout.allowed`, plus `global.required_fields` and `global.canonical_fields`. **`scripts/lint-pages` reads it, so it gates CI.** |
 * | it-journey | `.cms/config.yml` + `.cms/schema/content-schema.json` | the content engine's contract: `required_base` + per-collection `required_extra` / `recommended`, and SEO `constraints`. Its own header says it is *stricter* than the CI gate and never fails a build. |
 * | this project | `zer0.json` | content types whose fields carry `required: true`. Nothing in anybody's CI reads it. |
 *
 * Re-typing any of those here would have created a fourth answer that drifts
 * from all three. So this module *ingests* them, and `mergeSchemas` decides
 * which one wins where they overlap.
 *
 * ## Precedence: the source that gates CI wins
 *
 *     frontmatter_schema.yml  (3)   a CI lint reads this file
 *     cms-config              (2)   the site's own engine contract, advisory by its own admission
 *     zer0.json               (1)   this editor's project file
 *     profile-default         (0)   the platform profile's content roots
 *     none                   (-1)   nothing was found — a normal state (D9)
 *
 * The rule is not "the most specific declaration wins" but "the declaration a
 * contributor's pull request will actually be judged by wins". An audit exists
 * to predict the red X on somebody's PR; a schema that let a local file lower
 * the bar CI enforces would report green on work that is about to fail, which
 * is worse than reporting nothing. `zer0.json` still owns field *types*,
 * defaults and choices — that is `ContentType`, and `audit.ts` reads it from
 * there — it just does not get to overrule the gate.
 *
 * Precedence is resolved **per collection**, not per file. A site can gate
 * `posts` in CI and describe `quests` only in `.cms/`; dropping the second
 * because the first outranks it would report less than we actually know, and
 * silence about a collection is not a claim that it has no rules. Within one
 * collection the winner is taken whole — no union of required keys — because a
 * union is exactly how the editor would invent a requirement CI does not have.
 *
 * ## What is not ingested yet
 *
 * `global.canonical_fields` (zer0-mistakes' `updated → lastmod`,
 * `estimated_time → estimated_reading_time`) is a rename map, and `SiteSchema`
 * has no slot for one. Both spellings are folded into every collection's
 * `optional` list so the vocabulary stays complete and `unknown-key` does not
 * fire on a key the site has merely renamed; the mapping itself is dropped
 * rather than guessed at. See `README.md`.
 *
 * Pure Node, no I/O of its own: `readSiteSchema` takes a `read` callback so the
 * MCP server, the extension host and the tests all reach the same parser.
 */

import { compileGlob, globMatches, toPosix } from '../shared/glob';
import type {
  CollectionSchema,
  LogSink,
  PlatformProfile,
  SchemaSource,
  SiteSchema,
  Zer0Config,
} from '../shared/types';
import { asList, asString, ownValue, parseYamlSubset } from './frontmatter';
import type { FmValue, FrontMatter } from './frontmatter';

// ---------------------------------------------------------------------------
// The files, and what outranks what
// ---------------------------------------------------------------------------

/** Workspace-relative paths `readSiteSchema` looks for, in no particular order. */
export const SCHEMA_PATHS = {
  frontmatterSchema: '.github/config/frontmatter_schema.yml',
  cmsConfig: '.cms/config.yml',
  cmsSchema: '.cms/schema/content-schema.json',
} as const;

/**
 * How strongly each source binds a contributor. Higher wins in `mergeSchemas`.
 * The ordering is the module comment's, restated as data so a test can read it.
 */
export const SCHEMA_SOURCE_RANK: Readonly<Record<SchemaSource, number>> = {
  'frontmatter_schema.yml': 3,
  'cms-config': 2,
  'zer0.json': 1,
  'profile-default': 0,
  none: -1,
};

/**
 * The SEO description cap every site in this fleet uses, and the one
 * lifehacker's `lint_frontmatter.rb` enforces as a warning. It is the profile
 * default because a site that declares nothing still has this convention; a
 * site that declares `constraints` outranks it.
 */
export const DEFAULT_DESCRIPTION_MAX = 160;

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------

/** A schema that claims nothing. `source: 'none'` is a normal state (D9). */
export function emptySiteSchema(): SiteSchema {
  return {
    source: 'none',
    path: null,
    global: { required: [], draftType: null },
    collections: {},
    constraints: { titleMax: null, descriptionMin: null, descriptionMax: null },
  };
}

function emptyCollection(): CollectionSchema {
  return {
    pathPattern: null,
    required: [],
    optional: [],
    layoutAllowed: null,
    fmContentType: null,
    dateFormat: null,
  };
}

/** De-duplicate while keeping first-seen order — a schema's order is its author's. */
function uniq(values: readonly string[]): string[] {
  const out: string[] = [];
  for (const value of values) {
    const trimmed = value.trim();
    if (trimmed.length > 0 && !out.includes(trimmed)) {
      out.push(trimmed);
    }
  }
  return out;
}

function mapping(value: FmValue | undefined): FrontMatter {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function positiveInt(value: FmValue | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.trunc(value) : null;
}

// ---------------------------------------------------------------------------
// zer0-mistakes — `.github/config/frontmatter_schema.yml`
// ---------------------------------------------------------------------------

/**
 * The file `scripts/lint-pages` validates against. Per-collection
 * `path_pattern` / `required` / `optional` / `layout.allowed`, plus the global
 * block.
 *
 * Never throws: the hand-rolled YAML subset already degrades a construct it
 * cannot read to "these keys, minus the ones I could not read", and a schema
 * we half-read is still better than no schema — the keys it did read are real.
 */
export function schemaFromFrontmatterSchemaYml(text: string): SiteSchema {
  const data = parseYamlSubset(text);
  const schema = emptySiteSchema();
  schema.source = 'frontmatter_schema.yml';
  schema.path = SCHEMA_PATHS.frontmatterSchema;

  const global = mapping(ownValue(data, 'global'));
  schema.global.required = uniq(asList(ownValue(global, 'required_fields')));
  const draftType = asString(ownValue(global, 'draft_type'));
  if (draftType === 'boolean' || draftType === 'choice') {
    schema.global.draftType = draftType;
  }
  const dateFormat = asString(ownValue(global, 'date_format')) === 'iso8601' ? 'iso-ms' : null;

  // A rename map has no slot on SiteSchema. Keeping both spellings in the
  // optional vocabulary is the part of it we can carry honestly.
  const canonical = mapping(ownValue(global, 'canonical_fields'));
  const aliases = uniq([...Object.keys(canonical), ...Object.values(canonical).map((v) => asString(v))]);

  const collections = mapping(ownValue(data, 'collections'));
  for (const [name, raw] of Object.entries(collections)) {
    const node = mapping(raw);
    const collection = emptyCollection();
    const pattern = asString(ownValue(node, 'path_pattern'));
    collection.pathPattern = pattern.length > 0 ? toPosix(pattern) : null;
    collection.required = uniq(asList(ownValue(node, 'required')));
    collection.optional = uniq([...asList(ownValue(node, 'optional')), ...aliases]);
    const layout = asList(ownValue(mapping(ownValue(node, 'layout')), 'allowed'));
    collection.layoutAllowed = layout.length > 0 ? layout : null;
    collection.dateFormat = dateFormat;
    schema.collections[name] = collection;
  }
  return schema;
}

// ---------------------------------------------------------------------------
// it-journey — `.cms/config.yml` + `.cms/schema/content-schema.json`
// ---------------------------------------------------------------------------

/**
 * The `.cms/` engine's contract. The JSON is *generated from* the YAML (its own
 * `generated_from` says so) and already carries the merged `required` list, so
 * it is read first and the YAML fills in what generation dropped.
 *
 * A JSON file that does not parse yields the YAML's answer alone — never an
 * exception. This runs against somebody else's repository, where a
 * half-written generated file is an ordinary Tuesday.
 */
export function schemaFromCmsConfig(
  configYml: string | undefined,
  schemaJson: string,
  log?: LogSink,
): SiteSchema {
  const schema = emptySiteSchema();
  schema.source = 'cms-config';
  schema.path = SCHEMA_PATHS.cmsSchema;

  const config = configYml === undefined ? {} : parseYamlSubset(configYml);
  const requiredBase = uniq(asList(ownValue(config, 'required_base')));
  schema.global.required = requiredBase;

  let json: FrontMatter = {};
  try {
    const parsed: unknown = JSON.parse(schemaJson);
    if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
      for (const [key, value] of Object.entries(parsed)) {
        json[key] = toFrontMatterValue(value) ?? null;
      }
    }
  } catch (error) {
    // A generated file mid-write is a normal state, not a failure of this
    // console. The YAML half still answers, and the reason is logged.
    log?.warn(`[schema] ${SCHEMA_PATHS.cmsSchema} did not parse as JSON: ${String(error)}`);
    json = {};
  }
  if (Object.keys(json).length === 0 && configYml === undefined) {
    schema.path = SCHEMA_PATHS.cmsConfig;
  }

  readCmsConstraints(schema, mapping(ownValue(json, 'constraints')));
  readCmsConstraints(schema, mapping(ownValue(config, 'constraints')));

  const fromJson = mapping(ownValue(json, 'collections'));
  const fromYaml = mapping(ownValue(config, 'collections'));
  for (const name of uniq([...Object.keys(fromJson), ...Object.keys(fromYaml)])) {
    const jsonNode = mapping(ownValue(fromJson, name));
    const yamlNode = mapping(ownValue(fromYaml, name));
    const collection = emptyCollection();

    const dir = asString(ownValue(jsonNode, 'path')) || asString(ownValue(yamlNode, 'path'));
    // `path: pages/_quests` names a directory, not a glob. Every file under it
    // belongs to the collection, which is what the engine means by it.
    collection.pathPattern = dir.length > 0 ? `${toPosix(dir).replace(/\/+$/, '')}/**` : null;
    collection.fmContentType =
      asString(ownValue(jsonNode, 'fm_content_type')) ||
      asString(ownValue(yamlNode, 'fm_content_type')) ||
      null;

    const explicit = uniq(asList(ownValue(jsonNode, 'required')));
    collection.required =
      explicit.length > 0
        ? explicit
        : uniq([...requiredBase, ...asList(ownValue(yamlNode, 'required_extra'))]);
    collection.optional = uniq([
      ...asList(ownValue(jsonNode, 'recommended')),
      ...asList(ownValue(yamlNode, 'recommended')),
    ]);
    schema.collections[name] = collection;
  }
  return schema;
}

function readCmsConstraints(schema: SiteSchema, constraints: FrontMatter): void {
  const title = mapping(ownValue(constraints, 'title'));
  const description = mapping(ownValue(constraints, 'description'));
  schema.constraints.titleMax = schema.constraints.titleMax ?? positiveInt(ownValue(title, 'hard_max'));
  schema.constraints.descriptionMin =
    schema.constraints.descriptionMin ?? positiveInt(ownValue(description, 'hard_min'));
  schema.constraints.descriptionMax =
    schema.constraints.descriptionMax ?? positiveInt(ownValue(description, 'hard_max'));
}

/**
 * A structural copy of an `unknown` as an `FmValue`. Nothing is asserted: every
 * branch is a real runtime narrowing, so a shape this vocabulary cannot hold
 * comes back `undefined` rather than being waved through by a cast.
 *
 * Two boundaries need it — parsed JSON here, and `PageEntry.data` (typed
 * `Record<string, unknown>` by the index) in `audit.ts`.
 */
export function toFrontMatterValue(value: unknown): FmValue | undefined {
  if (value === null) {
    return null;
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value;
  }
  if (Array.isArray(value)) {
    const out: FmValue[] = [];
    for (const item of value) {
      const converted = toFrontMatterValue(item);
      if (converted !== undefined) {
        out.push(converted);
      }
    }
    return out;
  }
  if (typeof value === 'object') {
    const out: FrontMatter = {};
    for (const [key, item] of Object.entries(value)) {
      const converted = toFrontMatterValue(item);
      if (converted !== undefined) {
        out[key] = converted;
      }
    }
    return out;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// This project's own two sources
// ---------------------------------------------------------------------------

/**
 * `zer0.json`'s content types, read as a schema: a field marked
 * `required: true` is a required key of every folder bound to that type.
 *
 * It ranks below both site files on purpose (see the module comment) — but it
 * ranks above the platform profile, because a person wrote it about this site
 * and the profile is a guess about every site of that kind.
 */
export function schemaFromProjectConfig(cfg: Zer0Config): SiteSchema {
  const schema = emptySiteSchema();
  const byFolder = cfg.contentFolders.filter((folder) => (folder.contentTypes ?? []).length === 1);
  if (cfg.contentTypes.length === 0 || byFolder.length === 0) {
    return schema;
  }
  schema.source = 'zer0.json';
  schema.path = cfg.configFile;

  for (const folder of byFolder) {
    const typeName = (folder.contentTypes ?? [])[0];
    const type = cfg.contentTypes.find((ct) => ct.name === typeName);
    if (type === undefined) {
      continue;
    }
    const collection = emptyCollection();
    const rel = relativeTo(cfg.workspaceRoot, folder.path);
    collection.pathPattern = rel === null ? null : `${rel}/**`;
    collection.fmContentType = type.name;
    collection.required = uniq(
      type.fields.filter((field) => field.required === true).map((field) => field.name),
    );
    // Every declared field is a known key; that is what makes `unknown-key`
    // answerable for a project that took the trouble to declare its fields.
    collection.optional = uniq(type.fields.map((field) => field.name));
    schema.collections[folder.title || type.name] = collection;
  }
  return schema;
}

/** The platform's own idea of what a page in each content root must carry. */
export function schemaFromProfile(profile: PlatformProfile): SiteSchema {
  const schema = emptySiteSchema();
  schema.source = 'profile-default';
  schema.constraints.descriptionMax = DEFAULT_DESCRIPTION_MAX;
  for (const root of profile.contentRoots) {
    const collection = emptyCollection();
    collection.pathPattern = `${toPosix(root.path).replace(/\/+$/, '')}/**`;
    collection.required = uniq(root.requiredKeys);
    // A profile's `recommendedKeys` is advice, not a closed vocabulary, so it
    // does not turn `unknown-key` on. `optional` stays empty here on purpose.
    collection.layoutAllowed = root.layoutAllowed.length > 0 ? [...root.layoutAllowed] : null;
    collection.dateFormat = profile.frontMatter.dateFormat === 'iso-ms' ? 'iso-ms' : 'date';
    schema.collections[root.collection] = collection;
  }
  return schema;
}

/** A configured folder path as a workspace-relative POSIX path, or `null`. */
function relativeTo(root: string, folderPath: string): string | null {
  const posixRoot = toPosix(root).replace(/\/+$/, '');
  const posixPath = toPosix(folderPath).replace(/\/+$/, '');
  if (posixRoot.length > 0 && posixPath.startsWith(`${posixRoot}/`)) {
    return posixPath.slice(posixRoot.length + 1);
  }
  if (posixPath.startsWith('/') || /^[A-Za-z]:/.test(posixPath) || posixPath.includes('[[')) {
    return null;
  }
  return posixPath;
}

// ---------------------------------------------------------------------------
// Precedence
// ---------------------------------------------------------------------------

/**
 * One schema out of several. The source that gates CI wins; where the winner is
 * silent about a collection, the next-ranked source that names it is used, and
 * where every source is silent the answer is silence.
 *
 * Stable within a rank: two schemas of the same source arrive in call order,
 * and the first one wins, so a caller controls its own tie-breaks.
 */
export function mergeSchemas(...schemas: readonly SiteSchema[]): SiteSchema {
  const ranked = schemas
    .map((schema, index) => ({ schema, index, rank: SCHEMA_SOURCE_RANK[schema.source] }))
    .filter((entry) => entry.rank >= 0)
    .sort((a, b) => (b.rank - a.rank) || (a.index - b.index));

  const merged = emptySiteSchema();
  const winner = ranked[0];
  if (winner === undefined) {
    return merged;
  }
  merged.source = winner.schema.source;
  merged.path = winner.schema.path;

  // The global required list is the winner's alone — never filled in from a
  // lower-ranked source. A cap that nobody stated is genuinely unstated and can
  // be borrowed; a required-key list that came out empty said "none", and
  // letting an advisory file raise that bar is precisely what precedence exists
  // to prevent.
  merged.global.required = [...winner.schema.global.required];

  const claimed = new Set<string>();
  for (const { schema } of ranked) {
    merged.global.draftType = merged.global.draftType ?? schema.global.draftType;
    merged.constraints.titleMax = merged.constraints.titleMax ?? schema.constraints.titleMax;
    merged.constraints.descriptionMin =
      merged.constraints.descriptionMin ?? schema.constraints.descriptionMin;
    merged.constraints.descriptionMax =
      merged.constraints.descriptionMax ?? schema.constraints.descriptionMax;

    for (const [name, collection] of Object.entries(schema.collections)) {
      // Claim by the glob's static base, not by the pattern: a CI file's
      // `pages/_posts/**/*.md` and a profile's `pages/_posts/**` are the same
      // content root written twice, and keeping both would let the loser's
      // (empty) vocabulary decide a tie in `collectionSchemaFor`.
      const key =
        collection.pathPattern === null ? `name:${name}` : compileGlob(collection.pathPattern).base;
      if (claimed.has(key) || Object.prototype.hasOwnProperty.call(merged.collections, name)) {
        continue;
      }
      claimed.add(key);
      merged.collections[name] = { ...collection, required: [...collection.required], optional: [...collection.optional] };
    }
  }
  return merged;
}

// ---------------------------------------------------------------------------
// Reading, and looking a page up
// ---------------------------------------------------------------------------

/**
 * Every schema this site declares, merged. `read(rel)` resolves to the file's
 * text or `undefined` when it is not there — absence is the normal case and
 * produces the profile's own defaults, never an error.
 */
export async function readSiteSchema(
  root: string,
  profile: PlatformProfile,
  read: (rel: string) => Promise<string | undefined>,
  log?: LogSink,
): Promise<SiteSchema> {
  const [frontmatterSchema, cmsConfig, cmsSchema] = await Promise.all([
    read(SCHEMA_PATHS.frontmatterSchema),
    read(SCHEMA_PATHS.cmsConfig),
    read(SCHEMA_PATHS.cmsSchema),
  ]);

  const found: SiteSchema[] = [];
  if (frontmatterSchema !== undefined) {
    found.push(withRoot(root, schemaFromFrontmatterSchemaYml(frontmatterSchema)));
  }
  if (cmsSchema !== undefined || cmsConfig !== undefined) {
    found.push(withRoot(root, schemaFromCmsConfig(cmsConfig, cmsSchema ?? '', log)));
  }
  found.push(schemaFromProfile(profile));
  const merged = mergeSchemas(...found);
  log?.verbose(
    `[schema] source=${merged.source} collections=${Object.keys(merged.collections).length} path=${merged.path ?? '—'}`,
  );
  return merged;
}

/** Re-point a schema's `path` at the workspace it was read from. */
function withRoot(root: string, schema: SiteSchema): SiteSchema {
  if (schema.path === null || root.length === 0) {
    return schema;
  }
  return { ...schema, path: `${toPosix(root).replace(/\/+$/, '')}/${schema.path}` };
}

/**
 * The collection a page belongs to, by `path_pattern` first and by name second.
 *
 * The most specific pattern wins — `pages/_posts/**` beats `pages/**` — because
 * a site that describes both means the narrower one. A page no pattern claims
 * falls back to the collection whose *name* matches, and then to nothing, which
 * leaves only `global.required` in force.
 */
export function collectionSchemaFor(
  schema: SiteSchema,
  relPath: string,
  collection?: string,
): { name: string; schema: CollectionSchema } | undefined {
  const candidate = toPosix(relPath);
  let best: { name: string; schema: CollectionSchema; weight: number } | undefined;
  for (const [name, entry] of Object.entries(schema.collections)) {
    if (entry.pathPattern === null) {
      continue;
    }
    if (!globMatches(candidate, [compileGlob(entry.pathPattern)])) {
      continue;
    }
    const weight = compileGlob(entry.pathPattern).base.length;
    if (best === undefined || weight > best.weight) {
      best = { name, schema: entry, weight };
    }
  }
  if (best !== undefined) {
    return { name: best.name, schema: best.schema };
  }
  if (collection !== undefined && Object.prototype.hasOwnProperty.call(schema.collections, collection)) {
    const entry = schema.collections[collection];
    if (entry !== undefined) {
      return { name: collection, schema: entry };
    }
  }
  return undefined;
}

/**
 * Every key this page must carry: the matched collection's `required`, plus the
 * global list. Order is the schema's, globals last, duplicates removed.
 */
export function requiredKeysFor(schema: SiteSchema, relPath: string, collection?: string): string[] {
  const matched = collectionSchemaFor(schema, relPath, collection);
  return uniq([...(matched?.schema.required ?? []), ...schema.global.required]);
}
