"""A site's checkout as the X lane reads it: `zer0.json` `distribution.x`, then
`_config.yml` for the site URL, under the environment's switches — the LinkedIn
lane's `Config` (`site.py`) with X's settings.

The file layers describe; they never arm. A live publish takes
`ZER0_X_PUBLISH=1` in the environment of the process doing it, and a `pending`
draft counts as approved only where `ZER0_X_MERGED=1` says the run is on the
default branch — the LinkedIn lane's rules, with X's own switches so arming one
network never arms the other. The ledger is X's own file: it is keyed by
canonical URL, and a page shared on LinkedIn has still to go to X.
"""

from ..x import plan
from ..x.client import Credentials
from .site import Config

DEFAULT_QUEUE = ".zer0/drafts/x"
DEFAULT_LEDGER = ".zer0/x-ledger.json"
ARM_VARIABLE = "ZER0_X_PUBLISH"
MERGED_VARIABLE = "ZER0_X_MERGED"
KEYS = (
    "account",
    "siteUrl",
    "queue",
    "ledger",
    "acceptStatuses",
    "sources",
    "hashtagLimit",
    "bannedPatternsFile",
    "cadence",
    "checkLink",
)
# X reads a post at a glance: two hashtags, not LinkedIn's three.
HASHTAGS = 2


class XConfig(Config):
    BLOCK, KEYS, ARM, MERGED = "x", KEYS, ARM_VARIABLE, MERGED_VARIABLE

    @property
    def credentials(self) -> Credentials:
        return Credentials.from_env(self.env)

    @property
    def author_type(self):
        return "account" if self.account else None

    def _resolve(self, cms_root):
        block, jekyll = self.block, self.site_config
        url = str(jekyll.get("url") or "").strip()
        jekyll_url = f"{url.rstrip('/')}{str(jekyll.get('baseurl') or '').strip().rstrip('/')}" if url else None
        self.account_setting = self._first(block.get("account"))
        self.account = plan.handle(self.account_setting) or ""
        self.author = self.account
        self.site_url = self._first(block.get("siteUrl"), jekyll_url).rstrip("/")
        self.queue = self._confined(block.get("queue") or DEFAULT_QUEUE, "queue")
        self.ledger = self._confined(block.get("ledger") or DEFAULT_LEDGER, "ledger")
        accept = block.get("acceptStatuses")
        self.accept_statuses = [str(s).strip().lower() for s in (accept if isinstance(accept, list) else ["approved"])]
        self.sources = [str(s) for s in block.get("sources") or []]
        try:
            self.hashtag_limit = max(0, min(int(block.get("hashtagLimit", HASHTAGS)), 10))
        except (TypeError, ValueError):
            self.hashtag_limit = HASHTAGS
        bans = block.get("bannedPatternsFile")
        self.banned_patterns_file = self._confined(bans, "bannedPatternsFile") if bans else None
        self.cms_root = self._confined(cms_root or ".cms", "cms.root")

    def _validate(self):
        self._validate_keys()
        if not self.account_setting:
            self._warn("no X account: set distribution.x.account (the handle the token posts as) in zer0.json")
        elif not self.account:
            self._error(f'account must be an X handle (letters, digits, _, at most 15), got "{self.account_setting}"')
        self._validate_url_and_statuses()
