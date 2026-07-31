# `src/core/content` — the content model

Ten files that know what a content file *is*: how to read its front matter, how
to write it back without disturbing anything the user did not change, what a
field means, where a page lives, and what its SEO metrics are. Pure Node — see
`../README.md` for the layering rule.

| File | Exports | Owner |
|---|---|---|
| `frontmatter.ts` | `FmValue`, `FrontMatter`, `FmFormat`, `FmBlock`, `detectFormat`, `splitFrontMatter`, `parseFrontMatterBlock`, `parseYamlSubset`, `parseTomlFlat`, `parseYamlKeyLine`, `isYamlSequenceItem`, `asString`, `asList`, `asBool` | WP03 |
| `serialize.ts` | `SerializeOptions`, `DEFAULT_SERIALIZE_OPTIONS`, `serializeOptions`, `KeyChange`, `applyChanges`, `applyCommaSeparatedFields`, `updateFrontMatterKeys`, `serializeFrontMatter`, `stitch` | WP03 |
| `article.ts` | `Article`, `parseArticle`, `readArticle`, `writeArticle`, `setFieldValue`, `stampModified`, `isSupported`, `CONVENTIONAL_MODIFIED_KEYS` | WP03 |
| `fields.ts` | `inlineFieldCollections`, `evaluateWhen`, `visibleFields`, `emptyValueFor`, `isEmpty`, `validateFields`, `FieldViolation`, `labelOf`, `limitFor`, `findField` | WP04 |
| `contentType.ts` | `DEFAULT_CONTENT_TYPE`, `DEFAULT_CONTENT_TYPE_NAME`, `CONTENT_TYPE_FIELD`, `getContentTypes`, `contentTypeByName`, `resolveContentType`, `processFields`, `createContent`, `renderContentFile`, `sanitizeFileName`, `generateContentTypeFrom`, `missingFields` | WP04 |
| `folders.ts` | `resolveFolders`, `folderForFile`, `filePrefixFor` | WP04 |
| `placeholders.ts` | `processPlaceholders`, `hasPlaceholder`, `PlaceholderContext`, `FAULTY_PLACEHOLDER`, and the synchronous token processors (`processTimePlaceholders`, `processDatePlaceholders`, `processFmPlaceholders`, `processArticlePlaceholders`, `processPathPlaceholders`, `processFilePrefixIndex`, `processCustomPlaceholders`) | WP04 |
| `slug.ts` | `createSlug`, `decorateSlug`, `alignedFilePath` | WP04 |
| `pageIndex.ts` | `IndexCache`, `buildIndex`, `pageToRecord`, `searchPages`, `emptyIndexCache`, `asIndexCache` | WP05 |
| `seo.ts` | `ArticleDetails`, `getArticleDetails`, `emptyArticleDetails`, `stripShortcodes`, `SeoRow`, `seoInsights`, `KeywordCheck`, `KeywordInfo`, `keywordAnalysis`, `keywordDensity`, `keywordsOf`, `isHealthyDensity`, `KEYWORD_CHECK_NAMES`, `KEYWORD_CHECK_TOTAL`, `DENSITY_MIN`, `DENSITY_MAX`, `WORDS_PER_MINUTE` | WP05 |

## The front-matter engine, in one paragraph

`splitFrontMatter` decides *by the file's leading characters* — `---`, `+++`,
`{` — which dialect a block is written in, and returns an `FmBlock` (raw text,
character offsets, parsed data) plus the body. `updateFrontMatterKeys` edits a
block by **line surgery**: it finds the line range each changed key occupies and
rewrites only those lines. `serializeFrontMatter` is the full-emit fallback for
the cases surgery declines. `stitch` puts the fences back. `article.ts` is the
only module that writes user markdown.

## Contracts worth knowing before you change anything

**Dates stay strings.** Nothing in `frontmatter.ts` or `serialize.ts`
constructs a `Date`. Round-tripping `2026-07-31` through a JS `Date` is how a
CMS quietly rewrites every date in a repository to a timezone-shifted
timestamp, and it is the single most common way a front-matter library corrupts
a site. `stampModified` formats a `Date` *into* a string and never reads one
back out.

**The dialect belongs to the file, not to the setting.**
`zer0Cms.frontMatter.format` decides what *new* blocks look like. An existing
TOML file stays TOML. `serializeOptions(cfg, format)` takes the detected format
explicitly for exactly this reason; passing only `cfg` means "I am creating this
block".

