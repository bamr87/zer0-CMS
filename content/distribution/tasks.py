"""Distribution's work on the worker, never inside a request: publishing a
post (`services.deliver`: the gates again, the channel's transport, the
ledger), exchanging an OAuth code, checking a channel's credential, giving a
disconnected X channel's grant back to X, and — on
Celery beat — releasing the scheduled posts whose time has come (each minute,
`services.release_due`), settling every attempt that is over without its worker saying so
(each minute: a send whose worker died, a post no worker took, an email post
whose newsletter issue the newsroom sent or failed) and the statistics of every
LinkedIn and X channel's posts (daily).
"""

import logging

from celery import shared_task

from .linkedin import Error as LinkedInError
from .models import Channel, Kind
from .x import Error as XError

log = logging.getLogger(__name__)

# A send never outlives this, so `services._settle` reads an older claim as a worker that died mid-send. A send
# still going a minute before is stopped from the inside (the soft limit) and fails as one whose outcome is unknown,
# rather than being killed.
SEND_TIME_LIMIT = 600


@shared_task(time_limit=SEND_TIME_LIMIT, soft_time_limit=SEND_TIME_LIMIT - 60)
def publish_post(post_id: int) -> str:
    from .services import deliver

    return deliver(post_id).status


@shared_task
def release_posts() -> int:
    from .services import release_due

    return release_due()


@shared_task
def settle_posts() -> int:
    from .services import settle_due

    return settle_due()


@shared_task
def exchange_code(channel_id: int) -> None:
    from .services import exchange

    exchange(Channel.objects.get(pk=channel_id))


@shared_task
def check_channel(channel_id: int) -> None:
    from .services import check

    check(Channel.objects.get(pk=channel_id))


@shared_task
def revoke_x_grant(sealed: str) -> bool:
    from .services import revoke_x

    return revoke_x(sealed)


@shared_task
def ingest_statistics(channel_id: int | None = None) -> int:
    """One channel's statistics, or — from beat — every connected LinkedIn and X channel's; a channel its target
    refuses is recorded on the channel and the rest still run."""
    from .services import ingest_statistics as ingest

    channels = Channel.objects.filter(kind__in=(Kind.LINKEDIN, Kind.X))
    if channel_id is not None:
        channels = channels.filter(pk=channel_id)
    total = 0
    for channel in channels:
        try:
            total += ingest(channel)
        except (LinkedInError, XError) as e:
            log.warning("distribution: statistics for channel %s failed: %s", channel.public_id, e)
            Channel.objects.filter(pk=channel.pk).update(last_error=f"statistics: {e}"[:1000])
    return total
