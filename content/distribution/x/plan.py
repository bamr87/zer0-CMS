"""Every call the X client can make, declared before it is made — with the host,
the handles and post ids the rest of the client shares, and the length X counts
a post's text by.

`Client.request` takes a call id, never a URL, so a request that is not on this
list cannot be expressed. Two assertions keep the list honest, as LinkedIn's do
(`linkedin/plan.py`), and both are tests: every entry's `returns` sentence
contains the word "own" (`own_content_only`), and no declared path reaches
followers, likes, bookmarks, mentions, messages, lists, spaces or search
(`forbidden_path`). OAuth 1.0a carries no per-call scopes: what a token may do
is the app's permission ("Read and write"), set where the app is. An OAuth 2.0
token — a platform channel's — carries the scopes its owner granted
(`oauth2.SCOPES`, the least a channel needs).

X counts a post's text with its twitter-text rules (`weighted_length`): a link
is 23 whatever its length, a character in the Latin, Greek, Cyrillic and common
punctuation ranges is 1 and any other is 2, after NFC normalisation, against a
limit of 280. An emoji sequence is counted here per code point, and a bare
domain at no less than 23, so the count can refuse a text X would take — a
person shortens it — but never takes one X refuses. The library X maintains is
JavaScript and Java; its Python port is unmaintained, and the rules are these
few lines.
"""

import re
import unicodedata
from dataclasses import dataclass

API_HOST = "api.x.com"
TEXT_MAX = 280
URL_LENGTH = 23
HANDLE = re.compile(r"\A@?([A-Za-z0-9_]{1,15})\Z")
POST_ID = re.compile(r"\A[0-9]{1,19}\Z")
FORBIDDEN = re.compile(
    r"follow|liking|liked|/likes|bookmark|mention|/dm|direct|/lists|spaces|search|blocking|muting|retweeted_by",
    re.I,
)
# twitter-text v3: the ranges that weigh 1; every other code point weighs 2.
LIGHT = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
LINK = re.compile(r"https?://\S+", re.I)
BARE = re.compile(r"(?<![\w@/.-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?", re.I)


def handle(value) -> str | None:
    """`@bamr87` or `bamr87` → `bamr87`; None for anything X would not take as a handle."""
    match = HANDLE.match(str(value or "").strip())
    return match.group(1) if match else None


def _weight(text: str) -> int:
    return sum(1 if any(a <= ord(c) <= b for a, b in LIGHT) else 2 for c in text)


def weighted_length(text) -> int:
    rest = unicodedata.normalize("NFC", str(text or ""))
    total = len(LINK.findall(rest)) * URL_LENGTH
    rest = LINK.sub("", rest)
    total += sum(max(URL_LENGTH, _weight(m.group(0))) for m in BARE.finditer(rest))
    return total + _weight(BARE.sub("", rest))


def post_text(commentary, link=None) -> str:
    """What X receives: the commentary, then — for an article — the page's URL on a line of its own, unless the
    commentary already carries it. X draws the link's card from the page's own card tags."""
    text = str(commentary or "").strip()
    if link and link not in text:
        text = f"{text}\n\n{link}" if text else str(link)
    return text


@dataclass(frozen=True)
class Call:
    id: str
    verb: str
    path: str
    purpose: str
    returns: str
    write: bool = False
    host: str = API_HOST

    @property
    def oauth(self) -> bool:
        """A step of OAuth 1.0a's handshake: signed by the app, with no account token yet."""
        return self.path.startswith("/oauth/")

    @property
    def grant(self) -> bool:
        """OAuth 2.0's token endpoint: the platform's app authenticates, with HTTP Basic."""
        return self.path.startswith("/2/oauth2/")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "verb": self.verb,
            "host": self.host,
            "path": self.path,
            "write": self.write,
            "purpose": self.purpose,
            "returns": self.returns,
        }


CALLS = [
    Call(
        "request_token",
        "POST",
        "/oauth/request_token",
        "start connecting an account: a temporary token its owner authorizes",
        "a temporary token for this app's own connection request",
    ),
    Call(
        "access_token",
        "POST",
        "/oauth/access_token",
        "finish connecting: the authorized token and its PIN for the account's token",
        "this app's own access token for the account whose owner authorized it",
    ),
    Call(
        "oauth2_token",
        "POST",
        "/2/oauth2/token",
        "connect an account through X's consent screen, and renew its two-hour token (OAuth 2.0)",
        "this app's own OAuth 2.0 token for the account whose owner authorized it",
    ),
    Call(
        "oauth2_revoke",
        "POST",
        "/2/oauth2/revoke",
        "give back a token for an account the channel does not post as, or the grant of a channel a person disconnected",
        "nothing but this app's own token, revoked",
    ),
    Call(
        "me",
        "GET",
        "/2/users/me",
        "learn which account a token posts as, and refuse to post as any other",
        "the authenticated account's own id, name and handle",
    ),
    Call(
        "posts_create",
        "POST",
        "/2/tweets",
        "publish an approved draft as the account",
        "the id of the account's own new post",
        write=True,
    ),
    Call(
        "posts_lookup",
        "GET",
        "/2/tweets",
        "confirm the account's posts published, and read how they performed",
        "the account's own posts, as published, with their aggregate counts",
    ),
    Call(
        "posts_by_account",
        "GET",
        "/2/users/{id}/tweets",
        "list what the account already published",
        "the account's own recent posts",
    ),
]

BY_ID = {call.id: call for call in CALLS}


def fetch(call_id: str) -> Call:
    from .client import Refused

    try:
        return BY_ID[call_id]
    except KeyError:
        raise Refused(f"{call_id} is not a declared X call") from None


def own_content_only(calls=None) -> bool:
    return all(re.search(r"\bown\b", call.returns) for call in (CALLS if calls is None else calls))


def forbidden_path(path) -> bool:
    return bool(FORBIDDEN.search(str(path or "")))


def describe() -> str:
    """The surface as text, for a terminal or a job summary."""
    lines = ["X calls this CMS can make, and nothing else:", ""]
    for call in CALLS:
        lines.append(f"  {call.verb.ljust(6)} {call.host}{call.path}{'   [write]' if call.write else ''}")
        lines.append(f"    to        {call.purpose}")
        lines.append(f"    returns   {call.returns}")
        lines.append("")
    lines.append("No followers, likes, bookmarks, mentions, messages or search. Aggregate counts only, for the")
    lines.append("account's own posts. X bills each request (pay-per-use): a post carrying a link costs more than one")
    lines.append("without, and every read is billed too.")
    return "\n".join(lines)
