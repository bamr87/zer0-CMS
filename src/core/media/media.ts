/**
 * Media — find the image a page already has, or say how to get one.
 *
 * zer0-image-generator already solves social imagery for these sites: a
 * three-stage pipeline (an art brief is written from the article, a model
 * renders it, the render is reviewed) that produces a preview image per page
 * and wires it into front matter. A share wants exactly that image, so this
 * module generates nothing. It resolves what the site already produced, and
 * when there is none it emits the request the generator takes as input.
 *
 * Rendering stays in the generator, where the provider matrix, the review stage
 * and the credential chain live. A second renderer here would be a second
 * definition of what a preview image is, and they would drift.
 *
 * ## Why this exists when publishing already reads the image
 *
 * `governance/publish` calls `previewImageValue` and, finding nothing, posts
 * without a thumbnail. That is the right behaviour for one post — a missing
 * image should never block publishing — but it is silent, so a repository can
 * drift into publishing dozens of untreated links without anyone noticing. This
 * module makes the same question askable *across* the content set, before
 * anything is published, and answers it with the generator's own command.
 *
 * It shares `THUMBNAIL_KEYS` and `previewImageValue` with publishing rather than
 * restating them: a page that looks covered in the media report and then
 * publishes without a thumbnail would be worse than no report at all.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { recordSlug } from '../contract/contract';
import { previewImageValue } from '../governance/publish';
import type { ContentRecord } from '../shared/types';
import type { FrontMatter } from '../content/frontmatter';

/** Where the generator writes, and therefore where to look without front matter. */
export const PREVIEW_DIR = path.join('assets', 'images', 'previews');

/** Extensions the generator can emit, in the order they are preferred. */
export const PREVIEW_EXTS = ['.png', '.jpg', '.jpeg', '.webp', '.svg'] as const;

/** How an image was found — or that it was not. */
export type MediaSource = 'frontmatter' | 'convention' | 'none';

export interface Media {
  /** Workspace-relative path to the image, or `''` when there is none. */
  path: string;
  source: MediaSource;
  /** Size on disk, `0` when unknown or absent. */
  bytes: number;
  /** The generator request. Populated only when `source` is `'none'`. */
  brief: string;
}

/** Whether a page has an image at all. */
export function hasMedia(media: Media): boolean {
  return media.source !== 'none';
}

/**
 * The request zer0-image-generator's first stage takes.
 *
 * It names the article and stops. The generator writes the actual art direction
 * from the article's own text, and inventing visual direction here would
 * compete with the stage that does it properly — badly, since this module has
 * read the front matter and not the piece.
 */
export function briefFor(record: Pick<ContentRecord, 'path' | 'title'>): string {
  const slug = recordSlug(record);
  const title = record.title || slug;
  return (
    `generate a preview image for ${record.path} (title: ${title}); ` +
    `run: jekyll preview-images --only ${slug}`
  );
}

async function sizeOf(absolute: string): Promise<number | undefined> {
  try {
    const stat = await fs.stat(absolute);
    return stat.isFile() ? stat.size : undefined;
  } catch {
    return undefined;
  }
}

/** The declared image, if the file is actually there. */
async function fromFrontMatter(
  root: string,
  data: FrontMatter | undefined,
): Promise<{ rel: string; bytes: number } | undefined> {
  if (!data) {
    return undefined;
  }
  const declared = previewImageValue(data);
  if (declared === '') {
    return undefined;
  }
  // A leading slash is site-absolute, not filesystem-absolute — the generator
  // writes `/assets/…` into front matter because that is what the rendered
  // page needs, and resolving it against the filesystem root would miss.
  const rel = declared.replace(/^\/+/, '');
  const bytes = await sizeOf(path.join(root, rel));
  return bytes === undefined ? undefined : { rel, bytes };
}

/** The conventional path, for a page whose front matter was never wired up. */
async function fromConvention(
  root: string,
  slug: string,
): Promise<{ rel: string; bytes: number } | undefined> {
  for (const ext of PREVIEW_EXTS) {
    const rel = path.join(PREVIEW_DIR, `${slug}${ext}`);
    const bytes = await sizeOf(path.join(root, rel));
    if (bytes !== undefined) {
      return { rel, bytes };
    }
  }
  return undefined;
}

/**
 * Resolve the image a page would share with.
 *
 * Front matter first because the generator writes it there, so it is
 * authoritative wherever the pipeline has run; the conventional path second,
 * which catches an image produced before the front matter was wired up. A
 * declared path that does not exist on disk falls through to the convention
 * rather than being reported as found — a broken link is not coverage.
 */
export async function resolveMedia(
  root: string,
  record: Pick<ContentRecord, 'path' | 'title'>,
  data?: FrontMatter,
): Promise<Media> {
  const declared = await fromFrontMatter(root, data);
  if (declared) {
    return { path: declared.rel, source: 'frontmatter', bytes: declared.bytes, brief: '' };
  }
  const conventional = await fromConvention(root, recordSlug(record));
  if (conventional) {
    return { path: conventional.rel, source: 'convention', bytes: conventional.bytes, brief: '' };
  }
  return { path: '', source: 'none', bytes: 0, brief: briefFor(record) };
}

export interface MediaCoverage {
  /** One row per record, in the order given. */
  items: Array<{ record: Pick<ContentRecord, 'path' | 'title'>; media: Media }>;
  found: number;
  missing: number;
}

/**
 * Resolve images for a set of records.
 *
 * Sequential rather than `Promise.all`: this walks the whole content set, and a
 * few hundred parallel `stat` calls is how a large repository exhausts the file
 * descriptor table. The work is milliseconds either way.
 */
export async function mediaCoverage(
  root: string,
  records: ReadonlyArray<Pick<ContentRecord, 'path' | 'title'>>,
  frontMatterOf?: (record: Pick<ContentRecord, 'path' | 'title'>) => FrontMatter | undefined,
): Promise<MediaCoverage> {
  const items: MediaCoverage['items'] = [];
  let found = 0;
  for (const record of records) {
    const media = await resolveMedia(root, record, frontMatterOf?.(record));
    items.push({ record, media });
    if (hasMedia(media)) {
      found += 1;
    }
  }
  return { items, found, missing: items.length - found };
}

/** The coverage report as text, listing only what is missing. */
export function renderCoverage(coverage: MediaCoverage): string {
  if (coverage.items.length === 0) {
    return 'media: no content to check.';
  }
  const lines = [
    `media: ${coverage.found} of ${coverage.items.length} page(s) have a preview image.`,
  ];
  if (coverage.missing === 0) {
    return lines.join('\n');
  }
  lines.push('', `${coverage.missing} without one:`);
  for (const { record, media } of coverage.items) {
    if (!hasMedia(media)) {
      lines.push(`  ${record.path}`);
      lines.push(`    ${media.brief}`);
    }
  }
  lines.push('');
  lines.push('zer0-image-generator produces these; this lane only reuses them.');
  return lines.join('\n');
}
