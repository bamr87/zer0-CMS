"""Distribution's API shapes (`/api/v2/distribution/`).

Rows travel by their UUID public id (`id`); a page by Wagtail's id, a site by
Wagtail's site id, a story and a newsletter by the newsroom's public ids. A
channel's credential is write-only: `credentials` goes in, is encrypted, and
only `has_credential` ever comes back. Every serializer's name starts with
`Distribution`, so its OpenAPI component is unique across the platform.
"""

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from wagtail.models import Site

from newsroom.models import Newsletter, Story
from newsroom.serializers import Visible

from . import services
from .models import POST_KINDS, SECRETS, Channel, DistributionPost, LedgerEntry, Statistic

LEVELS = [("error", "error"), ("warning", "warning"), ("info", "info")]


class DistributionChannelSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all())
    site_name = serializers.CharField(source="site.site_name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    newsletter = Visible(Newsletter, required=False, allow_null=True)
    newsletter_name = serializers.CharField(source="newsletter.name", read_only=True, default="")
    settings = serializers.JSONField(required=False, help_text="What the kind needs; never a secret (README).")
    credentials = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        write_only=True,
        required=False,
        help_text="The kind's secret (linkedin: access_token, refresh_token; wordpress: application_password; "
        "github_pr: token). Encrypted at rest and never returned.",
    )
    has_credential = serializers.SerializerMethodField()
    connecting = serializers.SerializerMethodField(help_text="LinkedIn came back; the worker is exchanging the code.")
    deployment_armed = serializers.SerializerMethodField(help_text="The deployment publishes to this kind.")
    secret_fields = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = Channel
        fields = [
            "id",
            "site",
            "site_name",
            "kind",
            "kind_label",
            "name",
            "settings",
            "newsletter",
            "newsletter_name",
            "credentials",
            "has_credential",
            "secret_fields",
            "connecting",
            "account",
            "scopes",
            "connected_at",
            "expires_at",
            "refresh_expires_at",
            "checked_at",
            "last_check",
            "last_error",
            "auto_draft",
            "armed",
            "deployment_armed",
            "can_manage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "account",
            "scopes",
            "connected_at",
            "expires_at",
            "refresh_expires_at",
            "checked_at",
            "last_check",
            "last_error",
            "created_at",
            "updated_at",
        ]

    def get_has_credential(self, row) -> bool:
        return bool(row.credential_encrypted)

    def get_connecting(self, row) -> bool:
        return bool(row.pending_encrypted)

    def get_deployment_armed(self, row) -> bool:
        return row.kind in settings.DISTRIBUTION_ARMED

    def get_secret_fields(self, row) -> list[str]:
        return list(SECRETS[row.kind])

    def get_can_manage(self, row) -> bool:
        return services.may_manage(self.context["request"].user)

    def save(self, **kwargs):
        user = self.context["request"].user
        data = {**self.validated_data}
        credentials = data.pop("credentials", None)
        channel = services.save_channel(user, channel=self.instance, **data)
        if credentials:
            channel = services.set_credentials(channel, user, credentials)
        self.instance = channel
        return channel


class DistributionBlockerSerializer(serializers.Serializer):
    kind = serializers.CharField()
    message = serializers.CharField()


class DistributionFindingSerializer(serializers.Serializer):
    level = serializers.ChoiceField(choices=LEVELS)
    message = serializers.CharField()


