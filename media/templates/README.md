# `media/templates` — the files a generated lane is written from

Three files, shipped inside the vsix (`.vscodeignore` excludes only `media/README.md`, and `src/**` is not packaged, so a template kept beside the tests would not exist at runtime). The Harness route reads them from `context.extensionUri` when it plans a scaffold, which is why they live under `media/` with the stylesheets rather than under `src/`.

## What each file is, and where it came from

| File | Origin | Origin path | Commit | Authored here? |
|---|---|---|---|---|
| `ai-lane.template.yml` | `bamr87/bamr87` | `templates/ai-runner/ai-lane.template.yml` | `7e6ba1e` | no — **verbatim** |
| `ai-runner.VERSION` | `bamr87/bamr87` | `templates/ai-runner/VERSION` | `7e6ba1e` | no — **verbatim** |
| `agent.template.md` | this repository | — | — | yes |

Two more copies of the same upstream files sit under `src/test/fixtures/harness/hub/` — `ai-lane.template.yml`, `VERSION`, and additionally `ai-lane.yml` (the hub's reusable workflow, `bamr87/bamr87@7e6ba1e .github/workflows/ai-lane.yml`, which is not shipped because nothing at runtime reads it). `lanes.test.ts` asserts the shipped copies are **byte-identical** to the fixture copies, so a refresh of one that forgets the other is a failing test rather than a generator quietly rendering against a template the tests no longer pin.

## The rule for refreshing a vendored file

1. Re-copy it from the origin path above at a newer commit — **into both places**, `media/templates/` and `src/test/fixtures/harness/hub/`.
2. Update the commit in the table above.
3. Re-run the golden generator: `node src/test/fixtures/golden/lanes/generate.mjs` (it needs `npx tsc -p . --outDir out` first).
4. **Read the golden diff.** A reworded comment is nothing; a moved `with:` key, a changed default, or a renamed input is a change in what this console generates, and that is exactly the moment to notice it.

Never hand-edit a vendored copy. A local edit to `ai-lane.template.yml` is a fork of somebody else's artefact that nothing upstream will ever hear about; if the template is wrong, it is wrong in `bamr87/bamr87`.

## What is NOT vendored, and must never be

The runner itself. `.github/actions/claude-run` and `.github/workflows/ai-lane.yml` are consumed **by reference** — `uses: bamr87/bamr87/.github/actions/claude-run@main` and `uses: bamr87/bamr87/.github/workflows/ai-lane.yml@main` — because the 2026-09-06 fleet review found three divergent copies of one `claude-run` contract (three hashes, one name) and two of them exiting 0 on a dead credential. A generated lane points at the hub; it never carries a copy of it. The `VERSION` file is vendored only so the `# kit: ai-runner v<version>` stamp can be written without a network call.

## `ai-lane.template.yml` — the five placeholders

`renderAiLaneCaller` substitutes exactly these, and nothing else:

| Placeholder | Filled with |
|---|---|
| `__KIT_VERSION__` | the `version:` from `ai-runner.VERSION` |
| `__LANE__` | the lane id — the workflow `name:`, the `lane:` input, the concurrency group, the metering role |
| `__SWITCH__` | the `*_ENABLED` variable name **without** its suffix (the template supplies `_ENABLED`) |
| `__AGENT__` | the `.claude/agents/<name>.md` role |
| `__PROJECT_NAME__` | the site's own name, for the prompt |

`__PLACEHOLDERS__`, in the second header comment, is prose about the placeholders and is deliberately not one of them.

Beyond those five, the renderer replaces a short list of **whole, named lines** — the cron, the extra events, the permission entries, the prompt, the tools, and the `setup-ruby` / `result-file` pair that becomes the rest of the `with:` block. They are matched by their complete text (`AI_LANE_OWNED_LINES` in `src/core/harness/render.ts`), so a refreshed template that reworded one of them fails a test instead of rendering a lane with a stale schedule or a hard-coded Ruby version. Every other line — the three header comments, the `uses:` reference, the `secrets:` block, the least-privilege note — comes through byte-for-byte, because it is the hub's documentation of the hub's own shape.

## `agent.template.md` — ours, and why it is a file

The role a generated lane runs as. It is authored here rather than vendored, because the hub's `agent-context` kit templates a *specific* agent (`agent-auditor`), not a blank one. It is a file rather than a string literal for the same reason the lane template is: a person can read it, diff it, and see what their agent file will say before anything is written.

Its placeholders: `__KIT_VERSION__`, `__AGENT__`, `__DESCRIPTION__`, `__TOOLS__`, `__VERB__`, `__PROJECT_NAME__`, `__LANE__`, `__SKILL_CLAUSE__`, `__RESULT_FILE__`.

Two things in it are load-bearing and a test asserts both. The **guardrail citation** — `.claude/skills/_shared/quarantine.md — all sections apply.` — is a citation on purpose: an agent file that restates the untrusted-input rules in its own words is one that will drift from them. And the **Hard rules** end where every agent file in this fleet ends: write the resulting PR URL to the result file, and never merge.
