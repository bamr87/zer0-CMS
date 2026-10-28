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
    assert [b.block_type for b in hello.body] == ["markdown", "heading", "markdown", "code", "raw_html"]
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
def test_a_landing_page_carries_its_call_to_action_into_its_file_and_back(imported, tmp_path):
    """A landing page's file keeps its call to action in its front matter (`cta_text`, `cta_url`), and a page whose
    front matter has one is read back as a landing page — `layout: landing` alone is a theme's layout, not this type."""
    from aieo.models import LandingPage

    root = SiteRootPage.objects.get(site_key="fixture")
    page = LandingPage(
        title="Bookkeeping for founders",
        slug="founders",
        cta_text="Start your free trial",
        cta_url="/trial/",
        body=[{"type": "markdown", "value": "Close the books in a day."}],
    )
    root.add_child(instance=page)
    page.save_revision().publish()
    export_site("fixture", tmp_path)
    text = (tmp_path / "founders.md").read_text()
    assert text.startswith(
        "---\ntitle: Bookkeeping for founders\ncta_text: Start your free trial\ncta_url: /trial/\n---"
    )
    copy = tmp_path / "copy"  # the generated file, read back as a site of its own
    copy.mkdir()
    (copy / "_config.yml").write_text("title: Landing copy\n")
    (copy / "founders.md").write_text(text)
    (copy / "index.md").write_text("---\ntitle: Home\nlayout: landing\n---\nWelcome.\n")
    report = import_site(copy, "landing-copy")
    assert not report.errors and sorted(report.created) == ["founders.md", "index.md"]
    back = ImportedSource.objects.get(site_key="landing-copy", legacy_path="founders.md").page.specific
    assert isinstance(back, LandingPage) and (back.cta_text, back.cta_url) == ("Start your free trial", "/trial/")
    home = ImportedSource.objects.get(site_key="landing-copy", legacy_path="index.md").page.specific
    assert isinstance(home, StandardPage)
    back.cta_text = "Book a demo"
    back.save_revision().publish()
    export_site("landing-copy", tmp_path / "again")
    assert "\ncta_text: Book a demo\ncta_url: /trial/\n" in (tmp_path / "again" / "founders.md").read_text()


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


DRAFTS = [
    f"{POSTS}/2026-03-01-unpublished.md",  # published: false — Jekyll never builds it
    f"{POSTS}/2026-03-02-draft-flag.md",  # draft: true — how the zer0 sites mark a draft
    f"{POSTS}/2026-03-03-status-draft.md",  # status: draft — and the other way
    "src/_drafts/idea.md",
]
FAR_FUTURE = f"{POSTS}/2999-01-01-far-future.md"  # dated by its file name
UPCOMING = "src/_docs/upcoming.md"  # a collection document dated in the front matter
SOMEDAY = "src/someday.md"  # a page dated in the front matter


def state(rel, site):
    page = page_at(rel, site)
    return "live" if page.live else "scheduled" if page.scheduled_revision else "draft"


