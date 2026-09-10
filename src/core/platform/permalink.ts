/**
 * Where a page lives — the URL it serves at, the directories its content sits
 * in, and the directories that are build output rather than content.
 *
 * Six generators, six different answers, and the differences are not cosmetic:
 * Jekyll hides the underscore of a collection folder and expands a template of
 * `:tokens`; MkDocs turns `a/b.md` into `/a/b/` or `/a/b.html` depending on one
 * boolean; Hugo lets a page override its own URL outright; Docusaurus strips
 * `01-` number prefixes that mean sidebar order rather than anything about the
 * address; Astro's URL is defined by a route file this code never sees.
 *
 * Three rules hold across all of them.
 *
 * **The page's own word wins.** A `permalink:` in front matter is verbatim, and
 * is checked before anything is derived. That is why lifehacker.dev's posts
 * serve at `/hacks/<slug>/` rather than the collection default — and why
 * "fixing" one of those permalinks to match the collection would break every
 * inbound link to the article.
 *
 * **Dates are read as strings.** `:year/:month/:day` are slices of the date
 * text, never fields of a `Date`. Constructing a `Date` from `2026-07-08` to
 * read its year is how a page published on the 8th ends up filed under the 7th
 * for every reader west of Greenwich.
 *
 * **Nothing here is guessed from a name.** The behaviour is driven by the
 * profile and by what the site's own config actually said; when the config said
 * nothing, the profile's documented default applies and the caller can see it
 * in `ResolvedPlatform.evidence` rather than inferring it.
 */

import { asList, asString } from '../content/frontmatter';
import type { FrontMatter } from '../content/frontmatter';
import type {
  ContentFolder,
  DatePrefixRule,
  PlatformContentRoot,
  PlatformProfile,
  SiteConfigFacts,
} from '../shared/types';

// ---------------------------------------------------------------------------
// Small string surgery — no `Date`, no `path`, no filesystem
// ---------------------------------------------------------------------------

/** POSIX segments of a relative path, with `.` and empties dropped. */
function segmentsOf(rel: string): string[] {
  return rel
    .split('\\')
    .join('/')
    .split('/')
    .filter((segment) => segment !== '' && segment !== '.');
}

function stripExtension(name: string): string {
  return name.replace(/\.[^./]+$/, '');
}

/** The filename stem with the profile's date prefix removed, if it carries one. */
function stemOf(profile: PlatformProfile, fileName: string): string {
  const stem = stripExtension(fileName);
  const re = profile.frontMatter.filenameDate;
  return re === null ? stem : stem.replace(re, '');
}

/**
 * A Docusaurus blog filename's date. It lives here rather than in the profile
 * because it is a rule of one content root, not of the platform: a docs page
 * called `2026-01-01-notes.md` keeps its digits.
 */
const BLOG_DATE_RE = /^(\d{4}-\d{2}-\d{2})-/;

/** `01-intro` → `intro`. Docusaurus number prefixes are order, not identity. */
function stripNumberPrefix(segment: string): string {
  return segment.replace(/^\d+-/, '');
}

/** `2026-07-08…` → `['2026','07','08']`, or `null`. Text only — never a `Date`. */
function dateParts(value: string): [string, string, string] | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (match === null) {
    return null;
  }
  const [, year, month, day] = match;
  return year !== undefined && month !== undefined && day !== undefined ? [year, month, day] : null;
}

/** The path component of an absolute URL — `https://x.dev/README/` → `/README`. */
export function basePathOf(url: string | null): string {
  if (url === null || url.trim() === '') {
    return '';
  }
  const match = /^[a-z][a-z0-9+.-]*:\/\/[^/]+(\/.*)?$/i.exec(url.trim());
  const raw = match?.[1] ?? (url.startsWith('/') ? url : '');
  const trimmed = raw.replace(/\/+$/, '');
  return trimmed === '/' ? '' : trimmed;
}

