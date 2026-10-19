"""Handlers for the Rails plane's events (outbox/consumers.py dedupes them).

`app.user.interaction` adds one to the page's count for the day and to every
co-viewed pair's count. The reader's `anon_id` is read nowhere and stored
nowhere: only the aggregate crosses into this plane (note §5).
"""

from django.db.models import F
from django.utils import timezone
from wagtail.models import Page

from outbox.consumers import handler

from .models import CoViewCount, InteractionCount


@handler("app.user.interaction", consumer="graph.interactions")
def count_interaction(envelope: dict):
    data = envelope["data"]
    day = timezone.now().date()
    page_ids = {data["page_id"], *data.get("session_page_ids", [])}
    existing = set(Page.objects.filter(pk__in=page_ids).values_list("pk", flat=True))
    if data["page_id"] not in existing:
        return
    row, _ = InteractionCount.objects.get_or_create(page_id=data["page_id"], kind=data["kind"], day=day)
    InteractionCount.objects.filter(pk=row.pk).update(count=F("count") + 1)
    if data["kind"] != "view":
        return
    for other in sorted(existing - {data["page_id"]}):
        a, b = sorted((data["page_id"], other))
        pair, _ = CoViewCount.objects.get_or_create(page_a_id=a, page_b_id=b, day=day)
        CoViewCount.objects.filter(pk=pair.pk).update(count=F("count") + 1)
