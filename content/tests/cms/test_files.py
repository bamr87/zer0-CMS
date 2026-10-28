"""cms/files.py below the API: raw front matter can never set a key the
exporter writes from a field (for every page type that has a file), keeps each
typed key in its file's place, holds only what YAML gives back as it is, and a
file path's checks hold without a request."""

from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError

from cms import files
from cms.models import ArticlePage, BookPage, Category, CollectionPage, SiteRootPage, StandardPage
from exporters.jekyll import front_matter_for
from tests.conftest import make_article


def test_only_pages_that_are_files_of_their_own_have_a_file_to_edit():
    assert ArticlePage.file_editor_fields == StandardPage.file_editor_fields == ("file_path", "front_matter")
    for model in (SiteRootPage, CollectionPage, BookPage):  # not exported as a file / the books library's files
        assert model.file_editor_fields == ()


@pytest.mark.django_db
def test_every_key_the_exporter_writes_from_a_field_is_refused_as_raw_front_matter(site_root):
    category = Category.objects.create(name="Ops", slug="ops")
    article = make_article(
        site_root,
        "Every field",
        seo_title="Every field, briefly",
        search_description="All of them set.",
        date=datetime(2026, 10, 28, 9, tzinfo=UTC),
        author="rhea",
    )
    article.tags.add("ai")
    article.categories.add(category)
    standard = StandardPage(title="About", slug="about", seo_title="About us", search_description="Who.")
    site_root.add_child(instance=standard)
    for page in (article, standard):
        written = set(front_matter_for(page))
        assert written <= set(files.owned_keys(type(page))), written - set(files.owned_keys(type(page)))


def test_raw_front_matter_fills_the_raw_places_and_keeps_the_typed_keys_where_they_were():
    page = ArticlePage(front_matter={"layout": "post", "title": "T", "date": "2026-07-31", "comments": True})
    assert files.raw_front_matter(page) == {"layout": "post", "comments": True}
    files.set_front_matter(page, {"layout": "post", "comments": True})
    assert list(page.front_matter) == ["layout", "title", "date", "comments"]  # as read, nothing moves
    files.set_front_matter(page, {"comments": False, "excerpt": "New.", "layout": "wide"})
    assert list(page.front_matter) == ["comments", "title", "date", "excerpt", "layout"]
    assert page.front_matter["title"] == "T"
    files.set_front_matter(page, None)
    assert page.front_matter == {"title": "T", "date": "2026-07-31"}


def test_raw_front_matter_holds_only_what_the_exporters_yaml_gives_back():
    page = StandardPage(front_matter={})
    for value in (float("inf"), float("nan"), ["ok", {"deep": float("-inf")}], "\ud800"):
        with pytest.raises(ValidationError) as refused:
            files.set_front_matter(page, {"weight": value})
        assert list(refused.value.message_dict) == ["front_matter.weight"], value
    fine = {"note": "multi\nline\n", "when": "2026-10-28", "yes": "yes", "n": 1.5, "flag": None, "": None}
    with pytest.raises(ValidationError) as empty_key:
        files.set_front_matter(page, fine)
    assert list(empty_key.value.message_dict) == ["front_matter"]
    del fine[""]
    files.set_front_matter(page, fine)
    assert page.front_matter == fine


@pytest.mark.parametrize(
    "path, problem",
    [
        ("pages/_posts/wire/2026-10-28-example.md", None),
        ("about.html", None),
        ("pages/_docs/setup.markdown", None),
        ("pages/ spaced/x.md", "space"),
        ("pages/tab\there.md", "control"),
        ("x" * 510 + ".md", "512"),
        ("pages/_posts/README", ".md, .markdown or .html"),
    ],
)
def test_a_file_paths_shape(path, problem):
    found = files._path_problem(path)
    assert (found is None) if problem is None else (problem in found)


def test_a_dated_file_name_is_the_dates_day_in_utc():
    page = ArticlePage(legacy_path="pages/_posts/2026-10-28-x.md", date=datetime(2026, 10, 28, 23, 59, tzinfo=UTC))
    assert files.date_problem(page) is None
    page.date = datetime(2026, 10, 29, tzinfo=UTC)
    assert "dated 2026-10-28" in files.date_problem(page)
    page.legacy_path = "pages/_posts/undated.md"
    assert files.date_problem(page) is None
    assert files.date_problem(StandardPage(legacy_path="pages/2026-10-28-x.md")) is None  # no date to agree with
