# `lib/zer0_cms/cms/` — the stdlib content library

The read/write layer the Rails app drives. Stdlib only — no gems — so `bin/test-stdlib` runs it with no bundler on the CI Ruby (3.3) and on the app's Ruby (4.0).

| File | Role |
|---|---|
| `catalog.rb` | Walk a site exactly as Jekyll 4.4's reader does (EntryFilter, `read_directories`, PostReader, `Collection#read`, included files) and list its pages, posts, drafts and documents. Stricter than Jekyll where that matters: only markdown and HTML become entries (the rest is counted in `skipped`), every symlink is skipped, and a `source:` or `collections_dir:` resolving outside the root raises `Zer0Cms::Cms::UnsafePath`. |
| `front_matter.rb` | `parse(text, strict: false)` returns a `Document` (`data, body, raw, raw_values, fence_style, newline, bom, errors`); `strict: true` raises the Psych exception instead. `update_keys(text, changes)` is the Ruby port of the extension's line surgery: untouched lines stay byte-identical, the closing fence stays, a new key goes in before it, a key's whole span is replaced, `nil` deletes every duplicate of a key, `NULL` writes a null, scalars are quoted by YAML's rules, lists keep the file's style, CRLF and a BOM survive, and every edit is re-read before it is returned (`EditError` otherwise). |
| `writer.rb` | `create` (a declared collection, an existing section, a validated slug, O_EXCL, realpath-confined) and `duplicate` (a draft titled "(copy)" without the original's `permalink`, `redirect_from` or `preview`). |

## Proving it on real sites

- `ruby bin/jekyll-parity SITE` diffs the catalog against Jekyll's own reader and exits 1 on any difference. It needs the jekyll gem, so it is not part of `bin/test-stdlib`; `--json` prints the lists committed as `test/fixtures/*.expected.json`, which the stdlib test asserts without Jekyll.
- `ruby bin/front-matter-roundtrip SITE...` runs the `update_keys` round-trip property over every catalogued file of one or more sites, read-only: an update with the parsed values is a byte no-op, and re-emitting each key reads back unchanged without moving any other line.

Keep the front-matter contract aligned with the extension's `src/core/content/serialize.ts`: dates stay strings, comments survive, a missing key goes in before the closing fence. Where the extension hand-rolls a YAML subset, this port takes each key's line range from Psych's node marks — the parser Jekyll itself reads front matter with — so the two cannot disagree about where a value ends.
