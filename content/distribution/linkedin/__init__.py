"""A LinkedIn API client: the versioned REST gateway, three-legged OAuth with
PKCE, posts and their card images, the pages a member administers, and
aggregate statistics for the author's own posts — ported from the Ruby lane
(`rails/lib/zer0_cms/linkedin/`, retired by PLAN G5) to Python over httpx.

Every call it can make is declared in `plan.CALLS` as data — verb, host, path,
the scopes it needs and a sentence saying what comes back — and
`client.Client.request` takes a call id, never a URL, refusing anything not on
that list before a socket opens. Nothing here decides what to publish or
whether it may: that is `distribution.services` (the platform's queue) and
`distribution.lane` (a site's own files, for its CI), which share this client.

| Module | What it holds |
|---|---|
| `plan.py` | the hosts, the API version rule, URNs, and every call as data |
| `restli.py` | Rest.li 2.0 encoding and the `little` text format of `commentary` |
| `client.py` | `Client.request(call_id, …)`: the plan's gate, versioned headers, asymmetric retries, scrubbed errors |
| `oauth.py` | the consent URL with state and PKCE, the code exchange, refresh, introspection, the member behind a token |
| `posts.py` | payloads (pure), create, read back, list, delete; a link card's image upload |
| `statistics.py` | the pages a member may post to, and aggregate counts for the author's own posts |
"""

from .client import Client, Error, HTTPError, NetworkError, Refused, Response
from .plan import (
    API_HOST,
    COMMENTARY_MAX,
    DEFAULT_API_VERSION,
    OAUTH_HOST,
    POST_URN,
    author_type,
    version_status,
)

__all__ = [
    "API_HOST",
    "COMMENTARY_MAX",
    "DEFAULT_API_VERSION",
    "OAUTH_HOST",
    "POST_URN",
    "Client",
    "Error",
    "HTTPError",
    "NetworkError",
    "Refused",
    "Response",
    "author_type",
    "version_status",
]
