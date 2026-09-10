/**
 * The zer0-mistakes overlay — a *theme*, laid over Jekyll, never a platform of
 * its own.
 *
 * Every site in this fleet (lifehacker.dev, it-journey.dev, bash-365.com,
 * irony-works, ai-world-view) is a Jekyll site on `remote_theme:
 * bamr87/zer0-mistakes` with `collections_dir: pages`. The temptation is to
 * give that combination a `PlatformId` of its own, and decision D12 refuses:
 * two entries in the profile table that have to be kept in sync is one entry
 * too many, and the day the theme changes something Jekyll-shaped, only one of
 * them would learn.
 *
 * So this file exports a `Partial<PlatformProfile>` that is merged onto
 * `JEKYLL_PROFILE` when the probe fires, and `ResolvedPlatform.profile.id`
 * stays `'jekyll'` with `overlay: 'zer0-mistakes'` beside it. Anything that
 * wants to know "is this a fleet site?" asks about the overlay; anything that
 * wants to know "how do I read a post here?" asks about the platform, and gets
 * the same answer it would get for any Jekyll site.
 *
 * What the overlay actually changes:
 *
 *  - **`typeKey: 'fmContentType'`.** The fleet's own content-type key, on top
 *    of the conventional `type` that `resolveContentType` reads first.
 *  - **`preview` first among the thumbnail keys.** The theme writes
 *    `preview: /images/previews/<slug>.svg` and auto-prefixes `/assets`;
 *    reading `image:` first would find whatever an imported article carried.
 *  - **`lastmod` as the modified key** — the theme canonicalises `updated` to
 *    it, and `frontmatter_schema.yml` requires it.
 *  - **The preview-image generator**, which for these sites is the
 *    zer0-image-generator Jekyll plugin.
 *
 * What it deliberately does NOT change: the date format. The fleet disagrees
 * with itself — lifehacker writes bare `2026-06-22`, it-journey and bash-365
 * write quoted ISO-ms — so the overlay would have to pick a side, and picking
 * one would make the other site's every date an error. That disagreement is a
 * per-site fact and belongs in that site's `zer0.json`, not in a theme profile.
 */

import type { PlatformOverlay, PlatformProbe, PlatformProfile } from '../../shared/types';

/** The overlay's identity, so nothing has to spell the string twice. */
export const ZER0_MISTAKES: PlatformOverlay = 'zer0-mistakes';

/**
 * The probes that say "this Jekyll site wears the theme". Read against
 * `_config.yml`, and only after Jekyll itself has been identified — an overlay
 * probe that could fire on its own would be a sibling id wearing a disguise.
 */
export const ZER0_MISTAKES_PROBES: readonly PlatformProbe[] = [
  { file: '_config.yml', contains: 'remote_theme: bamr87/zer0-mistakes' },
  { file: '_config.yml', contains: 'theme: jekyll-theme-zer0' },
];

export const ZER0_MISTAKES_OVERLAY: Partial<PlatformProfile> = {
  overlay: ZER0_MISTAKES,
  frontMatter: {
    dialects: ['yaml'],
    typeKey: 'fmContentType',
    draft: { name: 'draft', type: 'boolean' },
    draftFolders: ['_drafts'],
    dateKeys: {
      publish: ['date'],
      modified: ['lastmod', 'last_modified_at', 'lastModified', 'modified', 'updated'],
    },
    dateFormat: 'date',
    filenameDate: /^(\d{4}-\d{2}-\d{2})-/,
    taxonomyKeys: ['categories', 'tags', 'keywords'],
    slugKey: 'slug',
    permalinkKeys: ['permalink', 'canonical_url', 'canonicalUrl', 'url'],
    thumbnailKeys: ['preview', 'image', 'thumbnail', 'cover', 'featured_image', 'banner'],
    structuralStems: ['index', '_index', 'readme'],
    bundleNames: ['index', '_index'],
  },
  commands: {
    serve: ['docker', 'compose', 'up'],
    build: ['bundle', 'exec', 'jekyll', 'build'],
    previewUrl: 'http://localhost:4000',
    port: 4000,
    previewImages: 'jekyll preview-images',
  },
};
