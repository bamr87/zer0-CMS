/**
 * Reading a site's own configuration file — and, just as importantly, saying
 * when it could not be read.
 *
 * `_config.yml`, `mkdocs.yml` and `hugo.toml` all answer questions a CMS needs:
 * where content lives, what the URLs look like, what the site is called. They
 * are also real files written by people, and real `_config.yml` files in this
 * fleet use YAML anchors and aliases (`&title`, `*name`, `<<:`) that the
 * hand-rolled subset parser cannot resolve — by design, since resolving them
 * would mean a YAML implementation, and the zero-dependency rule says no.
 *
 * So the contract of this module is: **an anchor becomes a warning, never a
 * guessed value.** `SiteConfigFacts.warnings` exists for exactly that, and
 * every field is `null` when the file did not say. A guessed `baseurl` is worse
 * than no `baseurl`: it produces URLs that look right and are wrong, and the
 * ledger is keyed by URL.
 *
 * The same rule covers configuration that is *code*. Docusaurus and Astro
 * configure themselves in JavaScript; this module reads none of it and says so
 * in a warning, leaving the profile's documented defaults in place. A regex
 * over somebody's TypeScript would eventually read a value out of a comment.
 *
 * The field names are Jekyll-flavoured because Jekyll is the anchor profile,
 * and the other platforms are mapped onto them rather than given fields of
 * their own: MkDocs' `site_name` is a `title`, Hugo's `contentDir` is a
 * `docsDir`, Hugo's `[permalinks]` table is a set of `collections`. One shape
 * that every reader understands beats six shapes each reader must switch on.
 */

import { asBool, asString, parseTomlFlat, parseYamlSubset } from '../content/frontmatter';
import type { FmValue, FrontMatter } from '../content/frontmatter';
import type { PlatformProfile, SiteConfigFacts } from '../shared/types';

/** Facts with nothing in them — the honest answer for a site with no config. */
export function emptySiteConfigFacts(): SiteConfigFacts {
  return {
    title: null,
    url: null,
    baseurl: null,
    collectionsDir: null,
    collections: {},
    permalink: null,
    docsDir: null,
    useDirectoryUrls: null,
    warnings: [],
  };
}

/**
 * An anchor is a label on a value, so the value is still right there.
 *
 * `parseYamlSubset` keeps both YAML back-references literally: `"*base"` for an
 * alias and `"&name pages"` for an anchored scalar. They are not the same
 * problem. An **alias** points at a value defined somewhere else, and resolving
 * it needs a real parser — so it stays unknown. An **anchor** merely names the
 * scalar it is attached to, and `collections_dir: &collections_dir pages`
 * says `pages` as plainly as the unanchored form does. Reading it is not a
 * guess; refusing to read it is a bug.
 *
 * That bug was real: it-journey.dev anchors its `collections_dir`, and treating
 * the anchor as unresolvable made every one of that site's 409 content files
 * invisible to this console — a CMS that cannot see a page cannot help with it.
 *
 * Returns the value with the anchor stripped, or `null` when the string is
 * genuinely unresolvable.
 */
function anchoredValue(value: string): string | null {
  const match = /^&[A-Za-z0-9_-]+\s+(.*)$/u.exec(value);
  const inner = match?.[1]?.trim();
  return inner !== undefined && inner !== '' && !inner.startsWith('*') ? inner : null;
}

/** Does this string carry a YAML construct that cannot be resolved here? */
function unresolved(value: string): 'alias' | 'anchor' | null {
  if (value.startsWith('*')) {
    return 'alias';
  }
  // A bare `&name` with nothing after it anchors the *next* node, which this
  // parser did not keep — that one really is unknown.
  if (value.startsWith('&')) {
    return anchoredValue(value) === null ? 'anchor' : null;
  }
  return null;
}

/** A record for `key`, or `undefined` when the value is not a mapping. */
function asMap(value: FmValue | undefined): FrontMatter | undefined {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    return value;
  }
  return undefined;
}

/**
 * A reader that records why it returned nothing.
 *
 * Every field of `SiteConfigFacts` goes through this, so "the file did not say"
 * and "the file said something this parser cannot resolve" are different
 * outcomes with different consequences — the first is silence, the second is a
 * line in `warnings` naming the key and the construct.
 */
class FactReader {
  readonly warnings: string[] = [];

  constructor(
    private readonly data: FrontMatter,
    private readonly file: string,
  ) {}

  /** The first of `keys` that holds a resolvable scalar, else `null`. */
  string(...keys: string[]): string | null {
    for (const key of keys) {
      const raw = this.data[key];
      if (raw === undefined || raw === null) {
        continue;
      }
      const value = asString(raw).trim();
      if (value === '') {
        continue;
      }
      const kind = unresolved(value);
      if (kind !== null) {
        this.warnings.push(
          `${this.file}: \`${key}\` is a YAML ${kind} (${value}); zer0-CMS resolves neither, so the value is unknown rather than guessed`,
        );
        continue;
      }
      return anchoredValue(value) ?? value;
    }
    return null;
  }

  /** The first of `keys` that holds a boolean, else `null` — never a default. */
  boolean(...keys: string[]): boolean | null {
    for (const key of keys) {
      const raw = this.data[key];
      if (raw === undefined || raw === null) {
        continue;
      }
      if (typeof raw === 'boolean') {
        return raw;
      }
      const text = asString(raw).trim();
      if (text === '') {
        continue;
      }
      const kind = unresolved(text);
      if (kind !== null) {
        this.warnings.push(
          `${this.file}: \`${key}\` is a YAML ${kind}; the flag is left unknown`,
        );
        continue;
      }
      return asBool(raw);
    }
    return null;
  }

