/**
 * The Docusaurus v3 profile.
 *
 * Docusaurus is the only platform here whose site config is *code* —
 * `docusaurus.config.ts` is a JavaScript module, and zer0-CMS reads no
 * JavaScript. So `siteConfig.format` is `js`, `readSiteConfigFacts` returns
 * nothing but a warning saying why, and every route below is the plugin
 * default written down where a person can see it. A site that moved
 * `routeBasePath` states that in `zer0.json`'s `platform.overrides`; guessing
 * it out of a regex over somebody's TypeScript is how a CMS learns a route that
 * was inside a comment.
 *
 * The filename rule is the interesting one: `01-intro.md` is `intro` in the URL
 * and `sidebar_position: 1` in the sidebar. That is a number prefix, not a date
 * prefix, so `filenameDate` stays `null` and `permalinkOf` strips the digits.
 * Blog posts *do* carry `YYYY-MM-DD-` in the filename, which is why the blog
 * root's `datePrefix` is `required` while docs' is `forbidden` — one profile,
 * two roots, two rules, which is the reason `PlatformContentRoot` exists.
 *
 * `unlisted: true` is not a draft: the page is built and served, just kept out
 * of sidebars and the sitemap. It is recorded as a recommended key rather than
 * folded into the draft flag, because collapsing the two would tell a person
 * their published page is unpublished.
 */

import type { PlatformProfile } from '../../shared/types';

export const DOCUSAURUS_PROFILE: PlatformProfile = {
  id: 'docusaurus',
  overlay: null,
  probes: [
    { file: 'docusaurus.config.js' },
    { file: 'docusaurus.config.ts' },
    { file: 'docusaurus.config.mjs' },
  ],
  siteConfig: { file: 'docusaurus.config.js', format: 'js' },
  contentRoots: [
    {
      collection: 'docs',
      path: 'docs',
      mode: 'authored',
      filename: { datePrefix: 'forbidden', bundles: 'index' },
      permalink: '/docs/:path/:name/',
      requiredKeys: [],
      recommendedKeys: ['title', 'description', 'sidebar_position', 'tags'],
      layoutAllowed: [],
    },
    {
      collection: 'blog',
      path: 'blog',
      mode: 'authored',
      filename: { datePrefix: 'required', bundles: 'index' },
      permalink: '/blog/:year/:month/:day/:name/',
      requiredKeys: ['title'],
      recommendedKeys: ['authors', 'tags', 'description'],
      layoutAllowed: [],
    },
    {
      collection: 'pages',
      path: 'src/pages',
      mode: 'authored',
      filename: { datePrefix: 'forbidden', bundles: 'index' },
      permalink: '/:path/:name/',
      requiredKeys: [],
      recommendedKeys: ['title', 'description'],
      layoutAllowed: [],
    },
  ],
  outputDirs: ['build', '.docusaurus'],
  frontMatter: {
    dialects: ['yaml'],
    typeKey: null,
    draft: { name: 'draft', type: 'boolean' },
    draftFolders: [],
    dateKeys: { publish: ['date'], modified: ['last_update'] },
    dateFormat: 'date',
    filenameDate: null,
    taxonomyKeys: ['tags'],
    slugKey: 'slug',
    // `slug:` is Docusaurus' own route override and is handled by the slug key
    // rather than as a permalink, because a relative `slug: my-page` is not a
    // path — `permalinkOf` has to place it under the route base itself.
    permalinkKeys: [],
    thumbnailKeys: ['image'],
    structuralStems: ['index', 'readme'],
    bundleNames: ['index', 'readme'],
  },
  commands: {
    serve: ['npm', 'run', 'start'],
    build: ['npm', 'run', 'build'],
    previewUrl: 'http://localhost:3000',
    port: 3000,
    previewImages: null,
  },
  governanceTarget: 'docusaurus',
  validators: [{ command: ['npm', 'run', 'build'], findingsPath: null, format: 'text' }],
};
