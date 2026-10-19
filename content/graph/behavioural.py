"""The nightly job that turns co-view counts into `viewed_together` edges.

Pairs read together in the last `days` days become (or refresh) an edge each
way with `source="rails"` and a weight that is the pair's share of the
busiest pair's count; pairs below `min_count` are left out, and edges for
pairs that fell out of the window are closed (`valid_to`), not deleted.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from wagtail.models import Page

from .models import CoViewCount, Edge
from .services import _ct, _edge


@transaction.atomic
def build_viewed_together(days: int = 30, min_count: int = 2) -> int:
    since = timezone.now().date() - timedelta(days=days)
    totals = (
        CoViewCount.objects.filter(day__gte=since)
        .values("page_a_id", "page_b_id")
        .annotate(n=Sum("count"))
        .filter(n__gte=min_count)
    )
    totals = list(totals)
    busiest = max((t["n"] for t in totals), default=0)
    pages = {
        p.pk: p for p in Page.objects.filter(pk__in={t["page_a_id"] for t in totals} | {t["page_b_id"] for t in totals})
    }
    kept = set()
    for t in totals:
        a, b = pages.get(t["page_a_id"]), pages.get(t["page_b_id"])
        if a is None or b is None:
            continue
        weight = round(t["n"] / busiest, 6) if busiest else 0.0
        for src, dst in ((a, b), (b, a)):
            edge = _edge(src, "viewed_together", dst, source="rails", weight=weight)
            kept.add(edge.pk)
    page_ct = _ct(Page())
    Edge.objects.filter(rel="viewed_together", source="rails", src_ct=page_ct, valid_to__isnull=True).exclude(
        pk__in=kept
    ).update(valid_to=timezone.now())
    return len(kept)
