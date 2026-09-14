/**
 * Which kind of site is this? — and, just as importantly, *why does it think
 * so*.
 *
 * Detection is marker files, in a fixed order, over an **injected** pair of
 * readers. No `fs` here: the same function answers for a workspace folder, for
 * a fixture directory in a test, and one day for a virtual workspace, because
 * it never learns what a filesystem is. `io.exists` answers for directories as
 * well as files — several of the corroborating Jekyll markers are folders.
 *
 * The order matters and is deliberate:
 *
 *   1. **`zer0.json`'s `platform.id` wins outright.** A site that has said what
 *      it is has said what it is; probing over the top of that would make a
 *      stated fact subject to a heuristic.
 *   2. **Jekyll**, on `_config.yml`. Corroborating markers (`Gemfile`,
 *      `_layouts/`, `_includes/`, `_posts/`, `pages/`) are recorded as evidence
 *      but are not required — `_config.yml` is the strongest single marker
 *      there is, and a site early in its life may have nothing else yet.
 *   3. **The zer0-mistakes overlay**, probed only once Jekyll is established.
 *      An overlay probe that could fire on its own would be a sibling platform
 *      id wearing a disguise, and decision D12 says it is not one.
 *   4. mkdocs → hugo → docusaurus → astro → wikijs.
 *   5. **generic**, with `source: 'default'` — nothing matched, and saying so
 *      is better than picking the most likely.
 *
 * `evidence` is the point of the exercise. "Why does it think this is Hugo?" is
 * a question somebody asks at the worst possible moment, and the answer has to
 * be a list of the files that were actually found, not a re-run of the same
 * guess. Every branch appends to it, including the branch that gives up.
 */

import type {
  PlatformConfig,
  PlatformId,
  PlatformProfile,
  PlatformProfileJson,
  PlatformProbe,
  ResolvedPlatform,
  Zer0Config,
} from '../shared/types';
import { ASTRO_PROFILE } from './profiles/astro';
import { DOCUSAURUS_PROFILE } from './profiles/docusaurus';
import { GENERIC_PROFILE } from './profiles/generic';
import { HUGO_PROFILE } from './profiles/hugo';
import { JEKYLL_PROFILE } from './profiles/jekyll';
import { MKDOCS_PROFILE } from './profiles/mkdocs';
import { WIKIJS_PROFILE } from './profiles/wikijs';
import { ZER0_MISTAKES_OVERLAY, ZER0_MISTAKES_PROBES } from './overlays/zer0-mistakes';
import { emptySiteConfigFacts, readSiteConfigFacts } from './siteConfig';

/** Every profile, by id. The table decision D12 says "support mkdocs" edits. */
export const PLATFORM_PROFILES: Readonly<Record<PlatformId, PlatformProfile>> = {
  jekyll: JEKYLL_PROFILE,
  mkdocs: MKDOCS_PROFILE,
  wikijs: WIKIJS_PROFILE,
  hugo: HUGO_PROFILE,
  docusaurus: DOCUSAURUS_PROFILE,
  astro: ASTRO_PROFILE,
  generic: GENERIC_PROFILE,
};

/** The order probes are tried in. `generic` is the fallback, never a probe. */
const DETECTION_ORDER: readonly PlatformId[] = [
  'jekyll',
  'mkdocs',
  'hugo',
  'docusaurus',
  'astro',
  'wikijs',
];

/** Corroborating Jekyll markers — evidence, never a requirement. */
const JEKYLL_COMPANIONS = ['Gemfile', '_layouts', '_includes', '_posts', 'pages'];

/** The readers detection is given. Relative to the root; never absolute. */
export interface PlatformIo {
  exists(rel: string): Promise<boolean>;
  read(rel: string): Promise<string | undefined>;
}

// ---------------------------------------------------------------------------
// Merging: overlays and zer0.json overrides
// ---------------------------------------------------------------------------

/**
 * Merge a partial profile onto a base.
 *
 * Top-level keys replace wholesale — a caller overriding `contentRoots` means
 * *these* roots, not these plus the defaults, and item-level array merging is
 * how "where did this content root come from?" becomes unanswerable. The three
 * grouped objects (`siteConfig`, `frontMatter`, `commands`) merge key by key,
 * because overriding one of their forty fields should not require restating the
 * other thirty-nine.
 */
export function mergeProfile(
  base: PlatformProfile,
  patch: Partial<PlatformProfile>,
): PlatformProfile {
  return {
    ...base,
    ...patch,
    siteConfig: { ...base.siteConfig, ...(patch.siteConfig ?? {}) },
    frontMatter: { ...base.frontMatter, ...(patch.frontMatter ?? {}) },
    commands: { ...base.commands, ...(patch.commands ?? {}) },
  };
}

