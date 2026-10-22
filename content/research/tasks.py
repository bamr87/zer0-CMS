"""The research library's Celery tasks: a captured page fetched, a source's
vector stored, and the feeds refreshed — every due subscription on Celery beat
(`CELERY_BEAT_SCHEDULE["research-feeds"]`) or one on request, each in its own
transaction so one bad feed never holds back the rest."""

import logging

from celery import shared_task
from django.db import transaction

from .models import FeedSubscription, Source
from .services import due_feeds, embed, fetch_into, refresh

log = logging.getLogger(__name__)


@shared_task
def fetch_source(pk: int) -> str:
    source = Source.objects.filter(pk=pk, kind=Source.URL).first()
    return fetch_into(source).status if source is not None else "gone"


@shared_task
def embed_source(pk: int) -> bool:
    source = Source.objects.filter(pk=pk).first()
    return embed(source) if source is not None else False


@shared_task
def refresh_feed(pk: int) -> int:
    feed = FeedSubscription.objects.filter(pk=pk).first()
    return refresh(feed) if feed is not None else 0


@shared_task
def refresh_feeds() -> int:
    """Every active subscription that is due; returns how many new items arrived."""
    new = 0
    for feed in list(due_feeds()):
        try:
            with transaction.atomic():
                new += refresh(feed)
        except Exception:  # noqa: BLE001 — one feed's failure is logged and retried on schedule, never fatal to the rest
            log.exception("refreshing feed %s failed; it is tried again on schedule", feed.pk)
    return new
