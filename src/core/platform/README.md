# `src/core/platform` — what kind of site is this?

Decision **D12**: a site's platform is a *profile*, resolved once, never guessed twice. Jekyll, MkDocs, Wiki.js, Hugo, Docusaurus, Astro and a `generic` fallback are **data** — content roots, the front-matter dialect and its load-bearing keys, the draft convention, date keys and formats, the slug and permalink rules, the directories that are build output, the serve command and preview URL. Nothing platform-specific is hard-coded outside a profile.

| File | Exports | Notes |
|---|---|---|
| `profiles/{jekyll,mkdocs,wikijs,hugo,docusaurus,astro,generic}.ts` | `JEKYLL_PROFILE`, `MKDOCS_PROFILE`, `WIKIJS_PROFILE`, `HUGO_PROFILE`, `DOCUSAURUS_PROFILE`, `ASTRO_PROFILE`, `GENERIC_PROFILE` | One file per platform. Pure data — a profile may not contain a function. |
| `overlays/zer0-mistakes.ts` | `ZER0_MISTAKES`, `ZER0_MISTAKES_PROBES`, `ZER0_MISTAKES_OVERLAY` | A `Partial<PlatformProfile>` merged onto Jekyll. Never a platform id. |
| `detect.ts` | `PLATFORM_PROFILES`, `PlatformIo`, `detectPlatform`, `profileFor`, `mergeProfile`, `applyOverrides`, `toProfileJson` | Marker files over injected readers. No `fs`. |
| `siteConfig.ts` | `readSiteConfigFacts`, `emptySiteConfigFacts` | The site's own config, or a warning saying why not. |
| `permalink.ts` | `permalinkOf`, `permalinkFallback`, `contentRootsFor`, `datePrefixRuleAt`, `skipDirsFor`, `basePathOf` | Pure string surgery: no `Date`, no `path`, no disk. `datePrefixRuleAt` is `…At` rather than `…For` because `governance/fileTarget.ts` exports a `datePrefixRuleFor(cfg, profile, dir)` of its own, and one name in two barrel-exported modules makes `export *` ambiguous for everybody. The two answer the same question from different sides and are worth collapsing. |
| `index.ts` | the barrel | `src/core/index.ts` re-exports this one line; inside core, import the module. |

## The four rules this package is built on

**A profile is data.** No function, no `fs`, no network, no lazily-evaluated anything. `commands.serve` is an argv array a *shell* runs — nothing in core spawns it. That is what makes "support MkDocs" a table entry a person can read and review, rather than a new branch in every reader, and it is what lets `toProfileJson` produce a value a cache fingerprint can hash and a `zer0.json` can override.

**zer0-mistakes is an overlay on Jekyll, never a sibling id.** Every site in this fleet is a Jekyll site wearing the theme; giving that combination its own `PlatformId` would mean two rows in the profile table that have to be kept in sync, and the day Jekyll changes something only one of them would learn. So `ResolvedPlatform.profile.id` stays `'jekyll'` and `profile.overlay` is `'zer0-mistakes'` beside it. Code asking "how do I read a post here?" gets Jekyll's answer; code asking "is this a fleet site?" asks about the overlay. The overlay probe runs *only after* Jekyll is established — an overlay that could fire on its own would be a sibling id in disguise.

**Detection records its evidence.** "Why does it think this is Hugo?" is a question somebody asks at the worst possible moment, and re-running the same guess is not an answer. `ResolvedPlatform.evidence` is the list of files that were actually found — `_config.yml`, `Gemfile`, `pages`, `_config.yml contains "remote_theme: bamr87/zer0-mistakes"` — including the branch that gives up, which records `no platform marker file found` rather than leaving an empty array to be read as "not checked".

**An anchor becomes a warning, never a guessed value.** Real `_config.yml` files in this fleet use YAML anchors, aliases and merge keys; the hand-rolled subset parser keeps them as literal text and does not resolve them, because resolving them would mean a YAML implementation and the zero-dependency rule says no. So `title: &site_title lifehacker.dev` yields `title: null` plus a `warnings` line naming the key and the construct. A guessed `baseurl` is worse than no `baseurl`: it produces URLs that look right and are wrong, and the ledger is keyed by URL.

## Detection order

1. **`zer0.json`'s `platform.id`**, when it is not `auto` — it wins outright, probes skipped. A site that has said what it is has said what it is.
2. **Jekyll**, on `_config.yml` / `_config.yaml`. `Gemfile`, `_layouts`, `_includes`, `_posts` and `pages` are recorded as corroborating evidence but are never required.
3. **The zer0-mistakes overlay**, on `remote_theme: bamr87/zer0-mistakes` or `theme: jekyll-theme-zer0` in `_config.yml` — probed only once Jekyll has matched. `platform.overlay: null` is a real answer meaning "do not probe", and is *not* coalesced into the default.
4. **mkdocs → hugo → docusaurus → astro → wikijs**, each on its own marker file.
5. **generic**, with `source: 'default'`.

