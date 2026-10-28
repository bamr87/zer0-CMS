"""The one gateway to LinkedIn.

`Client.request` takes a call id from `plan`, never a URL, and does four things
in order: refuses a call the plan does not declare (or a scope the token is
known not to hold), builds the URL and the headers LinkedIn's versioned API
requires, sends it with httpx, and maps a non-2xx answer to `HTTPError`.

Retries are deliberately asymmetric. A read is retried on 429, 5xx and a
dropped connection, honouring `Retry-After`. A write — creating a post,
uploading an image — and the token call are retried only on 429, which LinkedIn
sends before doing anything: a 5xx or a dropped socket after a POST may mean
the post exists, and retrying it is how a page publishes the same thing twice.
An error's message is built from LinkedIn's error body, never from the request,
and every credential the client holds is scrubbed out of it.
"""

import json as jsonlib
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

import httpx

from . import plan, restli

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
NO_RETRY = {"token"}
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class Error(Exception):
    """Anything the LinkedIn lane cannot do; the message is safe to show a person."""


class Refused(Error):
    """A request the declared plan does not contain, a host outside it, or a scope the token is known not to
    hold. Raised before any socket opens."""


class NetworkError(Error):
    """The socket could not be opened, or the peer went away."""


class HTTPError(Error):
    """A non-2xx answer from LinkedIn, after the retries a call is allowed."""

    def __init__(self, status: int, message: str, *, code=None, request_id=None, body=None):
        self.status, self.code, self.request_id, self.body = status, code, request_id, body
        detail = f"HTTP {status}: {message}"
        if code:
            detail += f" ({code})"
        if request_id:
            detail += f" [x-li-uuid {request_id}]"
        super().__init__(detail)

    @property
    def unauthorized(self) -> bool:
        return self.status == 401

    @property
    def forbidden(self) -> bool:
        return self.status == 403

    @property
    def not_found(self) -> bool:
        return self.status == 404


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)  # lower-cased names
    body: bytes = b""

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    @property
    def success(self) -> bool:
        return 200 <= self.status < 300

    def json(self):
        text = self.body.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        try:
            return jsonlib.loads(text)
        except ValueError:
            return None


