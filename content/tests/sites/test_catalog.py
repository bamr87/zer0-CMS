"""The Jekyll catalog (sites/catalog.py, PLAN G4) against Jekyll 4.4.1's own
reader, and the Rails catalog's hardening tests ported test for test.

`tests/fixtures/jekyll-site*.expected.json` were written by `rails/bin/jekyll-parity
<fixture> --json` running Jekyll 4.4.1's reader — Jekyll's answer, not a
hand-written expectation. The parity test renders this walk in the same JSON
and compares the bytes."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sites import catalog

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
COUNTED = ("non_content_pages", "non_content_posts", "non_content_documents")


def jekyll_parity_json(name: str) -> str:
    """This walk's lists in jekyll-parity's `--json` shape (Ruby's pretty JSON)."""
    expected = json.loads((FIXTURES / f"{name}.expected.json").read_text())
    result = catalog.scan(FIXTURES / name)
    lists = {
        "generator": expected["generator"],
        "entries": sorted([e.collection, e.source_relative] for e in result.entries),
        "skipped": {k: result.skipped[k] for k in COUNTED},
        "notes": [],
    }
    return json.dumps(lists, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("name", ["jekyll-site", "jekyll-site-src"])
def test_the_fixture_sites_match_jekylls_reader_byte_for_byte(name):
    assert jekyll_parity_json(name) == (FIXTURES / f"{name}.expected.json").read_text()


def test_fixture_details():
    result = catalog.scan(FIXTURES / "jekyll-site", now=datetime(2026, 9, 14, tzinfo=UTC))
    by_path = {e.source_relative: e for e in result.entries}
    assert by_path["pages/_drafts/wip.md"].kind == "draft"
    assert by_path["pages/_posts/2099-01-01-future.md"].future
    assert not by_path["pages/_docs/hidden.md"].published
    assert by_path["guides/template.md"].date is None, "a {{date}} placeholder is not a date"
    assert by_path["guides/template.md"].error is None
    assert by_path["pages/_posts/2026-01-01-hello.md"].title == "Hello"
    assert by_path["pages/_posts/2026-02-02-no-front-matter.md"].title == "No Front Matter"
    assert not by_path["pages/_posts/2026-02-02-no-front-matter.md"].front_matter
    assert result.skipped["undated_posts"] == 1
    assert result.collections == ["posts", "docs", "notes"]


# ── hardening ──────────────────────────────────────────────────────────────


@pytest.fixture
def site(tmp_path):
    def make(config: str) -> Path:
        root = tmp_path / "site"
        root.mkdir(exist_ok=True)
        (root / "_config.yml").write_text(config)
        return root

    return make


def write(root: Path, rel: str, text: str | bytes = "---\ntitle: T\n---\nBody\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode())
    return path


def test_scan_reads_post_front_matter(site):
    root = site("title: t\ncollections_dir: pages\n")
    write(
        root,
        "pages/_posts/2026-01-01-hello.md",
        "---\ntitle: Hello\nauthor: rhea\ncategories: [Hacks]\ntags: [ci]\ndraft: false\n---\nBody\n",
    )
    entry = catalog.scan(root).entries[0]
    assert (entry.title, entry.author, entry.categories, entry.tags, entry.draft) == (
        "Hello",
        "rhea",
        ["Hacks"],
        ["ci"],
        False,
    )


def test_front_matter_errors_are_recorded_not_raised(site):
    root = site("title: t\n")
    write(root, "broken.md", "---\ntitle: [x\n---\nBody\n")
    entry = catalog.scan(root).entries[0]
    assert entry.error.startswith("front matter: ") and entry.data == {} and entry.error_line == 2


@pytest.mark.parametrize("config", ["source: ..\n", "source: /etc\n", "source: sub/../../elsewhere\n"])
def test_refuses_a_source_outside_the_root(site, config):
    with pytest.raises(catalog.UnsafePath):
        catalog.scan(site(config))


@pytest.mark.parametrize("config", ["collections_dir: ../x\n", "collections_dir: /tmp\n"])
def test_refuses_a_collections_dir_outside_the_root(site, config):
    with pytest.raises(catalog.UnsafePath):
        catalog.scan(site(config))


def test_refuses_a_source_symlinked_outside_the_root(site, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = site("source: src\n")
    os.symlink(outside, root / "src")
    with pytest.raises(catalog.UnsafePath):
        catalog.scan(root)


def test_symlinked_entries_are_skipped_and_counted(site, tmp_path):
    outside = tmp_path / "outside"
    secret = write(outside, "secret.md", "---\ntitle: Secret\n---\n")
    root = site("collections_dir: pages\ncollections:\n  docs: {}\n")
    write(root, "pages/_docs/real.md")
    os.symlink(secret, root / "pages/_docs/linked.md")
    os.symlink(secret, root / "linked-page.md")
    (root / "pages/_posts").mkdir(parents=True)
    os.symlink(secret, root / "pages/_posts/2026-01-01-linked.md")
    os.symlink(outside, root / "linked-dir")
    result = catalog.scan(root)
    assert [e.source_relative for e in result.entries] == ["pages/_docs/real.md"]
    assert result.skipped["symlinks"] == 4


def test_legacy_list_form_collections(site):
    root = site('collections: [recipes, "bad/../name"]\n')
    write(root, "_recipes/soup.md")
    result = catalog.scan(root)
    # Jekyll's label sanitising drops the slashes and keeps the dots.
    assert result.collections == ["posts", "recipes", "bad..name"]
    assert [(e.collection, e.source_relative) for e in result.entries] == [("recipes", "_recipes/soup.md")]


def test_a_configured_include_replaces_the_htaccess_default(site, tmp_path):
    root = site("include: [_kept.md]\n")
    write(root, ".htaccess.md")
    write(root, "_kept.md")
    assert [e.source_relative for e in catalog.scan(root).entries] == ["_kept.md"]
    (root / "_config.yml").write_text("title: t\n")
    assert catalog.site_for(root).includes == [".htaccess"]


def test_invalid_utf8_posts_are_skipped_like_jekyll(site):
    root = site("title: t\n")
    write(root, "_posts/2026-01-01-bad.md", b"---\ntitle: T\n---\n\xff\n")
    write(root, "bad-page.md", b"---\ntitle: T\n---\n\xff\n")
    result = catalog.scan(root)
    assert [e.source_relative for e in result.entries] == ["bad-page.md"]
    assert result.skipped["invalid_utf8_posts"] == 1
    assert result.entries[0].error == "not valid UTF-8"


def test_an_impossible_date_is_a_front_matter_error_not_a_crash(site):
    root = site("title: t\n")
    write(root, "odd.md", "---\ndate: 2026-13-45\n---\n")
    assert catalog.scan(root).entries[0].error.startswith("front matter: ")


def test_media_ignores_an_output_dir_outside_the_root(site, tmp_path):
    outside = tmp_path / "outside"
    write(outside, "leak.png", "x")
    root = site(f"preview_images:\n  output_dir: {outside}\n")
    ok = write(root, "assets/images/ok.png", "x")
    assert catalog.media(root) == [Path(os.path.realpath(ok))]
