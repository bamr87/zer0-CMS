"""The shapes `/api/v2/switches/` reads and writes (switches/views.py), so the OpenAPI document and the studio's
generated client follow them. The credential is write-only: it goes in, and only `has_credential` comes back."""

from rest_framework import serializers

from jobs.serializers import JobSerializer

from . import github

SEMANTICS = [("opt_in", "opt_in"), ("opt_out", "opt_out")]
ON_OFF = [("on", "on"), ("off", "off")]
EFFECTIVE = [("on", "on"), ("off", "off"), ("unknown", "unknown")]
LIVE_STATES = [(v, v) for v in ("set", "unset", "unreadable", "none")]
MAP_STATES = [(v, v) for v in ("on", "off", "unverified")]
ACTIONS = [(v, v) for v in ("update", "create", "none", "refused", "unreadable")]
SCOPES = [("switch", "switch"), ("outlet", "outlet")]
HUB_SOURCES = [("github", "github"), ("checkout", "checkout")]


class SwitchHoldSerializer(serializers.Serializer):
    kind = serializers.CharField(required=False)
    name = serializers.CharField(required=False)
    value = serializers.CharField(required=False)
    source = serializers.CharField(required=False)
    lift = serializers.CharField(required=False)


class SwitchSerializer(serializers.Serializer):
    loop = serializers.CharField(allow_null=True, help_text="The hub map's id for the loop; null: not in the map.")
    workflow = serializers.CharField(allow_null=True)
    variable = serializers.CharField(allow_null=True, help_text="The repository variable that gates it, if any.")
    gate = serializers.CharField(help_text="repo_variable, none, env, fleet_config or planned (the map's gate kind).")
    semantics = serializers.ChoiceField(SEMANTICS, allow_null=True, help_text="null: not in the map, so unknown.")
    default = serializers.ChoiceField(ON_OFF, allow_null=True)
    in_map = serializers.BooleanField()
    live = serializers.CharField(allow_null=True, help_text="The variable's value now; null when unset or unread.")
    live_state = serializers.ChoiceField(LIVE_STATES)
    effective = serializers.ChoiceField(EFFECTIVE)
    why = serializers.CharField()
    map_state = serializers.ChoiceField(MAP_STATES, allow_null=True)
    verified = serializers.BooleanField()
    reason = serializers.CharField(allow_null=True)
    set_by = serializers.CharField(allow_null=True)
    set_at = serializers.CharField(allow_null=True)
    drift = serializers.BooleanField(help_text="The live value disagrees with what the map records: record it there.")
    hold = SwitchHoldSerializer(
        allow_null=True, help_text="A code-level hold that idles the workflow whatever the variable."
    )
    flippable = serializers.BooleanField()
    merge_authority = serializers.BooleanField(help_text="It decides what merges without a person: off only, here.")


class SwitchOutletSerializer(serializers.Serializer):
    repo = serializers.CharField()
    readable = serializers.BooleanField()
    error = serializers.CharField(allow_blank=True)
    switches = SwitchSerializer(many=True)


class SwitchHubSerializer(serializers.Serializer):
    repo = serializers.CharField()
    path = serializers.CharField()
    ref = serializers.CharField()
    read_from = serializers.ChoiceField(HUB_SOURCES, help_text="GitHub, or the hub checkout ZER0_HUB_CHECKOUT names.")
    read = serializers.BooleanField()
    error = serializers.CharField(allow_blank=True)


class SwitchCredentialSerializer(serializers.Serializer):
    set = serializers.BooleanField()
    error = serializers.CharField(allow_blank=True)
    needs = serializers.CharField(help_text="What the platform needs to read and set the variables.")


class SwitchBoardSerializer(serializers.Serializer):
    hub = SwitchHubSerializer()
    credential = SwitchCredentialSerializer()
    outlets = SwitchOutletSerializer(many=True)


class SwitchConfigSerializer(serializers.Serializer):
    outlets = serializers.ListField(
        child=serializers.CharField(max_length=140), max_length=20, required=False, help_text="owner/name each."
    )
    credential = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=400,
        style={"input_type": "password"},
        help_text="Write-only; encrypted at rest. An empty string removes it.",
    )
    has_credential = serializers.BooleanField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def validate_outlets(self, value):
        bad = [repo for repo in value if not github.REPO.match(repo)]
        if bad:
            raise serializers.ValidationError(f"not a repository (owner/name): {', '.join(bad)}")
        if len({repo.lower() for repo in value}) != len(value):
            raise serializers.ValidationError("an outlet is listed twice")
        return value


class SwitchFlipSerializer(serializers.Serializer):
    repo = serializers.CharField(help_text="The outlet, owner/name.")
    switch = serializers.CharField(
        required=False, allow_null=True, default=None, help_text="One variable; leave it out for every switch."
    )
    target = serializers.ChoiceField(ON_OFF)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)


class SwitchApplySerializer(SwitchFlipSerializer):
    reason = serializers.CharField(max_length=500, help_text="Why; recorded with the flip.")
    digest = serializers.CharField(help_text="The preview's digest: the flip is refused if anything changed since.")
    confirm = serializers.BooleanField(help_text="Must be true: the person confirmed the preview.")

    def validate_confirm(self, value):
        if value is not True:
            raise serializers.ValidationError("a flip is applied only when confirmed")
        return value


class SwitchChangeSerializer(serializers.Serializer):
    name = serializers.CharField()
    loops = serializers.ListField(child=serializers.CharField())
    in_map = serializers.BooleanField()
    current = serializers.CharField(allow_null=True)
    current_state = serializers.ChoiceField(LIVE_STATES)
    new = serializers.CharField()
    action = serializers.ChoiceField(ACTIONS)
    why = serializers.CharField()
    hold = SwitchHoldSerializer(allow_null=True)


class SwitchPreviewSerializer(serializers.Serializer):
    repo = serializers.CharField()
    scope = serializers.ChoiceField(SCOPES)
    switch = serializers.CharField(allow_null=True)
    target = serializers.ChoiceField(ON_OFF)
    reason = serializers.CharField(allow_blank=True)
    changes = SwitchChangeSerializer(many=True)
    writes = serializers.IntegerField(help_text="How many variables a flip would write.")
    digest = serializers.CharField()
    credential = SwitchCredentialSerializer()
    hub = SwitchHubSerializer()


class SwitchFlipAcceptedSerializer(serializers.Serializer):
    job = JobSerializer()
