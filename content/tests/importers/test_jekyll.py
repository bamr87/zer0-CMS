"""Jekyll → Wagtail → Jekyll (M6, M7, PLAN §4.7): what each file becomes,
that a re-run changes nothing, that an editor's change is never overwritten,
that an unchanged site exports byte for byte, that an edited page exports its
edits over its original front matter, and that the real sites in this
repository survive the round trip."""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from wagtail.models import Page, Revision

from cms.models import ArticlePage, BookPage, ChapterPage, CollectionPage, SiteRootPage, StandardPage
from exporters.jekyll import export_site
from graph.models import Edge
from importers.jekyll import import_site
from importers.models import ImportedSource
from outbox.models import OutboxEvent

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "jekyll" / "site"
# A site whose `source:` is a subdirectory, as zer0-pages's is: preview images and publish states.
SOURCE_SITE = FIXTURE.parent / "source-site"
POSTS = "src/_posts"
REPO = Path(settings.REPO_ROOT)


@pytest.fixture
def imported(db):
    report = import_site(FIXTURE, "fixture")
    assert not report.errors and not report.conflicts, report.errors + report.conflicts
    return report


def page_at(rel, site="fixture"):
    return ImportedSource.objects.get(site_key=site, legacy_path=rel).page.specific


@pytest.mark.django_db
def test_each_file_becomes_the_right_page(imported):
    assert sorted(imported.created) == sorted(
        [
            "about.md",
            "index.md",
            "pages/_posts/2026-07-31-hello.md",
            "pages/_posts/2026-08-01-unfinished.md",
            "pages/_docs/setup.md",
            "pages/_books/abc/index.md",
            "pages/_books/story/index.md",
            "pages/_books/story/01-one.md",
        ]
    )
    root = SiteRootPage.objects.get(site_key="fixture")
    assert root.title == "Fixture Site" and root.jekyll_config["collections_dir"] == "pages"
    hello = page_at("pages/_posts/2026-07-31-hello.md")
    assert isinstance(hello, ArticlePage) and hello.get_parent().specific.collection == "posts"
    assert hello.title == "Hello, backups" and hello.search_description == "Why we copy the site every night."
    from datetime import datetime

    assert hello.date == datetime.fromisoformat("2026-07-31T10:00:00-05:00") and hello.author == "amr"
    assert sorted(t.name for t in hello.tags.all()) == ["backups", "ops"]
    assert [c.slug for c in hello.categories.all()] == ["guides"]
    assert hello.front_matter["date"] == "2026-07-31 10:00:00 -0500"  # a string, as written
    assert hello.preview_image is not None and hello.preview_image.width == 8
    assert [b.block_type for b in hello.body] == ["markdown", "heading", "markdown", "code", "markdown"]
    assert "{% include callout.html" in hello.body[0].value
    assert isinstance(page_at("about.md"), StandardPage) and page_at("about.md").get_parent().pk == root.pk
    assert not page_at("pages/_posts/2026-08-01-unfinished.md").live
    book = page_at("pages/_books/abc/index.md")
    assert isinstance(book, BookPage) and book.profile == "abc" and book.series == "abc-language"
    assert [b.value["word"] for b in book.body if b.block_type == "letter"] == ["Automation", "Backup"]
    chapter = page_at("pages/_books/story/01-one.md")
    assert isinstance(chapter, ChapterPage) and chapter.number == 1
    assert chapter.get_parent().pk == page_at("pages/_books/story/index.md").pk
    assert not ImportedSource.objects.filter(legacy_path__in=["README.md", "pages/_docs/raw.md"]).exists()


@pytest.mark.django_db
def test_internal_links_are_indexed_once_every_page_exists(imported):
    hello, setup = page_at("pages/_posts/2026-07-31-hello.md"), page_at("pages/_docs/setup.md")
    index = page_at("index.md")
    assert Edge.objects.filter(src_id=hello.pk, rel="links_to", dst_id=setup.pk).exists()  # permalink and wikilink
    assert Edge.objects.filter(src_id=index.pk, rel="links_to", dst_id=setup.pk).exists()  # index came first


@pytest.mark.django_db
def test_a_second_import_changes_nothing(imported):
    revisions, events = Revision.objects.count(), OutboxEvent.objects.count()
    again = import_site(FIXTURE, "fixture")
    assert again.created == [] and again.updated == [] and len(again.unchanged) == len(imported.created)
    assert (Revision.objects.count(), OutboxEvent.objects.count()) == (revisions, events)


