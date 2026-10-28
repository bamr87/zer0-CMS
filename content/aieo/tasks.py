"""AIEO's Celery tasks: a connector's sync, in a worker (the vendor's API is never called inside a request), and the
tracked citation questions that are due — on Celery beat (`CELERY_BEAT_SCHEDULE["aieo-citations"]`), which claims
each due question before it is asked, so a later tick never asks it twice, and starts one run per engine as the
question's owner (`trigger` schedule)."""

import logging

import httpx
from celery import shared_task
from django.utils import timezone

from ai import crypto

from . import connectors, services
from .models import CitationQuery, Connector

log = logging.getLogger(__name__)


@shared_task(soft_time_limit=120, time_limit=150)
def sync_connector(pk: int) -> str:
    connector = Connector.objects.filter(pk=pk).first()
    if connector is None:
        return "gone"
    outcome = {"status": Connector.OK, "error": "", "last_synced_at": timezone.now()}
    try:
        connectors.fetch_rows(connector)
    except connectors.ConnectorError as e:
        outcome = {"status": Connector.FAILED, "error": str(e)}
    except crypto.InvalidToken:
        outcome = {
            "status": Connector.FAILED,
            "error": "the credential was encrypted with a key that is gone: set it again",
        }
    except httpx.HTTPError as e:
        outcome = {"status": Connector.FAILED, "error": f"the service could not be reached: {type(e).__name__}"}
    except Exception as e:  # noqa: BLE001 — a failed sync is recorded on the connector, never left syncing
        log.exception("syncing connector %s failed", pk)
        outcome = {"status": Connector.FAILED, "error": f"the sync failed: {type(e).__name__}"}
    Connector.objects.filter(pk=pk).update(**outcome, updated_at=timezone.now())
    return outcome["status"]


@shared_task
def check_citations() -> int:
    """Ask every due, active question again; returns how many were asked."""
    asked = 0
    for pk in list(services.due_queries().values_list("pk", flat=True)):
        if not services.claim(pk):
            continue
        query = CitationQuery.objects.select_related("owner").get(pk=pk)
        if query.owner is None or not query.owner.is_active:
            continue
        try:
            services.check_citations(query, user=query.owner, trigger="schedule")
            asked += 1
        except Exception:  # noqa: BLE001 — one question that cannot be asked (a provider off, a budget spent) never stops the rest
            log.exception("checking citation query %s failed", pk)
    return asked
