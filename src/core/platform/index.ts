/**
 * The platform package's own barrel — decision D12's public surface.
 *
 * Four modules and eight data files sit behind it: the seven profiles and the
 * one overlay (`profiles/`, `overlays/`), detection (`detect.ts`), the site's
 * own configuration (`siteConfig.ts`), and the path and URL derivations
 * (`permalink.ts`). Nothing here touches a filesystem, a network or an editor;
 * detection takes its readers as parameters and everything else is a pure
 * function over data.
 *
 * The rest of `src/core` imports from the individual modules by relative path,
 * as it does everywhere inside core. This file exists so `src/core/index.ts`
 * has one line to add and everything outside core has one place to import
 * from.
 */

export {
  applyOverrides,
  detectPlatform,
  mergeProfile,
  PLATFORM_PROFILES,
  profileFor,
  toProfileJson,
  type PlatformIo,
} from './detect';
export { emptySiteConfigFacts, readSiteConfigFacts } from './siteConfig';
export {
  basePathOf,
  contentRootsFor,
  datePrefixRuleAt,
  permalinkFallback,
  permalinkOf,
  skipDirsFor,
} from './permalink';
export { ASTRO_PROFILE } from './profiles/astro';
export { DOCUSAURUS_PROFILE } from './profiles/docusaurus';
export { GENERIC_PROFILE } from './profiles/generic';
export { HUGO_PROFILE } from './profiles/hugo';
export { JEKYLL_PROFILE } from './profiles/jekyll';
export { MKDOCS_PROFILE } from './profiles/mkdocs';
export { WIKIJS_PROFILE } from './profiles/wikijs';
export { ZER0_MISTAKES, ZER0_MISTAKES_OVERLAY, ZER0_MISTAKES_PROBES } from './overlays/zer0-mistakes';