  map(key: string): FrontMatter | undefined {
    return asMap(this.data[key]);
  }

  list(key: string): string[] | undefined {
    const raw = this.data[key];
    return Array.isArray(raw) ? raw.map((item) => asString(item).trim()).filter((s) => s !== '') : undefined;
  }
}

/**
 * Merge keys and aliases the parser stepped over.
 *
 * `<<: *defaults` parses as a key literally named `<<`, and a sequence item
 * `- *base` is kept as the string `"*base"`. Neither reaches a field this
 * module reads, so without this scan a config built entirely out of anchors
 * would produce empty facts and no explanation at all.
 */
function structuralWarnings(text: string, file: string): string[] {
  const out: string[] = [];
  if (/^\s*<<\s*:/m.test(text)) {
    out.push(
      `${file}: uses YAML merge keys (\`<<:\`); the merged values are not resolved, so anything they supply is missing here`,
    );
  }
  if (/^\s*[A-Za-z0-9_.-]+\s*:\s*&[A-Za-z0-9_-]+/m.test(text)) {
    out.push(`${file}: declares YAML anchors (\`&name\`); anchored values are read as literal text`);
  }
  return out;
}

/** Jekyll `collections:` — a mapping of options, or a bare list of names. */
function jekyllCollections(reader: FactReader): SiteConfigFacts['collections'] {
  const out: SiteConfigFacts['collections'] = {};
  const mapping = reader.map('collections');
  if (mapping !== undefined) {
    for (const [name, value] of Object.entries(mapping)) {
      const options = asMap(value);
      const permalink = options === undefined ? null : asString(options.permalink).trim() || null;
      // Jekyll's own default is `output: false` for a collection that does not
      // say — `posts` is the exception, and it says so in its own entry.
      const output = options === undefined ? false : asBool(options.output);
      const usable = permalink !== null && unresolved(permalink) === null ? permalink : null;
      out[name] = { permalink: usable, output };
    }
    return out;
  }
  for (const name of reader.list('collections') ?? []) {
    out[name] = { permalink: null, output: false };
  }
  return out;
}

/**
 * Hugo's `[permalinks]` table read as collections.
 *
 * Hugo has no collections — it has sections, and `permalinks` maps a section to
 * a URL template. That is the same question `collections[].permalink` answers
 * for Jekyll, so it lands in the same field rather than in a Hugo-shaped one
 * that only Hugo code could read.
 */
function hugoSections(data: FrontMatter): SiteConfigFacts['collections'] {
  const out: SiteConfigFacts['collections'] = {};
  const permalinks = asMap(data.permalinks);
  if (permalinks === undefined) {
    return out;
  }
  for (const [section, value] of Object.entries(permalinks)) {
    const template = asString(value).trim();
    if (template !== '' && unresolved(template) === null) {
      out[section] = { permalink: template, output: true };
    }
  }
  return out;
}

/**
 * What the site's own configuration file says, per its platform's dialect.
 *
 * `text` is `undefined` when the file is not there, which is a normal state and
 * produces empty facts with no warning at all — a site that has not been
 * configured yet is not a site with a problem.
 */
export function readSiteConfigFacts(
  profile: PlatformProfile,
  text: string | undefined,
): SiteConfigFacts {
  const facts = emptySiteConfigFacts();
  const file = profile.siteConfig.file ?? '(no site config)';

  if (profile.siteConfig.format === 'none' || profile.siteConfig.file === null) {
    return facts;
  }
  if (profile.siteConfig.format === 'js') {
    // Reading this would mean evaluating somebody's JavaScript, or a regex that
    // eventually finds a value inside a comment. The profile's documented
    // defaults are used instead, and the warning says which file was skipped.
    facts.warnings.push(
      `${file} is JavaScript; zer0-CMS reads no JavaScript, so the profile's documented defaults are used — state any change in zer0.json \`platform.overrides\``,
    );
    return facts;
  }
  if (text === undefined) {
    return facts;
  }

  const data =
    profile.siteConfig.format === 'toml' ? parseTomlFlat(text) : parseYamlSubset(text);
  const reader = new FactReader(data, file);

  if (profile.id === 'mkdocs') {
    facts.title = reader.string('site_name');
    facts.url = reader.string('site_url');
    facts.docsDir = reader.string('docs_dir');
    facts.useDirectoryUrls = reader.boolean('use_directory_urls');
  } else if (profile.id === 'hugo') {
    facts.title = reader.string('title');
    facts.url = reader.string('baseURL', 'baseurl');
    facts.docsDir = reader.string('contentDir');
    facts.collections = hugoSections(data);
  } else {
    // Jekyll, and anything else declaring a YAML site config: Jekyll's key
    // vocabulary is the shared one, so `generic` gets it for free if a site
    // happens to carry a `_config.yml`-shaped file.
    facts.title = reader.string('title');
    facts.url = reader.string('url');
    facts.baseurl = reader.string('baseurl');
    facts.collectionsDir = reader.string('collections_dir');
    facts.permalink = reader.string('permalink');
    facts.collections = jekyllCollections(reader);
  }

  facts.warnings.push(...reader.warnings, ...structuralWarnings(text, file));
  return facts;
}