/** Join a base path and a site-relative one without doubling the slash. */
function withBase(base: string, url: string): string {
  if (base === '') {
    return url;
  }
  return url === '/' ? `${base}/` : `${base}${url}`;
}

/** `['a','b']` → `/a/b/`; an empty list is the site root. */
function dirUrl(segments: readonly string[]): string {
  const kept = segments.filter((segment) => segment !== '');
  return kept.length === 0 ? '/' : `/${kept.join('/')}/`;
}

// ---------------------------------------------------------------------------
// Content roots and skip sets
// ---------------------------------------------------------------------------

/**
 * Does this platform hide the leading underscore of a collection folder?
 *
 * Asked of the profile's own data rather than of its id: Jekyll is the platform
 * whose collections are `_posts` and `_drafts` on disk and `posts` and `drafts`
 * in the URL, and the profile already says that in `contentRoots`. Testing the
 * data keeps the rule with the platform that has it instead of putting a second
 * copy of "if jekyll" in a function that is supposed to be platform-agnostic.
 */
function hidesCollectionUnderscore(profile: PlatformProfile): boolean {
  return profile.contentRoots.some((root) => root.path.startsWith('_'));
}

/**
 * The URL a page gets from its path alone, with nothing else to go on.
 *
 * This is the shape zer0-CMS has always derived for a Jekyll page — extension
 * gone, `YYYY-MM-DD-` gone, the collection folder's underscore gone — expressed
 * over the profile so the other platforms get the parts of it that are true for
 * them and none of the parts that are not. Exported because the ledger key
 * (`governance/publish.ts` `canonicalUrl`) is exactly this derivation, and two
 * copies of a ledger key is two ledgers.
 */
export function permalinkFallback(profile: PlatformProfile, relPath: string): string {
  const segments = segmentsOf(relPath);
  const file = segments.pop() ?? '';
  const stem = stemOf(profile, file);
  const dirs = hidesCollectionUnderscore(profile)
    ? segments.map((segment) => (segment.startsWith('_') ? segment.slice(1) : segment))
    : segments;
  return dirUrl([...dirs, stem]);
}

/**
 * The directories a scan should never walk into for this platform.
 *
 * The base set is the platform-agnostic half — version control, dependencies,
 * this repository's own build output — and the profile contributes its
 * generator's output directory on top. A site's `_site/` and a Hugo site's
 * `public/` are the same mistake with different names: a scan that walks into
 * one indexes a copy of every page it just indexed, and the CMS then reports
 * twice as much content as the site has.
 */
export function skipDirsFor(
  profile: PlatformProfile,
  base: ReadonlySet<string>,
): ReadonlySet<string> {
  const out = new Set(base);
  for (const dir of profile.outputDirs) {
    out.add(dir);
  }
  return out;
}

/** The content root whose `path` best matches this relative path, if any. */
function rootForPath(
  profile: PlatformProfile,
  facts: SiteConfigFacts,
  relPath: string,
): { root: PlatformContentRoot; within: string[] } | undefined {
  const segments = segmentsOf(relPath);
  const prefix = segmentsOf(facts.collectionsDir ?? facts.docsDir ?? '');
  const relative = segments.slice(0, prefix.length).join('/') === prefix.join('/')
    ? segments.slice(prefix.length)
    : segments;

  let best: { root: PlatformContentRoot; within: string[] } | undefined;
  for (const root of profile.contentRoots) {
    const rootSegments = segmentsOf(root.path);
    if (rootSegments.length === 0) {
      continue;
    }
    if (relative.slice(0, rootSegments.length).join('/') !== rootSegments.join('/')) {
      continue;
    }
    if (best === undefined || rootSegments.length > segmentsOf(best.root.path).length) {
      best = { root, within: relative.slice(rootSegments.length) };
    }
  }
  return best;
}

