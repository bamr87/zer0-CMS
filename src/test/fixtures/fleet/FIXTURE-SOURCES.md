# Fixture sources — verbatim copies, with origin and commit

Every file under `src/test/fixtures/fleet/` is a **byte-verbatim** copy of a file that exists in another repository (or in this one). Nothing here is authored: the point of the directory is that the parity, drift and golden tests run against the fleet as it actually is, not against a shape somebody typed to make a test pass.

**Never hand-edit a copy.** When a fixture needs to move forward, re-copy it from the origin path at a newer commit and update the row below — and expect a golden under `src/test/fixtures/golden/engines/` to change with it, which is the whole point.

Staged 2026-09-09.

| fixture path | origin repo | origin path | commit |
|---|---|---|---|
| `manifests/lifehacker.fleet.manifest.yml` | `bamr87/lifehacker.dev` | `fleet.manifest.yml` | `9ee9059` |
| `manifests/it-journey.fleet.manifest.yml` | `bamr87/it-journey` | `fleet.manifest.yml` | `dbb88733` |
| `manifests/zer0-mistakes.fleet.manifest.yml` | `bamr87/zer0-mistakes` | `fleet.manifest.yml` | `4edc0010` |
| `manifests/irony-works.fleet.manifest.yml` | `bamr87/irony-works` | `fleet.manifest.yml` | `cb0647e` |
| `manifests/ai-world-view.fleet.manifest.yml` | `ai-world-view/ai-world-view.github.io` | `fleet.manifest.yml` | `d7a99a7` |
| `manifests/zer0-cms.fleet.manifest.yml` | `bamr87/zer0-CMS` (this repo) | `fleet.manifest.yml` | `6401bb05` |
| `harness_registry.yml` | `bamr87/bamr87` | `_data/harness_registry.yml` | `b004623` |
| `projects.yml` | `bamr87/bamr87` | `_data/projects.yml` | `1263038` |
| `workflows/hub/ai-lane.yml` | `bamr87/bamr87` | `.github/workflows/ai-lane.yml` | `7e6ba1e` |
| `workflows/hub/ai-lane.template.yml` | `bamr87/bamr87` | `templates/ai-runner/ai-lane.template.yml` | `7e6ba1e` |
| `workflows/hub/claude-run.action.yml` | `bamr87/bamr87` | `.github/actions/claude-run/action.yml` | `7e6ba1e` |
| `workflows/lifehacker/content-factory.yml` | `bamr87/lifehacker.dev` | `.github/workflows/content-factory.yml` | `50e1ce4` |
| `workflows/lifehacker/explore.yml` | `bamr87/lifehacker.dev` | `.github/workflows/explore.yml` | `50e1ce4` |
| `workflows/lifehacker/auto-fix.yml` | `bamr87/lifehacker.dev` | `.github/workflows/auto-fix.yml` | `50e1ce4` |
| `workflows/lifehacker/theme-scout.yml` | `bamr87/lifehacker.dev` | `.github/workflows/theme-scout.yml` | `50e1ce4` |
| `workflows/lifehacker/pipeline.yml` | `bamr87/lifehacker.dev` | `.github/workflows/pipeline.yml` | `50e1ce4` |
| `workflows/lifehacker/triage.yml` | `bamr87/lifehacker.dev` | `.github/workflows/triage.yml` | `e8f5cbd` |
| `workflows/lifehacker/ai-usage.yml` | `bamr87/lifehacker.dev` | `.github/workflows/ai-usage.yml` | `e8f5cbd` |
| `workflows/lifehacker/factory--issue-factory-1.yml` | `bamr87/lifehacker.dev` | `.github/workflows/factory--issue-factory-1.yml` | `e8f5cbd` |
| `workflows/it-journey/cms-daily-loop.yml` | `bamr87/it-journey` | `.github/workflows/cms-daily-loop.yml` | `9aa0faf1` |
| `workflows/it-journey/quest-walkthrough.yml` | `bamr87/it-journey` | `.github/workflows/quest-walkthrough.yml` | `7fd3cc59` |
| `workflows/it-journey/issue-autopilot.yml` | `bamr87/it-journey` | `.github/workflows/issue-autopilot.yml` | `7fd3cc59` |
| `workflows/zer0-mistakes/ai-content-review.yml` | `bamr87/zer0-mistakes` | `.github/workflows/ai-content-review.yml` | `f048cb22` |
| `workflows/zer0-mistakes/ui-audit.yml` | `bamr87/zer0-mistakes` | `.github/workflows/ui-audit.yml` | `ab926194` |
| `workflows/zer0-mistakes/translate.yml` | `bamr87/zer0-mistakes` | `.github/workflows/translate.yml` | `19cea462` |
| `workflows/zer0-mistakes/issue-autopilot.yml` | `bamr87/zer0-mistakes` | `.github/workflows/issue-autopilot.yml` | `4edc0010` |
| `workflows/zer0-mistakes/issue-pr-auto-merge.yml` | `bamr87/zer0-mistakes` | `.github/workflows/issue-pr-auto-merge.yml` | `a8931750` |
| `workflows/bash-365/content-loop.yml` | `amr-bash/bash-365.com` | `.github/workflows/content-loop.yml` | `14fe3ae` |
| `workflows/bash-365/content-gardener.yml` | `amr-bash/bash-365.com` | `.github/workflows/content-gardener.yml` | `14fe3ae` |
| `workflows/bash-365/content-review.yml` | `amr-bash/bash-365.com` | `.github/workflows/content-review.yml` | `5a99d88` |
| `workflows/bash-365/preacher.yml` | `amr-bash/bash-365.com` | `.github/workflows/preacher.yml` | `d605957` |
| `workflows/irony-works/germinate.yml` | `bamr87/irony-works` | `.github/workflows/germinate.yml` | `cb0647e` |
| `workflows/ai-world-view/grow-lineage.yml` | `ai-world-view/ai-world-view.github.io` | `.github/workflows/grow-lineage.yml` | `67c5049` |

