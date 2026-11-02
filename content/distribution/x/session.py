"""An X channel's OAuth 2.0 token at work: a client that renews the two-hour
token before it lapses — or once on a 401 — and repeats the work.

X spends a refresh token when it is used and answers with a new pair, so the
pair is kept the moment it arrives. `renew`, when the caller gives one, does
the refresh its own way — the platform's holds the channel's row and keeps the
pair before it lets go (`services.x_session`) — so two workers that find the
token lapsed at once spend it once: the second takes the pair the first kept.
A 401 means X did nothing, so repeating the work after a renewal cannot post
twice.
"""

import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .client import Client, HTTPError, send
from .oauth2 import OAuth

EARLY = timedelta(minutes=2)  # renew this long before X says the token lapses


@dataclass
class UserToken:
    """An account's OAuth 2.0 pair, when its access token lapses, and the platform's app that renews it."""

    access_token: str = ""
    refresh_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    expires_at: datetime | None = None

    @property
    def access(self) -> bool:
        return bool(self.access_token)

    @property
    def app(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def refreshable(self) -> bool:
        return self.app and bool(self.refresh_token)

    def lapsed(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at - EARLY


class Session:
    def __init__(self, token: UserToken, *, renew=None, sleeper=time.sleep, transport=send, now=None):
        self.token = token
        self.renew = renew  # renew(spent token, refreshed) -> the token to use; `refreshed(spent)` asks X
        self.sleeper, self.transport, self.now = sleeper, transport, now
        self.refreshed = False

    def oauth(self) -> OAuth:
        return OAuth(self.token.client_id, self.token.client_secret, transport=self.transport, sleeper=self.sleeper)

    def client(self) -> Client:
        t = self.token
        if t.refreshable and not self.refreshed and (not t.access or t.lapsed(self.now or datetime.now(UTC))):
            self.refresh()
        return Client(
            bearer=self.token.access_token,
            secrets=(self.token.refresh_token, self.token.client_secret),
            sleeper=self.sleeper,
            transport=self.transport,
        )

    def refresh(self) -> UserToken:
        self.refreshed = True
        self.token = self.renew(self.token, self._refreshed) if self.renew else self._refreshed(self.token)
        return self.token

    def _refreshed(self, spent: UserToken) -> UserToken:
        fresh = self.oauth().refresh(refresh_token=spent.refresh_token, now=self.now)
        return replace(
            spent,
            access_token=fresh.access_token,
            refresh_token=fresh.refresh_token or spent.refresh_token,
            expires_at=fresh.expires_at,
        )

    def run(self, work):
        """`work(client)`; on a 401, renew once (when the token can be) and run it again."""
        try:
            return work(self.client())
        except HTTPError as e:
            if not (e.unauthorized and self.token.refreshable and not self.refreshed):
                raise
        self.refresh()
        return work(self.client())
