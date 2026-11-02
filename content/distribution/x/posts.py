"""Posts on X: the payload (pure), creating one, reading the account's own posts
back, and their aggregate counts — plus the account behind a token.

One shape: `{"text": …}`. An article is its commentary with the page's URL
after it (`plan.post_text`); X draws the card from the page's own card tags
(`twitter:card`, Open Graph), so nothing is uploaded. Reads keep a whitelist of
fields, so a field X adds later reaches nobody until somebody decides it
should, and a lookup keeps only the account's own posts.

The counts are X's `public_metrics`: impressions, likes (as reactions),
replies (as comments), reposts and quotes (as shares). Link clicks are not
public metrics, so `clicks` is left at zero — as LinkedIn's member statistics
leave it before the version that reports them.
"""

from ..linkedin.statistics import normalize
from . import plan
from .client import Error

FIELDS = ("id", "text", "created_at", "author_id", "public_metrics")
TWEET_FIELDS = "created_at,author_id,public_metrics"
BATCH = 100


def payload(*, commentary: str, link: str | None = None) -> dict:
    return {"text": plan.post_text(commentary, link)}


def create(client, body: dict) -> str:
    """POST /2/tweets → the new post's id."""
    post_id = str((client.json("posts_create", json=body).get("data") or {}).get("id") or "")
    if not plan.POST_ID.match(post_id):
        raise Error("X answered the post without its id, so it may exist")
    return post_id


def me(client) -> dict:
    data = client.json("me").get("data") or {}
    if not data.get("id") or not data.get("username"):
        raise Error("X did not say which account the token belongs to")
    return {"id": str(data["id"]), "username": str(data["username"]), "name": str(data.get("name") or "")}


def check_account(client, account: str) -> dict:
    """The account behind the token, refused unless it is the configured one: X posts as whoever the token is."""
    found = me(client)
    if found["username"].lower() != str(account or "").lower():
        raise Error(f"the token posts as @{found['username']}, not @{account}: connect @{account}'s token")
    return found


def lookup(client, ids, *, account_id: str) -> dict:
    """{post id: the post} for the account's own posts among `ids` — one call per hundred."""
    wanted = list(dict.fromkeys(str(i) for i in ids if plan.POST_ID.match(str(i))))
    out = {}
    for i in range(0, len(wanted), BATCH):
        query = [("ids", ",".join(wanted[i : i + BATCH])), ("tweet.fields", TWEET_FIELDS)]
        for post in client.json("posts_lookup", query=query).get("data") or []:
            if isinstance(post, dict) and str(post.get("author_id")) == account_id:
                out[str(post["id"])] = trim(post)
    return out


def by_account(client, *, account_id: str, count: int = 10) -> list[dict]:
    query = [("max_results", max(5, min(int(count), 100))), ("tweet.fields", TWEET_FIELDS)]
    return [trim(p) for p in client.json("posts_by_account", path={"id": account_id}, query=query).get("data") or []]


def counts(post: dict) -> dict:
    metrics = post.get("public_metrics") or {}
    return normalize(
        {
            "impressions": metrics.get("impression_count"),
            "reactions": metrics.get("like_count"),
            "comments": metrics.get("reply_count"),
            "shares": int(metrics.get("retweet_count") or 0) + int(metrics.get("quote_count") or 0),
        }
    )


def post_url(post_id: str, account: str | None = None) -> str:
    return f"https://x.com/{plan.handle(account) or 'i'}/status/{post_id}"


def trim(post) -> dict:
    return {k: post[k] for k in FIELDS if k in post} if isinstance(post, dict) else {}
