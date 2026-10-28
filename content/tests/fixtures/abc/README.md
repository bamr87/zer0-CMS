# ABC book fixture

The golden for the ABC export tests (`content/tests/books/test_abc.py`): drsai's IT Alphabet as the Rails ABC generator wrote it, frozen from commit `d0a572fb` — `pages/_books/it-alphabet/index.md` is `git show d0a572fb:sites/drsai/pages/_books/it-alphabet/index.md` and `_data/abc_books/it-alphabet.json` is `git show d0a572fb:sites/drsai/_data/abc_books/it-alphabet.json`, byte for byte. `_config.yml` is the smallest Jekyll root that holds them (drsai's `collections_dir` and `books` collection).

Never edit the two book files to make a test pass: they are the Rails generator's output (docs/plan/rails-cms-spec.md § rails.abc-generator), and the tests hold the platform to them.
