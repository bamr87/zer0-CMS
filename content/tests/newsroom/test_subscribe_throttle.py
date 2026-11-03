"""The public subscribe and confirm endpoints have an allowance of their own
(WORK-18): each new address is a confirmation email, so one caller gets
`THROTTLE_NEWSLETTER_SUBSCRIBE_RATE` (5 a minute by default), and the request
over it is 429 and sends no mail."""

import pytest

from config.settings import base
from newsroom.models import Newsletter, Subscriber
from newsroom.views import SubscribeThrottle

URL = "/api/v2/newsroom"


def test_the_default_is_five_a_minute():
    assert base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["newsletter_subscribe"] == "5/min"


@pytest.mark.django_db
def test_the_sixth_subscribe_in_a_minute_sends_no_mail(
    client, site, mailoutbox, monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setitem(SubscribeThrottle.THROTTLE_RATES, "newsletter_subscribe", "5/min")
    newsletter = Newsletter.objects.create(site=site, name="Morning Brief", slug="morning")
    url = f"{URL}/newsletters/{newsletter.public_id}/subscribe/"
    for n in range(5):
        with django_capture_on_commit_callbacks(execute=True):
            answer = client.post(url, {"email": f"reader{n}@example.com"}, content_type="application/json")
        assert answer.status_code == 202
    with django_capture_on_commit_callbacks(execute=True):
        refused = client.post(url, {"email": "reader5@example.com"}, content_type="application/json")
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "rate.limited"
    assert int(refused["Retry-After"]) >= 1
    assert len(mailoutbox) == 5 and not Subscriber.objects.filter(email="reader5@example.com").exists()
    # confirming spends the same allowance: a token guesser is held to it too
    assert (
        client.post(f"{URL}/subscriptions/confirm/", {"token": "x"}, content_type="application/json").status_code == 429
    )
