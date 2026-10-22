"""Bylines and corrections in `export_jekyll`'s output (PLAN G15): a story's
exported file carries `authors` and `corrections` (date, kind, text) for the
site to render — an imported page that has them is rendered rather than
written back verbatim — and a page without them exports exactly as before."""

import pytest

from exporters.jekyll import export_site
from importers import frontmatter
from importers.models import ImportedSource
from newsroom import services
from newsroom.models import Author, Story

S = Story.Status


@pytest.mark.django_db
def test_a_storys_bylines_and_corrections_are_in_its_exported_front_matter(desk, ed, advance, tmp_path):
    author = Author.objects.create(name="Ada Reporter", slug="ada")
    story = advance(desk, S.PUBLISHED, headline="Bridge reopens")
    services.update(story, user=ed, bylines=[author])
    services.move(story, S.CORRECTED, user=ed, text="An earlier version gave the wrong date.")
    quiet = advance(desk, S.PUBLISHED, headline="Nothing to add")

    page = story.page.specific
    source = "---\ntitle: Bridge reopens\n---\nAs imported.\n"
    ImportedSource.objects.create(
        page=page,
        site_key="test-site",
        legacy_path="_posts/bridge.md",
        source_text=source,
        source_digest="x",
        import_hash=page.compute_content_hash(),
    )
    page.legacy_path = "_posts/bridge.md"
    page.save(update_fields=["legacy_path"])

    report = export_site("test-site", tmp_path)
    assert "_posts/bridge.md" in report.rendered  # unchanged since import, but it has a log to show
    data, _ = frontmatter.split((tmp_path / "_posts/bridge.md").read_text())
    assert data["authors"] == ["Ada Reporter"]
    [entry] = data["corrections"]
    assert (entry["kind"], entry["text"]) == ("correction", "An earlier version gave the wrong date.")
    assert entry["date"] == frontmatter.format_date(story.corrections.get().created_at)

    quiet_file = next(path for path in report.rendered if quiet.page.slug in path)
    quiet_data, _ = frontmatter.split((tmp_path / quiet_file).read_text())
    assert "authors" not in quiet_data and "corrections" not in quiet_data
