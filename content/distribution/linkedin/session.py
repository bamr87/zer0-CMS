"""One author's credentials at work: a client that refreshes its token once on
a 401 and repeats the work, and the publish step both lanes share.

A 401 means LinkedIn did nothing, so repeating the work after a refresh cannot
duplicate a write. `send_post` is the one way a post is created: a create that
ends in a 5xx, a dropped connection or a success with no post id may have
posted, so it calls `mark_unconfirmed` before anything else happens — and the
caller's ledger then refuses that key, on every surface, until a person has
looked. A refusal before a socket, a 4xx, and a 429 LinkedIn sends before
acting are not doubts, and are not written down.
"""

import copy
import time
from dataclasses import dataclass

from . import posts
from .client import Client, Error, HTTPError, Refused, send
from .oauth import OAuth
from .plan import DEFAULT_API_VERSION


@dataclass
class Credentials:
    access_token: str = ""
    refresh_token: str = ""
    client_id: str = ""
    client_secret: str = ""

    @classmethod
    def from_env(cls, env) -> "Credentials":
        return cls(
            *(
                str(env.get(f"LINKEDIN_{name}") or "").strip()
                for name in ("ACCESS_TOKEN", "REFRESH_TOKEN", "CLIENT_ID", "CLIENT_SECRET")
            )
        )

    @property
    def access(self) -> bool:
        return bool(self.access_token)

    @property
    def app(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def refreshable(self) -> bool:
        return self.app and bool(self.refresh_token)

    def present(self) -> dict:
        """Names only — the values never leave through a report."""
        return {
            "LINKEDIN_ACCESS_TOKEN": self.access,
            "LINKEDIN_REFRESH_TOKEN": bool(self.refresh_token),
            "LINKEDIN_CLIENT_ID": bool(self.client_id),
            "LINKEDIN_CLIENT_SECRET": bool(self.client_secret),
        }


class Session:
    def __init__(
        self,
        credentials: Credentials,
        *,
        api_version=DEFAULT_API_VERSION,
        sleeper=time.sleep,
        on_refresh=None,
        transport=send,
        now=None,
    ):
        self.credentials = credentials
        self.api_version = api_version
        self.sleeper = sleeper
        self.on_refresh = on_refresh  # called with the new oauth.Token, to keep it
        self.transport = transport
        self.now = now
        self.refreshed = False

    def oauth(self) -> OAuth:
        c = self.credentials
        return OAuth(c.client_id, c.client_secret, transport=self.transport, sleeper=self.sleeper)

    def client(self) -> Client:
        if not self.credentials.access and self.credentials.refreshable and not self.refreshed:
            self.refresh()
        c = self.credentials
        return Client(
            c.access_token,
            api_version=self.api_version,
            sleeper=self.sleeper,
            transport=self.transport,
            secrets=[c.refresh_token, c.client_secret],
        )

    def refresh(self):
        token = self.oauth().refresh(refresh_token=self.credentials.refresh_token, now=self.now)
        self.credentials.access_token = token.access_token
        self.refreshed = True
        if self.on_refresh:
            self.on_refresh(token)
        return token

    def run(self, work):
        """`work(client)`; on a 401, refresh once (when the credentials can) and run it again."""
        try:
            return work(self.client())
        except HTTPError as e:
            if not (e.unauthorized and self.credentials.refreshable and not self.refreshed):
                raise
        self.refresh()
        return work(self.client())


def send_post(session: Session, *, author: str, payload: dict, image=None, notes: list, mark_unconfirmed):
    """Upload the card image (best effort), create the post, and return (post URN, image URN). `image` is
    (name, bytes) or None; `mark_unconfirmed(message)` writes the doubt down before the error goes up."""

    def work(client):
        image_urn = None
        if image is not None:
            try:
                image_urn = posts.upload_image(
                    client, owner=author, name=image[0], data=image[1], sleeper=session.sleeper
                )
            except Refused:
                raise
            except Error as e:
                notes.append(f"thumbnail upload failed ({e}); posting without a card image")
        body = copy.deepcopy(payload)
        if image_urn and "content" in body:
            body["content"]["article"]["thumbnail"] = image_urn
        try:
            return posts.create(client, body), image_urn
        except Refused:
            raise
        except HTTPError as e:
            if e.status == 0 or e.status >= 500:
                mark_unconfirmed(str(e))
            raise
        except Error as e:
            mark_unconfirmed(str(e))
            raise

    return session.run(work)
