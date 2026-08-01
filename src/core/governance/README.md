# `src/core/governance` — the governed queue

Five files that decide what gets published, and record what did. Pure Node — see `../README.md` for the layering rule.

| File | Exports | Owner |
|---|---|---|
| `drafts.ts` | `STATUS_*`, `DRAFT_STATUSES`, `DraftFile`, `NewDraft`, `parseDraft`, `readDraft`, `listQueue`, `commentaryOf`, `noThumbnail`, `titleOf`/`descriptionOf`/`sourceOf`/`linkOf`/`slugOf`, `writeDraft`, `markStatus` | WP06 |
| `guard.ts` | `FOLD`, `MAX_LEN`, `GuardFinding`, `BannedPattern`, `BANNED_PATTERNS`, `FILLER`, `guardText`, `hasErrors`, `errorMessages`, `loadWorkspacePatterns`, `workspacePatterns`, `guardWithWorkspace` | WP06 |
| `ledger.ts` | `TOKEN_KEY`, `LedgerEntry`, `Ledger`, `loadLedger`, `saveLedger`, `getEntry`, `isPublished`, `record`, `shareEntries`, `publishedSourceFiles`, `readMeta`, `writeMeta` | WP06 |
| `approval.ts` | `BlockerKind`, `Blocker`, `GateInput`, `evaluateGates`, `evaluateApproveGates`, `evaluatePublishGates`, `hasBlocker`, `blockerSummary` | WP06 |
| `publish.ts` | `PreviewRequest`, `Preview`, `PublishPlan`, `PublishOutcome`, `PublishTarget`, `PublishDeps`, `buildPreview`, `previewRequestFromDraft`, `publishPreview`, `canonicalUrl`, `resolveSource`, `destinationFolder`, `jekyllTarget`, `targetById`, `targetFor`, `registerTarget`, `listTargets` | WP06 |

## The lifecycle, in one paragraph

A draft lands in `governance.draftsFolder` as a markdown file — written by a human, by `zer0Cms.draft.new`, or by the agent through the MCP `zer0_draft` tool. `listQueue` reads the folder; `guardText` reads the commentary; `buildPreview` renders the exact artifact a publish would produce; `evaluatePublishGates` says whether it may go; `publishPreview` runs the gates again, hands the artifact to a `PublishTarget`, and records the result in the ledger. Approving (`pending` → `approved`) and publishing (`approved` → `published`) are two separate human acts, and `markStatus` performs each as a one-line diff.

## Contracts worth knowing before you change anything

**`approval.ts` is the only place that decides.** Three callers ask it the same question — the webview (advisory, to render a disabled button and its note), the command the user invokes (authoritative), and `publish.ts` (final, right before the target sends). Decision D5: *the webview is UI, never the gate.* If you find yourself adding a condition to a button's `disabled` attribute, add a `BlockerKind` instead. The order of `Blocker[]` is fixed and tested:

    noWorkspace, publishDisabled, guardError, alreadyPublished,
    statusNotAccepted, requiredFieldMissing, previewFailed

**`force` never overrides `publishDisabled`.** It overrides the guard and the ledger, because a human who has read the findings is allowed to decide. A workspace that has not set `governance.publishAllow` has not consented, and a flag on a call site is not consent.

**An already-published URL is `{ skipped }`, not an error.** Publishing twice is the failure; being *asked* to twice is not. `publishPreview` returns a skip message and exit code zero all the way up, so a re-run of a CI job or a double-click is boring rather than red.

**The ledger key is the coordination.** One flat JSON file, keyed by canonical URL. Whichever lane publishes a URL first writes the key; every other lane looks it up and skips. No lock, no lease, no shared process — which only works if both lanes agree on the file byte for byte, hence `pyJsonDump(…, {indent: 2, sortKeys: true, ensureAscii: true}) + '\n'` written atomically. Keys beginning with `_` are metadata; **always enumerate shares through `shareEntries`**, which drops those and any entry without a `urn`.

**An atomic write is not a serializable update.** `record` and `writeMeta` each read the whole file, change one key and write it back; two of those interleaved lose a key outright, and a lost key means the URL republishes. Both go through `mutate`, which serializes the cycles per ledger path *inside this process* and then reads the file back and retries when another process's write landed on top. Convergent rather than exclusive: nothing here can lock a file against the Python lane, and a lock protocol that lane does not implement would be theatre.

