"""The AI content layer's tables (TARGET.md § The AI content layer): credentials
encrypted at rest and rotatable — through the move to explicit keys and a new
`SECRET_KEY` — one default provider by constraint, schemas (local references
only) and personas validated on save, one `visible_to` that scopes every row,
and the bundled barodybroject schemas seeded by migrate once the tables are
there."""

import io
import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.db.migrations.state import ProjectState
from django.test import override_settings
from wagtail.models import Page, Site

from ai.apps import _seed
from ai.models import (
    Assistant,
    Conversation,
    Message,
    ModelEntry,
    OutputSchema,
    Pipeline,
    PipelineStep,
    ProviderConfig,
    Visibility,
)
from ai.providers import NotConfigured
from ai.services import DATA, bundled_schema, import_bundled, stable_id

PARODYNEWS_SCHEMAS = Path(__file__).resolve().parents[3] / "apps" / "parodynews" / "src" / "parodynews" / "schema"


@pytest.mark.django_db
def test_a_credential_is_encrypted_at_rest_and_round_trips():
    row = ProviderConfig.objects.get(slug="anthropic")
    assert not row.has_credential and row.get_credential() == ""
    row.set_credential("sk-ant-api-very-secret")
    row.save()
    stored = ProviderConfig.objects.values_list("credential_encrypted", flat=True).get(pk=row.pk)
    assert "very-secret" not in stored and stored.startswith("gAAAA")
    row.refresh_from_db()
    assert row.has_credential and row.get_credential() == "sk-ant-api-very-secret"
    assert row.settings().credential == "sk-ant-api-very-secret"
    row.set_credential("")
    assert not row.has_credential


@pytest.mark.django_db
def test_credentials_survive_the_move_to_explicit_keys_and_rotate_to_a_new_one():
    row = ProviderConfig.objects.get(slug="openai")
    row.set_credential("sk-openai")  # no AI_CREDENTIAL_KEYS yet: the key derived from SECRET_KEY
    row.save()
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    out = io.StringIO()
    with override_settings(AI_CREDENTIAL_KEYS=[old]):
        assert ProviderConfig.objects.get(pk=row.pk).get_credential() == "sk-openai"  # the derived key still reads
        call_command("rotate_ai_credentials", stdout=out)
    with override_settings(AI_CREDENTIAL_KEYS=[new, old]):
        call_command("rotate_ai_credentials", stdout=out)
    with override_settings(AI_CREDENTIAL_KEYS=[new], SECRET_KEY="a-new-secret"):
        assert ProviderConfig.objects.get(pk=row.pk).get_credential() == "sk-openai"
    with override_settings(AI_CREDENTIAL_KEYS=[old]):
        with pytest.raises(NotConfigured, match="rotate_ai_credentials"):
            ProviderConfig.objects.get(pk=row.pk).get_credential()
        with pytest.raises(CommandError, match="the openai credential"):
            call_command("rotate_ai_credentials", stdout=out)


@pytest.mark.django_db
def test_a_credential_survives_a_new_secret_key_through_its_fallbacks():
    with override_settings(SECRET_KEY="first"):
        row = ProviderConfig.objects.get(slug="anthropic")
        row.set_credential("sk-ant-api-x")
        row.save()
    with override_settings(SECRET_KEY="second", SECRET_KEY_FALLBACKS=["first"]):
        assert ProviderConfig.objects.get(pk=row.pk).get_credential() == "sk-ant-api-x"
    with override_settings(SECRET_KEY="second"), pytest.raises(NotConfigured):
        ProviderConfig.objects.get(pk=row.pk).settings()


