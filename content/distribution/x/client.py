"""The one gateway to X, and the credentials it signs with.

`Client.request` takes a call id from `plan`, never a URL: it refuses a call the
plan does not declare, signs the request with OAuth 1.0a (HMAC-SHA1, oauthlib's
signer, so no signature is hand-rolled) — the app's key and secret, and the
account's token and secret — sends it with httpx and maps a non-2xx answer to
`HTTPError`. OAuth 1.0a tokens do not expire until their owner revokes them,
which is what a CI secret needs: X's OAuth 2.0 tokens last two hours and their
refresh tokens are spent on use, which a repository secret cannot follow.

Retries are LinkedIn's (`linkedin/client.py`), for the same reason: a read is
retried on 429, 5xx and a dropped connection, honouring `retry-after` or X's
`x-rate-limit-reset`; a write and the token calls only on 429, which X sends
before acting — a 5xx or a dropped socket after `POST /2/tweets` may mean the
post exists. An error's message is built from X's error body, never from the
request, and every credential the client holds is scrubbed out of it.
"""

import json as jsonlib
import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx
from oauthlib.oauth1 import Client as Signer

from ..linkedin.client import Response
from . import plan

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
NAMES = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")


class Error(Exception):
    """Anything the X lane cannot do; the message is safe to show a person."""


class Refused(Error):
    """A request the declared plan does not contain, or one with no credential to sign it. Raised before any socket
    opens."""


class NetworkError(Error):
    """The socket could not be opened, or the peer went away."""


class HTTPError(Error):
    """A non-2xx answer from X, after the retries a call is allowed."""

    def __init__(self, status: int, message: str, *, code=None, body=None):
        self.status, self.code, self.body = status, code, body
        super().__init__(f"HTTP {status}: {message}" + (f" ({code})" if code else ""))

    @property
    def unauthorized(self) -> bool:
        return self.status == 401

    @property
    def forbidden(self) -> bool:
        return self.status == 403


@dataclass
class Credentials:
    """The app's key and secret (the X developer console's "API Key and Secret") and the account's token and secret
    ("Access Token and Secret", or `manage.py x connect`)."""

    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    access_token_secret: str = ""

    @classmethod
    def from_env(cls, env) -> "Credentials":
        return cls(*(str(env.get(name) or "").strip() for name in NAMES))

    @property
    def app(self) -> bool:
        return bool(self.api_key and self.api_secret)

    @property
    def complete(self) -> bool:
        return self.app and bool(self.access_token and self.access_token_secret)

    def present(self) -> dict:
        """Names only — the values never leave through a report."""
        values = (self.api_key, self.api_secret, self.access_token, self.access_token_secret)
        return {name: bool(value) for name, value in zip(NAMES, values, strict=True)}


def send(verb: str, url: str, headers: dict, body) -> Response:
    """One HTTPS request; `Client` owns signing, retries and error mapping."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != plan.API_HOST:
        raise Refused(f"only https to {plan.API_HOST} is allowed: {parts.scheme}://{parts.hostname}")
    try:
        with httpx.Client(timeout=TIMEOUT) as http:
            answer = http.request(verb, url, headers=headers, content=body)
    except httpx.TransportError as e:
        raise NetworkError(f"{parts.hostname}: {type(e).__name__}") from e
    return Response(answer.status_code, {k.lower(): v for k, v in answer.headers.items()}, answer.content)


class Client:
    def __init__(self, credentials: Credentials, *, sleeper=time.sleep, transport=send, clock=time.time):
        self.credentials = credentials
        self.sleeper, self.transport, self.clock = sleeper, transport, clock
        c = credentials
        self.secrets = [s for s in (c.api_key, c.api_secret, c.access_token, c.access_token_secret) if len(s) >= 8]

    def request(self, call_id, *, path=None, query=(), json=None, owner=None, callback=None, verifier=None):
        """Perform a declared call. `path` fills the declared path's `{placeholders}`; `query` is (key, value) pairs;
        `owner` is a (token, secret) pair in place of the account's, for the second step of connecting."""
        call = plan.fetch(call_id)
        c = self.credentials
        if not c.app:
            raise Refused("no X app credentials (X_API_KEY and X_API_SECRET)")
        token, secret = owner or (c.access_token, c.access_token_secret)
        if not call.oauth and not (token and secret):
            raise Refused("no X account token (X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET): connect the account")
        target = self._url(call, path or {}, query)
        body = jsonlib.dumps(json, separators=(",", ":"), ensure_ascii=False).encode() if json is not None else None
        signer = Signer(
            c.api_key,
            client_secret=c.api_secret,
            resource_owner_key=token or None,
            resource_owner_secret=secret or None,
            callback_uri=callback,
            verifier=verifier,
        )
        _, headers, _ = signer.sign(target, http_method=call.verb)  # a JSON body is not part of an OAuth 1.0a signature
        headers = {**headers, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        return self._send(call, target, headers, body)

    def json(self, call_id, **options) -> dict:
        data = self.request(call_id, **options).json()
        return data if isinstance(data, dict) else {}

    def _send(self, call, target, headers, body) -> Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.transport(call.verb, target, headers, body)
            except NetworkError as e:
                if call.write or call.oauth or attempt >= MAX_ATTEMPTS:
                    raise HTTPError(0, self.scrub(str(e))) from e
                self.sleeper(self._backoff(attempt, None))
                continue
            if response.success:
                return response
            retry = response.status == 429 if (call.write or call.oauth) else response.status in RETRY_STATUSES
            if not retry or attempt >= MAX_ATTEMPTS:
                raise self._error(response)
            self.sleeper(self._backoff(attempt, response))

    def _backoff(self, attempt, response) -> int:
        after = response.header("retry-after") if response is not None else ""
        if after.isdigit():
            return min(int(after), 60)
        reset = response.header("x-rate-limit-reset") if response is not None else ""
        if reset.isdigit():
            return max(1, min(int(reset) - int(self.clock()), 60))
        return min(2**attempt, 30)

    @staticmethod
    def _url(call, params, query) -> str:
        def fill(match):
            value = str(params.get(match.group(1)) or "")
            if not plan.POST_ID.match(value):
                raise ValueError(f"{call.id} needs a numeric {match.group(1)}, got {value!r}")
            return value

        path = re.sub(r"\{(\w+)\}", fill, call.path)
        if plan.forbidden_path(path):
            raise Refused(f"{call.id} resolves to a forbidden path: {path}")
        qs = urlencode(list(query))
        return f"https://{call.host}{path}{'?' + qs if qs else ''}"

    def _error(self, response) -> HTTPError:
        data = response.json()
        data = data if isinstance(data, dict) else {}
        errors = data.get("errors") if isinstance(data.get("errors"), list) else []
        first = errors[0] if errors and isinstance(errors[0], dict) else {}
        message = data.get("detail") or data.get("title") or first.get("message") or data.get("message")
        message = message or response.body.decode("utf-8", errors="replace").strip()[:300] or "request failed"
        code = first.get("code") or data.get("code") or data.get("type")
        return HTTPError(response.status, self.scrub(str(message)), code=code, body=data)

    def scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        return text