@pytest.mark.django_db
def test_a_changed_file_updates_its_page_but_never_an_editors_change(imported, tmp_path):
    import shutil

    site = tmp_path / "site"
    shutil.copytree(FIXTURE, site)
    import_site(site, "copy")
    about = site / "about.md"
    about.write_text(about.read_text().replace("Who writes this site.", "Who writes here."))
    report = import_site(site, "copy")
    assert report.updated == ["about.md"]
    page = ImportedSource.objects.get(site_key="copy", legacy_path="about.md").page.specific
    assert page.search_description == "Who writes here."
    page.title = "About us (edited in Wagtail)"
    page.save_revision().publish()
    about.write_text(about.read_text().replace("Who writes here.", "Who writes, again."))
    blocked = import_site(site, "copy")
    assert blocked.updated == [] and "changed in Wagtail" in blocked.conflicts[0]
    assert import_site(site, "copy", force=True).updated == ["about.md"]


@pytest.mark.django_db
def test_an_unchanged_site_exports_byte_for_byte(imported, tmp_path):
    report = export_site("fixture", tmp_path)
    assert report.rendered == [] and "pages/_posts/2026-08-01-unfinished.md" not in report.verbatim
    for rel in report.verbatim:
        assert (tmp_path / rel).read_bytes() == (FIXTURE / rel).read_bytes(), rel
    drafts = export_site("fixture", tmp_path / "with-drafts", include_drafts=True)
    assert "pages/_posts/2026-08-01-unfinished.md" in drafts.verbatim


@pytest.mark.django_db
def test_an_edited_page_exports_its_edits_over_its_front_matter(imported, tmp_path):
    hello = page_at("pages/_posts/2026-07-31-hello.md")
    hello.title = "Hello again, backups"
    hello.tags.add("restore")
    hello.body = [*hello.body.get_prep_value(), {"type": "markdown", "value": "A new closing line."}]
    hello.save_revision().publish()
    book = page_at("pages/_books/abc/index.md")
    raw = book.body.get_prep_value()
    for block in raw:
        if block["type"] == "letter" and block["value"]["letter"] == "B":
            block["value"]["word"] = "Bandwidth"
            block["value"]["tagline"] = "B is for Bandwidth!"
    book.body = raw
    book.save_revision().publish()
    report = export_site("fixture", tmp_path)
    assert sorted(report.rendered) == ["pages/_books/abc/index.md", "pages/_posts/2026-07-31-hello.md"]
    text = (tmp_path / "pages/_posts/2026-07-31-hello.md").read_text()
    # Only the changed keys are rewritten, by line surgery: the title keeps its
    # quotes, the tags their flow style, and every other line is the file's own.
    original = (FIXTURE / "pages/_posts/2026-07-31-hello.md").read_text()
    assert text.startswith(
        original.split("\n---\n")[0]
        .replace('title: "Hello, backups"', 'title: "Hello again, backups"')
        .replace("tags: [backups, ops]", "tags: [backups, ops, restore]")
        + "\n---\n"
    )
    assert '{% include callout.html text="Nightly" %}' in text and text.rstrip().endswith("A new closing line.")
    abc = (tmp_path / "pages/_books/abc/index.md").read_text()
    assert (
        "word: Bandwidth" in abc
        and "prompt: a robot arm stacking blocks" in abc
        and "image: /assets/images/a.png" in abc
    )
    # …and the rendered file imports back to the same content.
    import shutil

    copy = tmp_path / "copy"
    shutil.copytree(FIXTURE, copy)
    shutil.copy(tmp_path / "pages/_posts/2026-07-31-hello.md", copy / "pages/_posts/2026-07-31-hello.md")
    import_site(copy, "reimported")
    again = ImportedSource.objects.get(
        site_key="reimported", legacy_path="pages/_posts/2026-07-31-hello.md"
    ).page.specific
    assert again.title == "Hello again, backups" and again.body[-1].value.endswith("A new closing line.")


@pytest.mark.django_db
def test_a_page_made_in_wagtail_gets_a_jekyll_path(imported, tmp_path):
    from datetime import UTC, datetime

    posts = CollectionPage.objects.get(
        collection="posts", path__startswith=SiteRootPage.objects.get(site_key="fixture").path
    )
    page = ArticlePage(
        title="Made in Wagtail",
        slug="made-in-wagtail",
        date=datetime(2026, 9, 1, tzinfo=UTC),
        body=[{"type": "markdown", "value": "Written in the CMS."}],
    )
    posts.add_child(instance=page)
    page.save_revision().publish()
    report = export_site("fixture", tmp_path)
    assert "pages/_posts/2026-09-01-made-in-wagtail.md" in report.rendered
    text = (tmp_path / "pages/_posts/2026-09-01-made-in-wagtail.md").read_text()
    assert (
        text.startswith("---\ntitle: Made in Wagtail\ndate: 2026-09-01 00:00:00 +0000\n")
        and "Written in the CMS." in text
    )


