"""The newsroom's email, sent by the worker and never inside a request.

Mail goes through Django's mail API to `EMAIL_BACKEND`: one of django-anymail's
ESP backends in production (Amazon SES, Mailgun, Postmark …, configured from
`ANYMAIL_*` variables), the console in development, locmem in tests. Each message
is an `AnymailMessage`, so an ESP sees its tags and metadata; every newsletter
carries its subscriber's own unsubscribe link and the one-click
`List-Unsubscribe` headers. A send that fails marks the issue failed, to be
sent again; the details stay in the worker's log, not on the issue.
"""

import logging

from anymail.message import AnymailMessage
from celery import shared_task
from django.core.mail import get_connection
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Issue, Subscriber
from .services import issue_items, render_issue, subscription_link

log = logging.getLogger(__name__)


def newsletter_message(issue, subscriber, items=None) -> AnymailMessage:
    unsubscribe = subscription_link(subscriber, "unsubscribe")
    content = render_issue(issue, unsubscribe_url=unsubscribe, items=items)
    message = AnymailMessage(
        subject=content["subject"],
        body=content["text"],
        from_email=issue.newsletter.from_email or None,
        to=[subscriber.email],
        tags=["newsletter", issue.newsletter.slug],
        metadata={"issue": str(issue.public_id)},
        headers={"List-Unsubscribe": f"<{unsubscribe}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
    )
    message.attach_alternative(content["html"], "text/html")
    return message


@shared_task
def send_issue(issue_id: int) -> int:
    issue = Issue.objects.select_related("newsletter").get(pk=issue_id)
    if issue.status != Issue.Status.SENDING:
        return 0
    try:
        items = issue_items(issue)
        confirmed = issue.newsletter.subscribers.filter(status=Subscriber.Status.CONFIRMED)
        sent = get_connection().send_messages([newsletter_message(issue, s, items) for s in confirmed]) or 0
    except Exception as e:  # noqa: BLE001 — any ESP failure fails the issue, which can be sent again
        log.exception("newsletter issue %s failed to send", issue.public_id)
        Issue.objects.filter(pk=issue.pk).update(
            status=Issue.Status.FAILED, error=f"the mail backend refused the send ({type(e).__name__})"
        )
        return 0
    Issue.objects.filter(pk=issue.pk).update(status=Issue.Status.SENT, recipients=sent, sent_at=timezone.now())
    return sent


@shared_task
def send_confirmation(subscriber_id: int) -> None:
    subscriber = Subscriber.objects.select_related("newsletter").get(pk=subscriber_id)
    context = {"newsletter": subscriber.newsletter, "confirm_url": subscription_link(subscriber, "confirm")}
    AnymailMessage(
        subject=f"Confirm your subscription to {subscriber.newsletter.name}",
        body=render_to_string("newsroom/confirm.txt", context),
        from_email=subscriber.newsletter.from_email or None,
        to=[subscriber.email],
        tags=["newsletter-confirmation"],
    ).send()
