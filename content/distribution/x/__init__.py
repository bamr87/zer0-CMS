"""An X API v2 client: OAuth 1.0a request signing (a site's lane) and OAuth 2.0
bearer tokens that renew themselves (the platform's channels), posts, the
account's own posts and their aggregate counts, and connecting an account —
with a PIN in a terminal, through X's consent screen in the studio — the
counterpart of `distribution/linkedin/`, over httpx.

Every call it can make is declared in `plan.CALLS` as data — verb, path and a
sentence saying what comes back — and `client.Client.request` takes a call id,
never a URL, refusing anything not on that list before a socket opens. Nothing
here decides what to publish or whether it may: that is `distribution.services`
(the platform's queue) and `distribution.lane.x_pipeline` (a site's own files,
for its CI), which share this client.

| Module | What it holds |
|---|---|
| `plan.py` | the host, handles and post ids, the length X counts a post's text by, and every call as data |
| `client.py` | the lane's credentials; `Client.request(call_id, …)`: the plan's gate, OAuth 1.0a signing or an OAuth 2.0 bearer, asymmetric retries, scrubbed errors |
| `posts.py` | the payload (pure), create, the account behind a token, the account's own posts and their counts |
| `oauth.py` | connecting an account for the lane (OAuth 1.0a): request token, authorize URL, PIN for the access token |
| `oauth2.py` | connecting an account for a platform channel (OAuth 2.0, PKCE): the consent URL, the code for a token pair, renewing it |
| `session.py` | a channel's token pair at work: renewed before it lapses or once on a 401, the new pair kept at once |
"""

from .client import Client, Credentials, Error, HTTPError, NetworkError, Refused
from .plan import API_HOST, TEXT_MAX, handle, post_text, weighted_length

__all__ = [
    "API_HOST",
    "TEXT_MAX",
    "Client",
    "Credentials",
    "Error",
    "HTTPError",
    "NetworkError",
    "Refused",
    "handle",
    "post_text",
    "weighted_length",
]
