/**
 * The Jekyll profile — decision D12's anchor, and the only one that had to be
 * *discovered* rather than designed.
 *
 * Every value below was lifted out of a file that used to hard-code it, not
 * retyped from the Jekyll documentation. That distinction is the whole point:
 * `JEKYLL_PROFILE` is a transcript of what zer0-CMS already did, so routing the
 * readers through it changes nothing for a Jekyll site while making every other
 * platform a table entry instead of a fork in the code.
 *
 * | Value | Lifted from |
 * |---|---|
 * | `frontMatter.filenameDate` | `content/pageIndex.ts` `FILENAME_DATE_RE` |
 * | `frontMatter.structuralStems` | `content/pageIndex.ts` `STRUCTURAL_STEMS` |
 * | `frontMatter.thumbnailKeys` | `content/pageIndex.ts` `THUMBNAIL_KEYS` (identical to `governance/publish.ts`'s) |
 * | `frontMatter.bundleNames` | `content/slug.ts` `BUNDLE_NAMES` |
 * | `frontMatter.permalinkKeys` | `governance/publish.ts` `PERMALINK_KEYS` |
 * | `outputDirs` | the `_site` member of `shared/glob.ts` `SKIP_DIRS` |
 * | `contentRoots[posts].filename.datePrefix` | `governance/publish.ts` `filePrefixFor`'s `_posts` rule |
 * | `commands.previewImages` | `media/media.ts` `briefFor`'s `jekyll preview-images` |
 *
 * `typeKey` is deliberately `null`. `resolveContentType` already reads the
 * conventional `type` key as its first step for every platform; a profile's
 * `typeKey` is the *extra* key a platform's own vocabulary adds, which for bare
 * Jekyll is nothing and for the zer0-mistakes overlay is `fmContentType`.
 *
 * The permalink templates are the ones the sites actually serve, expressed in
 * Jekyll's own token vocabulary; a site's `_config.yml` overrides them through
 * `SiteConfigFacts`, and a page's own `permalink:` overrides both.
 */

import type { PlatformProfile } from '../../shared/types';

/**
 * A `2026-07-31-` filename prefix. Verbatim from `pageIndex.ts`, including the
 * capture group: callers read `[1]` to get the date without the trailing dash.
 */
const FILENAME_DATE_RE = /^(\d{4}-\d{2}-\d{2})-/;

export const JEKYLL_PROFILE: PlatformProfile = {
  id: 'jekyll',
  overlay: null,
  probes: [{ file: '_config.yml' }, { file: '_config.yaml' }],
  siteConfig: { file: '_config.yml', format: 'yaml' },
  contentRoots: [
    {
      collection: 'posts',
      path: '_posts',
      mode: 'authored',
      // Jekyll refuses to build an undated post, which is why `publish.ts`
      // stamps a date onto a `_posts` filename even when nothing is configured.
      filename: { datePrefix: 'required', bundles: 'none' },
      permalink: '/:collection/:year/:month/:day/:title/',
      requiredKeys: ['title'],
      recommendedKeys: ['date', 'description', 'categories', 'tags'],
      layoutAllowed: [],
    },
    {
      collection: 'drafts',
      path: '_drafts',
      mode: 'authored',
      // A draft has no date in its name — that is how Jekyll tells the two
      // folders apart, and dating one is how it accidentally publishes.
      filename: { datePrefix: 'forbidden', bundles: 'none' },
      permalink: null,
      requiredKeys: ['title'],
      recommendedKeys: ['description'],
      layoutAllowed: [],
    },
    {
      collection: 'pages',
      path: '.',
      mode: 'authored',
      filename: { datePrefix: 'optional', bundles: 'index' },
      permalink: '/:path/:name/',
      requiredKeys: ['title'],
      recommendedKeys: ['description', 'layout'],
      layoutAllowed: [],
    },
  ],
  outputDirs: ['_site', '.jekyll-cache', '.sass-cache'],
  frontMatter: {
    dialects: ['yaml'],
    typeKey: null,
    // Jekyll's own flag is `published:` (inverted); `draft:` is a theme and CMS
    // convention. The default config's `draftField` says `draft`, and this
    // profile agrees with it so a bare Jekyll site behaves exactly as before.
    draft: { name: 'draft', type: 'boolean' },
    draftFolders: ['_drafts'],
    dateKeys: {
      publish: ['date'],
      // `article.ts` `CONVENTIONAL_MODIFIED_KEYS`, in its order.
      modified: ['lastmod', 'last_modified_at', 'lastModified', 'modified', 'updated'],
    },
    dateFormat: 'date',
    filenameDate: FILENAME_DATE_RE,
    taxonomyKeys: ['categories', 'tags'],
    slugKey: 'slug',
    permalinkKeys: ['permalink', 'canonical_url', 'canonicalUrl', 'url'],
    thumbnailKeys: ['image', 'preview', 'thumbnail', 'cover', 'featured_image', 'banner'],
    structuralStems: ['index', '_index', 'readme'],
    bundleNames: ['index', '_index'],
  },
  commands: {
    serve: ['bundle', 'exec', 'jekyll', 'serve', '--livereload'],
    build: ['bundle', 'exec', 'jekyll', 'build'],
    previewUrl: 'http://localhost:4000',
    port: 4000,
    previewImages: 'jekyll preview-images',
  },
  governanceTarget: 'jekyll',
  validators: [
    {
      command: ['bundle', 'exec', 'jekyll', 'build', '--safe', '--strict_front_matter'],
      findingsPath: null,
      format: 'text',
    },
  ],
};
