"""A site's voice composed in one place (voice/, ADR 0010 V0): every store a
layer in the guard's order, who reads each, the book and chapter scopes, the
`brand.rules` tool answering exactly what it always answered, and the API —
a page the caller may open, a channel of the site, AIEO's context hidden from
anyone who does not edit the site, and the guard run on a text without a model."""

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from agents.tools import brand_rules
from ai.models import Assistant, Visibility
from aieo.models import CONTEXT_TEMPLATES, BrandContext
from cms.models import BrandRules, ChapterPage
from cms.services import save_draft
from distribution.models import Channel
from sites.models import SiteSettings
from suggestions.guard import BANNED_PATTERNS, FILLER, builtin_bans, site_of
from voice.services import resolve, told

from ..conftest import make_article


def keys(resolved):
    return [layer["key"] for layer in resolved["layers"]]


def layer(resolved, key):
    return next(layer for layer in resolved["layers"] if layer["key"] == key)


def what_brand_rules_answered(target):
    """The `brand.rules` tool before it read voice/services.py, kept here to hold the new one to it."""
    active = BrandRules.objects.filter(is_active=True)
    own = SiteSettings.objects.filter(site=site_of(target)).first()
    builtin = [name for name, _ in BANNED_PATTERNS] if builtin_bans(target) else []
    entries = [p for r in active for p in (r.banned_patterns or [])] + (own.banned_patterns if own else [])
    return {
        "style_guides": [r.style_guide for r in active if r.style_guide]
        + ([own.brand_voice] if own and own.brand_voice else []),
        "banned": builtin + [p.get("name") for p in entries if isinstance(p, dict)],
    }


@pytest.fixture
def voiced(article):
    """The article's site with every store of a voice filled in, malformed entries included."""
    site = article.get_site()
    house = BrandRules.objects.create(
        name="House",
        style_guide="Short sentences.",
        banned_patterns=[{"name": "synergy", "pattern": r"\bsynerg\w*"}, "a bare string", {"pattern": "nameless"}],
    )
    BrandRules.objects.create(name="Retired", is_active=False, style_guide="Old.", banned_patterns=[])
    SiteSettings.objects.create(
        site=site,
        brand_voice="Plain and calm.",
        banned_patterns=[{"name": "nightly", "pattern": r"\bnightly\b"}, {"name": "broken", "pattern": "("}],
    )
    BrandContext.objects.create(site=site, brand_voice="Warm, exact.", style_guide=CONTEXT_TEMPLATES["style_guide"])
    return SimpleNamespace(site=site, house=house, article=article)


@pytest.mark.django_db
def test_a_site_with_nothing_set_is_the_built_in_lists_alone_and_reading_it_makes_no_row(article):
    resolved = resolve(article.get_site(), page=article)
    assert keys(resolved) == ["builtin"]
    builtin = layer(resolved, "builtin")
    assert builtin["active"] and builtin["scope"] == "platform"
    assert [b["name"] for b in builtin["bans"] if b["level"] == "error"] == [name for name, _ in BANNED_PATTERNS]
    assert len([b for b in builtin["bans"] if b["level"] == "warning"]) == len(FILLER)
    assert not SiteSettings.objects.exists() and not BrandContext.objects.exists()


@pytest.mark.django_db
def test_every_store_is_a_layer_in_the_order_the_guard_applies_it_with_who_reads_it(voiced):
    resolved = resolve(voiced.site, page=voiced.article)
    assert keys(resolved) == ["builtin", f"brand-rules-{voiced.house.pk}", "site", "aieo"]
    site = layer(resolved, "site")
    assert site["guidance"] == [{"label": "Brand voice", "text": "Plain and calm."}]
    assert {"guard", "review", "eval", "distribution", "brand_rules"} == set(site["readers"])
    broken = next(b for b in site["bans"] if b["name"] == "broken")
    assert not broken["valid"] and "not a regular expression" in broken["why"]
    house = layer(resolved, f"brand-rules-{voiced.house.pk}")
    assert [b["valid"] for b in house["bans"]] == [True, False, False]
    aieo = layer(resolved, "aieo")
    assert aieo["readers"] == ["aieo"]
    assert aieo["guidance"] == [
        {"label": "Brand voice", "text": "Warm, exact."}
    ]  # the unfilled template is not a voice


@pytest.mark.django_db
def test_the_digest_follows_what_the_voice_says_not_who_reads_it(voiced):
    first = resolve(voiced.site, page=voiced.article)["digest"]
    assert resolve(voiced.site, page=voiced.article)["digest"] == first
    SiteSettings.objects.filter(site=voiced.site).update(brand_voice="Plain, calm and brief.")
    assert resolve(voiced.site, page=voiced.article)["digest"] != first


@pytest.mark.django_db
def test_brand_rules_answers_what_it_always_answered(voiced, root_page):
    for target in (None, voiced.article, make_article(root_page, "Nowhere")):
        assert brand_rules(SimpleNamespace(extra={"target": target})) == what_brand_rules_answered(target)
    # after the built-in errors: each mapping's name as stored (None for a nameless one), a bare string left out
    banned = told(resolve(voiced.site, page=voiced.article))["banned"]
    assert banned[len(BANNED_PATTERNS) :] == ["synergy", None, "nightly", "broken"]


