/**
 * The generic profile — what a directory of Markdown files is when no marker
 * file says otherwise.
 *
 * This is decision D9 applied to platforms: not knowing is a normal state, and
 * the honest answer is a profile that claims nothing. No date prefix, because
 * a filename that starts with digits might be a date or might be a chapter
 * number. No collections, because a folder is not a collection until something
 * declares it one. No serve command, because guessing one would put a command
 * in front of somebody that fails in a way they cannot debug. The permalink is
 * the path, which is the only URL claim that is true by construction.
 *
 * `probes` is empty on purpose: `generic` is never *detected*, it is what
 * detection falls back to, and giving it a probe would make that fallback look
 * like a positive identification.
 */

import type { PlatformProfile } from '../../shared/types';

export const GENERIC_PROFILE: PlatformProfile = {
  id: 'generic',
  overlay: null,
  probes: [],
  siteConfig: { file: null, format: 'none' },
  contentRoots: [],
  outputDirs: [],
  frontMatter: {
    dialects: ['yaml', 'toml', 'json'],
    typeKey: null,
    draft: { name: 'draft', type: 'boolean' },
    draftFolders: [],
    dateKeys: { publish: ['date'], modified: ['lastmod', 'updated'] },
    dateFormat: 'date',
    filenameDate: null,
    taxonomyKeys: ['tags', 'categories'],
    slugKey: 'slug',
    permalinkKeys: ['permalink'],
    thumbnailKeys: ['image'],
    structuralStems: ['index', 'readme'],
    bundleNames: ['index'],
  },
  commands: {
    serve: null,
    build: null,
    previewUrl: null,
    port: null,
    previewImages: null,
  },
  governanceTarget: 'generic',
  validators: [],
};