class DistributionPostSerializer(serializers.ModelSerializer):
    """A post as the queue shows it; a person composes one with `DistributionCompose` and changes its text with
    `DistributionPostEdit`."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    channel = serializers.UUIDField(source="channel.public_id", read_only=True)
    channel_name = serializers.CharField(source="channel.name", read_only=True)
    channel_kind = serializers.CharField(source="channel.kind", read_only=True)
    page = serializers.IntegerField(source="page_id", read_only=True, allow_null=True)
    page_title = serializers.CharField(source="page.title", read_only=True, default="")
    story = serializers.UUIDField(source="story.public_id", read_only=True, default=None)
    guard = DistributionFindingSerializer(many=True, read_only=True)
    created_by = serializers.CharField(source="created_by.username", read_only=True, default=None)
    approved_by = serializers.CharField(source="approved_by.username", read_only=True, default=None)
    can_publish = serializers.SerializerMethodField()

    class Meta:
        model = DistributionPost
        fields = [
            "id",
            "channel",
            "channel_name",
            "channel_kind",
            "page",
            "page_title",
            "story",
            "kind",
            "title",
            "description",
            "commentary",
            "link",
            "status",
            "guard",
            "origin",
            "external_id",
            "external_url",
            "error",
            "notes",
            "reason",
            "created_by",
            "approved_by",
            "approved_at",
            "attempted_at",
            "published_at",
            "can_publish",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_can_publish(self, row) -> bool:
        return services.may_publish(row, self.context["request"].user)


class DistributionPostDetailSerializer(DistributionPostSerializer):
    """A post with what publishing it now would meet: every blocker, and for LinkedIn the exact payload."""

    blockers = serializers.SerializerMethodField()
    payload = serializers.SerializerMethodField()

    class Meta(DistributionPostSerializer.Meta):
        fields = [*DistributionPostSerializer.Meta.fields, "blockers", "payload"]
        read_only_fields = fields

    def _preview(self, row):
        if getattr(self, "_seen", (None,))[0] != row.pk:
            self._seen = (row.pk, services.preview(row))
        return self._seen[1]

    @extend_schema_field(DistributionBlockerSerializer(many=True))
    def get_blockers(self, row) -> list[dict]:
        return [b.as_dict() for b in self._preview(row).blockers]

    @extend_schema_field({"type": "object", "additionalProperties": True, "nullable": True})
    def get_payload(self, row) -> dict | None:
        return self._preview(row).payload


class DistributionComposeSerializer(serializers.Serializer):
    channel = Visible(Channel)
    page = serializers.IntegerField(required=False, allow_null=True)
    story = Visible(Story, required=False, allow_null=True)
    kind = serializers.ChoiceField(choices=POST_KINDS, default="article")
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    commentary = serializers.CharField(required=False, allow_blank=True)


class DistributionPostEditSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=POST_KINDS, required=False)
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    commentary = serializers.CharField(required=False, allow_blank=True)


class DistributionRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class DistributionPublishSerializer(serializers.Serializer):
    force = serializers.BooleanField(
        default=False,
        help_text="Past a guard error, a ledger entry or an unconfirmed attempt — never approval or arming.",
    )


class DistributionRecordSerializer(serializers.Serializer):
    urn = serializers.CharField(help_text="What it was published as: a LinkedIn post URN, a post id, a URL.")


class DistributionConnectSerializer(serializers.Serializer):
    url = serializers.URLField(read_only=True, help_text="LinkedIn's consent screen, for the account's owner.")


class DistributionLedgerFileSerializer(serializers.Serializer):
    filename = serializers.CharField(read_only=True)
    content = serializers.CharField(help_text="The ledger as a file: Python's json.dump, sorted, indented 2, ASCII.")


class DistributionLedgerImportSerializer(serializers.Serializer):
    added = serializers.IntegerField()
    kept = serializers.IntegerField()
    skipped = serializers.IntegerField()


class DistributionStatisticSerializer(serializers.ModelSerializer):
    class Meta:
        model = Statistic
        fields = ["day", "impressions", "clicks", "reactions", "comments", "shares", "engagements", "fetched_at"]


class DistributionLedgerEntrySerializer(serializers.ModelSerializer):
    channel = serializers.UUIDField(source="channel.public_id", read_only=True)
    channel_name = serializers.CharField(source="channel.name", read_only=True)
    channel_kind = serializers.CharField(source="channel.kind", read_only=True)
    post = serializers.UUIDField(source="post.public_id", read_only=True, default=None)
    page = serializers.IntegerField(source="post.page_id", read_only=True, default=None)
    latest = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "channel",
            "channel_name",
            "channel_kind",
            "key",
            "urn",
            "state",
            "kind",
            "posted_at",
            "attempted_at",
            "error",
            "source_file",
            "post",
            "page",
            "latest",
        ]

    @extend_schema_field(DistributionStatisticSerializer(allow_null=True))
    def get_latest(self, row):
        latest = next(iter(row.statistics.all()), None)
        return DistributionStatisticSerializer(latest).data if latest else None
