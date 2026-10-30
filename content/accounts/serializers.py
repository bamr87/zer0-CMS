"""The shapes of `/api/v2/account/` (accounts/api.py): a person's API tokens as
the account menu shows them, the request that issues one, and the one answer
that carries the raw token — shown once, never again."""

from rest_framework import serializers

from .models import SCOPES
from .services import DEFAULT_DAYS, MAX_DAYS

TOKEN_STATES = ("active", "expired", "revoked")


class UserTokenSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    name = serializers.CharField()
    prefix = serializers.CharField(help_text="The token's first characters, to tell it apart; never the token.")
    scopes = serializers.ListField(child=serializers.ChoiceField(choices=SCOPES))
    state = serializers.ChoiceField(choices=TOKEN_STATES)
    created_at = serializers.DateTimeField()
    last_used_at = serializers.DateTimeField(allow_null=True, help_text="To within a few minutes.")
    expires_at = serializers.DateTimeField(allow_null=True, help_text="Null: it never expires.")
    revoked_at = serializers.DateTimeField(allow_null=True)
    current = serializers.BooleanField(help_text="This request was made with it.")


class IssueTokenSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, help_text="Where it is used, e.g. “VS Code on my laptop”.")
    days = serializers.IntegerField(
        min_value=1, max_value=MAX_DAYS, default=DEFAULT_DAYS, help_text="It expires after this many days."
    )
    scopes = serializers.MultipleChoiceField(
        choices=SCOPES, default=list(SCOPES), help_text="`read`, and `write` to change anything; read is always in."
    )
    superuser = serializers.BooleanField(
        default=False, help_text="A superuser says yes to a token that carries every permission."
    )


class IssuedTokenSerializer(serializers.Serializer):
    token = UserTokenSerializer()
    raw = serializers.CharField(help_text="The token itself — shown this once; only its hash is stored.")