/**
 * What a filename in this folder is allowed to say about dates.
 *
 * `folderRel` is workspace-relative. A folder that matches no content root gets
 * `optional`, which is the profile declining to have an opinion rather than
 * permission — the same honesty `health: -1` uses for a score nobody measured.
 *
 * Named `…At` rather than `…For` because `governance/fileTarget.ts` declares a
 * `datePrefixRuleFor(cfg, profile, dir)` of its own, and two modules exporting
 * one name makes the core barrel's `export *` ambiguous for everybody. The two
 * answer the same question from different sides and are worth collapsing; until
 * somebody does, they must not share a name.
 */
export function datePrefixRuleAt(profile: PlatformProfile, folderRel: string): DatePrefixRule {
  const segments = segmentsOf(folderRel);
  let best: { rule: DatePrefixRule; depth: number } | undefined;
  for (const root of profile.contentRoots) {
    const rootSegments = segmentsOf(root.path);
    if (rootSegments.length === 0) {
      continue;
    }
    // A content root matches when its segments appear in order anywhere in the
    // folder path: `pages/_posts/corp` is inside the `_posts` root even though
    // `collections_dir` moved it and a section folder nests below it.
    for (let start = 0; start + rootSegments.length <= segments.length; start += 1) {
      if (segments.slice(start, start + rootSegments.length).join('/') === rootSegments.join('/')) {
        if (best === undefined || rootSegments.length > best.depth) {
          best = { rule: root.filename.datePrefix, depth: rootSegments.length };
        }
        break;
      }
    }
  }
  return best?.rule ?? 'optional';
}

/**
 * The content folders a site has, derived from its *own* configuration.
 *
 * This is what makes a platform profile useful rather than theoretical: point
 * zer0-CMS at a sister site with no `zer0.json` at all and it still knows where
 * the content is, because `collections_dir` and `collections:` in `_config.yml`
 * (or `docs_dir` in `mkdocs.yml`, or `contentDir` in `hugo.toml`) already say.
 *
 * Paths come back absolute, POSIX-joined onto `root`, with `originalPath` set to
 * the site-relative spelling so a round-trip into `zer0.json` writes the short
 * form a person would have typed. `generic` derives nothing and returns an empty
 * list: no marker file means no claim about where content lives.
 */
export function contentRootsFor(
  profile: PlatformProfile,
  facts: SiteConfigFacts,
  root: string,
): ContentFolder[] {
  const base = root.replace(/[/\\]+$/, '');
  const out: ContentFolder[] = [];
  const seen = new Set<string>();

  const push = (rel: string, title: string): void => {
    const clean = segmentsOf(rel).join('/');
    const key = clean === '' ? '.' : clean;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    out.push({
      title,
      path: clean === '' ? base : `${base}/${clean}`,
      originalPath: clean === '' ? '.' : clean,
    });
  };

  const declared = Object.keys(facts.collections);
  if (profile.id === 'jekyll' && declared.length > 0) {
    const dir = segmentsOf(facts.collectionsDir ?? '').join('/');
    for (const name of declared) {
      push(dir === '' ? `_${name}` : `${dir}/_${name}`, titleFor(name));
    }
    // Jekyll builds every markdown file under the source directory, not only
    // the ones inside a declared collection: a site's loose pages and its
    // un-collected sections are real published pages. Deriving collections
    // alone made the console silently blind to fourteen of lifehacker.dev's
    // 382 files — and a CMS that cannot see a page cannot report a problem with
    // it, which is worse than reporting nothing at all. The collections are
    // pushed first, so the longest-prefix match still binds a post to `_posts`
    // rather than to this.
    if (dir !== '') {
      push(dir, titleFor(dir.split('/').pop() ?? 'pages'));
    }
    return out;
  }

  if (profile.id === 'mkdocs') {
    push(facts.docsDir ?? 'docs', 'Docs');
    return out;
  }

  if (profile.id === 'hugo') {
    push(facts.docsDir ?? 'content', 'Content');
    return out;
  }

  for (const contentRoot of profile.contentRoots) {
    // A `.` root means "the whole site", which is only a real answer for a
    // platform whose file tree *is* its page tree — Wiki.js. For everything
    // else it is the Jekyll loose-pages root, and registering the workspace
    // root as a content folder would index the repository's own README.
    if (contentRoot.path === '.' && profile.id !== 'wikijs') {
      continue;
    }
    push(contentRoot.path, titleFor(contentRoot.collection));
  }
  return out;
}

