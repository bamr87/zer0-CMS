/**
 * Publish targets for every generator that is not Jekyll — one factory, not
 * five copy-pasted targets.
 *
 * Decision D8 says publishing is an interface, not a vendor: a pure `build`, an
 * effectful `send`, and an open registry. Decision D12 says a site's platform is
 * a **profile** — data, not code. `platformFileTarget` is where the two meet:
 * given a `PlatformProfile` it returns the `PublishTarget` for that platform,
 * with the destination rule, the front-matter dialect and the date keys read out
 * of the profile rather than written down here. Adding MkDocs support is a table
 * entry in `core/platform`, not a sixth target in this file.
 *
 * This file exists because of a specific bug. `TARGETS` held exactly one entry
 * and `targetById` **threw** for anything else, so the moment detection could
 * answer "this is a Hugo site", `targetFor` would resolve a `governanceTarget`
 * nobody had registered and `buildPreview` would throw where it used to work.
 * **Nothing may throw for a platform the extension itself detected** — a person
 * who opened an MkDocs folder made no mistake and must not be handed an error.
 * A typo in *their own* `governance.target` is a different thing, and still
 * throws.
 *
 * The two halves keep the same discipline `jekyllTarget` has:
 *
 *   - `build` is **pure**. It computes the destination path, the rendered file
 *     and any warnings, and it touches neither disk nor network — that is what
 *     makes a preview provably free of side effects, and it is what lets a
 *     reviewer approve the literal bytes instead of a description of them.
 *   - `send` writes with the exclusive `wx` flag through
 *     `writeArtifactExclusively`, which is the *same function* `jekyllTarget`
 *     uses — same `-2`/`-3` collision chain, same adopt-on-identical semantics
 *     for a publish interrupted between the write and the ledger. Sharing the
 *     implementation is the only way "the same behaviour" stays true.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { splitFrontMatter, type FrontMatter } from '../content/frontmatter';
import { serializeFrontMatter, serializeOptions, stitch } from '../content/serialize';
import { absPath } from '../shared/config';
import { formatDate } from '../shared/dates';
import { toPosix } from '../shared/glob';
import type {
  DatePrefixRule,
  PlatformContentRoot,
  PlatformProfile,
  Zer0Config,
} from '../shared/types';
import type { Preview, PublishDeps, PublishPlan, PublishTarget } from './publish';

// ---------------------------------------------------------------------------
// The exclusive write — shared with jekyllTarget, deliberately
// ---------------------------------------------------------------------------

/**
 * Everything in an artifact except the moment it was built.
 *
 * `build` stamps the publish date from the clock, so the same publish retried a
 * minute later produces different bytes for identical content. Every other key,
 * and the body, are functions of the draft alone — which is what makes this a
 * usable answer to "did I already write this exact page?".
 */
export function artifactIdentity(text: string, dateKeys: readonly string[] = ['date']): string {
  const { block, body } = splitFrontMatter(text);
  const skip = new Set(dateKeys);
  const keys = Object.entries(block?.data ?? {})
    .filter(([key]) => !skip.has(key))
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return JSON.stringify([keys, body.trim()]);
}

function errnoCode(error: unknown): string | undefined {
  if (typeof error === 'object' && error !== null && 'code' in error) {
    const code = (error as { code?: unknown }).code;
    return typeof code === 'string' ? code : undefined;
  }
  return undefined;
}

/** Whether the file already at `rel` is the artifact we were about to write. */
async function sameArtifactOnDisk(
  cfg: Zer0Config,
  rel: string,
  identity: string,
  dateKeys: readonly string[],
): Promise<boolean> {
  try {
    return artifactIdentity(await fs.readFile(absPath(cfg, rel), 'utf8'), dateKeys) === identity;
  } catch {
    // The name is taken by something we cannot read — a directory, or a file
    // whose permissions say no. "Not ours" is the safe answer: the caller bumps
    // to the next name instead of assuming a match it could not verify.
    return false;
  }
}

