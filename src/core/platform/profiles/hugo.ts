/**
 * The Hugo profile.
 *
 * Hugo is the profile that most tests the rule "dates stay strings". Its
 * archetypes write TOML front matter with *bare* RFC 3339 datetimes, which a
 * TOML library would gladly hand back as native date objects; `parseTomlFlat`
 * deliberately does not, and this profile records `dateFormat: 'rfc3339'` so a
 * reader knows the shape of the string it is holding without parsing it.
 *
 * Two Hugo facts contradict Jekyll habits and are worth stating out loud:
 *
 *  - **A date in a filename means nothing** unless `frontmatter.date` names
 *    `:filename` in the site config. `filenameDate: null` and a `forbidden`
 *    date prefix are how this profile stops zer0-CMS from stamping
 *    `2026-09-09-` onto a Hugo file and quietly changing its URL.
 *  - **`type:` is Hugo's own key** — it overrides the section-derived content
 *    type — and it collides in meaning with `CONTENT_TYPE_FIELD`. Naming it as
 *    the profile's `typeKey` makes the collision explicit rather than lucky.
 *
 * `_index.md` (branch bundle) and `index.md` (leaf bundle) are both real here,
 * so `bundleNames` carries both and `bundles: '_index'` records which one a new
 * section page should be.
 */

import type { PlatformProfile } from '../../shared/types';

export const HUGO_PROFILE: PlatformProfile = {
  id: 'hugo',
  overlay: null,
  probes: [
    { file: 'hugo.toml' },
    { file: 'hugo.yaml' },
    { file: 'hugo.yml' },
    { file: 'hugo.json' },
    { file: 'config/_default/hugo.toml' },
    { file: 'config.toml' },
  ],
  siteConfig: { file: 'hugo.toml', format: 'toml' },
  contentRoots: [
    {
      collection: 'content',
      path: 'content',
      mode: 'authored',
      filename: { datePrefix: 'forbidden', bundles: '_index' },
      permalink: null,
      requiredKeys: ['title'],
      recommendedKeys: ['date', 'description', 'draft', 'tags', 'categories'],
      layoutAllowed: [],
    },
  ],
  outputDirs: ['public', 'resources'],
  frontMatter: {
    dialects: ['toml', 'yaml', 'json'],
    typeKey: 'type',
    draft: { name: 'draft', type: 'boolean' },
    draftFolders: [],
    dateKeys: {
      publish: ['date', 'publishDate'],
      modified: ['lastmod'],
    },
    dateFormat: 'rfc3339',
    filenameDate: null,
    taxonomyKeys: ['tags', 'categories', 'series'],
    slugKey: 'slug',
    // `url:` is Hugo's absolute override; `aliases` emit redirects and are not
    // a page's own address, so they are not listed here.
    permalinkKeys: ['url'],
    thumbnailKeys: ['images', 'featured_image', 'cover'],
    structuralStems: ['index', '_index', 'readme'],
    bundleNames: ['index', '_index'],
  },
  commands: {
    serve: ['hugo', 'server', '-D'],
    build: ['hugo', '--minify'],
    previewUrl: 'http://localhost:1313',
    port: 1313,
    previewImages: null,
  },
  governanceTarget: 'hugo',
  validators: [{ command: ['hugo', '--gc'], findingsPath: null, format: 'text' }],
};