function titleFor(name: string): string {
  const clean = name.replace(/^_/, '').replace(/[-_]+/g, ' ').trim();
  return clean === '' ? 'Content' : clean.charAt(0).toUpperCase() + clean.slice(1);
}

// ---------------------------------------------------------------------------
// Permalinks
// ---------------------------------------------------------------------------

/**
 * Expand a `:token` permalink template.
 *
 * Jekyll and Hugo both spell their templates this way — Jekyll with
 * `:collection :path :name :title :slug :categories :year :month :day
 * :output_ext`, Hugo with `:section :sections :slug :slugorfilename :filename
 * :contentbasename :year :month :day` — so one expander serves both and the
 * caller supplies the vocabulary. An unknown `:token` is left standing rather
 * than blanked: a template this code does not understand should look wrong in
 * the UI, not silently produce a plausible URL.
 */
function expandTemplate(
  template: string,
  values: Readonly<Record<string, string>>,
): string {
  // Longest names first: `:title` must not be eaten by a shorter `:t` rule, and
  // `:output_ext` must not be split by `:output`.
  const tokens = Object.keys(values).sort((a, b) => b.length - a.length);
  let out = template;
  for (const token of tokens) {
    out = out.split(`:${token}`).join(values[token] ?? '');
  }
  // Collapse the gaps left by tokens that had no value (`:categories` on an
  // uncategorised post), then restore the leading slash.
  const trailing = out.endsWith('/');
  const joined = segmentsOf(out).join('/');
  if (joined === '') {
    return '/';
  }
  return trailing ? `/${joined}/` : `/${joined}`;
}

/** The publication date as text: front matter first, then the filename. */
function dateTextOf(profile: PlatformProfile, relPath: string, data: FrontMatter): string {
  for (const key of profile.frontMatter.dateKeys.publish) {
    const value = asString(data[key]).trim();
    if (value !== '') {
      return value;
    }
  }
  const file = segmentsOf(relPath).pop() ?? '';
  const re = profile.frontMatter.filenameDate;
  return re === null ? '' : (re.exec(file)?.[1] ?? '');
}

function jekyllPermalink(
  profile: PlatformProfile,
  facts: SiteConfigFacts,
  relPath: string,
  data: FrontMatter,
): string {
  const segments = segmentsOf(relPath);
  const file = segments.pop() ?? '';
  const stem = stemOf(profile, file);
  const declaredSlug = asString(data[profile.frontMatter.slugKey]).trim();
  const slug = declaredSlug === '' ? stem : declaredSlug;

  const collectionsDir = segmentsOf(facts.collectionsDir ?? '');
  const afterDir =
    segments.slice(0, collectionsDir.length).join('/') === collectionsDir.join('/')
      ? segments.slice(collectionsDir.length)
      : segments;
  const head = afterDir[0] ?? '';
  const collection = head.startsWith('_') ? head.slice(1) : '';
  const within = collection === '' ? afterDir : afterDir.slice(1);

  const declaredTemplate =
    (collection === '' ? null : facts.collections[collection]?.permalink) ??
    (collection === 'posts' ? facts.permalink : null) ??
    profile.contentRoots.find((root) => root.collection === collection)?.permalink ??
    null;

  if (declaredTemplate === null) {
    return withBase(basePathOf(facts.baseurl), permalinkFallback(profile, relPath));
  }

  const date = dateParts(dateTextOf(profile, relPath, data));
  const categories = asList(data.categories)
    .map((value) => value.trim().toLowerCase().split(/\s+/).join('-'))
    .filter((value) => value !== '');

  const url = expandTemplate(declaredTemplate, {
    collection,
    path: within.join('/'),
    name: stem,
    title: slug,
    slug,
    categories: categories.join('/'),
    year: date?.[0] ?? '',
    month: date?.[1] ?? '',
    day: date?.[2] ?? '',
    output_ext: '',
  });
  return withBase(basePathOf(facts.baseurl), url);
}

