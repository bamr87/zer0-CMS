"""Connecting an X account through X's consent screen — OAuth 2.0's
authorization code with PKCE (S256) — for the platform's channels: the studio's
**Connect with X**.

The platform is the X app: `X_CLIENT_ID` and `X_CLIENT_SECRET`, a confidential
client, so the token calls carry them as HTTP Basic, never in a URL or a form.
The account's owner approves on x.com while signed in as that account; X sends
them back with a code that lives thirty seconds, which the worker trades — with
the verifier only that browser session kept — for a two-hour access token and,
with `offline.access`, a refresh token. Each refresh spends the refresh token
it used and returns a new one, so whoever refreshes keeps the new pair at once
(`session.py`); a repository secret cannot, so the site lane keeps OAuth 1.0a
(`oauth.py`). Nothing here can mint a token for an account whose owner did not
approve.
"""

import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode, urlsplit

# A token, a state and a PKCE pair are OAuth's, not LinkedIn's: one implementation serves both.
from ..linkedin.oauth import STATE_TTL, Token, challenge, new_state, new_verifier
from .client import Client, Error, HTTPError, send

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
# The least a channel needs: publish (X's create asks for tweet.read and users.read beside tweet.write), read its
# own posts and their counts back, learn which account it is, and renew the token while its owner is away.
SCOPES = ("tweet.read", "tweet.write", "users.read", "offline.access")
CODE_TTL = 30  # seconds: X's code is spent or dead by then

__all__ = ["AUTHORIZE_URL", "CODE_TTL", "SCOPES", "STATE_TTL", "OAuth", "challenge", "new_state", "new_verifier"]


class OAuth:
    def __init__(self, client_id: str, client_secret: str, *, transport=send, sleeper=time.sleep):
        self.client_id, self.client_secret = str(client_id or ""), str(client_secret or "")
        if not self.client_id or not self.client_secret:
            raise ValueError("X_CLIENT_ID and X_CLIENT_SECRET are both required for OAuth 2.0")
        self.client = Client(app=(self.client_id, self.client_secret), transport=transport, sleeper=sleeper)

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: str, scopes=SCOPES) -> str:
        parts = urlsplit(str(redirect_uri or ""))
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.fragment:
            raise ValueError("redirect_uri must be an absolute http(s) URL without a fragment")
        if not state or not code_challenge:
            raise ValueError("state and a PKCE challenge are required")
        pairs = [
            ("response_type", "code"),
            ("client_id", self.client_id),
            ("redirect_uri", redirect_uri),
            ("scope", " ".join(scopes)),
            ("state", state),
            ("code_challenge", code_challenge),
            ("code_challenge_method", "S256"),
        ]
        return f"{AUTHORIZE_URL}?{urlencode(pairs, quote_via=quote)}"

    def exchange(self, *, code: str, redirect_uri: str, code_verifier: str, now=None) -> Token:
        if not code:
            raise ValueError("authorization code is empty")
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        return _token(self.client.json("oauth2_token", form=form), now)

    def refresh(self, *, refresh_token: str, now=None) -> Token:
        if not refresh_token:
            raise ValueError("refresh token is empty")
        try:
            data = self.client.json(
                "oauth2_token", form={"grant_type": "refresh_token", "refresh_token": refresh_token}
            )
        except HTTPError as e:
            if e.status not in (400, 401):
                raise
            raise HTTPError(
                e.status, f"X would not renew the token ({e.message}): connect the channel again", code=e.code
            ) from e
        return _token(data, now)

    def revoke(self, token: str, *, hint: str = "refresh_token") -> None:
        self.client.request("oauth2_revoke", form={"token": token, "token_type_hint": hint})


def _token(data: dict, now) -> Token:
    now = now or datetime.now(UTC)
    access = str(data.get("access_token") or "")
    if not access:
        raise Error("X returned no access_token")
    expires = data.get("expires_in")
    return Token(
        access_token=access,
        expires_at=now + timedelta(seconds=int(expires)) if expires else None,
        refresh_token=str(data.get("refresh_token") or "") or None,
        scopes=str(data.get("scope") or "").split(),
    )