/**
 * The JSON twin of a profile: no `RegExp`, no functions.
 *
 * This is the shape `zer0.json` writes and a cache fingerprint hashes. A
 * `RegExp` does not survive `JSON.stringify` — it stringifies to `{}` — so a
 * fingerprint built over the live profile would call two different filename
 * rules identical.
 */
export function toProfileJson(profile: PlatformProfile): PlatformProfileJson {
  const { filenameDate, ...rest } = profile.frontMatter;
  return {
    ...profile,
    probes: profile.probes.map((probe) => ({ ...probe })),
    frontMatter: { ...rest, filenameDate: filenameDate === null ? null : filenameDate.source },
  };
}

/**
 * Apply a `zer0.json` `platform.overrides` block.
 *
 * `overrides` arrived from an untrusted file and was deliberately not validated
 * by `resolveConfig` — only this module knows which of a profile's keys are
 * meaningful. A `filenameDate` that is not a compilable pattern is dropped with
 * the rest of that key rather than thrown: a bad regex in a config file must
 * cost the override, never the session.
 */
export function applyOverrides(
  profile: PlatformProfile,
  overrides: Partial<PlatformProfileJson>,
): PlatformProfile {
  // No overrides is the overwhelmingly common case, and returning the profile
  // itself keeps it reference-stable — which is what lets a caller memoise on
  // identity and what makes "this workspace is still read as Jekyll" a
  // checkable claim rather than a structural resemblance.
  if (Object.keys(overrides).length === 0) {
    return profile;
  }
  const { frontMatter, ...patch } = overrides;
  if (frontMatter === undefined) {
    return mergeProfile(profile, patch);
  }

  const { filenameDate, ...restFm } = frontMatter;
  const merged: Partial<PlatformProfile['frontMatter']> = { ...restFm };
  if (filenameDate === null) {
    merged.filenameDate = null;
  } else if (typeof filenameDate === 'string') {
    try {
      merged.filenameDate = new RegExp(filenameDate);
    } catch {
      // An unusable pattern costs the override, never the session: the
      // profile's own rule stays in place, which is a working CMS rather than
      // a crash in front of somebody who mistyped a backslash.
      merged.filenameDate = profile.frontMatter.filenameDate;
    }
  }
  return mergeProfile(profile, {
    ...patch,
    frontMatter: { ...profile.frontMatter, ...merged },
  });
}

// ---------------------------------------------------------------------------
// Detection
// ---------------------------------------------------------------------------

/** A probe reader that reads each file at most once per detection. */

/**
 * Flatten the ways a person can write the same YAML mapping, so a probe like
 * `remote_theme: bamr87/zer0-mistakes` matches what real files actually say.
 *
 * This is not fussiness. Of the five sites in this fleet that use the
 * zer0-mistakes theme, four write it aligned and quoted —
 * `remote_theme             : "bamr87/zer0-mistakes"` — and one writes it
 * compactly. A literal substring probe found exactly the one, and would have
 * silently denied the theme overlay to the four sites the overlay exists for.
 * A detector that only recognises tidy files is a detector for fixtures.
 *
 * It collapses whitespace around a colon, drops surrounding quotes from the
 * value, and lower-cases. It deliberately does NOT parse YAML: a probe runs
 * before anything is known about the file, on text that may not be YAML at all.
 */
function normalizeForProbe(text: string): string {
  return text
    .split(/\r?\n/u)
    .map((line) => line.replace(/\s*:\s*/u, ': ').replace(/:\s*["']([^"']*)["']\s*$/u, ': $1'))
    .join('\n')
    .toLowerCase();
}

class Prober {
  private readonly texts = new Map<string, string | undefined>();

  constructor(private readonly io: PlatformIo) {}

  async text(file: string): Promise<string | undefined> {
    if (!this.texts.has(file)) {
      this.texts.set(file, await this.io.read(file));
    }
    return this.texts.get(file);
  }

  /** The evidence line a matching probe produces, or `undefined`. */
  async match(probe: PlatformProbe): Promise<string | undefined> {
    if (probe.contains === undefined) {
      return (await this.io.exists(probe.file)) ? probe.file : undefined;
    }
    const text = await this.text(probe.file);
    return text !== undefined && normalizeForProbe(text).includes(normalizeForProbe(probe.contains))
      ? `${probe.file} contains "${probe.contains}"`
      : undefined;
  }

  async first(probes: readonly PlatformProbe[]): Promise<string | undefined> {
    for (const probe of probes) {
      const hit = await this.match(probe);
      if (hit !== undefined) {
        return hit;
      }
    }
    return undefined;
  }
}

/** Read the site's own config for `profile`, when it has one on disk. */
async function factsFor(
  profile: PlatformProfile,
  prober: Prober,
): Promise<ResolvedPlatform['siteConfig']> {
  const file = profile.siteConfig.file;
  if (file === null) {
    return readSiteConfigFacts(profile, undefined);
  }
  return readSiteConfigFacts(profile, await prober.text(file));
}

