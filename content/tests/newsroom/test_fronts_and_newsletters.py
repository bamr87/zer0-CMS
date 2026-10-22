"""Fronts and newsletters (PLAN G15). A front's slots resolve to stories as a
reader would find them — a pinned story while it is live, else the next latest
published story of a desk, never twice. A newsletter subscription is confirmed
by an emailed link before anything is sent (double opt-in); an issue assembled
from published stories is previewed, then sent by the worker through Django's
mail API (locmem here; an anymail ESP in production) to confirmed subscribers
only, each with their own unsubscribe link — once."""

from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.utils import timezone

from newsroom import services
from newsroom.models import Front, Issue, Newsletter, Story, Subscriber

S = Story.Status
URL = "/api/v2/newsroom"


def link(text, path):
    """The token of the link to `path` in an email's text."""
    url = next(word for word in text.split() if path in word)
    return parse_qs(urlparse(url).query)["token"][0]


@pytest.mark.django_db
def test_a_front_shows_pinned_stories_and_fills_the_rest_with_the_latest(
    api, desk, site, ed, reporter, outsider, advance
):
    older = advance(desk, S.PUBLISHED, headline="Older")
    newer = advance(desk, S.PUBLISHED, headline="Newer")
    pinned_draft = advance(desk, S.DRAFTING, headline="Pinned but not out")
    body = {
        "site": site.pk,
        "name": "Home",
        "slug": "home",
        "slots": [
            {"rule": "pinned", "story": str(older.public_id)},
            {"rule": "latest", "desk": str(desk.public_id)},
            {"rule": "latest"},
            {"rule": "pinned", "story": str(pinned_draft.public_id)},
        ],
    }
    assert api(reporter).post(f"{URL}/fronts/", body, format="json").status_code == 403  # sees the site, edits no desk
    assert api(outsider).post(f"{URL}/fronts/", body, format="json").status_code == 422  # cannot even name the stories
    made = api(ed).post(f"{URL}/fronts/", body, format="json")
    assert made.status_code == 201, made.json()
    front = Front.objects.get(public_id=made.json()["id"])
    assert [s.rule for s in front.slots.all()] == ["pinned", "latest", "latest", "pinned"]
    shown = api(ed).get(f"{URL}/fronts/{front.public_id}/stories/").json()
    assert [(s["position"], s["story"] and s["story"]["headline"]) for s in shown] == [
        (0, "Older"),  # pinned
        (1, "Newer"),  # the latest of the desk, not the pinned one again
        (2, None),  # nothing published is left
        (3, None),  # pinned, but its page is not live
    ]
    assert newer.page_id and api(outsider).get(f"{URL}/fronts/{front.public_id}/stories/").status_code == 404
    unpinned = api(ed).post(f"{URL}/fronts/", {**body, "slug": "x", "slots": [{"rule": "pinned"}]}, format="json")
    assert unpinned.status_code == 422


@pytest.mark.django_db
def test_a_subscription_is_confirmed_by_email_before_anything_is_sent(
    client, site, mailoutbox, django_capture_on_commit_callbacks
):
    newsletter = Newsletter.objects.create(site=site, name="Morning Brief", slug="morning")
    url = f"{URL}/newsletters/{newsletter.public_id}/subscribe/"
    with django_capture_on_commit_callbacks(execute=True):
        answer = client.post(url, {"email": "Reader@Example.com"}, content_type="application/json")
    assert answer.status_code == 202 and answer.json() == {"status": "pending", "newsletter": "Morning Brief"}
    subscriber = Subscriber.objects.get()
    assert (subscriber.email, subscriber.status) == ("reader@example.com", "pending")
    assert len(mailoutbox) == 1 and mailoutbox[0].to == ["reader@example.com"]
    with django_capture_on_commit_callbacks(execute=True):
        client.post(url, {"email": "reader@example.com"}, content_type="application/json")
    assert len(mailoutbox) == 1  # not again within the hour
    assert client.post(url, {"email": "not an address"}, content_type="application/json").status_code == 422

    token = link(mailoutbox[0].body, "/subscriptions/confirm/")
    assert client.get(f"{URL}/subscriptions/confirm/", {"token": token + "x"}).status_code == 422
    confirmed = client.get(f"{URL}/subscriptions/confirm/", {"token": token})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    with django_capture_on_commit_callbacks(execute=True):
        client.post(url, {"email": "reader@example.com"}, content_type="application/json")
    assert len(mailoutbox) == 1 and Subscriber.objects.get().status == "confirmed"