@pytest.mark.django_db
def test_every_registered_adapter_has_a_row_and_only_one_is_default():
    assert sorted(ProviderConfig.objects.values_list("slug", flat=True)) == [
        "anthropic",
        "claude_code",
        "fake",
        "litellm",
        "openai",
        "recorded",
    ]
    ProviderConfig.objects.filter(slug="anthropic").update(is_default=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        ProviderConfig.objects.filter(slug="openai").update(is_default=True)
    with pytest.raises(ValidationError, match="must be enabled"):
        ProviderConfig(slug="openai", is_default=True, enabled=False).clean()
    with pytest.raises(ValidationError, match="no adapter"):
        ProviderConfig(slug="nope").clean()


@pytest.mark.django_db
def test_a_model_is_unique_per_provider():
    provider = ProviderConfig.objects.get(slug="anthropic")
    ModelEntry.objects.create(provider=provider, model_id="claude-opus-5-5")
    ModelEntry.objects.create(provider=ProviderConfig.objects.get(slug="claude_code"), model_id="claude-opus-5-5")
    with pytest.raises(IntegrityError), transaction.atomic():
        ModelEntry.objects.create(provider=provider, model_id="claude-opus-5-5")


@pytest.mark.django_db
def test_an_output_schema_is_validated_on_save_and_versioned():
    with pytest.raises(ValidationError, match="not a valid JSON Schema"):
        OutputSchema.objects.create(name="bad", schema={"type": "nonsense"})
    with pytest.raises(ValidationError, match="does not compile"):
        OutputSchema.objects.create(name="bad", schema={"type": "object"}, render_template="{% for %}")
    schema = OutputSchema.objects.create(name="ok", schema={"type": "object"}, render_template="# {{ title }}")
    assert schema.version == 1
    schema.description = "changed"
    schema.save()
    assert schema.version == 1
    schema.schema = {"type": "object", "required": ["title"]}
    schema.save()
    assert schema.version == 2
    assert schema.to_markdown({"title": "Hello"}) == "# Hello"
    assert OutputSchema(name="g", schema={}).to_markdown({"Content": {"Body": ["a", "b"]}, "summary": "c"}) == (
        "## Content\n\n### Body\n\n- a\n- b\n\n## Summary\n\nc"
    )


@pytest.mark.django_db
def test_a_schema_that_refers_outside_itself_is_refused():
    for ref in ("http://169.254.169.254/latest/meta-data", "other.json#/x", "/etc/passwd"):
        with pytest.raises(ValidationError, match="refers only to itself"):
            OutputSchema.objects.create(name="away", schema={"type": "object", "properties": {"a": {"$ref": ref}}})
    with pytest.raises(ValidationError, match="refers only to itself"):
        OutputSchema.objects.create(
            name="away", schema={"prefixItems": [{"$dynamicRef": "https://elsewhere.example/s"}]}
        )
    local = {"$defs": {"a": {"type": "string"}}, "type": "object", "properties": {"a": {"$ref": "#/$defs/a"}}}
    assert OutputSchema.objects.create(name="local", schema=local).version == 1


@pytest.mark.django_db
def test_a_provider_takes_only_the_options_its_adapter_reads():
    claude_code = ProviderConfig.objects.get(slug="claude_code")
    for extra in ({"cli_path": "/tmp/x"}, {"env": {"LD_PRELOAD": "x"}}, {"cwd": "/"}, {"max_turns": "lots"}):
        claude_code.extra = extra
        with pytest.raises(ValidationError, match="extra"):
            claude_code.clean()
    claude_code.extra = {"max_turns": 5, "effort": "low"}
    claude_code.clean()
    ProviderConfig(slug="litellm", extra={"models": ["gemini/flash"]}).clean()


@pytest.mark.django_db
def test_seeding_after_migrate_waits_for_the_ai_tables():
    ProviderConfig.objects.all().delete()
    _seed(None, apps=ProjectState().apps)  # what `migrate ai zero` leaves: no AI models
    assert not ProviderConfig.objects.exists()
    _seed(None)
    assert ProviderConfig.objects.count() == 6


@pytest.mark.django_db
def test_an_assistant_is_validated_on_save():
    with pytest.raises(ValidationError, match="maximum"):
        Assistant.objects.create(name="hot", params={"temperature": 9})
    with pytest.raises(ValidationError, match="Additional properties"):
        Assistant.objects.create(name="odd", params={"seed": 1})
    with pytest.raises(ValidationError, match="read-only tools"):
        Assistant.objects.create(name="writer", tools=["content.propose_edit"])
    anthropic = ProviderConfig.objects.get(slug="anthropic")
    elsewhere = ModelEntry.objects.create(provider=ProviderConfig.objects.get(slug="openai"), model_id="gpt-4o")
    with pytest.raises(ValidationError, match="another provider"):
        Assistant.objects.create(name="mixed", provider=anthropic, model=elsewhere)
    with pytest.raises(ValidationError, match="does not compile"):
        Assistant.objects.create(name="broken", prompt_template="{% if %}")
    ok = Assistant.objects.create(
        name="reader", tools=["content.get_page", "graph.search"], params={"temperature": 0.3, "effort": "low"}
    )
    assert ok.EFFECT == "propose" and ok.public_id and ok.visibility == Visibility.PRIVATE


@pytest.mark.django_db
def test_steps_and_messages_are_numbered_once():
    assistant = Assistant.objects.create(name="a")
    pipeline = Pipeline.objects.create(name="p")
    PipelineStep.objects.create(pipeline=pipeline, position=1, assistant=assistant)
    with pytest.raises(IntegrityError), transaction.atomic():
        PipelineStep.objects.create(pipeline=pipeline, position=1, assistant=assistant)
    conversation = Conversation.objects.create()
    Message.objects.create(conversation=conversation, seq=1, text="hi")
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(conversation=conversation, seq=1, text="again")


@pytest.mark.django_db
def test_visible_to_is_the_one_scope(alice, bob, staff, root_page):
    site = Site.objects.create(hostname="news.example", root_page=root_page, site_name="News")
    mine = Conversation.objects.create(owner=bob, title="bob's")
    theirs = Conversation.objects.create(owner=alice, title="alice's")
    shared = Conversation.objects.create(owner=alice, visibility=Visibility.SHARED, title="shared")
    on_site = Conversation.objects.create(owner=staff, site=site, visibility=Visibility.SITE, title="site")
    elsewhere = Conversation.objects.create(owner=alice, site=site, title="private on the site")

    def titles(user, site=None):
        return set(Conversation.objects.visible_to(user, site).values_list("title", flat=True))

    assert titles(bob) == {mine.title, shared.title}  # bob edits no site
    assert titles(alice) == {theirs.title, shared.title, on_site.title, elsewhere.title}  # alice edits every site
    assert titles(staff) == {c.title for c in Conversation.objects.all()}
    assert titles(None) == set()
    Message.objects.create(conversation=mine, seq=1, text="hello")
    assert Message.objects.visible_to(bob).count() == 1 and Message.objects.visible_to(alice).count() == 0
    # With a site: that site's rows and rows that belong to no site.
    other = Page.get_first_root_node().add_child(title="Other", slug="other")
    other_site = Site.objects.create(hostname="other.example", root_page=other, site_name="Other")
    Conversation.objects.create(owner=alice, site=other_site, title="other site")
    assert "other site" not in titles(alice, site) and "other site" in titles(alice, other_site)
    assert theirs.title in titles(alice, other_site)
    with pytest.raises(ValidationError, match="needs a site"):
        Conversation(owner=alice, visibility=Visibility.SITE).clean()
    assert theirs.can_edit(alice) and not theirs.can_edit(bob) and theirs.can_edit(staff)
    assert not shared.can_edit(bob)


@pytest.mark.django_db
def test_the_bundled_schemas_are_seeded_once_from_byte_copies():
    for name in ("content_detail_schema.json", "news_article_schema.json", "parody_news_article_schema.json"):
        assert (DATA / name).read_bytes() == (PARODYNEWS_SCHEMAS / name).read_bytes()
    assert (DATA / "parody_prompt.md").read_bytes() == (PARODYNEWS_SCHEMAS / "parody_prompt.md").read_bytes()
    bundled = OutputSchema.objects.filter(bundled=True).order_by("name")
    assert [s.name for s in bundled] == ["Content detail", "News article", "Parody news article"]
    assert all(s.visibility == Visibility.SHARED and s.owner is None for s in bundled)
    parody = OutputSchema.objects.get(public_id=stable_id("bundled-schema", "parody-news-article"))
    assert "$ref" not in json.dumps(parody.schema)
    assert parody.schema["properties"]["Metadata"]["title"] == "Content Detail"
    assert parody.schema == bundled_schema("parody_news_article_schema.json")
    writer = Assistant.objects.get(public_id=stable_id("bundled-assistant", "parody-news-writer"))
    assert writer.output_schema == parody and writer.instructions.startswith("**Role:**")
    parody.render_template = "edited by a person"
    parody.save()
    again = import_bundled()
    assert OutputSchema.objects.filter(bundled=True).count() == 3 and Assistant.objects.count() == 1
    parody.refresh_from_db()
    assert parody.render_template == "edited by a person" and len(again["schemas"]) == 3


@pytest.mark.django_db
def test_the_parody_template_renders_an_article():
    parody = OutputSchema.objects.get(public_id=stable_id("bundled-schema", "parody-news-article"))
    article = {
        "Content": {
            "Headline": ["Cat Secedes", "Sofa in Turmoil"],
            "Introduction": ["It began at dawn."],
            "Body": {"DarkHumor": ["Grim."], "Facts": ["Cats sleep 16 hours."], "OptimisticTurn": ["Hope."]},
            "Conclusion": ["Pet your cat."],
        }
    }
    assert parody.to_markdown(article) == (
        "# Cat Secedes\n\n*Sofa in Turmoil*\n\nIt began at dawn.\n\n## Dark humor\n\nGrim.\n\n## Facts\n\n"
        "Cats sleep 16 hours.\n\n## Optimistic turn\n\nHope.\n\n## Conclusion\n\nPet your cat."
    )
