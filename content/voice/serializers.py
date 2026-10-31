"""The shapes `/api/v2/sites/<id>/voice/` answers with (voice/views.py), which the
OpenAPI document and the studio's generated client follow. Read-only: a
resolution is composed by voice/services.py, never stored."""

from rest_framework import serializers

from .services import READERS

SCOPES = ["platform", "site", "book", "chapter", "channel"]
READER_KEYS = list(READERS)


class VoiceBanSerializer(serializers.Serializer):
    name = serializers.CharField()
    pattern = serializers.CharField(help_text="A regular expression.")
    flags = serializers.CharField(help_text='"i" (the default) matches any case.')
    level = serializers.ChoiceField(["error", "warning"], help_text="An error blocks; a warning never does.")
    valid = serializers.BooleanField(help_text="False when the guard skips it.")
    why = serializers.CharField(allow_blank=True, help_text="Why the guard skips it.")


class VoiceGuidanceSerializer(serializers.Serializer):
    label = serializers.CharField()
    text = serializers.CharField(help_text="Markdown.")


class VoiceLimitsSerializer(serializers.Serializer):
    max_length = serializers.IntegerField(required=False)
    fold = serializers.IntegerField(required=False, help_text="Where a long post is cut off with '… see more'.")
    max_escaped_length = serializers.IntegerField(required=False, help_text="LinkedIn's limit once escaped.")


class VoiceLayerSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="builtin, brand-rules-<n>, site, aieo, book, chapter or channel.")
    label = serializers.CharField()
    scope = serializers.ChoiceField(SCOPES)
    source = serializers.CharField(help_text="The store that holds it.")
    edit = serializers.CharField(allow_blank=True, help_text="Where a person changes it; blank when it is code.")
    readers = serializers.ListField(child=serializers.ChoiceField(READER_KEYS), help_text="Who reads it today.")
    guidance = VoiceGuidanceSerializer(many=True)
    bans = VoiceBanSerializer(many=True)
    limits = VoiceLimitsSerializer()
    active = serializers.BooleanField(help_text="False when switched off for this page (lifted_by says by whom).")
    lifted_by = serializers.CharField(allow_blank=True)
    hidden = serializers.BooleanField(help_text="True when its content is not the caller's to see (AIEO's context).")


class VoiceToldSerializer(serializers.Serializer):
    style_guides = serializers.ListField(child=serializers.CharField())
    banned = serializers.ListField(child=serializers.CharField(allow_null=True))


class VoicePageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    type = serializers.CharField(help_text="Its page type's name.")


class VoiceChannelSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.CharField()


class VoiceAssistantSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    reads_voice = serializers.BooleanField(help_text="It lists brand.rules among its tools, so its model may ask.")


class VoiceReaderSerializer(serializers.Serializer):
    key = serializers.ChoiceField(READER_KEYS)
    label = serializers.CharField()


class ResolvedVoiceSerializer(serializers.Serializer):
    page = VoicePageSerializer(allow_null=True)
    channel = VoiceChannelSerializer(allow_null=True)
    layers = VoiceLayerSerializer(many=True)
    digest = serializers.CharField(help_text="The sha256 of what the layers say.")
    told = VoiceToldSerializer(help_text="What brand.rules answers an agent working on this page.")
    assistants = VoiceAssistantSerializer(many=True, help_text="The assistants the caller may run on this site.")
    readers = VoiceReaderSerializer(many=True)


class VoiceTestRequestSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=20_000, trim_whitespace=False)
    page = serializers.IntegerField(required=False, allow_null=True)
    channel = serializers.UUIDField(required=False, allow_null=True)


class VoiceFindingSerializer(serializers.Serializer):
    level = serializers.ChoiceField(["error", "warning", "info"])
    message = serializers.CharField()


class VoiceTestSerializer(serializers.Serializer):
    findings = VoiceFindingSerializer(many=True)
    digest = serializers.CharField()
