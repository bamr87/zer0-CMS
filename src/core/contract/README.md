# `src/core/contract` — the `.cms/` file bus

Two files that read what the content engine produced, and run the engine that produces it. Pure Node — see `../README.md` for the layering rule.

| File | Exports | Owner |
|---|---|---|
| `contract.ts` | `CMS_DIRNAME`, `INDEX_DIRNAME`, `DISTRIBUTION_DIRNAME`, `PUBLISHABLE_HEALTH`, `FRESH_BANDS`, `METRICS`, `Contract`, `LoadContractOptions`, `CmsSummary`, `CollectionSummary`, `loadContract`, `loadContractOrScan`, `cmsDir`/`indexDir`/`distributionDir`, `isDistributable`, `isEditable`, `healthBucket`, `recordSlug`, `distributable`, `byPath`, `byCollection`, `issueKinds`, `issuesByLane`, `issuesBySeverity`, `normalisePerformance`, `performancePath`, `loadPerformance`, `writePerformance`, `worklistPath`, `writeWorklist` | WP07 |
| `engine.ts` | `EngineCommand`, `ENGINE_COMMANDS`, `EngineConfig`, `EngineResult`, `CHANGES_PENDING_CODE`, `SKIP_MARKER`, `engineConfigFor`, `runEngine`, `runNormalizerPreview`, `runNormalizerApply`, `condenseNormalizerOutput` | WP07 |

## What `.cms/` is

A directory the *user's* repository owns, written by a Python content engine that lives there — not by this extension. It is the machine-readable view of a whole site, so that a health score means the same thing in the dashboard, in the catering worklist and in an MCP tool result.

    .cms/
      index/content-index.json     ← read: one record per page
      index/summary.json           ← read: the engine's roll-up
      distribution/performance.json   ← written by us: aggregate engagement
      distribution/worklists/<date>-catering.md  ← written by us

We read the index and write only under `distribution/`. `zer0Cms.cms.root` moves the whole directory, which is why `Contract` carries `dir` rather than recomputing `<root>/.cms` in every writer.

## Contracts worth knowing before you change anything

**Absence is a normal state (D9), and `loadContract` never throws.** No `.cms/` yields `{ present: false, generatedAt: '', records: [], summary: {} }` — the same shape, so callers branch on `present`, not on `undefined`. A missing file, a directory where a file should be, and malformed JSON are all the same answer: this repository has no engine yet. Turning that into a rejected promise would make "no engine" an error at every call site in the product.

`loadContractOrScan(cfg)` is the version the shell and the MCP server use: when the index is missing it fills `records` from `content/pageIndex`, with `health: -1` and `freshness: 'unknown'`. **`present` stays `false`** — the records are real, the engine's judgement is not. A scan failure degrades to "no records" and a `log.warn`, for the same reason.

**Health `70` in, `69` out, `-1` in.** `isDistributable` refuses drafts, generated files and structural pages outright; a *scored* page must reach `PUBLISHABLE_HEALTH = 70`; an *unscored* one is not punished for the engine's absence and only needs a title. That last clause is what makes the D9 fallback honest instead of empty. The three boundary values are pinned by test.

**`isEditable` is a different question.** `isDistributable` asks "may we show this to an audience"; `isEditable` asks "may a tool write to it". A vendored, generated or notebook file is off limits however well it scores.

**Issues keep their lane.** `ContentRecord.issues` is `CmsIssue[]` — kind, severity, field, message, **lane**, suggestion. BASH-CMS's port flattened this to a list of `kind` strings; the mechanical-versus-substantive split is the premise of the whole curation workflow (mechanical is safely auto-fixable, and `normalize-apply` fixes exactly that half), so it survives here and `issueKinds()` is the derived helper for callers that only wanted the names.

Two coercion defaults are deliberate: an **unrecognised severity becomes `warning`**, so a level we have not met yet is not silently made invisible, and an **unrecognised lane becomes `substantive`**, because "a human should look at this" is the safe answer when we cannot tell whether a fix is mechanical.

**Everything is coerced at the boundary.** `Number` + `Math.trunc` with a defined fallback, `String(x ?? '')`, explicit `null` for `draft`/`date`/ `lastmod`. `NaN` never escapes. The engine's spelling is snake_case and our own writers use camelCase, so `pick()` accepts both. A malformed index produces a wrong-but-well-typed record instead of a `TypeError` three modules away.

**`CmsSummary` is typed, and every field is optional.** An absent `.cms/` yields the literal `{}`, and an engine version that has not learned a key yet must not force every reader through a `?? 0` dance for a number it never wrote.

**`normalisePerformance` drops unknown keys.** Only the five metrics in `METRICS` survive, and `engagements` is derived (`reactions + comments + shares`), never read raw. That is what makes `performance.json` safe to hand to an agent: whatever an upstream export contains, only five counters get into the repository.

**Writes under `distribution/` are atomic; nothing else is written at all.** `writePerformance` uses `pyJsonDump(…, { indent: 2, ensureAscii: true }) + '\n'` so the Python lane can read and rewrite the same file byte for byte.

## The engine driver

`EngineConfig.root` is the **working directory the scripts run in** — the repository root, because that is what their relative paths resolve against. It is *not* `Zer0Config.cms.root`, which locates the `.cms/` output directory. `engineConfigFor(cfg)` makes the distinction for you; the two being different things with the same name is the one trap in this module.

**Nothing rejects.** Every runner resolves an `EngineResult`. A missing interpreter, a missing script and a script that exited 1 are all normal outcomes for a tool that runs against somebody else's repository, and the caller wants to show the output either way. A failure to *start* the process (`ENOENT`, `EACCES`) is reported as code 1 with the reason prepended to stderr, so "python3 is not installed" reads as a failed run rather than a silent zero.

**Exit code 2 means "changes pending", not failure** — the normalizer's dry-run signal for "there is work to do". The zer0 layer documented that in a comment and then dropped it on the floor; `EngineResult.changesPending` makes it a value. Note that the promise is the *normalizer's*: `python3` itself exits 2 when it cannot open a script, so a caller reporting an engine subcommand should say "exited 2", and only the normalize paths should say "changes pending". `src/mcp/tools.ts` does exactly that.

`condenseNormalizerOutput` strips the `read-only/vendored` chorus and returns the count. On a large site those lines outnumber the real ones ten to one, and a reviewer scrolling past them is a reviewer who has stopped reading.

## Tests

`src/test/governance.test.ts` covers health 70/69/-1, `present: false` on a missing index, `normalisePerformance` dropping unknown keys, the `CmsIssue` lane surviving a round trip through `loadContract`, and the scan fallback producing the same record shape. `src/test/golden.test.ts` holds the cross-lane byte contract for `distribution/`.
