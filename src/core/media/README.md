# `core/media` — reuse the image the site already made

zer0-image-generator already solves social imagery: a three-stage pipeline that writes an art brief from the article, renders it, reviews the render, and wires the result into front matter. A share wants exactly that image.

**So this module generates nothing.** It resolves what the site already produced, and when there is none it emits the request the generator takes as input. Rendering stays where the provider matrix, the review stage and the credential chain live — a second renderer here would be a second definition of what a preview image is, and they would drift.

## Why it exists when publishing already reads the image

`governance/publish` calls `previewImageValue` and, finding nothing, posts without a thumbnail. That is right for one post — a missing image should never block publishing — but it is silent, so a repository can drift into publishing dozens of untreated links with nobody noticing.

This module makes the same question askable *across* the content set, before anything is published, and answers it with the generator's own command.

## It shares the vocabulary with publishing

`THUMBNAIL_KEYS` and `previewImageValue` are imported from `governance/publish`, not restated. A page that looked covered in the media report and then published without a thumbnail would be worse than no report at all.

## The generator's command comes from the platform profile

`briefFor` reads `profile.commands.previewImages` — `jekyll preview-images` for Jekyll and for a zer0-mistakes site, which is the literal this module used to hard-code. A platform with no generator wired up says `null`, and the brief then names the article and stops. Telling somebody to run a command that does not exist on their site is worse than telling them nothing, because they will try it.

## Resolution order

1. **Front matter** — authoritative wherever the generator has run.
2. **The conventional path** (`assets/images/previews/<slug>.*`) — catches an image produced before front matter was wired up.
3. **Nothing** — plus a brief.

A declared path that is not on disk falls through to the convention rather than counting as found. A broken link is not coverage.

## Shape

| Export | Purpose |
|---|---|
| `resolveMedia(root, record, data?, profile?)` | one page's image, or a brief |
| `mediaCoverage(root, records, frontMatterOf?, profile?)` | the whole set; sequential, to stay inside the fd table |
| `renderCoverage(coverage)` | as text, listing only the gaps |
| `briefFor(record, profile?)` | the generator request alone |

`profile` defaults to `JEKYLL_PROFILE` everywhere it appears, so a caller that has not resolved a platform gets exactly the brief this module always emitted.
