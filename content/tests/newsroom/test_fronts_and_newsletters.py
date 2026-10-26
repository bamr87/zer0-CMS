"""Fronts and newsletters (PLAN G15). A front's slots resolve to stories as a
reader would find them — a pinned story while it is live, else the next latest
published story of a desk, never twice. A newsletter subscription is confirmed
by an emailed link before anything is sent (double opt-in): the link opens a
page that changes nothing until its button is pressed, and a link stops working
once the address unsubscribes. An issue assembled from published stories is
previewed, then sent by the worker through Django's mail API (locmem here; an
anymail ESP in production) to confirmed subscribers only, each with their own
unsubscribe link — once each, even when a send fails part way or its task runs
twice. Production never mails to the console by default."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from smtplib import SMTPDataError
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.mail.backends import locmem
from django.utils import timezone

from newsroom import services, tasks
from newsroom.models import Front, Issue, Newsletter, Story, Subscriber

S = Story.Status
URL = "/api/v2/newsroom"


def link(text, path):
    """The link to `path` in an email's text, without its host."""
    url = urlparse(next(word for word in text.split() if path in word))
    return f"{url.path}?{url.query}"


def token(url):
    return parse_qs(urlparse(url).query)["token"][0]


class Throttled(locmem.EmailBackend):
    """Django's test backend, refusing every message after the first `limit`, as an ESP throttling a send does."""

    limit = 1

    def send_messages(self, messages):
        if len(mail.outbox) >= self.limit:
            raise SMTPDataError(454, b"throttled")
        return super().send_messages(messages)


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

    confirm = link(mailoutbox[0].body, "/newsletters/confirm/")
    page = client.get(confirm)  # what a mail scanner, a prefetcher or a person opening the link fetches
    assert page.status_code == 200 and page["Content-Type"].startswith("text/html")
    assert b"Confirm the subscription" in page.content and b'method="post"' in page.content
    assert Subscriber.objects.get().status == "pending"  # opening the link changes nothing
    assert client.get(confirm + "x").status_code == 422
    done = client.post(confirm)  # the page's button
    assert done.status_code == 200 and b"You are subscribed" in done.content
    assert Subscriber.objects.get().status == "confirmed"
    with django_capture_on_commit_callbacks(execute=True):
        client.post(url, {"email": "reader@example.com"}, content_type="application/json")
    assert len(mailoutbox) == 1 and Subscriber.objects.get().status == "confirmed"
    assert client.get(f"{URL}/subscriptions/confirm/", {"token": token(confirm)}).status_code == 405  # POST only


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

    assert urlparse(unsubscribe).path == "/newsletters/unsubscribe/"
    gone = api().post(  # a mail client's one-click unsubscribe (RFC 8058): no session, no CSRF token
        f"{urlparse(unsubscribe).path}?{urlparse(unsubscribe).query}",
        "List-Unsubscribe=One-Click",
        content_type="application/x-www-form-urlencoded",
    )
    assert gone.status_code == 200 and Subscriber.objects.get(pk=confirmed.pk).status == "unsubscribed"


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
    old_link = token("confirm")
    assert services.confirm(old_link).status == "confirmed"
    assert services.unsubscribe(token("unsubscribe", timezone.now() - timedelta(days=400))).status == "unsubscribed"
    with pytest.raises(services.Invalid, match="no longer valid"):
        services.confirm(old_link)  # a confirm link still in the mailbox does not subscribe the address again
    assert Subscriber.objects.get(pk=subscriber.pk).status == "unsubscribed"


