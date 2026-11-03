"""Every credential shape the platform handles is starred in a log line, and
Sentry drops a credential by its name wherever an event carries it — `extra`,
request data, every frame's variables, a header nested inside one of them
(SEC-15)."""

from contextlib import contextmanager

import pytest
import sentry_sdk
from django.test import override_settings
from sentry_sdk.transport import Transport

from distribution.linkedin import Client
from ops import sentry
from ops.logging import redact

# A LinkedIn access token has no fixed prefix, so no pattern can find one in a
# string; only its name gives it away.
LINKEDIN_TOKEN = "AQVlinkedinaccesstoken0123456789"


@pytest.mark.parametrize(
    "secret",
    [
        "sk-" + "A1b2C3d4" * 6,  # OpenAI, the classic form
        "sk-proj-" + "A1b2_C3d4-" * 8,  # OpenAI, a project key
        "sk-svcacct-" + "A1b2_C3d4-" * 8,  # OpenAI, a service account's
        "xai-" + "A1b2C3d4" * 10,  # xAI
        "AKIAIOSFODNN7EXAMPLE",  # AWS, a long-lived access key id
        "ASIAIOSFODNN7EXAMPLE",  # AWS, a temporary one
        "gho_" + "A1b2C3d4" * 5,  # GitHub, an OAuth token
        "ghu_" + "A1b2C3d4" * 5,  # GitHub, a user-to-server token
        "ghs_" + "A1b2C3d4" * 5,  # GitHub, a server-to-server token
        "ghr_" + "A1b2C3d4" * 5,  # GitHub, a refresh token
        "gAAAAABn" + "A1b2_C3d4-" * 6 + "==",  # a Fernet ciphertext (ai/crypto.py)
    ],
)
def test_every_named_secret_shape_is_redacted(secret):
    assert redact(f"key={secret} done") == "key=[REDACTED] done"


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            '{"access_token": "AQVabc123", "expires_in": 5184000}',
            '{"access_token": "[REDACTED]", "expires_in": 5184000}',
        ),
        (
            "grant_type=refresh_token&refresh_token=AQX99&client_id=a",
            "grant_type=refresh_token&refresh_token=[REDACTED]&client_id=a",
        ),
        ("client_secret: s3cr3t-value", "client_secret: [REDACTED]"),
    ],
)
def test_a_credential_named_in_a_body_is_redacted(text, expected):
    assert redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "risk-assessment-and-mitigation-guide",  # a slug: `sk-` inside a word
        "sk-learn-tutorial-for-beginners",  # a slug: `sk-` with dashes, no key
        "grant_type=refresh_token",  # the grant's name, not a token
        "the task asked for an access token",
    ],
)
def test_words_that_only_look_like_a_prefix_are_kept(text):
    assert redact(text) == text


class Capture(Transport):
    """A Sentry transport that keeps the events it would have sent."""

    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        self.events += [event for event in (item.get_event() for item in envelope.items) if event]


@contextmanager
def reporting():
    """A Sentry client built from `ops.sentry.options()`, current for the block
    only, whose events are kept instead of sent."""
    transport = Capture()
    with override_settings(SENTRY_DSN="https://key@o0.ingest.example.invalid/1"):
        client = sentry_sdk.Client(**sentry.options(), transport=transport)
    with sentry_sdk.new_scope() as scope:
        scope.set_client(client)
        yield scope, transport


@pytest.mark.filterwarnings("ignore:The send_default_pii option is deprecated")
def test_a_credential_in_extra_is_scrubbed():
    with reporting() as (scope, transport):
        scope.set_extra("access_token", LINKEDIN_TOKEN)
        scope.set_extra("channel", "linkedin")
        sentry_sdk.capture_message("token refresh failed")
    (event,) = transport.events
    assert LINKEDIN_TOKEN not in repr(event)
    assert event["extra"]["channel"] == "linkedin"


@pytest.mark.filterwarnings("ignore:The send_default_pii option is deprecated")
def test_a_crash_inside_a_channel_client_reports_no_credential():
    """The headers a client signs a request with are a local of every frame
    between the request and the socket; a crash there sends those frames to
    Sentry, and the bearer token in them must not go too."""

    def crash(verb, url, headers, body):
        raise RuntimeError("the socket library broke")

    with reporting() as (_, transport):
        try:
            Client(LINKEDIN_TOKEN, transport=crash).request("posts_get", path={"urn": "urn:li:share:1"})
        except RuntimeError as e:
            sentry_sdk.capture_exception(e)
    (event,) = transport.events
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    assert any("headers" in frame.get("vars", {}) for frame in frames), "the frames carry no headers to scrub"
    assert LINKEDIN_TOKEN not in repr(event)
