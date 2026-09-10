<!-- docs/RELEASING.md — how a zer0-CMS release actually happens, for a person. What release-please owns, what this repository owns, which secrets have to exist before a registry publish can work, and the operator steps that are still outstanding. -->

# Releasing zer0-CMS

Nobody edits a version number by hand in this repository. Conventional Commits on `main` drive everything: the version, the changelog, the tag, the GitHub Release, and the packaged extension attached to it. This page explains the machinery so that when it does something surprising you can tell whether it was right.

## The short version

Merge a `feat:` or `fix:` commit to `main` → release-please opens a **release PR** → you read and merge that PR → a tag, a Release, and a `.vsix` appear. Nothing publishes to a marketplace until somebody provisions a token, and until then a release still produces a downloadable extension.

## The two halves of `.github/workflows/release.yml`

### `release` — the shared half

The `release` job is a thin caller of `bamr87/.github/.github/workflows/release-please.yml@main`, the fleet's shared release-please workflow. This repository contributes only two files to it:

- **`release-please-config.json`** — `release-type: node` (the version lives in `package.json`), `changelog-path: CHANGELOG.md`, and `include-component-in-tag: false` so tags are `v0.2.0` rather than `zer0-cms-v0.2.0`.
- **`.release-please-manifest.json`** — the released version, `{".": "0.1.0"}`. release-please rewrites this file; you do not.

The config also carries **`bootstrap-sha: 9f729741954de209ea5afa97d710c01ca42f72ad`** at the top level, which is where release-please reads it — not inside the package block. That commit is `refactor!: break free from the Front Matter fork`, the first commit of zer0-CMS as its own project. Without it, release-please walks back through the entire inherited Front Matter history and reads five years of somebody else's Conventional Commits as this project's unreleased changes.

On every push to `main` the job opens or updates one release PR that bumps `package.json` and `.release-please-manifest.json` and rewrites `CHANGELOG.md`. **Merging that PR is the release.** The shared workflow also re-locks `package-lock.json` on the release PR's own branch in the same run, so the merge commit is self-consistent and `npm ci` works at the tag.

The job's `concurrency` group is `release-please-main` with `cancel-in-progress: false`. A half-cancelled release leaves a tag without a Release, or a Release without a `.vsix`; waiting is always cheaper than reconciling that by hand.

### `marketplace` — this repository's half

A VS Code extension is not an npm package, so the hub's generic publish workflow has no path for it. The `marketplace` job is therefore repo-owned. It runs only when the release job reports `release_created == 'true'`, checks out the new tag, and then, in order:

1. **Packages** — `npx @vscode/vsce package --no-dependencies -o zer0-cms-<version>.vsix`. `vsce package` runs `vscode:prepublish`, so this type-checks, lints and bundles in production mode before it writes anything.
2. **Verifies the file list** — `vsce ls --no-dependencies`, sorted, diffed against the committed `.vsix-manifest.txt`. What ships is a reviewed artefact, not a side effect of whatever `.vscodeignore` happens to say. Regenerate that file with `npx @vscode/vsce ls --no-dependencies | LC_ALL=C sort > .vsix-manifest.txt` and read the diff.
3. **Attaches the `.vsix` to the GitHub Release** — `gh release upload <tag> <vsix> --clobber`. This is the distribution path that needs no marketplace account and no token beyond the run's own `GITHUB_TOKEN`. Any machine in the fleet can then install the exact released build:

   ```bash
   gh release download v0.2.0 --repo bamr87/zer0-CMS --pattern '*.vsix'
   code --install-extension zer0-cms-0.2.0.vsix
   ```

4. **Publishes to the Visual Studio Marketplace** — `vsce publish --packagePath …`, gated on `VSCE_PAT`.
5. **Publishes to Open VSX** — `ovsx publish … -p $OVSX_PAT`, gated on `OVSX_PAT`.

Steps 4 and 5 **skip with a `::notice::` when their token is absent — they never fail the run.** The publisher account and both tokens do not exist yet, and a release that cannot reach a registry must still produce a tag, a changelog and an installable file. The presence check happens inside the shell rather than in an `if:` because GitHub does not expose the `secrets` context to a step-level condition.

## Secrets

