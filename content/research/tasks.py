"""The research library's Celery tasks: a captured page fetched, a source's
vector stored, and the feeds refreshed — on Celery beat
(`CELERY_BEAT_SCHEDULE["research-feeds"]`), which claims each due subscription
and reads it in a task of its own, or one on request. A feed is claimed by
moving its next check on before it is read, so one bad or slow feed never holds
back the rest and a later tick never reads it a second time. The two tasks that
wait on other servers run on the `research` queue (`CELERY_TASK_ROUTES`) under
a time limit, so they never hold the workers that run agents and publish."""

from celery import shared_task
from django.conf import settings

from .models import FeedSubscription, Source
from .services import claim, due_feeds, embed, fetch_into, refresh

# A fetch is stopped once it has run this long, whatever it waits on (CELERY_TASK_ROUTES gives it its own queue).
LIMITS = {"soft_time_limit": settings.RESEARCH_TASK_TIME_LIMIT, "time_limit": settings.RESEARCH_TASK_TIME_LIMIT + 30}


@shared_task(**LIMITS)
def fetch_source(pk: int) -> str:
    source = Source.objects.filter(pk=pk, kind=Source.URL).first()
    fetched = fetch_into(source) if source is not None else None
    return fetched.status if fetched is not None else "gone"


@shared_task
def embed_source(pk: int) -> bool:
    source = Source.objects.filter(pk=pk).first()
    return embed(source) if source is not None else False


@shared_task(**LIMITS)
def refresh_feed(pk: int) -> int:
    feed = FeedSubscription.objects.filter(pk=pk).first()
    return refresh(feed) if feed is not None else 0


@shared_task
def refresh_feeds() -> int:
    """Claim every active subscription that is due and queue its read; returns how many were queued."""
    claimed = [pk for pk in due_feeds().values_list("pk", flat=True) if claim(pk)]
    for pk in claimed:
        refresh_feed.delay(pk)
    return len(claimed)