## `projects.yml`

The hub's `_data/projects.yml` is the fleet's project registry — the join key every dash surface uses. Nothing reads it yet: it is staged here for the roster reader that lands with the multi-repo slice, copied now so its provenance is recorded at the same commit as everything else in this directory rather than reconstructed later.

## The seventh manifest

The parity suite reads **seven** committed manifests: the six above plus `src/test/fixtures/workspace/fleet.manifest.yml`, which is an **older** `bamr87/irony-works` `fleet.manifest.yml` (commit `92076039` in this repository, added with the Fleet console) and lives beside the fixture workspace because `fleet.test.ts` reads it as this repository's stand-in fleet. It is not duplicated here; it is read from where it already is.

`amr-bash/bash-365.com` deliberately contributes **no** manifest. It is the fleet's "lanes with no manifest" case: four real AI workflows and nothing that declares them, which is what a repository looks like before `wtd fleet adopt` has ever run and what `inspectWorkspaceFleet` must survive.

## Two things these copies prove that a hand-written fixture could not

**Four of the seven manifests are not valid YAML.** `wtd fleet adopt` wraps a single-quoted scalar at column 80 and puts the continuation line at column 0 — outside the block's indentation:

```yaml
  purpose: 'Preferred Claude auth (house convention: OAuth first). Produced by
`claude setup-token`.'
```

The `yaml` package throws on that, so `@bamr87/fleet-engines`' `parseFleetManifest` returns an **empty** manifest — with `skipped: 0`, so a caller cannot even tell it failed. This repository's own tolerant `parseYamlSubset`-based reader parses all seven. `engines.test.ts` pins both halves: parity where the package can read, and the disagreement where it cannot.

**lifehacker's `content-factory` lane says `opens_pull_requests: false` and the workflow opens pull requests.** The workflow file is checked in here beside the manifest that misdescribes it, so the drift row the console shows is derived from the real bytes rather than asserted from a comment.
