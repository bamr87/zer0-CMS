/**
 * The MkDocs profile (plus the Material blog plugin).
 *
 * MkDocs is the shape that most clearly is *not* Jekyll: one `docs_dir` tree
 * where the file path is the URL, no collections, no date prefixes, and — for
 * a plain documentation page — no draft flag at all. `draft:` exists only in
 * Material's blog plugin, so the profile names it while `contentRoots` records
 * that `docs/` itself has none of the machinery a `_posts` folder has.
 *
 * `use_directory_urls` (default `true`) is the one setting that changes every
 * URL on the site, which is why `SiteConfigFacts` carries it and `permalinkOf`
 * reads it rather than assuming.
 *
 * `docs/` is very often *generated* — the fleet's own `projects/README` site
 * aggregates one folder per source repository into it — so the default root is
 * marked `authored` and a site whose `docs/` is written by a script should say
 * so through `platform.overrides` rather than have this file guess.
 */

import type { PlatformProfile } from '../../shared/types';

export const MKDOCS_PROFILE: PlatformProfile = {
  id: 'mkdocs',
  overlay: null,
  probes: [{ file: 'mkdocs.yml' }, { file: 'mkdocs.yaml' }],
  siteConfig: { file: 'mkdocs.yml', format: 'yaml' },
  contentRoots: [
    {
      collection: 'docs',
      path: 'docs',
      mode: 'authored',
      filename: { datePrefix: 'forbidden', bundles: 'index' },
      permalink: null,
      requiredKeys: [],
      recommendedKeys: ['title', 'description'],
      layoutAllowed: [],
    },
    {
      collection: 'blog',
      path: 'docs/blog/posts',
      mode: 'authored',
      // Material's blog reads the date from front matter, never the filename.
      filename: { datePrefix: 'forbidden', bundles: 'none' },
      permalink: null,
      requiredKeys: ['date'],
      recommendedKeys: ['title', 'description', 'categories', 'tags', 'authors'],
      layoutAllowed: [],
    },
  ],
  outputDirs: ['site'],
  frontMatter: {
    dialects: ['yaml'],
    typeKey: null,
    draft: { name: 'draft', type: 'boolean' },
    draftFolders: [],
    dateKeys: { publish: ['date'], modified: ['revision_date'] },
    dateFormat: 'date',
    filenameDate: null,
    taxonomyKeys: ['tags', 'categories'],
    slugKey: 'slug',
    permalinkKeys: [],
    thumbnailKeys: ['image', 'icon'],
    structuralStems: ['index', 'readme'],
    bundleNames: ['index'],
  },
  commands: {
    serve: ['mkdocs', 'serve'],
    build: ['mkdocs', 'build'],
    previewUrl: 'http://127.0.0.1:8000',
    port: 8000,
    previewImages: null,
  },
  governanceTarget: 'mkdocs',
  validators: [{ command: ['mkdocs', 'build', '--strict'], findingsPath: null, format: 'text' }],
};
