"""The shapes `/api/v2/jobs/` answers with (jobs/views.py), which the OpenAPI
document and the studio's generated client follow."""

from rest_framework import serializers

from .models import Job, JobArtifact, JobLine


class JobLineSerializer(serializers.ModelSerializer):
    # A job writes its log; the API only reads it. Read-only fields also take no
    # validator from the model, whose PositiveIntegerField bound is the database's
    # integer range (64-bit on SQLite, 32-bit on Postgres), so the OpenAPI
    # document is the same whichever database generates it.
    class Meta:
        model = JobLine
        fields = ["idx", "at", "level", "text"]
        read_only_fields = fields


class JobArtifactSerializer(serializers.ModelSerializer):
    size = serializers.SerializerMethodField(help_text="Characters.")

    class Meta:
        model = JobArtifact
        fields = ["name", "media_type", "size"]

    def get_size(self, artifact) -> int:
        return len(artifact.content)


class JobSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    status = serializers.ChoiceField(Job.Status.choices)
    is_final = serializers.BooleanField(help_text="It has ended: succeeded, failed or cancelled.")
    site = serializers.IntegerField(source="site_id", allow_null=True, help_text="The Wagtail site it works on.")
    created_by = serializers.SlugRelatedField(slug_field="username", read_only=True, allow_null=True)
    artifacts = JobArtifactSerializer(many=True)

    class Meta:
        model = Job
        fields = [
            "id",
            "kind",
            "status",
            "is_final",
            "site",
            "params",
            "created_by",
            "created_at",
            "started_at",
            "finished_at",
            "cancel_requested",
            "result",
            "error",
            "artifacts",
        ]


class JobDetailSerializer(JobSerializer):
    lines = JobLineSerializer(many=True, help_text="The whole log so far, in order.")

    class Meta(JobSerializer.Meta):
        fields = [*JobSerializer.Meta.fields, "lines"]