@pytest.mark.django_db
def test_an_issue_is_assembled_previewed_and_sent_once_to_confirmed_subscribers(
    api, desk, site, ed, reporter, advance, mailoutbox, django_capture_on_commit_callbacks
):
    newsletter = Newsletter.objects.create(site=site, name="Morning Brief", slug="morning")
    confirmed = Subscriber.objects.create(newsletter=newsletter, email="yes@example.com", status="confirmed")
    Subscriber.objects.create(newsletter=newsletter, email="maybe@example.com", status="pending")
    out = advance(desk, S.PUBLISHED, headline="Bridge reopens", summary="After six weeks.")
    draft = advance(desk, S.DRAFTING, headline="Not yet")
    made = api(ed).post(
        f"{URL}/issues/",
        {
            "newsletter": str(newsletter.public_id),
            "subject": "Monday",
            "intro": "Good morning.",
            "story_ids": [str(draft.public_id), str(out.public_id)],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    issue = Issue.objects.get(public_id=made.json()["id"])
    assert [s["headline"] for s in made.json()["stories"]] == ["Not yet", "Bridge reopens"]
    send = f"{URL}/issues/{issue.public_id}/send/"
    assert api(ed).post(send).status_code == 409  # a story in it is not published
    api(ed).patch(f"{URL}/issues/{issue.public_id}/", {"story_ids": [str(out.public_id)]}, format="json")

    preview = api(ed).get(f"{URL}/issues/{issue.public_id}/preview/").json()
    assert (
        preview["subject"] == "Monday" and "Bridge reopens" in preview["text"] and "After six weeks." in preview["text"]
    )
    assert "<h3>" in preview["html"] and "Good morning." in preview["html"]
    assert api(reporter).post(send).status_code == 403  # only the site's desk editors send

    with django_capture_on_commit_callbacks(execute=True):
        sent = api(ed).post(send)
    assert sent.status_code == 202 and sent.json()["status"] == "sending"
    issue.refresh_from_db()
    assert (issue.status, issue.recipients) == ("sent", 1) and issue.sent_at is not None
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.to == [confirmed.email] and message.subject == "Monday"
    assert message.tags == ["newsletter", "morning"] and message.metadata == {"issue": str(issue.public_id)}
    assert message.alternatives[0][1] == "text/html"
    unsubscribe = message.extra_headers["List-Unsubscribe"].strip("<>")
    assert message.extra_headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert api(ed).post(send).status_code == 409  # never twice
    assert api(ed).patch(f"{URL}/issues/{issue.public_id}/", {"subject": "Changed"}, format="json").status_code == 409

    token = parse_qs(urlparse(unsubscribe).query)["token"][0]
    gone = api().post(
        f"{URL}/subscriptions/unsubscribe/?token={token}",
        "List-Unsubscribe=One-Click",
        content_type="application/x-www-form-urlencoded",
    )
    assert gone.status_code == 200 and gone.json()["status"] == "unsubscribed"


@pytest.mark.django_db
def test_an_issue_with_no_confirmed_subscribers_or_stories_is_not_sent(desk, site, ed, advance):
    newsletter = Newsletter.objects.create(site=site, name="Brief", slug="brief")
    issue = Issue.objects.create(newsletter=newsletter, subject="Empty")
    with pytest.raises(services.Invalid):
        services.send_issue(issue, user=ed)
    services.set_issue_stories(issue, [advance(desk, S.PUBLISHED)])
    with pytest.raises(services.Conflict, match="nobody has confirmed"):
        services.send_issue(issue, user=ed)


@pytest.mark.django_db
def test_a_confirmation_link_expires_and_does_only_what_it_says(site):
    newsletter = Newsletter.objects.create(site=site, name="Brief", slug="brief")
    subscriber = Subscriber.objects.create(newsletter=newsletter, email="late@example.com")

    def token(action, made_at=None):
        with mock.patch("django.core.signing.time.time", return_value=(made_at or timezone.now()).timestamp()):
            return parse_qs(urlparse(services.subscription_link(subscriber, action)).query)["token"][0]

    with pytest.raises(services.Invalid, match="expired"):
        services.confirm(token("confirm", timezone.now() - timedelta(days=8)))
    with pytest.raises(services.Invalid):
        services.unsubscribe(token("confirm"))  # a confirm link does not unsubscribe
    assert services.confirm(token("confirm")).status == "confirmed"
    assert services.unsubscribe(token("unsubscribe", timezone.now() - timedelta(days=400))).status == "unsubscribed"
