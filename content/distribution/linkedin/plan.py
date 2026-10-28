"""Every call the LinkedIn client can make, declared before it is made — with
the hosts, the API version rule and the URNs the rest of the client shares.

`Client.request` takes a call id, never a URL, so a request that is not on this
list cannot be expressed; the one caller-supplied URL (an image upload slot
LinkedIn hands back) must be https on linkedin.com (`UPLOAD_HOST`).

Two assertions keep the list honest, and both are tests: every entry's
`returns` sentence contains the word "own" (`own_content_only`) — writing that
sentence forces whoever adds a connections, followers or feed call to describe
the data, and a sentence that cannot honestly contain "own" fails — and no
declared path reaches member graphs, messaging, per-member engagement or
search (`forbidden_path`). Scopes are "any of": a call is refused locally only
when the token's granted scopes are known (from introspection) and hold none.
"""

import re
from dataclasses import dataclass, field
from datetime import date

API_HOST = "api.linkedin.com"
OAUTH_HOST = "www.linkedin.com"
UPLOAD = "upload"  # the host of `images_upload`: the slot LinkedIn returned
RESTLI_PROTOCOL = "2.0.0"
# `Linkedin-Version` (YYYYMM). LinkedIn publishes one a month and supports each
# for twelve months; there is no unversioned call.
DEFAULT_API_VERSION = "202608"
VERSION_SUPPORT_MONTHS = 12
VERSION_WARN_MONTHS = 10
# The Posts API's limit on `commentary`, counted after little-text escaping.
COMMENTARY_MAX = 3000

URN = re.compile(r"\Aurn:li:(person|organization|organizationBrand|share|ugcPost|image):([A-Za-z0-9_-]+)\Z")
POST_URN = re.compile(r"\Aurn:li:(share|ugcPost):\d+\Z")
AUTHOR_TYPES = ("person", "organization")
# LinkedIn's upload slots are signed URLs on linkedin.com.
UPLOAD_HOST = re.compile(r"\A(?:[a-z0-9-]+\.)*linkedin\.com\Z")
FORBIDDEN = re.compile(
    r"connections|/people|networkSizes|follower|memberFollowers|messages|conversations|"
    r"socialActions|/likes|/reactions|/comments|search|/me\b|profile",
    re.I,
)


def author_type(urn) -> str | None:
    """'organization' or 'person' for an author URN, else None."""
    match = URN.match(str(urn or ""))
    return match.group(1) if match and match.group(1) in AUTHOR_TYPES else None


def version_status(version, today: date | None = None) -> str:
    """ok, aging (within two months of the support window closing), sunset (past
    it — LinkedIn rejects the header), future, or invalid."""
    match = re.fullmatch(r"(\d{4})(\d{2})", str(version or ""))
    if not match or not 1 <= int(match.group(2)) <= 12:
        return "invalid"
    today = today or date.today()
    age = (today.year * 12 + today.month) - (int(match.group(1)) * 12 + int(match.group(2)))
    if age < 0:
        return "future"
    if age >= VERSION_SUPPORT_MONTHS:
        return "sunset"
    if age >= VERSION_WARN_MONTHS:
        return "aging"
    return "ok"


@dataclass(frozen=True)
class Call:
    id: str
    verb: str
    host: str
    path: str
    purpose: str
    returns: str
    scopes: tuple = field(default=())
    write: bool = False
    method_header: str | None = None

    @property
    def rest(self) -> bool:
        return self.host == API_HOST and self.path.startswith("/rest/")

    @property
    def oauth(self) -> bool:
        return self.host == OAUTH_HOST

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "verb": self.verb,
            "host": self.host,
            "path": self.path,
            "scopes": list(self.scopes),
            "write": self.write,
            "purpose": self.purpose,
            "returns": self.returns,
        }


ORG_READ = ("r_organization_social", "rw_organization_admin")
MEMBER_READ = ("r_member_social",)
ORG_ADMIN = ("r_organization_admin", "rw_organization_admin")
WRITE_SOCIAL = ("w_organization_social", "w_member_social")