function mkdocsPermalink(
  profile: PlatformProfile,
  facts: SiteConfigFacts,
  relPath: string,
): string {
  const docsDir = segmentsOf(facts.docsDir ?? 'docs');
  const segments = segmentsOf(relPath);
  const within =
    segments.slice(0, docsDir.length).join('/') === docsDir.join('/')
      ? segments.slice(docsDir.length)
      : segments;
  const file = within.pop() ?? '';
  const stem = stripExtension(file);
  const isIndex = profile.frontMatter.structuralStems.includes(stem.toLowerCase());
  const base = basePathOf(facts.url);

  // `use_directory_urls` defaults to `true` in MkDocs itself; the profile's job
  // is to know the default, and `null` here means the file did not say.
  if (facts.useDirectoryUrls === false) {
    const tail = isIndex ? 'index.html' : `${stem}.html`;
    return withBase(base, `/${[...within, tail].join('/')}`);
  }
  return withBase(base, dirUrl(isIndex ? within : [...within, stem]));
}

function hugoPermalink(
  profile: PlatformProfile,
  facts: SiteConfigFacts,
  relPath: string,
  data: FrontMatter,
): string {
  const contentDir = segmentsOf(facts.docsDir ?? 'content');
  const segments = segmentsOf(relPath);
  const within =
    segments.slice(0, contentDir.length).join('/') === contentDir.join('/')
      ? segments.slice(contentDir.length)
      : segments;
  const file = within.pop() ?? '';
  const stem = stripExtension(file);
  const declaredSlug = asString(data[profile.frontMatter.slugKey]).trim();
  const isBundle = profile.frontMatter.bundleNames.includes(stem.toLowerCase());
  const section = within[0] ?? '';
  const base = basePathOf(facts.url);

  // A branch or leaf bundle IS its directory; naming the bundle file in the URL
  // would give every section page a `/…/_index/` nobody links to.
  const tail = isBundle ? [] : [declaredSlug === '' ? stem : declaredSlug];

  const template = section === '' ? null : (facts.collections[section]?.permalink ?? null);
  if (template === null || isBundle) {
    return withBase(base, dirUrl([...within, ...tail]));
  }

  const date = dateParts(dateTextOf(profile, relPath, data));
  const slugOrFilename = declaredSlug === '' ? stem : declaredSlug;
  const url = expandTemplate(template, {
    section,
    sections: within.join('/'),
    title: slugOrFilename,
    slug: slugOrFilename,
    slugorfilename: slugOrFilename,
    filename: stem,
    contentbasename: stem,
    year: date?.[0] ?? '',
    month: date?.[1] ?? '',
    day: date?.[2] ?? '',
  });
  return withBase(base, url);
}

