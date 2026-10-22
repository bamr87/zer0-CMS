"""LinkedIn's three-legged OAuth: the consent URL (with `state` and a PKCE
challenge), the code exchange, the refresh grant, token introspection, and the
member behind a token.

Each account is authorized by its own owner — a member for their profile, a
page administrator for the pages they administer — and nothing here can mint a
token for anyone who did not consent. The client secret travels only in a form
body to www.linkedin.com, never in a URL, and never in an error message.
LinkedIn issues access tokens for 60 days; refresh tokens (365 days) only to
apps it has enabled for programmatic refresh — without one the owner re-runs
consent, which LinkedIn skips while they are signed in and the old token lives.
"""

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import ceil
from urllib.parse import urlsplit

from . import restli
from .client import Client, Error, send

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
STATE_TTL = 600
# The least each author kind needs: publish, read its own posts back, and read their aggregate statistics.
DEFAULT_SCOPES = {
    "organization": ("w_organization_social", "r_organization_social", "rw_organization_admin"),
    "person": ("openid", "profile", "w_member_social", "r_member_postAnalytics"),
}


def _days_left(expires_at, now) -> int | None:
    return ceil((expires_at - now).total_seconds() / 86400) if expires_at else None


@dataclass
class Token:
    access_token: str
    expires_at: datetime | None = None
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None
    scopes: list = field(default_factory=list)

    def days_left(self, now=None) -> int | None:
        return _days_left(self.expires_at, now or datetime.now(UTC))


@dataclass
class Introspection:
    active: bool
    status: str = ""
    scopes: list = field(default_factory=list)
    expires_at: datetime | None = None
    created_at: datetime | None = None
    authorized_at: datetime | None = None
    auth_type: str = ""

    def days_left(self, now=None) -> int | None:
        return _days_left(self.expires_at, now or datetime.now(UTC))


def new_state() -> str:
    return secrets.token_urlsafe(32)


def state_matches(expected, given) -> bool:
    a, b = str(expected or ""), str(given or "")
    return bool(a) and len(a) == len(b) and hmac.compare_digest(a, b)


def new_verifier() -> str:
    """A PKCE code verifier (RFC 7636): 43 to 128 unreserved characters."""
    return secrets.token_urlsafe(64)[:96]


def challenge(verifier: str) -> str:
    """The S256 code challenge for a verifier."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def scopes_for(author_type) -> tuple:
    return DEFAULT_SCOPES.get(str(author_type or ""), DEFAULT_SCOPES["organization"])


def member(client: Client) -> dict:
    """The member behind a token that carries `openid profile`."""
    data = client.json("userinfo")
    sub = str(data.get("sub") or "")
    if not sub:
        raise Error("userinfo returned no member id")
    return {"urn": f"urn:li:person:{sub}", "name": str(data.get("name") or "")}


def _scopes(value) -> list:
    return [s for s in str(value or "").replace(",", " ").split() if s]


def _epoch(value):
    return datetime.fromtimestamp(int(value), UTC) if value is not None else None


class OAuth:
    def __init__(self, client_id: str, client_secret: str, *, transport=send, sleeper=time.sleep):
        self.client_id, self.client_secret = str(client_id or ""), str(client_secret or "")
        if not self.client_id or not self.client_secret:
            raise ValueError("LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET are both required for OAuth")
        self.client = Client(transport=transport, sleeper=sleeper, secrets=[self.client_secret])

    def authorize_url(self, *, redirect_uri: str, state: str, scopes, code_challenge: str | None = None) -> str:
        self._check_redirect(redirect_uri)
        if not state:
            raise ValueError("state is required")
        if not scopes:
            raise ValueError("at least one scope is required")
        pairs = [
            ("response_type", "code"),
            ("client_id", self.client_id),
            ("redirect_uri", redirect_uri),
            ("state", state),
            ("scope", " ".join(scopes)),
        ]
        if code_challenge:
            pairs += [("code_challenge", code_challenge), ("code_challenge_method", "S256")]
        return f"{AUTHORIZE_URL}?{restli.query(pairs)}"

    def exchange(self, *, code: str, redirect_uri: str, code_verifier: str | None = None, now=None) -> Token:
        if not code:
            raise ValueError("authorization code is empty")
        fields = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        if code_verifier:
            fields["code_verifier"] = code_verifier
        return self._token(self._post_token(fields), now)

    def refresh(self, *, refresh_token: str, now=None) -> Token:
        if not refresh_token:
            raise ValueError("refresh token is empty")
        return self._token(self._post_token({"grant_type": "refresh_token", "refresh_token": refresh_token}), now)

    def introspect(self, token: str) -> Introspection:
        """Needs no scope and no bearer: the app's own credentials in the body."""
        form = {"client_id": self.client_id, "client_secret": self.client_secret, "token": token}
        data = self.client.json("introspect", auth=False, form=form)
        return Introspection(
            active=data.get("active") is True,
            status=str(data.get("status") or ""),
            scopes=_scopes(data.get("scope")),
            expires_at=_epoch(data.get("expires_at")),
            created_at=_epoch(data.get("created_at")),
            authorized_at=_epoch(data.get("authorized_at")),
            auth_type=str(data.get("auth_type") or ""),
        )

    def _post_token(self, fields: dict) -> dict:
        form = {**fields, "client_id": self.client_id, "client_secret": self.client_secret}
        return self.client.json("token", auth=False, form=form)

    @staticmethod
    def _token(data: dict, now) -> Token:
        now = now or datetime.now(UTC)
        access = str(data.get("access_token") or "")
        if not access:
            raise Error("LinkedIn returned no access_token")
        expires, refresh_expires = data.get("expires_in"), data.get("refresh_token_expires_in")
        return Token(
            access_token=access,
            expires_at=now + timedelta(seconds=int(expires)) if expires else None,
            refresh_token=str(data.get("refresh_token") or "") or None,
            refresh_expires_at=now + timedelta(seconds=int(refresh_expires)) if refresh_expires else None,
            scopes=_scopes(data.get("scope")),
        )

    @staticmethod
    def _check_redirect(uri):
        try:
            parts = urlsplit(str(uri or ""))
        except ValueError as e:
            raise ValueError("redirect_uri is not a valid URL") from e
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.fragment:
            raise ValueError("redirect_uri must be an absolute http(s) URL without a fragment")
