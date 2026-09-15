/**
 * The Astro profile (content collections, v4 and v5).
 *
 * Astro's schema is *code*: `src/content.config.ts` declares each collection
 * with a zod object, and `astro check` fails the build on a violation. That
 * makes Astro the one platform whose required keys genuinely live somewhere
 * zer0-CMS cannot read, so this profile records the convention the official
 * blog template established (`title`, `description`, `pubDate`, `draft`) as
 * *recommended* and requires only `title`. Recommending is honest; requiring a
 * key the site never declared would file an issue against every page.
 *
 * `pubDate` and `updatedDate` are template names rather than platform names,
 * which is why both they and the ordinary `date`/`lastmod` pair are listed —
 * first key present wins, and a site that renamed them says so in
 * `platform.overrides`.
 *
 * A v5 loader's `base` can point anywhere, even outside `src/`, so
 * `contentRootsFor` treats `src/content` as the default rather than the truth,
 * and the evidence line names the config file it found so a person debugging an
 * empty content list can see what was assumed.
 */

import type { PlatformProfile } from '../../shared/types';

export const ASTRO_PROFILE: PlatformProfile = {
  id: 'astro',
  overlay: null,
  probes: [
    { file: 'astro.config.mjs' },
    { file: 'astro.config.ts' },
    { file: 'astro.config.js' },
    { file: 'src/content.config.ts' },
    { file: 'src/content/config.ts' },
  ],
  siteConfig: { file: 'astro.config.mjs', format: 'js' },
  contentRoots: [
    {
      collection: 'content',
      path: 'src/content',
      mode: 'authored',
      // The collection entry id is the path inside the collection folder; a
      // date in the filename would become part of that id, and therefore part
      // of the URL. The blog template puts the date in `pubDate` instead.
      filename: { datePrefix: 'forbidden', bundles: 'none' },
      permalink: null,
      requiredKeys: ['title'],
      recommendedKeys: ['description', 'pubDate', 'draft', 'tags'],
      layoutAllowed: [],
    },
    {
      collection: 'pages',
      path: 'src/pages',
      mode: 'authored',
      filename: { datePrefix: 'forbidden', bundles: 'index' },
      permalink: '/:path/:name/',
      requiredKeys: [],
      recommendedKeys: ['title', 'layout'],
      layoutAllowed: [],
    },
  ],
  outputDirs: ['dist', '.astro'],
  frontMatter: {
    dialects: ['yaml'],
    typeKey: null,
    draft: { name: 'draft', type: 'boolean' },
    draftFolders: [],
    dateKeys: { publish: ['pubDate', 'date'], modified: ['updatedDate', 'lastmod'] },
    dateFormat: 'date',
    filenameDate: null,
    taxonomyKeys: ['tags'],
    slugKey: 'slug',
    permalinkKeys: [],
    thumbnailKeys: ['heroImage', 'image'],
    structuralStems: ['index', 'readme'],
    bundleNames: ['index'],
  },
  commands: {
    serve: ['npm', 'run', 'dev'],
    build: ['npm', 'run', 'build'],
    previewUrl: 'http://localhost:4321',
    port: 4321,
    previewImages: null,
  },
  governanceTarget: 'astro',
  validators: [{ command: ['npx', 'astro', 'check'], findingsPath: null, format: 'text' }],
};
