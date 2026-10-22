"""The small sites the doctor's tests build (tests/sites/test_doctor.py): the
Rails catalog's `test_doctor.rb` scenarios, one per rule, as {path: text}.

`tests/fixtures/doctor/ruby-recording.json` holds what the Ruby doctor
(`rails/bin/zer0-cms doctor --format findings`, Ruby 3.3) reported for each,
recorded before it was deleted, with a digest of the files it was run on, so
the test knows it builds the very sites that were recorded. The theme's own
`remote_theme` is not named here (no Python may name the theme): the aligned
site points at another theme, which only the dropped theme rule cared about.
"""

import hashlib
import json

ALIGNED = {
    "_config.yml": "remote_theme: example/theme@v1\ncollections_dir: pages\npreview_images:\n  provider: local\n",
    ".theme-overrides.yml": "overrides: []\n",
    "Gemfile": 'source "https://rubygems.org"\ngem "zer0-image-generator", "~> 0.6", group: :jekyll_plugins\n',
    "zer0.json": (
        '{\n  // console dialect\n  "$schema": "https://example.com/zer0.schema.json",\n  "contentFolders": [\n'
        '    { "path": "[[workspace]]/pages/_posts", },\n    { "path": "[[workspace]]/pages/{{year}}/x" },\n  ],\n}\n'
    ),
    "fleet.manifest.yml": "name: fixture\nlanes: []\n",
    "pages/_posts/2026-01-01-hello.md": (
        "---\ntitle: Hello\ndate: 2026-01-01\nlastmod: 2026-01-02\ndescription: d\nlayout: article\n"
        "categories: [a]\ntags: [b]\nauthor: rhea\n---\nBody\n"
    ),
}


def aligned(**changes):
    """The aligned site with files replaced (a value) or removed (None)."""
    files = {**ALIGNED, **changes}
    return {path: text for path, text in files.items() if text is not None}


def _distribution(block: str, **more):
    zer0 = ALIGNED["zer0.json"].replace('"$schema"', f'"distribution": {{ "linkedin": {block} }},\n  "$schema"')
    return aligned(**{"zer0.json": zer0}, **more)


VALID_LINKEDIN = '{ "author": "urn:li:organization:1", "siteUrl": "https://example.test", "ledger": "log.json" }'

SCENARIOS = {
    "aligned": aligned(),
    "distribution-valid": _distribution(VALID_LINKEDIN),
    "distribution-invalid": _distribution('{ "author": "urn:li:company:1", "publishAllow": true }'),
    "distribution-ledger": _distribution(VALID_LINKEDIN, **{"log.json": "{ not json"}),
    "distribution-outside": _distribution('{ "author": "urn:li:person:x", "queue": "../outside" }'),
    "distribution-vendored": aligned(**{"scripts/features/linkedin/posts.py": "# publisher\n"}),
    "theme-other": aligned(
        **{"_config.yml": "remote_theme: someone/else\npreview_images: {}\n", ".theme-overrides.yml": None}
    ),
    "theme-gem": aligned(**{"_config.yml": "theme: some-theme-gem\npreview_images: {}\n"}),
    "config-broken": aligned(**{"_config.yml": "title: [broken\n"}),
    "config-missing": aligned(**{"_config.yml": None}),
    "image-engine": aligned(
        **{
            "_config.yml": "remote_theme: example/theme\n",
            "Gemfile": 'gem "github-pages"\n',
            "_plugins/preview_image_generator.rb": "config = site.config['preview_images']\n",
            "_plugins/preview_generator.rb": "config = site.config['preview_images']\n",
            "scripts/lib/preview_generator.py": "cfg = config.get('preview_images', {})\n",
        }
    ),
    "image-engine-namesake": aligned(
        **{"_plugins/preview_generator.rb": "config = site.config['preview_generator'] || {}\n"}
    ),
    "cms-missing": aligned(**{"zer0.json": None}),
    "cms-folder-missing": aligned(**{"zer0.json": '{ "contentFolders": [ { "path": "[[workspace]]/pages/_nope" } ] }'}),
    "cms-jsonc": aligned(**{"zer0.json": '{ "$schema": "x", // ok\n "a": "//not a comment" /* block */, }'}),
    "cms-invalid": aligned(**{"zer0.json": '{ "$schema": "x" "missing comma": 1 }'}),
    "fleet-wrapped": aligned(**{"fleet.manifest.yml": "name: a\n  wrapped: at column 80 went wrong\nx: [\n"}),
    "fleet-duplicate": aligned(**{"fleet.manifest.yml": "name: a\nname: b\n"}),
    "fleet-list": aligned(**{"fleet.manifest.yml": "- a list\n"}),
    "fleet-alias": aligned(**{"fleet.manifest.yml": "base: &b {x: 1}\nother: *b\n"}),
    "fleet-missing": aligned(**{"fleet.manifest.yml": None}),
    "content": aligned(
        **{
            "pages/_posts/2026-01-02-thin.md": "---\ntitle: Thin\nlastmod: ''\n---\nBody\n",
            "pages/_posts/2026-01-03-broken.md": "---\ntitle: [x\n---\nBody\n",
        }
    ),
}


def digest(files: dict) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def build(root, files: dict) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