function docusaurusPermalink(
  profile: PlatformProfile,
  facts: SiteConfigFacts,
  relPath: string,
  data: FrontMatter,
): string {
  const match = rootForPath(profile, facts, relPath);
  const base = basePathOf(facts.baseurl ?? facts.url);
  const segments = match === undefined ? segmentsOf(relPath) : match.within;
  const file = segments.pop() ?? '';
  const routeBase = segmentsOf(
    (match?.root.permalink ?? '/:path/:name/').split('/:')[0] ?? '',
  );

  const declaredSlug = asString(data[profile.frontMatter.slugKey]).trim();
  if (declaredSlug.startsWith('/')) {
    // An absolute `slug:` replaces the whole route below the base URL — not
    // just the last segment — which is the one Docusaurus rule most easily got
    // wrong by treating every slug the same way.
    return withBase(base, dirUrl([...routeBase, ...segmentsOf(declaredSlug)]));
  }

  const dirs = segments.map(stripNumberPrefix);
  const stem = stripNumberPrefix(stripExtension(file));
  const isIndex = profile.frontMatter.structuralStems.includes(stem.toLowerCase());
  const id = declaredSlug === '' ? stem : declaredSlug;

  if (match?.root.collection === 'blog') {
    // Only the blog reads a date out of the filename, which is why the profile
    // itself says `filenameDate: null` — the rule belongs to one root, not to
    // the platform. Front matter still wins: `date:` overrides the path date.
    const fromName = BLOG_DATE_RE.exec(stripExtension(file))?.[1] ?? '';
    const written = asString(data.date).trim();
    const date = dateParts(written === '' ? fromName : written);
    const slug =
      declaredSlug === '' ? stripExtension(file).replace(BLOG_DATE_RE, '') : declaredSlug;
    return withBase(
      base,
      dirUrl([...routeBase, date?.[0] ?? '', date?.[1] ?? '', date?.[2] ?? '', slug]),
    );
  }

  return withBase(base, dirUrl(isIndex ? [...routeBase, ...dirs] : [...routeBase, ...dirs, id]));
}

function astroPermalink(
  profile: PlatformProfile,
  facts: SiteConfigFacts,
  relPath: string,
  data: FrontMatter,
): string {
  const match = rootForPath(profile, facts, relPath);
  const segments = match === undefined ? segmentsOf(relPath) : [...match.within];
  const file = segments.pop() ?? '';
  const stem = stripExtension(file);
  const declaredSlug = asString(data[profile.frontMatter.slugKey]).trim();
  const id = declaredSlug === '' ? stem : declaredSlug;

  if (match?.root.collection === 'pages') {
    const isIndex = profile.frontMatter.structuralStems.includes(stem.toLowerCase());
    return dirUrl(isIndex ? segments : [...segments, id]);
  }
  // A content-collection entry's route is decided by a `[...slug].astro` page
  // this code never reads; `/<collection>/<id>/` is the template convention and
  // the profile says so rather than this function pretending to know.
  return dirUrl([...segments, id]);
}

function wikijsPermalink(relPath: string): string {
  const segments = segmentsOf(relPath);
  const file = segments.pop() ?? '';
  const stem = stripExtension(file);
  // Wiki.js paths have no trailing slash and no extension, and `home` is the
  // wiki root rather than a page called "home".
  if (stem.toLowerCase() === 'home') {
    return segments.length === 0 ? '/' : `/${segments.join('/')}`;
  }
  return `/${[...segments, stem].join('/')}`;
}

/**
 * The URL this page serves at.
 *
 * `relPath` is workspace-relative POSIX; `data` is the page's front matter. The
 * page's own `permalink` (or the platform's equivalent key) wins verbatim
 * before anything is derived, which is the rule that keeps a hand-pinned
 * `/hacks/my-post/` from being "corrected" into a collection default.
 */
export function permalinkOf(
  profile: PlatformProfile,
  facts: SiteConfigFacts,
  relPath: string,
  data: FrontMatter = {},
): string {
  for (const key of profile.frontMatter.permalinkKeys) {
    const value = asString(data[key]).trim();
    if (value !== '') {
      return value;
    }
  }

  switch (profile.id) {
    case 'jekyll':
      return jekyllPermalink(profile, facts, relPath, data);
    case 'mkdocs':
      return mkdocsPermalink(profile, facts, relPath);
    case 'hugo':
      return hugoPermalink(profile, facts, relPath, data);
    case 'docusaurus':
      return docusaurusPermalink(profile, facts, relPath, data);
    case 'astro':
      return astroPermalink(profile, facts, relPath, data);
    case 'wikijs':
      return wikijsPermalink(relPath);
    default:
      return permalinkFallback(profile, relPath);
  }
}