@pytest.mark.django_db
def test_a_chapter_shows_its_book_and_its_tone_and_who_lifted_the_built_in_bans(sample):
    def first():  # fresh each time: a page caches its parent, and the parent its latest revision
        return ChapterPage.objects.child_of(sample).get(number=1)

    draft = first().get_latest_revision_as_object()
    draft.tone = ["wry"]
    save_draft(draft, user=None)
    site = first().get_site()
    resolved = resolve(site, page=first())
    assert keys(resolved)[-2:] == ["book", "chapter"] and layer(resolved, "builtin")["active"]
    assert layer(resolved, "chapter")["guidance"][0] == {"label": "Tone", "text": "wry"}
    book = sample.get_latest_revision_as_object()
    book.builtin_bans = False
    save_draft(book, user=None)
    lifted = layer(resolve(site, page=first()), "builtin")
    assert not lifted["active"] and lifted["lifted_by"] == "book"
    own = SiteSettings.for_site(site)
    own.chapter_builtin_bans = False
    own.save()
    assert layer(resolve(site, page=first()), "builtin")["lifted_by"] == "site"
    assert brand_rules(SimpleNamespace(extra={"target": first()})) == what_brand_rules_answered(first())
    channel = Channel.objects.create(site=site, kind="linkedin", name="Company page")
    # a post's text is commentary: the distribution guard holds the built-in lists whatever the page is
    assert layer(resolve(site, page=first(), channel=channel), "builtin")["active"]


# ── the API ─────────────────────────────────────────────────────────────────


@pytest.fixture
def boss(db):
    return get_user_model().objects.create_superuser("boss", password="pw")


@pytest.fixture
def client(boss):
    c = APIClient()
    c.force_authenticate(boss)
    return c


@pytest.mark.django_db
def test_the_api_resolves_a_page_with_the_assistants_that_could_read_it(client, voiced, boss):
    Assistant.objects.create(
        name="Asks", owner=boss, site=voiced.site, visibility=Visibility.SITE, tools=["brand.rules"]
    )
    Assistant.objects.create(name="Does not", owner=boss, site=voiced.site, visibility=Visibility.SITE, tools=[])
    answer = client.get(f"/api/v2/sites/{voiced.site.pk}/voice/resolved/", {"page": voiced.article.pk})
    assert answer.status_code == 200, answer.json()
    body = answer.json()
    assert body["page"]["title"] == "Nightly backups" and body["channel"] is None
    assert [layer["key"] for layer in body["layers"]][-2:] == ["site", "aieo"]
    reads = {a["name"]: a["reads_voice"] for a in body["assistants"]}
    assert reads["Asks"] and not reads["Does not"]
    assert not any(reads[name] for name in reads if name not in ("Asks", "Does not"))  # no bundled one asks
    assert body["told"] == what_brand_rules_answered(voiced.article)
    assert {r["key"] for r in body["readers"]} >= {"guard", "brand_rules", "aieo", "book"}


@pytest.mark.django_db
def test_the_api_refuses_a_page_or_channel_of_another_site_and_hides_aieo_from_non_editors(
    client, voiced, root_page, monkeypatch
):
    from wagtail.models import Site

    from cms.models import SiteRootPage
    from ops.errors import NotFound

    url = f"/api/v2/sites/{voiced.site.pk}/voice/resolved/"
    elsewhere = SiteRootPage(title="Elsewhere", slug="elsewhere", site_key="elsewhere")
    root_page.add_child(instance=elsewhere)
    other = Site.objects.create(hostname="elsewhere.localhost", root_page=elsewhere)
    assert client.get(url, {"page": make_article(elsewhere, "Theirs").pk}).status_code == 404
    theirs = Channel.objects.create(site=other, kind="linkedin", name="Theirs")
    assert client.get(url, {"channel": str(theirs.public_id)}).status_code == 404
    assert client.get(url, {"channel": "not-a-uuid"}).status_code == 404
    assert client.get("/api/v2/sites/999999/voice/resolved/").status_code == 404

    def not_an_editor(user, site):
        raise NotFound("no site")

    monkeypatch.setattr("voice.views.editor_of", not_an_editor)
    aieo = next(layer for layer in client.get(url).json()["layers"] if layer["key"] == "aieo")
    assert aieo["hidden"] and aieo["guidance"] == []


@pytest.mark.django_db
def test_the_api_tests_a_text_against_the_page_or_the_channel_without_a_model(client, voiced):
    url = f"/api/v2/sites/{voiced.site.pk}/voice/test/"
    text = "Our cutting-edge nightly copies!"
    found = client.post(url, {"text": text, "page": voiced.article.pk}, format="json")
    assert found.status_code == 200, found.json()
    messages = [f["message"] for f in found.json()["findings"] if f["level"] == "error"]
    assert any("cutting-edge" in m for m in messages) and any("nightly" in m for m in messages)
    channel = Channel.objects.create(site=voiced.site, kind="linkedin", name="Company page")
    post = client.post(url, {"text": text, "channel": str(channel.public_id)}, format="json").json()
    assert any(f["level"] == "info" and "fold at 140" in f["message"] for f in post["findings"])
    assert (
        post["digest"]
        == client.get(f"/api/v2/sites/{voiced.site.pk}/voice/resolved/", {"channel": str(channel.public_id)}).json()[
            "digest"
        ]
    )
    assert client.post(url, {"text": "x" * 20_001}, format="json").status_code == 422


@pytest.mark.django_db
def test_an_agent_principal_may_not_ask(voiced):
    agent = get_user_model().objects.create_user("agent:somebody", password="pw")
    c = APIClient()
    c.force_authenticate(agent)
    assert c.get(f"/api/v2/sites/{voiced.site.pk}/voice/resolved/").status_code == 403