CALLS = [
    Call(
        "token",
        "POST",
        OAUTH_HOST,
        "/oauth/v2/accessToken",
        "exchange an authorization code, or a refresh token, for an access token",
        "this app's own access token for the member who consented",
    ),
    Call(
        "introspect",
        "POST",
        OAUTH_HOST,
        "/oauth/v2/introspectToken",
        "check whether a token is active, when it expires and what it may do",
        "the status, expiry and scopes of this app's own token",
    ),
    Call(
        "userinfo",
        "GET",
        API_HOST,
        "/v2/userinfo",
        "learn which member authorized the app, to name their own person URN",
        "the authenticated member's own id and name",
        scopes=("openid", "profile"),
    ),
    Call(
        "organization_acls",
        "GET",
        API_HOST,
        "/rest/organizationAcls",
        "list the pages the member may post to",
        "the authenticated member's own page roles",
        scopes=ORG_ADMIN,
        method_header="FINDER",
    ),
    Call(
        "organization",
        "GET",
        API_HOST,
        "/rest/organizations/{id}",
        "show a page's name next to its URN",
        "the own public name of a page the member administers",
        scopes=ORG_ADMIN,
    ),
    Call(
        "posts_create",
        "POST",
        API_HOST,
        "/rest/posts",
        "publish an approved draft as its author",
        "the id of the author's own new post",
        scopes=WRITE_SOCIAL,
        write=True,
    ),
    Call(
        "posts_get",
        "GET",
        API_HOST,
        "/rest/posts/{urn}",
        "confirm a post published",
        "the author's own post, as published",
        scopes=ORG_READ + MEMBER_READ,
    ),
    Call(
        "posts_by_author",
        "GET",
        API_HOST,
        "/rest/posts",
        "list what the configured author already published",
        "the configured author's own recent posts",
        scopes=ORG_READ + MEMBER_READ,
        method_header="FINDER",
    ),
    Call(
        "posts_delete",
        "DELETE",
        API_HOST,
        "/rest/posts/{urn}",
        "withdraw a post the author published",
        "nothing; it removes the author's own post",
        scopes=WRITE_SOCIAL,
        write=True,
        method_header="DELETE",
    ),
    Call(
        "images_initialize",
        "POST",
        API_HOST,
        "/rest/images",
        "reserve an upload for a link card's thumbnail",
        "an upload slot for the author's own image",
        scopes=WRITE_SOCIAL,
        write=True,
    ),
    Call(
        "images_upload",
        "PUT",
        UPLOAD,
        "{uploadUrl}",
        "send the thumbnail's bytes to the slot LinkedIn returned",
        "nothing; it stores the author's own image",
        scopes=WRITE_SOCIAL,
        write=True,
    ),
    Call(
        "images_get",
        "GET",
        API_HOST,
        "/rest/images/{urn}",
        "wait for an uploaded thumbnail to finish processing",
        "the processing status of the author's own image",
        scopes=("w_organization_social",),
    ),
    Call(
        "organization_share_statistics",
        "GET",
        API_HOST,
        "/rest/organizationalEntityShareStatistics",
        "read how the page's published posts performed",
        "aggregate counts for the page's own posts",
        scopes=ORG_ADMIN,
        method_header="FINDER",
    ),
    Call(
        "member_post_statistics",
        "GET",
        API_HOST,
        "/rest/memberCreatorPostAnalytics",
        "read how a member's published post performed",
        "aggregate counts for the member's own post",
        scopes=("r_member_postAnalytics",),
        method_header="FINDER",
    ),
]

BY_ID = {call.id: call for call in CALLS}


def fetch(call_id: str) -> Call:
    from .client import Refused

    try:
        return BY_ID[call_id]
    except KeyError:
        raise Refused(f"{call_id} is not a declared LinkedIn call") from None


def own_content_only(calls=None) -> bool:
    return all(re.search(r"\bown\b", call.returns) for call in (CALLS if calls is None else calls))


def forbidden_path(path) -> bool:
    return bool(FORBIDDEN.search(str(path or "")))


def reads() -> list[Call]:
    return [call for call in CALLS if not call.write]


def writes() -> list[Call]:
    return [call for call in CALLS if call.write]


def describe() -> str:
    """The surface as text, for a terminal, a job summary or an application form."""
    lines = ["LinkedIn calls this CMS can make, and nothing else:", ""]
    for call in CALLS:
        host = "<upload slot on linkedin.com>" if call.host == UPLOAD else call.host
        path = "" if call.host == UPLOAD else call.path
        lines.append(f"  {call.verb.ljust(6)} {host}{path}{'   [write]' if call.write else ''}")
        lines.append(f"    to        {call.purpose}")
        lines.append(f"    scopes    {' | '.join(call.scopes) if call.scopes else '(app credentials)'}")
        lines.append(f"    returns   {call.returns}")
        lines.append("")
    lines.append("No member profiles, connections, followers, feeds or messages. No record of who")
    lines.append("engaged with a post — aggregate counts only, for the author's own posts.")
    return "\n".join(lines)