@pytest.mark.django_db
def test_a_file_the_site_does_not_build_imports_as_a_draft_or_scheduled(tmp_path):
    """rails.page-search: a file is live exactly when the catalog says the site
    builds it (`Entry.live`, the write-back's rule too). `published: false`,
    `draft: true`, `status: draft` and `_drafts/` are drafts, never published (a
    quoted "false" is true to Ruby: built, so live); a file dated in the future
    is scheduled for its date. A re-import changes nothing, not even once
    Wagtail's sweep has published the scheduled page, and every file exports
    byte for byte."""
    from datetime import UTC, datetime, timedelta

    from django.utils import timezone

    from cms.tasks import publish_scheduled
    from sites import catalog

    report = import_site(SOURCE_SITE, "states")
    assert not report.errors, report.errors
    states = {rel: state(rel, "states") for rel in report.created}
    assert {rel for rel, s in states.items() if s == "draft"} == set(DRAFTS)
    assert {rel for rel, s in states.items() if s == "scheduled"} == {FAR_FUTURE, UPCOMING, SOMEDAY}
    assert states[f"{POSTS}/2026-03-04-quoted-false.md"] == "live"
    assert {e.relative: e.live for e in catalog.scan(SOURCE_SITE).entries} == {
        rel: s == "live" for rel, s in states.items()
    }
    for rel in DRAFTS:
        page = page_at(rel, "states")
        assert page.go_live_at is None and page.get_latest_revision() is not None, rel
    # The file's own marker stays in the page's front matter (the write-back tells it from its own by that).
    for rel, (key, value) in zip(DRAFTS, [("published", False), ("draft", True), ("status", "draft")], strict=False):
        assert page_at(rel, "states").front_matter[key] == value, rel
    # A date with no zone is local time, as the catalog (and Ruby) read it.
    assert page_at(FAR_FUTURE, "states").scheduled_revision.approved_go_live_at == datetime(2999, 1, 1).astimezone()
    assert page_at(UPCOMING, "states").go_live_at == datetime(2999, 2, 1, 9, tzinfo=UTC)
    assert page_at(SOMEDAY, "states").go_live_at == datetime(2999, 3, 1, 12, tzinfo=UTC)

    revisions = Revision.objects.count()
    again = import_site(SOURCE_SITE, "states")
    assert again.created == again.updated == [] and sorted(again.unchanged) == sorted(report.created)
    assert Revision.objects.count() == revisions and {rel: state(rel, "states") for rel in report.created} == states

    # The clock reaches the post's date: the sweep publishes it, and a re-import leaves it live.
    revision = page_at(FAR_FUTURE, "states").scheduled_revision
    past = timezone.now() - timedelta(minutes=1)
    revision.content["go_live_at"] = past.isoformat()
    revision.approved_go_live_at = past
    revision.save(update_fields=["content", "approved_go_live_at"])
    publish_scheduled()
    assert state(FAR_FUTURE, "states") == "live"
    revisions = Revision.objects.count()
    assert FAR_FUTURE in import_site(SOURCE_SITE, "states").unchanged
    assert state(FAR_FUTURE, "states") == "live" and Revision.objects.count() == revisions

    live_only = export_site("states", tmp_path / "live")
    assert not {*DRAFTS, UPCOMING, SOMEDAY} & {*live_only.verbatim, *live_only.rendered}
    export = export_site("states", tmp_path / "all", include_drafts=True)
    assert export.rendered == [] and sorted(export.verbatim) == sorted(report.created)
    for rel in export.verbatim:
        assert (tmp_path / "all" / rel).read_bytes() == (SOURCE_SITE / rel).read_bytes(), rel


@pytest.mark.django_db
def test_a_site_with_future_true_publishes_what_is_dated_in_the_future_now(tmp_path):
    """Jekyll builds a file dated in the future when `_config.yml` says
    `future: true`, so it imports live; a draft stays a draft."""
    import shutil

    site = tmp_path / "site"
    shutil.copytree(SOURCE_SITE, site)
    with (site / "_config.yml").open("a") as config:
        config.write("future: true\n")
    assert not import_site(site, "future").errors
    assert state(FAR_FUTURE, "future") == state(UPCOMING, "future") == state(SOMEDAY, "future") == "live"
    assert page_at(FAR_FUTURE, "future").go_live_at is None
    assert {state(rel, "future") for rel in DRAFTS} == {"draft"}


@pytest.mark.django_db
def test_a_changed_file_moves_its_page_between_live_scheduled_and_draft(tmp_path):
    """The file decides: a live page whose file now marks it a draft, or dates
    it in the future, comes down; a scheduled one dated in the past goes up
    now; a draft cancels a schedule."""
    import shutil
    from datetime import datetime

    site = tmp_path / "site"
    shutil.copytree(SOURCE_SITE, site)
    assert not import_site(site, "moving").errors

    def edit(rel, old, new):
        path = site / rel
        path.write_text(path.read_text().replace(old, new, 1))
        report = import_site(site, "moving")
        assert report.updated == [rel] and not report.errors, report.errors + report.conflicts
        return state(rel, "moving")

    engine = f"{POSTS}/2026-01-01-engine-preview.md"
    assert edit(engine, "\n---\n", "\nstatus: draft\n---\n") == "draft"
    assert edit(engine, "status: draft\n", "") == "live"
    assert edit(engine, "\n---\n", "\ndate: 2999-04-01\n---\n") == "scheduled"
    assert page_at(engine, "moving").scheduled_revision.approved_go_live_at == datetime(2999, 4, 1).astimezone()
    assert edit(FAR_FUTURE, "\n---\n", "\ndate: 2026-01-10\n---\n") == "live"
    assert page_at(FAR_FUTURE, "moving").go_live_at is None
    assert edit(UPCOMING, "\n---\n", "\npublished: false\n---\n") == "draft"
    assert page_at(UPCOMING, "moving").go_live_at is None


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
    "sites/irony-works",
    # The big ones run in the full suite, not the fast tier: wargames and 2005 (whose bodies are
    # mostly HTML blocks and tables), zer0-pages (210 files) and the theme's docs site (376).
    pytest.param("sites/wargames", marks=pytest.mark.slow),
    pytest.param("sites/2005", marks=pytest.mark.slow),
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
