"""The ideas API's shapes (`/api/v2/ideas/`).

An idea is addressed by its UUID public id (`id`); its board, sources, the
message it was brainstormed in and the brief it became are named by theirs, a
page by Wagtail's id — and only a row the requester may see can be named
(`Visible`). What an idea links to is shown only as far as the requester may
see it: the sources they see, the brief if they see it, the page if they can
find it (`ideas.views.IdeaViewSet` prefetches and annotates exactly that), and
saving `source_ids` keeps the links to sources the requester cannot see. Tags
are plain names (taggit underneath). `votes` and `voted` are counted for the
requester. Validation is the models' own, and only an idea's owner changes who
sees it (`research.serializers.CollaborativeSerializer`).
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ai.models import Assistant, Brief, Conversation, Message
from ai.serializers import OWNED, BriefSerializer, MessageSerializer, RunRefSerializer, Visible
from cms.services import visible_pages
from research.models import Source, placement
from research.serializers import CollaborativeSerializer

from .models import Board, Idea
from .services import KINDS, TEMPLATES

PROMOTIONS = ["brief", "article", "book"]


class BoardSerializer(CollaborativeSerializer):
    class Meta:
        model = Board
        fields = [*OWNED, "name", "description"]
        read_only_fields = ["created_at", "updated_at"]


class TagsField(serializers.ListField):
    child = serializers.CharField(max_length=100)

    def to_representation(self, manager):
        return sorted(tag.name for tag in manager.all())


class IdeaSourceSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    title = serializers.CharField()
    url = serializers.CharField()
    kind = serializers.CharField()


class IdeaBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    title = serializers.CharField()
    status = serializers.CharField()


class IdeaPageSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    title = serializers.CharField()


class IdeaSerializer(CollaborativeSerializer):
    board = Visible(Board, allow_null=True, required=False)
    tags = TagsField(required=False)
    sources = serializers.SerializerMethodField(help_text="The linked sources the requester sees.")
    source_ids = Visible(Source, many=True, write_only=True, required=False, source="sources")
    source_message = serializers.SlugRelatedField(slug_field="public_id", read_only=True, allow_null=True)
    brief = serializers.SerializerMethodField(help_text="The brief it became, if the requester sees it.")
    page = serializers.SerializerMethodField(help_text="The draft it became, if the requester can find it.")
    votes = serializers.SerializerMethodField()
    voted = serializers.SerializerMethodField()

    class Meta:
        model = Idea
        fields = [
            *OWNED,
            "board",
            "title",
            "notes",
            "tags",
            "status",
            "origin",
            "url",
            "sources",
            "source_ids",
            "source_message",
            "brief",
            "page",
            "votes",
            "voted",
        ]
        read_only_fields = ["origin", "created_at", "updated_at"]

    def _user(self):
        return getattr(self.context.get("request"), "user", None)

    @extend_schema_field(IdeaSourceSerializer(many=True))
    def get_sources(self, idea):
        seen = getattr(idea, "seen_sources", None)  # IdeaViewSet's prefetch; else asked now
        if seen is None:
            seen = Source.objects.visible_to(self._user()).filter(ideas=idea)
        return IdeaSourceSerializer(seen, many=True).data

    @extend_schema_field(IdeaBriefSerializer(allow_null=True))
    def get_brief(self, idea):
        if idea.brief_id is None:
            return None
        seen = getattr(idea, "brief_seen", None)
        if seen is None:
            seen = Brief.objects.visible_to(self._user()).filter(pk=idea.brief_id).exists()
        return IdeaBriefSerializer(idea.brief).data if seen else None

    @extend_schema_field(IdeaPageSerializer(allow_null=True))
    def get_page(self, idea):
        if idea.page_id is None:
            return None
        seen = getattr(idea, "page_seen", None)
        if seen is None:
            seen = visible_pages(self._user()).filter(pk=idea.page_id).exists()
        return IdeaPageSerializer(idea.page).data if seen else None

    def get_votes(self, idea) -> int:
        return idea.vote_count if hasattr(idea, "vote_count") else idea.votes.count()

    def get_voted(self, idea) -> bool:
        if hasattr(idea, "my_vote"):
            return idea.my_vote
        user = getattr(self.context.get("request"), "user", None)
        return bool(user and idea.votes.filter(user=user).exists())

    def validate(self, attrs):
        held = {key: attrs.pop(key) for key in ("tags", "sources") if key in attrs}  # not fields a model can set
        return {**super().validate(attrs), **held}

    def create(self, validated_data):
        tags = validated_data.pop("tags", None)
        board = validated_data.get("board")
        if board is not None and "visibility" not in self.initial_data:
            validated_data = {**placement(validated_data["owner"], board), **validated_data}
        idea = super().create(validated_data)
        if tags:
            idea.tags.set(tags)
        return idea

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        sources = validated_data.pop("sources", None)
        idea = super().update(instance, validated_data)
        if tags is not None:
            idea.tags.set(tags)
        if sources is not None:  # the links to sources the requester cannot see are not theirs to drop
            unseen = idea.sources.exclude(pk__in=Source.objects.visible_to(self._user()).values("pk"))
            idea.sources.set([*sources, *unseen])
        return idea


class CaptureSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=20_000, help_text="The first line is the title; the rest, the notes.")
    url = serializers.URLField(max_length=2000, required=False, allow_blank=True)
    board = Visible(Board, allow_null=True, required=False, help_text="Else the inbox.")
    tags = serializers.ListField(child=serializers.CharField(max_length=100), required=False)
    template = serializers.CharField(
        required=False, allow_blank=True, help_text=f"Notes from a template: {', '.join(TEMPLATES)}."
    )


class BrainstormSerializer(serializers.Serializer):
    prompt = serializers.CharField(max_length=5000)
    kind = serializers.ChoiceField(choices=list(KINDS), required=False, help_text="angles when not given.")
    count = serializers.IntegerField(min_value=1, max_value=20, required=False, help_text="8 when not given.")
    board = Visible(Board, allow_null=True, required=False)
    conversation = Visible(Conversation, allow_null=True, required=False, help_text="A session to continue.")
    sources = Visible(Source, many=True, required=False, help_text="Research to brainstorm from.")
    assistant = Visible(Assistant, allow_null=True, required=False, help_text="Else the bundled Brainstormer.")


class BrainstormedSerializer(serializers.Serializer):
    conversation = serializers.UUIDField(help_text="The brainstorm session, to continue it.")
    message = MessageSerializer()
    reply = MessageSerializer(help_text="Its `result.ideas` are the ideas to keep, once it is completed.")
    run = RunRefSerializer()


class KeepSerializer(serializers.Serializer):
    message = Visible(Message, help_text="A brainstorm's finished reply.")
    picks = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_null=True,
        help_text="Else all.",
    )
    board = Visible(Board, allow_null=True, required=False, help_text="Else the inbox.")


class KeptSerializer(serializers.Serializer):
    ideas = IdeaSerializer(many=True)


class IdeaRefSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    title = serializers.CharField()
    status = serializers.CharField()


class ClusterSerializer(serializers.Serializer):
    ideas = IdeaRefSerializer(many=True)


class DuplicateSerializer(serializers.Serializer):
    a = IdeaRefSerializer()
    b = IdeaRefSerializer()
    similarity = serializers.FloatField()


class ClustersSerializer(serializers.Serializer):
    model = serializers.CharField(help_text="The embedding model the vectors come from.")
    clusters = ClusterSerializer(many=True)
    duplicates = DuplicateSerializer(many=True, help_text="Pairs similar enough to be one idea; merge them.")
    pending = IdeaRefSerializer(many=True, help_text="Ideas whose vector is still being computed.")


class MergeSerializer(serializers.Serializer):
    other = Visible(Idea, help_text="The idea to fold into this one; it goes.")


class PromoteIdeaSerializer(serializers.Serializer):
    into = serializers.ChoiceField(choices=PROMOTIONS, help_text="What the idea becomes.")
    parent = serializers.IntegerField(required=False, help_text="Where the draft goes (an article, a book).")
    assistant = Visible(Assistant, allow_null=True, required=False, help_text="Who writes the brief.")
    generate = serializers.BooleanField(required=False, help_text="Write the brief now (202, with its run).")


class PromotedIdeaSerializer(serializers.Serializer):
    idea = IdeaSerializer()
    brief = BriefSerializer(allow_null=True)
    page_id = serializers.IntegerField(allow_null=True, help_text="The draft (not live).")
    run = RunRefSerializer(allow_null=True)