**Line surgery is the default write path (decision D7).**
`updateFrontMatterKeys` rewrites only the lines of the keys named in its
`KeyChange[]`. Comments, blank lines, key order, quoting style and indentation
quirks of every *other* key survive because they are never re-emitted. Flipping
`status: pending` to `status: approved` is a one-line diff, always — the
property BASH-CMS's `markStatus` had for one key, generalised to every field
edit. A key's range stops before the blank lines and comments that separate it
from the next key, which is what makes "untouched lines are byte-identical"
literally true.

**`null` is the fallback signal, not an error.** `updateFrontMatterKeys`
returns `null` when it cannot place a change — an unlocatable nested path, a
parent that holds a scalar, or a TOML/JSON block. The caller
(`writeArticle`) then re-serialises the merged data with
`serializeFrontMatter`, which is correct but loses comments. Never "guess" a
location; appending a duplicate key is a worse failure than a formatting
change.

**A malformed file has no front matter.** Every parser here is written not to
throw, and `parseFrontMatterBlock` catches anything that slips through and
returns `{}`. The panel re-parses on every keystroke of a file somebody is
mid-edit, so "unreadable" has to be a value, not an exception. Nothing is
written as a result: a construct we cannot read is a construct we cannot
corrupt.

**Nested changes are dotted keys.** `setFieldValue(data, ['seo','title'], v)`
yields `{ key: 'seo.title', value: v }`, which the surgery resolves to the exact
leaf line. A key that literally contains a dot (`image.alt`) wins over the path
reading, decided against the block's own top-level keys. Path segments address
mappings only — there is no index syntax for reaching into a sequence, and a
segment that itself contains a dot falls back to rewriting the whole top-level
container.

## The YAML subset

The zero-dependency rule (D3) buys a hand-rolled parser instead of js-yaml. The
full list of what is and is not supported — and, for each unsupported
construct, what happens instead — is the header comment of `frontmatter.ts`.
Read it before filing a bug against the parser. The short version:

- **Supported:** scalars with coercion, nested mappings, block sequences
  (indented or not, including sequences of mappings), one-line flow collections
  with quoted commas, block scalars with every chomping and indentation
  indicator, comments, CRLF, BOM, common quote escapes.
