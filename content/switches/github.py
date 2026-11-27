"""Every GitHub call the content switches can make, declared before it is made,
and the one client that makes them.

`Client.request` takes a call id from `CALLS`, never a URL, so a request the
plan does not declare cannot be expressed — the way distribution's LinkedIn
and X clients declare theirs (`distribution/linkedin/plan.py`) and the
extension's Fleet console declares its `FLEET_PLAN` (`src/core/fleet/github.ts`).
Three guards read the plan, and each is a test (`tests/switches/test_github.py`):

- `repository_scoped_only`: every path is a repository's own Actions variables
  or a file of its contents, and every `returns` says "own";
- `never_a_secret`: no path reaches `/actions/secrets` (or any `secret`), so no
  switch tool reads, prints or changes one (the hub's constitution § 17.8);
- `no_deletes`: nothing is deleted — a switch is set to `false`, never removed.

Each `{name}` is one path segment, checked against `SEGMENT` before a URL is
built; `{+path}` (a file in the hub) is a run of such segments, with no `.` or
`..`. The token goes into one header and nowhere else: an error's message is
built from GitHub's status and body, never from the request, and the token is
scrubbed out of it all the same.
"""

import re
from dataclasses import dataclass

import httpx
from django.conf import settings

SEGMENT = re.compile(r"\A[A-Za-z0-9_.-]{1,100}\Z")
REPO = re.compile(r"\A[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}\Z")
PAGE = 30  # GitHub's largest page of Actions variables is 30
PLACEHOLDER = re.compile(r"\{(\+?)(\w+)\}")


@dataclass(frozen=True)
class Call:
    id: str
    verb: str
    path: str
    purpose: str
    returns: str
    write: bool = False
    accept: str = "application/vnd.github+json"


CALLS = [
    Call(
        "hub_map",
        "GET",
        "/repos/{owner}/{repo}/contents/{+path}",
        "read the hub's switch map (_data/fleet.yml), the record every switch is a projection of",
        "the hub repository's own file at one ref, raw; read only, never written",
        accept="application/vnd.github.raw+json",
    ),
    Call(
        "variables",
        "GET",
        "/repos/{owner}/{repo}/actions/variables",
        "list an outlet's switches as they are set right now, a page at a time",
        "the repository's own Actions variables, names and plaintext values; never a secret, which has no value to read",
    ),
    Call(
        "variable",
        "GET",
        "/repos/{owner}/{repo}/actions/variables/{name}",
        "read one switch back after setting it",
        "the repository's own variable, as it is set now (404: it is unset)",
    ),
    Call(
        "variable_update",
        "PATCH",
        "/repos/{owner}/{repo}/actions/variables/{name}",
        "set a switch a person confirmed, with the reason they gave",
        "nothing: the repository's own variable now holds the value the person confirmed",
        write=True,
    ),
    Call(
        "variable_create",
        "POST",
        "/repos/{owner}/{repo}/actions/variables",
        "create a switch the first time it is set (the update answered 404)",
        "nothing: the repository's own variable exists, holding the value the person confirmed",
        write=True,
    ),
]
BY_ID = {call.id: call for call in CALLS}
SUBROOTS = ("/actions/variables", "/contents/")


class Error(Exception):
    """A call that could not be made or did not succeed; the message is safe to show a person."""

    def __init__(self, message: str, status: int | None = None):
        self.status = status
        super().__init__(message)


class Refused(Error):
    """A call the plan does not declare, or a value that is not one path segment. Raised before any socket opens."""


def repository_scoped_only(calls=None) -> bool:
    prefix = "/repos/{owner}/{repo}"
    return all(
        call.path.startswith(prefix)
        and any(
            call.path[len(prefix) :] == root or call.path[len(prefix) :].startswith(root.rstrip("/") + "/")
            for root in SUBROOTS
        )
        and re.search(r"\bown\b", call.returns)
        for call in (CALLS if calls is None else calls)
    )


def never_a_secret(calls=None) -> bool:
    return not any("secret" in call.path.lower() for call in (CALLS if calls is None else calls))


def no_deletes(calls=None) -> bool:
    return all(call.verb != "DELETE" for call in (CALLS if calls is None else calls))


def describe() -> str:
    """The surface as text, for a reviewer or a terminal."""
    lines = ["GitHub calls the content switches make, and nothing else:", ""]
    for call in CALLS:
        lines.append(f"  {call.verb.ljust(6)} {call.path}{'   [write]' if call.write else ''}")
        lines.append(f"    to        {call.purpose}")
        lines.append(f"    returns   {call.returns}")
        lines.append("")
    lines.append("No secrets are read or written, nothing is deleted, and nothing is dispatched or merged.")
    return "\n".join(lines)


def split_repo(repo: str) -> tuple[str, str]:
    if not REPO.match(str(repo or "")):
        raise Refused(f"{repo!r} is not a repository (owner/name)")
    owner, name = str(repo).split("/")
    return owner, name


def _path(call: Call, params: dict) -> str:
    def fill(match):
        spread, key = match.group(1), match.group(2)
        value = str(params.get(key, ""))
        parts = value.split("/") if spread else [value]
        if not all(SEGMENT.match(part) and part not in (".", "..") for part in parts):
            raise Refused(f"{key} {value!r} is not a path GitHub's {call.id} call takes")
        return "/".join(parts)

    return PLACEHOLDER.sub(fill, call.path)


class Client:
    """The one gateway to GitHub's API (`settings.SWITCHES_GITHUB_API`). `token` may be empty: a public file then
    reads without one, and a variable answers 401 or 403 — unreadable, never off."""

    def __init__(self, token: str = "", *, transport: httpx.BaseTransport | None = None):
        self._token = token or ""
        self._http = httpx.Client(
            base_url=settings.SWITCHES_GITHUB_API,
            timeout=httpx.Timeout(settings.SWITCHES_GITHUB_TIMEOUT),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._http.close()

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, "[credential]") if self._token else text

    def request(self, call_id: str, *, query: dict | None = None, json: dict | None = None, **params) -> httpx.Response:
        call = BY_ID.get(call_id)
        if call is None:
            raise Refused(f"{call_id} is not a declared GitHub call")
        headers = {"Accept": call.accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "zer0-cms-switches"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = self._http.request(call.verb, _path(call, params), params=query, json=json, headers=headers)
        except httpx.HTTPError as e:
            raise Error(f"GitHub could not be reached ({type(e).__name__})") from None
        if response.is_success:
            return response
        raise Error(self._scrub(_message(response)), response.status_code)


def _message(response: httpx.Response) -> str:
    status = response.status_code
    if status in (403, 429) and response.headers.get("x-ratelimit-remaining") == "0":
        return (
            f"GitHub's rate limit is spent until {response.headers.get('x-ratelimit-reset', 'later')} (HTTP {status})"
        )
    try:
        said = str(response.json().get("message") or "")[:200]
    except ValueError:
        said = ""
    return f"HTTP {status}" + (f": {said}" if said else "")
