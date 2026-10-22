"""The newsroom's email, sent by the worker and never inside a request.

Mail goes through Django's mail API to `EMAIL_BACKEND`: one of django-anymail's
ESP backends in production (Amazon SES, Mailgun, Postmark …, configured from
`ANYMAIL_*` variables), the console in development, locmem in tests. Each message
is an `AnymailMessage`, so an ESP sees its tags and metadata; every newsletter
carries its subscriber's own unsubscribe link and the one-click
`List-Unsubscribe` headers.

An issue is sent once to each subscriber: one worker at a time holds it (a lock
in the shared cache, as `cms.tasks.publish_scheduled` does), and each message the
backend accepts is recorded (`IssueDelivery`) before the next is sent. A send
that fails part way marks the issue failed, to be sent again to the rest; a
worker that dies, or a task the broker delivers twice, resumes with the
subscribers who have not had it. The details of a failure stay in the worker's
log, not on the issue.
"""

import logging

from anymail.message import AnymailMessage
from celery import shared_task
from django.core.cache import cache
from django.core.mail import get_connection
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Issue, IssueDelivery, Subscriber
from .services import issue_items, render_issue, sending, subscription_link

log = logging.getLogger(__name__)
LEASE = 3600  # seconds a worker holds an issue without sending a message, before another may take it over


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
    """Send an issue to its confirmed subscribers who have not had it; returns how many it sent now."""
    lock = sending(issue_id)
    if not cache.add(lock, True, timeout=LEASE):
        return 0  # another worker is sending it
    try:
        issue = Issue.objects.select_related("newsletter").get(pk=issue_id)
        if issue.status != Issue.Status.SENDING:
            return 0
        confirmed = issue.newsletter.subscribers.filter(status=Subscriber.Status.CONFIRMED)
        waiting = confirmed.exclude(pk__in=issue.deliveries.values("subscriber"))
        sent = 0
        try:
            items = issue_items(issue)
            with get_connection() as connection:
                for subscriber in list(waiting):
                    message = newsletter_message(issue, subscriber, items)
                    if connection.send_messages([message]) != 1:
                        raise RuntimeError("the mail backend did not send the message")
                    IssueDelivery.objects.create(
                        issue=issue, subscriber=subscriber, message_id=message.anymail_status.message_id or ""
                    )
                    sent += 1
                    cache.touch(lock, LEASE)
        except Exception as e:  # noqa: BLE001 — any ESP failure fails the issue, which is sent again to the rest
            log.exception("newsletter issue %s failed to send", issue.public_id)
            had, left = issue.deliveries.count(), waiting.all().count()  # .all(): not the list sent from
            Issue.objects.filter(pk=issue.pk).update(
                status=Issue.Status.FAILED,
                recipients=had,
                error=f"sent to {had} of {had + left}; the mail backend refused the rest "
                f"({type(e).__name__}) — send it again for them",
            )
            return sent
        Issue.objects.filter(pk=issue.pk).update(
            status=Issue.Status.SENT, recipients=issue.deliveries.count(), sent_at=timezone.now(), error=""
        )
        return sent
    finally:
        cache.delete(lock)


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