- **Not supported:** anchors/aliases/merge keys, tags, multi-document,
  multi-line flow collections, multi-line plain scalars, complex keys. Each one
  degrades to a documented result (usually "the literal text" or "the line is
  skipped") and never throws.
- **Coercion:** `true`/`false` → boolean, `null`/`~`/empty → `null`, integers
  and decimals → number. `yes`/`no`/`on`/`off`, zero-padded integers, integers
  past `Number.MAX_SAFE_INTEGER` and anything date-shaped all stay strings.

On the way back out, `serializeFrontMatter` quotes a string when a *reader*
would coerce it — including the YAML 1.1 words Jekyll's Ruby parser treats as
booleans, which our own parser does not. Keys are quoted only when they would
not parse back as themselves.

## `commaSeparatedFields` has two halves

Write side: `serializeFrontMatter` joins a listed key's array with `', '` onto
one line. Read side: `applyCommaSeparatedFields(data, keys)` splits it back.
The parser does **not** do the split — it has no configuration and never will;
this is a field-level concern applied by whoever built the `Zer0Config`.

## The content model, in five more paragraphs

**Creation computes; it does not write.** `createContent` resolves the content
type, the filename prefix, the path and the starting front matter, refuses a
path that already exists, and returns a `CreateContentResult`.
`renderContentFile(result, cfg)` turns that into the exact bytes; the `mkdir`
and the `writeFile` belong to the caller. That keeps `article.ts`'s "only
writer of user markdown" property intact and lets the MCP server and the tests
exercise creation without producing files.

**A content type is resolved in five steps**, in order: the file's own `type`
key → a content folder that binds exactly one type → the sole registered type →
the type named `default` → the synthesized `DEFAULT_CONTENT_TYPE`. Step 1 is
`type`, not FM's branded `fmContentType`. A folder that lists *two* content
types binds nothing: guessing between them would apply the wrong schema
silently.

**Placeholders run in one documented order** — article (`{{title}}`,
`{{slug}}`) → front matter (`{{fm.x}}`) → path (`{{pathToken.n}}`) → file index
(`{{filePrefix.index}}`) → custom (`{{id}}`) → time (`{{now}}`, `{{year}}`, …)
→ `{{date|pattern}}`. FM used two different orders for field defaults and file
prefixes and documented neither. A token whose source is missing is **left in
the text**: a visible `{{fm.author}}` in a filename is a bug somebody fixes, an
empty string is one nobody notices. A custom placeholder whose script fails
yields `FAULTY_PLACEHOLDER` (`<failed to process>`), which `isEmpty` reads as
empty — scripts run through `execFile` with an argv array and no shell.

**`folderForFile` matches on path boundaries, longest prefix first.** FM asked
`filePath.includes(folder.path)`, which lets `/site/pages` claim
`/tmp/copy-of/site/pages/x.md`. A folder registered with a wildcard is matched
against its pattern, so the answer does not depend on `resolveFolders` having
run first.

**The `when` clause hides, it never invents.** All 10 operators are
implemented; the four FM declares but never implements are absent from
`WhenOperator` entirely. A comparison whose operands are not comparable
(`startsWith` against a number) returns "visible" rather than guessing, and a
field whose parent is hidden is hidden too. `caseSensitive` defaults to `true`.

## The index and the metrics

**A file with no front matter is not a page.** `buildIndex` walks the registered
folders (honouring `excludeSubdir` and `excludePaths`, deepest folder winning
when two overlap), and skips anything whose front-matter block does not parse.
Nothing it meets can throw: an unreadable file, a missing folder and a malformed
block are all just absent from the result, with a line in the `LogSink`.

**The cache is keyed by mtime and invalidated by configuration.** A refresh over
an unchanged tree re-reads nothing and returns the *same `PageEntry` objects*,
by identity — that is both the fast path and how the tests prove zero re-parses.
`IndexCache.skipped` remembers the files that had no front matter, without which
every refresh would re-read every `README.md` in the repository forever, and
`IndexCache.fingerprint` covers the other staleness: a settings change that
alters the projection (a different title field, a different draft field) while
every mtime stays put. The cache is rebuilt, never mutated, so a deleted file
cannot linger in it. The shell owns where it is stored
(`zer0Cms:Pages:Cache` in `workspaceState`); `asIndexCache` is the guard for
what comes back out.

**`pageToRecord` says "unknown" out loud.** It is decision D9: `.cms/` absence
is a normal state, so a `PageEntry` is projected into the same `ContentRecord`
the contract uses, with `health: -1` and `freshness: 'unknown'`. Under those two
values `isDistributable` degrades to *not a draft and has a title* — the
strongest claim a front-matter scan can support. A `choice` draft field whose
value is neither a draft word nor a published word yields `draft: null` rather
than a guess, because guessing is how a governed queue publishes something it
should not have.

**Article metrics are a line scan, not a syntax tree.** `getArticleDetails`
strips `{{…}}` shortcodes with FM's own regex, then walks the body once:
fenced code is skipped whole, inline code and image alt text are dropped
(mdast calls them `inlineCode` and a node property, so FM never counted them
either), link text is kept, and each list item is its own paragraph. `wordCount`
keeps FM's `split(' ')` over-count bug-for-bug — the 1,760-word target was tuned
against it, and "fixing" it would move the goal for every article in a
repository at once. Links split internal/external on the `http` prefix plus the
site's own base URL.

**SEO thresholds are FM's, including the two rules people trip over.** A
threshold of `<= 0` switches its row off entirely (that is how a workspace
disables a check), and *article length is never validated* — it carries no
`isValid`, so it renders as an em dash. `keywordAnalysis` is exactly six checks;
heading matching is a substring test for a multi-word keyword and an exact-word
test for a single word; density uses FM's regex, with the keyword escaped so a
`(` in a keyword no longer throws out of the panel's render, and is `null`
rather than `NaN` when there is nothing to divide by.

## Tests

`src/test/core.test.ts` covers the parser (nested maps, block scalars, flow
collections, coercion, every documented non-goal), `updateFrontMatterKeys`
(comment preservation counted line by line, key add/delete, the `null` fallback
signal), `serializeFrontMatter` in both directions of each option, and the
`readArticle` → `writeArticle` byte-identical no-op on all three dialects.
