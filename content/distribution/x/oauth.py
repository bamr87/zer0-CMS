"""Connecting an X account: OAuth 1.0a's three legs with a PIN (`oob`), for a
terminal (`manage.py x connect`).

The app asks X for a temporary token, the account's owner opens the authorize
URL signed in as that account and approves, X shows them a PIN, and the app
trades the temporary token and the PIN for the account's token and secret.
Nothing here can mint a token for an account whose owner did not approve. The
app's owner can skip all of it for their own account: the developer console
generates that account's token and secret.
"""

from urllib.parse import parse_qsl, quote

from .client import Error

AUTHORIZE_URL = "https://api.x.com/oauth/authorize"


def _form(response) -> dict:
    return dict(parse_qsl(response.body.decode("utf-8", errors="replace")))


def request_token(client) -> tuple[str, str]:
    data = _form(client.request("request_token", callback="oob"))
    if not data.get("oauth_token") or not data.get("oauth_token_secret"):
        raise Error("X returned no request token")
    return data["oauth_token"], data["oauth_token_secret"]


def authorize_url(token: str) -> str:
    return f"{AUTHORIZE_URL}?oauth_token={quote(token, safe='')}"


def access_token(client, *, token: str, secret: str, pin: str) -> dict:
    if not str(pin or "").strip():
        raise ValueError("the PIN X showed is empty")
    data = _form(client.request("access_token", owner=(token, secret), verifier=str(pin).strip()))
    if not data.get("oauth_token") or not data.get("oauth_token_secret"):
        raise Error("X returned no access token")
    return {
        "access_token": data["oauth_token"],
        "access_token_secret": data["oauth_token_secret"],
        "account": data.get("screen_name") or "",
    }
