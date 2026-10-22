"""The newsroom API's shapes (`/api/v2/newsroom/`).

Rows travel by their UUID public id (`id`); a related row is named by its
public id too, and only a row the requester may see can be named. Pages,
sites and people go by Wagtail's and Django's own ids, as everywhere else in
the studio's API. drf-spectacular writes these into the committed OpenAPI
document, and `web/packages/api` generates the studio's client from it.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.fields import get_error_detail
from rest_framework.validators import UniqueValidator
from wagtail.models import Page, Site

from agents.models import AgentRun
from ai.models import Assistant, Pipeline
from ai.serializers import RunRefSerializer

from . import services
from .models import Author, Correction, Desk, Front, FrontSlot, Issue, Newsletter, Story, StoryEvent, Subscriber

User = get_user_model()


class Visible(serializers.SlugRelatedField):
    """A related row by public id, out of the rows the requester may see."""

    def __init__(self, model, **kwargs):
        self.model = model
        super().__init__(slug_field="public_id", queryset=model.objects.all(), **kwargs)

    def get_queryset(self):
        user = getattr(self.context.get("request"), "user", None)
        rows = self.model.objects
        return rows.visible_to(user) if hasattr(rows, "visible_to") else rows.all()


def writable(serializer_class):
    """`serializer_class` without its read-only fields: what a client sends to create a row. One component
    serves requests and responses in the document, so without this a create's body would have to carry the
    id and timestamps the generated client marks required."""
    fields = [name for name, field in serializer_class().fields.items() if not field.read_only]
    meta = type("Meta", (serializer_class.Meta,), {"fields": fields})
    return type(serializer_class.__name__.replace("Serializer", "WriteSerializer"), (serializer_class,), {"Meta": meta})


class PersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    name = serializers.SerializerMethodField()

    def get_name(self, user) -> str:
        return user.get_full_name() or user.username


class AuthorRefSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    name = serializers.CharField()
    slug = serializers.CharField()


# ── desks ──────────────────────────────────────────────────────────────────


class DeskSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all())
    section = serializers.PrimaryKeyRelatedField(queryset=Page.objects.all(), help_text="Its stories' pages go here.")
    editors = PersonSerializer(many=True, read_only=True)
    copy_editors = PersonSerializer(many=True, read_only=True)
    editor_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False, source="editors", queryset=User.objects.filter(is_active=True)
    )
    copy_editor_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False, source="copy_editors", queryset=User.objects.filter(is_active=True)
    )
    assistant = Visible(Assistant, required=False, allow_null=True)
    pipeline = Visible(Pipeline, required=False, allow_null=True)
    section_title = serializers.CharField(source="section.title", read_only=True)
    is_editor = serializers.SerializerMethodField(help_text="Whether the requester edits this desk.")

    class Meta:
        model = Desk
        fields = [
            "id",
            "site",
            "name",
            "slug",
            "description",
            "section",
            "section_title",
            "editors",
            "copy_editors",
            "editor_ids",
            "copy_editor_ids",
            "assistant",
            "pipeline",
            "is_editor",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_is_editor(self, desk) -> bool:
        return desk.is_editor(self.context["request"].user)

    def validate(self, attrs):
        candidate = Desk(
            site=attrs.get("site") or self.instance.site, section=attrs.get("section") or self.instance.section
        )
        try:
            candidate.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(get_error_detail(e)) from e
        return attrs


# ── stories ────────────────────────────────────────────────────────────────


class WireItemSerializer(serializers.Serializer):
    """A wire story, a feed entry or a page to pitch from (`services.WireItem`)."""

    url = serializers.URLField()
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    summary = serializers.CharField(required=False, allow_blank=True)
    text = serializers.CharField(required=False, allow_blank=True)
    feed = serializers.CharField(required=False, allow_blank=True, max_length=200)
    published_at = serializers.CharField(required=False, allow_blank=True, max_length=40)


class StoryPageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    live = serializers.BooleanField()
    has_unpublished_changes = serializers.BooleanField(help_text="A draft saved since it last went live.")
    url_path = serializers.CharField()
    first_published_at = serializers.DateTimeField(allow_null=True)


class StorySerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    desk = Visible(Desk)
    desk_name = serializers.CharField(source="desk.name", read_only=True)
    slug = serializers.SlugField(required=False, allow_blank=True, max_length=200)
    # Declared, not left to ModelSerializer: the model field's range validators come from the database
    # (SQLite's 64-bit range, Postgres's smallint), and the committed OpenAPI document must not.
    priority = serializers.ChoiceField(Story.Priority.choices, required=False)
    assignee = PersonSerializer(read_only=True, allow_null=True)
    page = StoryPageSerializer(read_only=True, allow_null=True)
    brief = serializers.UUIDField(source="brief.public_id", read_only=True, allow_null=True)
    source = WireItemSerializer(required=False, write_only=True, help_text="Pitch it from a wire or feed item.")
    wire_item = serializers.JSONField(source="source", read_only=True, help_text="The item it was pitched from.")
    bylines = serializers.SerializerMethodField()
    byline_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False, help_text="Authors, in byline order."
    )
    moves = serializers.SerializerMethodField(help_text="The statuses it may move to next.")

    class Meta:
        model = Story
        fields = [
            "id",
            "desk",
            "desk_name",
            "slug",
            "headline",
            "summary",
            "status",
            "priority",
            "assignee",
            "deadline",
            "slot_date",
            "embargo",
            "page",
            "brief",
            "source",
            "wire_item",
            "breaking",
            "fast_path_reason",
            "bylines",
            "byline_ids",
            "moves",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "breaking", "fast_path_reason", "created_at", "updated_at"]
        extra_kwargs = {"headline": {"required": False}}
        validators: list = []  # the slug is made unique by newsroom.services (a pitch may leave it out)

    @extend_schema_field(AuthorRefSerializer(many=True))
    def get_bylines(self, story):
        return AuthorRefSerializer([row.author for row in story.byline_rows.all()], many=True).data

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(Story.Status.choices)))
    def get_moves(self, story):
        return list(services.MOVES.get(story.status, ()))

    def validate_byline_ids(self, ids):
        user = self.context["request"].user
        found = {a.public_id: a for a in Author.objects.visible_to(user).filter(public_id__in=ids)}
        missing = [str(i) for i in ids if i not in found]
        if missing:
            raise serializers.ValidationError(f"no author {', '.join(missing)}")
        return [found[i] for i in ids]

    def validate(self, attrs):
        if self.instance is not None and "desk" in attrs and attrs["desk"] != self.instance.desk:
            raise serializers.ValidationError({"desk": "a story stays on its desk"})
        return attrs


class StoryEventSerializer(serializers.ModelSerializer):
    actor = PersonSerializer(read_only=True, allow_null=True)
    assignee = PersonSerializer(read_only=True, allow_null=True)

    class Meta:
        model = StoryEvent
        fields = ["created_at", "actor", "action", "from_status", "to_status", "assignee", "note"]


class CorrectionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    created_by = PersonSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Correction
        fields = ["id", "kind", "text", "created_at", "created_by"]


class StoryAIRunSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(services.AI_KINDS)
    run = RunRefSerializer()
    result = serializers.JSONField(allow_null=True, help_text="The structured answer, once the run has succeeded.")
    text = serializers.CharField(help_text="The answer as Markdown, once the run has succeeded.")
    error = serializers.CharField()


class StoryDetailSerializer(StorySerializer):
    events = StoryEventSerializer(many=True, read_only=True)
    corrections = CorrectionSerializer(many=True, read_only=True)
    ai_runs = serializers.SerializerMethodField(help_text="The latest AI run of each kind and its answer.")
    is_editor = serializers.SerializerMethodField(
        help_text="Whether the requester edits the story's desk: its priority, deadline, slot and embargo are theirs."
    )

    class Meta(StorySerializer.Meta):
        fields = [*StorySerializer.Meta.fields, "events", "corrections", "ai_runs", "is_editor"]

    def get_is_editor(self, story) -> bool:
        return story.desk.is_editor(self.context["request"].user)

    @extend_schema_field(StoryAIRunSerializer(many=True))
    def get_ai_runs(self, story):
        user = self.context["request"].user
        runs = {r.pk: r for r in AgentRun.objects.visible_to(user).filter(pk__in=(story.ai or {}).values())}
        out = []
        for kind in services.AI_KINDS:
            run = runs.get((story.ai or {}).get(kind))
            if run is None:
                continue
            done = run.status == AgentRun.SUCCEEDED
            output = run.output or {}
            out.append(
                {
                    "kind": kind,
                    "run": RunRefSerializer(run).data,
                    "result": output.get("json") if done else None,
                    "text": output.get("markdown", "") if done else "",
                    "error": run.error or "",
                }
            )
        return out


class MoveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(Story.Status.choices, help_text="Where the story goes.")
    assignee = serializers.IntegerField(required=False, help_text="To assigned: the person.")
    comment = serializers.CharField(required=False, allow_blank=True, help_text="To copy, or back to drafting.")
    reason = serializers.CharField(
        required=False, allow_blank=True, help_text="Editing to published: why copy is skipped."
    )
    go_live_at = serializers.DateTimeField(required=False, allow_null=True, help_text="To scheduled: when.")
    text = serializers.CharField(required=False, allow_blank=True, help_text="To corrected or updated: the note.")


class AssignSerializer(serializers.Serializer):
    assignee = serializers.IntegerField()
    note = serializers.CharField(required=False, allow_blank=True)


class AskAISerializer(serializers.Serializer):
    kind = serializers.ChoiceField(services.AI_KINDS)
    text = serializers.CharField(required=False, allow_blank=True, help_text="For a correction: what changed.")


class AppliedDraftSerializer(serializers.Serializer):
    story = StoryDetailSerializer()
    page_id = serializers.IntegerField()
    suggestions = serializers.ListField(child=serializers.IntegerField())


# ── authors ────────────────────────────────────────────────────────────────


class AuthorSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    slug = serializers.SlugField(
        required=False,
        allow_blank=True,
        max_length=120,
        validators=[UniqueValidator(queryset=Author.objects.all(), message="another author has this slug")],
        help_text="Made from the name when left empty.",
    )
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Author
        fields = ["id", "name", "slug", "bio", "email", "user", "created_at"]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        if attrs.get("slug"):
            return attrs
        attrs.pop("slug", None)  # an empty slug keeps an author's, and a new author's is made from the name
        if self.instance is None:
            base, n = slugify(attrs.get("name", ""))[:110] or "author", 2
            attrs["slug"] = base
            while Author.objects.filter(slug=attrs["slug"]).exists():
                attrs["slug"], n = f"{base}-{n}", n + 1
        return attrs


class AuthorStorySerializer(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    headline = serializers.CharField()
    url_path = serializers.CharField(source="page.url_path")
    published_at = serializers.DateTimeField(source="page.first_published_at", allow_null=True)


class AuthorPageSerializer(AuthorSerializer):
    """An author page: the author and their published stories, newest first."""

    stories = serializers.SerializerMethodField()

    class Meta(AuthorSerializer.Meta):
        fields = [*AuthorSerializer.Meta.fields, "stories"]

    @extend_schema_field(AuthorStorySerializer(many=True))
    def get_stories(self, author):
        user = self.context["request"].user
        stories = (
            Story.objects.visible_to(user)
            .filter(bylines=author, status__in=services.PUBLISHED, page__live=True)
            .select_related("page")
            .order_by("-page__first_published_at")
        )
        return AuthorStorySerializer(stories, many=True).data


# ── fronts ─────────────────────────────────────────────────────────────────


class FrontSlotSerializer(serializers.ModelSerializer):
    story = Visible(Story, required=False, allow_null=True)
    desk = Visible(Desk, required=False, allow_null=True)

    class Meta:
        model = FrontSlot
        fields = ["rule", "story", "desk"]

    def validate(self, attrs):
        if attrs.get("rule", FrontSlot.Rule.PINNED) == FrontSlot.Rule.PINNED and not attrs.get("story"):
            raise serializers.ValidationError({"story": "a pinned slot names its story"})
        return attrs


class FrontSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all())
    desk = Visible(Desk, required=False, allow_null=True, help_text="A section front's desk; none for the home front.")
    slots = FrontSlotSerializer(many=True, required=False, help_text="In order; replaced as a whole.")

    class Meta:
        model = Front
        fields = ["id", "site", "desk", "name", "slug", "slots", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        named = [
            attrs.get("desk"),
            *(s.get("desk") for s in attrs.get("slots", [])),
            *(s["story"].desk for s in attrs.get("slots", []) if s.get("story")),
        ]
        if any(d is not None and d.site_id != site.pk for d in named):
            raise serializers.ValidationError({"slots": "a front shows stories of its own site"})
        return attrs

    def _slots(self, front, slots):
        if slots is not None:
            front.slots.all().delete()
            FrontSlot.objects.bulk_create(FrontSlot(front=front, position=i, **s) for i, s in enumerate(slots))

    def create(self, validated):
        slots = validated.pop("slots", [])
        front = super().create(validated)
        self._slots(front, slots)
        return front

    def update(self, instance, validated):
        slots = validated.pop("slots", None)
        front = super().update(instance, validated)
        self._slots(front, slots)
        return front


class StoryCardSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    headline = serializers.CharField()
    summary = serializers.CharField()
    status = serializers.ChoiceField(Story.Status.choices)
    desk_name = serializers.CharField(source="desk.name")
    url_path = serializers.CharField(source="page.url_path", allow_null=True, help_text="Null until it has a page.")
    published_at = serializers.DateTimeField(source="page.first_published_at", allow_null=True)


class ResolvedSlotSerializer(serializers.Serializer):
    position = serializers.IntegerField()
    rule = serializers.ChoiceField(FrontSlot.Rule.choices)
    story = StoryCardSerializer(allow_null=True)


# ── newsletters ────────────────────────────────────────────────────────────


class SubscriberCountsSerializer(serializers.Serializer):
    pending = serializers.IntegerField()
    confirmed = serializers.IntegerField()
    unsubscribed = serializers.IntegerField()


class NewsletterSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all())
    subscribers = serializers.SerializerMethodField()

    class Meta:
        model = Newsletter
        fields = ["id", "site", "name", "slug", "description", "from_email", "subscribers", "created_at"]
        read_only_fields = ["created_at"]

    @extend_schema_field(SubscriberCountsSerializer)
    def get_subscribers(self, newsletter):
        counts = {status: 0 for status in ("pending", "confirmed", "unsubscribed")}
        for status in newsletter.subscribers.values_list("status", flat=True):
            counts[status] += 1
        return counts


class IssueSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    newsletter = Visible(Newsletter)
    stories = serializers.SerializerMethodField()
    story_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False, help_text="Its stories, in order."
    )

    class Meta:
        model = Issue
        fields = [
            "id",
            "newsletter",
            "subject",
            "intro",
            "stories",
            "story_ids",
            "status",
            "recipients",
            "sent_at",
            "error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "recipients", "sent_at", "error", "created_at", "updated_at"]

    @extend_schema_field(StoryCardSerializer(many=True))
    def get_stories(self, issue):
        return StoryCardSerializer(services.issue_stories(issue), many=True).data

    def validate(self, attrs):
        if self.instance is not None and "newsletter" in attrs and attrs["newsletter"] != self.instance.newsletter:
            raise serializers.ValidationError({"newsletter": "an issue stays on its newsletter"})
        return attrs

    def validate_story_ids(self, ids):
        user = self.context["request"].user
        found = {
            s.public_id: s for s in Story.objects.visible_to(user).filter(public_id__in=ids).select_related("desk")
        }
        missing = [str(i) for i in ids if i not in found]
        if missing:
            raise serializers.ValidationError(f"no story {', '.join(missing)}")
        return [found[i] for i in ids]


class IssuePreviewSerializer(serializers.Serializer):
    subject = serializers.CharField()
    text = serializers.CharField()
    html = serializers.CharField()


class SubscribeSerializer(serializers.Serializer):
    email = serializers.EmailField()


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField()


class SubscriptionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(Subscriber.Status.choices)
    newsletter = serializers.CharField(source="newsletter.name")
