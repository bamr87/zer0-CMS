"""`/api/v2/account/` (accounts/api.py): a person's API tokens; included from
config/urls.py and, for the OpenAPI document, from ops/openapi.py. Sign-in,
MFA, passkeys and the session list are allauth's headless API at `/_allauth/`."""

from django.urls import path

from . import api

urlpatterns = [
    path("tokens/", api.Tokens.as_view(), name="account-tokens"),
    path("tokens/<uuid:public_id>/", api.Token.as_view(), name="account-token"),
]
