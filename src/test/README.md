# `src/test/` — the test suite

Six files, three execution contexts, one command: `npm test`. The runner is `@vscode/test-cli` driving Mocha's **tdd** interface (`suite` / `test`) over the plain `tsc` output in `out/test/`, configured by `.vscode-test.mjs` at the repository root. `npm run pretest` compiles that output, builds the five esbuild bundles and runs eslint first, so a green `npm test` means the tests, the types, the lint gate and the shipped artifacts all agree.

| File | Runs in | Covers |
|---|---|---|
| `core.test.ts` | plain Node | The three configuration layers, `pyJsonDump` parity, the YAML/TOML/JSON front-matter parsers, line surgery, the shared primitives, the page-index cache and the SEO metrics. |
| `fields.test.ts` | plain Node | All 18 field types, the ten `when` operators, field-group inlining, required-field validation, SEO limit derivation, `processFields`, placeholders and slugs. |
| `governance.test.ts` | plain Node | The brand guard, the draft queue, the ledger, every publish gate in isolation and in order, the `.cms/` contract, and the read-only preview. |
| `golden.test.ts` | plain Node | Cross-lane byte contracts against fixtures written by Python. |
| `mcp.test.ts` | child process | Spawns the bundled `dist/mcp-server.js` over stdio with a scrubbed environment. |
| `extension.test.ts` | extension host | Activation, the contributed commands, the context keys, and the fixture workspace's live settings. |

## The two rules every test here obeys

**Zero network.** Nothing in the suite resolves a hostname. The `buildPreview` test proves it positively rather than by convention: it installs a `fetch` that throws, runs the preview, and asserts the counter it increments is still zero.

**Zero writes outside `os.tmpdir()` and the fixture workspace.** Tests that write create a fresh `fs.mkdtempSync` directory and remove it in a `finally`. The fixture workspace itself is read-only from the suite's side — `governance.test.ts` snapshots every file under `src/test/fixtures/workspace/` before and after `buildPreview` and asserts the two trees are byte-identical, so a regression that started writing during a preview would fail here rather than in somebody's repository.

## `fixtures/workspace/` — a small, realistic site

`.vscode-test.mjs` opens this directory as the workspace folder, so it is both the input to the pure-Node tests and the live workspace the extension-host tests activate against.

`zer0.json` declares two content folders (`pages/_posts/corp`, `pages/_posts/tech`) and two content types. The `post` type exercises **every one of the 18 field types** — `fields.test.ts` asserts that, so adding a type without adding a fixture field fails the suite rather than going untested. `.vscode/settings.json` sets `zer0Cms.governance.publishAllow` to `false` while `zer0.json` sets it to `true`: the layers disagree on purpose, and the merge that collapsed them would fail loudly.

Seven markdown files cover the shapes the parser has to survive: YAML front matter, TOML (`+++`), Hugo-style JSON (a bare object), a file dense with comments and blank lines that pins the byte-preservation property of line surgery, a draft, and a `README.md` with no front matter at all that must be skipped and remembered rather than re-read.

`.zer0/drafts/` is the queue: a `README.md` with no front matter that `listQueue` must skip, a `pending` draft whose source is already in the ledger (so a publish is skipped rather than duplicated), and an `approved` one that is not. `.zer0/ledger.json` carries a `_meta` block, one real share, and one half-written entry with no `urn` — the two rows `shareEntries` has to filter. `.cms/index/` holds a six-record content index and its summary, spanning fresh/aging/stale, health 40/82/88/90/93/95, one draft and one structural page.

## `fixtures/golden/` — generated, never hand-edited

Every file here was written by **Python**, and the TypeScript core has to reproduce those bytes exactly. That is what makes them prove lane compatibility rather than self-consistency.

`ledger.json` is `json.dumps(indent=2, sort_keys=True, ensure_ascii=True)` plus a trailing newline; its `café-métier` URL pins the escaping and the code-point key ordering in one object. `worklist.md` and `worklist-inputs.json` come from the real `catering.build` / `catering.render` and are inherited verbatim from BASH-CMS — eleven records and seven performance rows chosen to hit every lane boundary: health exactly 70, health `-1`, a draft, a structural page and a stale page with engagements.

Regenerate with `generate.py`, from that directory:

```bash
python3 generate.py                          # ledger.json (stdlib only)
python3 generate.py /path/to/bashconsultants  # + the worklist pair, from the real lane
```

When a golden test fails, the fix is either a real bug in our serializer or a re-run of `generate.py` against a changed Python lane. Decide which. **Never edit a golden to match a change made here** — the moment you do, the file stops proving anything.

## Running a subset

`npm test` runs everything. During development the four pure-Node files also run under plain Mocha, which is much faster and needs no VS Code download:

```bash
npx tsc -p . --outDir out
npx mocha --ui tdd out/test/{core,fields,governance,golden}.test.js
```

`extension.test.ts` needs the extension host and `mcp.test.ts` needs `dist/mcp-server.js`, so neither is in that list. On a headless Linux box `npm test` shells out to `xvfb-run` for you (see `test-runner.js`); set `ZER0_CMS_NO_XVFB=1` to force the plain path.