@pytest.mark.django_db
def test_a_send_that_fails_part_way_is_sent_again_to_the_rest_only(
    api, desk, site, ed, advance, settings, mailoutbox, django_capture_on_commit_callbacks
):
    settings.EMAIL_BACKEND = f"{__name__}.Throttled"
    newsletter = Newsletter.objects.create(site=site, name="Brief", slug="brief")
    for name in ("ann", "bo", "cy"):
        Subscriber.objects.create(newsletter=newsletter, email=f"{name}@example.com", status="confirmed")
    issue = Issue.objects.create(newsletter=newsletter, subject="Monday")
    services.set_issue_stories(issue, [advance(desk, S.PUBLISHED)])
    send = f"{URL}/issues/{issue.public_id}/send/"

    with django_capture_on_commit_callbacks(execute=True):
        assert api(ed).post(send).status_code == 202
    issue.refresh_from_db()
    assert (issue.status, issue.recipients, len(mailoutbox)) == ("failed", 1, 1)
    assert issue.error.startswith("sent to 1 of 3")

    Throttled.limit = 99
    try:
        with django_capture_on_commit_callbacks(execute=True):
            assert api(ed).post(send).status_code == 202
        issue.refresh_from_db()
        assert (issue.status, issue.recipients) == ("sent", 3)
        assert sorted(m.to[0] for m in mailoutbox) == ["ann@example.com", "bo@example.com", "cy@example.com"]
        assert tasks.send_issue(issue.pk) == 0  # the broker delivers the task again: nobody gets it twice
        assert len(mailoutbox) == 3
    finally:
        Throttled.limit = 1


@pytest.mark.django_db
def test_an_issue_a_worker_left_sending_resumes_and_one_being_sent_is_not_sent_again(
    api, desk, site, ed, advance, mailoutbox, django_capture_on_commit_callbacks
):
    newsletter = Newsletter.objects.create(site=site, name="Brief", slug="brief")
    had = Subscriber.objects.create(newsletter=newsletter, email="had@example.com", status="confirmed")
    Subscriber.objects.create(newsletter=newsletter, email="next@example.com", status="confirmed")
    issue = Issue.objects.create(newsletter=newsletter, subject="Monday", status=Issue.Status.SENDING)
    services.set_issue_stories(issue, [advance(desk, S.PUBLISHED)])
    issue.deliveries.create(subscriber=had)  # the worker died after the first message
    send = f"{URL}/issues/{issue.public_id}/send/"

    cache.add(services.sending(issue.pk), True)  # while a worker holds it …
    try:
        assert api(ed).post(send).status_code == 409
        assert tasks.send_issue(issue.pk) == 0  # … a second delivery of the task sends nothing
    finally:
        cache.delete(services.sending(issue.pk))
    with django_capture_on_commit_callbacks(execute=True):
        assert api(ed).post(send).status_code == 202  # nobody holds it: resume
    issue.refresh_from_db()
    assert (issue.status, issue.recipients) == ("sent", 2) and [m.to for m in mailoutbox] == [["next@example.com"]]


@pytest.mark.django_db
def test_an_issue_is_sent_only_with_its_own_sites_stories(desk, site, advance):
    from wagtail.models import Site

    from .conftest import person

    newsletter = Newsletter.objects.create(site=site, name="Brief", slug="brief")
    Subscriber.objects.create(newsletter=newsletter, email="a@example.com", status="confirmed")
    issue = Issue.objects.create(newsletter=newsletter, subject="Monday")
    services.set_issue_stories(issue, [advance(desk, S.PUBLISHED)])
    other = Site.objects.create(hostname="other.localhost", root_page=desk.section)
    type(desk).objects.filter(pk=desk.pk).update(site=other)  # its desk moved to another site since
    with pytest.raises(services.Conflict, match="its newsletter's site"):
        services.send_issue(issue, user=person("staffer", is_staff=True))


def test_production_never_mails_to_the_console_by_default():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EMAIL_", "DJANGO_"))}
    env |= {"DJANGO_SETTINGS_MODULE": "config.settings.production", "SECRET_KEY": "check"}
    code = "import django; django.setup(); from django.conf import settings; print(settings.EMAIL_BACKEND)"
    content = Path(__file__).resolve().parents[2]
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=content, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "django.core.mail.backends.smtp.EmailBackend"
