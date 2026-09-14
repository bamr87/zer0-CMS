/**
 * The Wiki.js profile — the one target whose repository has a second writer.
 *
 * Wiki.js 2.x can use a git repository as its storage back end, syncing both
 * ways on a schedule and committing wiki edits back as its own git author. So
 * every content root here is `shared-writer`: an editor working in this
 * repository must expect the file it is holding to change underneath it, and
 * must never assume its own ledger is the only publisher.
 *
 * Two other things are backwards from every other profile:
 *
 *  - **The draft flag is inverted.** `published: false` hides a page; there is
 *    no `draft:` key. `DraftFieldConfig.invert` already models exactly this.
 *  - **There is no site config in the repository.** Title, description and
 *    site URL live in the Wiki.js database, so `siteConfig.file` is `null` and
 *    `readSiteConfigFacts` honestly returns nothing rather than inventing it.
 *
 * The detection probe is the compose file that runs the server, because a
 * git-storage repository carries no manifest of its own. The other diagnostic —
 * front matter holding `published:`, `editor:` and `dateCreated:` together —
 * needs a content walk, which detection deliberately does not do.
 */

import type { PlatformProfile } from '../../shared/types';

export const WIKIJS_PROFILE: PlatformProfile = {
  id: 'wikijs',
  overlay: null,
  probes: [
    { file: 'docker-compose.yml', contains: 'requarks/wiki' },
    { file: 'compose.yml', contains: 'requarks/wiki' },
    { file: 'docker-compose.yaml', contains: 'requarks/wiki' },
  ],
  siteConfig: { file: null, format: 'none' },
  contentRoots: [
    {
      collection: 'wiki',
      path: '.',
      mode: 'shared-writer',
      filename: { datePrefix: 'forbidden', bundles: 'none' },
      permalink: null,
      requiredKeys: ['title'],
      recommendedKeys: ['description', 'published', 'editor', 'dateCreated'],
      layoutAllowed: [],
    },
  ],
  outputDirs: [],
  frontMatter: {
    dialects: ['yaml'],
    typeKey: null,
    draft: { name: 'published', type: 'boolean', invert: true },
    draftFolders: [],
    // Wiki.js rewrites `date` on every save, so it is the *modified* stamp and
    // `dateCreated` is the publication one. Reading them the other way round is
    // how a wiki export looks like it was all written this morning.
    dateKeys: { publish: ['dateCreated'], modified: ['date'] },
    dateFormat: 'iso-ms',
    filenameDate: null,
    taxonomyKeys: ['tags'],
    slugKey: 'slug',
    permalinkKeys: [],
    thumbnailKeys: [],
    structuralStems: ['home', 'index', 'readme'],
    bundleNames: [],
  },
  commands: {
    serve: ['docker', 'compose', 'up', '-d'],
    build: null,
    previewUrl: 'http://localhost:3000',
    port: 3000,
    previewImages: null,
  },
  governanceTarget: 'wikijs',
  validators: [],
};