**Writing the artifact and recording it are two steps, and the gap is real.** A crash — or a read-only `.zer0/` — between them leaves a page on disk that no ledger key mentions. On the retry `jekyllTarget.send` gets `EEXIST`, compares the file already there against the artifact it was about to write (ignoring the `date` stamp, which is the only part that is a function of *when* rather than *what*), and **adopts** it instead of bumping to `-2`. The `-2` chain is for a different page that wants the same name; using it for a retry left two live pages for one canonical URL, with the ledger naming the wrong one.

With no site base URL in the config, `canonicalUrl` produces a site-*relative* permalink: a `permalink` / `canonical_url` in the front matter wins verbatim, otherwise the path with its extension, its `YYYY-MM-DD-` filename prefix and the leading underscore of a Jekyll collection folder removed (`pages/_posts/2026-07-31-hello.md` → `/pages/posts/hello/`). Deriving the key from a configurable domain would change every key the day somebody moves the domain, which is the one thing a ledger must never do.

**A missing ledger and a corrupt ledger both read as `{}`.** "Nothing has been published" makes the caller check its other gates; a thrown parse error would make a broken file block every read in the product.

**`buildPreview` writes nothing and calls nothing.** It reads files and it computes. Every screen, every dry run, and the MCP `zer0_preview` tool go through it, so what a reviewer approves is the literal artifact — the bytes `jekyllTarget.send` will write — not a description of them that can drift. `PublishTarget.build` is held to the same rule; `send` is the only half allowed to touch the world.

**Nothing here overwrites a page.** `jekyllTarget.send` writes with the `wx` flag and bumps the filename to `-2`, `-3` on collision, reporting the bump as a warning. `writeDraft` resolves queue collisions the same way. A publish that silently replaced somebody's article would be the worst bug this module could have.

**`markStatus` changes exactly one line.** It replaces the first line whose trimmed form starts with `status:` and normalises the file to a single trailing newline; every other byte survives, including comments and key order. That property is why drafts are never round-tripped through a serialiser, and it is the same reason `content/serialize.ts` edits front matter by line surgery (D7). A draft with no status line at all gets one inserted after the opening fence — silently doing nothing would leave the queue claiming a draft is still pending after it published.

**Draft writes are not atomic; ledger writes are.** A draft is a file a human may have open in an editor, and `atomicWriteFile` replaces the inode, detaching editors and watchers. Same rule as `content/article.ts`.

## The guard

`FOLD = 140`, `MAX_LEN = 3000`, 13 hard bans (`error`), 9 filler patterns (`warning`), a weak-hook check (`warning`), and exactly one always-appended fold `info` — so a clean string yields precisely one finding. The counts are pinned by test: adding a rule means updating both the constant and the test, deliberately.

Two deduplications keep the output honest: the filler entry named `exclamation mark` is skipped because a dedicated check already reported it, and a filler entry whose name already produced an *error* is skipped. `synergy` is deliberately **not** deduped against the ban named `leverage synergies` — the names differ, so that phrase reports both. It is upstream behaviour shared with the Python lane, and "fixing" it would make two lanes disagree.

A workspace `governance.bannedPatternsFile` is an *addition*. Every failure loading it — unset, missing, malformed JSON, bad regex — degrades to "no extra rules" in `workspacePatterns`, because a broken addition must never brick previewing or publishing. `loadWorkspacePatterns` is the throwing variant, for the caller that asked about the file by name and wants the reason.

`MAX_LEN` is a house-style ceiling on *commentary*, not on an article. It is why `buildPreview` never falls back to a source page's whole body for the commentary: a 5,000-character post tripping a length gate is a nonsense blocker.

## Publish targets (D8)

`PublishTarget` is an interface with two halves — `build` (pure) and `send` (effectful) — and a registry (`targetById`, `registerTarget`). The built-in target is `jekyll`: an approved draft becomes a markdown file in a registered content folder plus a ledger record. `PublishDeps.fetchImpl` exists so a remote target can be added without either half reaching for a global, and so a test can prove the preview path never calls out.

A text update has **no canonical URL on purpose**: dedupe needs a stable identity and free text has none, so updates are never ledgered. Articles are.

## Tests

`src/test/governance.test.ts` pins the guard's rule counts and message shapes, the filler dedup and the deliberate double-report, `listQueue` skipping a zero-key `README.md`, `writeDraft`'s collision chain and its always-`pending` status, `markStatus`'s one-line diff, the ledger's missing/corrupt/`_`-key behaviour, every `BlockerKind` in isolation and in order, and `publishPreview`'s skip-versus-block split. `src/test/golden.test.ts` holds the cross-lane byte contract for the ledger and for `markStatus`.