/**
 * Create the destination directory and write `contents` there, exclusively.
 *
 * `wx` fails rather than overwriting, and the destination bumps to `-2`, `-3` on
 * collision. Publishing must never silently replace somebody's page.
 *
 * **The `-2` bump is for a different page that wants the same name, and only
 * that.** Writing the file and recording the ledger entry are two steps, and a
 * crash — or a read-only `.zer0/` — between them leaves an artifact on disk that
 * no ledger key mentions. The next attempt passes every gate, reaches `wx`, gets
 * `EEXIST` and used to bump: two live pages for one canonical URL, with the
 * ledger naming the `-2` file under the URL the `-1` file is served at. So an
 * existing file whose content is this artifact's is *adopted* — the publish is
 * completed by recording it, not duplicated.
 */
export async function writeArtifactExclusively(
  cfg: Zer0Config,
  targetId: string,
  intended: string,
  contents: string,
  deps: PublishDeps,
  dateKeys: readonly string[] = ['date'],
): Promise<{ urn: string; warnings: string[] }> {
  await fs.mkdir(path.dirname(absPath(cfg, intended)), { recursive: true });

  const ext = path.extname(intended);
  const stem = intended.slice(0, intended.length - ext.length);
  const warnings: string[] = [];
  const identity = artifactIdentity(contents, dateKeys);

  for (let n = 1; ; n += 1) {
    const rel = n === 1 ? intended : `${stem}-${n}${ext}`;
    try {
      // `wx`: create or fail. Never overwrite an existing page.
      await fs.writeFile(absPath(cfg, rel), contents, { encoding: 'utf8', flag: 'wx' });
      if (rel !== intended) {
        warnings.push(`warning: ${intended} already existed; wrote ${rel} instead`);
      }
      deps.log?.(`published ${rel}`);
      return { urn: `${targetId}:${rel}`, warnings };
    } catch (error) {
      if (errnoCode(error) !== 'EEXIST') {
        throw error;
      }
      if (await sameArtifactOnDisk(cfg, rel, identity, dateKeys)) {
        // An earlier attempt wrote this exact page and did not get as far as
        // the ledger. Adopt it and let the caller record it, rather than
        // shipping a second copy of the same canonical URL.
        warnings.push(
          `warning: ${rel} was already on disk with this exact content but had no ledger ` +
            'record — an interrupted publish. Recording it instead of writing a second copy.',
        );
        deps.log?.(`adopted the existing ${rel}`);
        return { urn: `${targetId}:${rel}`, warnings };
      }
      if (n > 50) {
        throw new Error(`cannot find a free filename for ${intended}`);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// The artifact
// ---------------------------------------------------------------------------

/**
 * What a platform file target would write. The same shape `JekyllArtifact` has,
 * plus the warnings `build` raised while reconciling the configured destination
 * with what the platform actually allows — a filename date prefix MkDocs would
 * serve as part of the slug, say.
 */
export interface PlatformArtifact {
  /** The platform id — the same string as the target's `id`. */
  target: string;
  /** Workspace-relative POSIX path the file would be written to. */
  path: string;
  frontMatter: FrontMatter;
  body: string;
  /** The exact bytes. */
  contents: string;
  /** Non-fatal notes from planning the destination. Advisory, never thrown. */
  warnings: string[];
}

function isPlatformArtifact(value: unknown, id: string): value is PlatformArtifact {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { target?: unknown }).target === id &&
    typeof (value as { contents?: unknown }).contents === 'string' &&
    typeof (value as { path?: unknown }).path === 'string'
  );
}

function requirePlan(preview: Preview): PublishPlan {
  if (preview.plan === undefined) {
    throw new Error('preview has no publish plan (build it with buildPreview)');
  }
  return preview.plan;
}

// ---------------------------------------------------------------------------
// The destination, read out of the profile
// ---------------------------------------------------------------------------

const DEFAULT_FILENAME_DATE = /^\d{4}-\d{2}-\d{2}-/;

/**
 * A non-sticky copy of the profile's filename-date pattern.
 *
 * A `RegExp` carrying `g` or `y` keeps `lastIndex` between calls, so testing the
 * same profile twice would answer differently the second time. The profile is a
 * shared value; a stateful match against it is a bug that only shows up under
 * load.
 */
export function filenameDateRe(profile: PlatformProfile): RegExp {
  const declared = profile.frontMatter.filenameDate;
  if (declared === null) {
    return DEFAULT_FILENAME_DATE;
  }
  const flags = declared.flags.replace(/[gy]/g, '');
  return flags === declared.flags ? declared : new RegExp(declared.source, flags);
}

/** Workspace-relative POSIX form of a content root's path, with no trailing slash. */
function rootPath(cfg: Zer0Config, root: PlatformContentRoot): string {
  const raw = toPosix(root.path).trim();
  const rel = path.isAbsolute(raw)
    ? toPosix(path.relative(cfg.workspaceRoot, raw))
    : raw.replace(/^\.?\//, '');
  return rel.replace(/\/+$/, '');
}

/**
 * The content root that owns `dir`, or nothing.
 *
 * Longest match wins, the same way `folderOf` resolves a nested content folder:
 * `content/posts` must beat `content` for a file under it.
 */
export function contentRootFor(
  cfg: Zer0Config,
  profile: PlatformProfile,
  dir: string,
): PlatformContentRoot | undefined {
  const wanted = toPosix(dir).replace(/^\.?\//, '').replace(/\/+$/, '');
  let best: PlatformContentRoot | undefined;
  let bestLen = -1;
  for (const root of profile.contentRoots) {
    const candidate = rootPath(cfg, root);
    const matches = candidate === '' || wanted === candidate || wanted.startsWith(`${candidate}/`);
    if (matches && candidate.length > bestLen) {
      best = root;
      bestLen = candidate.length;
    }
  }
  return best;
}

/**
 * The date-prefix rule that applies to a destination directory.
 *
 * A directory no content root claims gets `optional`: the profile has said
 * nothing about that folder, and inventing a rule for it would rename a file the
 * configuration deliberately placed.
 */
export function datePrefixRuleFor(
  cfg: Zer0Config,
  profile: PlatformProfile,
  dir: string,
): DatePrefixRule {
  return contentRootFor(cfg, profile, dir)?.filename.datePrefix ?? 'optional';
}

/**
 * Reconcile the planned destination with what the platform allows.
 *
 * The *directory* comes from the plan, because `destinationFolder` already chose
 * it from the registered content folders — which, on a site that registered
 * none, `resolveConfig` derives from these very content roots. The *filename* is
 * the platform's call: `required` means Jekyll-style `YYYY-MM-DD-slug.md` and
 * `forbidden` means a plain slug, because MkDocs, Hugo and Astro serve the
 * filename as part of the URL and a date in it becomes a date in the permalink.
 */
export function platformDestination(
  cfg: Zer0Config,
  profile: PlatformProfile,
  plan: PublishPlan,
  now: Date,
): { destination: string; warnings: string[] } {
  const planned = toPosix(plan.destination);
  const cut = planned.lastIndexOf('/');
  const dir = cut === -1 ? '' : planned.slice(0, cut);
  const base = cut === -1 ? planned : planned.slice(cut + 1);

  const rule = datePrefixRuleFor(cfg, profile, dir);
  const datePattern = filenameDateRe(profile);
  const hasPrefix = datePattern.test(base);
  const warnings: string[] = [];

  let name = base;
  if (rule === 'required' && !hasPrefix) {
    name = `${formatDate(now, 'yyyy-MM-dd', cfg.date.timezone)}-${base}`;
    warnings.push(
      `warning: ${profile.id} requires a date in the filename; wrote ${name} instead of ${base}`,
    );
  } else if (rule === 'forbidden' && hasPrefix) {
    name = base.replace(datePattern, '');
    warnings.push(
      `warning: ${profile.id} serves the filename as the slug and takes no date prefix; ` +
        `wrote ${name} instead of ${base}`,
    );
  }

  return { destination: dir === '' ? name : `${dir}/${name}`, warnings };
}

// ---------------------------------------------------------------------------
// The front matter, read out of the profile
// ---------------------------------------------------------------------------

/** The `formatDate` pattern for a profile's declared date shape. */
function datePatternFor(cfg: Zer0Config, profile: PlatformProfile): string {
  switch (profile.frontMatter.dateFormat) {
    case 'rfc3339':
      return "yyyy-MM-dd'T'HH:mm:ssXXX";
    case 'iso-ms':
      return "yyyy-MM-dd'T'HH:mm:ss.SSSXXX";
    case 'date':
    default:
      // `date` means a bare calendar day. The configured format is honoured only
      // when it *is* one, so a site that writes `yyyy-MM-dd HH:mm:ss ZZ` for
      // Jekyll does not get that shape smuggled into a Hugo file.
      return cfg.date.format.includes('H') ? 'yyyy-MM-dd' : cfg.date.format;
  }
}

/** The key a platform publishes its date under — the first it declares. */
function publishDateKey(profile: PlatformProfile): string {
  return profile.frontMatter.dateKeys.publish[0] ?? 'date';
}

/**
 * The front matter a publish stamps onto a new page.
 *
 * Every key is either the site's own configuration (title and description field
 * names, which belong to the person) or the profile's (the date key and format,
 * the draft convention, the thumbnail key). Nothing here is a per-platform
 * literal, which is the property that keeps a sixth platform a table entry.
 */
export function platformFrontMatter(
  cfg: Zer0Config,
  profile: PlatformProfile,
  plan: PublishPlan,
  now: Date,
): FrontMatter {
  const data: FrontMatter = {};
  data[cfg.seo.titleField] = plan.title;
  if (plan.description !== '') {
    data[cfg.seo.descriptionField] = plan.description;
  }
  data[publishDateKey(profile)] = formatDate(now, datePatternFor(cfg, profile), cfg.date.timezone);

  const draft = profile.frontMatter.draft;
  if (draft.type === 'boolean') {
    // Publishing means "not a draft" — inverted when the field marks published.
    data[draft.name] = draft.invert === true;
  }
  if (plan.link !== '') {
    data.link = plan.link;
  }
  if (plan.image !== '') {
    data[profile.frontMatter.thumbnailKeys[0] ?? 'image'] = plan.image;
  }
  return data;
}

// ---------------------------------------------------------------------------
// The factory
// ---------------------------------------------------------------------------

/**
 * The id a profile's target answers to.
 *
 * `governanceTarget` is the profile's own answer (`jekyll` for Jekyll and its
 * zer0-mistakes overlay, the platform id otherwise), and it is the key
 * `targetFor` looks up in the registry — so a target built on the fly must
 * answer to the same name that missed the registry, or the ledger would record a
 * target string nothing resolves.
 */
export function targetIdFor(profile: PlatformProfile): string {
  return (profile.governanceTarget || profile.id).trim().toLowerCase();
}

/**
 * The publish target for whichever platform `profile` describes.
 *
 * One factory covers `mkdocs`, `hugo`, `docusaurus`, `astro`, `wikijs` and the
 * `generic` fallback, because they differ only in data: where content lives,
 * whether the filename carries a date, which front-matter dialect and keys the
 * generator reads. Jekyll keeps its own `jekyllTarget` — it is registered, so
 * `targetFor` resolves it from the registry and never reaches this factory.
 */
export function platformFileTarget(profile: PlatformProfile): PublishTarget {
  const id = targetIdFor(profile);
  // Every key `build` stamps from the clock, so `artifactIdentity` can tell
  // "the same page, rebuilt later" from "a different page, same name".
  const dateKeys = [...new Set([publishDateKey(profile), ...profile.frontMatter.dateKeys.publish])];

  const build = (cfg: Zer0Config, preview: Preview): PlatformArtifact => {
    const plan = requirePlan(preview);
    const now = new Date();
    const dialect = profile.frontMatter.dialects[0] ?? cfg.frontMatter.format;
    const opts = serializeOptions(cfg, dialect);

    const { destination, warnings } = platformDestination(cfg, profile, plan, now);
    const data = platformFrontMatter(cfg, profile, plan, now);
    const body = `\n${preview.commentary.trim()}\n`;

    return {
      target: id,
      path: destination,
      frontMatter: data,
      body,
      contents: stitch(null, serializeFrontMatter(data, opts), body, opts.format),
      warnings,
    };
  };

  return {
    id,

    async build(cfg: Zer0Config, preview: Preview): Promise<PlatformArtifact> {
      return build(cfg, preview);
    },

    async send(
      cfg: Zer0Config,
      preview: Preview,
      deps: PublishDeps,
    ): Promise<{ urn: string; warnings?: string[] }> {
      const artifact = isPlatformArtifact(preview.artifact, id)
        ? preview.artifact
        : build(cfg, preview);
      const written = await writeArtifactExclusively(
        cfg,
        id,
        artifact.path,
        artifact.contents,
        deps,
        dateKeys,
      );
      return { urn: written.urn, warnings: [...artifact.warnings, ...written.warnings] };
    },
  };
}
