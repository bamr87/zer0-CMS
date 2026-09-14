# `lib/zer0_cms/cms/` — fleet CMS primitives

Stdlib-only read/write layer the Rails app drives. No gems. CI: `ruby -Ilib test/zer0_cms/test_*.rb` via `bin/test-stdlib`.

| File | Role |
|---|---|
| `front_matter.rb` | Parse YAML fences; `update_keys` rewrites only changed lines |
| `catalog.rb` | Walk a Jekyll root (`collections_dir` / `source` / `_<collection>/`) |
| `writer.rb` | Create a dated post or slug page; duplicate a file |

The VS Code extension has its own TypeScript line surgery. Keep the two contracts aligned: dates stay strings, comments survive, a missing key is appended before the closing fence.
