"""The public read surfaces show only what is public (SITES-11, SEC-19): an
anonymous caller of REST's `images/` and `documents/` and of GraphQL's
`images`, `image`, `documents` and `document` gets the files a live, public
page references (Wagtail's ReferenceIndex) and nothing a draft holds; and the
OpenAPI document is served to anyone only while the API docs are on."""

import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.images import ImageFile
from django.test import Client, override_settings
from PIL import Image as Pillow
from wagtail.documents import get_document_model
from wagtail.images import get_image_model
from wagtail.models import ReferenceIndex

from ..conftest import make_article


def image(title):
    data = io.BytesIO()
    Pillow.new("RGB", (8, 8)).save(data, "PNG")
    return get_image_model().objects.create(title=title, file=ImageFile(data, name=f"{title}.png"))


def document(title):
    return get_document_model().objects.create(title=title, file=ContentFile(b"%PDF-1.4", name=f"{title}.pdf"))


def file_block(doc):
    return {"type": "document", "value": {"title": doc.title, "href": f"/files/{doc.title}.pdf", "document": doc.pk}}


@pytest.fixture
def media(site_root):
    """`shown` and `report` on a live page; `drafted` and `memo` on a page never
    published, indexed as Wagtail's own task indexes a saved row; `pending` only
    in an unpublished draft of the live page; `loose` and `spare` on nothing."""
    shown, drafted, pending, loose = image("shown"), image("drafted"), image("pending"), image("loose")
    report, memo, spare = document("report"), document("memo"), document("spare")
    live = make_article(site_root, "Live", preview_image=shown, body=[file_block(report)])
    draft = make_article(site_root, "Draft", publish=False, preview_image=drafted, body=[file_block(memo)])
    ReferenceIndex.create_or_update_for_object(draft)
    later = live.get_latest_revision_as_object()
    later.preview_image = pending
    later.save_revision()
    ReferenceIndex.create_or_update_for_object(type(live).objects.get(pk=live.pk))
    return {"shown": shown, "drafted": drafted, "pending": pending, "loose": loose}, {
        "report": report,
        "memo": memo,
        "spare": spare,
    }


def titles(response):
    assert response.status_code == 200, response.content
    return sorted(item["title"] for item in response.json()["items"])


def graphql(query):
    response = Client().post("/graphql/", json.dumps({"query": query}), content_type="application/json")
    assert response.status_code == 200, response.content
    body = response.json()
    assert "errors" not in body, body
    return body["data"]


@pytest.mark.django_db
def test_rest_lists_only_the_files_a_live_page_references(media):
    images, documents = media
    anonymous = Client()
    assert titles(anonymous.get("/api/v2/images/")) == ["shown"]
    assert titles(anonymous.get("/api/v2/documents/")) == ["report"]
    assert anonymous.get(f"/api/v2/images/{images['shown'].pk}/").status_code == 200
    for hidden in ("drafted", "pending", "loose"):
        assert anonymous.get(f"/api/v2/images/{images[hidden].pk}/").status_code == 404, hidden
    assert anonymous.get(f"/api/v2/documents/{documents['memo'].pk}/").status_code == 404


@pytest.mark.django_db
def test_graphql_lists_only_the_files_a_live_page_references(media):
    images, documents = media
    data = graphql("{ images { title } documents { title } }")
    assert [i["title"] for i in data["images"]] == ["shown"]
    assert [d["title"] for d in data["documents"]] == ["report"]
    one = graphql(
        f'{{ shown: image(id: "{images["shown"].pk}") {{ title }} drafted: image(id: "{images["drafted"].pk}") '
        f'{{ title }} memo: document(id: "{documents["memo"].pk}") {{ title }} }}'
    )
    assert one == {"shown": {"title": "shown"}, "drafted": None, "memo": None}


@pytest.mark.django_db
def test_the_openapi_document_needs_a_session_while_the_docs_are_off(client):
    with override_settings(API_DOCS_ENABLED=False):
        refused = client.get("/api/v2/openapi.json")
        assert refused.status_code == 401 and refused.json()["error"]["code"] == "auth.required"
        client.force_login(get_user_model().objects.create_user("reader", password="pw"))
        assert client.get("/api/v2/openapi.json").status_code == 200
    assert Client().get("/api/v2/openapi.json").status_code == 200  # the docs are on in testing