`source` distinguishes the three ways a profile can be believed: `'zer0.json'` (stated), `'detected'` (a marker file), `'default'` (nothing matched). `profileFor(cfg, detected?)` adds a fourth state that is deliberately *not* `generic`: called with no detection result at all it returns `JEKYLL_PROFILE`, because "nobody ran detection" is a different thing from "detection looked and found nothing", and Jekyll is the behaviour every reader in this codebase had before D12. The golden at `src/test/fixtures/golden/platform/` is the proof of that sentence.

## The Jekyll profile is a transcript, not a design

`JEKYLL_PROFILE` was populated by *moving* literals out of the modules that held them, not by reading the Jekyll documentation. The suite cross-checks each one against the other module that still holds the same value, so a drift is a test failure rather than a surprise months later.

| Profile field | Lifted from |
|---|---|
| `frontMatter.filenameDate` | `content/pageIndex.ts` `FILENAME_DATE_RE` |
| `frontMatter.structuralStems` | `content/pageIndex.ts` `STRUCTURAL_STEMS` |
| `frontMatter.thumbnailKeys` | `content/pageIndex.ts` / `governance/publish.ts` `THUMBNAIL_KEYS` |
| `frontMatter.bundleNames` | `content/slug.ts` `BUNDLE_NAMES` |
| `frontMatter.permalinkKeys` | `governance/publish.ts` `PERMALINK_KEYS` |
| `frontMatter.dateKeys.modified` | `content/article.ts` `CONVENTIONAL_MODIFIED_KEYS` |
| `outputDirs` | the `_site` member of `shared/glob.ts` `SKIP_DIRS` |
| `contentRoots[posts].filename.datePrefix` | `governance/publish.ts` `filePrefixFor`'s `_posts` rule |
| `commands.previewImages` | `media/media.ts` `briefFor` |

Every reader that used to hold one of those takes `profile: PlatformProfile = JEKYLL_PROFILE` as its **last** parameter, so a call site that has not resolved a platform behaves exactly as it did before: `buildIndex`, `pageToRecord`, `resolveFolders`, `filePrefixFor`, `resolveContentType`, `createContent`, `alignedFilePath`, `byPath`, `loadContractOrScan`, `briefFor`, `resolveMedia`, `mediaCoverage`. `walkGlobs` takes an injected `skip` set for the same reason.

## What a profile does *not* decide

The **workspace's own configuration wins** wherever the two overlap. `cfg.draftField` beats `profile.frontMatter.draft`, and `cfg.contentFolders` beats `contentRootsFor` — `withPlatformDefaults` (in `shared/config.ts`) fills a *gap* and never overrules a stated value. A site whose `_config.yml` lists twelve collections of which the author registered two meant two.

The **platform gets one veto and no vote** over filenames. Where a content root says `datePrefix: 'forbidden'`, `filePrefixFor` drops the configured prefix, because writing `2026-09-09-` onto a Hugo file silently changes the page's address. It never *adds* a prefix: the one platform that requires one is Jekyll, and `governance/publish.ts` has stamped it at write time since long before profiles existed.

## Known limits, stated rather than hidden

**JavaScript configuration is not read.** `docusaurus.config.js` and `astro.config.mjs` are code; `readSiteConfigFacts` returns empty facts and one warning naming the file, and the profile's documented defaults apply. A regex over somebody's TypeScript eventually reads a value out of a comment. A site that moved `routeBasePath` or set a `base` says so in `zer0.json`'s `platform.overrides`.

**Material's blog URL scheme is not modelled.** A page under `docs/blog/posts/` derives the same directory URL as any other MkDocs page. The plugin's `post_url_format` default puts the date in the path, and reproducing that would mean reading plugin options this parser does not reach — so the profile declares the blog root (and its required `date:`) and stops short of claiming its URL.

**Astro's schema is code, so its required keys are a convention.** The zod object in `content.config.ts` is the real authority; the profile records the official blog template's keys as *recommended* and requires only `title`. Requiring a key the site never declared would file an issue against every page.

**Wiki.js has a second writer.** Its content roots are `shared-writer`: git storage syncs both ways on a schedule and commits wiki edits back as its own author. An editor here must expect the file it is holding to change underneath it, and must never assume its ledger is the only publisher.

## Testing

`src/test/platform.test.ts` (37 tests) and the byte-identity golden at `src/test/fixtures/golden/platform/`. Six fixture sites live under `src/test/fixtures/sites/`, each written in its platform's own idiom — TOML `+++` for Hugo, `published:`/`dateCreated:` for a Wiki.js export, a number-prefixed filename and `sidebar_position` for Docusaurus, `pubDate` under `src/content/` for Astro, and a YAML anchor in the fleet's `_config.yml` so the anchor warning is exercised against a real file rather than a contrived string.

The golden is the load-bearing one. Run it after any change in this package:

```bash
npx tsc -p . --outDir out
node src/test/fixtures/golden/platform/generate.mjs | diff src/test/fixtures/golden/platform/jekyll-projection.json -
```

Silence means Jekyll's answers did not move. Output means they did — and that is either a bug to fix or a decision somebody has to write down. Never hand-edit the golden to make it pass.