| Secret | Used by | Needed for | How to provision |
|---|---|---|---|
| `RELEASE_PLEASE_TOKEN` | the shared `release` job | Making the release PR's commits trigger CI. Commits pushed with the default `GITHUB_TOKEN` do not start other workflows, so without this the release PR shows no checks. | A fine-grained PAT on `bamr87/zer0-CMS` with **Contents: read & write** and **Pull requests: read & write**. Set it as a repository secret. Optional — the shared workflow falls back to `github.token`. |
| `VSCE_PAT` | the `marketplace` job | Publishing to the Visual Studio Marketplace. | Create an Azure DevOps organisation, then a Personal Access Token scoped to **all accessible organizations** with **Marketplace: Manage**. It must belong to the same Microsoft account that owns the `bamr87` publisher. |
| `OVSX_PAT` | the `marketplace` job | Publishing to Open VSX. | Sign in to <https://open-vsx.org> with GitHub, sign the publisher agreement, create the `bamr87` namespace, then generate an access token from your profile. |

None of these are optional-but-nice for the *tag*: a release works with all three absent. They are only the difference between "installable from the Release page" and "installable from the extension marketplaces".

## Why `package.json` is `"private": true`

Because an extension manifest must never be routed to `npm publish`. `package.json` here describes a VS Code extension — `contributes`, `activationEvents`, `engines.vscode` — and publishing it to the npm registry would put a package on npm that nothing can consume and that squats a name. The `private` flag makes that a hard error in npm itself rather than a convention someone has to remember.

It also steers the fleet's tooling. The hub's `detect-stack` step reads `package.json` and, seeing `"private": true`, reports `registry=none` instead of `registry=npm` — which is why the shared publish workflow is not wired in here at all and the `marketplace` job exists instead. The flag is load-bearing in two directions; do not remove it to make a tool happy.

## Why the lockfile is committed

Against the hub's `lockfiles: never-commit` posture, and deliberately. Three reasons, in increasing order of importance: `npm ci` needs it, and both `extension.yml` and the `marketplace` job use `npm ci`; the shared release workflow's re-lock step needs one to sync; and `@bamr87/fleet-engines` is exact-pinned because a bump changes generated goldens, which is only reproducible with a lockfile. This is recorded as a standard deviation in `CLAUDE.md`.

## Operator steps still outstanding

None of these can be done from a pull request. They need somebody with the repository's and the accounts' credentials.

1. **Create the Marketplace publisher `bamr87`.** `package.json` already claims `"publisher": "bamr87"`; the publisher does not exist yet. Create it at <https://marketplace.visualstudio.com/manage>, then mint `VSCE_PAT` as described above.
2. **Create the Open VSX namespace `bamr87`** and mint `OVSX_PAT`.
3. **Tag `v0.1.0` on `9f729741954de209ea5afa97d710c01ca42f72ad`.** `.release-please-manifest.json` says the released version is `0.1.0`, and `bootstrap-sha` says history starts there — but there is no `v0.1.0` tag to match. Creating it makes the manifest, the tags and the history tell the same story before the first real release moves anything.
4. **Delete the 77 inherited Front Matter tags.** `git ls-remote --tags` on this repository returns 77 tags belonging to `estruyf/vscode-front-matter`, the newest of which is `v10.10.1`. They are not this project's releases, they make `v0.2.0` look like a catastrophic downgrade in every UI that sorts tags, and they are a standing trap for any tool that infers "latest" from tags rather than from the manifest. Delete them remotely and locally:

   ```bash
   # Read the list first. This deletes tags; there is no undo.
   git ls-remote --tags bamr87/zer0-CMS
   ```

5. **Ask GitHub to detach the fork.** `bamr87/zer0-CMS` is still recorded as a fork of `estruyf/vscode-front-matter`. That is why `gh` in a local clone resolves commands to the *parent* repository unless you pass `-R bamr87/zer0-CMS`, and why pull requests default to the wrong base. Support can detach it. Until they do, every `gh` invocation in a script here must carry `-R bamr87/zer0-CMS`.
6. **Consider enabling issues.** Issues are currently disabled on the repository, which makes `.github/ISSUE_TEMPLATE/` staged rather than live. The templates are kept correct so that turning issues on is a settings change and not a documentation project.

## Cutting a release, start to finish

1. Merge the work. Use Conventional Commits: `feat:` bumps the minor, `fix:` the patch, and a `!` or a `BREAKING CHANGE:` footer bumps the major.
2. Watch for the release PR titled `chore(main): release <version>`. Read the changelog diff it proposes — this is the one moment where a badly-worded commit subject becomes a permanent, public sentence.
3. Merge the release PR. The same run tags, releases, packages, uploads, and attempts both registries.
4. Check the Release page for the attached `.vsix`, and the run log for either a publish or the `::notice::` that says which token is missing.

## See also

- `.github/workflows/release.yml` — the workflow itself, commented.
- `.vsix-manifest.txt` — the reviewed list of what ships inside the extension.
- `docs/ARCHITECTURE.md` — why the extension ships zero runtime dependencies, which is what makes `--no-dependencies` honest.
- `CLAUDE.md` — the standard deviations, including the committed lockfile.
