"""The SEO and social fields beyond Wagtail's own (P4): `canonical_url`, the
Open Graph title, description and image, and `noindex` — each the front-matter
key its file has (`image` for the Open Graph image), shown to a person as the
file says it, written back only where a person changed it, and owned by its
field rather than raw front matter. An imported page keeps its hash, so an
unchanged file exports byte for byte."""

from pathlib import Path

import pytest
from rest_framework.test import APIClient

from cms.models import ArticlePage
from distribution.services import canonical_url
from exporters.jekyll import export_site
from importers.jekyll import import_site
from importers.models import ImportedSource

POST = "_posts/2026-10-02-seo.md"
FRONT = """---
title: SEO
date: 2026-10-02
canonical_url: https://example.com/original/
og_title: "A title for sharing"
og_description: Shared, not searched.
image:
  path: /assets/images/seo.png
  alt: A chart
noindex: true
---

Body.
"""


@pytest.fixture
def imported(tmp_path, db):
    site = tmp_path / "site"
    (site / "_posts").mkdir(parents=True)
    (site / "_config.yml").write_text("title: SEO\nurl: https://seo.example\n")
    (site / POST).write_text(FRONT)
    report = import_site(site, "seo")
    assert not report.errors, report.errors
    return ImportedSource.objects.get(site_key="seo", legacy_path=POST).page.specific


def exported(tmp_path) -> str:
    out = tmp_path / "out"
    export_site("seo", out, include_drafts=True)
    return (out / POST).read_text()


def save(page, editor, fields):
    client = APIClient()
    client.force_authenticate(editor)
    response = client.patch(
        f"/api/v2/content/pages/{page.pk}/",
        {"base_revision_id": page.get_latest_revision().pk, "fields": fields},
        format="json",
    )
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.mark.django_db
def test_an_imported_file_shows_its_seo_keys_as_fields_and_exports_byte_for_byte(imported, tmp_path, editor):
    assert all(getattr(imported, name) is None for name in ("og_title", "og_image", "canonical_url", "noindex"))
    source = ImportedSource.objects.get(page=imported)
    assert source.unchanged(imported)  # the fields add nothing to the hash while the page says what its file says
    assert exported(tmp_path) == FRONT
    client = APIClient()
    client.force_authenticate(editor)
    detail = client.get(f"/api/v2/content/pages/{imported.pk}/").json()
    fields = detail["fields"]
    assert fields["canonical_url"] == "https://example.com/original/" and fields["og_title"] == "A title for sharing"
    assert fields["og_description"] == "Shared, not searched." and fields["noindex"] is True
    assert fields["og_image"] == ""  # jekyll-seo-tag's {path, alt} form is not a field's: shown empty, kept as it is
    seo = {s["name"]: s for s in detail["field_specs"] if s["group"] == "seo"}
    assert seo["noindex"]["kind"] == "boolean" and seo["og_image"]["label"] == "Open Graph image"
    assert fields["front_matter"] == {}  # every key of this file is a typed field's: none is raw
    assert canonical_url(imported) == "https://example.com/original/"


@pytest.mark.django_db
def test_a_changed_seo_field_rewrites_its_own_key_and_nothing_else(imported, tmp_path, editor):
    save(imported, editor, {"title": "SEO, revised"})
    assert exported(tmp_path) == FRONT.replace("title: SEO\n", "title: SEO, revised\n")  # no SEO key touched
    page = ArticlePage.objects.get(pk=imported.pk)
    fields = save(page, editor, {"og_title": "Shared better", "noindex": False, "og_image": "/assets/images/x.png"})[
        "fields"
    ]
    assert fields["og_title"] == "Shared better" and fields["noindex"] is False
    text = exported(tmp_path)
    assert 'og_title: "Shared better"\n' in text and "noindex: false\n" in text  # in place, its quoting kept
    assert "image: /assets/images/x.png\n" in text and "  alt: A chart" not in text  # a person replaced the mapping
    assert (
        "canonical_url: https://example.com/original/\n" in text and "og_description: Shared, not searched.\n" in text
    )
    page = ArticlePage.objects.get(pk=imported.pk)
    save(page, editor, {"canonical_url": "https://seo.example/elsewhere/"})
    assert canonical_url(ArticlePage.objects.get(pk=imported.pk).get_latest_revision_as_object()) == (
        "https://seo.example/elsewhere/"
    )


@pytest.mark.django_db
def test_seo_keys_are_fields_not_raw_front_matter_and_a_new_page_writes_them(site_root, editor, tmp_path):
    from cms.models import CollectionPage
    from cms.services import create_draft, publish

    site_root.site_key = "seo"
    site_root.save()
    posts = CollectionPage(title="Posts", slug="posts", collection="posts", output_dir="_posts")
    site_root.add_child(instance=posts)
    page = create_draft(
        posts,
        ArticlePage,
        editor,
        fields={"title": "New", "og_description": "For sharing.", "noindex": True, "front_matter": {"excerpt": "x"}},
    )
    publish(page, editor)
    out = tmp_path / "out"
    export_site("seo", out)
    [written] = list(Path(out).rglob("*.md"))
    text = written.read_text()
    assert text.index("og_description: For sharing.") < text.index("excerpt: x") and "noindex: true\n" in text
    client = APIClient()
    client.force_authenticate(editor)
    refused = client.patch(
        f"/api/v2/content/pages/{page.pk}/",
        {"base_revision_id": page.get_latest_revision().pk, "fields": {"front_matter": {"image": "/x.png"}}},
        format="json",
    )
    assert refused.status_code == 422
    assert "Open Graph image" in refused.json()["error"]["details"][0]["message"]
    bad = client.patch(
        f"/api/v2/content/pages/{page.pk}/",
        {"base_revision_id": page.get_latest_revision().pk, "fields": {"canonical_url": "not a url"}},
        format="json",
    )
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "canonical_url"
