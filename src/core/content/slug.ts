/**
 * Slug generation — the URL a page will live at, derived from its title.
 *
 * `slugTemplate` decides the shape, and its four tokens are checked in an
 * **else-if chain**: the first one present wins and the rest are ignored. That
 * is Front Matter's behaviour and it is preserved exactly, because a template
 * is a permalink scheme — changing which token wins would silently re-slug
 * every future page of a site that already has thousands of URLs committed.
 *
 * | Token | Value |
 * |---|---|
 * | `{{title}}` | the title lowercased with spaces as dashes — punctuation kept |
 * | `{{seoTitle}}` | the full `slugify` pipeline: punctuation and stop words dropped |
 * | `{{fileName}}` | the file's basename without its extension |
 * | `{{sluggedFileName}}` / `{{slugifiedFileName}}` | that basename, slugified |
 *
 * Whatever the chain produced is then run through the time and front-matter
 * tokens, so `blog/{{year}}/{{seoTitle}}` and `{{fm.category}}/{{seoTitle}}`
 * both work. With no template configured at all, the slug is `slugify(title)`.
 *
 * The stop-word list and the transliteration table live in `shared/text.ts` and
 * come from FM verbatim: slugs generated here have to match the ones already
 * committed in a repository that used to run Front Matter.
 */

import * as path from 'node:path';

import { JEKYLL_PROFILE } from '../platform/profiles/jekyll';
import { slugify } from '../shared/text';
import type { ContentType, PlatformProfile, Zer0Config } from '../shared/types';
import type { FrontMatter } from './frontmatter';
import { processFmPlaceholders, processTimePlaceholders } from './placeholders';

function baseName(filePath: string | undefined): string {
  if (!filePath) {
    return '';
  }
  return path.parse(filePath).name;
}

/**
 * The slug for `title`, per the content type's template (falling back to the
 * workspace template, and to `slugify` when neither is set).
 *
 * A content type may set `slugTemplate: null` to mean "no opinion" — it then
 * inherits the workspace template, which is FM's reading of the same value.
 * `data` is optional and only needed by templates that use `{{fm.…}}`.
 */
export function createSlug(
  cfg: Zer0Config,
  title: string,
  ct: ContentType | undefined,
  filePath?: string,
  data: FrontMatter = {},
): string {
  if (!title) {
    return '';
  }

  const template = ct?.slugTemplate ?? cfg.slug.template;
  if (typeof template !== 'string' || template.trim() === '') {
    return slugify(title, cfg.slug.stopWords);
  }

  let out = template;
  if (out.includes('{{title}}')) {
    out = out.split('{{title}}').join(title.toLowerCase().replace(/\s/g, '-'));
  } else if (out.includes('{{seoTitle}}')) {
    out = out.split('{{seoTitle}}').join(slugify(title, cfg.slug.stopWords));
  } else if (out.includes('{{fileName}}')) {
    out = out.split('{{fileName}}').join(baseName(filePath));
  } else if (out.includes('{{sluggedFileName}}')) {
    out = out.split('{{sluggedFileName}}').join(slugify(baseName(filePath), cfg.slug.stopWords));
  } else if (out.includes('{{slugifiedFileName}}')) {
    out = out.split('{{slugifiedFileName}}').join(slugify(baseName(filePath), cfg.slug.stopWords));
  }

  out = processTimePlaceholders(out, cfg);
  return processFmPlaceholders(out, data, cfg);
}

/**
 * The slug as it is written into the front matter: the configured prefix and
 * suffix wrapped around it. Kept separate from `createSlug` because the
 * undecorated form is what filenames and `{{slug}}` use.
 */
export function decorateSlug(cfg: Zer0Config, slug: string): string {
  if (!slug) {
    return slug;
  }
  return `${cfg.slug.prefix}${slug}${cfg.slug.suffix}`;
}

/**
 * Where the file would move if `slug.alignFilename` is honoured, or
 * `undefined` when it should stay put — the setting is off, the slug is empty,
 * the name already matches, or the file is a page-bundle `index`.
 *
 * A leading date prefix (`2026-07-31-`) survives the rename: it is part of how
 * a Jekyll-shaped site orders its posts, not part of the slug. Renaming a page
 * bundle would move a whole directory, which is a decision for the command that
 * can ask the user, so it is refused here.
 *
 * Both of those rules are the *platform's*, not this module's, which is why
 * they arrive in a `PlatformProfile` (decision D12). Hugo has no filename date
 * to preserve and Docusaurus' `01-` prefix is a sidebar position rather than a
 * date, so a profile that says `filenameDate: null` renames the whole stem —
 * which is the correct answer there and would have been a bug here. The default
 * is `JEKYLL_PROFILE`, whose values are the literals this function used to
 * carry, so a caller that has not resolved a platform behaves exactly as before.
 */
export function alignedFilePath(
  cfg: Zer0Config,
  filePath: string,
  slug: string,
  profile: PlatformProfile = JEKYLL_PROFILE,
): string | undefined {
  if (!cfg.slug.alignFilename || !slug) {
    return undefined;
  }

  const parsed = path.parse(filePath);
  if (profile.frontMatter.bundleNames.includes(parsed.name.toLowerCase())) {
    return undefined;
  }

  // `[0]` rather than `[1]`: the profile's pattern captures the date without
  // its trailing dash, and what is re-attached to the new name is the whole
  // matched prefix, dash included.
  const datePrefix = profile.frontMatter.filenameDate?.exec(parsed.name)?.[0] ?? '';
  const safeSlug = slug.split(/[\\/]+/).filter(Boolean).join('-');
  if (safeSlug === '') {
    return undefined;
  }

  const nextName = `${datePrefix}${safeSlug}${parsed.ext}`;
  if (nextName === parsed.base) {
    return undefined;
  }
  return path.join(parsed.dir, nextName);
}