def send(verb: str, url: str, headers: dict, body) -> Response:
    """One HTTPS request; `Client` owns retries and error mapping. Only https leaves here."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise Refused(f"only https is allowed: {parts.scheme}://{parts.hostname}")
    try:
        with httpx.Client(timeout=TIMEOUT) as http:
            answer = http.request(verb, url, headers=headers, content=body)
    except httpx.TransportError as e:
        raise NetworkError(f"{parts.hostname}: {type(e).__name__}") from e
    return Response(answer.status_code, {k.lower(): v for k, v in answer.headers.items()}, answer.content)


class Client:
    def __init__(
        self,
        token: str = "",
        *,
        api_version: str = plan.DEFAULT_API_VERSION,
        sleeper=time.sleep,
        granted_scopes=None,
        secrets=(),
        transport=send,
    ):
        if plan.version_status(api_version) == "invalid":
            raise ValueError(f"LinkedIn-Version must be YYYYMM, got {api_version!r}")
        self.token = str(token or "")
        self.api_version = str(api_version)
        self.sleeper = sleeper
        self.granted_scopes = granted_scopes
        self.transport = transport
        self.secrets = [s for s in (self.token, *[str(x or "") for x in secrets]) if len(s) >= 8]

    def request(
        self, call_id, *, path=None, query=(), json=None, form=None, raw=None, content_type=None, url=None, auth=True
    ) -> Response:
        """Perform a declared call. `path` fills the declared path's `{placeholders}` (encoded here); `query` is
        ordered (key, value) pairs, a `restli.Raw` value inserted as is; `url` only for `images_upload`."""
        call = plan.fetch(call_id)
        self._check_scopes(call)
        target = self._url(call, path or {}, query) if url is None else self._upload_url(call, url)
        headers = self._headers(call, auth=auth, content_type=content_type, json=json, form=form)
        if json is not None:
            body = jsonlib.dumps(json, separators=(",", ":"), ensure_ascii=False).encode()
        elif form is not None:
            body = urlencode(form).encode()
        else:
            body = raw
        return self._send(call, target, headers, body)

    def json(self, call_id, **options) -> dict:
        data = self.request(call_id, **options).json()
        return data if isinstance(data, dict) else {}

    # ── sending ──────────────────────────────────────────────────────────────
    def _send(self, call, target, headers, body) -> Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.transport(call.verb, target, headers, body)
            except NetworkError as e:
                if not self._retry_network(call) or attempt >= MAX_ATTEMPTS:
                    raise HTTPError(0, self.scrub(str(e))) from e
                self.sleeper(self._backoff(attempt, None))
                continue
            if response.success:
                return response
            if not self._retry_status(call, response.status) or attempt >= MAX_ATTEMPTS:
                raise self._error(response)
            self.sleeper(self._backoff(attempt, response))

    @staticmethod
    def _retry_network(call) -> bool:
        return not call.write and call.id not in NO_RETRY

    @staticmethod
    def _retry_status(call, status) -> bool:
        if call.write or call.id in NO_RETRY:
            return status == 429
        return status in RETRY_STATUSES

    @staticmethod
    def _backoff(attempt, response) -> int:
        after = response.header("retry-after") if response is not None else ""
        if after.isdigit():
            return min(int(after), 60)
        return min(2**attempt, 30)

    # ── building ─────────────────────────────────────────────────────────────
    def _check_scopes(self, call):
        if self.granted_scopes is None or not call.scopes:
            return
        if not set(call.scopes) & set(self.granted_scopes):
            raise Refused(
                f"{call.id} needs one of {', '.join(call.scopes)}; this token holds {', '.join(self.granted_scopes)}"
            )

    @staticmethod
    def _url(call, params, query) -> str:
        if call.host == plan.UPLOAD:
            raise Refused(f"{call.id} takes the upload URL LinkedIn returned")

        def fill(match):
            key = match.group(1)
            if key not in params:
                raise ValueError(f"{call.id} needs {key}")
            value = str(params[key])
            if not value:
                raise ValueError(f"{call.id}: {key} is empty")
            return restli.encode(value)

        path = re.sub(r"\{(\w+)\}", fill, call.path)
        if plan.forbidden_path(path):
            raise Refused(f"{call.id} resolves to a forbidden path: {path}")
        qs = restli.query(query)
        return f"https://{call.host}{path}{'?' + qs if qs else ''}"

    @staticmethod
    def _upload_url(call, url) -> str:
        if call.host != plan.UPLOAD:
            raise Refused(f"{call.id} does not take a URL")
        try:
            parts = urlsplit(str(url))
            host = (parts.hostname or "").lower()
        except ValueError as e:
            raise Refused("upload URL is not a valid URL") from e
        if parts.scheme != "https" or not plan.UPLOAD_HOST.match(host):
            raise Refused("upload URL is not an https URL on linkedin.com")
        return str(url)

    def _headers(self, call, *, auth, content_type, json, form) -> dict:
        headers = {}
        if auth and not call.oauth:
            if not self.token:
                raise Error("no LinkedIn access token (connect the channel, or set LINKEDIN_ACCESS_TOKEN)")
            headers["Authorization"] = f"Bearer {self.token}"
        if call.rest:
            headers["LinkedIn-Version"] = self.api_version
            headers["X-Restli-Protocol-Version"] = plan.RESTLI_PROTOCOL
            if call.method_header:
                headers["X-RestLi-Method"] = call.method_header
        kind = content_type or (
            "application/json" if json is not None else "application/x-www-form-urlencoded" if form else None
        )
        if kind:
            headers["Content-Type"] = kind
        if call.host != plan.UPLOAD:
            headers["Accept"] = "application/json"
        return headers

    def _error(self, response) -> HTTPError:
        data = response.json()
        data = data if isinstance(data, dict) else {}
        message = data.get("message") or data.get("error_description") or data.get("error")
        message = message or response.body.decode("utf-8", errors="replace").strip()[:300] or "request failed"
        code = data.get("serviceErrorCode") or data.get("code")
        if not code and data.get("error_description"):
            code = data.get("error")
        request_id = response.header("x-li-uuid") or None
        return HTTPError(response.status, self.scrub(str(message)), code=code, request_id=request_id, body=data)

    def scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        return text