@pytest.mark.django_db
def test_a_preview_under_assets_is_found_like_the_engine_finds_it(tmp_path):
    """rails.assets-terms: `preview: /images/previews/x.png` is a file in the
    source's `assets/images/previews/` (sites/zer0-pages, sites/2005), an SVG is
    imported like any other image, an `/assets/…` value is the same file, and
    an external or missing one sets nothing and keeps its key."""
    report = import_site(SOURCE_SITE, "sourced")
    assert not report.errors, report.errors
    engine = page_at(f"{POSTS}/2026-01-01-engine-preview.md", "sourced")
    assert engine.preview_image is not None and engine.preview_image.width == 8
    assert engine.preview_image.collection.name == "site: sourced"
    svg = page_at(f"{POSTS}/2026-01-02-svg-preview.md", "sourced").preview_image
    assert svg is not None and svg.is_svg() and (svg.width, svg.height) == (16, 9)
    assets = page_at(f"{POSTS}/2026-01-03-assets-preview.md", "sourced")
    assert assets.preview_image == engine.preview_image  # one file, one image; the query is not part of it
    external = page_at(f"{POSTS}/2026-01-04-external-preview.md", "sourced")
    assert external.preview_image is None and external.front_matter["preview"] == "https://images.example/x.png"
    assert page_at(f"{POSTS}/2026-01-05-missing-preview.md", "sourced").preview_image is None
    # The front matter still names the file as written, so every file exports byte for byte.
    export = export_site("sourced", tmp_path, include_drafts=True)
    assert export.rendered == [] and sorted(export.verbatim) == sorted(report.created)
    for rel in export.verbatim:
        assert (tmp_path / rel).read_bytes() == (SOURCE_SITE / rel).read_bytes(), rel


@pytest.mark.django_db
def test_a_preview_is_read_only_through_plain_paths_inside_the_site(tmp_path):
    """A preview is confined like every disk path (sites/writer.py): a symlink
    at any component — even one that stays inside the site — or a `..` that
    leaves it is never read; a file that is not an image is skipped, and its
    page still imports."""
    import shutil

    site = tmp_path / "site"
    shutil.copytree(SOURCE_SITE, site)
    previews = site / "src/assets/images/previews"
    (previews / "alias.png").symlink_to("engine.png")
    (tmp_path / "elsewhere").mkdir()
    shutil.copy(previews / "engine.png", tmp_path / "elsewhere" / "far.png")
    shutil.copy(previews / "engine.png", tmp_path / "outside.png")
    (previews / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    (previews / "broken.png").write_bytes((previews / "engine.png").read_bytes()[:40])
    values = {
        "alias": "/images/previews/alias.png",
        "linked": "/assets/images/previews/linked/far.png",
        "escape": "/../../outside.png",
        "broken": "/images/previews/broken.png",
    }
    for slug, value in values.items():
        (site / POSTS / f"2026-02-01-{slug}.md").write_text(f"---\ntitle: {slug}\npreview: {value}\n---\n\nText.\n")
    report = import_site(site, "confined")
    assert not report.errors, report.errors
    for slug in values:
        assert page_at(f"{POSTS}/2026-02-01-{slug}.md", "confined").preview_image is None, slug
    assert page_at(f"{POSTS}/2026-01-01-engine-preview.md", "confined").preview_image is not None


# The theme's docs site (376 files) is the largest fixture, and it lives in its
# own repository (ADR 0005): content.yml checks bamr87/zer0-mistakes out at a
# pinned tag into .cache/zer0-mistakes; locally, point ZER0_THEME_CHECKOUT at a
# checkout, or the case skips with a reason.
THEME_CHECKOUT = os.environ.get("ZER0_THEME_CHECKOUT", ".cache/zer0-mistakes")
REAL_SITES = [
    "sites/zer0-demo-garden",
    "sites/zer0-pages-remote",
    "sites/zer0-demo-cookbook",
    "sites/drsai",
    # The two big ones (210 and 376 files) run in the full suite, not the fast tier.
    pytest.param("sites/zer0-pages", marks=pytest.mark.slow),
    pytest.param(THEME_CHECKOUT, marks=pytest.mark.slow, id="zer0-mistakes"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("site", REAL_SITES)
def test_the_real_sites_round_trip_byte_for_byte(site, capsys):
    root = REPO / site
    if not (root / "_config.yml").is_file():
        pytest.skip(f"{site} is not in this checkout")
    call_command("roundtrip_jekyll", "--path", str(root), "--site", Path(site).name)
    out = capsys.readouterr().out
    assert "identical after the round trip" in out and "differs" not in out
    assert Page.objects.filter(depth=2).count() >= 1
