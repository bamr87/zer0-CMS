# `src/core/shared` — primitives

Eight files with no domain knowledge and no dependencies. Everything else in the codebase imports from here; nothing here imports from anywhere else in the codebase except `types.ts`.

| File | Exports | Notes |
|---|---|---|
| `types.ts` | `Zer0Config`, `Field`, `FieldType`, `ContentType`, `ContentFolder`, `FieldGroup`, `PageEntry`, `ContentRecord`, `CmsIssue`, `PerfStats`, `LogSink`, `NOOP_LOG`, … | The vocabulary. Types only, plus the null log sink. |
| `config.ts` | `defaultConfig`, `resolveConfig`, `absPath`, `relPath`, `configPath`, `require*` | Three-layer merge and `[[workspace]]` expansion. |
| `atomic.ts` | `atomicWriteFile`, `atomicWriteText` | Temp file in the same directory, then `rename`. |
| `jsonio.ts` | `readJsonc`, `readJsonFile`, `pyJsonDump` | JSON-with-comments in, Python-identical JSON out. |
| `timestamp.ts` | `utcStamp`, `utcDate` | Second precision, no milliseconds — a byte contract. |
| `dates.ts` | `formatDate`, `parseDate`, `normalizePattern`, `timezoneOffset` | date-fns token subset via `Intl`. |
| `glob.ts` | `compileGlob`, `globMatches`, `walkGlobs`, `SKIP_DIRS` | Single-pass translation, static base, sorted output. |
| `text.ts` | `slugify`, `removePunctuation`, `removeStopWords`, `transliterate`, `encodeEmoji`, `truncate`, `escapeHtml`, `CHAR_MAP`, `STOP_WORDS`, `MINIMAL_STOP_WORDS`, `NO_STOP_WORDS`, `STOP_WORD_PRESETS` | Slug pipeline ported from Front Matter CMS. |

## Contracts worth knowing before you change anything

**`resolveConfig(root, fileJson, settings)`** — precedence per key is `settings` (VS Code) → `fileJson` (`zer0.json`) → default. Arrays and free-form objects replace wholesale; there is no item-level merging. The file layer is *coerced*, not cast: `zer0.json` is untrusted input, so a field with an unknown `type` is dropped rather than admitted as a lie about its shape. Every `requireX()` error names both the `zer0.json` key and the VS Code setting id, because "not configured" is useless when there are two places to configure it.

**`atomicWriteFile`** — the temp file is created in the *target's* directory, because `rename` is only atomic within a filesystem. On failure the temp file is removed and the original error re-thrown, so a failed write leaves no `.tmp` residue. Never use it for user-edited markdown: replacing the inode detaches open editors and file watchers.

**`pyJsonDump`** — byte-identical to Python's `json.dumps`, including `sort_keys` code-point ordering, `ensure_ascii` escaping that starts at **U+007F** (not U+0080), Python's `', '`/`': '` compact separators, and its `Infinity`/`NaN` spellings. The ledger and `.cms/distribution/` files are written by both lanes; a one-byte disagreement turns every publish into a git diff. The single unavoidable difference is that JS has one number type, so a Python `2.0` round-trips as `2`.

**`utcStamp()`** — `2026-07-31T14:05:22Z`. Second precision, no milliseconds. Machine-read fields only; anything a human reads goes through `dates.ts`.

**`readJsonc`** — comments and trailing commas are blanked with *spaces*, not deleted, so byte offsets survive and the thrown error can name a real line and column in the original text.

**`compileGlob`** — one left-to-right pass. Cascading string replaces (`**` then `*`) rewrite the fragments emitted by earlier steps, which is the classic way to get `pages/**/*.md` subtly wrong. `walkGlobs` starts at each pattern's static base, skips `SKIP_DIRS` and hidden directories below the base, and returns sorted workspace-relative POSIX paths.

**`slugify`** — Front Matter's pipeline (remove punctuation → lowercase → drop stop words → join with `-` → transliterate), plus a final collapse of repeated and edge dashes.

**Which words it drops is configuration, and the default is no longer FM's.** FM used the SMART information-retrieval stop-word list, which is built for matching documents rather than for naming them: it contains `back`, `new`, `value`, `use`, `way`, `thing`, `vs` and `without`. Run over a real 72-post site, 31% of titles lost a word that carried meaning — `"MCP for the back office"` became `mcp-office`, and `"… without losing data"` became `…-losing-data`, which is not a shorter URL but the opposite claim. So `MINIMAL_STOP_WORDS` (the closed class of English function words) is the default, and `STOP_WORDS` is one setting away — `"slug": {"stopWords": "smart"}` — for a repository whose permalinks FM already minted. `slugify` takes the set as a parameter because this module is the bottom of the stack and cannot see `Zer0Config`; `createSlug` and `publish` pass `cfg.slug.stopWords`.

## Tests

`src/test/core.test.ts` covers this directory: glob translation, slug + stop words, date format/parse round-trip across a DST boundary, `pyJsonDump` U+007F escaping and deep sorting, and `utcStamp`.
