"""Posts: the payloads (pure) and the calls that act on them, and a link card's
thumbnail through the Images API.

Two shapes, both organic and public on the main feed: a text update
(`commentary` only) and an article share (`commentary` above a link card).
LinkedIn does not scrape the URL, so the card's title, description and
thumbnail travel in the payload, the thumbnail as an image URN uploaded first.
`commentary` is escaped to the little text format here, so a payload is always
what LinkedIn will read, and a preview shows exactly that.

LinkedIn takes JPG, GIF and PNG card images; `uploadable` says so before any
call (an SVG preview is not uploadable), so a publish can go without a card
image and say why rather than fail.
"""

import time
from urllib.parse import unquote, urlsplit

from . import plan, restli
from .client import Error

# What a read returns to a caller: a whitelist, so a field LinkedIn adds later
# reaches nobody until somebody decides it should.
FIELDS = (
    "id",
    "author",
    "commentary",
    "lifecycleState",
    "visibility",
    "publishedAt",
    "createdAt",
    "lastModifiedAt",
    "content",
)
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def text_payload(*, author: str, commentary: str) -> dict:
    check_author(author)
    return {
        "author": author,
        "commentary": restli.escape(commentary),
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }


def article_payload(*, author, commentary, source, title, description, thumbnail=None) -> dict:
    if not http_url(source):
        raise ValueError("an article share needs an http(s) source URL")
    if not str(title or "").strip():
        raise ValueError("an article share needs a title")
    article = {"source": str(source), "title": str(title), "description": str(description or "")}
    if thumbnail:
        article["thumbnail"] = thumbnail
    return {**text_payload(author=author, commentary=commentary), "content": {"article": article}}


def commentary_length(text) -> int:
    """The escaped length LinkedIn counts against COMMENTARY_MAX."""
    return len(restli.escape(text))


def create(client, payload: dict) -> str:
    """POST /rest/posts → the new post's URN, from `x-restli-id`."""
    response = client.request("posts_create", json=payload)
    urn = unquote(response.header("x-restli-id"))
    if not urn:
        raise Error(f"LinkedIn created the post (HTTP {response.status}) but returned no x-restli-id")
    return urn


def get(client, urn: str) -> dict:
    check_post(urn)
    return trim(client.json("posts_get", path={"urn": urn}))


def by_author(client, *, author: str, count: int = 10) -> list[dict]:
    check_author(author)
    count = max(1, min(int(count), 100))
    query = [("q", "author"), ("author", author), ("count", count), ("sortBy", "LAST_MODIFIED")]
    return [trim(post) for post in client.json("posts_by_author", query=query).get("elements") or []]


def delete(client, urn: str) -> bool:
    check_post(urn)
    client.request("posts_delete", path={"urn": urn})
    return True


def feed_url(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}/"


def trim(post) -> dict:
    return {k: post[k] for k in FIELDS if k in post} if isinstance(post, dict) else {}


def http_url(value) -> bool:
    try:
        parts = urlsplit(str(value or ""))
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def check_author(author):
    if not plan.author_type(author):
        raise ValueError(f"author must be urn:li:organization:{{id}} or urn:li:person:{{id}}, got {author!r}")


def check_post(urn):
    if not plan.POST_URN.match(str(urn or "")):
        raise ValueError(f"not a post URN: {urn!r}")


# ── a link card's image ─────────────────────────────────────────────────────


def uploadable(name: str, size: int) -> tuple[bool, str | None]:
    """(True, None) or (False, the reason) for an image called `name` of `size` bytes."""
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    base = name.rsplit("/", 1)[-1]
    if ext not in IMAGE_TYPES:
        return False, f"{base}: LinkedIn takes PNG, JPG or GIF, not {ext or 'this file'}"
    if size > MAX_IMAGE_BYTES:
        return False, f"{base} is over {MAX_IMAGE_BYTES // 1024 // 1024} MB"
    return True, None


def upload_image(client, *, owner: str, name: str, data: bytes, sleeper=time.sleep, polls: int = 3) -> str:
    """Reserve an upload, send the bytes to the signed slot, then — best effort — wait for processing."""
    ok, reason = uploadable(name, len(data))
    if not ok:
        raise Error(reason)
    if not plan.author_type(owner):
        raise ValueError("image owner must be an organization or person URN")
    body = {"initializeUploadRequest": {"owner": owner}}
    value = client.json("images_initialize", query=[("action", "initializeUpload")], json=body).get("value") or {}
    upload_url, urn = str(value.get("uploadUrl") or ""), str(value.get("image") or "")
    if not upload_url or not urn:
        raise Error("initializeUpload returned no uploadUrl or image URN")
    content_type = IMAGE_TYPES["." + name.rsplit(".", 1)[-1].lower()]
    client.request("images_upload", url=upload_url, raw=data, content_type=content_type)
    _wait_available(client, urn, sleeper, polls)
    return urn


def _wait_available(client, urn, sleeper, polls):
    """The URN is usable in a card while it processes, so this never fails the publish."""
    try:
        for _ in range(polls):
            status = client.json("images_get", path={"urn": urn}).get("status")
            if status in (None, "AVAILABLE", "PROCESSING_FAILED"):
                return status
            sleeper(2)
    except Error:
        return None
    return None
