"""Distribution's work on the worker, never inside a request: publishing a
post (`services.deliver`: the gates again, the channel's transport, the
ledger), exchanging an OAuth code, checking a channel's credential, and — on
Celery beat, once a day — the statistics of every LinkedIn channel's posts.
"""

import logging

from celery import shared_task

from .linkedin import Error as LinkedInError
from .models import Channel, Kind

log = logging.getLogger(__name__)

# A send never outlives this, so `services.deliver` reads an older claim as a worker that died mid-send.
SEND_TIME_LIMIT = 600


@shared_task(time_limit=SEND_TIME_LIMIT)
def publish_post(post_id: int) -> str:
    from .services import deliver

    return deliver(post_id).status


@shared_task
def exchange_code(channel_id: int) -> None:
    from .services import exchange

    exchange(Channel.objects.get(pk=channel_id))


@shared_task
def check_channel(channel_id: int) -> None:
    from .services import check

    check(Channel.objects.get(pk=channel_id))


@shared_task
def ingest_statistics(channel_id: int | None = None) -> int:
    """One channel's statistics, or — from beat — every connected LinkedIn channel's; a channel LinkedIn refuses
    is recorded on the channel and the rest still run."""
    from .services import ingest_statistics as ingest

    channels = Channel.objects.filter(kind=Kind.LINKEDIN)
    if channel_id is not None:
        channels = channels.filter(pk=channel_id)
    total = 0
    for channel in channels:
        try:
            total += ingest(channel)
        except LinkedInError as e:
            log.warning("distribution: statistics for channel %s failed: %s", channel.public_id, e)
            Channel.objects.filter(pk=channel.pk).update(last_error=f"statistics: {e}"[:1000])
    return total