/**
 * Should the zer0-mistakes overlay be applied, and what proved it?
 *
 * `overlay: null` in `zer0.json` means "no overlay, do not probe" — a real
 * answer — and `'zer0-mistakes'` means "yes, I know it is" without a probe.
 * Only `'auto'` (the default) actually looks.
 */
async function resolveOverlay(
  configured: PlatformConfig['overlay'],
  prober: Prober,
): Promise<{ apply: boolean; evidence: string | null }> {
  if (configured === null) {
    return { apply: false, evidence: 'zer0.json: platform.overlay = null (probe skipped)' };
  }
  if (configured === 'zer0-mistakes') {
    return { apply: true, evidence: 'zer0.json: platform.overlay = zer0-mistakes' };
  }
  const hit = await prober.first(ZER0_MISTAKES_PROBES);
  return { apply: hit !== undefined, evidence: hit ?? null };
}

/**
 * Identify the platform of the directory `io` reads from.
 *
 * `platform` is the `zer0.json` block, when there is one; passing it is what
 * makes rule 1 above ("an explicit id wins outright") happen inside detection
 * rather than in every caller. With no block at all the function probes, which
 * is the same thing `{ id: 'auto', overlay: 'auto' }` does.
 */
export async function detectPlatform(
  root: string,
  io: PlatformIo,
  platform?: PlatformConfig,
): Promise<ResolvedPlatform> {
  // `io` is already scoped to `root`; the parameter is kept because a call
  // reads as "detect the platform of this directory", and because the evidence
  // a caller shows a person is only meaningful next to the folder it is about.
  void root;

  const prober = new Prober(io);
  const evidence: string[] = [];

  // `overlay: null` means "no overlay, do not probe" and is a real answer, so
  // it must not be coalesced into the default the way `??` would coalesce it.
  const configuredOverlay: PlatformConfig['overlay'] =
    platform === undefined || platform.overlay === undefined ? 'auto' : platform.overlay;

  const withOverlay = async (base: PlatformProfile): Promise<PlatformProfile> => {
    if (base.id !== 'jekyll') {
      return base;
    }
    const overlay = await resolveOverlay(configuredOverlay, prober);
    if (overlay.evidence !== null) {
      evidence.push(overlay.evidence);
    }
    return overlay.apply ? mergeProfile(base, ZER0_MISTAKES_OVERLAY) : base;
  };

  const overrides = platform?.overrides ?? {};

  // 1 — an explicit id in zer0.json.
  if (platform !== undefined && platform.id !== 'auto') {
    evidence.push(`zer0.json: platform.id = ${platform.id} (probes skipped)`);
    const profile = applyOverrides(
      await withOverlay(PLATFORM_PROFILES[platform.id]),
      overrides,
    );
    return {
      profile,
      source: 'zer0.json',
      evidence,
      siteConfig: await factsFor(profile, prober),
    };
  }

  // 2–4 — the probe order.
  for (const id of DETECTION_ORDER) {
    const candidate = PLATFORM_PROFILES[id];
    const hit = await prober.first(candidate.probes);
    if (hit === undefined) {
      continue;
    }
    evidence.push(hit);
    if (id === 'jekyll') {
      for (const companion of JEKYLL_COMPANIONS) {
        if (await io.exists(companion)) {
          evidence.push(companion);
        }
      }
    }
    const profile = applyOverrides(await withOverlay(candidate), overrides);
    return {
      profile,
      source: 'detected',
      evidence,
      siteConfig: await factsFor(profile, prober),
    };
  }

  // 5 — nothing matched. `generic` claims nothing, and the evidence says so in
  //     words rather than leaving an empty list to be read as "not checked".
  evidence.push('no platform marker file found');
  return {
    profile: applyOverrides(GENERIC_PROFILE, overrides),
    source: 'default',
    evidence,
    siteConfig: emptySiteConfigFacts(),
  };
}

/**
 * The profile to read a workspace's content with.
 *
 * Pass the `detectPlatform` result whenever there is one. Without it, an
 * explicit `platform.id` still applies, and the last resort is `JEKYLL_PROFILE`
 * rather than `generic` — because "nobody ran detection" is a different state
 * from "detection looked and found nothing", and Jekyll is the behaviour every
 * reader in this codebase had before decision D12 moved it behind a profile.
 * The Jekyll projection golden is the proof of that sentence.
 */
export function profileFor(cfg: Zer0Config, detected?: ResolvedPlatform): PlatformProfile {
  if (detected !== undefined) {
    return detected.profile;
  }
  const base = cfg.platform.id === 'auto' ? JEKYLL_PROFILE : PLATFORM_PROFILES[cfg.platform.id];
  const overlaid =
    base.id === 'jekyll' && cfg.platform.overlay === 'zer0-mistakes'
      ? mergeProfile(base, ZER0_MISTAKES_OVERLAY)
      : base;
  return applyOverrides(overlaid, cfg.platform.overrides);
}
